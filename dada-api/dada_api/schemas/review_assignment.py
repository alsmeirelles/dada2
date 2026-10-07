"""Candidate-scoped review queue and immutable evidence schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from dada_api.schemas.assignment import AssignmentMedia

ReviewStatusName = Literal["pending", "in_progress", "submitted", "cancelled"]


class ReviewEvidenceWrite(BaseModel):
    """A complete private review draft or submission."""

    version: int = Field(ge=1)
    evidence: dict[str, Any]


class ReviewQueueItem(BaseModel):
    id: UUID
    work_item_id: UUID
    media_id: UUID
    relative_path: str
    scope: Literal["image", "candidate"]
    status: ReviewStatusName
    version: int
    updated_at: datetime


class ReviewQueueCounts(BaseModel):
    pending: int
    in_progress: int
    submitted: int


class ReviewQueuePage(BaseModel):
    items: list[ReviewQueueItem]
    next_cursor: str | None = None
    counts: ReviewQueueCounts


class ReviewAssignmentDetail(BaseModel):
    id: UUID
    project_id: UUID
    work_item_id: UUID
    source_input_id: UUID
    candidate_key: str
    candidate_ordinal: int
    scope: Literal["image", "candidate"]
    status: ReviewStatusName
    version: int
    media: AssignmentMedia
    candidate_context: dict[str, Any]
    evidence: dict[str, Any]
    draft_saved_at: datetime | None
    submitted_at: datetime | None


class ReviewDraftSaved(BaseModel):
    id: UUID
    status: ReviewStatusName
    version: int
    draft_saved_at: datetime


class ReviewSubmissionReceived(BaseModel):
    id: UUID
    status: ReviewStatusName
    version: int
    submission_id: UUID
    submitted_at: datetime
