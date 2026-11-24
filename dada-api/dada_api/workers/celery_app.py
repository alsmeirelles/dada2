"""Celery application transporting consensus, learning, and assistance work."""

import asyncio

from celery import Celery
from celery.exceptions import TimeoutError as CeleryTimeoutError

from dada_api.active_learning.contract import AssistanceRequest
from dada_api.consensus import protocol
from dada_api.core.config import get_settings
from dada_api.models.learning import LearningRun
from dada_api.models.resolution import ResolutionRun
from dada_api.services.learning_runs import QUEUE as LEARNING_QUEUE
from dada_api.services.learning_runs import Command as LearningCommand

RESOLVE_TASK = "consensus.resolve"
LEARNING_TASK = "learning.select"
ASSISTANCE_TASK = "assistance.suggest"
ASSISTANCE_QUEUE = "assistance"

app = Celery(
    "dada",
    broker=get_settings().redis_url,
    backend=get_settings().redis_url,
    include=[
        "dada_api.workers.consensus",
        "dada_api.workers.learning",
        "dada_api.workers.assistance",
    ],
)
app.conf.update(
    task_default_queue="consensus.standard",
    task_acks_late=False,
    task_ignore_result=True,
    result_expires=300,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)


def send(command: protocol.Command, run: ResolutionRun) -> None:
    """Hand one attempt to its queue with the run's recorded time limits.

    PostgreSQL stays authoritative: the broker only carries the command, and
    a lost or repeated message is reconciled by the relay and the attempt
    check.

    Args:
        command: Identifiers and fingerprints of the attempt.
        run: Run being dispatched, for its queue and limits.
    """
    app.send_task(
        RESOLVE_TASK,
        args=[command.model_dump()],
        queue=run.queue,
        task_id=f"{run.id}:{command.attempt}",
        time_limit=run.effective_limits["hard_seconds"],
        soft_time_limit=run.effective_limits["soft_seconds"],
    )


def send_learning(command: LearningCommand, run: LearningRun) -> None:
    """Hand one learning attempt to the ``learning`` queue.

    The hard time limit is the run's timeout; a worker killed by it reports
    nothing, and the relay fails the run once the limit has passed.

    Args:
        command: Identifiers and fingerprint of the attempt.
        run: Run being dispatched.
    """
    app.send_task(
        LEARNING_TASK,
        args=[command.model_dump()],
        queue=LEARNING_QUEUE,
        task_id=f"{run.id}:{command.attempt}",
        time_limit=run.timeout_seconds,
    )


async def dispatch_assistance(request: AssistanceRequest, seconds: float) -> dict:
    """Send one prompt to the ``assistance`` queue and wait for its answer.

    Only this task keeps a result, in Redis and for a few minutes: the
    suggestion is shown once and never stored (D18).

    Args:
        request: The prompt and the retained model to use.
        seconds: How long to wait before giving up.

    Returns:
        The worker's raw answer.

    Raises:
        TimeoutError: When no answer arrives in time.
    """
    handle = app.send_task(
        ASSISTANCE_TASK,
        args=[request.model_dump()],
        queue=ASSISTANCE_QUEUE,
        expires=seconds,
    )
    try:
        return await asyncio.to_thread(handle.get, timeout=seconds)
    except CeleryTimeoutError as error:
        handle.forget()
        raise TimeoutError from error
