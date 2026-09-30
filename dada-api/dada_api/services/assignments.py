"""Direct image assignments: queue, drafts, submissions, and manager actions.

Nothing here claims or leases an image. An assignment belongs to its annotator
from the moment its batch starts, and several annotators may work the same
image at once, each on their own assignment.

Every write locks the assignment and its batch item, so two submissions for
the same image are serialised and the last one reliably marks readiness.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.cursors import decode_cursor, encode_cursor
from dada_api.core.errors import ApiError
from dada_api.models.annotation import (
    SINGLE_SUBMISSION_SOURCE,
    AnnotationSubmission,
    ResolvedAnnotation,
)
from dada_api.models.annotation_policy import AnnotationMode
from dada_api.models.batch import (
    ACTIVE_ASSIGNMENT_STATUSES,
    AnnotationAssignment,
    AnnotationBatch,
    AssignmentStatus,
    BatchItem,
    BatchStatus,
    ItemStatus,
)
from dada_api.models.label_import import ImportedSeedDocument
from dada_api.models.media import ContentObject, Media
from dada_api.models.project import Project, ProjectClass
from dada_api.models.user import User
from dada_api.schemas.assignment import DocumentWrite
from dada_api.services import annotation_documents, audit, batches, datasets

PAGE_SIZE = 50
OPEN_STATUSES = (AssignmentStatus.pending, AssignmentStatus.in_progress)


@dataclass(frozen=True)
class OpenedAssignment:
    """Everything the annotator needs to work on one assignment."""

    assignment: AnnotationAssignment
    batch: AnnotationBatch
    media: Media
    content: ContentObject
    latest: AnnotationSubmission | None


async def list_queue(
    session: AsyncSession,
    user: User,
    project: Project,
    purpose: str | None,
    state: str | None,
    cursor: str | None,
) -> tuple[list[tuple], str | None, dict[str, int]]:
    """List the caller's own active assignments in a stable order.

    The order follows the batches as they were created, then the image paths,
    so every annotator walks their work in the same predictable sequence.

    Args:
        session: Active database session.
        user: The annotator.
        project: Authorized project.
        purpose: Optional batch purpose filter.
        state: Optional assignment status filter.
        cursor: Opaque cursor from a previous page.

    Returns:
        The page of ``(assignment, batch, media, content)`` rows, the next
        cursor, and the caller's counts by status.
    """
    order = (
        AnnotationBatch.created_at,
        AnnotationBatch.id,
        Media.relative_path,
        AnnotationAssignment.id,
    )
    query = (
        select(AnnotationAssignment, AnnotationBatch, Media, ContentObject)
        .join(BatchItem, BatchItem.id == AnnotationAssignment.batch_item_id)
        .join(AnnotationBatch, AnnotationBatch.id == BatchItem.batch_id)
        .join(Media, Media.id == BatchItem.media_id)
        .join(ContentObject, ContentObject.id == Media.content_object_id)
        .where(
            AnnotationBatch.project_id == project.id,
            AnnotationAssignment.annotator_id == user.id,
            AnnotationAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
        )
        .order_by(*order)
    )
    if purpose is not None:
        query = query.where(AnnotationBatch.purpose == purpose)
    if state is not None:
        query = query.where(AnnotationAssignment.status == state)
    if cursor is not None:
        position = decode_cursor(cursor)
        query = query.where(
            tuple_(*order)
            > tuple_(
                datetime.fromisoformat(str(position["created_at"])),
                position["batch_id"],
                position["path"],
                position["id"],
            )
        )

    rows = [tuple(row) for row in await session.execute(query.limit(PAGE_SIZE + 1))]
    next_cursor = None
    if len(rows) > PAGE_SIZE:
        rows = rows[:PAGE_SIZE]
        assignment, batch, media, _ = rows[-1]
        next_cursor = encode_cursor(
            {
                "created_at": batch.created_at.isoformat(),
                "batch_id": batch.id,
                "path": media.relative_path,
                "id": assignment.id,
            }
        )

    counts = dict(
        (
            await session.execute(
                select(AnnotationAssignment.status, func.count())
                .join(BatchItem, BatchItem.id == AnnotationAssignment.batch_item_id)
                .join(AnnotationBatch, AnnotationBatch.id == BatchItem.batch_id)
                .where(
                    AnnotationBatch.project_id == project.id,
                    AnnotationAssignment.annotator_id == user.id,
                )
                .group_by(AnnotationAssignment.status)
            )
        ).all()
    )
    return (
        rows,
        next_cursor,
        {status: counts.get(status, 0) for status in ACTIVE_ASSIGNMENT_STATUSES},
    )


async def _load(
    session: AsyncSession,
    project: Project,
    assignment_id: str,
    *,
    lock: bool,
) -> tuple[AnnotationAssignment, BatchItem, AnnotationBatch]:
    """Return one of a project's assignments with its item and batch.

    Raises:
        ApiError: 404 when the project has no such assignment.
    """
    query = (
        select(AnnotationAssignment, BatchItem, AnnotationBatch)
        .join(BatchItem, BatchItem.id == AnnotationAssignment.batch_item_id)
        .join(AnnotationBatch, AnnotationBatch.id == BatchItem.batch_id)
        .where(
            AnnotationAssignment.id == assignment_id,
            AnnotationBatch.project_id == project.id,
        )
    )
    if lock:
        query = query.with_for_update(of=[AnnotationAssignment, BatchItem])
    row = (await session.execute(query)).first()
    if row is None:
        raise ApiError(404, "not_found", "The assignment does not exist.")
    assignment, item, batch = row
    return assignment, item, batch


async def _load_owned(
    session: AsyncSession,
    user: User,
    project: Project,
    assignment_id: str,
    *,
    lock: bool,
) -> tuple[AnnotationAssignment, BatchItem, AnnotationBatch]:
    """Return an assignment only to its own annotator.

    Administrators and managers included: an assignment's work is private to
    its annotator, and managers inspect evidence through their own routes.

    Raises:
        ApiError: 404 when missing, 403 when it belongs to someone else.
    """
    assignment, item, batch = await _load(session, project, assignment_id, lock=lock)
    if assignment.annotator_id != user.id:
        raise ApiError(
            403,
            "assignment_not_owned",
            "The assignment belongs to another annotator.",
        )
    return assignment, item, batch


async def _latest_submission(
    session: AsyncSession, assignment: AnnotationAssignment
) -> AnnotationSubmission | None:
    """Return an assignment's most recent submission revision, if any."""
    return await session.scalar(
        select(AnnotationSubmission)
        .where(AnnotationSubmission.assignment_id == assignment.id)
        .order_by(AnnotationSubmission.revision.desc())
        .limit(1)
    )


