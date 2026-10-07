"""Batch creation, policy snapshots, and assignment generation."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.cursors import decode_cursor, encode_cursor
from dada_api.core.errors import ApiError
from dada_api.models.annotation_policy import AnnotationMode
from dada_api.models.batch import (
    ACTIVE_ASSIGNMENT_STATUSES,
    AnnotationAssignment,
    AnnotationBatch,
    AnnotationBatchAnnotator,
    AnnotationItemAnnotator,
    AssignmentStatus,
    BatchItem,
    BatchPurpose,
    BatchStatus,
    ItemStatus,
)
from dada_api.models.label_import import (
    AnnotationImport,
    ImportedSeedDocument,
    ImportStatus,
)
from dada_api.models.media import Media
from dada_api.models.project import ANNOTATION_ROLES, Project, ProjectMember
from dada_api.models.user import User
from dada_api.schemas.batch import BatchPolicyUpdate
from dada_api.services import annotation_policy, audit, cohort_selection, selection

PAGE_SIZE = 50


@dataclass(frozen=True)
class BatchCounts:
    """Image and assignment progress of one batch.

    Cancelled images and terminal assignments are left out of the totals:
    they are kept as evidence but are no longer work.
    """

    total_items: int
    resolved_items: int
    awaiting_resolution_items: int
    cancelled_items: int
    total_assignments: int
    available_assignments: int
    in_progress_assignments: int
    submitted_assignments: int


async def _snapshot_policy(
    session: AsyncSession,
    project: Project,
    batch: AnnotationBatch,
) -> None:
    """Copy the project's default policy and group onto a new batch."""
    policy, annotator_ids = await annotation_policy.get_policy(session, project)
    batch.mode = policy.mode.value
    batch.required_consensus_annotations = policy.required_consensus_annotations
    batch.required_consensus_reviewers = policy.required_consensus_reviewers
    batch.resolver = policy.resolver
    batch.resolver_version = policy.resolver_version
    batch.parameters = dict(policy.parameters)
    batch.review_thresholds = dict(policy.review_thresholds)
    batch.source_policy_version = policy.version
    await session.flush()

    for position, user_id in enumerate(annotator_ids):
        session.add(
            AnnotationBatchAnnotator(
                batch_id=batch.id, user_id=user_id, position=position
            )
        )


async def create_batch(
    session: AsyncSession,
    project: Project,
    purpose: BatchPurpose,
    candidates: list[str],
    size: int,
) -> list[str]:
    """Draw media reproducibly, open the batch that annotates it, and record how.

    The recorded seed and fingerprint describe this very draw, so a split
    selected from the whole inventory can be recomputed from its batch.

    Args:
        session: Active database session, committed by the caller.
        project: Project the batch belongs to.
        purpose: Why the media is being selected.
        candidates: Eligible media identifiers, in deterministic order.
        size: Requested batch size; fewer are taken when fewer remain.

    Returns:
        The chosen media identifiers.
    """
    seed = selection.new_seed()
    chosen = selection.choose_up_to(candidates, size, seed)
    batch = AnnotationBatch(
        project_id=project.id,
        purpose=purpose,
        status=BatchStatus.preparing,
        mode=AnnotationMode.single,
        parameters={},
        review_thresholds={},
        source_policy_version=1,
        selection_strategy=selection.RANDOM_STRATEGY,
        selection_seed=seed,
        selection_input_fingerprint=selection.fingerprint(candidates),
        requested_size=size,
    )
    session.add(batch)
    await _snapshot_policy(session, project, batch)

    media_order = list(
        await session.scalars(
            select(Media.id)
            .where(Media.id.in_(chosen))
            .order_by(Media.relative_path, Media.id)
        )
    )
    positions = {media_id: position for position, media_id in enumerate(media_order)}
    for media_id in chosen:
        session.add(
            BatchItem(
                batch_id=batch.id,
                media_id=media_id,
                position=positions[media_id],
            )
        )
    return chosen


