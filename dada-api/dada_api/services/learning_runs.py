"""The Phase 7 acquisition loop: opening iterations, worker attempts, result
ingestion, retries, and the iteration views built from them."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.active_learning import catalog
from dada_api.active_learning.contract import (
    MANIFEST_SCHEMA,
    PROTOCOL_VERSION,
    STAGES,
    AdapterError,
    BatchRequest,
    BatchResult,
    ClassEntry,
    EvaluationPlan,
    ManifestRef,
    read_manifest,
)
from dada_api.consensus.protocol import fingerprint
from dada_api.core.config import get_settings
from dada_api.core.cursors import decode_cursor, encode_cursor
from dada_api.core.errors import ApiError
from dada_api.models.batch import AnnotationBatch, BatchPurpose, BatchStatus
from dada_api.models.consensus import OutboxEvent
from dada_api.models.learning import (
    ACTIVE_LEARNING_RUN_STATUSES,
    BATCH_RESOLVED_EVENT,
    CompletionReason,
    LearningRun,
    LearningRunPurpose,
    LearningRunStatus,
    ModelEvaluation,
)
from dada_api.models.project import (
    AcquisitionStrategy,
    DatasetLayout,
    Project,
    ProjectClass,
)
from dada_api.models.user import User
from dada_api.schemas.learning import (
    EvaluationView,
    IterationPage,
    IterationResponse,
    StatisticsResponse,
)
from dada_api.services import (
    audit,
    batches,
    datasets,
    learning_snapshots,
    selection,
    storage,
)

QUEUE = "learning"
RELAY_BATCH = 50
PAGE_SIZE = 50
TIMEOUT_GRACE = timedelta(seconds=60)
FINISHED_BATCH_STATUSES = (BatchStatus.resolved, BatchStatus.closed, BatchStatus.failed)
ACTIVE_LEARNING_STRATEGY = "active_learning"
BATCH_STATES = {
    BatchStatus.preparing: "preparing",
    BatchStatus.annotating: "annotating",
    BatchStatus.resolving: "consolidating",
    BatchStatus.review_required: "consolidating",
    BatchStatus.resolved: "ready",
    BatchStatus.closed: "ready",
    BatchStatus.failed: "failed",
}


class Command(BaseModel):
    """What the broker transports: the run, its attempt, and its fingerprint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal["learning.v1"] = PROTOCOL_VERSION
    run_id: str
    attempt: int
    configuration_fingerprint: str


@dataclass(frozen=True)
class Failure:
    """A typed failure reported by the worker instead of a result."""

    code: str
    detail: str


Sender = Callable[[Command, LearningRun], None]


def command_for(run: LearningRun) -> Command:
    """Return the broker command of a run's current attempt."""
    return Command(
        run_id=run.id,
        attempt=run.attempt,
        configuration_fingerprint=run.configuration_fingerprint,
    )


def _audit(
    session: AsyncSession,
    run: LearningRun,
    action: str,
    actor: User | None = None,
    **after: Any,
) -> None:
    """Record a run lifecycle change; a None actor is the system."""
    audit.record(
        session,
        actor,
        run.project_id,
        action,
        "learning_run",
        run.id,
        after={"iteration": run.iteration, "attempt": run.attempt, **after},
    )


def _fail(
    session: AsyncSession, run: LearningRun, code: str, detail: str, now: datetime
) -> None:
    """Fail a run permanently; only a manager's retry continues the loop."""
    run.status = LearningRunStatus.failed
    run.finished_at = now
    run.stage = None
    run.failure_code = code
    run.failure_detail = detail[:500]
    _audit(session, run, "learning.run_failed", failure_code=code)


def _complete(
    session: AsyncSession,
    project: Project,
    reason: CompletionReason,
    actor: User | None = None,
) -> None:
    """Stop acquiring for good and record why."""
    project.status = "completed"
    project.completion_reason = reason
    audit.record(
        session,
        actor,
        project.id,
        "project.acquisition_completed",
        "project",
        project.id,
        after={"completion_reason": reason},
    )


