"""Project listing, creation, versioned update, activation, and deletion routes."""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import get_current_user, require_project_action
from dada_api.db.session import get_session
from dada_api.models.project import Project
from dada_api.models.user import User
from dada_api.schemas.project import (
    ProjectCreate,
    ProjectPage,
    ProjectResponse,
    ProjectUpdate,
)
from dada_api.services import projects as project_service
from dada_api.services.authorization import ProjectAction

router = APIRouter()


@router.get("/projects", response_model=ProjectPage)
async def list_projects(
    cursor: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectPage:
    """List the projects the caller may read.

    Args:
        cursor: Opaque cursor from a previous page.
        user: Authenticated user.
        session: Active database session.

    Returns:
        One page of projects with the cursor for the next one.
    """
    items, next_cursor = await project_service.list_projects(session, user, cursor)
    return ProjectPage(
        items=[ProjectResponse.model_validate(item) for item in items],
        next_cursor=next_cursor,
    )


@router.post(
    "/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED
)
async def create_project(
    request: ProjectCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Project:
    """Create a project owned by the caller.

    Args:
        request: Validated creation request.
        user: Authenticated user, recorded as the truthful owner.
        session: Active database session.

    Returns:
        The created project.
    """
    return await project_service.create_project(session, user, request)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def read_project(
    project: Project = Depends(require_project_action(ProjectAction.read_project)),
) -> Project:
    """Return one project when the caller holds a role permitting reads.

    Args:
        project: Project resolved and authorized by the dependency.

    Returns:
        The authorized project.
    """
    return project


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    request: ProjectUpdate,
    project: Project = Depends(require_project_action(ProjectAction.update_project)),
    session: AsyncSession = Depends(get_session),
) -> Project:
    """Apply a versioned update to a project.

    Args:
        request: Validated update request carrying the expected version.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The updated project.
    """
    return await project_service.update_project(session, project, request)


@router.post("/projects/{project_id}/activate", response_model=ProjectResponse)
async def activate_project(
    project: Project = Depends(require_project_action(ProjectAction.activate_project)),
    session: AsyncSession = Depends(get_session),
) -> Project:
    """Validate that a project is ready to be activated.

    Freezing the dataset split and opening the first annotation batch belong to
    a later phase, so this route currently only reports unmet prerequisites.

    Args:
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The project when every prerequisite is met.
    """
    return await project_service.activate_project(session, project)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project: Project = Depends(require_project_action(ProjectAction.delete_project)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Permanently delete a project and purge its media.

    The deletion is terminal: no restore window exists in this release.

    Args:
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        An empty response.
    """
    await project_service.delete_project(session, project)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
