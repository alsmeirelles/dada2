"""Project membership management with sole-owner protection and auditing."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.cursors import decode_cursor, encode_cursor
from dada_api.core.errors import ApiError
from dada_api.models.project import Project, ProjectMember, ProjectRole
from dada_api.models.user import User
from dada_api.services import audit
from dada_api.services.users import get_user_by_username

PAGE_SIZE = 100

SOLE_OWNER_MESSAGE = (
    "A project keeps exactly one owner, which cannot be removed or changed here."
)


async def list_members(
    session: AsyncSession,
    project: Project,
    cursor: str | None,
) -> tuple[list[tuple[ProjectMember, User]], str | None]:
    """List a project's members ordered by username.

    Args:
        session: Active database session.
        project: Authorized project.
        cursor: Opaque cursor from a previous page.

    Returns:
        The page of membership and user pairs, and the next cursor if any.
    """
    query = (
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project.id)
        .order_by(User.username)
    )
    if cursor is not None:
        position = decode_cursor(cursor)
        query = query.where(User.username > str(position["username"]))

    rows = [tuple(row) for row in await session.execute(query.limit(PAGE_SIZE + 1))]
    if len(rows) <= PAGE_SIZE:
        return rows, None
    page = rows[:PAGE_SIZE]
    return page, encode_cursor({"username": page[-1][1].username})


async def add_member(
    session: AsyncSession,
    actor: User,
    project: Project,
    username: str,
    role: ProjectRole,
) -> tuple[ProjectMember, User]:
    """Grant an existing user a role in a project.

    Invitation by email is deferred, so an unknown username is an error rather
    than a pending invitation.

    Args:
        session: Active database session.
        actor: User performing the change.
        project: Authorized project.
        username: Username of the user being added.
        role: Role being granted.

    Returns:
        The membership and the user it belongs to.

    Raises:
        ApiError: 404 when the username is unknown, 409 when the user is
            already a member or the requested role is owner.
    """
    if role is ProjectRole.owner:
        raise ApiError(409, "sole_owner_protected", SOLE_OWNER_MESSAGE)

    user = await get_user_by_username(session, username)
    if user is None or not user.is_active:
        raise ApiError(404, "user_not_found", "No active user has that username.")

    member = ProjectMember(project_id=project.id, user_id=user.id, role=role)
    session.add(member)
    audit.record(
        session,
        actor,
        project.id,
        "member.added",
        "project_member",
        user.id,
        after={"user_id": user.id, "role": role.value},
    )
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise ApiError(
            409, "duplicate_member", "That user is already a project member."
        ) from error
    await session.refresh(member)
    return member, user


async def get_member(
    session: AsyncSession,
    project: Project,
    user_id: str,
) -> tuple[ProjectMember, User]:
    """Return one membership and its user.

    Args:
        session: Active database session.
        project: Authorized project.
        user_id: User whose membership is requested.

    Returns:
        The membership and the user it belongs to.

    Raises:
        ApiError: 404 when the user is not a member of the project.
    """
    row = (
        await session.execute(
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == user_id,
            )
        )
    ).first()
    if row is None:
        raise ApiError(404, "not_found", "That user is not a project member.")
    return row[0], row[1]


async def change_member_role(
    session: AsyncSession,
    actor: User,
    project: Project,
    member: ProjectMember,
    role: ProjectRole,
) -> ProjectMember:
    """Change a member's role, protecting the project's single owner.

    Args:
        session: Active database session.
        actor: User performing the change.
        project: Authorized project.
        member: Membership being changed.
        role: New role.

    Returns:
        The updated membership.

    Raises:
        ApiError: 409 when the change would remove or duplicate the owner.
    """
    if member.role is ProjectRole.owner or role is ProjectRole.owner:
        raise ApiError(409, "sole_owner_protected", SOLE_OWNER_MESSAGE)

    previous = member.role
    member.role = role
    audit.record(
        session,
        actor,
        project.id,
        "member.role_changed",
        "project_member",
        member.user_id,
        before={"role": previous.value},
        after={"role": role.value},
    )
    await session.commit()
    await session.refresh(member)
    return member


async def remove_member(
    session: AsyncSession,
    actor: User,
    project: Project,
    member: ProjectMember,
) -> None:
    """Remove a member, protecting the project's single owner.

    Args:
        session: Active database session.
        actor: User performing the change.
        project: Authorized project.
        member: Membership being removed.

    Raises:
        ApiError: 409 when the membership is the project owner's.
    """
    if member.role is ProjectRole.owner:
        raise ApiError(409, "sole_owner_protected", SOLE_OWNER_MESSAGE)

    audit.record(
        session,
        actor,
        project.id,
        "member.removed",
        "project_member",
        member.user_id,
        before={"role": member.role.value},
    )
    await session.delete(member)
    await session.commit()