def _solution_problem(run: LearningRun) -> str | None:
    """Explain why a run's exact solution version cannot run here."""
    solution = catalog.find(run.solution or "")
    if solution is None or solution.version != run.solution_version:
        return f"{run.solution}@{run.solution_version} is not registered"
    if catalog.unavailable_reason(solution) is not None:
        return f"{run.solution}@{run.solution_version} lacks dependencies"
    return None


async def _latest(session: AsyncSession, project_id: str) -> LearningRun | None:
    """Return the project's most recent run attempt."""
    return await session.scalar(
        select(LearningRun)
        .where(LearningRun.project_id == project_id)
        .order_by(LearningRun.iteration.desc(), LearningRun.attempt.desc())
        .limit(1)
    )


async def _acquisitions(
    session: AsyncSession, project_id: str
) -> list[AnnotationBatch]:
    """Return the project's acquisition batches in creation order."""
    return list(
        await session.scalars(
            select(AnnotationBatch)
            .where(
                AnnotationBatch.project_id == project_id,
                AnnotationBatch.purpose == BatchPurpose.acquisition,
            )
            .order_by(AnnotationBatch.created_at, AnnotationBatch.id)
        )
    )


async def advance(
    session: AsyncSession,
    project: Project,
    now: datetime,
    actor: User | None = None,
) -> LearningRun | None:
    """Open the next acquisition iteration when the loop is ready for it.

    Nothing happens unless the project is an active ``split`` project whose
    initial images are resolved, whose last acquisition batch is finished,
    and whose latest run succeeded. A random iteration is drawn and its batch
    opened at once; an active-learning iteration becomes a queued run. When
    the iteration limit is reached or the eligible pool is exhausted, random
    acquisition completes the project and active learning queues its final
    evaluation (D8).

    Args:
        session: Active database session; the caller commits.
        project: Project, locked by the caller.
        now: Server time.
        actor: User who asked, or None for the relay.

    Returns:
        The run created, or None when nothing was opened.
    """
    if project.dataset_layout != DatasetLayout.split or project.status != "active":
        return None
    if not await datasets.first_acquisition_ready(session, project):
        return None
    latest = await _latest(session, project.id)
    if latest is not None and (
        latest.status != LearningRunStatus.succeeded
        or latest.purpose == LearningRunPurpose.final_evaluation
    ):
        return None
    acquisitions = await _acquisitions(session, project.id)
    if acquisitions and acquisitions[-1].status not in FINISHED_BATCH_STATUSES:
        return None

    iteration = latest.iteration + 1 if latest is not None else 1
    reason: CompletionReason | None = None
    pool_ids: list[str] = []
    limit = project.max_acquisition_iterations
    if limit is not None and len(acquisitions) >= limit:
        reason = CompletionReason.max_iterations
    else:
        pool_ids = await datasets.eligible_training_pool(session, project)
        if not pool_ids or (latest is not None and latest.result.get("selected") == 0):
            reason = CompletionReason.pool_exhausted

    if project.acquisition_strategy == AcquisitionStrategy.random:
        if reason is not None:
            _complete(session, project, reason, actor)
            return None
        return await _random_run(session, project, iteration, pool_ids, now, actor)
    return await _queue_run(
        session,
        project,
        iteration,
        len(acquisitions),
        pool_ids,
        reason,
        now,
        actor,
    )


async def _random_run(
    session: AsyncSession,
    project: Project,
    iteration: int,
    pool_ids: list[str],
    now: datetime,
    actor: User | None,
) -> LearningRun:
    """Draw a random iteration and open its batch in the same transaction."""
    size = project.iteration_batch_size or 0
    seed = selection.new_seed()
    chosen = selection.choose_up_to(pool_ids, size, seed)
    run = LearningRun(
        project_id=project.id,
        iteration=iteration,
        attempt=1,
        purpose=LearningRunPurpose.selection,
        strategy=AcquisitionStrategy.random,
        configuration={},
        configuration_fingerprint=fingerprint({"strategy": "random"}),
        requested_size=size,
        seed=seed,
        snapshots={},
        status=LearningRunStatus.succeeded,
        timeout_seconds=get_settings().learning_timeout_seconds,
        started_at=now,
        finished_at=now,
        result={
            "selected": len(chosen),
            "shortfall_reason": (
                "insufficient_candidates" if len(chosen) < size else None
            ),
            "stop_reason": None,
        },
        requested_by=actor.id if actor is not None else None,
    )
    session.add(run)
    await session.flush()
    await batches.open_batch(
        session,
        project,
        BatchPurpose.acquisition,
        chosen,
        strategy=selection.RANDOM_STRATEGY,
        seed=seed,
        input_fingerprint=selection.fingerprint(pool_ids),
        requested_size=size,
        model_run_id=run.id,
    )
    _audit(session, run, "learning.run_succeeded", actor, selected=len(chosen))
    return run


