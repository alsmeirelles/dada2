"""Runtime capability discovery endpoint."""

from fastapi import APIRouter

from dada_api.core.config import get_settings
from dada_api.schemas.capabilities import CapabilitiesResponse

router = APIRouter()


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def read_capabilities() -> CapabilitiesResponse:
    """Return upload limits, media formats, tasks, and realtime transport."""
    settings = get_settings()
    return CapabilitiesResponse(
        supported_image_media_types=settings.image_media_types,
        max_file_bytes=settings.max_file_bytes,
        max_project_files=settings.max_project_files,
        upload_chunk_bytes=settings.upload_chunk_bytes,
        supported_task_types=["classification", "detection", "segmentation"],
        realtime_transport=settings.realtime_transport,
    )
