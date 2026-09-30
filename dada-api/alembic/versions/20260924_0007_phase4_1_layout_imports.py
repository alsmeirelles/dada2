"""Add dataset layout, draft preparation, label imports, and assignment seeds.

Revision ID: 20260924_0007
Revises: 20260915_0006
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260924_0007"
down_revision: str | None = "20260915_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the label import tables and widen projects and assignments."""
    op.add_column(
        "projects",
        sa.Column(
            "acquisition_strategy",
            sa.String(length=32),
            nullable=False,
            server_default="random",
        ),
    )
    op.alter_column("projects", "acquisition_strategy", server_default=None)
    op.add_column(
        "projects",
        sa.Column(
            "dataset_layout",
            sa.String(length=16),
            nullable=False,
            server_default="split",
        ),
    )
    op.alter_column("projects", "dataset_layout", server_default=None)
    op.add_column(
        "projects",
        sa.Column("dataset_prepared_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column(
        "projects",
        "initial_training_size",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "projects",
        "iteration_batch_size",
        existing_type=sa.Integer(),
        nullable=True,
    )

    op.create_table(
        "annotation_imports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("parser_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column(
            "class_index_map", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("media_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_annotation_import_project"),
    )
    op.create_index(
        op.f("ix_annotation_imports_created_by"), "annotation_imports", ["created_by"]
    )

    op.create_table(
        "annotation_import_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("import_id", sa.String(length=36), nullable=False),
        sa.Column("client_file_id", sa.String(length=128), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["import_id"], ["annotation_imports.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "import_id", "client_file_id", name="uq_import_file_client"
        ),
    )
    op.create_index(
        op.f("ix_annotation_import_files_import_id"),
        "annotation_import_files",
        ["import_id"],
    )

    op.create_table(
        "imported_seed_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("import_id", sa.String(length=36), nullable=False),
        sa.Column("media_id", sa.String(length=36), nullable=False),
        sa.Column("source_file_id", sa.String(length=36), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["import_id"], ["annotation_imports.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_file_id"], ["annotation_import_files.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_id", "media_id", name="uq_seed_document_media"),
    )
    op.create_index(
        op.f("ix_imported_seed_documents_import_id"),
        "imported_seed_documents",
        ["import_id"],
    )
    op.create_index(
        op.f("ix_imported_seed_documents_media_id"),
        "imported_seed_documents",
        ["media_id"],
    )
    op.create_index(
        op.f("ix_imported_seed_documents_source_file_id"),
        "imported_seed_documents",
        ["source_file_id"],
    )

    op.add_column(
        "annotation_assignments",
        sa.Column(
            "seed_document_id",
            sa.String(length=36),
            sa.ForeignKey("imported_seed_documents.id"),
            nullable=True,
        ),
    )
    op.create_index(
        op.f("ix_annotation_assignments_seed_document_id"),
        "annotation_assignments",
        ["seed_document_id"],
    )


def downgrade() -> None:
    """Remove label imports and restore the earlier project columns.

    The earlier schema has no optional training sizes. A missing first-batch
    size is restored as the iteration size it resolved to, and a static
    project without an iteration size receives one, so no project is lost.
    """
    op.drop_index(
        op.f("ix_annotation_assignments_seed_document_id"),
        table_name="annotation_assignments",
    )
    op.drop_column("annotation_assignments", "seed_document_id")

    op.drop_index(
        op.f("ix_imported_seed_documents_source_file_id"),
        table_name="imported_seed_documents",
    )
    op.drop_index(
        op.f("ix_imported_seed_documents_media_id"),
        table_name="imported_seed_documents",
    )
    op.drop_index(
        op.f("ix_imported_seed_documents_import_id"),
        table_name="imported_seed_documents",
    )
    op.drop_table("imported_seed_documents")

    op.drop_index(
        op.f("ix_annotation_import_files_import_id"),
        table_name="annotation_import_files",
    )
    op.drop_table("annotation_import_files")

    op.drop_index(
        op.f("ix_annotation_imports_created_by"), table_name="annotation_imports"
    )
    op.drop_table("annotation_imports")

    op.execute(
        "UPDATE projects SET iteration_batch_size = 1 "
        "WHERE iteration_batch_size IS NULL"
    )
    op.execute(
        "UPDATE projects SET initial_training_size = iteration_batch_size "
        "WHERE initial_training_size IS NULL"
    )
    op.alter_column(
        "projects",
        "iteration_batch_size",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "projects",
        "initial_training_size",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_column("projects", "dataset_prepared_at")
    op.drop_column("projects", "dataset_layout")
    op.drop_column("projects", "acquisition_strategy")
