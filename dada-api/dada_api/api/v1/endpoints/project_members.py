"""Project membership routes."""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import get_current_user, require_project_action
from dada_api.db.session import get_session
from dada_api.models.project import Project, ProjectMember, ProjectRole
from dada_api.models.user import User
from dada_api.schemas.project import (
    ProjectMemberCreate,
    ProjectMemberPage,
    ProjectMemberResponse,
    ProjectMemberUpdate,
)
from dada_api.services import project_members as member_service
from dada_api.services.authorization import ProjectAction

router = APIRouter()


def _response(member: ProjectMember, user: User) -> ProjectMemberResponse:
    """Build the membership representation the App consumes.

    Args:
        member: Membership record.
        user: User the membership belongs to.

    Returns:
        The combined membership representation.
    """
    return ProjectMemberResponse(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=member.role.value,
    )


@router.get("/projects/{project_id}/members", response_model=ProjectMemberPage)
async def list_members(
    cursor: str | None = Query(default=None),
    project: Project = Depends(require_project_action(ProjectAction.read_project)),
    session: AsyncSession = Depends(get_session),
) -> ProjectMemberPage:
    """List a project's members ordered by username.

    Args:
        cursor: Opaque cursor from a previous page.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        One page of members with the cursor for the next one.
    """
    rows, next_cursor = await member_service.list_members(session, project, cursor)
    return ProjectMemberPage(
        items=[_response(member, user) for member, user in rows],
        next_cursor=next_cursor,
    )


@router.post(
    "/projects/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    request: ProjectMemberCreate,
    actor: User = Depends(get_current_user),
    project: Project = Depends(require_project_action(ProjectAction.manage_members)),
    session: AsyncSession = Depends(get_session),
) -> ProjectMemberResponse:
    """Grant an existing user a role in a project.

    Args:
        request: Validated request naming the username and role.
        actor: Authenticated user performing the change.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The created membership.
    """
    member, user = await member_service.add_member(
        session, actor, project, request.username, ProjectRole(request.role)
    )
    return _response(member, user)


@router.patch(
    "/projects/{project_id}/members/{user_id}", response_model=ProjectMemberResponse
)
async def change_member_role(
    user_id: str,
    request: ProjectMemberUpdate,
    actor: User = Depends(get_current_user),
    project: Project = Depends(require_project_action(ProjectAction.manage_members)),
    session: AsyncSession = Depends(get_session),
) -> ProjectMemberResponse:
    """Change a member's role.

    Args:
        user_id: Member being changed.
        request: Validated request naming the new role.
        actor: Authenticated user performing the change.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The updated membership.
    """
    member, user = await member_service.get_member(session, project, user_id)
    updated = await member_service.change_member_role(
        session, actor, project, member, ProjectRole(request.role)
    )
    return _response(updated, user)


@router.delete(
    "/projects/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    user_id: str,
    actor: User = Depends(get_current_user),
    project: Project = Depends(require_project_action(ProjectAction.manage_members)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Remove a member from a project.

    Args:
        user_id: Member being removed.
        actor: Authenticated user performing the change.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        An empty response.
    """
    member, _ = await member_service.get_member(session, project, user_id)
    await member_service.remove_member(session, actor, project, member)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