async def open_assignment(
    session: AsyncSession,
    user: User,
    project: Project,
    assignment_id: str,
) -> OpenedAssignment:
    """Return the caller's assignment with its image and current work.

    Opening changes nothing: it neither claims the image nor hides it from the
    other annotators assigned to it.

    Args:
        session: Active database session.
        user: The annotator.
        project: Authorized project.
        assignment_id: Assignment being opened.

    Returns:
        The assignment, its batch, its image, and its latest submission.
    """
    assignment, item, batch = await _load_owned(
        session, user, project, assignment_id, lock=False
    )
    media, content = (
        await session.execute(
            select(Media, ContentObject)
            .join(ContentObject, ContentObject.id == Media.content_object_id)
            .where(Media.id == item.media_id)
        )
    ).one()
    latest = await _latest_submission(session, assignment)
    return OpenedAssignment(assignment, batch, media, content, latest)


def _require_open(assignment: AnnotationAssignment) -> None:
    """Refuse work on an assignment that is submitted or no longer active.

    Raises:
        ApiError: 409 when the assignment cannot take new work.
    """
    if assignment.status == AssignmentStatus.submitted:
        raise ApiError(
            409,
            "assignment_already_submitted",
            "The assignment has already been submitted.",
            details={"version": assignment.version},
        )
    if assignment.status not in OPEN_STATUSES:
        raise ApiError(
            409,
            "assignment_not_active",
            "The assignment was reassigned or cancelled.",
            details={"status": assignment.status},
        )


def _require_version(assignment: AnnotationAssignment, version: int) -> None:
    """Refuse a write based on a version that is no longer current.

    Raises:
        ApiError: 409 when the caller's version is stale.
    """
    if version != assignment.version:
        raise ApiError(
            409,
            "version_conflict",
            "The assignment changed since it was read.",
            details={"expected_version": assignment.version},
        )


