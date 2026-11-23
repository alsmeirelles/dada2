"""Celery application transporting consensus and learning commands to workers."""

from celery import Celery

from dada_api.consensus import protocol
from dada_api.core.config import get_settings
from dada_api.models.learning import LearningRun
from dada_api.models.resolution import ResolutionRun
from dada_api.services.learning_runs import QUEUE as LEARNING_QUEUE
from dada_api.services.learning_runs import Command as LearningCommand

RESOLVE_TASK = "consensus.resolve"
LEARNING_TASK = "learning.select"

app = Celery(
    "dada",
    broker=get_settings().redis_url,
    include=["dada_api.workers.consensus", "dada_api.workers.learning"],
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
