"""Project media inventory schemas used by the v1 OpenAPI surface."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class MediaResponse(BaseModel):
    """One ingested image, with the original dimensions annotation depends on."""

    id: UUID
    relative_path: str
    media_type: str
    size_bytes: int
    sha256: str
    width: int
    height: int
    created_at: datetime


class MediaPage(BaseModel):
    """Cursor-paginated media collection."""

    items: list[MediaResponse]
    next_cursor: str | None = None
