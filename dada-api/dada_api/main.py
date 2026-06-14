"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from dada_api.api.router import router as api_router
from dada_api.core.config import get_settings
from dada_api.db.init_db import create_database_schema, seed_admin_user
from dada_api.db.session import async_session_factory
from dada_api.schemas.health import HealthResponse


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize runtime resources on startup."""
    settings = get_settings()
    await create_database_schema()
    async with async_session_factory() as session:
        await seed_admin_user(session, settings)
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(api_router)


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    """Return API health status."""
    return HealthResponse(status="ok", service=settings.app_name)