async def _queue_run(
    session: AsyncSession,
    project: Project,
    iteration: int,
    completed: int,
    pool_ids: list[str],
    reason: CompletionReason | None,
    now: datetime,
    actor: User | None,
) -> LearningRun:
    """Snapshot the accepted data and queue an active-learning run.

    The target model is evaluated after every K completed acquisitions and
    always in the final run. The test split is attached only when the run may
    stop: when it is final or a metric target is set.
    """
    final = reason is not None
    interval = project.evaluation_interval or 1
    evaluate = final or (completed > 0 and completed % interval == 0)
    snapshots: dict[str, Any] = {
        "training": learning_snapshots.write(
            project.id,
            await learning_snapshots.accepted(session, project, "training"),
        ).model_dump()
    }
    if not final:
        snapshots["pool"] = learning_snapshots.write(
            project.id, await learning_snapshots.pool(session, project, pool_ids)
        ).model_dump()

    problem: tuple[str, str] | None = None
    plan: dict[str, Any] | None = None
    if evaluate:
        splits = ["validation"]
        if final or project.metric_target is not None:
            splits.append("test")
        for split in splits:
            manifest = await learning_snapshots.accepted(session, project, split)
            if not manifest["images"] and problem is None:
                problem = (
                    f"{split}_unavailable",
                    f"no {split} image has an accepted resolution",
                )
            snapshots[split] = learning_snapshots.write(
                project.id, manifest
            ).model_dump()
        plan = {
            "metric": project.evaluation_metric,
            "target": project.metric_target,
            "final": final,
            "reason": reason,
        }

    run = LearningRun(
        project_id=project.id,
        iteration=iteration,
        attempt=1,
        purpose=(
            LearningRunPurpose.final_evaluation
            if final
            else LearningRunPurpose.selection
        ),
        strategy=AcquisitionStrategy.active_learning,
        solution=project.learning_solution,
        solution_version=project.learning_solution_version,
        configuration=project.learning_configuration,
        configuration_fingerprint=fingerprint(
            {
                "solution": project.learning_solution,
                "version": project.learning_solution_version,
                "configuration": project.learning_configuration,
            }
        ),
        requested_size=0 if final else project.iteration_batch_size or 0,
        seed=selection.new_seed(),
        evaluation=plan,
        snapshots=snapshots,
        status=LearningRunStatus.queued,
        timeout_seconds=get_settings().learning_timeout_seconds,
        result={},
        requested_by=actor.id if actor is not None else None,
    )
    session.add(run)
    await session.flush()
    _audit(session, run, "learning.run_queued", actor, purpose=run.purpose)
    unavailable = _solution_problem(run)
    if problem is not None:
        _fail(session, run, *problem, now)
    elif unavailable is not None:
        _fail(session, run, "solution_unavailable", unavailable, now)
    return run


async def relay_once(session: AsyncSession, send: Sender, now: datetime) -> dict:
    """Run one pass of the learning side of the outbox relay.

    It opens iterations for resolved batches, fails runs that outlived their
    time limit, and sends queued runs to the broker.

    Args:
        session: Active database session.
        send: Callable that hands one command to the broker.
        now: Server time.

    Returns:
        Counts of opened, expired, and dispatched runs.
    """
    opened = await _consume_events(session, now)
    expired = await _expire(session, now)
    dispatched = await _dispatch(session, send, now)
    return {"opened": opened, "expired": expired, "dispatched": dispatched}


