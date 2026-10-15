"""Manager resolution queue, evidence, retries, adjudication, and cancellation."""

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import case, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.consensus import catalog
from dada_api.core import media_urls
from dada_api.core.cursors import decode_cursor, encode_cursor
from dada_api.core.errors import ApiError, redact_validation_errors
from dada_api.models.annotation import (
    EXPERT_ADJUDICATION_SOURCE,
    AnnotationSubmission,
    ResolvedAnnotation,
)
from dada_api.models.annotation_policy import AnnotationMode
from dada_api.models.batch import (
    AnnotationAssignment,
    AnnotationBatch,
    AnnotationItemAnnotator,
    BatchItem,
    ItemStatus,
)
from dada_api.models.consensus import (
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
    EDITING_ACTIONS,
    Adjudication,
    AdjudicationAction,
    ResolutionLease,
    ResolutionProposal,
    ResolutionRun,
    RunTrigger,
)
from dada_api.models.user import User
from dada_api.schemas.assignment import AssignmentMedia
from dada_api.schemas.resolution import (
    AdjudicationRequest,
    AdjudicationView,
    CancelRunRequest,
    EvidenceResponse,
    EvidenceVersions,
    ExpectedVersions,
    LeaseResponse,
    ProposalView,
    ResolutionView,
    RetryRequest,
    ReviewEvidence,
    RunView,
    SubmissionEvidence,
    WorkItemView,
)
from dada_api.services import (
    annotation_documents,
    audit,
    batches,
    performance,
    resolution_leases,
    resolution_runs,
)
from dada_api.services.authorization import get_project_role

PAGE_SIZE = 50
FAILURE_REASONS = ("worker_failed", "resolver_output_invalid", "resolver_unavailable")
SEVERITY = case(
    (ResolutionWorkItem.reason.in_(FAILURE_REASONS), 0),
    (ResolutionWorkItem.reason == "expert_required", 1),
    else_=2,
)


async def load_item(
    session: AsyncSession, project: Project, item_id: str, *, lock: bool = False
) -> tuple[BatchItem, AnnotationBatch]:
    """Return a batch item of the project with its batch.

    Args:
        session: Active database session.
        project: Authorized project.
        item_id: Batch item identifier.
        lock: Whether to lock the item row.

    Returns:
        The item and its batch.

    Raises:
        ApiError: 404 when it does not exist in this project.
    """
    query = (
        select(BatchItem, AnnotationBatch)
        .join(AnnotationBatch, AnnotationBatch.id == BatchItem.batch_id)
        .where(BatchItem.id == item_id, AnnotationBatch.project_id == project.id)
    )
    if lock:
        query = query.with_for_update(of=BatchItem)
    row = (await session.execute(query)).first()
    if row is None:
        raise ApiError(404, "not_found", "The batch item does not exist.")
    return row[0], row[1]


