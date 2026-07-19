"""FastAPI application factory and process entrypoint."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import text

from dada_api.api.router import router as api_router
from dada_api.core.config import Settings, get_settings
from dada_api.core.errors import install_exception_handlers
from dada_api.core.idempotency import IdempotencyMiddleware
from dada_api.core.logging import configure_logging
from dada_api.core.trace import TraceMiddleware
from dada_api.db.migrations import current_revision, migration_head
from dada_api.db.session import close_database, engine
from dada_api.schemas.errors import ErrorEnvelope
from dada_api.schemas.health import DependencyStatus, HealthResponse, ReadinessResponse


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Release process resources without mutating the database schema."""
    yield
    await close_database()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the HTTP application without startup side effects."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    application = FastAPI(
        title=resolved_settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
        responses={
            400: {"model": ErrorEnvelope, "description": "Invalid request"},
            409: {"model": ErrorEnvelope, "description": "State or version conflict"},
            422: {
                "model": ErrorEnvelope,
                "description": "Semantic or schema validation failure",
            },
            503: {"model": ErrorEnvelope, "description": "Temporarily unavailable"},
        },
    )
    application.state.settings = resolved_settings
    application.include_router(api_router)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Content-Range",
            "Idempotency-Key",
            "Upload-Offset",
            "X-Chunk-SHA256",
            "X-Trace-ID",
        ],
        expose_headers=["Location", "Retry-After", "Upload-Offset", "X-Trace-ID"],
    )
    application.add_middleware(IdempotencyMiddleware)
    application.add_middleware(TraceMiddleware)
    install_exception_handlers(application)

    @application.get("/health", response_model=HealthResponse, tags=["health"])
    async def health_check() -> HealthResponse:
        """Return liveness without contacting external dependencies."""
        return HealthResponse(status="ok", service=resolved_settings.app_name)

    @application.get(
        "/ready",
        response_model=ReadinessResponse,
        tags=["health"],
    )
    async def readiness_check() -> ReadinessResponse:
        """Report PostgreSQL, migration, and Redis readiness."""
        dependencies: dict[str, DependencyStatus] = {}
        try:
            async with asyncio.timeout(resolved_settings.readiness_timeout_seconds):
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                    revision = await current_revision(connection)
            dependencies["postgresql"] = DependencyStatus(status="ok")
            expected_revision = migration_head()
            dependencies["migrations"] = DependencyStatus(
                status="ok" if revision == expected_revision else "error",
                detail=None
                if revision == expected_revision
                else (
                    f"database revision {revision or 'none'}; "
                    f"expected {expected_revision}"
                ),
            )
        except Exception as error:
            dependencies["postgresql"] = DependencyStatus(
                status="error", detail=type(error).__name__
            )
            dependencies["migrations"] = DependencyStatus(
                status="unknown", detail="PostgreSQL is unavailable."
            )

        redis_client = Redis.from_url(resolved_settings.redis_url)
        try:
            async with asyncio.timeout(resolved_settings.readiness_timeout_seconds):
                await redis_client.ping()
            dependencies["redis"] = DependencyStatus(status="ok")
        except Exception as error:
            dependencies["redis"] = DependencyStatus(
                status="error", detail=type(error).__name__
            )
        finally:
            await redis_client.aclose()

        ready = all(item.status == "ok" for item in dependencies.values())
        response = ReadinessResponse(
            status="ready" if ready else "not_ready",
            service=resolved_settings.app_name,
            dependencies=dependencies,
        )
        if not ready:
            from dada_api.core.errors import ApiError

            raise ApiError(
                503,
                "not_ready",
                "One or more required dependencies are unavailable.",
                details=response.model_dump(),
                headers={"Retry-After": "5"},
            )
        return response

    return application


app = create_app()