async def _consume_events(session: AsyncSession, now: datetime) -> int:
    """Turn unpublished batch-resolved events into opened iterations."""
    events = list(
        await session.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.event_type == BATCH_RESOLVED_EVENT,
                OutboxEvent.published_at.is_(None),
            )
            .order_by(OutboxEvent.occurred_at, OutboxEvent.id)
            .limit(RELAY_BATCH)
            .with_for_update(skip_locked=True)
        )
    )
    project_ids: list[str] = []
    for event in events:
        event.published_at = now
        if event.project_id not in project_ids:
            project_ids.append(event.project_id)
    opened = 0
    for project_id in project_ids:
        project = await session.get(Project, project_id, with_for_update=True)
        if project is not None and await advance(session, project, now) is not None:
            opened += 1
    await session.commit()
    return opened


async def _expire(session: AsyncSession, now: datetime) -> int:
    """Fail dispatched runs whose worker reported nothing within the limit."""
    runs = list(
        await session.scalars(
            select(LearningRun)
            .where(
                or_(
                    LearningRun.status == LearningRunStatus.running,
                    and_(
                        LearningRun.status == LearningRunStatus.queued,
                        LearningRun.dispatched_at.is_not(None),
                    ),
                )
            )
            .with_for_update(skip_locked=True)
        )
    )
    expired = 0
    for run in runs:
        since = run.started_at or run.dispatched_at
        if since + timedelta(seconds=run.timeout_seconds) + TIMEOUT_GRACE <= now:
            _fail(session, run, "worker_failed", "no result within the time limit", now)
            expired += 1
    await session.commit()
    return expired


async def _dispatch(session: AsyncSession, send: Sender, now: datetime) -> int:
    """Send queued runs to the broker; one run per project is ever active."""
    runs = list(
        await session.scalars(
            select(LearningRun)
            .where(
                LearningRun.status == LearningRunStatus.queued,
                LearningRun.dispatched_at.is_(None),
            )
            .order_by(LearningRun.created_at, LearningRun.id)
            .limit(RELAY_BATCH)
            .with_for_update(skip_locked=True)
        )
    )
    for run in runs:
        run.dispatched_at = now
        send(command_for(run), run)
    await session.commit()
    return len(runs)


def _ref(snapshots: dict[str, Any], name: str) -> ManifestRef | None:
    """Return a stored manifest reference, when the run has that snapshot."""
    value = snapshots.get(name)
    return ManifestRef(**value) if value is not None else None


def artifact_folder(project_id: str, iteration: int) -> str:
    """Return the key of the folder holding an iteration's attempt artifacts."""
    return storage.learning_key(project_id, "runs", f"iteration-{iteration}")


async def _request(session: AsyncSession, run: LearningRun) -> BatchRequest:
    """Build the immutable request of a run's current attempt."""
    project = await session.get(Project, run.project_id)
    classes = await session.scalars(
        select(ProjectClass)
        .where(ProjectClass.project_id == project.id)
        .order_by(ProjectClass.display_order)
    )
    plan = run.evaluation
    root = get_settings().media_root
    return BatchRequest(
        request_id=run.id,
        attempt=run.attempt,
        project_id=project.id,
        iteration=run.iteration,
        purpose=run.purpose,
        solution_id=run.solution,
        solution_version=run.solution_version,
        configuration=run.configuration,
        task=project.task_type,
        classes=[
            ClassEntry(id=item.id, index=item.display_order, name=item.name)
            for item in classes
        ],
        requested_size=run.requested_size,
        seed=run.seed,
        media_root=str(root),
        training=_ref(run.snapshots, "training"),
        pool=_ref(run.snapshots, "pool"),
        evaluation=(
            EvaluationPlan(
                metric=plan["metric"],
                target=plan["target"],
                final=plan["final"],
                validation=_ref(run.snapshots, "validation"),
                test=_ref(run.snapshots, "test"),
            )
            if plan is not None
            else None
        ),
        artifact_dir=str(
            storage.media_path(
                f"{artifact_folder(project.id, run.iteration)}/attempt-{run.attempt}"
            )
        ),
        state_dir=str(
            storage.media_path(storage.learning_key(project.id, "state", run.solution))
        ),
        retain_helper_models=bool(run.configuration.get("retain_helper_models")),
    )