async def list_queue(
    session: AsyncSession,
    project: Project,
    batch_id: str,
    *,
    states: list[str],
    reason: str | None,
    strategy: str | None,
    min_age_seconds: int | None,
    cursor: str | None,
    now: datetime,
) -> tuple[list[tuple], str | None]:
    """List a batch's resolution work items for an owner or manager.

    Failures come first, then cases explicitly waiting for an expert, then
    the rest; oldest first within each group.

    Args:
        session: Active database session.
        project: Authorized project.
        batch_id: Batch whose work is listed.
        states: Work item statuses to include.
        reason: Optional reason filter.
        strategy: Optional class-strategy filter.
        min_age_seconds: Only items at least this old.
        cursor: Opaque page cursor.
        now: Server time.

    Returns:
        Rows of (work item, item, media, run or None) and the next cursor.
    """
    order = (SEVERITY, ResolutionWorkItem.created_at, ResolutionWorkItem.id)
    query = (
        select(ResolutionWorkItem, BatchItem, Media, ResolutionRun, SEVERITY)
        .join(BatchItem, BatchItem.id == ResolutionWorkItem.batch_item_id)
        .join(AnnotationBatch, AnnotationBatch.id == BatchItem.batch_id)
        .join(Media, Media.id == BatchItem.media_id)
        .outerjoin(ResolutionRun, ResolutionRun.id == ResolutionWorkItem.run_id)
        .where(
            AnnotationBatch.project_id == project.id,
            AnnotationBatch.id == batch_id,
            ResolutionWorkItem.status.in_(states),
        )
    )
    if reason is not None:
        query = query.where(ResolutionWorkItem.reason == reason)
    if strategy is not None:
        query = query.where(
            ResolutionRun.configuration["parameters"]["class_strategy"][
                "strategy"
            ].astext
            == strategy
        )
    if min_age_seconds is not None:
        query = query.where(
            ResolutionWorkItem.created_at <= now - timedelta(seconds=min_age_seconds)
        )
    if cursor is not None:
        position = decode_cursor(cursor)
        query = query.where(
            tuple_(*order)
            > tuple_(
                position["severity"],
                datetime.fromisoformat(position["created_at"]),
                position["id"],
            )
        )
    rows = list(
        (await session.execute(query.order_by(*order).limit(PAGE_SIZE + 1))).all()
    )
    next_cursor = None
    if len(rows) > PAGE_SIZE:
        rows = rows[:PAGE_SIZE]
        work_item, *_, severity = rows[-1]
        next_cursor = encode_cursor(
            {
                "severity": severity,
                "created_at": work_item.created_at.isoformat(),
                "id": work_item.id,
            }
        )
    return [tuple(row[:4]) for row in rows], next_cursor


async def review_counts(session: AsyncSession, work_item_id: str) -> tuple[int, int]:
    """Return (submitted, required) reviewer counts of a work item.

    Args:
        session: Active database session.
        work_item_id: Work item identifier.

    Returns:
        The submitted and total active review assignments.
    """
    counts = dict(
        (
            await session.execute(
                select(ReviewAssignment.status, func.count())
                .where(ReviewAssignment.work_item_id == work_item_id)
                .group_by(ReviewAssignment.status)
            )
        ).all()
    )
    submitted = counts.get(ReviewAssignmentStatus.submitted, 0)
    cancelled = counts.get(ReviewAssignmentStatus.cancelled, 0)
    return submitted, sum(counts.values()) - cancelled


async def proposal_of(
    session: AsyncSession, run_id: str | None
) -> ResolutionProposal | None:
    """Return the proposal a run produced, if any.

    Args:
        session: Active database session.
        run_id: Run identifier, possibly None.

    Returns:
        The proposal, or None.
    """
    if run_id is None:
        return None
    return await session.scalar(
        select(ResolutionProposal).where(ResolutionProposal.run_id == run_id)
    )


def candidate_of(proposal: ResolutionProposal | None, key: str) -> dict | None:
    """Return one candidate decision of a proposal by its key.

    Args:
        proposal: Proposal to search, possibly None.
        key: Candidate key.

    Returns:
        The candidate dictionary, or None.
    """
    if proposal is None:
        return None
    return next((entry for entry in proposal.candidates if entry["key"] == key), None)


async def contributions(session: AsyncSession, item_id: str, user_id: str) -> list[str]:
    """Return every evidence ID a user contributed to an image.

    Initial submissions of every generation and review submissions both
    count, so promotion or a later generation never erases the history.

    Args:
        session: Active database session.
        item_id: Batch item identifier.
        user_id: User being checked.

    Returns:
        Submission and review-submission IDs, oldest first.
    """
    submissions = list(
        await session.scalars(
            select(AnnotationSubmission.id)
            .join(
                AnnotationAssignment,
                AnnotationAssignment.id == AnnotationSubmission.assignment_id,
            )
            .where(
                AnnotationAssignment.batch_item_id == item_id,
                AnnotationSubmission.submitted_by == user_id,
            )
            .order_by(AnnotationSubmission.submitted_at)
        )
    )
    reviews = list(
        await session.scalars(
            select(ReviewSubmission.id)
            .join(
                ResolutionWorkItem,
                ResolutionWorkItem.id == ReviewSubmission.work_item_id,
            )
            .where(
                ResolutionWorkItem.batch_item_id == item_id,
                ReviewSubmission.reviewer_id == user_id,
            )
            .order_by(ReviewSubmission.submitted_at)
        )
    )
    return submissions + reviews


