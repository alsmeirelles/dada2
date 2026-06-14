"""Top-level API router."""

from fastapi import APIRouter

from dada_api.api.v1.endpoints import admin, auth, inference, queue, users
from dada_api.core.config import get_settings

settings = get_settings()

router = APIRouter()
router.include_router(
    auth.router,
    prefix=f"{settings.api_v1_prefix}/auth",
    tags=["auth"],
)
router.include_router(
    users.router,
    prefix=f"{settings.api_v1_prefix}/users",
    tags=["users"],
)
router.include_router(
    queue.router,
    prefix=f"{settings.api_v1_prefix}/queue",
    tags=["queue"],
)
router.include_router(
    inference.router,
    prefix=f"{settings.api_v1_prefix}/inference",
    tags=["inference"],
)
router.include_router(
    admin.router,
    prefix=f"{settings.api_v1_prefix}/admin",
    tags=["admin"],
)
