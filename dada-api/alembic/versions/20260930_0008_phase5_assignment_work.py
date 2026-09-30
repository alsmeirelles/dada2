"""Add assignment drafts, immutable submissions, and canonical resolutions.

Every assignment now names its annotator, so an earlier single-mode batch
started with an unowned assignment cannot be upgraded. Such rows only exist in
development data, which the Phase 4.1 reset removes before this revision.

Links to imported seeds are set to null when a seed is deleted. A seed only
disappears with its project, and the cascade reaches seeds before it reaches
the assignments and submissions that point at them, so a blocking link would
make the project impossible to delete.

Revision ID: 20260930_0008
Revises: 20260924_0007
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260930_0008"
down_revision: str | None = "20260924_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Give assignments an owner and a draft, and add the evidence tables."""
    op.alter_column(
        "annotation_assignments",
        "annotator_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
    op.add_column(
        "annotation_assignments",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column("annotation_assignments", "version", server_default=None)
    op.add_column(
        "annotation_assignments",
        sa.Column("draft", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "annotation_assignments",
        sa.Column("draft_saved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "annotation_assignments",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.alter_column("annotation_assignments", "updated_at", server_default=None)
    op.drop_constraint(
        "annotation_assignments_seed_document_id_fkey",
        "annotation_assignments",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "annotation_assignments_seed_document_id_fkey",
        "annotation_assignments",
        "imported_seed_documents",
        ["seed_document_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "annotation_submissions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("assignment_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("objects", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("seed_document_id", sa.String(length=36), nullable=True),
        sa.Column("submitted_by", sa.String(length=36), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["annotation_assignments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["seed_document_id"], ["imported_seed_documents.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "revision", name="uq_submission_revision"),
    )
    op.create_index(
        op.f("ix_annotation_submissions_assignment_id"),
        "annotation_submissions",
        ["assignment_id"],
    )
    op.create_index(
        op.f("ix_annotation_submissions_submitted_by"),
        "annotation_submissions",
        ["submitted_by"],
    )

    op.create_table(
        "resolved_annotations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_item_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("submission_id", sa.String(length=36), nullable=True),
        sa.Column("objects", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_item_id"], ["batch_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["annotation_submissions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_item_id", "version", name="uq_resolution_version"),
    )
    op.create_index(
        op.f("ix_resolved_annotations_batch_item_id"),
        "resolved_annotations",
        ["batch_item_id"],
    )
    op.create_index(
        op.f("ix_resolved_annotations_submission_id"),
        "resolved_annotations",
        ["submission_id"],
    )


def downgrade() -> None:
    """Remove the evidence tables and the assignment draft columns."""
    op.drop_index(
        op.f("ix_resolved_annotations_submission_id"),
        table_name="resolved_annotations",
    )
    op.drop_index(
        op.f("ix_resolved_annotations_batch_item_id"),
        table_name="resolved_annotations",
    )
    op.drop_table("resolved_annotations")

    op.drop_index(
        op.f("ix_annotation_submissions_submitted_by"),
        table_name="annotation_submissions",
    )
    op.drop_index(
        op.f("ix_annotation_submissions_assignment_id"),
        table_name="annotation_submissions",
    )
    op.drop_table("annotation_submissions")

    op.drop_constraint(
        "annotation_assignments_seed_document_id_fkey",
        "annotation_assignments",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "annotation_assignments_seed_document_id_fkey",
        "annotation_assignments",
        "imported_seed_documents",
        ["seed_document_id"],
        ["id"],
    )
    op.drop_column("annotation_assignments", "updated_at")
    op.drop_column("annotation_assignments", "draft_saved_at")
    op.drop_column("annotation_assignments", "draft")
    op.drop_column("annotation_assignments", "version")
    op.alter_column(
        "annotation_assignments",
        "annotator_id",
        existing_type=sa.String(length=36),
        nullable=True,
    )
