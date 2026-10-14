"""Candidate-scoped review queue and immutable evidence schemas."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from dada_api.schemas.assignment import (
    AssignmentMedia,
    PolygonGeometry,
    RectangleGeometry,
)

ReviewStatusName = Literal["pending", "in_progress", "submitted", "cancelled"]


class ImageReviewEvidence(BaseModel):
    """A reviewer's own label set for an image-level classification case."""

    model_config = ConfigDict(extra="forbid")

    class_ids: list[str] = Field(min_length=1, max_length=1000)


class ObjectReviewEvidence(BaseModel):
    """A reviewer's statement that the candidate is an object, with its class
    and geometry."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["object"]
    class_id: str = Field(min_length=1, max_length=36)
    geometry: Annotated[
        RectangleGeometry | PolygonGeometry, Field(discriminator="type")
    ]


class NoObjectReviewEvidence(BaseModel):
    """A reviewer's statement that nothing exists at the candidate."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["no_object"]


CandidateReviewEvidence = Annotated[
    ObjectReviewEvidence | NoObjectReviewEvidence, Field(discriminator="decision")
]


class ReviewEvidenceWrite(BaseModel):
    """A private review draft or submission.

    A draft may be incomplete. A submission must be an
    :class:`ImageReviewEvidence` for an image case or a
    :class:`CandidateReviewEvidence` for a candidate case (D16).
    """

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