async def save_draft(
    session: AsyncSession,
    user: User,
    project: Project,
    assignment_id: str,
    request: DocumentWrite,
) -> AnnotationAssignment:
    """Store the annotator's unfinished work as their new draft.

    A draft is checked only for structure, so incomplete work can always be
    saved; the task and geometry rules apply at submission.

    Args:
        session: Active database session.
        user: The annotator.
        project: Authorized project.
        assignment_id: Assignment being saved.
        request: The complete draft and the version it was based on.

    Returns:
        The assignment with its new version.

    Raises:
        ApiError: 409 when submitted, inactive, or stale.
    """
    assignment, _, _ = await _load_owned(
        session, user, project, assignment_id, lock=True
    )
    _require_open(assignment)
    _require_version(assignment, request.version)

    assignment.draft = [item.model_dump() for item in request.objects]
    assignment.draft_saved_at = datetime.now(UTC)
    assignment.status = AssignmentStatus.in_progress
    assignment.version += 1
    await session.commit()
    await session.refresh(assignment)
    return assignment


async def submit(
    session: AsyncSession,
    user: User,
    project: Project,
    assignment_id: str,
    request: DocumentWrite,
) -> tuple[AnnotationAssignment, AnnotationSubmission, bool]:
    """Record the annotator's final document as an immutable submission.

    In single mode the submission is the canonical resolution of its image,
    written in the same transaction. In consensus mode the image becomes ready
    for resolution only once every active assignment on it has submitted;
    imported seeds never count, only annotator submissions do.

    Args:
        session: Active database session.
        user: The annotator.
        project: Authorized project.
        assignment_id: Assignment being submitted.
        request: The final document and the version it was based on.

    Returns:
        The assignment, the new submission, and whether the image is resolved.

    Raises:
        ApiError: 409 when already submitted, inactive, or stale; 422 when the
            document breaks a task or geometry rule.
    """
    assignment, item, batch = await _load_owned(
        session, user, project, assignment_id, lock=True
    )
    _require_open(assignment)
    _require_version(assignment, request.version)

    objects = [entry.model_dump() for entry in request.objects]
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
            "The annotation document breaks the task or geometry rules.",
            details={"errors": [asdict(error) for error in errors]},
        )

    latest = await _latest_submission(session, assignment)
    digest = annotation_documents.content_hash(objects)
    submission = AnnotationSubmission(
        assignment_id=assignment.id,
        revision=latest.revision + 1 if latest else 1,
        objects=objects,
        content_hash=digest,
        seed_document_id=assignment.seed_document_id,
        submitted_by=user.id,
    )
    session.add(submission)
    assignment.status = AssignmentStatus.submitted
    assignment.draft = None
    assignment.version += 1
    await session.flush()

    resolved = batch.mode == AnnotationMode.single
    if resolved:
        session.add(
            ResolvedAnnotation(
                batch_item_id=item.id,
                version=1,
                source=SINGLE_SUBMISSION_SOURCE,
                submission_id=submission.id,
                objects=objects,
                content_hash=digest,
            )
        )
        item.status = ItemStatus.resolved
        await session.flush()
        await _resolve_batch_if_done(session, batch)
    else:
        await _refresh_readiness(session, item)

    await session.commit()
    await session.refresh(assignment)
    await session.refresh(submission)
    return assignment, submission, resolved


async def _refresh_readiness(session: AsyncSession, item: BatchItem) -> None:
    """Mark an unresolved image ready once every active assignment submitted."""
    if item.status in (ItemStatus.resolved, ItemStatus.cancelled):
        return
    open_work = await session.scalar(
        select(func.count())
        .select_from(AnnotationAssignment)
        .where(
            AnnotationAssignment.batch_item_id == item.id,
            AnnotationAssignment.status.in_(OPEN_STATUSES),
        )
    )
    item.status = ItemStatus.pending if open_work else ItemStatus.awaiting_resolution


async def _resolve_batch_if_done(session: AsyncSession, batch: AnnotationBatch) -> None:
    """Move an annotating batch to ``resolved`` once no image is left open."""
    if batch.status != BatchStatus.annotating:
        return
    unresolved = await session.scalar(
        select(func.count())
        .select_from(BatchItem)
        .where(
            BatchItem.batch_id == batch.id,
            BatchItem.status.not_in((ItemStatus.resolved, ItemStatus.cancelled)),
        )
    )
    if not unresolved:
        batch.status = BatchStatus.resolved


