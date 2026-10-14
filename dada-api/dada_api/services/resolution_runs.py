"""Durable resolver runs: the outbox relay, worker attempts, and result
ingestion."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.consensus import catalog, protocol
from dada_api.core.config import get_settings
from dada_api.core.errors import ApiError
from dada_api.models.annotation import (
    AUTOMATIC_CONSENSUS_SOURCE,
    EXPERT_ADJUDICATION_SOURCE,
    AnnotationSubmission,
    ResolvedAnnotation,
)
from dada_api.models.batch import AnnotationBatch, BatchItem, ItemStatus
from dada_api.models.consensus import (
    INITIAL_EVIDENCE_READY_EVENT,
    OutboxEvent,
    ResolutionInput,
    ResolutionWorkItem,
    ResolutionWorkStatus,
    ReviewAssignment,
    ReviewAssignmentStatus,
    ReviewSubmission,
)
from dada_api.models.media import ContentObject, Media
from dada_api.models.project import Project, ProjectClass
from dada_api.models.resolution import (
    ACTIVE_RUN_STATUSES,
    CalibrationSnapshot,
    ResolutionProposal,
    ResolutionRun,
    ResolverQuarantine,
    RunStatus,
    RunTrigger,
)
from dada_api.models.user import User
from dada_api.services import (
    annotation_documents,
    audit,
    batches,
    performance,
    resolution_foundation,
)

QUEUES = {
    "classification": "consensus.standard",
    "detection": "consensus.standard",
    "segmentation": "consensus.mask",
}
PROJECT_CAPS = {"consensus.standard": 2, "consensus.mask": 1}
MAX_ATTEMPTS = 3
BACKOFF = (timedelta(minutes=1), timedelta(minutes=5))
RECOVERY_GRACE = timedelta(seconds=60)
CANCEL_GRACE = timedelta(seconds=30)
COOPERATIVE_MARGIN_SECONDS = 30
QUARANTINE_FAILURES = 5
QUARANTINE_WINDOW = timedelta(minutes=10)
QUARANTINE_CODES = ("resolver_output_invalid", "resource_limit")
RELAY_BATCH = 50
MASK_BYTES_PER_PIXEL = 48
OPEN_WORK_STATUSES = (
    ResolutionWorkStatus.pending_review,
    ResolutionWorkStatus.review_ready,
    ResolutionWorkStatus.review_required,
)
FAILURE_REASONS = {
    "resolver_unavailable": "resolver_unavailable",
    "resolver_output_invalid": "resolver_output_invalid",
    "cancelled": "expert_required",
}
RUN_STARTED = "resolution.started"
RUN_COMPLETED = "resolution.completed"
RUN_REVIEW_REQUIRED = "resolution.review_required"

Sender = Callable[[protocol.Command, ResolutionRun], None]


class InvalidInput(Exception):
    """A stored input whose evidence no longer matches its fingerprints."""


def _limits(queue: str) -> dict[str, int]:
    """Return the effective time and memory limits a new run records."""
    settings = get_settings()
    if queue == "consensus.mask":
        hard = settings.consensus_mask_timeout_seconds
        memory = settings.consensus_mask_memory_bytes
    else:
        hard = settings.consensus_standard_timeout_seconds
        memory = settings.consensus_standard_memory_bytes
    return {
        "hard_seconds": hard,
        "soft_seconds": hard - COOPERATIVE_MARGIN_SECONDS,
        "memory_bytes": memory,
    }


async def quarantined_keys(session: AsyncSession) -> frozenset[str]:
    """Return ``identifier@version`` of every open quarantine.

    Args:
        session: Active database session.

    Returns:
        The quarantined keys the catalog must report as unavailable.
    """
    rows = await session.execute(
        select(ResolverQuarantine.identifier, ResolverQuarantine.version).where(
            ResolverQuarantine.released_at.is_(None)
        )
    )
    return frozenset(f"{identifier}@{version}" for identifier, version in rows)


def command_for(run: ResolutionRun) -> protocol.Command:
    """Return the broker command of a run's current attempt.

    Args:
        run: Run being dispatched.

    Returns:
        The identifiers and fingerprints the worker needs.
    """
    return protocol.Command(
        run_id=run.id,
        attempt=run.attempt,
        configuration_fingerprint=run.configuration_fingerprint,
        input_fingerprint=run.input_fingerprint,
    )


def _audit(
    session: AsyncSession,
    run: ResolutionRun,
    action: str,
    actor: User | None = None,
    **after: Any,
) -> None:
    """Audit one run transition with identifiers and states only."""
    audit.record(
        session,
        actor,
        run.project_id,
        action,
        "resolution_run",
        run.id,
        after={
            "batch_item_id": run.batch_item_id,
            "status": run.status,
            "attempt": run.attempt,
            **after,
        },
    )


def _event(session: AsyncSession, run: ResolutionRun, event_type: str) -> None:
    """Record a privacy-safe resolution event for Phase 8 delivery."""
    session.add(
        OutboxEvent(
            project_id=run.project_id,
            event_type=event_type,
            aggregate_type="resolution_run",
            aggregate_id=run.id,
            generation=max(run.attempt, 1),
            payload={
                "project_id": run.project_id,
                "batch_item_id": run.batch_item_id,
                "run_id": run.id,
                "status": run.status,
            },
        )
    )


async def create_run(
    session: AsyncSession,
    *,
    project: Project,
    batch: AnnotationBatch,
    item: BatchItem,
    source_input: ResolutionInput,
    trigger: RunTrigger,
    now: datetime,
    configuration: dict[str, Any] | None = None,
    actor: User | None = None,
) -> ResolutionRun:
    """Queue one run over an input snapshot, or fail it at once when its
    pipeline or strategies cannot run.

    Args:
        session: Active database session; the caller commits.
        project: Project owning the item.
        batch: Batch whose frozen policy configures the run.
        item: Image being resolved, locked by the caller.
        source_input: Immutable evidence snapshot.
        trigger: Why the run exists.
        now: Server time.
        configuration: Validated configuration overriding the batch snapshot.
        actor: User who asked for a manual run; None for the system.

    Returns:
        The queued run, or the failed run when it is unavailable.

    Raises:
        ApiError: 409 ``resolution_in_progress`` when an equivalent run is
            already active for the item.
    """
    configuration = configuration or {
        "parameters": batch.parameters,
        "review_thresholds": batch.review_thresholds,
    }
    configuration_fingerprint = protocol.fingerprint(
        {
            "pipeline": batch.resolver,
            "pipeline_version": batch.resolver_version,
            **configuration,
        }
    )
    active = await session.scalar(
        select(ResolutionRun.id).where(
            ResolutionRun.batch_item_id == item.id,
            ResolutionRun.configuration_fingerprint == configuration_fingerprint,
            ResolutionRun.status.in_(ACTIVE_RUN_STATUSES),
        )
    )
    if active is not None:
        raise ApiError(
            409,
            "resolution_in_progress",
            "An equivalent resolution run is already active for this image.",
            details={"run_id": active},
        )

    sequence = await session.scalar(
        select(func.max(ResolutionRun.sequence)).where(
            ResolutionRun.batch_item_id == item.id
        )
    )
    queue = QUEUES[project.task_type]
    pipeline = catalog.pipeline_for(project.task_type)
    requires = {
        *pipeline.requires,
        *(
            name
            for strategy in catalog.selected_strategies(
                project.task_type, configuration["parameters"]
            )
            for name in strategy.requires
        ),
    }
    run = ResolutionRun(
        project_id=project.id,
        batch_item_id=item.id,
        resolution_input_id=source_input.id,
        sequence=(sequence or 0) + 1,
        trigger=trigger,
        pipeline=batch.resolver,
        pipeline_version=batch.resolver_version,
        configuration=configuration,
        configuration_fingerprint=configuration_fingerprint,
        input_fingerprint=source_input.content_hash,
        dependency_versions={
            name: catalog.installed_version(name) for name in sorted(requires)
        },
        queue=queue,
        status=RunStatus.queued,
        attempt=0,
        effective_limits=_limits(queue),
        requested_by=actor.id if actor is not None else None,
    )
    session.add(run)
    await session.flush()
    _audit(
        session,
        run,
        "resolution.run_queued",
        actor,
        trigger=trigger,
        sequence=run.sequence,
        configuration_fingerprint=configuration_fingerprint,
    )

    reason = catalog.configuration_unavailable_reason(
        project.task_type,
        configuration["parameters"],
        quarantined=await quarantined_keys(session),
    )
    if reason is not None:
        await _fail(session, run, item, batch, "resolver_unavailable", reason, now)
    return run


async def relay_once(session: AsyncSession, send: Sender, now: datetime) -> dict:
    """Run one pass of the outbox relay.

    It turns readiness events into queued runs, re-queues runs whose worker
    vanished, and sends queued runs to the broker within the per-project caps.
    Delivery is at least once: a command whose attempt is no longer current
    is ignored by the worker.

    Args:
        session: Active database session.
        send: Callable that hands one command to the broker.
        now: Server time.

    Returns:
        Counts of created, recovered, and dispatched runs.
    """
    created = await _consume_events(session, now)
    recovered = await _recover(session, now)
    dispatched = await _dispatch(session, send, now)
    return {"created": created, "recovered": recovered, "dispatched": dispatched}


async def _consume_events(session: AsyncSession, now: datetime) -> int:
    """Turn unpublished readiness events into first-round runs."""
    events = list(
        await session.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.event_type == INITIAL_EVIDENCE_READY_EVENT,
                OutboxEvent.published_at.is_(None),
            )
            .order_by(OutboxEvent.occurred_at, OutboxEvent.id)
            .limit(RELAY_BATCH)
            .with_for_update(skip_locked=True)
        )
    )
    created = 0
    for event in events:
        event.published_at = now
        item = await session.get(BatchItem, event.aggregate_id, with_for_update=True)
        if (
            item is None
            or item.initial_evidence_generation != event.generation
            or item.status != ItemStatus.awaiting_resolution
        ):
            continue
        source_input = await resolution_foundation.create_initial_input(
            session, event.id
        )
        batch = await session.get(AnnotationBatch, item.batch_id)
        project = await session.get(Project, batch.project_id)
        await create_run(
            session,
            project=project,
            batch=batch,
            item=item,
            source_input=source_input,
            trigger=RunTrigger.initial,
            now=now,
        )
        created += 1
    await session.commit()
    return created


async def _recover(session: AsyncSession, now: datetime) -> int:
    """Re-queue runs whose worker produced nothing within its hard limit."""
    runs = list(
        await session.scalars(
            select(ResolutionRun)
            .where(
                or_(
                    ResolutionRun.status == RunStatus.running,
                    (ResolutionRun.status == RunStatus.queued)
                    & ResolutionRun.dispatched_at.is_not(None),
                )
            )
            .with_for_update(skip_locked=True)
        )
    )
    recovered = 0
    for run in runs:
        if (
            run.cancel_requested_at is not None
            and run.cancel_requested_at + CANCEL_GRACE <= now
        ):
            item = await session.get(BatchItem, run.batch_item_id, with_for_update=True)
            batch = await session.get(AnnotationBatch, item.batch_id)
            await _fail(session, run, item, batch, "cancelled", "cancelled", now)
            recovered += 1
            continue
        since = run.started_at or run.dispatched_at
        deadline = timedelta(seconds=run.effective_limits["hard_seconds"])
        if since + deadline + RECOVERY_GRACE > now:
            continue
        item = await session.get(BatchItem, run.batch_item_id, with_for_update=True)
        batch = await session.get(AnnotationBatch, item.batch_id)
        if run.attempt >= MAX_ATTEMPTS:
            await _fail(
                session,
                run,
                item,
                batch,
                "worker_failed",
                "no result after the final attempt",
                now,
            )
        else:
            run.status = RunStatus.queued
            run.dispatched_at = None
            run.started_at = None
            run.next_attempt_at = now + BACKOFF[run.attempt - 1]
            if item.status != ItemStatus.resolved:
                item.status = ItemStatus.awaiting_resolution
            _audit(
                session,
                run,
                "resolution.run_retried",
                next_attempt_at=run.next_attempt_at.isoformat(),
            )
        recovered += 1
    await session.commit()
    return recovered


async def _dispatch(session: AsyncSession, send: Sender, now: datetime) -> int:
    """Send due queued runs to the broker within the per-project caps."""
    in_flight = {
        (project_id, queue): count
        for project_id, queue, count in await session.execute(
            select(ResolutionRun.project_id, ResolutionRun.queue, func.count())
            .where(
                or_(
                    ResolutionRun.status == RunStatus.running,
                    (ResolutionRun.status == RunStatus.queued)
                    & ResolutionRun.dispatched_at.is_not(None),
                )
            )
            .group_by(ResolutionRun.project_id, ResolutionRun.queue)
        )
    }
    runs = list(
        await session.scalars(
            select(ResolutionRun)
            .where(
                ResolutionRun.status == RunStatus.queued,
                ResolutionRun.dispatched_at.is_(None),
                or_(
                    ResolutionRun.next_attempt_at.is_(None),
                    ResolutionRun.next_attempt_at <= now,
                ),
            )
            .order_by(ResolutionRun.created_at, ResolutionRun.id)
            .limit(RELAY_BATCH)
            .with_for_update(skip_locked=True)
        )
    )
    dispatched = 0
    for run in runs:
        key = (run.project_id, run.queue)
        if in_flight.get(key, 0) >= PROJECT_CAPS[run.queue]:
            continue
        run.attempt += 1
        run.dispatched_at = now
        send(command_for(run), run)
        in_flight[key] = in_flight.get(key, 0) + 1
        dispatched += 1
    await session.commit()
    return dispatched


async def request_cancel(
    session: AsyncSession, run: ResolutionRun, now: datetime
) -> None:
    """Cancel a run: at once when no worker has it, otherwise cooperatively.

    A dispatched run is flagged; the worker honours the flag when it starts
    or reports, and the relay cancels it outright after a short grace period.
    Either way its late result is discarded and the image goes to an expert.

    Args:
        session: Active database session; the caller commits.
        run: Active run to cancel, locked by the caller.
        now: Server time.
    """
    if run.status == RunStatus.queued and run.dispatched_at is None:
        item = await session.get(BatchItem, run.batch_item_id, with_for_update=True)
        batch = await session.get(AnnotationBatch, item.batch_id)
        await _fail(session, run, item, batch, "cancelled", "cancelled", now)
    else:
        run.cancel_requested_at = now


async def start_attempt(
    session: AsyncSession, command: protocol.Command, now: datetime
) -> protocol.ResolverInput | None:
    """Claim a dispatched attempt for a worker and load its verified input.

    A command whose attempt or fingerprints are no longer current, or whose
    run is no longer queued, is a duplicate or stale delivery and is ignored.
    An input whose stored evidence changed fails closed.

    Args:
        session: Active database session.
        command: Broker command.
        now: Server time.

    Returns:
        The plain resolver input, or None when the command must not run.
    """
    run = await session.get(ResolutionRun, command.run_id, with_for_update=True)
    if (
        run is None
        or run.status != RunStatus.queued
        or run.dispatched_at is None
        or run.attempt != command.attempt
        or run.configuration_fingerprint != command.configuration_fingerprint
        or run.input_fingerprint != command.input_fingerprint
    ):
        return None
    item = await session.get(BatchItem, run.batch_item_id, with_for_update=True)
    batch = await session.get(AnnotationBatch, item.batch_id)
    if run.cancel_requested_at is not None:
        await _fail(session, run, item, batch, "cancelled", "cancelled", now)
        await session.commit()
        return None

    run.status = RunStatus.running
    run.started_at = now
    if item.status != ItemStatus.resolved:
        item.status = ItemStatus.resolving
    _event(session, run, RUN_STARTED)
    try:
        resolver_input = await _load_input(session, run, item)
    except InvalidInput as error:
        await _fail(session, run, item, batch, "invalid_input", str(error), now)
        await session.commit()
        return None
    if _estimated_bytes(resolver_input) > run.effective_limits["memory_bytes"]:
        await _fail(
            session,
            run,
            item,
            batch,
            "resource_limit",
            "the masks would exceed the memory limit",
            now,
        )
        await session.commit()
        return None
    await session.commit()
    return resolver_input


def _estimated_bytes(resolver_input: protocol.ResolverInput) -> int:
    """Estimate a segmentation run's peak memory before any mask exists.

    Measured peaks of mask aggregation were 20 to 35 times the raw boolean
    masks, so each mask counts ``MASK_BYTES_PER_PIXEL`` bytes per pixel.
    Other tasks hold no rasters and are not estimated.
    """
    if resolver_input.task_type != "segmentation":
        return 0
    masks = sum(len(source.objects) for source in resolver_input.sources) + sum(
        1 for source in resolver_input.sources if source.kind == "review"
    )
    return resolver_input.width * resolver_input.height * masks * MASK_BYTES_PER_PIXEL


async def _load_input(
    session: AsyncSession, run: ResolutionRun, item: BatchItem
) -> protocol.ResolverInput:
    """Build the plain resolver input of a run, verifying every hash."""
    source_input = await session.get(ResolutionInput, run.resolution_input_id)
    if protocol.fingerprint(source_input.source_inputs) != source_input.content_hash:
        raise InvalidInput("the input snapshot no longer matches its fingerprint")

    sources: list[protocol.Source] = []
    for reference in source_input.source_inputs:
        if reference.get("kind", "submission") == "submission":
            submission = await session.get(
                AnnotationSubmission, reference["submission_id"]
            )
            if (
                submission is None
                or submission.content_hash != reference["content_hash"]
                or annotation_documents.content_hash(submission.objects)
                != reference["content_hash"]
            ):
                raise InvalidInput("a submission changed or disappeared")
            sources.append(
                protocol.Source(
                    kind="submission",
                    id=submission.id,
                    annotator_id=reference["annotator_id"],
                    annotator_index=reference["position"],
                    content_hash=submission.content_hash,
                    objects=submission.objects,
                )
            )
        else:
            review = await session.get(
                ReviewSubmission, reference["review_submission_id"]
            )
            if (
                review is None
                or review.content_hash != reference["content_hash"]
                or protocol.fingerprint(review.evidence) != reference["content_hash"]
            ):
                raise InvalidInput("a review submission changed or disappeared")
            sources.append(
                protocol.Source(
                    kind="review",
                    id=review.id,
                    annotator_id=reference["reviewer_id"],
                    annotator_index=reference["position"],
                    content_hash=review.content_hash,
                    candidate_key=reference["candidate_key"],
                    evidence=review.evidence,
                )
            )

    project = await session.get(Project, run.project_id)
    width, height = (
        await session.execute(
            select(ContentObject.width, ContentObject.height)
            .join(Media, Media.content_object_id == ContentObject.id)
            .where(Media.id == item.media_id)
        )
    ).one()
    class_ids = list(
        await session.scalars(
            select(ProjectClass.id)
            .where(ProjectClass.project_id == project.id)
            .order_by(ProjectClass.display_order)
        )
    )
    batch = await session.get(AnnotationBatch, item.batch_id)
    snapshot = (
        await session.get(CalibrationSnapshot, batch.calibration_snapshot_id)
        if batch.calibration_snapshot_id is not None
        else None
    )
    return protocol.ResolverInput(
        pipeline=run.pipeline,
        pipeline_version=run.pipeline_version,
        task_type=project.task_type,
        configuration=run.configuration,
        width=width,
        height=height,
        class_ids=class_ids,
        sources=sources,
        candidates=source_input.candidate_mapping.get("candidates"),
        calibration=snapshot.parameters if snapshot is not None else None,
    )


async def ingest(session: AsyncSession, result: protocol.Result, now: datetime) -> None:
    """Apply one worker result atomically, ignoring duplicate and stale ones.

    A valid proposal is always persisted first. The image is then accepted
    automatically when every candidate passed its frozen gates; otherwise the
    failing candidates become work items. A failure moves the image to an
    owner or manager.

    Args:
        session: Active database session.
        result: Worker result of one attempt.
        now: Server time.
    """
    run = await session.get(ResolutionRun, result.run_id, with_for_update=True)
    if (
        run is None
        or run.status != RunStatus.running
        or run.attempt != result.attempt
        or run.configuration_fingerprint != result.configuration_fingerprint
        or run.input_fingerprint != result.input_fingerprint
    ):
        return
    item = await session.get(BatchItem, run.batch_item_id, with_for_update=True)
    batch = await session.get(AnnotationBatch, item.batch_id)
    run.finished_at = now

    if run.cancel_requested_at is not None:
        await _fail(session, run, item, batch, "cancelled", "cancelled", now)
    elif result.outcome == "failed":
        await _fail(
            session,
            run,
            item,
            batch,
            result.failure_code or "worker_failed",
            result.failure_detail or "",
            now,
        )
    else:
        problem = await _output_problem(session, run, item, result)
        if problem is not None:
            await _fail(
                session, run, item, batch, "resolver_output_invalid", problem, now
            )
        else:
            await _apply(session, run, item, batch, result.output, now)
    await session.commit()


async def _output_problem(
    session: AsyncSession, run: ResolutionRun, item: BatchItem, result: protocol.Result
) -> str | None:
    """Return why a proposal cannot be trusted, or None when it is valid."""
    output = result.output
    if output is None or not output.candidates:
        return "the result carries no candidates"
    if protocol.fingerprint(output.model_dump(mode="json")) != result.output_checksum:
        return "the output checksum does not match"
    keys = [candidate.key for candidate in output.candidates]
    if len(set(keys)) != len(keys):
        return "candidate keys repeat"

    project = await session.get(Project, run.project_id)
    width, height = (
        await session.execute(
            select(ContentObject.width, ContentObject.height)
            .join(Media, Media.content_object_id == ContentObject.id)
            .where(Media.id == item.media_id)
        )
    ).one()
    class_ids = set(
        await session.scalars(
            select(ProjectClass.id).where(ProjectClass.project_id == project.id)
        )
    )
    for candidate in output.candidates:
        if not candidate.objects:
            continue
        errors = annotation_documents.validate_submission(
            project.task_type, candidate.objects, class_ids, width, height
        )
        if errors:
            return f"candidate {candidate.ordinal} breaks {errors[0].code}"
    return None


async def _apply(
    session: AsyncSession,
    run: ResolutionRun,
    item: BatchItem,
    batch: AnnotationBatch,
    output: protocol.PipelineOutput,
    now: datetime,
) -> None:
    """Persist a valid proposal and either accept it or open work items."""
    source_input = await session.get(ResolutionInput, run.resolution_input_id)
    failing = [candidate for candidate in output.candidates if not candidate.passed]
    objects = [
        entry
        for candidate in output.candidates
        if candidate.passed
        for entry in candidate.objects
    ]
    candidates = [candidate.model_dump(mode="json") for candidate in output.candidates]
    proposal = ResolutionProposal(
        run_id=run.id,
        batch_item_id=item.id,
        outcome="review_required" if failing else "accept",
        objects=objects,
        candidates=candidates,
        diagnostics={**output.diagnostics, "versions": output.versions},
        content_hash=protocol.fingerprint(
            {"objects": objects, "candidates": candidates}
        ),
    )
    session.add(proposal)
    await session.flush()

    current = await current_resolution(session, item.id)
    if current is not None and (
        failing or current.source == EXPERT_ADJUDICATION_SOURCE
    ):
        run.status = RunStatus.review_required if failing else RunStatus.succeeded
        if not failing:
            await _await_explicit_acceptance(session, source_input, run, item)
        _audit(
            session, run, "resolution.proposal_held", current_version=current.version
        )
        return

    passed_keys = {candidate.key for candidate in output.candidates if candidate.passed}
    failing_keys = {candidate.key for candidate in failing}
    for work_item in await _open_work_items(session, item.id):
        if work_item.candidate_key in passed_keys:
            work_item.status = ResolutionWorkStatus.resolved
            work_item.closed_at = now
        elif (
            run.trigger == RunTrigger.manual_retry
            and work_item.candidate_key not in failing_keys
        ):
            work_item.status = ResolutionWorkStatus.cancelled
            work_item.closed_at = now

    if not failing:
        run.status = RunStatus.succeeded
        parts = [
            performance.Part(
                candidate.key, list(candidate.objects), performance.AUTOMATED_CONSENSUS
            )
            for candidate in output.candidates
        ]
        await accept(
            session, item, run, proposal, parts, None, now, source_input=source_input
        )
        _event(session, run, RUN_COMPLETED)
    else:
        first_round = run.trigger == RunTrigger.initial and source_input.run_number == 1
        for candidate in failing:
            await _escalate(session, source_input, run, item, candidate, first_round)
        run.status = RunStatus.review_required
        item.status = (
            ItemStatus.in_review if first_round else ItemStatus.review_required
        )
        _event(session, run, RUN_REVIEW_REQUIRED)
        _audit(
            session,
            run,
            "resolution.review_required",
            candidate_keys=[candidate.key for candidate in failing],
            reviewers_requested=first_round,
        )
    await session.flush()
    await batches.refresh_status(session, batch)


async def _await_explicit_acceptance(
    session: AsyncSession,
    source_input: ResolutionInput,
    run: ResolutionRun,
    item: BatchItem,
) -> None:
    """Open an image case so an owner or manager may explicitly accept a
    passing proposal over an adjudicated version (P6-06 precedence)."""
    existing = await _work_item(session, item, "image")
    if existing is not None:
        _reopen(existing, run, "expert_required")
        return
    await resolution_foundation.create_expert_work_item(
        session,
        source_input,
        candidate_key="image",
        candidate_ordinal=0,
        scope="image",
        candidate_context={},
        reason="expert_required",
        run_id=run.id,
    )


async def _escalate(
    session: AsyncSession,
    source_input: ResolutionInput,
    run: ResolutionRun,
    item: BatchItem,
    candidate: protocol.Candidate,
    first_round: bool,
) -> None:
    """Route one failing candidate to reviewers on a first round, otherwise to
    an owner or manager."""
    reason = candidate.reasons[0] if candidate.reasons else "expert_required"
    context = {"region": candidate.region} if candidate.region else {}
    existing = await _work_item(session, item, candidate.key)
    if first_round and existing is None:
        await resolution_foundation.create_review_work_item(
            session,
            source_input,
            candidate_key=candidate.key,
            candidate_ordinal=candidate.ordinal,
            scope=candidate.scope,
            candidate_context=context,
            reason=reason,
            run_id=run.id,
        )
    elif existing is not None:
        _reopen(existing, run, reason)
    else:
        await resolution_foundation.create_expert_work_item(
            session,
            source_input,
            candidate_key=candidate.key,
            candidate_ordinal=candidate.ordinal,
            scope=candidate.scope,
            candidate_context=context,
            reason=reason,
            run_id=run.id,
        )


async def accept(
    session: AsyncSession,
    item: BatchItem,
    run: ResolutionRun | None,
    proposal: ResolutionProposal | None,
    parts: list[performance.Part],
    actor: User | None,
    now: datetime,
    source_input: ResolutionInput | None,
    source: str = AUTOMATIC_CONSENSUS_SOURCE,
) -> ResolvedAnnotation:
    """Make a new canonical resolution current and resolve its image.

    Object IDs are renumbered for the new version so no raw annotator ID is
    reused. The previous current version is superseded, never deleted, and its
    performance observations stop counting for summaries. The new version's
    raw-to-canonical evidence and observations are written with it.

    Args:
        session: Active database session; the caller commits.
        item: Image being resolved, locked by the caller.
        run: Run that produced the accepted proposal, if any.
        proposal: Proposal being accepted, if any.
        parts: Candidate contributions in candidate order.
        actor: Accepting user; None when the system accepts.
        now: Server time.
        source_input: Evidence snapshot the decision was built on.
        source: How the resolution was reached.

    Returns:
        The new current resolution.
    """
    current = await current_resolution(session, item.id)
    if current is not None:
        current.superseded_at = now
        await performance.supersede(session, current)
        await session.flush()
    canonical: list[dict[str, Any]] = []
    numbered = []
    for part in parts:
        ids = []
        for entry in part.objects:
            ids.append(f"o{len(canonical) + 1}")
            canonical.append({**entry, "id": ids[-1]})
        numbered.append(replace(part, canonical_ids=ids))
    resolution = ResolvedAnnotation(
        batch_item_id=item.id,
        version=(current.version + 1) if current is not None else 1,
        source=source,
        submission_id=None,
        objects=canonical,
        content_hash=annotation_documents.content_hash(canonical),
        run_id=run.id if run is not None else None,
        proposal_id=proposal.id if proposal is not None else None,
        accepted_by=actor.id if actor is not None else None,
    )
    session.add(resolution)
    item.status = ItemStatus.resolved
    for work_item in await _open_work_items(session, item.id):
        work_item.status = ResolutionWorkStatus.resolved
        work_item.closed_at = now
    await session.flush()
    batch = await session.get(AnnotationBatch, item.batch_id)
    project = await session.get(Project, batch.project_id)
    await performance.record(
        session,
        project_id=project.id,
        task_type=project.task_type,
        resolution=resolution,
        source_input=source_input,
        parts=numbered,
        candidates=proposal.candidates if proposal is not None else [],
        duplicates=(
            proposal.diagnostics.get("duplicates", []) if proposal is not None else []
        ),
    )
    audit.record(
        session,
        actor,
        project.id,
        "resolution.accepted",
        "resolved_annotation",
        resolution.id,
        before={"version": current.version} if current is not None else None,
        after={
            "batch_item_id": item.id,
            "version": resolution.version,
            "source": source,
            "run_id": resolution.run_id,
            "content_hash": resolution.content_hash,
        },
    )
    return resolution


async def current_resolution(
    session: AsyncSession, item_id: str
) -> ResolvedAnnotation | None:
    """Return an image's current canonical resolution, if any.

    Args:
        session: Active database session.
        item_id: Batch item identifier.

    Returns:
        The version that is not superseded, or None.
    """
    return await session.scalar(
        select(ResolvedAnnotation).where(
            ResolvedAnnotation.batch_item_id == item_id,
            ResolvedAnnotation.superseded_at.is_(None),
        )
    )


async def _open_work_items(
    session: AsyncSession, item_id: str
) -> list[ResolutionWorkItem]:
    """Return an image's work items that are still collecting or deciding."""
    return list(
        await session.scalars(
            select(ResolutionWorkItem).where(
                ResolutionWorkItem.batch_item_id == item_id,
                ResolutionWorkItem.status.in_(OPEN_WORK_STATUSES),
            )
        )
    )


