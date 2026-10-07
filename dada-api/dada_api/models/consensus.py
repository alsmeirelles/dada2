"""Durable Phase 5.1 boundary for consensus resolution and scoped review."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dada_api.db.base import Base


class ResolutionWorkStatus(StrEnum):
    pending_review = "pending_review"
    review_ready = "review_ready"
    review_required = "review_required"
    resolved = "resolved"
    cancelled = "cancelled"


class ReviewAssignmentStatus(StrEnum):
    pending = "pending"
    in_progress = "in_progress"
    submitted = "submitted"
    cancelled = "cancelled"


class OutboxEvent(Base):
    """An immutable domain event awaiting delivery to a Phase 6 consumer."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint(
            "event_type",
            "aggregate_id",
            "generation",
            name="uq_outbox_event_generation",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(96), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(32))
    aggregate_id: Mapped[str] = mapped_column(String(36), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ResolutionInput(Base):
    """An immutable, versioned input snapshot created by the resolution service."""

    __tablename__ = "resolution_inputs"
    __table_args__ = (
        UniqueConstraint(
            "batch_item_id",
            "evidence_generation",
            "run_number",
            name="uq_resolution_input_run",
        ),
        UniqueConstraint("source_event_id", name="uq_resolution_input_event"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    batch_item_id: Mapped[str] = mapped_column(
        ForeignKey("batch_items.id", ondelete="CASCADE"), index=True
    )
    source_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("outbox_events.id", ondelete="CASCADE"), nullable=True
    )
    evidence_generation: Mapped[int] = mapped_column(Integer)
    run_number: Mapped[int] = mapped_column(Integer)
    source_inputs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    candidate_mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ResolutionWorkItem(Base):
    """One image-level or candidate-level unit that needs more evidence."""

    __tablename__ = "resolution_work_items"
    __table_args__ = (
        UniqueConstraint(
            "resolution_input_id", "candidate_key", name="uq_resolution_candidate"
        ),
        UniqueConstraint(
            "batch_item_id",
            "candidate_key",
            "source_run_number",
            name="uq_resolution_candidate_run",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    resolution_input_id: Mapped[str] = mapped_column(
        ForeignKey("resolution_inputs.id", ondelete="CASCADE"), index=True
    )
    batch_item_id: Mapped[str] = mapped_column(
        ForeignKey("batch_items.id", ondelete="CASCADE"), index=True
    )
    candidate_key: Mapped[str] = mapped_column(String(128))
    candidate_ordinal: Mapped[int] = mapped_column(Integer)
    scope: Mapped[str] = mapped_column(String(16))
    source_run_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(32), default=ResolutionWorkStatus.pending_review, index=True
    )
    candidate_context: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ReviewAssignment(Base):
    """A reviewer's private, candidate-scoped evidence obligation."""

    __tablename__ = "review_assignments"
    __table_args__ = (
        UniqueConstraint("work_item_id", "reviewer_id", name="uq_review_reviewer"),
        UniqueConstraint("work_item_id", "position", name="uq_review_position"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    work_item_id: Mapped[str] = mapped_column(
        ForeignKey("resolution_work_items.id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(32), default=ReviewAssignmentStatus.pending, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    draft: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    draft_saved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    selection_algorithm: Mapped[str] = mapped_column(String(32))
    ordered_pool: Mapped[list[str]] = mapped_column(JSONB)
    excluded_reviewer_ids: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ReviewSubmission(Base):
    """One immutable scoped review, kept separate from image submissions."""

    __tablename__ = "review_submissions"
    __table_args__ = (
        UniqueConstraint("review_assignment_id", name="uq_review_submission"),
        UniqueConstraint(
            "work_item_id", "reviewer_id", name="uq_review_submission_reviewer"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    review_assignment_id: Mapped[str] = mapped_column(
        ForeignKey("review_assignments.id", ondelete="CASCADE"), index=True
    )
    work_item_id: Mapped[str] = mapped_column(
        ForeignKey("resolution_work_items.id", ondelete="CASCADE"), index=True
    )
    source_input_id: Mapped[str] = mapped_column(
        ForeignKey("resolution_inputs.id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
