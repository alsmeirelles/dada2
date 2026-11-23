"""Celery task that executes one attempt of an active-learning run."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dada_api.active_learning import catalog
from dada_api.active_learning.contract import (
    AdapterError,
    BaseModelAdapter,
    BatchResult,
)
from dada_api.core.config import get_settings
from dada_api.services import learning_runs, storage
from dada_api.workers.celery_app import LEARNING_TASK, app

logger = logging.getLogger(__name__)
STAGE_TIMEOUT_SECONDS = 30


def _now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(UTC)


async def execute(
    command: learning_runs.Command,
    session_factory: async_sessionmaker,
    load_adapter: Callable[[str, str], BaseModelAdapter] = catalog.load_adapter,
) -> None:
    """Run one attempt: claim it, run the solution, and ingest the outcome.

    The solution runs in a thread so its progress callback can record the
    stage through this event loop. A typed solution failure is recorded as
    is; any other error becomes ``solution_failed``. After a success, the
    iteration's attempt folders are removed unless retention is enabled
    (D15).

    Args:
        command: Broker command of the attempt.
        session_factory: Session factory bound to the worker's engine.
        load_adapter: Adapter loader, replaceable in tests.
    """
    async with session_factory() as session:
        request = await learning_runs.start_attempt(session, command, _now())
    if request is None:
        return

    loop = asyncio.get_running_loop()

    async def record(stage: str) -> None:
        async with session_factory() as session:
            await learning_runs.record_stage(session, command, stage)

    def report(stage: str) -> None:
        asyncio.run_coroutine_threadsafe(record(stage), loop).result(
            STAGE_TIMEOUT_SECONDS
        )

    outcome: BatchResult | learning_runs.Failure
    try:
        adapter = load_adapter(request.solution_id, request.solution_version)
        outcome = await asyncio.to_thread(adapter.select_batch, request, report)
    except AdapterError as error:
        outcome = learning_runs.Failure(error.code, error.detail)
    except Exception:
        logger.error(
            "learning run %s failed unexpectedly", command.run_id, exc_info=True
        )
        outcome = learning_runs.Failure(
            "solution_failed", "the solution raised an unexpected error"
        )

    async with session_factory() as session:
        applied = await learning_runs.ingest(session, command, outcome, _now())
    if applied and not request.retain_helper_models:
        storage.delete_learning_folder(
            learning_runs.artifact_folder(request.project_id, request.iteration)
        )


async def _execute_with_own_engine(command: learning_runs.Command) -> None:
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


@app.task(name=LEARNING_TASK)
def select(command: dict) -> None:
    """Celery entry point of ``learning.select``.

    Args:
        command: Serialized :class:`dada_api.services.learning_runs.Command`.
    """
    asyncio.run(_execute_with_own_engine(learning_runs.Command.model_validate(command)))