async def _work_item(
    session: AsyncSession, item: BatchItem, candidate_key: str
) -> ResolutionWorkItem | None:
    """Return the latest work item of one candidate in the image's current
    evidence generation, whatever its status, so it is reopened rather than
    duplicated."""
    return await session.scalar(
        select(ResolutionWorkItem)
        .join(
            ResolutionInput,
            ResolutionInput.id == ResolutionWorkItem.resolution_input_id,
        )
        .where(
            ResolutionWorkItem.batch_item_id == item.id,
            ResolutionWorkItem.candidate_key == candidate_key,
            ResolutionInput.evidence_generation == item.initial_evidence_generation,
        )
        .order_by(ResolutionWorkItem.created_at.desc())
        .limit(1)
    )


def _reopen(work_item: ResolutionWorkItem, run: ResolutionRun, reason: str) -> None:
    """Put an existing work item back in front of an owner or manager."""
    work_item.status = ResolutionWorkStatus.review_required
    work_item.reason = reason
    work_item.run_id = run.id
    work_item.closed_at = None


async def _fail(
    session: AsyncSession,
    run: ResolutionRun,
    item: BatchItem,
    batch: AnnotationBatch,
    code: str,
    detail: str,
    now: datetime,
) -> None:
    """End a run without a usable proposal and hand the image to an expert.

    The run keeps its evidence and error classification. An unresolved image
    gets one expert-only work item that an owner or manager may retry or
    adjudicate (D22); an image that already has an accepted resolution keeps
    it untouched, because a failed retry never displaces it (P6-06).
    """
    run.status = RunStatus.cancelled if code == "cancelled" else RunStatus.failed
    run.failure_code = code
    run.failure_detail = detail[:500]
    run.finished_at = now
    if await current_resolution(session, item.id) is None:
        reason = FAILURE_REASONS.get(code, "worker_failed")
        existing = await _work_item(session, item, "image")
        if existing is not None:
            _reopen(existing, run, reason)
        else:
            await resolution_foundation.create_expert_work_item(
                session,
                await session.get(ResolutionInput, run.resolution_input_id),
                candidate_key="image",
                candidate_ordinal=0,
                scope="image",
                candidate_context={},
                reason=reason,
                run_id=run.id,
            )
        item.status = ItemStatus.review_required
    _event(session, run, RUN_REVIEW_REQUIRED)
    _audit(session, run, "resolution.run_failed", failure_code=code)
    await session.flush()
    await _quarantine_if_failing(session, run, now)
    await batches.refresh_status(session, batch)


