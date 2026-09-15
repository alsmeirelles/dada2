"""Annotation batch request and response schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from dada_api.schemas.annotation_policy import AnnotationModeName

BatchPurposeName = Literal["initial_training", "validation", "test", "acquisition"]
BatchStatusName = Literal[
    "preparing",
    "annotating",
    "resolving",
    "review_required",
    "resolved",
    "closed",
    "failed",
]


class BatchPolicyUpdate(BaseModel):
    """Replacement policy for a batch that has not started.

    There is no ``version`` here: a batch's policy is a snapshot rather than a
    shared resource, and the batch status is what decides whether it may still
    change.
    """

    mode: AnnotationModeName
    annotator_ids: list[UUID] = Field(default_factory=list)
    resolver: str | None = Field(default=None, max_length=64)
    parameters: dict[str, float | int | str | bool] = Field(default_factory=dict)
    review_thresholds: dict[str, float] = Field(default_factory=dict)


class BatchResponse(BaseModel):
    """Batch representation carrying its policy snapshot and progress.

    Image counts and assignment counts are reported separately because one
    image carries one assignment per configured annotator, so the two never
    coincide in consensus mode.
    """

    id: UUID
    project_id: UUID
    purpose: BatchPurposeName
    status: BatchStatusName
    mode: AnnotationModeName
    annotator_ids: list[UUID]
    resolver: str | None
    resolver_version: str | None
    parameters: dict[str, float | int | str | bool]
    review_thresholds: dict[str, float]
    source_policy_version: int
    selection_strategy: str
    selection_seed: int
    selection_input_fingerprint: str
    requested_size: int
    total_items: int
    total_assignments: int
    submitted_assignments: int
    started_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BatchPage(BaseModel):
    """Cursor-paginated batch collection."""

    items: list[BatchResponse]
    next_cursor: str | None = None
