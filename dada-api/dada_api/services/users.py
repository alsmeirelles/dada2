"""User service helpers."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.security import hash_password, verify_password
from dada_api.models.user import User
from dada_api.schemas.user import UserCreate


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


async def create_user(session: AsyncSession, user_create: UserCreate) -> User:
    """Create and persist a user.

    Args:
        session: Active database session.
        user_create: Validated creation request.

    Returns:
        The persisted user.
    """
    user = User(
        username=user_create.username,
        display_name=user_create.display_name,
        password_hash=hash_password(user_create.password),
        is_administrator=user_create.is_administrator,
        is_active=user_create.is_active,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