async def current_versions(
    session: AsyncSession, item: BatchItem
) -> tuple[int, str | None, int]:
    """Return the three versions a manager action must expect (D18).

    Args:
        session: Active database session.
        item: Batch item.

    Returns:
        The evidence generation, the latest run's configuration fingerprint
        (None before any run), and the current resolution version (0 if none).
    """
    fingerprint = await session.scalar(
        select(ResolutionRun.configuration_fingerprint)
        .where(ResolutionRun.batch_item_id == item.id)
        .order_by(ResolutionRun.sequence.desc())
        .limit(1)
    )
    current = await resolution_runs.current_resolution(session, item.id)
    return (
        item.initial_evidence_generation,
        fingerprint,
        current.version if current is not None else 0,
    )


async def _require_versions(
    session: AsyncSession, item: BatchItem, expected: ExpectedVersions
) -> None:
    """Refuse a manager action built on stale evidence, configuration, or
    resolution."""
    generation, fingerprint, version = await current_versions(session, item)
    current = {
        "evidence_generation": generation,
        "configuration_fingerprint": fingerprint,
        "resolution_version": version,
    }
    if expected.expected_configuration_fingerprint != fingerprint:
        raise ApiError(
            409,
            "resolution_config_conflict",
            "The resolver configuration changed since it was read.",
            details=current,
        )
    if (
        expected.expected_evidence_generation != generation
        or expected.expected_resolution_version != version
    ):
        raise ApiError(
            409,
            "version_conflict",
            "The evidence or resolution changed since it was read.",
            details=current,
        )


async def retry(
    session: AsyncSession,
    actor: User,
    project: Project,
    item_id: str,
    request: RetryRequest,
    now: datetime,
) -> ResolutionRun:
    """Queue a manual resolver run over an image's latest evidence (D19).

    The configuration defaults to the batch snapshot. Another one may be
    given; it passes the same closed schema and hard floors, is recorded on
    the run, and never changes the snapshot. A failed retry never displaces an
    accepted resolution.

    Args:
        session: Active database session.
        actor: Owner or manager.
        project: Authorized project.
        item_id: Image to resolve again.
        request: Expected versions, rationale, optional configuration.
        now: Server time.

    Returns:
        The queued run.

    Raises:
        ApiError: 409 when the image is not ready, a run is active, a version
            is stale, or another user holds an edit lease; 422 on an invalid
            configuration.
    """
    item, batch = await load_item(session, project, item_id, lock=True)
    if batch.mode != AnnotationMode.consensus or item.status in (
        ItemStatus.pending,
        ItemStatus.in_review,
    ):
        raise ApiError(
            409,
            "resolution_not_ready",
            "The image is not waiting for a resolution decision.",
        )
    if item.status == ItemStatus.cancelled:
        raise ApiError(409, "item_closed", "The image was cancelled.")
    if item.status in (ItemStatus.awaiting_resolution, ItemStatus.resolving):
        raise ApiError(
            409, "resolution_in_progress", "A resolution run is already active."
        )
    await _require_versions(session, item, request)
    held = await resolution_leases.foreign_lease(session, item.id, actor, now)
    if held is not None:
        raise resolution_leases.lease_conflict(held)

    configuration = None
    if request.configuration is not None:
        try:
            parameters, thresholds = catalog.normalize(
                project.task_type,
                request.configuration.parameters,
                request.configuration.review_thresholds,
            )
        except ValidationError as error:
            raise ApiError(
                422,
                "invalid_resolver_configuration",
                "The resolver settings are not valid for this pipeline.",
                details={"errors": redact_validation_errors(error.errors())},
            ) from error
        configuration = {"parameters": parameters, "review_thresholds": thresholds}

    source_input = await session.scalar(
        select(ResolutionInput)
        .where(
            ResolutionInput.batch_item_id == item.id,
            ResolutionInput.evidence_generation == item.initial_evidence_generation,
        )
        .order_by(ResolutionInput.run_number.desc())
        .limit(1)
    )
    if source_input is None:
        raise ApiError(
            409, "resolution_not_ready", "The image has no evidence snapshot yet."
        )

    if item.status != ItemStatus.resolved:
        item.status = ItemStatus.awaiting_resolution
    run = await resolution_runs.create_run(
        session,
        project=project,
        batch=batch,
        item=item,
        source_input=source_input,
        trigger=RunTrigger.manual_retry,
        now=now,
        configuration=configuration,
        actor=actor,
    )
    audit.record(
        session,
        actor,
        project.id,
        "resolution.retry_requested",
        "resolution_run",
        run.id,
        after={
            "batch_item_id": item.id,
            "rationale": request.rationale,
            "configuration_fingerprint": run.configuration_fingerprint,
        },
    )
    await session.flush()
    await batches.refresh_status(session, batch)
    await session.commit()
    await session.refresh(run)
    return run


