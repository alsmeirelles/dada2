"""Project creation, listing, versioned update, activation checks, and deletion."""

import logging
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.cursors import decode_cursor, encode_cursor
from dada_api.core.errors import ApiError
from dada_api.models.annotation_policy import AnnotationMode, AnnotationPolicyDefault
from dada_api.models.label_import import AnnotationImport, ImportStatus
from dada_api.models.project import Project, ProjectMember, ProjectRole
from dada_api.models.user import User
from dada_api.schemas.project import ProjectCreate, ProjectUpdate
from dada_api.services import datasets, storage

logger = logging.getLogger(__name__)

PAGE_SIZE = 50


async def create_project(
    session: AsyncSession,
    creator: User,
    request: ProjectCreate,
) -> Project:
    """Create a project owned by its creator.

    Project authority is resolved from membership, so the owner's membership
    row and the default annotation policy are written in the same transaction
    as the project itself.

    Args:
        session: Active database session.
        creator: Authenticated user creating the project.
        request: Validated creation request.

    Returns:
        The persisted project.
    """
    project = Project(
        name=request.name,
        description=request.description,
        task_type=request.task_type,
        status="draft",
        owner_id=creator.id,
        acquisition_strategy=request.acquisition_strategy,
        dataset_layout=request.dataset_layout,
        initial_training_size=request.initial_training_size,
        test_set_size=request.test_set_size,
        test_set_percentage=request.test_set_percentage,
        validation_set_size=request.validation_set_size,
        validation_set_percentage=request.validation_set_percentage,
        iteration_batch_size=request.iteration_batch_size,
        version=1,
    )
    session.add(project)
    await session.flush()

    session.add(
        ProjectMember(project_id=project.id, user_id=creator.id, role=ProjectRole.owner)
    )
    session.add(
        AnnotationPolicyDefault(
            project_id=project.id,
            mode=AnnotationMode.single,
            parameters={},
            review_thresholds={},
            version=1,
        )
    )
    await session.commit()
    await session.refresh(project)
    return project


async def list_projects(
    session: AsyncSession,
    user: User,
    cursor: str | None,
) -> tuple[list[Project], str | None]:
    """List the projects a user may read, newest first.

    Args:
        session: Active database session.
        user: Authenticated user.
        cursor: Opaque cursor from a previous page.

    Returns:
        The page of projects and the cursor for the next page, if any.
    """
    query = select(Project).order_by(Project.created_at.desc(), Project.id.desc())
    if not user.is_administrator:
        query = query.where(
            Project.id.in_(
                select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
            )
        )
    if cursor is not None:
        position = decode_cursor(cursor)
        created_at = datetime.fromisoformat(str(position["created_at"]))
        query = query.where(
            or_(
                Project.created_at < created_at,
                (Project.created_at == created_at) & (Project.id < position["id"]),
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


async def update_project(
    session: AsyncSession,
    project: Project,
    request: ProjectUpdate,
) -> Project:
    """Apply a versioned update to a project.

    Args:
        session: Active database session.
        project: Authorized project.
        request: Validated update request carrying the expected version.

    Returns:
        The updated project.

    Raises:
        ApiError: 409 when the supplied version is not the current one.
    """
    if request.version != project.version:
        raise ApiError(
            409,
            "version_conflict",
            "The project changed since it was read.",
            details={"expected_version": project.version},
        )

    fields = request.model_dump(exclude_unset=True, exclude={"version"})
    for name, value in fields.items():
        setattr(project, name, value)
    project.version += 1
    await session.commit()
    await session.refresh(project)
    return project


async def missing_activation_prerequisites(
    session: AsyncSession,
    project: Project,
) -> list[str]:
    """Return the prerequisites a project still fails before activation.

    An unprepared draft reports its preparation prerequisites followed by
    ``dataset_layout``. A prepared draft can only still be waiting on its label
    import, since any change to its inputs would have reset the preparation.

    Args:
        session: Active database session.
        project: Project being checked.

    Returns:
        Stable prerequisite names, empty when the project may be activated.
    """
    if project.dataset_prepared_at is None:
        missing = await datasets.missing_preparation_prerequisites(session, project)
        return [*missing, "dataset_layout"]

    pending_import = await session.scalar(
        select(func.count())
        .select_from(AnnotationImport)
        .where(
            AnnotationImport.project_id == project.id,
            AnnotationImport.status != ImportStatus.accepted,
        )
    )
    return ["label_import"] if pending_import else []


async def activate_project(session: AsyncSession, project: Project) -> Project:
    """Lock a prepared draft's layout and make its batches workable.

    Nothing is drawn here: preparation already materialised the split and the
    batches. Activation closes the label-import review, after which batches may
    start distributing assignments.

    Args:
        session: Active database session.
        project: Authorized project.

    Returns:
        The activated project.

    Raises:
        ApiError: 409 when the project is not a draft or a prerequisite fails.
    """
    if project.status != "draft":
        raise ApiError(
            409,
            "project_not_draft",
            "Only a draft project can be activated.",
            details={"status": project.status},
        )

    missing = await missing_activation_prerequisites(session, project)
    if missing:
        raise ApiError(
            409,
            "activation_incomplete",
            "The project is not ready to be activated.",
            details={"missing": missing},
        )

    project.status = "active"
    await session.commit()
    await session.refresh(project)
    return project


async def delete_project(session: AsyncSession, project: Project) -> None:
    """Permanently remove a project, its records, and its stored media.

    The database rows are committed first so a storage failure cannot leave
    rows describing media the API can no longer serve. The reverse order would
    turn a partial failure into a project that lists unreadable images, which
    is worse than the orphaned bytes this order can leave behind.

    There is no restore window: the deletion is terminal by design.

    Args:
        session: Active database session.
        project: Authorized project.
    """
    project_id = project.id
    await session.delete(project)
    await session.commit()

    try:
        storage.delete_project_media(project_id)
    except OSError:
        logger.error("Failed to purge stored media for project %s", project_id)
