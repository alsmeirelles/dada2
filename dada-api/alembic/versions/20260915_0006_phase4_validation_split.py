"""Add validation split sizing and percentage-based held-out sizes.

Revision ID: 20260915_0006
Revises: 20260908_0005
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260915_0006"
down_revision: str | None = "20260908_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store validation configuration and optional percentage definitions."""
    op.alter_column(
        "projects",
        "test_set_size",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.add_column(
        "projects", sa.Column("test_set_percentage", sa.Float(), nullable=True)
    )
    op.add_column(
        "projects",
        sa.Column(
            "validation_set_size",
            sa.Integer(),
            nullable=True,
            server_default="1",
        ),
    )
    op.alter_column("projects", "validation_set_size", server_default=None)
    op.add_column(
        "projects", sa.Column("validation_set_percentage", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    """Remove validation and percentage configuration."""
    op.execute("UPDATE projects SET test_set_size = 1 WHERE test_set_size IS NULL")
    op.drop_column("projects", "validation_set_percentage")
    op.drop_column("projects", "validation_set_size")
    op.drop_column("projects", "test_set_percentage")
    op.alter_column(
        "projects",
        "test_set_size",
        existing_type=sa.Integer(),
        nullable=False,
    )