async def cancel_run(
    session: AsyncSession,
    actor: User,
    project: Project,
    run_id: str,
    request: CancelRunRequest,
    now: datetime,
) -> ResolutionRun:
    """Cancel an active run; its evidence stays and the image goes to an expert.

    Args:
        session: Active database session.
        actor: Owner or manager.
        project: Authorized project.
        run_id: Run to cancel.
        request: Mandatory rationale.
        now: Server time.

    Returns:
        The run, cancelled or flagged for cooperative cancellation.

    Raises:
        ApiError: 404 when the run is unknown; 409 when it is no longer active
            or another user holds an edit lease on the image.
    """
    run = await session.scalar(
        select(ResolutionRun)
        .where(ResolutionRun.id == run_id, ResolutionRun.project_id == project.id)
        .with_for_update()
    )
    if run is None:
        raise ApiError(404, "not_found", "The resolution run does not exist.")
    if run.status not in ACTIVE_RUN_STATUSES:
        raise ApiError(409, "run_not_active", "The run already finished.")
    held = await resolution_leases.foreign_lease(session, run.batch_item_id, actor, now)
    if held is not None:
        raise resolution_leases.lease_conflict(held)
    await resolution_runs.request_cancel(session, run, now)
    audit.record(
        session,
        actor,
        project.id,
        "resolution.run_cancel_requested",
        "resolution_run",
        run.id,
        after={"status": run.status, "rationale": request.rationale},
    )
    await session.commit()
    await session.refresh(run)
    return run


async def _decision_objects(
    session: AsyncSession,
    project: Project,
    item: BatchItem,
    work_item: ResolutionWorkItem,
    request: AdjudicationRequest,
) -> tuple[list[dict[str, Any]], ResolutionProposal | None, str | None]:
    """Return the canonical objects an adjudication decides, with its sources."""
    proposal = await proposal_of(session, work_item.run_id)
    if request.action == AdjudicationAction.accept_proposal:
        candidate = candidate_of(proposal, work_item.candidate_key)
        if candidate is not None:
            return list(candidate["objects"]), proposal, None
        if proposal is not None and work_item.scope == "image":
            return list(proposal.objects), proposal, None
        raise ApiError(
            422,
            "proposal_unavailable",
            "There is no resolution proposal to accept for this case.",
        )

    if request.objects is None:
        raise ApiError(
            422, "invalid_document", "Editing or replacing requires objects."
        )
    objects = [entry.model_dump() for entry in request.objects]
    source_submission_id = None
    if request.action == AdjudicationAction.edit_submission:
        source_submission_id = await session.scalar(
            select(AnnotationSubmission.id)
            .join(
                AnnotationAssignment,
                AnnotationAssignment.id == AnnotationSubmission.assignment_id,
            )
            .where(
                AnnotationSubmission.id == str(request.source_submission_id),
                AnnotationAssignment.batch_item_id == item.id,
            )
        )
        if source_submission_id is None:
            raise ApiError(
                422,
                "invalid_source",
                "The source submission does not belong to this image.",
            )
    if objects:
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
        errors = annotation_documents.validate_submission(
            project.task_type, objects, class_ids, width, height
        )
        if errors:
            raise ApiError(
                422,
                "invalid_document",
                "The adjudicated document breaks the task or geometry rules.",
                details={"errors": [asdict(error) for error in errors]},
            )
    elif work_item.scope == "image" and project.task_type == "classification":
        raise ApiError(
            422,
            "invalid_document",
            "A classification image needs at least one class.",
            details={"errors": [{"object_id": None, "code": "empty_not_allowed"}]},
        )
    return (
        objects,
        proposal if request.action == "edit_proposal" else None,
        (source_submission_id),
    )


