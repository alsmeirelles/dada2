"""Add acquisition-loop settings, learning runs, and model evaluations.

Projects gain the Phase 7 learning settings (D1) and the reason acquisition
stopped. Existing projects keep a null maximum, which means acquisition runs
until the eligible pool is exhausted. ``annotation_batches.model_run_id``
already existed without a target and now references the run that chose the
batch.

Revision ID: 20261123_0011
Revises: 20261014_0010
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261123_0011"
down_revision: str | None = "20261014_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Create the learning tables and the project learning settings."""
    op.add_column(
        "projects", sa.Column("max_acquisition_iterations", sa.Integer(), nullable=True)
    )
    op.add_column(
        "projects", sa.Column("learning_solution", sa.String(64), nullable=True)
    )
    op.add_column(
        "projects",
        sa.Column("learning_solution_version", sa.String(32), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column(
            "learning_configuration",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("projects", "learning_configuration", server_default=None)
    op.add_column(
        "projects", sa.Column("evaluation_metric", sa.String(32), nullable=True)
    )
    op.add_column(
        "projects", sa.Column("evaluation_interval", sa.Integer(), nullable=True)
    )
    op.add_column("projects", sa.Column("metric_target", sa.Float(), nullable=True))
    op.add_column(
        "projects", sa.Column("completion_reason", sa.String(32), nullable=True)
    )

    op.create_table(
        "learning_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("strategy", sa.String(32), nullable=False),
        sa.Column("solution", sa.String(64), nullable=True),
        sa.Column("solution_version", sa.String(32), nullable=True),
        sa.Column("configuration", JSONB, nullable=False),
        sa.Column("configuration_fingerprint", sa.String(64), nullable=False),
        sa.Column("requested_size", sa.Integer(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("evaluation", JSONB, nullable=True),
        sa.Column("snapshots", JSONB, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(32), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", JSONB, nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("failure_detail", sa.String(500), nullable=True),
        sa.Column(
            "requested_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id", "iteration", "attempt", name="uq_learning_run_attempt"
        ),
    )
    op.create_index("ix_learning_runs_project_id", "learning_runs", ["project_id"])
    op.create_index("ix_learning_runs_status", "learning_runs", ["status"])
    op.create_index(
        "uq_learning_run_active",
        "learning_runs",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "model_evaluations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("learning_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("split", sa.String(16), nullable=False),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("metrics", JSONB, nullable=False),
        sa.Column("model", JSONB, nullable=False),
        sa.Column("snapshot", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "split", name="uq_model_evaluation_split"),
    )
    op.create_index(
        "ix_model_evaluations_project_id", "model_evaluations", ["project_id"]
    )
    op.create_index("ix_model_evaluations_run_id", "model_evaluations", ["run_id"])

    op.create_foreign_key(
        "annotation_batches_model_run_id_fkey",
        "annotation_batches",
        "learning_runs",
        ["model_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Remove the learning tables and the project learning settings."""
    op.drop_constraint(
        "annotation_batches_model_run_id_fkey",
        "annotation_batches",
        type_="foreignkey",
    )
    op.drop_index("ix_model_evaluations_run_id", table_name="model_evaluations")
    op.drop_index("ix_model_evaluations_project_id", table_name="model_evaluations")
    op.drop_table("model_evaluations")
    op.drop_index("uq_learning_run_active", table_name="learning_runs")
    op.drop_index("ix_learning_runs_status", table_name="learning_runs")
    op.drop_index("ix_learning_runs_project_id", table_name="learning_runs")
    op.drop_table("learning_runs")
    for column in (
        "completion_reason",
        "metric_target",
        "evaluation_interval",
        "evaluation_metric",
        "learning_configuration",
        "learning_solution_version",
        "learning_solution",
        "max_acquisition_iterations",
    ):
        op.drop_column("projects", column)