async def _current(session: AsyncSession, command: Command) -> LearningRun | None:
    """Lock and return the run a command addresses, or None when stale."""
    run = await session.get(LearningRun, command.run_id, with_for_update=True)
    if (
        run is None
        or run.attempt != command.attempt
        or run.configuration_fingerprint != command.configuration_fingerprint
    ):
        return None
    return run


async def start_attempt(
    session: AsyncSession, command: Command, now: datetime
) -> BatchRequest | None:
    """Claim a dispatched attempt for a worker and build its request.

    A command whose attempt or fingerprint is no longer current, or whose run
    is no longer a dispatched queued run, is a duplicate or stale delivery and
    is ignored.

    Args:
        session: Active database session.
        command: Broker command.
        now: Server time.

    Returns:
        The request, or None when the command must not run.
    """
    run = await _current(session, command)
    if (
        run is None
        or run.status != LearningRunStatus.queued
        or run.dispatched_at is None
    ):
        return None
    run.status = LearningRunStatus.running
    run.started_at = now
    request = await _request(session, run)
    await session.commit()
    return request


async def record_stage(session: AsyncSession, command: Command, stage: str) -> None:
    """Record the stage a running attempt reports (D14).

    Args:
        session: Active database session.
        command: Broker command of the attempt.
        stage: ``training``, ``evaluating``, or ``selecting``.
    """
    run = await _current(session, command)
    if run is not None and run.status == LearningRunStatus.running and stage in STAGES:
        run.stage = stage
    await session.commit()


async def ingest(
    session: AsyncSession,
    command: Command,
    outcome: BatchResult | Failure,
    now: datetime,
) -> bool:
    """Apply one attempt's outcome atomically, ignoring duplicate and stale ones.

    Args:
        session: Active database session.
        command: Broker command of the attempt.
        outcome: The solution's result, or the failure the worker reported.
        now: Server time.

    Returns:
        True when a valid result was applied.
    """
    run = await _current(session, command)
    if run is None or run.status != LearningRunStatus.running:
        return False
    project = await session.get(Project, run.project_id, with_for_update=True)
    if isinstance(outcome, Failure):
        _fail(session, run, outcome.code, outcome.detail, now)
        await session.commit()
        return False
    try:
        chosen = _checked_selection(run, outcome)
    except AdapterError as error:
        _fail(session, run, "solution_output_invalid", error.detail, now)
        await session.commit()
        return False
    await _apply(session, run, project, outcome, chosen, now)
    await session.commit()
    return True


def _checked_selection(run: LearningRun, result: BatchResult) -> list[str]:
    """Validate a result against its run and return the chosen media.

    Raises:
        AdapterError: When the result does not answer the run's request.
    """
    if (
        result.request_id != run.id
        or result.solution_id != run.solution
        or result.solution_version != run.solution_version
    ):
        raise AdapterError("invalid", "the result answers another request")

    by_split = {item.split: item for item in result.evaluations}
    if len(by_split) != len(result.evaluations):
        raise AdapterError("invalid", "a split was evaluated twice")
    plan = run.evaluation
    if plan is None and result.evaluations:
        raise AdapterError("invalid", "no evaluation was planned")
    stopped = result.stop_reason is not None
    if plan is not None:
        required = {"validation"}
        if plan["final"] or stopped:
            required.add("test")
        if set(by_split) != required:
            raise AdapterError("invalid", f"expected evaluations of {sorted(required)}")
        if any(item.metric != plan["metric"] for item in result.evaluations):
            raise AdapterError("invalid", "an evaluation used another metric")
    if stopped and (
        plan is None
        or plan["target"] is None
        or by_split["validation"].value < plan["target"]
    ):
        raise AdapterError("invalid", "the metric target was not met")

    if run.purpose == LearningRunPurpose.final_evaluation or stopped:
        if result.selection is not None:
            raise AdapterError("invalid", "this run must not select a batch")
        return []
    selection_manifest = result.selection
    if (
        selection_manifest is None
        or selection_manifest.get("info", {}).get("schema") != MANIFEST_SCHEMA
    ):
        raise AdapterError("invalid", "the selection is not a manifest")
    if selection_manifest.get("annotations"):
        raise AdapterError("invalid", "object targets are not supported yet")
    chosen = [image["id"] for image in selection_manifest.get("images", [])]
    pool = read_manifest(str(get_settings().media_root), _ref(run.snapshots, "pool"))
    eligible = {image["id"] for image in pool["images"]}
    if len(set(chosen)) != len(chosen):
        raise AdapterError("invalid", "the selection repeats an image")
    if not set(chosen) <= eligible:
        raise AdapterError("invalid", "the selection names an ineligible image")
    if len(chosen) > run.requested_size:
        raise AdapterError("invalid", "the selection exceeds the requested size")
    return chosen