async def annotator_ids(session: AsyncSession, batch: AnnotationBatch) -> list[str]:
    """Return a batch's snapshotted eligible pool in its recorded order."""
    return list(
        await session.scalars(
            select(AnnotationBatchAnnotator.user_id)
            .where(AnnotationBatchAnnotator.batch_id == batch.id)
            .order_by(AnnotationBatchAnnotator.position)
        )
    )


async def counts(session: AsyncSession, batch: AnnotationBatch) -> BatchCounts:
    """Return a batch's image and assignment progress.

    Args:
        session: Active database session.
        batch: Batch being measured.

    Returns:
        The batch's counts by image and assignment state.
    """
    items = dict(
        (
            await session.execute(
                select(BatchItem.status, func.count())
                .where(BatchItem.batch_id == batch.id)
                .group_by(BatchItem.status)
            )
        ).all()
    )
    assignments = dict(
        (
            await session.execute(
                select(AnnotationAssignment.status, func.count())
                .join(BatchItem, BatchItem.id == AnnotationAssignment.batch_item_id)
                .where(BatchItem.batch_id == batch.id)
                .group_by(AnnotationAssignment.status)
            )
        ).all()
    )
    cancelled = items.get(ItemStatus.cancelled, 0)
    return BatchCounts(
        total_items=sum(items.values()) - cancelled,
        resolved_items=items.get(ItemStatus.resolved, 0),
        awaiting_resolution_items=items.get(ItemStatus.awaiting_resolution, 0),
        cancelled_items=cancelled,
        total_assignments=sum(
            assignments.get(status, 0) for status in ACTIVE_ASSIGNMENT_STATUSES
        ),
        available_assignments=assignments.get(AssignmentStatus.pending, 0),
        in_progress_assignments=assignments.get(AssignmentStatus.in_progress, 0),
        submitted_assignments=assignments.get(AssignmentStatus.submitted, 0),
    )


async def annotation_members(session: AsyncSession, project: Project) -> list[str]:
    """Return the project members allowed to annotate, ordered by username.

    Args:
        session: Active database session.
        project: Project being inspected.

    Returns:
        User identifiers of every owner, manager, and annotator.
    """
    return list(
        await session.scalars(
            select(ProjectMember.user_id)
            .join(User, User.id == ProjectMember.user_id)
            .where(
                ProjectMember.project_id == project.id,
                ProjectMember.role.in_(ANNOTATION_ROLES),
            )
            .order_by(User.username)
        )
    )


async def accepted_seeds(
    session: AsyncSession, project: Project
) -> dict[str, ImportedSeedDocument]:
    """Return the project's accepted imported seeds keyed by media identifier."""
    seeds = await session.scalars(
        select(ImportedSeedDocument)
        .join(AnnotationImport, AnnotationImport.id == ImportedSeedDocument.import_id)
        .where(
            AnnotationImport.project_id == project.id,
            AnnotationImport.status == ImportStatus.accepted,
        )
    )
    return {seed.media_id: seed for seed in seeds}


def seeded_assignment(
    item_id: str,
    annotator_id: str,
    seed: ImportedSeedDocument | None,
) -> AnnotationAssignment:
    """Return a new assignment whose draft starts as a copy of the image's seed."""
    return AnnotationAssignment(
        batch_item_id=item_id,
        annotator_id=annotator_id,
        seed_document_id=seed.id if seed else None,
        draft=list(seed.document["objects"]) if seed else None,
    )


