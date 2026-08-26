"""Ordered object-class routes scoped to one project."""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import require_project_action
from dada_api.db.session import get_session
from dada_api.models.project import Project, ProjectClass
from dada_api.schemas.project import (
    ProjectClassCreate,
    ProjectClassPage,
    ProjectClassResponse,
    ProjectClassUpdate,
)
from dada_api.services import project_classes as class_service
from dada_api.services.authorization import ProjectAction

router = APIRouter()


@router.get("/projects/{project_id}/classes", response_model=ProjectClassPage)
async def list_classes(
    cursor: str | None = Query(default=None),
    project: Project = Depends(require_project_action(ProjectAction.read_project)),
    session: AsyncSession = Depends(get_session),
) -> ProjectClassPage:
    """List a project's classes in display order.

    Args:
        cursor: Opaque cursor from a previous page.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        One page of classes with the cursor for the next one.
    """
    items, next_cursor = await class_service.list_classes(session, project, cursor)
    return ProjectClassPage(
        items=[ProjectClassResponse.model_validate(item) for item in items],
        next_cursor=next_cursor,
    )


@router.post(
    "/projects/{project_id}/classes",
    response_model=ProjectClassResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_class(
    request: ProjectClassCreate,
    project: Project = Depends(require_project_action(ProjectAction.manage_classes)),
    session: AsyncSession = Depends(get_session),
) -> ProjectClass:
    """Add a class to a project.

    Args:
        request: Validated creation request.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The created class.
    """
    return await class_service.create_class(session, project, request)


@router.patch(
    "/projects/{project_id}/classes/{class_id}", response_model=ProjectClassResponse
)
async def update_class(
    class_id: str,
    request: ProjectClassUpdate,
    project: Project = Depends(require_project_action(ProjectAction.manage_classes)),
    session: AsyncSession = Depends(get_session),
) -> ProjectClass:
    """Apply a versioned update to a class.

    Args:
        class_id: Class being updated.
        request: Validated update request carrying the expected version.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The updated class.
    """
    item = await class_service.get_class(session, project, class_id)
    return await class_service.update_class(session, item, request)


@router.delete(
    "/projects/{project_id}/classes/{class_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_class(
    class_id: str,
    project: Project = Depends(require_project_action(ProjectAction.manage_classes)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Remove a class from a project.

    Args:
        class_id: Class being removed.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        An empty response.
    """
    item = await class_service.get_class(session, project, class_id)
    await class_service.delete_class(session, item)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
