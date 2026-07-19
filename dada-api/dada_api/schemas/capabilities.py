"""API capability discovery schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class CapabilitiesResponse(BaseModel):
    """Limits and features that clients must discover at runtime."""

    supported_image_media_types: list[str] = Field(min_length=1)
    max_file_bytes: int = Field(gt=0)
    max_project_files: int = Field(gt=0)
    upload_chunk_bytes: int = Field(gt=0)
    supported_task_types: list[Literal["classification", "detection", "segmentation"]]
    realtime_transport: Literal["websocket", "polling"]
