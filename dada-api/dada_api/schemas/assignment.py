"""Image-assignment queue, draft, submission, and manager request/response schemas."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from dada_api.schemas.batch import BatchPurposeName
from dada_api.schemas.project import TaskType
from dada_api.services.annotation_documents import MAX_OBJECTS, MAX_RING_POINTS

AssignmentStatusName = Literal[
    "pending", "in_progress", "submitted", "reassigned", "cancelled"
]
QueueStateName = Literal["pending", "in_progress", "submitted"]
Coordinate = Annotated[float, Field(allow_inf_nan=False)]


class RectangleGeometry(BaseModel):
    """A box as ``[x, y, width, height]`` in original-image pixels."""

    type: Literal["rectangle"]
    coordinates: list[Coordinate] = Field(min_length=4, max_length=4)


class PolygonGeometry(BaseModel):
    """Rings of flat ``[x1, y1, x2, y2, ...]`` points in original-image pixels."""

    type: Literal["polygon"]
    coordinates: list[
        Annotated[list[Coordinate], Field(min_length=6, max_length=2 * MAX_RING_POINTS)]
    ] = Field(min_length=1)


class AnnotationObject(BaseModel):
    """One labelled object; classification labels carry no geometry."""

    id: str = Field(min_length=1, max_length=64)
    class_id: str = Field(min_length=1, max_length=36)
    geometry: (
        Annotated[RectangleGeometry | PolygonGeometry, Field(discriminator="type")]
        | None
    )
    attributes: dict[str, Any] = Field(default_factory=dict)


class DocumentWrite(BaseModel):
    """A draft save or a final submission of the complete image document.

    ``version`` is the assignment version the caller last read; a different
    current version means someone else changed the work first.
    """

    version: int = Field(ge=1)
    objects: list[AnnotationObject] = Field(max_length=MAX_OBJECTS)


class AssignmentQueueItem(BaseModel):
    """One of the caller's own assignments, without any peer information."""

    id: UUID
    batch_id: UUID
    batch_purpose: BatchPurposeName
    media_id: UUID
    relative_path: str
    width: int
    height: int
    status: AssignmentStatusName
    version: int
    seeded_from_import: bool
    updated_at: datetime


class AssignmentQueueCounts(BaseModel):
    """The caller's own workload in the project."""

    pending: int
    in_progress: int
    submitted: int


class AssignmentQueuePage(BaseModel):
    """Cursor-paginated personal queue with the caller's counts."""

    items: list[AssignmentQueueItem]
    next_cursor: str | None = None
    counts: AssignmentQueueCounts


class AssignmentMedia(BaseModel):
    """The image being annotated, with a short-lived signed URL for its bytes."""

    id: UUID
    relative_path: str
    width: int
    height: int
    image_url: str


class AssignmentDetail(BaseModel):
    """One assignment opened by its annotator.

    ``objects`` is the caller's draft while the work is open and their latest
    submission once it is submitted. ``seeded_from_import`` says the work began
    from imported labels without exposing the import itself.
    """

    id: UUID
    project_id: UUID
    batch_id: UUID
    batch_purpose: BatchPurposeName
    task_type: TaskType
    status: AssignmentStatusName
    version: int
    media: AssignmentMedia
    objects: list[dict[str, Any]]
    seeded_from_import: bool
    draft_saved_at: datetime | None
    revision: int | None
    submitted_at: datetime | None


class DraftSaved(BaseModel):
    """Result of a draft save."""

    id: UUID
    status: AssignmentStatusName
    version: int
    draft_saved_at: datetime


class SubmissionReceived(BaseModel):
    """Result of a final submission.

    ``image_resolved`` is true only in single mode, where the submission itself
    becomes the canonical resolution. In consensus mode it is always false so
    the answer never reveals whether peers have submitted.
    """

    id: UUID
    status: AssignmentStatusName
    version: int
    submission_id: UUID
    revision: int
    submitted_at: datetime
    image_resolved: bool


class BatchAssignment(BaseModel):
    """One assignment as a manager sees it, without its document content."""

    id: UUID
    batch_item_id: UUID
    item_status: str
    media_id: UUID
    relative_path: str
    annotator_id: UUID
    status: AssignmentStatusName
    version: int
    updated_at: datetime


class BatchAssignmentPage(BaseModel):
    """Cursor-paginated assignments of one batch."""

    items: list[BatchAssignment]
    next_cursor: str | None = None


class AssignmentReassign(BaseModel):
    """Target of a manager reassignment."""

    annotator_id: UUID
