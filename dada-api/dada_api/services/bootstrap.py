"""Idempotent creation and explicit replacement of the bootstrap administrator."""

from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.security import hash_password
from dada_api.models.bootstrap import SINGLETON_ID, BootstrapRecord
from dada_api.models.user import User
from dada_api.services.users import get_user_by_username


class BootstrapError(Exception):
    """Raised when a bootstrap request is ambiguous or cannot be satisfied."""


async def _create_administrator(
    session: AsyncSession,
    username: str,
    display_name: str,
    password: str,
) -> User:
    """Persist a new global administrator.

    Args:
        session: Active database session.
        username: Username for the administrator.
        display_name: Human-readable name.
        password: Plaintext password, hashed before persistence.

    Returns:
        The persisted administrator.
    """
    user = User(
        username=username,
        display_name=display_name,
        password_hash=hash_password(password),
        is_administrator=True,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def bootstrap_administrator(
    session: AsyncSession,
    username: str,
    display_name: str,
    password: str,
) -> tuple[User, bool]:
    """Create the bootstrap administrator when the installation has none.

    Rerunning with the same identity is a no-op that leaves the stored password
    hash untouched. Rerunning with a different identity is refused rather than
    resolved by guessing.

    Args:
        session: Active database session.
        username: Requested administrator username.
        display_name: Human-readable name.
        password: Plaintext password, hashed before persistence.

    Returns:
        The bootstrap administrator and whether this call created it.

    Raises:
        BootstrapError: When a different bootstrap identity already exists, or
            when the username is already taken by a non-bootstrap user.
    """
    record = await session.get(BootstrapRecord, SINGLETON_ID)
    if record is not None:
        existing = await session.get(User, record.user_id)
        if existing is not None and existing.username == username:
            return existing, False
        raise BootstrapError(
            "A different bootstrap administrator already exists. "
            "Use replace-bootstrap-admin to change the bootstrap identity."
        )

    if await get_user_by_username(session, username) is not None:
        raise BootstrapError(
            f"User {username!r} already exists but was not created by bootstrap. "
            "Choose a different username."
        )

    user = await _create_administrator(session, username, display_name, password)
    session.add(BootstrapRecord(id=SINGLETON_ID, user_id=user.id))
    await session.commit()
    return user, True


async def replace_bootstrap_administrator(
    session: AsyncSession,
    username: str,
    display_name: str,
    password: str,
) -> User:
    """Point the bootstrap record at a newly created administrator.

    The previous administrator keeps its own account and authority; revoking
    access is a separate, deliberate act.

    Args:
        session: Active database session.
        username: Username for the new bootstrap administrator.
        display_name: Human-readable name.
        password: Plaintext password, hashed before persistence.

    Returns:
        The new bootstrap administrator.

    Raises:
        BootstrapError: When no bootstrap administrator exists yet, or when the
            requested username is already taken.
    """
    record = await session.get(BootstrapRecord, SINGLETON_ID)
    if record is None:
        raise BootstrapError(
            "No bootstrap administrator exists. Run bootstrap-admin first."
        )

    if await get_user_by_username(session, username) is not None:
        raise BootstrapError(
            f"User {username!r} already exists. Choose a different username."
        )

    user = await _create_administrator(session, username, display_name, password)
    record.user_id = user.id
    await session.commit()
    return user
