"""Manager resolution queue, evidence, retry, adjudication, and lease schemas."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from dada_api.schemas.assignment import AssignmentMedia, CanonicalAnnotationObject

WorkItemStatusName = Literal[
    "pending_review", "review_ready", "review_required", "resolved", "cancelled"
]
RunStatusName = Literal[
    "queued", "running", "succeeded", "review_required", "failed", "cancelled"
]
AdjudicationActionName = Literal[
    "accept_proposal", "edit_proposal", "edit_submission", "replace"
]
Rationale = Annotated[str, Field(min_length=1, max_length=2000)]


class ExpectedVersions(BaseModel):
    """The versions a manager action is based on (D18).

    A mismatch with the server returns ``409`` so the client can refetch the
    evidence without losing its local work.
    """

    expected_evidence_generation: int = Field(ge=1)
    expected_configuration_fingerprint: str | None = Field(default=None, max_length=64)
    expected_resolution_version: int = Field(ge=0)


class ResolverConfigurationWrite(BaseModel):
    """An explicit configuration for a manual retry, validated like a policy."""

    parameters: dict[str, Any] = Field(default_factory=dict)
    review_thresholds: dict[str, Any] = Field(default_factory=dict)


class RetryRequest(ExpectedVersions):
    """Ask for a new resolver run over the image's latest evidence."""

    rationale: Rationale
    configuration: ResolverConfigurationWrite | None = None


class CancelRunRequest(BaseModel):
    """Cancel an active resolver run."""

    rationale: Rationale


class AdjudicationRequest(ExpectedVersions):
    """An expert decision on one resolution work item.

    ``objects`` is required to edit or replace and ignored when accepting.
    ``source_submission_id`` names the raw submission an
    ``edit_submission`` started from. A rationale is required for edits,
    replacements, conflicted self-adjudication, and overriding an earlier
    expert decision.
    """

    action: AdjudicationActionName
    objects: list[CanonicalAnnotationObject] | None = Field(
        default=None, max_length=1000
    )
    source_submission_id: UUID | None = None
    rationale: str | None = Field(default=None, max_length=2000)


class LeaseRevokeRequest(BaseModel):
    """Revoke an abandoned edit lease."""

    reason: Rationale


class LeaseResponse(BaseModel):
    """An active edit lease on one work item."""

    work_item_id: UUID
    holder_id: UUID
    acquired_at: datetime
    renewed_at: datetime
    expires_at: datetime
    cap_at: datetime


class ResolutionQueueItem(BaseModel):
    """One open case in a batch's manager queue, without full evidence."""

    work_item_id: UUID
    batch_item_id: UUID
    media_id: UUID
    relative_path: str
    scope: Literal["image", "candidate"]
    candidate_key: str
    status: WorkItemStatusName
    reason: str | None
    submissions: int
    reviews_submitted: int
    reviews_required: int
    resolver: str | None
    resolver_version: str | None
    class_strategy: str | None
    metrics: dict[str, Any]
    lease_holder_id: UUID | None
    lease_expires_at: datetime | None
    created_at: datetime


class ResolutionQueuePage(BaseModel):
    """A cursor page of the manager queue."""

    items: list[ResolutionQueueItem]
    next_cursor: str | None = None


class EvidenceVersions(BaseModel):
    """The values a manager action must send back as its expected versions."""

    evidence_generation: int
    configuration_fingerprint: str | None
    resolution_version: int


class ProposalView(BaseModel):
    """A run's immutable proposal."""

    id: UUID
    outcome: str
    objects: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    diagnostics: dict[str, Any]
    content_hash: str
    created_at: datetime


class RunView(BaseModel):
    """A resolver run with its provenance and outcome."""

    id: UUID
    sequence: int
    trigger: str
    status: RunStatusName
    pipeline: str
    pipeline_version: str
    configuration: dict[str, Any]
    configuration_fingerprint: str
    input_fingerprint: str
    dependency_versions: dict[str, Any]
    attempt: int
    failure_code: str | None
    failure_detail: str | None
    requested_by: UUID | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    proposal: ProposalView | None


class ResolutionView(BaseModel):
    """One canonical resolution version of the image."""

    id: UUID
    version: int
    source: str
    objects: list[dict[str, Any]]
    content_hash: str
    accepted_by: UUID | None
    run_id: UUID | None
    created_at: datetime
    superseded_at: datetime | None


class SubmissionEvidence(BaseModel):
    """One immutable annotator submission, named for owners and managers."""

    id: UUID
    assignment_id: UUID
    annotator_id: UUID
    annotator_name: str
    revision: int
    content_hash: str
    objects: list[dict[str, Any]]
    submitted_at: datetime
    current_generation: bool


class ReviewEvidence(BaseModel):
    """One immutable scoped review submission."""

    id: UUID
    work_item_id: UUID
    candidate_key: str
    reviewer_id: UUID
    reviewer_name: str
    evidence: dict[str, Any]
    content_hash: str
    submitted_at: datetime


class AdjudicationView(BaseModel):
    """One audited expert decision."""

    id: UUID
    work_item_id: UUID
    action: AdjudicationActionName
    actor_id: UUID
    actor_role: str
    objects: list[dict[str, Any]]
    rationale: str | None
    contributor_conflict: bool
    resolved_annotation_id: UUID | None
    created_at: datetime


class WorkItemView(BaseModel):
    """One image-level or candidate-level case with its lease and decisions."""

    id: UUID
    candidate_key: str
    candidate_ordinal: int
    scope: Literal["image", "candidate"]
    status: WorkItemStatusName
    reason: str | None
    candidate_context: dict[str, Any]
    run_id: UUID | None
    reviews_submitted: int
    reviews_required: int
    lease: LeaseResponse | None
    adjudications: list[AdjudicationView]
    created_at: datetime
    closed_at: datetime | None


class EvidenceResponse(BaseModel):
    """Everything an owner or manager needs to review one image."""

    batch_item_id: UUID
    batch_id: UUID
    purpose: str
    status: str
    task_type: str
    media: AssignmentMedia
    versions: EvidenceVersions
    require_independent_adjudicator: bool
    contributors: list[UUID]
    submissions: list[SubmissionEvidence]
    reviews: list[ReviewEvidence]
    runs: list[RunView]
    resolutions: list[ResolutionView]
    work_items: list[WorkItemView]


class AdjudicationResponse(BaseModel):
    """The recorded decision and the image's new resolution, if it closed."""

    adjudication: AdjudicationView
    resolution: ResolutionView | None


class PerformanceSummary(BaseModel):
    """Aggregate agreement of one annotator for one evaluation source.

    ``outcomes``, ``metrics`` and ``classes`` are null when the row has fewer
    than ``minimum_decisions`` decisions; an individual value is null when
    fewer than ``minimum_cell`` observations back it.
    """

    annotator_id: UUID
    annotator_name: str
    evaluation_source: str
    task_type: str
    decisions: int
    suppressed: bool
    outcomes: dict[str, int | None] | None
    metrics: dict[str, float | None] | None
    classes: dict[str, float | None] | None


class PerformanceReport(BaseModel):
    """Project-scoped annotator performance for owners and managers."""

    items: list[PerformanceSummary]
    minimum_decisions: int
    minimum_cell: int


class StrategyEligibility(BaseModel):
    """Whether one conditional strategy has the evidence it needs (D11)."""

    strategy: str
    eligible: bool
    missing: list[dict[str, Any]]
    report: dict[str, Any]


class ResolverEligibility(BaseModel):
    """The project's current eligibility for the conditional strategies."""

    strategies: list[StrategyEligibility]