async def list_batches(
    session: AsyncSession,
    project: Project,
    cursor: str | None,
) -> tuple[list[AnnotationBatch], str | None]:
    """List a project's batches, newest first.

    Args:
        session: Active database session.
        project: Authorized project.
        cursor: Opaque cursor from a previous page.

    Returns:
        The page of batches and the cursor for the next page, if any.
    """
    query = (
        select(AnnotationBatch)
        .where(AnnotationBatch.project_id == project.id)
        .order_by(AnnotationBatch.created_at.desc(), AnnotationBatch.id.desc())
    )
    if cursor is not None:
        position = decode_cursor(cursor)
        created_at = datetime.fromisoformat(str(position["created_at"]))
        query = query.where(
            (AnnotationBatch.created_at < created_at)
            | (
                (AnnotationBatch.created_at == created_at)
                & (AnnotationBatch.id < position["id"])
            )
        )

    rows = list(await session.scalars(query.limit(PAGE_SIZE + 1)))
    if len(rows) <= PAGE_SIZE:
        return rows, None
    page = rows[:PAGE_SIZE]
    last = page[-1]
    return page, encode_cursor(
        {"created_at": last.created_at.isoformat(), "id": last.id}
    )


async def get_batch(
    session: AsyncSession,
    project: Project,
    batch_id: str,
) -> AnnotationBatch:
    """Return one of a project's batches.

    Args:
        session: Active database session.
        project: Authorized project.
        batch_id: Batch being read.

    Returns:
        The batch.

    Raises:
        ApiError: 404 when the project has no such batch.
    """
    batch = await session.scalar(
        select(AnnotationBatch).where(
            AnnotationBatch.id == batch_id,
            AnnotationBatch.project_id == project.id,
        )
    )
    if batch is None:
        raise ApiError(404, "not_found", "The annotation batch does not exist.")
    return batch


def _require_preparing(batch: AnnotationBatch) -> None:
    """Refuse to change a batch whose policy is already frozen.

    Raises:
        ApiError: 409 when the batch has left ``preparing``.
    """
    if batch.status != BatchStatus.preparing:
        raise ApiError(
            409,
            "policy_locked",
            "The batch has started and its policy can no longer change.",
            details={"status": batch.status},
        )


async def update_policy(
    session: AsyncSession,
    actor: User,
    project: Project,
    batch: AnnotationBatch,
    request: BatchPolicyUpdate,
) -> AnnotationBatch:
    """Replace a batch's policy snapshot while it is still preparing.

    Args:
        session: Active database session.
        actor: User performing the change.
        project: Project owning the batch.
        batch: Batch being changed.
        request: Validated replacement policy.

    Returns:
        The updated batch.

    Raises:
        ApiError: 409 once the batch has started, 422 on an invalid group or
            resolver.
    """
    _require_preparing(batch)

    mode = AnnotationMode(request.mode)
    requested_ids = [str(user_id) for user_id in request.annotator_ids]
    await annotation_policy.validate_policy(
        session,
        project,
        mode,
        requested_ids,
        request.resolver,
        request.required_consensus_annotations,
        request.required_consensus_reviewers,
    )

    before = {
        "mode": batch.mode,
        "resolver": batch.resolver,
        "annotator_ids": await annotator_ids(session, batch),
        "required_consensus_annotations": batch.required_consensus_annotations,
        "required_consensus_reviewers": batch.required_consensus_reviewers,
    }

    await session.execute(
        delete(AnnotationBatchAnnotator).where(
            AnnotationBatchAnnotator.batch_id == batch.id
        )
    )
    for position, user_id in enumerate(requested_ids):
        session.add(
            AnnotationBatchAnnotator(
                batch_id=batch.id, user_id=user_id, position=position
            )
        )

    batch.mode = mode.value
    batch.required_consensus_annotations = request.required_consensus_annotations
    batch.required_consensus_reviewers = request.required_consensus_reviewers
    batch.resolver = request.resolver
    batch.parameters = dict(request.parameters)
    batch.review_thresholds = dict(request.review_thresholds)

    audit.record(
        session,
        actor,
        project.id,
        "batch.policy_updated",
        "annotation_batch",
        batch.id,
        before=before,
        after={
            "mode": mode.value,
            "resolver": request.resolver,
            "annotator_ids": requested_ids,
            "required_consensus_annotations": request.required_consensus_annotations,
            "required_consensus_reviewers": request.required_consensus_reviewers,
        },
    )
    await session.commit()
    await session.refresh(batch)
    return batch


