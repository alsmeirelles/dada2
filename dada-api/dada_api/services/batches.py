"""Dataset freezing, batch policy snapshots, and assignment generation."""

from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.cursors import decode_cursor, encode_cursor
from dada_api.core.errors import ApiError
from dada_api.models.annotation_policy import AnnotationMode
from dada_api.models.batch import (
    ASSIGNMENT_PENDING,
    AnnotationAssignment,
    AnnotationBatch,
    AnnotationBatchAnnotator,
    BatchItem,
    BatchPurpose,
    BatchStatus,
)
from dada_api.models.dataset import DatasetSplit, SplitName
from dada_api.models.media import Media
from dada_api.models.project import Project
from dada_api.models.user import User
from dada_api.schemas.batch import BatchPolicyUpdate
from dada_api.services import annotation_policy, audit, selection

PAGE_SIZE = 50


async def _ordered_media_ids(session: AsyncSession, project: Project) -> list[str]:
    """Return a project's media identifiers in the deterministic listing order.

    The order matches the media inventory route, so the recorded selection
    input can be reproduced from what a client can already read.
    """
    return list(
        await session.scalars(
            select(Media.id)
            .where(Media.project_id == project.id)
            .order_by(Media.relative_path, Media.id)
        )
    )


async def _snapshot_policy(
    session: AsyncSession,
    project: Project,
    batch: AnnotationBatch,
) -> None:
    """Copy the project's default policy and group onto a new batch."""
    policy, annotator_ids = await annotation_policy.get_policy(session, project)
    batch.mode = policy.mode.value
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


async def _create_batch(
    session: AsyncSession,
    project: Project,
    purpose: BatchPurpose,
    candidates: list[str],
    size: int,
) -> AnnotationBatch:
    """Select media, create the batch that annotates it, and record how."""
    seed = selection.new_seed()
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

    for media_id in selection.choose(candidates, size, seed):
        session.add(BatchItem(batch_id=batch.id, media_id=media_id))
    return batch


async def freeze_and_create(
    session: AsyncSession,
    project: Project,
) -> list[AnnotationBatch]:
    """Freeze the train/test split and open the project's first two batches.

    The test half is drawn from the whole dataset first and the training set
    from what remains, so no image can reach both. That ordering is what makes
    the evaluation set genuinely held out rather than filtered out later.

    The caller commits, so a failure anywhere leaves the project untouched.

    Args:
        session: Active database session, committed by the caller.
        project: Project being activated.

    Returns:
        The test and initial-training batches, in that order.
    """
    media_ids = await _ordered_media_ids(session, project)
    test_ids = selection.choose(media_ids, project.test_set_size, selection.new_seed())
    held_out = set(test_ids)
    train_pool = [media_id for media_id in media_ids if media_id not in held_out]

    for media_id in media_ids:
        session.add(
            DatasetSplit(
                project_id=project.id,
                media_id=media_id,
                split=SplitName.test if media_id in held_out else SplitName.train,
            )
        )

    test_batch = await _create_batch(
        session, project, BatchPurpose.test, test_ids, project.test_set_size
    )
    training_batch = await _create_batch(
        session,
        project,
        BatchPurpose.initial_training,
        train_pool,
        project.initial_training_size,
    )
    return [test_batch, training_batch]


async def annotator_ids(session: AsyncSession, batch: AnnotationBatch) -> list[str]:
    """Return a batch's snapshotted group in its recorded order."""
    return list(
        await session.scalars(
            select(AnnotationBatchAnnotator.user_id)
            .where(AnnotationBatchAnnotator.batch_id == batch.id)
            .order_by(AnnotationBatchAnnotator.position)
        )
    )


async def counts(session: AsyncSession, batch: AnnotationBatch) -> tuple[int, int, int]:
    """Return a batch's item, assignment, and submitted-assignment counts.

    Args:
        session: Active database session.
        batch: Batch being measured.

    Returns:
        Total items, total assignments, and submitted assignments.
    """
    items = await session.scalar(
        select(func.count())
        .select_from(BatchItem)
        .where(BatchItem.batch_id == batch.id)
    )
    assignments = await session.scalar(
        select(func.count())
        .select_from(AnnotationAssignment)
        .join(BatchItem, BatchItem.id == AnnotationAssignment.batch_item_id)
        .where(BatchItem.batch_id == batch.id)
    )
    submitted = await session.scalar(
        select(func.count())
        .select_from(AnnotationAssignment)
        .join(BatchItem, BatchItem.id == AnnotationAssignment.batch_item_id)
        .where(
            BatchItem.batch_id == batch.id,
            AnnotationAssignment.status != ASSIGNMENT_PENDING,
        )
    )
    return items or 0, assignments or 0, submitted or 0


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
        session, project, mode, requested_ids, request.resolver
    )

    before = {
        "mode": batch.mode,
        "resolver": batch.resolver,
        "annotator_ids": await annotator_ids(session, batch),
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

    A consensus batch produces one assignment per snapshotted annotator per
    item. A single-mode batch produces one unclaimed assignment per item,
    because the policy names no owner and any eligible annotator may take it.

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
        ApiError: 409 when the batch already started, 422 when the snapshotted
            group is no longer valid for the project.
    """
    if batch.status != BatchStatus.preparing:
        raise ApiError(
            409,
            "batch_already_started",
            "The batch has already been started.",
            details={"status": batch.status},
        )

    mode = AnnotationMode(batch.mode)
    group = await annotator_ids(session, batch)
    await annotation_policy.validate_policy(
        session, project, mode, group, batch.resolver
    )

    item_ids = list(
        await session.scalars(
            select(BatchItem.id).where(BatchItem.batch_id == batch.id)
        )
    )
    owners: list[str | None] = (
        list(group) if mode is AnnotationMode.consensus else [None]
    )
    for item_id in item_ids:
        for owner in owners:
            session.add(AnnotationAssignment(batch_item_id=item_id, annotator_id=owner))

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
            "items": len(item_ids),
            "assignments": len(item_ids) * len(owners),
        },
    )
    await session.commit()
    await session.refresh(batch)
    return batch