async def _apply(
    session: AsyncSession,
    run: LearningRun,
    project: Project,
    result: BatchResult,
    chosen: list[str],
    now: datetime,
) -> None:
    """Persist evaluations, then open the batch or finish the loop."""
    for item in result.evaluations:
        session.add(
            ModelEvaluation(
                project_id=run.project_id,
                run_id=run.id,
                iteration=run.iteration,
                split=item.split,
                metric=item.metric,
                value=item.value,
                metrics=item.metrics,
                model=item.model,
                snapshot=run.snapshots[item.split]["sha256"],
            )
        )
    run.status = LearningRunStatus.succeeded
    run.finished_at = now
    run.stage = None
    run.result = {
        "selected": len(chosen),
        "shortfall_reason": result.shortfall_reason,
        "stop_reason": result.stop_reason,
        "provenance": result.provenance,
    }
    _audit(session, run, "learning.run_succeeded", selected=len(chosen))

    if result.stop_reason is not None:
        _complete(session, project, CompletionReason.metric_target)
    elif run.purpose == LearningRunPurpose.final_evaluation:
        _complete(session, project, CompletionReason(run.evaluation["reason"]))
    elif chosen:
        await batches.open_batch(
            session,
            project,
            BatchPurpose.acquisition,
            chosen,
            strategy=ACTIVE_LEARNING_STRATEGY,
            seed=run.seed,
            input_fingerprint=run.snapshots["pool"]["sha256"],
            requested_size=run.requested_size,
            model_run_id=run.id,
        )
    else:
        await session.flush()
        await advance(session, project, now)


async def _first_attempt(
    session: AsyncSession, project: Project, iteration_id: str
) -> LearningRun:
    """Return the first attempt identifying an iteration of the project.

    Raises:
        ApiError: 404 when no such iteration exists in the project.
    """
    run = await session.get(LearningRun, iteration_id)
    if run is None or run.project_id != project.id or run.attempt != 1:
        raise ApiError(404, "not_found", "The iteration does not exist.")
    return run


