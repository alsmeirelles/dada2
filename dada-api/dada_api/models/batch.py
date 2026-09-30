"""Annotation batches, their policy snapshot, selected items, and assignments."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dada_api.db.base import Base


class ItemStatus(StrEnum):
    """Lifecycle of one image inside a batch."""

    pending = "pending"
    awaiting_resolution = "awaiting_resolution"
    resolved = "resolved"
    cancelled = "cancelled"


class AssignmentStatus(StrEnum):
    """Lifecycle of one annotator's work on one image.

    ``reassigned`` and ``cancelled`` are terminal: the row stays as evidence
    but no longer counts as work.
    """

    pending = "pending"
    in_progress = "in_progress"
    submitted = "submitted"
    reassigned = "reassigned"
    cancelled = "cancelled"


ACTIVE_ASSIGNMENT_STATUSES = (
    AssignmentStatus.pending,
    AssignmentStatus.in_progress,
    AssignmentStatus.submitted,
)


class BatchPurpose(StrEnum):
    """Why a set of media was selected for annotation."""

    initial_annotation = "initial_annotation"
    initial_training = "initial_training"
    validation = "validation"
    test = "test"
    acquisition = "acquisition"


class BatchStatus(StrEnum):
    """Lifecycle of one annotation batch."""

    preparing = "preparing"
    annotating = "annotating"
    resolving = "resolving"
    review_required = "review_required"
    resolved = "resolved"
    closed = "closed"
    failed = "failed"


class AnnotationBatch(Base):
    """A selected set of media plus the annotation policy frozen onto it.

    The policy columns are a copy of the project default taken when the batch is
    created. Editing the project default afterwards cannot reach work already in
    flight, which is the whole reason the copy exists.

    The selection columns record how the set was chosen. Together with the
    materialised ``batch_items`` they make a selection reproducible: the same
    recorded input and seed produce the same result.
    """

    __tablename__ = "annotation_batches"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(32),
        default=BatchStatus.preparing,
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(16))
    resolver: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolver_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    review_thresholds: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)
    source_policy_version: Mapped[int] = mapped_column(Integer)
    selection_strategy: Mapped[str] = mapped_column(String(32))
    selection_seed: Mapped[int] = mapped_column(BigInteger)
    selection_input_fingerprint: Mapped[str] = mapped_column(String(64))
    requested_size: Mapped[int] = mapped_column(Integer)
    model_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class AnnotationBatchAnnotator(Base):
    """One annotator's place in a batch's frozen consensus group.

    ``ondelete="RESTRICT"`` because this row is provenance: it records who was
    required to annotate. Removing the account would rewrite that history, so a
    referenced user can only be deactivated.
    """

    __tablename__ = "annotation_batch_annotators"
    __table_args__ = (
        UniqueConstraint("batch_id", "user_id", name="uq_batch_annotator"),
        UniqueConstraint("batch_id", "position", name="uq_batch_annotator_position"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("annotation_batches.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer)


class BatchItem(Base):
    """One selected image inside a batch.

    ``status`` becomes ``resolved`` only when the image has an accepted
    canonical resolution. Submitted assignments alone never set it, which is
    what makes it the signal the first-acquisition guard can trust.
    """

    __tablename__ = "batch_items"
    __table_args__ = (UniqueConstraint("batch_id", "media_id", name="uq_batch_item"),)

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("annotation_batches.id", ondelete="CASCADE"),
        index=True,
    )
    media_id: Mapped[str] = mapped_column(
        ForeignKey("media.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default=ItemStatus.pending)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class AnnotationAssignment(Base):
    """One annotator's obligation to annotate one complete image.

    Every assignment names its annotator, so it is directly available to them
    without any claim. In ``consensus`` mode one row exists per snapshotted
    group member, and the unique constraint is what makes an item's required
    submission count enforceable.

    The annotator reference restricts deletion for the same reason the group
    snapshot does: an assignment is retained domain evidence.

    ``draft`` holds the annotator's editable objects and ``version`` guards it
    against stale writes. When the image has imported labels the draft starts
    as a copy of them, and ``seed_document_id`` keeps that provenance.
    """

    __tablename__ = "annotation_assignments"
    __table_args__ = (
        UniqueConstraint("batch_item_id", "annotator_id", name="uq_assignment_owner"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    batch_item_id: Mapped[str] = mapped_column(
        ForeignKey("batch_items.id", ondelete="CASCADE"),
        index=True,
    )
    annotator_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default=AssignmentStatus.pending)
    version: Mapped[int] = mapped_column(Integer, default=1)
    draft: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    draft_saved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    seed_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("imported_seed_documents.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
