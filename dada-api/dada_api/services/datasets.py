"""Draft dataset preparation, reset, the eligible training pool, and readiness."""

from datetime import UTC, datetime
from math import ceil

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.errors import ApiError
from dada_api.models.batch import (
    AnnotationBatch,
    BatchItem,
    BatchPurpose,
    BatchStatus,
    ItemStatus,
)
from dada_api.models.dataset import DatasetSplit, SplitName
from dada_api.models.label_import import AnnotationImport
from dada_api.models.media import Media
from dada_api.models.project import DatasetLayout, Project, ProjectClass
from dada_api.models.user import User
from dada_api.services import audit, batches

INITIAL_SPLIT_PURPOSES = (
    BatchPurpose.initial_training,
    BatchPurpose.validation,
    BatchPurpose.test,
)
TRAINING_PURPOSES = (BatchPurpose.initial_training, BatchPurpose.acquisition)
FINISHED_BATCH_STATUSES = (BatchStatus.closed, BatchStatus.failed)


def resolve_split_size(
    total_media: int,
    absolute_size: int | None,
    percentage: float | None,
) -> int:
    """Resolve a held-out split definition to an absolute count."""
    if percentage is not None:
        return ceil(total_media * percentage / 100)
    if absolute_size is None:
        raise ValueError("a split count or percentage is required")
    return absolute_size


def resolved_first_training_size(project: Project) -> int | None:
    """Return the size of a split project's first training batch.

    ``initial_training_size`` is an optional override. Without it the first
    training batch has the same size as every later acquisition batch.
    """
    if project.initial_training_size is not None:
        return project.initial_training_size
    return project.iteration_batch_size


def _sizes_defined(project: Project) -> bool:
    """Return whether a split project defines every size it needs."""
    return (
        project.iteration_batch_size is not None
        and (project.test_set_size is None) != (project.test_set_percentage is None)
        and (project.validation_set_size is None)
        != (project.validation_set_percentage is None)
    )


async def ordered_media_ids(session: AsyncSession, project: Project) -> list[str]:
    """Return a project's media identifiers in the deterministic listing order.

    The order matches the media inventory route, so a recorded selection input
    can be reproduced from what a client can already read.
    """
    return list(
        await session.scalars(
            select(Media.id)
            .where(Media.project_id == project.id)
            .order_by(Media.relative_path, Media.id)
        )
    )


async def missing_preparation_prerequisites(
    session: AsyncSession,
    project: Project,
) -> list[str]:
    """Return the prerequisites a draft still fails before it can be prepared.

    Capacity is checked against the held-out sets and the first training batch
    only. The rest of the train split stays in the unlabeled pool, so it needs
    no capacity of its own.

    Args:
        session: Active database session.
        project: Project being checked.

    Returns:
        Stable prerequisite names, empty when the dataset may be prepared.
    """
    missing: list[str] = []

    class_count = await session.scalar(
        select(func.count())
        .select_from(ProjectClass)
        .where(ProjectClass.project_id == project.id)
    )
    if not class_count:
        missing.append("classes")

    media_count = (
        await session.scalar(
            select(func.count())
            .select_from(Media)
            .where(Media.project_id == project.id)
        )
        or 0
    )
    if not media_count:
        missing.append("media")

    if project.dataset_layout == DatasetLayout.single_batch:
        return missing

    if not _sizes_defined(project):
        missing.append("split_sizes")
        return missing

    test_size, validation_size = _held_out_sizes(project, media_count)
    first_size = resolved_first_training_size(project) or 0
    if media_count and media_count < test_size + validation_size + first_size:
        missing.append("insufficient_media")
    return missing


def _held_out_sizes(project: Project, media_count: int) -> tuple[int, int]:
    """Return the resolved test and validation counts for a media total."""
    return (
        resolve_split_size(
            media_count, project.test_set_size, project.test_set_percentage
        ),
        resolve_split_size(
            media_count,
            project.validation_set_size,
            project.validation_set_percentage,
        ),
    )


def _require_draft(project: Project) -> None:
    """Refuse to change the preparation of a project that left ``draft``.

    Raises:
        ApiError: 409 when the project is no longer a draft.
    """
    if project.status != "draft":
        raise ApiError(
            409,
            "project_not_draft",
            "Only a draft project's dataset can be prepared or reset.",
            details={"status": project.status},
        )


