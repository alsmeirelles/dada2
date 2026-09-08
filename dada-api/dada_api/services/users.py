"""User lookup, authentication, and audited global user administration."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.cursors import decode_cursor, encode_cursor
from dada_api.core.errors import ApiError
from dada_api.core.security import hash_password, verify_password
from dada_api.models.user import User
from dada_api.schemas.user import UserCreate, UserUpdate
from dada_api.services import audit
from dada_api.services.auth_sessions import revoke_user_sessions

PAGE_SIZE = 100


def access_token_roles(user: User) -> list[str]:
    """Return the role claims embedded in a user's access token.

    Args:
        user: Authenticated user.

    Returns:
        The claim list, holding ``administrator`` only for global administrators.
    """
    return ["administrator"] if user.is_administrator else []


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    """Return a user by username.

    Args:
        session: Active database session.
        username: Username to look up.

    Returns:
        The matching user, or None when no user has that username.
    """
    return await session.scalar(select(User).where(User.username == username))


async def authenticate_user(
    session: AsyncSession,
    username: str,
    password: str,
) -> User | None:
    """Return an active user when credentials are valid.

    Args:
        session: Active database session.
        username: Supplied username.
        password: Supplied plaintext password.

    Returns:
        The authenticated user, or None when authentication fails.
    """
    user = await get_user_by_username(session, username)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def get_user(session: AsyncSession, user_id: str) -> User:
    """Return one user by identifier.

    Args:
        session: Active database session.
        user_id: User being read.

    Returns:
        The user.

    Raises:
        ApiError: 404 when no user has that identifier.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise ApiError(404, "not_found", "The user does not exist.")
    return user


async def list_users(
    session: AsyncSession,
    cursor: str | None,
    active: bool | None,
) -> tuple[list[User], str | None]:
    """List users ordered by username, optionally filtered by active state.

    Args:
        session: Active database session.
        cursor: Opaque cursor from a previous page.
        active: Restrict to active or inactive users when supplied.

    Returns:
        The page of users and the cursor for the next page, if any.
    """
    query = select(User).order_by(User.username)
    if active is not None:
        query = query.where(User.is_active.is_(active))
    if cursor is not None:
        position = decode_cursor(cursor)
        query = query.where(User.username > str(position["username"]))

    rows = list(await session.scalars(query.limit(PAGE_SIZE + 1)))
    if len(rows) <= PAGE_SIZE:
        return rows, None
    page = rows[:PAGE_SIZE]
    return page, encode_cursor({"username": page[-1].username})


def _audit_state(user: User) -> dict[str, object]:
    """Return the non-secret fields of a user, for an audit payload."""
    return {
        "username": user.username,
        "display_name": user.display_name,
        "is_administrator": user.is_administrator,
        "is_active": user.is_active,
    }


async def _refuse_withdrawn_access(
    session: AsyncSession,
    actor: User,
    target: User,
) -> None:
    """Refuse withdrawing administration or access when it must be preserved.

    The installation-wide rule is checked first because it is the more specific
    fact: when the target is the only active administrator, saying that no
    administrator would remain explains the refusal better than saying the
    actor may not change their own account. With more than one administrator
    left, only the self-change rule can still apply.

    Args:
        session: Active database session.
        actor: User performing the change.
        target: User whose authority or access is being withdrawn.

    Raises:
        ApiError: 409 when the last active administrator would be lost, or when
            an administrator is withdrawing their own access.
    """
    if target.is_administrator and target.is_active:
        remaining = await session.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.is_administrator.is_(True),
                User.is_active.is_(True),
                User.id != target.id,
            )
        )
        if not remaining:
            raise ApiError(
                409,
                "last_active_administrator",
                "The installation must keep at least one active administrator.",
            )

    if actor.id == target.id:
        raise ApiError(
            409,
            "self_administration_change",
            "An administrator cannot remove their own administration or access.",
        )


