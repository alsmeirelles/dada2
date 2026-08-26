"""Single authority deciding whether a user may act on a project.

The role/action matrix below is the only place project authority is decided. A
global administrator bypasses the matrix with owner-equivalent authority while
``Project.owner_id`` keeps recording the truthful creator.
"""

from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.errors import ApiError
from dada_api.models.project import Project, ProjectMember, ProjectRole
from dada_api.models.user import User


class ProjectAction(StrEnum):
    """Project-scoped operations subject to role authorization."""

    read_project = "read_project"
    update_project = "update_project"
    activate_project = "activate_project"
    manage_classes = "manage_classes"
    manage_members = "manage_members"
    annotate = "annotate"
    revoke_lease = "revoke_lease"
    manage_annotation_policy = "manage_annotation_policy"
    read_annotation_evidence = "read_annotation_evidence"
    run_resolution = "run_resolution"
    adjudicate = "adjudicate"
    read_annotator_performance = "read_annotator_performance"


ROLE_ACTIONS: dict[ProjectRole, frozenset[ProjectAction]] = {
    ProjectRole.owner: frozenset(ProjectAction),
    ProjectRole.manager: frozenset(
        {
            ProjectAction.read_project,
            ProjectAction.update_project,
            ProjectAction.manage_classes,
            ProjectAction.manage_members,
            ProjectAction.annotate,
            ProjectAction.revoke_lease,
            ProjectAction.manage_annotation_policy,
            ProjectAction.read_annotation_evidence,
            ProjectAction.run_resolution,
            ProjectAction.adjudicate,
            ProjectAction.read_annotator_performance,
        }
    ),
    ProjectRole.annotator: frozenset(
        {
            ProjectAction.read_project,
            ProjectAction.annotate,
        }
    ),
    ProjectRole.viewer: frozenset({ProjectAction.read_project}),
}


def role_allows(role: ProjectRole, action: ProjectAction) -> bool:
    """Return whether a project role may perform an action.

    Args:
        role: Role the user holds in the project.
        action: Operation being attempted.

    Returns:
        True when the role grants the action.
    """
    return action in ROLE_ACTIONS[role]


async def get_project_role(
    session: AsyncSession,
    user: User,
    project_id: str,
) -> ProjectRole | None:
    """Return the role a user holds in a project.

    Args:
        session: Active database session.
        user: Authenticated user.
        project_id: Project being inspected.

    Returns:
        The membership role, or None when the user is not a member.
    """
    return await session.scalar(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        )
    )


async def authorize_project_action(
    session: AsyncSession,
    user: User,
    project_id: str,
    action: ProjectAction,
) -> Project:
    """Return the project when the user may perform the action on it.

    Args:
        session: Active database session.
        user: Authenticated user.
        project_id: Project being acted on.
        action: Operation being attempted.

    Returns:
        The authorized project.

    Raises:
        ApiError: 404 when the project does not exist, or 403 when the caller
            holds no role granting the action.
    """
    project = await session.get(Project, project_id)
    if project is None:
        raise ApiError(404, "not_found", "The project does not exist.")

    if user.is_administrator:
        return project

    role = await get_project_role(session, user, project_id)
    if role is None or not role_allows(role, action):
        raise ApiError(
            403,
            "forbidden",
            "The authenticated user is not allowed to perform this action.",
        )
    return project
