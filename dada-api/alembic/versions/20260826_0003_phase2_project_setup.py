"""Add project classes, annotation policy defaults, and the audit trail.

Revision ID: 20260826_0003
Revises: 20260812_0002
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260826_0003"
down_revision: str | None = "20260812_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

annotation_mode = postgresql.ENUM(
    "single", "consensus", name="annotation_mode", create_type=False
)


def upgrade() -> None:
    """Create the Phase 2 project setup tables and the single-owner index."""
    op.create_index(
        "uq_project_single_owner",
        "project_members",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("role = 'owner'"),
    )

    op.create_table(
        "project_classes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_project_class_name"),
        sa.UniqueConstraint(
            "project_id", "display_order", name="uq_project_class_order"
        ),
    )
    op.create_index(
        op.f("ix_project_classes_project_id"), "project_classes", ["project_id"]
    )

    annotation_mode.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "annotation_policy_defaults",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("mode", annotation_mode, nullable=False),
        sa.Column("resolver", sa.String(length=64), nullable=True),
        sa.Column("resolver_version", sa.String(length=32), nullable=True),
        sa.Column(
            "parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "review_thresholds", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )

    op.create_table(
        "annotation_policy_annotators",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("policy_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["policy_id"], ["annotation_policy_defaults.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_id", "user_id", name="uq_policy_annotator"),
        sa.UniqueConstraint(
            "policy_id", "position", name="uq_policy_annotator_position"
        ),
    )
    op.create_index(
        op.f("ix_annotation_policy_annotators_policy_id"),
        "annotation_policy_annotators",
        ["policy_id"],
    )
    op.create_index(
        op.f("ix_annotation_policy_annotators_user_id"),
        "annotation_policy_annotators",
        ["user_id"],
    )

    op.create_table(
        "audit_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_entries_action"), "audit_entries", ["action"])
    op.create_index(
        op.f("ix_audit_entries_actor_user_id"), "audit_entries", ["actor_user_id"]
    )
    op.create_index(
        op.f("ix_audit_entries_project_id"), "audit_entries", ["project_id"]
    )


def downgrade() -> None:
    """Remove the Phase 2 project setup tables and the single-owner index."""
    op.drop_index(op.f("ix_audit_entries_project_id"), table_name="audit_entries")
    op.drop_index(op.f("ix_audit_entries_actor_user_id"), table_name="audit_entries")
    op.drop_index(op.f("ix_audit_entries_action"), table_name="audit_entries")
    op.drop_table("audit_entries")

    op.drop_index(
        op.f("ix_annotation_policy_annotators_user_id"),
        table_name="annotation_policy_annotators",
    )
    op.drop_index(
        op.f("ix_annotation_policy_annotators_policy_id"),
        table_name="annotation_policy_annotators",
    )
    op.drop_table("annotation_policy_annotators")
    op.drop_table("annotation_policy_defaults")
    annotation_mode.drop(op.get_bind(), checkfirst=True)

    op.drop_index(op.f("ix_project_classes_project_id"), table_name="project_classes")
    op.drop_table("project_classes")

    op.drop_index("uq_project_single_owner", table_name="project_members")