async def retry(
    session: AsyncSession,
    actor: User,
    project: Project,
    iteration_id: str,
    now: datetime,
) -> IterationResponse:
    """Queue a new attempt of a failed iteration over the same snapshots.

    Args:
        session: Active database session.
        actor: Owner or manager asking for the retry.
        project: Authorized project.
        iteration_id: First attempt identifying the iteration.
        now: Server time.

    Returns:
        The iteration with its new attempt.

    Raises:
        ApiError: 404 for an unknown iteration; 409 when its latest attempt
            did not fail, the project is not active, or a run is active.
    """
    first = await _first_attempt(session, project, iteration_id)
    latest = await session.scalar(
        select(LearningRun)
        .where(
            LearningRun.project_id == project.id,
            LearningRun.iteration == first.iteration,
        )
        .order_by(LearningRun.attempt.desc())
        .limit(1)
        .with_for_update()
    )
    if latest.status not in (LearningRunStatus.failed, LearningRunStatus.cancelled):
        raise ApiError(
            409,
            "iteration_not_failed",
            "Only a failed iteration can be retried.",
            details={"status": latest.status},
        )
    if project.status != "active":
        raise ApiError(
            409,
            "project_not_active",
            "Only an active project acquires.",
            details={"status": project.status},
        )
    active = await session.scalar(
        select(LearningRun.id).where(
            LearningRun.project_id == project.id,
            LearningRun.status.in_(ACTIVE_LEARNING_RUN_STATUSES),
        )
    )
    if active is not None:
        raise ApiError(
            409,
            "learning_run_in_progress",
            "Another run of this project is already active.",
            details={"run_id": active},
        )

    run = LearningRun(
        project_id=project.id,
        iteration=latest.iteration,
        attempt=latest.attempt + 1,
        purpose=latest.purpose,
        strategy=latest.strategy,
        solution=latest.solution,
        solution_version=latest.solution_version,
        configuration=latest.configuration,
        configuration_fingerprint=latest.configuration_fingerprint,
        requested_size=latest.requested_size,
        seed=latest.seed,
        evaluation=latest.evaluation,
        snapshots=latest.snapshots,
        status=LearningRunStatus.queued,
        timeout_seconds=get_settings().learning_timeout_seconds,
        result={},
        requested_by=actor.id,
    )
    session.add(run)
    await session.flush()
    _audit(session, run, "learning.run_retried", actor)
    problem = _solution_problem(run)
    if problem is not None:
        _fail(session, run, "solution_unavailable", problem, now)
    await session.commit()
    return await iteration(session, project, iteration_id)


async def close(
    session: AsyncSession, project: Project, iteration_id: str, now: datetime
) -> IterationResponse:
    """Reconcile an iteration whose completion event may have been missed.

    Args:
        session: Active database session.
        project: Authorized project.
        iteration_id: First attempt identifying the iteration.
        now: Server time.

    Returns:
        The iteration after the check.

    Raises:
        ApiError: 404 for an unknown iteration; 409 ``iteration_incomplete``
            while its batch still has unresolved images.
    """
    view = await iteration(session, project, iteration_id)
    if view.batch_id is not None and view.status in (
        "preparing",
        "annotating",
        "consolidating",
    ):
        raise ApiError(
            409,
            "iteration_incomplete",
            "The iteration still has unresolved images.",
            details={"remaining_items": view.total_count - view.resolved_count},
        )
    locked = await session.get(Project, project.id, with_for_update=True)
    await advance(session, locked, now)
    await session.commit()
    return await iteration(session, project, iteration_id)


async def _views(session: AsyncSession, project: Project) -> list[IterationResponse]:
    """Build every iteration of a project from its runs and batches (D6)."""
    runs = list(
        await session.scalars(
            select(LearningRun)
            .where(LearningRun.project_id == project.id)
            .order_by(LearningRun.iteration, LearningRun.attempt)
        )
    )
    if not runs:
        return []
    run_ids = [run.id for run in runs]
    batch_by_run = {
        batch.model_run_id: batch
        for batch in await session.scalars(
            select(AnnotationBatch).where(AnnotationBatch.model_run_id.in_(run_ids))
        )
    }
    evaluations: dict[str, list[ModelEvaluation]] = {}
    for item in await session.scalars(
        select(ModelEvaluation)
        .where(ModelEvaluation.project_id == project.id)
        .order_by(ModelEvaluation.split.desc())
    ):
        evaluations.setdefault(item.run_id, []).append(item)

    groups: dict[int, list[LearningRun]] = {}
    for run in runs:
        groups.setdefault(run.iteration, []).append(run)
    views = []
    for attempts in groups.values():
        views.append(
            await _view(
                session,
                attempts,
                next(
                    (batch_by_run[r.id] for r in attempts if r.id in batch_by_run), None
                ),
                [item for r in attempts for item in evaluations.get(r.id, [])],
            )
        )
    return views


