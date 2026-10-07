"""Add selected consensus cohorts, durable readiness, and scoped review.

Revision ID: 20261007_0009
Revises: 20260930_0008
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261007_0009"
down_revision: str | None = "20260930_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Install the Phase 5.1 persistence boundary."""
    # Earlier consensus batches used every pool member and cannot be interpreted
    # as selected cohorts. Refuse to rewrite or delete that evidence implicitly;
    # development environments must explicitly reset and rebuild those batches.
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM annotation_batches WHERE mode = 'consensus') THEN "
        "RAISE EXCEPTION 'Phase 5.1 requires legacy consensus batches to be "
        "reset and rebuilt before migration'; "
        "END IF; END $$"
    )

    for table in ("annotation_policy_defaults", "annotation_batches"):
        op.add_column(
            table,
            sa.Column("required_consensus_annotations", sa.Integer(), nullable=True),
        )
        op.add_column(
            table,
            sa.Column("required_consensus_reviewers", sa.Integer(), nullable=True),
        )

    op.execute(
        "UPDATE annotation_policy_defaults "
        "SET required_consensus_annotations = 2, required_consensus_reviewers = 1 "
        "WHERE mode = 'consensus'"
    )
    op.create_check_constraint(
        "ck_policy_consensus_counts",
        "annotation_policy_defaults",
        "(mode = 'single' AND required_consensus_annotations IS NULL "
        "AND required_consensus_reviewers IS NULL) OR "
        "(mode = 'consensus' AND required_consensus_annotations >= 2 "
        "AND required_consensus_reviewers >= 1)",
    )
    op.create_check_constraint(
        "ck_batch_consensus_counts",
        "annotation_batches",
        "(mode = 'single' AND required_consensus_annotations IS NULL "
        "AND required_consensus_reviewers IS NULL) OR "
        "(mode = 'consensus' AND required_consensus_annotations >= 2 "
        "AND required_consensus_reviewers >= 1)",
    )

    op.add_column("batch_items", sa.Column("position", sa.Integer(), nullable=True))
    op.execute(
        "WITH ranked AS ("
        " SELECT batch_items.id, row_number() OVER "
        "(PARTITION BY batch_items.batch_id ORDER BY media.relative_path, media.id) "
        "- 1 AS pos"
        " FROM batch_items JOIN media ON media.id = batch_items.media_id"
        ") UPDATE batch_items SET position = ranked.pos FROM ranked "
        "WHERE batch_items.id = ranked.id"
    )
    op.alter_column("batch_items", "position", nullable=False)
    op.add_column(
        "batch_items",
        sa.Column(
            "initial_evidence_generation",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.alter_column("batch_items", "initial_evidence_generation", server_default=None)

    op.create_table(
        "annotation_item_annotators",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_item_id", sa.String(length=36), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("annotator_id", sa.String(length=36), nullable=False),
        sa.Column("assignment_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("pool_position", sa.Integer(), nullable=False),
        sa.Column("selection_algorithm", sa.String(length=32), nullable=False),
        sa.Column(
            "ordered_pool", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_item_id"], ["batch_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["annotator_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["annotation_assignments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_item_id",
            "generation",
            "annotator_id",
            name="uq_item_cohort_annotator",
        ),
        sa.UniqueConstraint(
            "batch_item_id",
            "generation",
            "position",
            name="uq_item_cohort_position",
        ),
    )
    for column in ("batch_item_id", "annotator_id", "assignment_id"):
        op.create_index(
            op.f(f"ix_annotation_item_annotators_{column}"),
            "annotation_item_annotators",
            [column],
        )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=96), nullable=False),
        sa.Column("aggregate_type", sa.String(length=32), nullable=False),
        sa.Column("aggregate_id", sa.String(length=36), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_type",
            "aggregate_id",
            "generation",
            name="uq_outbox_event_generation",
        ),
    )
    for column in ("project_id", "event_type", "aggregate_id"):
        op.create_index(op.f(f"ix_outbox_events_{column}"), "outbox_events", [column])

    op.create_table(
        "resolution_inputs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_item_id", sa.String(length=36), nullable=False),
        sa.Column("source_event_id", sa.String(length=36), nullable=True),
        sa.Column("evidence_generation", sa.Integer(), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column(
            "source_inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "candidate_mapping",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_item_id"], ["batch_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id"], ["outbox_events.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_item_id",
            "evidence_generation",
            "run_number",
            name="uq_resolution_input_run",
        ),
        sa.UniqueConstraint("source_event_id", name="uq_resolution_input_event"),
    )
    op.create_index(
        op.f("ix_resolution_inputs_batch_item_id"),
        "resolution_inputs",
        ["batch_item_id"],
    )

    op.create_table(
        "resolution_work_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resolution_input_id", sa.String(length=36), nullable=False),
        sa.Column("batch_item_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_key", sa.String(length=128), nullable=False),
        sa.Column("candidate_ordinal", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("source_run_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "candidate_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["resolution_input_id"], ["resolution_inputs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["batch_item_id"], ["batch_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resolution_input_id", "candidate_key", name="uq_resolution_candidate"
        ),
        sa.UniqueConstraint(
            "batch_item_id",
            "candidate_key",
            "source_run_number",
            name="uq_resolution_candidate_run",
        ),
    )
    op.create_index(
        op.f("ix_resolution_work_items_resolution_input_id"),
        "resolution_work_items",
        ["resolution_input_id"],
    )
    op.create_index(
        op.f("ix_resolution_work_items_batch_item_id"),
        "resolution_work_items",
        ["batch_item_id"],
    )
    op.create_index(
        op.f("ix_resolution_work_items_status"), "resolution_work_items", ["status"]
    )

    op.create_table(
        "review_assignments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("work_item_id", sa.String(length=36), nullable=False),
        sa.Column("reviewer_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("draft", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("draft_saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("selection_algorithm", sa.String(length=32), nullable=False),
        sa.Column(
            "ordered_pool", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "excluded_reviewer_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["work_item_id"], ["resolution_work_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("work_item_id", "reviewer_id", name="uq_review_reviewer"),
        sa.UniqueConstraint("work_item_id", "position", name="uq_review_position"),
    )
    for column in ("work_item_id", "reviewer_id", "status"):
        op.create_index(
            op.f(f"ix_review_assignments_{column}"), "review_assignments", [column]
        )

    op.create_table(
        "review_submissions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("review_assignment_id", sa.String(length=36), nullable=False),
        sa.Column("work_item_id", sa.String(length=36), nullable=False),
        sa.Column("source_input_id", sa.String(length=36), nullable=False),
        sa.Column("reviewer_id", sa.String(length=36), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["review_assignment_id"], ["review_assignments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["work_item_id"], ["resolution_work_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_input_id"], ["resolution_inputs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_assignment_id", name="uq_review_submission"),
        sa.UniqueConstraint(
            "work_item_id", "reviewer_id", name="uq_review_submission_reviewer"
        ),
    )
    for column in (
        "review_assignment_id",
        "work_item_id",
        "source_input_id",
        "reviewer_id",
    ):
        op.create_index(
            op.f(f"ix_review_submissions_{column}"), "review_submissions", [column]
        )


def downgrade() -> None:
    """Remove the Phase 5.1 persistence boundary."""
    op.drop_table("review_submissions")
    op.drop_table("review_assignments")
    op.drop_table("resolution_work_items")
    op.drop_table("resolution_inputs")
    op.drop_table("outbox_events")
    op.drop_table("annotation_item_annotators")
    op.drop_column("batch_items", "initial_evidence_generation")
    op.drop_column("batch_items", "position")
    op.drop_constraint("ck_batch_consensus_counts", "annotation_batches", type_="check")
    op.drop_constraint(
        "ck_policy_consensus_counts", "annotation_policy_defaults", type_="check"
    )
    for table in ("annotation_batches", "annotation_policy_defaults"):
        op.drop_column(table, "required_consensus_reviewers")
        op.drop_column(table, "required_consensus_annotations")
