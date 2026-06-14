"""Queue and annotation schemas for initial API contracts."""

from typing import Any

from pydantic import BaseModel, Field


class QueueItemResponse(BaseModel):
    """Image assignment returned by the annotation queue."""

    image_id: str
    image_url: str
    lease_expires_in_seconds: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnnotationSubmitRequest(BaseModel):
    """COCO-style annotation submission payload."""

    image_id: str = Field(min_length=1)
    annotations: list[dict[str, Any]]


class AnnotationSubmitResponse(BaseModel):
    """Annotation submission result."""

    status: str
    accepted_annotations: int