async def prepare(session: AsyncSession, actor: User, project: Project) -> Project:
    """Materialise a draft's layout, its first batches, and their policy copies.

    A ``split`` project draws test from the whole inventory, validation from
    the remainder, and the first training batch from what is left. Train items
    not drawn stay in the unlabeled pool with no batch item. A
    ``single_batch`` project opens one batch covering every image and writes
    no split rows.

    Everything commits together, and nothing changes until activation or an
    explicit reset.

    Args:
        session: Active database session.
        actor: User preparing the dataset.
        project: Authorized project.

    Returns:
        The prepared project.

    Raises:
        ApiError: 409 when the project is not a draft, is already prepared, or
            fails a preparation prerequisite.
    """
    _require_draft(project)
    if project.dataset_prepared_at is not None:
        raise ApiError(
            409,
            "dataset_already_prepared",
            "The dataset is already prepared; reset it before preparing again.",
        )

    missing = await missing_preparation_prerequisites(session, project)
    if missing:
        raise ApiError(
            409,
            "preparation_incomplete",
            "The project is not ready to prepare its dataset.",
            details={"missing": missing},
        )

    media_ids = await ordered_media_ids(session, project)
    if project.dataset_layout == DatasetLayout.single_batch:
        await batches.create_batch(
            session,
            project,
            BatchPurpose.initial_annotation,
            media_ids,
            len(media_ids),
        )
    else:
        await _prepare_split(session, project, media_ids)

    project.dataset_prepared_at = datetime.now(UTC)
    audit.record(
        session,
        actor,
        project.id,
        "dataset.prepared",
        "project",
        project.id,
        after={
            "dataset_layout": project.dataset_layout,
            "media": len(media_ids),
            "test_set_size": project.test_set_size,
            "validation_set_size": project.validation_set_size,
            "first_training_batch_size": resolved_first_training_size(project),
        },
    )
    await session.commit()
    await session.refresh(project)
    return project


async def _prepare_split(
    session: AsyncSession,
    project: Project,
    media_ids: list[str],
) -> None:
    """Draw the three-way split and open its three initial batches."""
    test_size, validation_size = _held_out_sizes(project, len(media_ids))
    project.test_set_size = test_size
    project.validation_set_size = validation_size

    test_ids = set(
        await batches.create_batch(
            session, project, BatchPurpose.test, media_ids, test_size
        )
    )
    after_test = [media_id for media_id in media_ids if media_id not in test_ids]
    validation_ids = set(
        await batches.create_batch(
            session, project, BatchPurpose.validation, after_test, validation_size
        )
    )
    train_ids = [media_id for media_id in after_test if media_id not in validation_ids]
    await batches.create_batch(
        session,
        project,
        BatchPurpose.initial_training,
        train_ids,
        resolved_first_training_size(project) or 0,
    )

    for media_id in media_ids:
        split = SplitName.train
        if media_id in test_ids:
            split = SplitName.test
        elif media_id in validation_ids:
            split = SplitName.validation
        session.add(DatasetSplit(project_id=project.id, media_id=media_id, split=split))


async def reset_prepared(
    session: AsyncSession,
    actor: User,
    project: Project,
    reason: str,
) -> None:
    """Discard a draft's preparation and its label import, without committing.

    The caller commits, so a class or media change and the reset it causes
    reach the database together or not at all. Percentage-backed held-out
    counts return to ``NULL`` so the next preparation recomputes them.

    Args:
        session: Active database session, committed by the caller.
        actor: User whose change caused the reset.
        project: Prepared draft project.
        reason: ``manual``, ``classes_changed``, or ``media_changed``.
    """
    await session.execute(
        delete(AnnotationBatch).where(AnnotationBatch.project_id == project.id)
    )
    await session.execute(
        delete(DatasetSplit).where(DatasetSplit.project_id == project.id)
    )
    await session.execute(
        delete(AnnotationImport).where(AnnotationImport.project_id == project.id)
    )
    if project.test_set_percentage is not None:
        project.test_set_size = None
    if project.validation_set_percentage is not None:
        project.validation_set_size = None
    project.dataset_prepared_at = None
    audit.record(
        session,
        actor,
        project.id,
        "dataset.reset",
        "project",
        project.id,
        after={"reason": reason},
    )


async def reset_if_prepared(
    session: AsyncSession,
    actor: User,
    project: Project,
    reason: str,
) -> None:
    """Reset a prepared draft whose layout inputs are changing.

    Classes and media are preparation inputs: once they change, the prepared
    layout and any import validated against it no longer describe the project.
    """
    if project.status == "draft" and project.dataset_prepared_at is not None:
        await reset_prepared(session, actor, project, reason)