async def list_batch_assignments(
    session: AsyncSession,
    project: Project,
    batch_id: str,
    cursor: str | None,
) -> tuple[list[tuple], str | None]:
    """List every assignment of a batch for a manager, without document content.

    Reassigned and cancelled assignments are included, because they are the
    history of who was asked to annotate what.

    Args:
        session: Active database session.
        project: Authorized project.
        batch_id: Batch being inspected.
        cursor: Opaque cursor from a previous page.

    Returns:
        The page of ``(assignment, item, media)`` rows and the next cursor.
    """
    batch = await batches.get_batch(session, project, batch_id)
    order = (
        Media.relative_path,
        AnnotationAssignment.created_at,
        AnnotationAssignment.id,
    )
    query = (
        select(AnnotationAssignment, BatchItem, Media)
        .join(BatchItem, BatchItem.id == AnnotationAssignment.batch_item_id)
        .join(Media, Media.id == BatchItem.media_id)
        .where(BatchItem.batch_id == batch.id)
        .order_by(*order)
    )
    if cursor is not None:
        position = decode_cursor(cursor)
        query = query.where(
            tuple_(*order)
            > tuple_(
                position["path"],
                datetime.fromisoformat(str(position["created_at"])),
                position["id"],
            )
        )

    rows = [tuple(row) for row in await session.execute(query.limit(PAGE_SIZE + 1))]
    if len(rows) <= PAGE_SIZE:
        return rows, None
    rows = rows[:PAGE_SIZE]
    assignment, _, media = rows[-1]
    return rows, encode_cursor(
        {
            "path": media.relative_path,
            "created_at": assignment.created_at.isoformat(),
            "id": assignment.id,
        }
    )


async def manager_row(
    session: AsyncSession,
    project: Project,
    assignment_id: str,
) -> tuple[AnnotationAssignment, BatchItem, Media]:
    """Return one assignment with its item and image, as a manager lists it."""
    assignment, item, _ = await _load(session, project, assignment_id, lock=False)
    media = await session.get(Media, item.media_id)
    return assignment, item, media


def _require_unresolved(item: BatchItem) -> None:
    """Refuse to change the work of an image that already has a resolution.

    Raises:
        ApiError: 409 when the image is resolved or cancelled.
    """
    if item.status in (ItemStatus.resolved, ItemStatus.cancelled):
        raise ApiError(
            409,
            "item_closed",
            "The image is already resolved or cancelled.",
            details={"item_status": item.status},
        )


async def reopen(
    session: AsyncSession,
    actor: User,
    project: Project,
    assignment_id: str,
) -> AnnotationAssignment:
    """Give a submitted assignment back to its annotator for correction.

    The submission stays as it was; the draft starts from it, and the next
    submission becomes a new revision. The version changes, so a tab still
    holding the submitted state is told to refresh.

    Args:
        session: Active database session.
        actor: Manager reopening the work.
        project: Authorized project.
        assignment_id: Submitted assignment.

    Returns:
        The reopened assignment.

    Raises:
        ApiError: 409 when the assignment is not submitted or its image is
            already resolved.
    """
    assignment, item, _ = await _load(session, project, assignment_id, lock=True)
    if assignment.status != AssignmentStatus.submitted:
        raise ApiError(
            409,
            "assignment_not_submitted",
            "Only a submitted assignment can be reopened.",
            details={"status": assignment.status},
        )
    _require_unresolved(item)

    latest = await _latest_submission(session, assignment)
    assignment.draft = list(latest.objects)
    assignment.draft_saved_at = datetime.now(UTC)
    assignment.status = AssignmentStatus.in_progress
    assignment.version += 1
    await session.flush()
    await _refresh_readiness(session, item)

    audit.record(
        session,
        actor,
        project.id,
        "assignment.reopened",
        "annotation_assignment",
        assignment.id,
        after={"annotator_id": assignment.annotator_id, "revision": latest.revision},
    )
    await session.commit()
    await session.refresh(assignment)
    return assignment


