"""Immutable annotation submissions and the canonical resolutions derived from them."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dada_api.db.base import Base

DOCUMENT_SCHEMA_VERSION = 1
SINGLE_SUBMISSION_SOURCE = "single_submission"


class AnnotationSubmission(Base):
    """One immutable revision of an annotator's completed image document.

    A reopened assignment submits again as the next revision; earlier
    revisions stay untouched as evidence. ``content_hash`` identifies the
    exact objects so a later consensus run can snapshot its inputs.
    ``seed_document_id`` records that the work began from imported labels,
    while ``submitted_by`` records that the annotator authored it.

    An accepted import can only disappear with its project, so the seed link
    is set to null rather than blocking that deletion: cascades reach seeds
    before they reach submissions, and the submission is removed anyway.
    """

    __tablename__ = "annotation_submissions"
    __table_args__ = (
        UniqueConstraint("assignment_id", "revision", name="uq_submission_revision"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    assignment_id: Mapped[str] = mapped_column(
        ForeignKey("annotation_assignments.id", ondelete="CASCADE"),
        index=True,
    )
    revision: Mapped[int] = mapped_column(Integer)
    objects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[int] = mapped_column(
        Integer, default=DOCUMENT_SCHEMA_VERSION
    )
    seed_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("imported_seed_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    submitted_by: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class ResolvedAnnotation(Base):
    """One version of an image's canonical annotation.

    Training and exports may only ever read these rows, never raw
    submissions. Single mode writes version 1 directly from the submission;
    consensus and adjudication add their own versions in later phases.
    """

    __tablename__ = "resolved_annotations"
    __table_args__ = (
        UniqueConstraint("batch_item_id", "version", name="uq_resolution_version"),
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
    version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32))
    submission_id: Mapped[str | None] = mapped_column(
        ForeignKey("annotation_submissions.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    objects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
