"""Celery application transporting consensus commands to resolver workers."""

from celery import Celery

from dada_api.consensus import protocol
from dada_api.core.config import get_settings
from dada_api.models.resolution import ResolutionRun

RESOLVE_TASK = "consensus.resolve"

app = Celery(
    "dada",
    broker=get_settings().redis_url,
    include=["dada_api.workers.consensus"],
)
app.conf.update(
    task_default_queue="consensus.standard",
    task_acks_late=False,
    task_ignore_result=True,
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
