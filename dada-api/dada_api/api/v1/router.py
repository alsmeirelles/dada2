"""Version 1 API routes."""

from fastapi import APIRouter

from dada_api.api.v1.endpoints import (
    admin,
    annotation_policy,
    auth,
    capabilities,
    inference,
    media,
    project_classes,
    project_members,
    projects,
    queue,
    uploads,
    users,
)

router = APIRouter()
router.include_router(capabilities.router, tags=["capabilities"])
router.include_router(projects.router, tags=["projects"])
router.include_router(project_classes.router, tags=["classes"])
router.include_router(project_members.router, tags=["members"])
router.include_router(annotation_policy.router, tags=["annotation-policy"])
router.include_router(uploads.router, tags=["uploads"])
router.include_router(media.router, tags=["media"])
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(users.router, prefix="/users", tags=["users"])
router.include_router(queue.router, prefix="/queue", tags=["queue"])
router.include_router(inference.router, prefix="/inference", tags=["inference"])
router.include_router(admin.router, prefix="/admin", tags=["admin"])
