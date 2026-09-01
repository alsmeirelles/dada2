"""Add resumable upload sessions, verified content objects, and project media.

Revision ID: 20260901_0004
Revises: 20260826_0003
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260901_0004"
down_revision: str | None = "20260826_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the Phase 3 ingestion and media tables."""
    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_upload_sessions_project_id"), "upload_sessions", ["project_id"]
    )

    op.create_table(
        "upload_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("client_file_id", sa.String(length=128), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("disposition", sa.String(length=32), nullable=False),
        sa.Column("rejection_reason", sa.String(length=64), nullable=True),
        sa.Column("received_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["upload_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id", "client_file_id", name="uq_upload_item_client"
        ),
    )
    op.create_index(op.f("ix_upload_items_session_id"), "upload_items", ["session_id"])

    op.create_table(
        "upload_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("byte_offset", sa.BigInteger(), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["upload_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "byte_offset", name="uq_upload_chunk_offset"),
    )
    op.create_index(op.f("ix_upload_chunks_item_id"), "upload_chunks", ["item_id"])

    op.create_table(
        "content_objects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "sha256", "size_bytes", name="uq_content_object_digest"
        ),
    )
    op.create_index(
        op.f("ix_content_objects_project_id"), "content_objects", ["project_id"]
    )

    op.create_table(
        "media",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("content_object_id", sa.String(length=36), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_object_id"], ["content_objects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "relative_path", name="uq_media_relative_path"
        ),
    )
    op.create_index(op.f("ix_media_content_object_id"), "media", ["content_object_id"])
    op.create_index(op.f("ix_media_project_id"), "media", ["project_id"])


def downgrade() -> None:
    """Remove the Phase 3 ingestion and media tables."""
    op.drop_index(op.f("ix_media_project_id"), table_name="media")
    op.drop_index(op.f("ix_media_content_object_id"), table_name="media")
    op.drop_table("media")

    op.drop_index(op.f("ix_content_objects_project_id"), table_name="content_objects")
    op.drop_table("content_objects")

    op.drop_index(op.f("ix_upload_chunks_item_id"), table_name="upload_chunks")
    op.drop_table("upload_chunks")

    op.drop_index(op.f("ix_upload_items_session_id"), table_name="upload_items")
    op.drop_table("upload_items")

    op.drop_index(op.f("ix_upload_sessions_project_id"), table_name="upload_sessions")
    op.drop_table("upload_sessions")
