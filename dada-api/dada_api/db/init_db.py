"""Database initialization helpers for the early API build."""

import asyncio

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


async def seed_user(
    session: AsyncSession,
    username: str | None,
    password: str | None,
    role: UserRole,
    display_name: str | None = None,
) -> None:
    """Create a configured user if it does not exist."""
    if not username or not password:
        return

    existing_user = await session.scalar(select(User).where(User.username == username))
    if existing_user is not None:
        return

    session.add(
        User(
            username=username,
            display_name=display_name or username,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
    )


async def seed_users(session: AsyncSession, settings: Settings) -> None:
    """Create configured bootstrap users if they do not exist."""
    await seed_user(
        session=session,
        username=settings.seed_admin_username,
        password=(
            settings.seed_admin_password.get_secret_value()
            if settings.seed_admin_password
            else None
        ),
        role=UserRole.admin,
    )
    await seed_user(
        session=session,
        username=settings.seed_service_username,
        password=(
            settings.seed_service_password.get_secret_value()
            if settings.seed_service_password
            else None
        ),
        role=UserRole.admin,
        display_name="Service command user",
    )
    await session.commit()


async def initialize_database() -> None:
    """Create the schema and seed configured bootstrap users."""
    from dada_api.core.config import get_settings
    from dada_api.db.session import async_session_factory

    settings = get_settings()
    await create_database_schema()
    async with async_session_factory() as session:
        await seed_users(session, settings)


def main() -> None:
    """Run database initialization from the command line."""
    asyncio.run(initialize_database())


if __name__ == "__main__":
    main()