async def adjudicate(
    session: AsyncSession,
    actor: User,
    project: Project,
    work_item_id: str,
    request: AdjudicationRequest,
    now: datetime,
) -> tuple[Adjudication, ResolvedAnnotation | None]:
    """Record an expert decision on a work item and close the image when it
    was the last open case.

    An adjudication is a final canonical decision, not another vote. Editing
    requires the caller's lease; accepting does not, but is refused while
    someone else edits. A contributor may adjudicate only with a rationale,
    and never when the batch requires an independent adjudicator (P6-04).

    Args:
        session: Active database session.
        actor: Owner or manager.
        project: Authorized project.
        work_item_id: Case being decided.
        request: Action, objects, rationale, and expected versions.
        now: Server time.

    Returns:
        The adjudication and, when the image closed, its new resolution.

    Raises:
        ApiError: 403 when independence is required; 409 on a closed or
            collecting case, stale versions, or lease conflicts; 422 on a
            missing rationale or an invalid document.
    """
    work_item = await resolution_leases.load_work_item(
        session, project, work_item_id, lock=True
    )
    item, batch = await load_item(session, project, work_item.batch_item_id, lock=True)
    if work_item.status in (
        ResolutionWorkStatus.resolved,
        ResolutionWorkStatus.cancelled,
    ):
        raise ApiError(409, "work_item_closed", "The case is already closed.")
    if work_item.status != ResolutionWorkStatus.review_required:
        raise ApiError(
            409,
            "resolution_not_ready",
            "Reviewers are still collecting evidence for this case.",
        )
    await _require_versions(session, item, request)

    lease = await resolution_leases.active_lease(session, work_item.id, now)
    if request.action in EDITING_ACTIONS:
        if lease is None or lease.holder_id != actor.id:
            raise ApiError(
                409, "lease_required", "Editing a case requires holding its lease."
            )
    held = await resolution_leases.foreign_lease(session, item.id, actor, now)
    if held is not None:
        raise resolution_leases.lease_conflict(held)

    contributed = await contributions(session, item.id, actor.id)
    conflict = bool(contributed)
    if conflict and batch.require_independent_adjudicator:
        raise ApiError(
            403,
            "adjudicator_not_independent",
            "This batch requires an adjudicator who contributed no evidence.",
        )
    current = await resolution_runs.current_resolution(session, item.id)
    overriding_expert = (
        current is not None and current.source == EXPERT_ADJUDICATION_SOURCE
    )
    if (request.action in EDITING_ACTIONS or conflict or overriding_expert) and not (
        request.rationale or ""
    ).strip():
        raise ApiError(
            422,
            "rationale_required",
            "This decision requires a rationale.",
            details={"contributor_conflict": conflict},
        )

    objects, source_proposal, source_submission_id = await _decision_objects(
        session, project, item, work_item, request
    )
    role = await get_project_role(session, actor, project.id)
    adjudication = Adjudication(
        project_id=project.id,
        batch_item_id=item.id,
        work_item_id=work_item.id,
        actor_id=actor.id,
        actor_role=role.value if role is not None else "administrator",
        action=request.action,
        source_proposal_id=source_proposal.id if source_proposal else None,
        source_submission_id=source_submission_id,
        objects=objects,
        content_hash=annotation_documents.content_hash(objects),
        rationale=request.rationale,
        contributor_conflict=conflict,
        contribution_submission_ids=contributed,
        independence_required=batch.require_independent_adjudicator,
        policy_version=batch.source_policy_version,
        expected_evidence_generation=request.expected_evidence_generation,
        expected_configuration_fingerprint=request.expected_configuration_fingerprint,
        expected_resolution_version=request.expected_resolution_version,
    )
    session.add(adjudication)
    work_item.status = ResolutionWorkStatus.resolved
    work_item.closed_at = now
    if lease is not None and lease.holder_id == actor.id:
        lease.released_at = now
    await session.flush()

    audit.record(
        session,
        actor,
        project.id,
        "resolution.adjudicated",
        "resolution_work_item",
        work_item.id,
        after={
            "batch_item_id": item.id,
            "action": request.action,
            "actor_role": adjudication.actor_role,
            "contributor_conflict": conflict,
            "contribution_submission_ids": contributed,
            "independence_required": batch.require_independent_adjudicator,
            "policy_version": batch.source_policy_version,
            "rationale": request.rationale,
            "content_hash": adjudication.content_hash,
        },
    )
    resolution = await _close_image_if_done(session, actor, item, now)
    await batches.refresh_status(session, batch)
    await session.commit()
    await session.refresh(adjudication)
    return adjudication, resolution


