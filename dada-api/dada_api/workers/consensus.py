"""Celery task that executes one attempt of a resolver run."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dada_api.consensus import pipeline, protocol
from dada_api.core.config import get_settings
from dada_api.services import resolution_runs
from dada_api.workers.celery_app import RESOLVE_TASK, app

logger = logging.getLogger(__name__)


def _now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(UTC)


def _result(
    command: protocol.Command, started_at: datetime, **fields: object
) -> protocol.Result:
    """Build the result envelope of one attempt."""
    return protocol.Result(
        run_id=command.run_id,
        attempt=command.attempt,
        configuration_fingerprint=command.configuration_fingerprint,
        input_fingerprint=command.input_fingerprint,
        started_at=started_at,
        finished_at=_now(),
        **fields,
    )


async def execute(
    command: protocol.Command,
    session_factory: async_sessionmaker,
    run_pipeline: Callable[
        [protocol.ResolverInput], protocol.PipelineOutput
    ] = pipeline.run,
) -> None:
    """Run one attempt: claim it, resolve it, and ingest the result.

    Database errors propagate so the attempt stays unanswered and the relay
    retries it; resolver failures are recorded as typed permanent failures.

    Args:
        command: Broker command of the attempt.
        session_factory: Session factory bound to the worker's engine.
        run_pipeline: Pipeline entry point, replaceable by a deterministic
            fake in tests.
    """
    async with session_factory() as session:
        resolver_input = await resolution_runs.start_attempt(session, command, _now())
    if resolver_input is None:
        return

    started_at = _now()
    try:
        output = run_pipeline(resolver_input)
        result = _result(
            command,
            started_at,
            outcome="proposal",
            output=output,
            output_checksum=protocol.fingerprint(output.model_dump(mode="json")),
        )
    except protocol.PipelineError as error:
        result = _result(
            command,
            started_at,
            outcome="failed",
            failure_code=error.code,
            failure_detail=error.detail,
        )
    except SoftTimeLimitExceeded:
        result = _result(
            command,
            started_at,
            outcome="failed",
            failure_code="resource_limit",
            failure_detail="the soft time limit was reached",
        )
    except Exception:
        logger.error(
            "resolver run %s failed unexpectedly", command.run_id, exc_info=True
        )
        result = _result(
            command,
            started_at,
            outcome="failed",
            failure_code="resolver_output_invalid",
            failure_detail="the resolver raised an unexpected error",
        )

    async with session_factory() as session:
        await resolution_runs.ingest(session, result, _now())


async def _execute_with_own_engine(command: protocol.Command) -> None:
    """Execute an attempt on an engine owned by this task's event loop."""
    engine = create_async_engine(
        get_settings().sqlalchemy_database_url(), poolclass=NullPool
    )
    try:
        await execute(
            command,
            async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False),
        )
    finally:
        await engine.dispose()


@app.task(name=RESOLVE_TASK)
def resolve(command: dict) -> None:
    """Celery entry point of ``consensus.resolve``.

    Args:
        command: Serialized :class:`dada_api.consensus.protocol.Command`.
    """
    asyncio.run(_execute_with_own_engine(protocol.Command.model_validate(command)))
