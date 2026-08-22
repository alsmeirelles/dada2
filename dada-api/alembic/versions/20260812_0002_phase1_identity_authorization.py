"""Add refresh sessions, bootstrap records, project membership, and admin flag.

Revision ID: 20260812_0002
Revises: 20260719_0001
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260812_0002"
down_revision: str | None = "20260719_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_role = postgresql.ENUM("annotator", "admin", name="user_role", create_type=False)
project_role = postgresql.ENUM(
    "owner", "manager", "annotator", "viewer", name="project_role", create_type=False
)


def upgrade() -> None:
    """Swap the global role enum for an admin flag and add the identity tables."""
    op.add_column(
        "users",
        sa.Column(
            "is_administrator",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute("UPDATE users SET is_administrator = true WHERE role = 'admin'")
    op.alter_column("users", "is_administrator", server_default=None)
    op.create_index(op.f("ix_users_is_administrator"), "users", ["is_administrator"])
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_column("users", "role")
    user_role.drop(op.get_bind(), checkfirst=True)

    op.create_table(
        "refresh_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("family_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_refresh_sessions_family_id"), "refresh_sessions", ["family_id"]
    )
    op.create_index(
        op.f("ix_refresh_sessions_user_id"), "refresh_sessions", ["user_id"]
    )

    op.create_table(
        "bootstrap_records",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_bootstrap_singleton"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("initial_training_size", sa.Integer(), nullable=False),
        sa.Column("test_set_size", sa.Integer(), nullable=False),
        sa.Column("iteration_batch_size", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_owner_id"), "projects", ["owner_id"])
    op.create_index(op.f("ix_projects_status"), "projects", ["status"])

    project_role.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "project_members",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", project_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )
    op.create_index(
        op.f("ix_project_members_project_id"), "project_members", ["project_id"]
    )
    op.create_index(op.f("ix_project_members_user_id"), "project_members", ["user_id"])


def downgrade() -> None:
    """Restore the global role enum and remove the Phase 1 identity tables."""
    op.drop_index(op.f("ix_project_members_user_id"), table_name="project_members")
    op.drop_index(op.f("ix_project_members_project_id"), table_name="project_members")
    op.drop_table("project_members")
    project_role.drop(op.get_bind(), checkfirst=True)

    op.drop_index(op.f("ix_projects_status"), table_name="projects")
    op.drop_index(op.f("ix_projects_owner_id"), table_name="projects")
    op.drop_table("projects")
    op.drop_table("bootstrap_records")

    op.drop_index(op.f("ix_refresh_sessions_user_id"), table_name="refresh_sessions")
    op.drop_index(op.f("ix_refresh_sessions_family_id"), table_name="refresh_sessions")
    op.drop_table("refresh_sessions")

    user_role.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "users",
        sa.Column("role", user_role, nullable=False, server_default="annotator"),
    )
    op.execute("UPDATE users SET role = 'admin' WHERE is_administrator = true")
    op.alter_column("users", "role", server_default=None)
    op.create_index(op.f("ix_users_role"), "users", ["role"])
    op.drop_index(op.f("ix_users_is_administrator"), table_name="users")
    op.drop_column("users", "is_administrator")
