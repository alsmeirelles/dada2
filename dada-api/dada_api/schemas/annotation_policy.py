"""Annotation policy request and response schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

AnnotationModeName = Literal["single", "consensus"]


class AnnotationPolicyUpdate(BaseModel):
    """Optimistically versioned policy replacement.

    ``version`` carries the version the caller believes is current.
    ``parameters`` and ``review_thresholds`` are validated against the task's
    closed pipeline configuration, which ``GET /capabilities`` describes;
    omitted values take their defaults.
    """

    mode: AnnotationModeName
    annotator_ids: list[UUID] = Field(default_factory=list)
    required_consensus_annotations: int | None = Field(default=None, ge=1)
    required_consensus_reviewers: int | None = Field(default=None, ge=1)
    resolver: str | None = Field(default=None, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)
    review_thresholds: dict[str, Any] = Field(default_factory=dict)
    require_independent_adjudicator: bool = False
    version: int = Field(ge=1)


class AnnotationPolicyResponse(BaseModel):
    """Policy representation expected by the App."""

    mode: AnnotationModeName
    annotator_ids: list[UUID]
    required_consensus_annotations: int | None
    required_consensus_reviewers: int | None
    resolver: str | None
    resolver_version: str | None
    parameters: dict[str, Any]
    review_thresholds: dict[str, Any]
    require_independent_adjudicator: bool
    version: int


class PolicyChange(BaseModel):
    """One audited change of the default policy and the fields it changed."""

    version: int
    actor_id: UUID | None
    actor_name: str | None
    changed_at: datetime
    resolver: str | None
    resolver_version: str | None
    changed_fields: dict[str, dict[str, Any]]


class PolicyHistory(BaseModel):
    """The read-only history of a project's default policy (A6-04).

    ``preparing_batches`` counts the batches a change can still reach; started
    batches keep their own snapshot.
    """

    items: list[PolicyChange]
    preparing_batches: int