async def _close_image_if_done(
    session: AsyncSession, actor: User, item: BatchItem, now: datetime
) -> ResolvedAnnotation | None:
    """Compose the image's new resolution once no case remains open.

    An image-wide adjudication decides the whole document. Otherwise every
    candidate of the latest proposal contributes its accepted objects or its
    adjudicated decision, in candidate order (P6-06: derived work items close
    into one parent-image version).
    """
    open_items = await session.scalar(
        select(func.count())
        .select_from(ResolutionWorkItem)
        .where(
            ResolutionWorkItem.batch_item_id == item.id,
            ResolutionWorkItem.status.in_(resolution_runs.OPEN_WORK_STATUSES),
        )
    )
    if open_items:
        return None

    decisions = list(
        await session.scalars(
            select(Adjudication)
            .join(
                ResolutionWorkItem,
                ResolutionWorkItem.id == Adjudication.work_item_id,
            )
            .join(
                ResolutionInput,
                ResolutionInput.id == ResolutionWorkItem.resolution_input_id,
            )
            .where(
                Adjudication.batch_item_id == item.id,
                Adjudication.resolved_annotation_id.is_(None),
                ResolutionInput.evidence_generation == item.initial_evidence_generation,
            )
            .order_by(Adjudication.created_at)
        )
    )
    keys = {
        decision.id: await session.scalar(
            select(ResolutionWorkItem.candidate_key).where(
                ResolutionWorkItem.id == decision.work_item_id
            )
        )
        for decision in decisions
    }
    latest = {keys[decision.id]: decision for decision in decisions}
    run = await session.scalar(
        select(ResolutionRun)
        .join(ResolutionProposal, ResolutionProposal.run_id == ResolutionRun.id)
        .where(ResolutionRun.batch_item_id == item.id)
        .order_by(ResolutionRun.sequence.desc())
        .limit(1)
    )
    proposal = await proposal_of(session, run.id if run is not None else None)

    if "image" in latest:
        parts = [
            performance.Part(
                "image", list(latest["image"].objects), performance.HUMAN_ADJUDICATION
            )
        ]
    else:
        parts = []
        for candidate in sorted(
            proposal.candidates, key=lambda entry: entry["ordinal"]
        ):
            if candidate["key"] in latest:
                parts.append(
                    performance.Part(
                        candidate["key"],
                        list(latest[candidate["key"]].objects),
                        performance.HUMAN_ADJUDICATION,
                    )
                )
            elif candidate["passed"]:
                parts.append(
                    performance.Part(
                        candidate["key"],
                        list(candidate["objects"]),
                        performance.AUTOMATED_CONSENSUS,
                    )
                )

    source_input = await session.scalar(
        select(ResolutionInput)
        .where(
            ResolutionInput.batch_item_id == item.id,
            ResolutionInput.evidence_generation == item.initial_evidence_generation,
        )
        .order_by(ResolutionInput.run_number.desc())
        .limit(1)
    )
    resolution = await resolution_runs.accept(
        session,
        item,
        run,
        proposal,
        parts,
        actor,
        now,
        source_input=source_input,
        source=EXPERT_ADJUDICATION_SOURCE,
    )
    for decision in decisions:
        decision.resolved_annotation_id = resolution.id
    return resolution