async def _quarantine_if_failing(
    session: AsyncSession, run: ResolutionRun, now: datetime
) -> None:
    """Quarantine a pipeline version after repeated invalid outputs or
    resource-limit failures (P6-05)."""
    if run.failure_code not in QUARANTINE_CODES:
        return
    failures = await session.scalar(
        select(func.count())
        .select_from(ResolutionRun)
        .where(
            ResolutionRun.pipeline == run.pipeline,
            ResolutionRun.pipeline_version == run.pipeline_version,
            ResolutionRun.failure_code.in_(QUARANTINE_CODES),
            ResolutionRun.finished_at >= now - QUARANTINE_WINDOW,
        )
    )
    if failures < QUARANTINE_FAILURES:
        return
    if f"{run.pipeline}@{run.pipeline_version}" in await quarantined_keys(session):
        return
    session.add(
        ResolverQuarantine(
            identifier=run.pipeline,
            version=run.pipeline_version,
            reason="repeated_invalid_output_or_resource_limit",
            triggered_at=now,
        )
    )


async def on_review_ready(
    session: AsyncSession, work_item: ResolutionWorkItem, now: datetime
) -> ResolutionRun | None:
    """Queue the second run once every first-round work item has its reviews.

    The image row is locked before counting, so two concurrent final reviews
    cannot both miss, or both create, the second round.

    Args:
        session: Active database session; the caller commits.
        work_item: Work item whose reviews just completed, flushed.
        now: Server time.

    Returns:
        The queued second-round run, or None while reviews are outstanding.
    """
    item = await session.get(BatchItem, work_item.batch_item_id, with_for_update=True)
    source_input = await session.get(ResolutionInput, work_item.resolution_input_id)
    if item.status != ItemStatus.in_review:
        return None
    collecting = await session.scalar(
        select(func.count())
        .select_from(ResolutionWorkItem)
        .where(
            ResolutionWorkItem.resolution_input_id == source_input.id,
            ResolutionWorkItem.status == ResolutionWorkStatus.pending_review,
        )
    )
    if collecting:
        return None

    reviews = (
        await session.execute(
            select(ReviewSubmission, ResolutionWorkItem.candidate_key)
            .join(
                ReviewAssignment,
                ReviewAssignment.id == ReviewSubmission.review_assignment_id,
            )
            .join(
                ResolutionWorkItem,
                ResolutionWorkItem.id == ReviewSubmission.work_item_id,
            )
            .where(
                ResolutionWorkItem.resolution_input_id == source_input.id,
                ReviewAssignment.status == ReviewAssignmentStatus.submitted,
            )
            .order_by(ResolutionWorkItem.candidate_ordinal, ReviewAssignment.position)
        )
    ).all()
    cohort_size = len(source_input.source_inputs)
    references = [
        *source_input.source_inputs,
        *(
            {
                "kind": "review",
                "position": cohort_size + index,
                "review_submission_id": review.id,
                "reviewer_id": review.reviewer_id,
                "candidate_key": candidate_key,
                "content_hash": review.content_hash,
            }
            for index, (review, candidate_key) in enumerate(reviews)
        ),
    ]
    first_run = await session.get(ResolutionRun, work_item.run_id)
    proposal = await session.scalar(
        select(ResolutionProposal).where(ResolutionProposal.run_id == first_run.id)
    )
    review_input = ResolutionInput(
        batch_item_id=item.id,
        source_event_id=None,
        evidence_generation=source_input.evidence_generation,
        run_number=source_input.run_number + 1,
        source_inputs=references,
        candidate_mapping={"candidates": proposal.candidates},
        content_hash=protocol.fingerprint(references),
    )
    session.add(review_input)
    await session.flush()
    item.status = ItemStatus.awaiting_resolution
    batch = await session.get(AnnotationBatch, item.batch_id)
    project = await session.get(Project, batch.project_id)
    run = await create_run(
        session,
        project=project,
        batch=batch,
        item=item,
        source_input=review_input,
        trigger=RunTrigger.review,
        now=now,
        configuration=first_run.configuration,
    )
    await session.flush()
    await batches.refresh_status(session, batch)
    return run


async def invalidate_generation(
    session: AsyncSession, item: BatchItem, now: datetime
) -> None:
    """Retire every run, work item, and review of an image whose evidence
    generation just advanced (D7).

    Results that arrive later fail the run-status check and are discarded.

    Args:
        session: Active database session; the caller commits.
        item: Image whose cohort changed, locked by the caller.
        now: Server time.
    """
    for run in await session.scalars(
        select(ResolutionRun).where(
            ResolutionRun.batch_item_id == item.id,
            ResolutionRun.status.in_(ACTIVE_RUN_STATUSES),
        )
    ):
        run.status = RunStatus.cancelled
        run.failure_code = "cancelled"
        run.failure_detail = "the evidence generation advanced"
        run.finished_at = now
    for work_item in await _open_work_items(session, item.id):
        work_item.status = ResolutionWorkStatus.cancelled
        work_item.closed_at = now
        for review in await session.scalars(
            select(ReviewAssignment).where(
                ReviewAssignment.work_item_id == work_item.id,
                ReviewAssignment.status.in_(
                    (ReviewAssignmentStatus.pending, ReviewAssignmentStatus.in_progress)
                ),
            )
        ):
            review.status = ReviewAssignmentStatus.cancelled
            review.version += 1
