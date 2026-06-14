"""Database engine and session factory."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from dada_api.core.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async SQLAlchemy session for request dependencies."""
    async with async_session_factory() as session:
        yield session