def lease_view(lease: ResolutionLease | None) -> LeaseResponse | None:
    """Represent an active lease, if any.

    Args:
        lease: Active lease or None.

    Returns:
        The lease representation, or None.
    """
    if lease is None:
        return None
    return LeaseResponse(
        work_item_id=lease.work_item_id,
        holder_id=lease.holder_id,
        acquired_at=lease.acquired_at,
        renewed_at=lease.renewed_at,
        expires_at=lease.expires_at,
        cap_at=lease.cap_at,
    )


def adjudication_view(adjudication: Adjudication) -> AdjudicationView:
    """Represent one recorded expert decision.

    Args:
        adjudication: Stored adjudication.

    Returns:
        Its representation.
    """
    return AdjudicationView(
        id=adjudication.id,
        work_item_id=adjudication.work_item_id,
        action=adjudication.action,
        actor_id=adjudication.actor_id,
        actor_role=adjudication.actor_role,
        objects=adjudication.objects,
        rationale=adjudication.rationale,
        contributor_conflict=adjudication.contributor_conflict,
        resolved_annotation_id=adjudication.resolved_annotation_id,
        created_at=adjudication.created_at,
    )


def resolution_view(resolution: ResolvedAnnotation) -> ResolutionView:
    """Represent one canonical resolution version.

    Args:
        resolution: Stored resolution.

    Returns:
        Its representation.
    """
    return ResolutionView(
        id=resolution.id,
        version=resolution.version,
        source=resolution.source,
        objects=resolution.objects,
        content_hash=resolution.content_hash,
        accepted_by=resolution.accepted_by,
        run_id=resolution.run_id,
        created_at=resolution.created_at,
        superseded_at=resolution.superseded_at,
    )


def run_view(run: ResolutionRun, proposal: ResolutionProposal | None) -> RunView:
    """Represent one run with its proposal.

    Args:
        run: Stored run.
        proposal: Its proposal, if it produced one.

    Returns:
        Its representation.
    """
    return RunView(
        id=run.id,
        sequence=run.sequence,
        trigger=run.trigger,
        status=run.status,
        pipeline=run.pipeline,
        pipeline_version=run.pipeline_version,
        configuration=run.configuration,
        configuration_fingerprint=run.configuration_fingerprint,
        input_fingerprint=run.input_fingerprint,
        dependency_versions=run.dependency_versions,
        attempt=run.attempt,
        failure_code=run.failure_code,
        failure_detail=run.failure_detail,
        requested_by=run.requested_by,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        proposal=(
            ProposalView(
                id=proposal.id,
                outcome=proposal.outcome,
                objects=proposal.objects,
                candidates=proposal.candidates,
                diagnostics=proposal.diagnostics,
                content_hash=proposal.content_hash,
                created_at=proposal.created_at,
            )
            if proposal is not None
            else None
        ),
    )


