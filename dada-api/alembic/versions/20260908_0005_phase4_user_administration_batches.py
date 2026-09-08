"""Add user versioning, global audit entries, frozen splits, and annotation batches.

Revision ID: 20260908_0005
Revises: 20260901_0004
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260908_0005"
down_revision: str | None = "20260901_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the Phase 4 tables and widen users and audit entries."""
    op.add_column(
        "users",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column("users", "version", server_default=None)

    op.alter_column(
        "audit_entries",
        "project_id",
        existing_type=sa.String(length=36),
        nullable=True,
    )

    op.create_table(
        "dataset_splits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("media_id", sa.String(length=36), nullable=False),
        sa.Column("split", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "media_id", name="uq_dataset_split_media"),
    )
    op.create_index(op.f("ix_dataset_splits_media_id"), "dataset_splits", ["media_id"])
    op.create_index(
        op.f("ix_dataset_splits_project_id"), "dataset_splits", ["project_id"]
    )

    op.create_table(
        "annotation_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("resolver", sa.String(length=64), nullable=True),
        sa.Column("resolver_version", sa.String(length=32), nullable=True),
        sa.Column(
            "parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "review_thresholds", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("source_policy_version", sa.Integer(), nullable=False),
        sa.Column("selection_strategy", sa.String(length=32), nullable=False),
        sa.Column("selection_seed", sa.BigInteger(), nullable=False),
        sa.Column("selection_input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("requested_size", sa.Integer(), nullable=False),
        sa.Column("model_run_id", sa.String(length=36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_annotation_batches_project_id"), "annotation_batches", ["project_id"]
    )
    op.create_index(
        op.f("ix_annotation_batches_status"), "annotation_batches", ["status"]
    )

    op.create_table(
        "annotation_batch_annotators",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["annotation_batches.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "position", name="uq_batch_annotator_position"),
        sa.UniqueConstraint("batch_id", "user_id", name="uq_batch_annotator"),
    )
    op.create_index(
        op.f("ix_annotation_batch_annotators_batch_id"),
        "annotation_batch_annotators",
        ["batch_id"],
    )
    op.create_index(
        op.f("ix_annotation_batch_annotators_user_id"),
        "annotation_batch_annotators",
        ["user_id"],
    )

    op.create_table(
        "batch_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("media_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["annotation_batches.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "media_id", name="uq_batch_item"),
    )
    op.create_index(op.f("ix_batch_items_batch_id"), "batch_items", ["batch_id"])
    op.create_index(op.f("ix_batch_items_media_id"), "batch_items", ["media_id"])

    op.create_table(
        "annotation_assignments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_item_id", sa.String(length=36), nullable=False),
        sa.Column("annotator_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["annotator_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["batch_item_id"], ["batch_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_item_id", "annotator_id", name="uq_assignment_owner"
        ),
    )
    op.create_index(
        op.f("ix_annotation_assignments_annotator_id"),
        "annotation_assignments",
        ["annotator_id"],
    )
    op.create_index(
        op.f("ix_annotation_assignments_batch_item_id"),
        "annotation_assignments",
        ["batch_item_id"],
    )


def downgrade() -> None:
    """Remove the Phase 4 tables and restore the earlier column definitions."""
    op.drop_index(
        op.f("ix_annotation_assignments_batch_item_id"),
        table_name="annotation_assignments",
    )
    op.drop_index(
        op.f("ix_annotation_assignments_annotator_id"),
        table_name="annotation_assignments",
    )
    op.drop_table("annotation_assignments")

    op.drop_index(op.f("ix_batch_items_media_id"), table_name="batch_items")
    op.drop_index(op.f("ix_batch_items_batch_id"), table_name="batch_items")
    op.drop_table("batch_items")

    op.drop_index(
        op.f("ix_annotation_batch_annotators_user_id"),
        table_name="annotation_batch_annotators",
    )
    op.drop_index(
        op.f("ix_annotation_batch_annotators_batch_id"),
        table_name="annotation_batch_annotators",
    )
    op.drop_table("annotation_batch_annotators")

    op.drop_index(op.f("ix_annotation_batches_status"), table_name="annotation_batches")
    op.drop_index(
        op.f("ix_annotation_batches_project_id"), table_name="annotation_batches"
    )
    op.drop_table("annotation_batches")

    op.drop_index(op.f("ix_dataset_splits_project_id"), table_name="dataset_splits")
    op.drop_index(op.f("ix_dataset_splits_media_id"), table_name="dataset_splits")
    op.drop_table("dataset_splits")

    op.execute("DELETE FROM audit_entries WHERE project_id IS NULL")
    op.alter_column(
        "audit_entries",
        "project_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )

    op.drop_column("users", "version")
