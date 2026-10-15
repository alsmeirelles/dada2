"""Phase 6 resolution runs, proposals, adjudications, leases, and evidence."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dada_api.db.base import Base


class RunStatus(StrEnum):
    """Lifecycle of one resolver run.

    ``queued`` and ``running`` are the active states; at most one active run
    exists per item and configuration fingerprint.
    """

    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    review_required = "review_required"
    failed = "failed"
    cancelled = "cancelled"


ACTIVE_RUN_STATUSES = (RunStatus.queued, RunStatus.running)


class RunTrigger(StrEnum):
    """Why a run was created."""

    initial = "initial"
    review = "review"
    manual_retry = "manual_retry"


class ResolutionRun(Base):
    """One versioned resolver execution over one immutable input snapshot.

    The row is also the durable job: Celery only transports its identifier,
    and every attempt, timing, and failure is recorded here.
    """

    __tablename__ = "resolution_runs"
    __table_args__ = (
        UniqueConstraint(
            "batch_item_id", "sequence", name="uq_resolution_run_sequence"
        ),
        Index(
            "uq_resolution_run_active",
            "batch_item_id",
            "configuration_fingerprint",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    batch_item_id: Mapped[str] = mapped_column(
        ForeignKey("batch_items.id", ondelete="CASCADE"), index=True
    )
    resolution_input_id: Mapped[str] = mapped_column(
        ForeignKey("resolution_inputs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(String(16))
    pipeline: Mapped[str] = mapped_column(String(64))
    pipeline_version: Mapped[str] = mapped_column(String(32))
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    dependency_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    queue: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(32), default=RunStatus.queued, index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    effective_limits: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    output_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ResolutionProposal(Base):
    """The immutable output of one run: a decision per candidate plus the
    image document those decisions imply."""

    __tablename__ = "resolution_proposals"
    __table_args__ = (UniqueConstraint("run_id", name="uq_resolution_proposal_run"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("resolution_runs.id", ondelete="CASCADE")
    )
    batch_item_id: Mapped[str] = mapped_column(
        ForeignKey("batch_items.id", ondelete="CASCADE"), index=True
    )
    outcome: Mapped[str] = mapped_column(String(16))
    objects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class AdjudicationAction(StrEnum):
    """What an expert did with a work item."""

    accept_proposal = "accept_proposal"
    edit_proposal = "edit_proposal"
    edit_submission = "edit_submission"
    replace = "replace"


EDITING_ACTIONS = (
    AdjudicationAction.edit_proposal,
    AdjudicationAction.edit_submission,
    AdjudicationAction.replace,
)


class Adjudication(Base):
    """One audited expert decision on a resolution work item.

    It is a final canonical decision, not another consensus vote.
    ``resolved_annotation_id`` is filled once, when the parent image
    resolution that includes this decision is composed.
    """

    __tablename__ = "adjudications"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    batch_item_id: Mapped[str] = mapped_column(
        ForeignKey("batch_items.id", ondelete="CASCADE"), index=True
    )
    work_item_id: Mapped[str] = mapped_column(
        ForeignKey("resolution_work_items.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    actor_role: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(32))
    source_proposal_id: Mapped[str | None] = mapped_column(
        ForeignKey("resolution_proposals.id", ondelete="CASCADE"), nullable=True
    )
    source_submission_id: Mapped[str | None] = mapped_column(
        ForeignKey("annotation_submissions.id", ondelete="CASCADE"), nullable=True
    )
    objects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    contributor_conflict: Mapped[bool] = mapped_column(Boolean)
    contribution_submission_ids: Mapped[list[str]] = mapped_column(JSONB)
    independence_required: Mapped[bool] = mapped_column(Boolean)
    policy_version: Mapped[int] = mapped_column(Integer)
    expected_evidence_generation: Mapped[int] = mapped_column(Integer)
    expected_configuration_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    expected_resolution_version: Mapped[int] = mapped_column(Integer)
    resolved_annotation_id: Mapped[str | None] = mapped_column(
        ForeignKey("resolved_annotations.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ResolutionLease(Base):
    """An advisory, expiring edit lock on one resolution work item (P6-08).

    A lease is active while ``released_at`` is null and the server clock is
    before ``expires_at``. An expired row is closed lazily when the next lease
    is requested, so no sweeper is needed.
    """

    __tablename__ = "resolution_leases"
    __table_args__ = (
        Index(
            "uq_resolution_lease_open",
            "work_item_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    work_item_id: Mapped[str] = mapped_column(
        ForeignKey("resolution_work_items.id", ondelete="CASCADE"), index=True
    )
    holder_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    renewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cap_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ResolutionObjectEvidence(Base):
    """How one source object maps to the accepted canonical document (P6-07).

    ``evidence_key`` names the source deterministically, so the rows of one
    resolution are written exactly once.
    """

    __tablename__ = "resolution_object_evidence"
    __table_args__ = (
        UniqueConstraint(
            "resolution_id", "evidence_key", name="uq_object_evidence_key"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    resolution_id: Mapped[str] = mapped_column(
        ForeignKey("resolved_annotations.id", ondelete="CASCADE"), index=True
    )
    batch_item_id: Mapped[str] = mapped_column(
        ForeignKey("batch_items.id", ondelete="CASCADE"), index=True
    )
    evidence_key: Mapped[str] = mapped_column(String(200))
    source_kind: Mapped[str] = mapped_column(String(16))
    submission_id: Mapped[str | None] = mapped_column(
        ForeignKey("annotation_submissions.id", ondelete="CASCADE"), nullable=True
    )
    review_submission_id: Mapped[str | None] = mapped_column(
        ForeignKey("review_submissions.id", ondelete="CASCADE"), nullable=True
    )
    annotator_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    source_object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    canonical_object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class PerformanceObservation(Base):
    """One immutable, project-scoped annotator observation against an
    accepted resolution version.

    Superseding the resolution closes ``summary_eligible`` and never rewrites
    the observation. ``weighting_eligible`` is true only for independent
    expert or gold evidence, so automated consensus cannot weight the
    annotator who contributed to it.
    """

    __tablename__ = "annotator_performance_observations"
    __table_args__ = (
        UniqueConstraint(
            "resolution_id", "observation_key", name="uq_performance_observation_key"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    annotator_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    assignment_id: Mapped[str | None] = mapped_column(
        ForeignKey("annotation_assignments.id", ondelete="CASCADE"), nullable=True
    )
    submission_id: Mapped[str | None] = mapped_column(
        ForeignKey("annotation_submissions.id", ondelete="CASCADE"), nullable=True
    )
    review_submission_id: Mapped[str | None] = mapped_column(
        ForeignKey("review_submissions.id", ondelete="CASCADE"), nullable=True
    )
    batch_item_id: Mapped[str] = mapped_column(
        ForeignKey("batch_items.id", ondelete="CASCADE"), index=True
    )
    resolution_id: Mapped[str] = mapped_column(
        ForeignKey("resolved_annotations.id", ondelete="CASCADE"), index=True
    )
    resolution_version: Mapped[int] = mapped_column(Integer)
    observation_key: Mapped[str] = mapped_column(String(200))
    evaluation_source: Mapped[str] = mapped_column(String(32))
    task_type: Mapped[str] = mapped_column(String(16))
    submitted_class_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    canonical_class_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32))
    metric_name: Mapped[str] = mapped_column(String(32))
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    weighting_eligible: Mapped[bool] = mapped_column(Boolean)
    summary_eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ResolverQuarantine(Base):
    """An operator-visible quarantine of one pipeline or strategy version."""

    __tablename__ = "resolver_quarantines"
    __table_args__ = (
        Index(
            "uq_resolver_quarantine_open",
            "identifier",
            "version",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    identifier: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(64))
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    released_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class CalibrationSnapshot(Base):
    """The frozen evidence a conditional strategy uses for one batch (D11)."""

    __tablename__ = "resolver_calibration_snapshots"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    strategy: Mapped[str] = mapped_column(String(64))
    strategy_version: Mapped[str] = mapped_column(String(32))
    corpus: Mapped[dict[str, Any]] = mapped_column(JSONB)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    eligibility: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
