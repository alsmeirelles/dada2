"""Add resolver runs, proposals, adjudication, leases, and evidence.

Audit entries may now have no actor, which records the system acting on its
own (P6-06 automatic acceptance). The Phase 5.1 work-item uniqueness that
ignored the evidence generation is dropped: per-input uniqueness remains, and
a reopened image must be able to raise the same candidate again.

The provisional Phase 2 resolver IDs become the Phase 6 pipeline IDs with the
first-release defaults of P6-02, in the policy defaults and in every batch
snapshot. The defaults are written here as literal JSON so the migration keeps
meaning the same thing if the catalog's defaults later change. The old opaque
``agreement`` threshold has no equivalent and is dropped; the downgrade
restores the provisional IDs with empty settings.

Revision ID: 20261014_0010
Revises: 20261007_0009
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261014_0010"
down_revision: str | None = "20261007_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PIPELINES = {
    "majority_vote": (
        "statistical_class_consensus",
        '{"class_strategy":{"strategy":"multilabel_binary_vote"}}',
        '{"minimum_support":{"numerator":2,"denominator":3}}',
    ),
    "two_stage_box_fusion": (
        "two_stage_detection_consensus",
        '{"class_strategy":{"strategy":"categorical_vote",'
        '"decision_rule":"supermajority"},"matching_iou":0.5,'
        '"box_refinement":{"strategy":"coordinate_median"}}',
        '{"minimum_support":{"numerator":2,"denominator":3},"minimum_median_iou":0.5}',
    ),
    "two_stage_mask_fusion": (
        "two_stage_segmentation_consensus",
        '{"class_strategy":{"strategy":"categorical_vote",'
        '"decision_rule":"supermajority"},"matching_metric":"iou",'
        '"matching_threshold":0.5,'
        '"mask_refinement":{"strategy":"segmentation_majority_vote"},'
        '"post_processing":{"remove_components_below":null,'
        '"fill_holes_below":null,"simplify_tolerance":null}}',
        '{"minimum_support":{"numerator":2,"denominator":3},'
        '"minimum_median_overlap":0.5}',
    ),
}
POLICY_TABLES = ("annotation_policy_defaults", "annotation_batches")
JSONB = postgresql.JSONB(astext_type=sa.Text())


def _timestamp(name: str, nullable: bool = False) -> sa.Column:
    """Return a timezone-aware timestamp column."""
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _index(table: str, *columns: str) -> None:
    """Create the conventional single-column indexes of a table."""
    for column in columns:
        op.create_index(op.f(f"ix_{table}_{column}"), table, [column])


def upgrade() -> None:
    """Install the Phase 6 resolution persistence and migrate resolver IDs."""
    op.create_table(
        "resolver_quarantines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("identifier", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        _timestamp("triggered_at"),
        _timestamp("released_at", nullable=True),
        sa.Column("released_by", sa.String(length=36), nullable=True),
        sa.Column("release_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["released_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_resolver_quarantine_open",
        "resolver_quarantines",
        ["identifier", "version"],
        unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
    )

    op.create_table(
        "resolver_calibration_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("corpus", JSONB, nullable=False),
        sa.Column("parameters", JSONB, nullable=False),
        sa.Column("eligibility", JSONB, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        _timestamp("created_at"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("resolver_calibration_snapshots", "project_id")

    op.create_table(
        "resolution_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("batch_item_id", sa.String(length=36), nullable=False),
        sa.Column("resolution_input_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("pipeline", sa.String(length=64), nullable=False),
        sa.Column("pipeline_version", sa.String(length=32), nullable=False),
        sa.Column("configuration", JSONB, nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("dependency_versions", JSONB, nullable=False),
        sa.Column("queue", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        _timestamp("next_attempt_at", nullable=True),
        _timestamp("dispatched_at", nullable=True),
        _timestamp("started_at", nullable=True),
        _timestamp("finished_at", nullable=True),
        _timestamp("cancel_requested_at", nullable=True),
        sa.Column("effective_limits", JSONB, nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_detail", sa.String(length=500), nullable=True),
        sa.Column("output_checksum", sa.String(length=64), nullable=True),
        sa.Column("requested_by", sa.String(length=36), nullable=True),
        _timestamp("created_at"),
        sa.ForeignKeyConstraint(
            ["batch_item_id"], ["batch_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["resolution_input_id"], ["resolution_inputs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_item_id", "sequence", name="uq_resolution_run_sequence"
        ),
    )
    _index(
        "resolution_runs",
        "batch_item_id",
        "project_id",
        "resolution_input_id",
        "status",
    )
    op.create_index(
        "uq_resolution_run_active",
        "resolution_runs",
        ["batch_item_id", "configuration_fingerprint"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "resolution_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("batch_item_id", sa.String(length=36), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("objects", JSONB, nullable=False),
        sa.Column("candidates", JSONB, nullable=False),
        sa.Column("diagnostics", JSONB, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        _timestamp("created_at"),
        sa.ForeignKeyConstraint(
            ["batch_item_id"], ["batch_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["resolution_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_resolution_proposal_run"),
    )
    _index("resolution_proposals", "batch_item_id")

    op.create_table(
        "resolution_leases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("work_item_id", sa.String(length=36), nullable=False),
        sa.Column("holder_id", sa.String(length=36), nullable=False),
        _timestamp("acquired_at"),
        _timestamp("renewed_at"),
        _timestamp("expires_at"),
        _timestamp("cap_at"),
        _timestamp("released_at", nullable=True),
        sa.Column("revoked_by", sa.String(length=36), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["holder_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revoked_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["work_item_id"], ["resolution_work_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("resolution_leases", "holder_id", "work_item_id")
    op.create_index(
        "uq_resolution_lease_open",
        "resolution_leases",
        ["work_item_id"],
        unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
    )

    op.add_column(
        "resolved_annotations", sa.Column("run_id", sa.String(length=36), nullable=True)
    )
    op.add_column(
        "resolved_annotations",
        sa.Column("proposal_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "resolved_annotations",
        sa.Column("accepted_by", sa.String(length=36), nullable=True),
    )
    op.add_column("resolved_annotations", _timestamp("superseded_at", nullable=True))
    op.create_foreign_key(
        "resolved_annotations_run_id_fkey",
        "resolved_annotations",
        "resolution_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "resolved_annotations_proposal_id_fkey",
        "resolved_annotations",
        "resolution_proposals",
        ["proposal_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "resolved_annotations_accepted_by_fkey",
        "resolved_annotations",
        "users",
        ["accepted_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_resolution_current",
        "resolved_annotations",
        ["batch_item_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    op.create_table(
        "adjudications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("batch_item_id", sa.String(length=36), nullable=False),
        sa.Column("work_item_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("actor_role", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("source_proposal_id", sa.String(length=36), nullable=True),
        sa.Column("source_submission_id", sa.String(length=36), nullable=True),
        sa.Column("objects", JSONB, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("contributor_conflict", sa.Boolean(), nullable=False),
        sa.Column("contribution_submission_ids", JSONB, nullable=False),
        sa.Column("independence_required", sa.Boolean(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("expected_evidence_generation", sa.Integer(), nullable=False),
        sa.Column(
            "expected_configuration_fingerprint", sa.String(length=64), nullable=True
        ),
        sa.Column("expected_resolution_version", sa.Integer(), nullable=False),
        sa.Column("resolved_annotation_id", sa.String(length=36), nullable=True),
        _timestamp("created_at"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["batch_item_id"], ["batch_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["resolved_annotation_id"], ["resolved_annotations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_proposal_id"], ["resolution_proposals.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_submission_id"], ["annotation_submissions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["work_item_id"], ["resolution_work_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    _index("adjudications", "actor_id", "batch_item_id", "project_id", "work_item_id")

    op.create_table(
        "annotator_performance_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("annotator_id", sa.String(length=36), nullable=False),
        sa.Column("assignment_id", sa.String(length=36), nullable=True),
        sa.Column("submission_id", sa.String(length=36), nullable=True),
        sa.Column("review_submission_id", sa.String(length=36), nullable=True),
        sa.Column("batch_item_id", sa.String(length=36), nullable=False),
        sa.Column("resolution_id", sa.String(length=36), nullable=False),
        sa.Column("resolution_version", sa.Integer(), nullable=False),
        sa.Column("observation_key", sa.String(length=200), nullable=False),
        sa.Column("evaluation_source", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=16), nullable=False),
        sa.Column("submitted_class_id", sa.String(length=36), nullable=True),
        sa.Column("canonical_class_id", sa.String(length=36), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("metric_name", sa.String(length=32), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column("weighting_eligible", sa.Boolean(), nullable=False),
        sa.Column("summary_eligible", sa.Boolean(), nullable=False),
        _timestamp("created_at"),
        sa.ForeignKeyConstraint(["annotator_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["annotation_assignments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["batch_item_id"], ["batch_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["resolution_id"], ["resolved_annotations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["review_submission_id"], ["review_submissions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["annotation_submissions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resolution_id", "observation_key", name="uq_performance_observation_key"
        ),
    )
    _index(
        "annotator_performance_observations",
        "annotator_id",
        "batch_item_id",
        "project_id",
        "resolution_id",
    )

    op.create_table(
        "resolution_object_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resolution_id", sa.String(length=36), nullable=False),
        sa.Column("batch_item_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_key", sa.String(length=200), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("submission_id", sa.String(length=36), nullable=True),
        sa.Column("review_submission_id", sa.String(length=36), nullable=True),
        sa.Column("annotator_id", sa.String(length=36), nullable=False),
        sa.Column("source_object_id", sa.String(length=64), nullable=True),
        sa.Column("candidate_key", sa.String(length=128), nullable=True),
        sa.Column("canonical_object_id", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        _timestamp("created_at"),
        sa.ForeignKeyConstraint(["annotator_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["batch_item_id"], ["batch_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["resolution_id"], ["resolved_annotations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["review_submission_id"], ["review_submissions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["annotation_submissions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resolution_id", "evidence_key", name="uq_object_evidence_key"
        ),
    )
    _index(
        "resolution_object_evidence", "annotator_id", "batch_item_id", "resolution_id"
    )

    op.drop_constraint(
        "uq_resolution_candidate_run", "resolution_work_items", type_="unique"
    )
    op.add_column(
        "resolution_work_items",
        sa.Column("reason", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "resolution_work_items",
        sa.Column("run_id", sa.String(length=36), nullable=True),
    )
    op.add_column("resolution_work_items", _timestamp("closed_at", nullable=True))
    op.create_foreign_key(
        "resolution_work_items_run_id_fkey",
        "resolution_work_items",
        "resolution_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )

    for table in POLICY_TABLES:
        op.add_column(
            table,
            sa.Column(
                "require_independent_adjudicator",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        op.alter_column(table, "require_independent_adjudicator", server_default=None)
    op.add_column(
        "annotation_batches",
        sa.Column("calibration_snapshot_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "annotation_batches_calibration_snapshot_id_fkey",
        "annotation_batches",
        "resolver_calibration_snapshots",
        ["calibration_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.alter_column("audit_entries", "actor_user_id", nullable=True)

    for table in POLICY_TABLES:
        for provisional, (pipeline, parameters, thresholds) in PIPELINES.items():
            op.execute(
                sa.text(
                    f"UPDATE {table} SET resolver = :pipeline, "
                    "resolver_version = '1.0.0', "
                    "parameters = CAST(:parameters AS JSONB), "
                    "review_thresholds = CAST(:thresholds AS JSONB) "
                    "WHERE resolver = :provisional"
                ).bindparams(
                    pipeline=pipeline,
                    parameters=parameters,
                    thresholds=thresholds,
                    provisional=provisional,
                )
            )


def downgrade() -> None:
    """Remove the Phase 6 resolution persistence and restore resolver IDs.

    System-actor audit entries cannot be represented once the actor is
    required again, so the downgrade deletes them.
    """
    op.execute("DELETE FROM audit_entries WHERE actor_user_id IS NULL")
    op.alter_column("audit_entries", "actor_user_id", nullable=False)
    for table in POLICY_TABLES:
        for provisional, (pipeline, _, _) in PIPELINES.items():
            op.execute(
                sa.text(
                    f"UPDATE {table} SET resolver = :provisional, "
                    "resolver_version = NULL, parameters = '{}'::jsonb, "
                    "review_thresholds = '{}'::jsonb WHERE resolver = :pipeline"
                ).bindparams(provisional=provisional, pipeline=pipeline)
            )

    op.drop_constraint(
        "annotation_batches_calibration_snapshot_id_fkey",
        "annotation_batches",
        type_="foreignkey",
    )
    op.drop_column("annotation_batches", "calibration_snapshot_id")
    for table in POLICY_TABLES:
        op.drop_column(table, "require_independent_adjudicator")

    op.drop_constraint(
        "resolution_work_items_run_id_fkey",
        "resolution_work_items",
        type_="foreignkey",
    )
    for column in ("closed_at", "run_id", "reason"):
        op.drop_column("resolution_work_items", column)
    op.create_unique_constraint(
        "uq_resolution_candidate_run",
        "resolution_work_items",
        ["batch_item_id", "candidate_key", "source_run_number"],
    )

    op.drop_table("resolution_object_evidence")
    op.drop_table("annotator_performance_observations")
    op.drop_table("adjudications")

    op.drop_index("uq_resolution_current", table_name="resolved_annotations")
    for name in ("run_id", "proposal_id", "accepted_by"):
        op.drop_constraint(
            f"resolved_annotations_{name}_fkey",
            "resolved_annotations",
            type_="foreignkey",
        )
    for column in ("superseded_at", "accepted_by", "proposal_id", "run_id"):
        op.drop_column("resolved_annotations", column)

    op.drop_table("resolution_leases")
    op.drop_table("resolution_proposals")
    op.drop_table("resolution_runs")
    op.drop_table("resolver_calibration_snapshots")
    op.drop_table("resolver_quarantines")
