"""Database initialization helpers for the early API build."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.config import Settings
from dada_api.core.security import hash_password
from dada_api.db.base import Base
from dada_api.db.session import engine
from dada_api.models.user import User, UserRole


async def create_database_schema() -> None:
    """Create tables required by the initial API.

    This keeps the first runnable build simple. A migration tool can replace
    this once the schema starts changing regularly.
    """
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def seed_admin_user(session: AsyncSession, settings: Settings) -> None:
    """Create the configured bootstrap admin user if it does not exist."""
    if not settings.seed_admin_username or not settings.seed_admin_password:
        return

    existing_user = await session.scalar(
        select(User).where(User.username == settings.seed_admin_username)
    )
    if existing_user is not None:
        return

    session.add(
        User(
            username=settings.seed_admin_username,
            display_name=settings.seed_admin_username,
            password_hash=hash_password(settings.seed_admin_password),
            role=UserRole.admin,
            is_active=True,
        )
    )
    await session.commit()