async def _view(
    session: AsyncSession,
    attempts: list[LearningRun],
    batch: AnnotationBatch | None,
    evaluations: list[ModelEvaluation],
) -> IterationResponse:
    """Build one iteration from its attempts, batch, and evaluations."""
    first, latest = attempts[0], attempts[-1]
    if latest.status in ACTIVE_LEARNING_RUN_STATUSES:
        state = "training"
    elif latest.status != LearningRunStatus.succeeded:
        state = "failed"
    elif batch is not None:
        state = BATCH_STATES[BatchStatus(batch.status)]
    else:
        state = "ready"
    counts = await batches.counts(session, batch) if batch is not None else None
    validation = next(
        (item for item in evaluations if item.split == "validation"), None
    )
    completed_at = None
    if state == "ready":
        completed_at = batch.updated_at if batch is not None else latest.finished_at
    return IterationResponse(
        id=first.id,
        number=first.iteration,
        purpose=latest.purpose,
        status=state,
        stage=latest.stage,
        strategy=latest.strategy,
        attempt=latest.attempt,
        solution=latest.solution,
        solution_version=latest.solution_version,
        batch_id=batch.id if batch is not None else None,
        requested_size=latest.requested_size,
        selected_count=latest.result.get("selected"),
        shortfall_reason=latest.result.get("shortfall_reason"),
        stop_reason=latest.result.get("stop_reason"),
        failure_code=latest.failure_code,
        failure_detail=latest.failure_detail,
        total_count=counts.total_items if counts else 0,
        resolved_count=counts.resolved_items if counts else 0,
        review_required_count=counts.review_required_items if counts else 0,
        available_count=counts.available_assignments if counts else 0,
        total_assignment_count=counts.total_assignments if counts else 0,
        submitted_assignment_count=counts.submitted_assignments if counts else 0,
        eta_seconds=None,
        metrics=dict(validation.metrics) if validation is not None else {},
        evaluations=[_evaluation_view(item) for item in evaluations],
        started_at=first.created_at,
        completed_at=completed_at,
    )


def _evaluation_view(item: ModelEvaluation) -> EvaluationView:
    """Represent one stored evaluation."""
    return EvaluationView(
        iteration=item.iteration,
        split=item.split,
        metric=item.metric,
        value=item.value,
        metrics=item.metrics,
        model=item.model,
        created_at=item.created_at,
    )


async def iteration(
    session: AsyncSession, project: Project, iteration_id: str
) -> IterationResponse:
    """Return one iteration of a project.

    Raises:
        ApiError: 404 when the project has no such iteration.
    """
    first = await _first_attempt(session, project, iteration_id)
    return next(view for view in await _views(session, project) if view.id == first.id)


async def iteration_page(
    session: AsyncSession, project: Project, cursor: str | None
) -> IterationPage:
    """Return one page of a project's iterations, oldest first.

    Args:
        session: Active database session.
        project: Authorized project.
        cursor: Opaque cursor from a previous page.

    Returns:
        The page, the current iteration, and the next cursor.
    """
    views = await _views(session, project)
    after = decode_cursor(cursor)["number"] if cursor is not None else 0
    remaining = [view for view in views if view.number > after]
    page = remaining[:PAGE_SIZE]
    return IterationPage(
        items=page,
        current_iteration=views[-1] if views else None,
        next_cursor=(
            encode_cursor({"number": page[-1].number})
            if len(remaining) > PAGE_SIZE
            else None
        ),
    )


async def statistics(session: AsyncSession, project: Project) -> StatisticsResponse:
    """Return the project's loop progress and every target-model evaluation.

    Args:
        session: Active database session.
        project: Authorized project.

    Returns:
        Progress counts and evaluations ordered by iteration.
    """
    acquisitions = await _acquisitions(session, project.id)
    evaluations = await session.scalars(
        select(ModelEvaluation)
        .where(ModelEvaluation.project_id == project.id)
        .order_by(ModelEvaluation.iteration, ModelEvaluation.split.desc())
    )
    return StatisticsResponse(
        project_id=project.id,
        acquisition_strategy=project.acquisition_strategy,
        max_acquisition_iterations=project.max_acquisition_iterations,
        completed_iterations=sum(
            1
            for batch in acquisitions
            if batch.status in (BatchStatus.resolved, BatchStatus.closed)
        ),
        completion_reason=project.completion_reason,
        evaluation_metric=project.evaluation_metric,
        metric_target=project.metric_target,
        evaluations=[_evaluation_view(item) for item in evaluations],
    )
