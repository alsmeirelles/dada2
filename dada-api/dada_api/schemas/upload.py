"""Resumable ingestion contract schemas used by the v1 OpenAPI surface."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

UploadStatusName = Literal["pending", "uploading", "processing", "completed", "failed"]
UploadDispositionName = Literal["upload_required", "already_present", "rejected"]
SHA256_HEX = r"^[0-9a-f]{64}$"


class UploadManifestFile(BaseModel):
    """One file the client intends to upload, described before any bytes move."""

    client_file_id: str = Field(min_length=1, max_length=128)
    relative_path: str = Field(min_length=1, max_length=1024)
    file_name: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=64)
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=SHA256_HEX)


class UploadSessionCreate(BaseModel):
    """Create-session request carrying the client's local manifest."""

    files: list[UploadManifestFile] = Field(min_length=1)


class UploadItemResponse(BaseModel):
    """Per-file disposition and progress within a session."""

    client_file_id: str
    disposition: UploadDispositionName
    reason: str | None = None
    size_bytes: int
    received_bytes: int


class UploadSessionResponse(BaseModel):
    """Upload session representation expected by the App."""

    id: UUID
    status: UploadStatusName
    items: list[UploadItemResponse]
    error: dict[str, Any] | None = None
    expires_at: datetime


class UploadChunkResponse(BaseModel):
    """Acknowledgement of one accepted chunk, naming the next expected offset."""

    client_file_id: str
    received_bytes: int
    size_bytes: int
