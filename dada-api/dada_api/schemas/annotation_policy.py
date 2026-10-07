"""Annotation policy request and response schemas."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

AnnotationModeName = Literal["single", "consensus"]


class AnnotationPolicyUpdate(BaseModel):
    """Optimistically versioned policy replacement.

    ``version`` carries the version the caller believes is current. Parameters
    stay opaque here because their per-resolver schemas belong to Phase 6; the
    resolver identifier itself is validated against advertised capabilities.
    """

    mode: AnnotationModeName
    annotator_ids: list[UUID] = Field(default_factory=list)
    required_consensus_annotations: int | None = Field(default=None, ge=1)
    required_consensus_reviewers: int | None = Field(default=None, ge=1)
    resolver: str | None = Field(default=None, max_length=64)
    parameters: dict[str, float | int | str | bool] = Field(default_factory=dict)
    review_thresholds: dict[str, float] = Field(default_factory=dict)
    version: int = Field(ge=1)


class AnnotationPolicyResponse(BaseModel):
    """Policy representation expected by the App."""

    mode: AnnotationModeName
    annotator_ids: list[UUID]
    required_consensus_annotations: int | None
    required_consensus_reviewers: int | None
    resolver: str | None
    resolver_version: str | None
    parameters: dict[str, float | int | str | bool]
    review_thresholds: dict[str, float]
    version: int
