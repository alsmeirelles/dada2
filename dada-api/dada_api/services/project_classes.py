"""Ordered object-class management inside a project."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.cursors import decode_cursor, encode_cursor
from dada_api.core.errors import ApiError
from dada_api.models.project import Project, ProjectClass
from dada_api.schemas.project import ProjectClassCreate, ProjectClassUpdate

PAGE_SIZE = 200


def _conflict(error: IntegrityError) -> ApiError:
    """Map a class uniqueness violation to its stable error code.

    Args:
        error: Integrity error raised by the database.

    Returns:
        The API error describing which uniqueness rule failed.
    """
    if "uq_project_class_order" in str(error.orig):
        return ApiError(
            409, "duplicate_display_order", "Another class already uses that order."
        )
    return ApiError(409, "duplicate_class_name", "A class with that name exists.")


async def list_classes(
    session: AsyncSession,
    project: Project,
    cursor: str | None,
) -> tuple[list[ProjectClass], str | None]:
    """List a project's classes in display order.

    Args:
        session: Active database session.
        project: Authorized project.
        cursor: Opaque cursor from a previous page.

    Returns:
        The page of classes and the cursor for the next page, if any.
    """
    query = (
        select(ProjectClass)
        .where(ProjectClass.project_id == project.id)
        .order_by(ProjectClass.display_order, ProjectClass.id)
    )
    if cursor is not None:
        position = decode_cursor(cursor)
        query = query.where(ProjectClass.display_order > int(position["order"]))

    rows = list(await session.scalars(query.limit(PAGE_SIZE + 1)))
    if len(rows) <= PAGE_SIZE:
        return rows, None
    page = rows[:PAGE_SIZE]
    return page, encode_cursor({"order": page[-1].display_order})


async def create_class(
    session: AsyncSession,
    project: Project,
    request: ProjectClassCreate,
) -> ProjectClass:
    """Add a class to a project.

    Args:
        session: Active database session.
        project: Authorized project.
        request: Validated creation request.

    Returns:
        The persisted class.

    Raises:
        ApiError: 409 when the name or display order is already used.
    """
    item = ProjectClass(
        project_id=project.id,
        name=request.name,
        color=request.color,
        display_order=request.display_order,
        version=1,
    )
    session.add(item)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise _conflict(error) from error
    await session.refresh(item)
    return item


async def get_class(
    session: AsyncSession,
    project: Project,
    class_id: str,
) -> ProjectClass:
    """Return one class belonging to a project.

    Args:
        session: Active database session.
        project: Authorized project.
        class_id: Class being fetched.

    Returns:
        The matching class.

    Raises:
        ApiError: 404 when the class does not belong to the project.
    """
    item = await session.get(ProjectClass, class_id)
    if item is None or item.project_id != project.id:
        raise ApiError(404, "not_found", "The class does not exist.")
    return item


async def update_class(
    session: AsyncSession,
    item: ProjectClass,
    request: ProjectClassUpdate,
) -> ProjectClass:
    """Apply a versioned update to a class.

    Args:
        session: Active database session.
        item: Class being updated.
        request: Validated update request carrying the expected version.

    Returns:
        The updated class.

    Raises:
        ApiError: 409 when the version is stale or uniqueness fails.
    """
    if request.version != item.version:
        raise ApiError(
            409,
            "version_conflict",
            "The class changed since it was read.",
            details={"expected_version": item.version},
        )

    fields = request.model_dump(exclude_unset=True, exclude={"version"})
    for name, value in fields.items():
        setattr(item, name, value)
    item.version += 1
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise _conflict(error) from error
    await session.refresh(item)
    return item


async def delete_class(session: AsyncSession, item: ProjectClass) -> None:
    """Remove a class from its project.

    Args:
        session: Active database session.
        item: Class being removed.
    """
    await session.delete(item)
    await session.commit()