async def reset(session: AsyncSession, actor: User, project: Project) -> None:
    """Discard a draft's preparation on explicit request.

    Args:
        session: Active database session.
        actor: User resetting the dataset.
        project: Authorized project.

    Raises:
        ApiError: 409 when the project is not a draft or is not prepared.
    """
    _require_draft(project)
    if project.dataset_prepared_at is None:
        raise ApiError(409, "dataset_not_prepared", "The dataset is not prepared.")
    await reset_prepared(session, actor, project, "manual")
    await session.commit()


async def eligible_training_pool(
    session: AsyncSession,
    project: Project,
) -> list[str]:
    """Return the train-split media a later training batch may select.

    A train image leaves the pool while a live training batch holds it and for
    good once its item is resolved. A cancelled item, or one left unresolved in
    a closed or failed batch, returns its image to the pool. Validation and
    test media are never in it because they are not in the train split.

    Args:
        session: Active database session.
        project: Project being inspected.

    Returns:
        Eligible media identifiers in the deterministic listing order.
    """
    held = (
        select(BatchItem.media_id)
        .join(AnnotationBatch, AnnotationBatch.id == BatchItem.batch_id)
        .where(
            AnnotationBatch.project_id == project.id,
            AnnotationBatch.purpose.in_(TRAINING_PURPOSES),
            or_(
                BatchItem.status == ItemStatus.resolved,
                and_(
                    AnnotationBatch.status.not_in(FINISHED_BATCH_STATUSES),
                    BatchItem.status != ItemStatus.cancelled,
                ),
            ),
        )
    )
    return list(
        await session.scalars(
            select(Media.id)
            .join(DatasetSplit, DatasetSplit.media_id == Media.id)
            .where(
                DatasetSplit.project_id == project.id,
                DatasetSplit.split == SplitName.train,
                Media.id.not_in(held),
            )
            .order_by(Media.relative_path, Media.id)
        )
    )


async def first_acquisition_ready(
    session: AsyncSession,
    project: Project,
) -> bool:
    """Return whether every initial image has an accepted canonical resolution.

    Submitted assignments are not enough: an image counts only once its item
    is resolved, which single mode does from its submission and consensus mode
    does through consensus or adjudication. A cancelled training image went
    back to the pool, so it no longer holds the first acquisition back. A
    ``single_batch`` project never acquires, so it is never ready.
    """
    if project.dataset_layout != DatasetLayout.split:
        return False

    purposes = set(
        await session.scalars(
            select(AnnotationBatch.purpose).where(
                AnnotationBatch.project_id == project.id,
                AnnotationBatch.purpose.in_(INITIAL_SPLIT_PURPOSES),
            )
        )
    )
    if purposes != set(INITIAL_SPLIT_PURPOSES):
        return False

    unresolved = await session.scalar(
        select(func.count())
        .select_from(BatchItem)
        .join(AnnotationBatch, AnnotationBatch.id == BatchItem.batch_id)
        .where(
            AnnotationBatch.project_id == project.id,
            AnnotationBatch.purpose.in_(INITIAL_SPLIT_PURPOSES),
            BatchItem.status.not_in((ItemStatus.resolved, ItemStatus.cancelled)),
        )
    )
    return unresolved == 0


async def layout_summary(session: AsyncSession, project: Project) -> dict:
    """Return the prepared layout's sizes, batches, pool, and import.

    Args:
        session: Active database session.
        project: Authorized project.

    Returns:
        Fields of the dataset-layout representation.
    """
    split_counts = dict(
        (
            await session.execute(
                select(DatasetSplit.split, func.count())
                .where(DatasetSplit.project_id == project.id)
                .group_by(DatasetSplit.split)
            )
        ).all()
    )
    batch_ids = list(
        await session.scalars(
            select(AnnotationBatch.id)
            .where(AnnotationBatch.project_id == project.id)
            .order_by(AnnotationBatch.created_at, AnnotationBatch.id)
        )
    )
    import_id = await session.scalar(
        select(AnnotationImport.id).where(AnnotationImport.project_id == project.id)
    )
    first_size = (
        resolved_first_training_size(project)
        if project.dataset_layout == DatasetLayout.split
        else None
    )
    return {
        "dataset_layout": project.dataset_layout,
        "prepared_at": project.dataset_prepared_at,
        "train_size": split_counts.get(SplitName.train, 0),
        "validation_size": split_counts.get(SplitName.validation, 0),
        "test_size": split_counts.get(SplitName.test, 0),
        "first_training_batch_size": first_size,
        "training_pool_size": len(await eligible_training_pool(session, project)),
        "batch_ids": batch_ids,
        "annotation_import_id": import_id,
    }
