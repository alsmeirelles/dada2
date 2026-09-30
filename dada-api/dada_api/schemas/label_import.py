"""Label import contract schemas used by the v1 OpenAPI surface."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from dada_api.schemas.upload import SHA256_HEX

ImportFormatName = Literal["yolo_detection", "coco_segmentation"]
ImportStatusName = Literal["uploading", "validated", "rejected", "accepted"]


class ImportManifestFile(BaseModel):
    """One label file the client intends to upload.

    ``size_bytes`` may be zero: an empty YOLO file marks an image as empty.
    """

    client_file_id: str = Field(min_length=1, max_length=128)
    relative_path: str = Field(min_length=1, max_length=1024)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=SHA256_HEX)


class AnnotationImportCreate(BaseModel):
    """Create-import request naming the source format and its files."""

    format: ImportFormatName
    files: list[ImportManifestFile] = Field(min_length=1)


class ImportFileResponse(BaseModel):
    """One source file and whether its bytes have arrived."""

    client_file_id: str
    relative_path: str
    size_bytes: int
    sha256: str
    received: bool


class ImportErrorResponse(BaseModel):
    """One reason the import cannot be accepted."""

    code: str
    client_file_id: str
    detail: str


class ImportReport(BaseModel):
    """Preview of what accepting the import would seed.

    Images without labels stay valid, unlabelled images; they are counted
    rather than reported as errors.
    """

    labelled_images: int
    objects: int
    unlabelled_images: int
    errors: list[ImportErrorResponse]


class AnnotationImportResponse(BaseModel):
    """Label import representation with its provenance and review report."""

    id: UUID
    project_id: UUID
    format: ImportFormatName
    parser_version: str
    status: ImportStatusName
    created_by: UUID
    report: ImportReport | None
    files: list[ImportFileResponse]
    created_at: datetime
    validated_at: datetime | None
    accepted_at: datetime | None