async def evidence(
    session: AsyncSession, project: Project, item_id: str, now: datetime
) -> EvidenceResponse:
    """Gather one image's complete, named evidence for an owner or manager.

    Args:
        session: Active database session.
        project: Authorized project.
        item_id: Batch item identifier.
        now: Server time, for the signed image link and lease expiry.

    Returns:
        Submissions, reviews, runs with proposals, resolution history, cases
        with leases and decisions, contributors, and the expected versions.
    """
    item, batch = await load_item(session, project, item_id)
    media, content = (
        await session.execute(
            select(Media, ContentObject)
            .join(ContentObject, ContentObject.id == Media.content_object_id)
            .where(Media.id == item.media_id)
        )
    ).one()
    cohort = set(
        await session.scalars(
            select(AnnotationItemAnnotator.assignment_id).where(
                AnnotationItemAnnotator.batch_item_id == item.id,
                AnnotationItemAnnotator.generation == item.initial_evidence_generation,
            )
        )
    )
    submission_rows = (
        await session.execute(
            select(AnnotationSubmission, AnnotationAssignment, User)
            .join(
                AnnotationAssignment,
                AnnotationAssignment.id == AnnotationSubmission.assignment_id,
            )
            .join(User, User.id == AnnotationSubmission.submitted_by)
            .where(AnnotationAssignment.batch_item_id == item.id)
            .order_by(AnnotationSubmission.submitted_at, AnnotationSubmission.id)
        )
    ).all()
    review_rows = (
        await session.execute(
            select(ReviewSubmission, ResolutionWorkItem.candidate_key, User)
            .join(
                ResolutionWorkItem,
                ResolutionWorkItem.id == ReviewSubmission.work_item_id,
            )
            .join(User, User.id == ReviewSubmission.reviewer_id)
            .where(ResolutionWorkItem.batch_item_id == item.id)
            .order_by(ReviewSubmission.submitted_at, ReviewSubmission.id)
        )
    ).all()
    runs = list(
        await session.scalars(
            select(ResolutionRun)
            .where(ResolutionRun.batch_item_id == item.id)
            .order_by(ResolutionRun.sequence)
        )
    )
    proposals = {
        proposal.run_id: proposal
        for proposal in await session.scalars(
            select(ResolutionProposal).where(
                ResolutionProposal.batch_item_id == item.id
            )
        )
    }
    resolutions = list(
        await session.scalars(
            select(ResolvedAnnotation)
            .where(ResolvedAnnotation.batch_item_id == item.id)
            .order_by(ResolvedAnnotation.version)
        )
    )
    work_items = list(
        await session.scalars(
            select(ResolutionWorkItem)
            .where(ResolutionWorkItem.batch_item_id == item.id)
            .order_by(ResolutionWorkItem.created_at, ResolutionWorkItem.id)
        )
    )
    work_item_views = []
    for work_item in work_items:
        submitted, required = await review_counts(session, work_item.id)
        decisions = await session.scalars(
            select(Adjudication)
            .where(Adjudication.work_item_id == work_item.id)
            .order_by(Adjudication.created_at)
        )
        work_item_views.append(
            WorkItemView(
                id=work_item.id,
                candidate_key=work_item.candidate_key,
                candidate_ordinal=work_item.candidate_ordinal,
                scope=work_item.scope,
                status=work_item.status,
                reason=work_item.reason,
                candidate_context=work_item.candidate_context,
                run_id=work_item.run_id,
                reviews_submitted=submitted,
                reviews_required=required,
                lease=lease_view(
                    await resolution_leases.active_lease(session, work_item.id, now)
                ),
                adjudications=[adjudication_view(entry) for entry in decisions],
                created_at=work_item.created_at,
                closed_at=work_item.closed_at,
            )
        )

    generation, fingerprint, version = await current_versions(session, item)
    contributors = sorted(
        {submission.submitted_by for submission, _, _ in submission_rows}
        | {review.reviewer_id for review, _, _ in review_rows}
    )
    return EvidenceResponse(
        batch_item_id=item.id,
        batch_id=batch.id,
        purpose=batch.purpose,
        status=item.status,
        task_type=project.task_type,
        media=AssignmentMedia(
            id=media.id,
            relative_path=media.relative_path,
            width=content.width,
            height=content.height,
            image_url=media_urls.signed_media_url(media.id, now),
        ),
        versions=EvidenceVersions(
            evidence_generation=generation,
            configuration_fingerprint=fingerprint,
            resolution_version=version,
        ),
        require_independent_adjudicator=batch.require_independent_adjudicator,
        contributors=contributors,
        submissions=[
            SubmissionEvidence(
                id=submission.id,
                assignment_id=assignment.id,
                annotator_id=submission.submitted_by,
                annotator_name=user.display_name,
                revision=submission.revision,
                content_hash=submission.content_hash,
                objects=submission.objects,
                submitted_at=submission.submitted_at,
                current_generation=assignment.id in cohort,
            )
            for submission, assignment, user in submission_rows
        ],
        reviews=[
            ReviewEvidence(
                id=review.id,
                work_item_id=review.work_item_id,
                candidate_key=candidate_key,
                reviewer_id=review.reviewer_id,
                reviewer_name=user.display_name,
                evidence=review.evidence,
                content_hash=review.content_hash,
                submitted_at=review.submitted_at,
            )
            for review, candidate_key, user in review_rows
        ],
        runs=[run_view(run, proposals.get(run.id)) for run in runs],
        resolutions=[resolution_view(entry) for entry in resolutions],
        work_items=work_item_views,
    )
