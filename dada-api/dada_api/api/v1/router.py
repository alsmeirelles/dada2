"""Version 1 API routes."""

from fastapi import APIRouter

from dada_api.api.v1.endpoints import admin, auth, inference, queue, users

router = APIRouter()
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(users.router, prefix="/users", tags=["users"])
router.include_router(queue.router, prefix="/queue", tags=["queue"])
router.include_router(inference.router, prefix="/inference", tags=["inference"])
router.include_router(admin.router, prefix="/admin", tags=["admin"])