async def start(
    session: AsyncSession,
    actor: User,
    project: Project,
    batch: AnnotationBatch,
) -> AnnotationBatch:
    """Freeze a batch's policy and generate its assignments atomically.

    A consensus batch produces one assignment per selected cohort member per
    item. A single-mode batch produces one assignment per item, dealt in turn
    to the snapshotted group, or to every member allowed to annotate when the
    group is empty. Every assignment therefore has an owner the moment it
    exists, and nobody ever claims work.

    Only an active project distributes work. Activation is what closes the
    label-import review, so starting a prepared draft's batch would hand out
    assignments before their seeds are settled. Each assignment's draft starts
    as a copy of its image's accepted imported seed.

    Validation happens before any assignment is created and everything commits
    together, so a refused start leaves no partial work behind.

    Args:
        session: Active database session.
        actor: User starting the batch.
        project: Project owning the batch.
        batch: Batch being started.

    Returns:
        The started batch.

    Raises:
        ApiError: 409 when the batch already started or the project is not
            active, 422 when the snapshotted group is no longer valid for the
            project.
    """
    if batch.status != BatchStatus.preparing:
        raise ApiError(
            409,
            "batch_already_started",
            "The batch has already been started.",
            details={"status": batch.status},
        )
    if project.status != "active":
        raise ApiError(
            409,
            "project_not_active",
            "Assignments are distributed only after the project is activated.",
            details={"status": project.status},
        )

    mode = AnnotationMode(batch.mode)
    group = await annotator_ids(session, batch)
    await annotation_policy.validate_policy(
        session,
        project,
        mode,
        group,
        batch.resolver,
        batch.required_consensus_annotations,
        batch.required_consensus_reviewers,
    )

    items = (
        await session.execute(
            select(BatchItem.id, BatchItem.media_id, BatchItem.position)
            .join(Media, Media.id == BatchItem.media_id)
            .where(BatchItem.batch_id == batch.id)
            .order_by(Media.relative_path, Media.id)
        )
    ).all()
    seeds = await accepted_seeds(session, project)

    dealers = group or await annotation_members(session, project)
    assignments = 0
    for position, (item_id, media_id, item_position) in enumerate(items):
        owners = (
            cohort_selection.initial_cohort(
                group, item_position, batch.required_consensus_annotations
            )
            if mode is AnnotationMode.consensus
            else [dealers[position % len(dealers)]]
        )
        for cohort_position, annotator_id in enumerate(owners):
            assignment = seeded_assignment(item_id, annotator_id, seeds.get(media_id))
            session.add(assignment)
            if mode is AnnotationMode.consensus:
                await session.flush()
                session.add(
                    AnnotationItemAnnotator(
                        batch_item_id=item_id,
                        generation=1,
                        annotator_id=annotator_id,
                        assignment_id=assignment.id,
                        position=cohort_position,
                        pool_position=group.index(annotator_id),
                        selection_algorithm=cohort_selection.INITIAL_ALGORITHM,
                        ordered_pool=group,
                    )
                )
        assignments += len(owners)

    batch.status = BatchStatus.annotating
    batch.started_at = datetime.now(UTC)

    audit.record(
        session,
        actor,
        project.id,
        "batch.started",
        "annotation_batch",
        batch.id,
        after={
            "mode": mode.value,
            "annotator_ids": group,
            "required_consensus_annotations": batch.required_consensus_annotations,
            "required_consensus_reviewers": batch.required_consensus_reviewers,
            "items": len(items),
            "assignments": assignments,
            "seeded_items": sum(1 for _, media_id, _ in items if media_id in seeds),
        },
    )
    await session.commit()
    await session.refresh(batch)
    return batch