async def create_user(
    session: AsyncSession,
    actor: User,
    request: UserCreate,
) -> User:
    """Create and persist a user on an administrator's behalf.

    Args:
        session: Active database session.
        actor: Administrator performing the creation.
        request: Validated creation request.

    Returns:
        The persisted user.

    Raises:
        ApiError: 409 when the username is already taken.
    """
    user = User(
        username=request.username,
        display_name=request.display_name,
        password_hash=hash_password(request.password),
        is_administrator=request.is_administrator,
        is_active=request.is_active,
        version=1,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        raise ApiError(
            409, "username_taken", "A user with this username already exists."
        ) from error

    audit.record(
        session,
        actor,
        None,
        "user.created",
        "user",
        user.id,
        after=_audit_state(user),
    )
    await session.commit()
    await session.refresh(user)
    return user


async def update_user(
    session: AsyncSession,
    actor: User,
    user: User,
    request: UserUpdate,
) -> User:
    """Apply a versioned administrator update to a user.

    Args:
        session: Active database session.
        actor: Administrator performing the change.
        user: User being changed.
        request: Validated update carrying the expected version.

    Returns:
        The updated user.

    Raises:
        ApiError: 409 on a stale version, a self-administration change, or the
            loss of the last active administrator.
    """
    if request.version != user.version:
        raise ApiError(
            409,
            "version_conflict",
            "The user changed since it was read.",
            details={"expected_version": user.version},
        )

    fields = request.model_dump(exclude_unset=True, exclude={"version"})
    withdraws_access = fields.get("is_administrator") is False or (
        fields.get("is_active") is False
    )
    if withdraws_access:
        await _refuse_withdrawn_access(session, actor, user)

    before = _audit_state(user)
    for name, value in fields.items():
        setattr(user, name, value)
    user.version += 1

    if fields.get("is_active") is False:
        await revoke_user_sessions(session, user.id)

    audit.record(
        session,
        actor,
        None,
        "user.updated",
        "user",
        user.id,
        before=before,
        after=_audit_state(user),
    )
    await session.commit()
    await session.refresh(user)
    return user


async def reset_password(
    session: AsyncSession,
    actor: User,
    user: User,
    new_password: str,
) -> None:
    """Replace a user's password on an administrator's behalf.

    Args:
        session: Active database session.
        actor: Administrator performing the reset.
        user: User whose password is replaced.
        new_password: Plaintext replacement, hashed before persistence.
    """
    user.password_hash = hash_password(new_password)
    await revoke_user_sessions(session, user.id)
    audit.record(session, actor, None, "user.password_reset", "user", user.id)
    await session.commit()


async def change_own_password(
    session: AsyncSession,
    user: User,
    current_password: str,
    new_password: str,
) -> None:
    """Replace the caller's own password after verifying the current one.

    Args:
        session: Active database session.
        user: Authenticated user changing their own password.
        current_password: Password the caller claims to hold.
        new_password: Plaintext replacement, hashed before persistence.

    Raises:
        ApiError: 400 when the current password does not match.
    """
    if not verify_password(current_password, user.password_hash):
        raise ApiError(
            400,
            "current_password_incorrect",
            "The current password is not correct.",
        )

    user.password_hash = hash_password(new_password)
    await revoke_user_sessions(session, user.id)
    audit.record(session, user, None, "user.password_changed", "user", user.id)
    await session.commit()


async def delete_user(session: AsyncSession, actor: User, user: User) -> None:
    """Permanently remove a user, refusing while anything still references them.

    Refresh sessions and project memberships cascade, so they need no explicit
    revocation: the rows are removed outright. Owned projects, audit authorship,
    the bootstrap record, group snapshots, and assignments all restrict the
    delete, and that database refusal is what this reports as ``user_in_use``.
    Deactivating the account is the reversible alternative.

    Args:
        session: Active database session.
        actor: Administrator performing the deletion.
        user: User being removed.

    Raises:
        ApiError: 409 on a self-administration change, the loss of the last
            active administrator, or a retained reference.
    """
    await _refuse_withdrawn_access(session, actor, user)

    audit.record(
        session,
        actor,
        None,
        "user.deleted",
        "user",
        user.id,
        before=_audit_state(user),
    )
    await session.delete(user)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise ApiError(
            409,
            "user_in_use",
            "The user is still referenced and can only be deactivated.",
        ) from error