async def reassign(
    session: AsyncSession,
    actor: User,
    project: Project,
    assignment_id: str,
    annotator_id: str,
) -> AnnotationAssignment:
    """Move an image's work from one annotator to another.

    The old assignment is kept, with its draft and submissions, as evidence.
    The new annotator starts afresh from the image's imported seed, if any,
    never from the previous annotator's work.

    Args:
        session: Active database session.
        actor: Manager reassigning the work.
        project: Authorized project.
        assignment_id: Assignment being taken away.
        annotator_id: Member receiving the image.

    Returns:
        The new assignment.

    Raises:
        ApiError: 409 when the assignment is inactive, the image is resolved,
            or the target already holds this image; 422 when the target may
            not annotate the project.
    """
    assignment, item, _ = await _load(session, project, assignment_id, lock=True)
    if assignment.status not in ACTIVE_ASSIGNMENT_STATUSES:
        raise ApiError(
            409,
            "assignment_not_active",
            "The assignment was already reassigned or cancelled.",
            details={"status": assignment.status},
        )
    _require_unresolved(item)
    if annotator_id not in await batches.annotation_members(session, project):
        raise ApiError(
            422,
            "invalid_assignee",
            "The new annotator must be a project member allowed to annotate.",
        )
    held = await session.scalar(
        select(func.count())
        .select_from(AnnotationAssignment)
        .where(
            AnnotationAssignment.batch_item_id == item.id,
            AnnotationAssignment.annotator_id == annotator_id,
        )
    )
    if held:
        raise ApiError(
            409,
            "already_assigned",
            "That annotator already holds this image.",
        )

    seed = (
        await session.get(ImportedSeedDocument, assignment.seed_document_id)
        if assignment.seed_document_id
        else None
    )
    replacement = batches.seeded_assignment(item.id, annotator_id, seed)
    session.add(replacement)
    previous = assignment.annotator_id
    assignment.status = AssignmentStatus.reassigned
    assignment.version += 1
    await session.flush()
    await _refresh_readiness(session, item)

    audit.record(
        session,
        actor,
        project.id,
        "assignment.reassigned",
        "annotation_assignment",
        assignment.id,
        before={"annotator_id": previous},
        after={"annotator_id": annotator_id, "assignment_id": replacement.id},
    )
    await session.commit()
    await session.refresh(replacement)
    return replacement


async def cancel_item(
    session: AsyncSession,
    actor: User,
    project: Project,
    item_id: str,
) -> None:
    """Withdraw an unresolved training image and return it to the pool.

    The whole image is cancelled, not one assignment: dropping one of a
    consensus group's assignments would leave the image short of its required
    submissions. Validation and test images form fixed held-out sets and are
    never cancelled.

    Args:
        session: Active database session.
        actor: Manager cancelling the image.
        project: Authorized project.
        item_id: Batch item being cancelled.

    Raises:
        ApiError: 404 when missing; 409 outside a training batch or when the
            image is already resolved or cancelled.
    """
    row = (
        await session.execute(
            select(BatchItem, AnnotationBatch)
            .join(AnnotationBatch, AnnotationBatch.id == BatchItem.batch_id)
            .where(BatchItem.id == item_id, AnnotationBatch.project_id == project.id)
            .with_for_update(of=BatchItem)
        )
    ).first()
    if row is None:
        raise ApiError(404, "not_found", "The batch item does not exist.")
    item, batch = row
    if batch.purpose not in datasets.TRAINING_PURPOSES:
        raise ApiError(
            409,
            "cancel_not_allowed",
            "Only training images can be cancelled and returned to the pool.",
            details={"purpose": batch.purpose},
        )
    _require_unresolved(item)

    await session.execute(
        update(AnnotationAssignment)
        .where(
            AnnotationAssignment.batch_item_id == item.id,
            AnnotationAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
        )
        .values(
            status=AssignmentStatus.cancelled,
            version=AnnotationAssignment.version + 1,
            updated_at=datetime.now(UTC),
        )
    )
    item.status = ItemStatus.cancelled
    await session.flush()
    await _resolve_batch_if_done(session, batch)

    audit.record(
        session,
        actor,
        project.id,
        "batch_item.cancelled",
        "batch_item",
        item.id,
        after={"batch_id": batch.id, "media_id": item.media_id},
    )
    await session.commit()
