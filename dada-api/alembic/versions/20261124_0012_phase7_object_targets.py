"""Let a batch item name one object target inside its image.

Model-guided detection and segmentation acquisition creates one item per
selected object target (D16). The item keeps the proposed geometry and the
context area around it, and the uniqueness of an image inside its batch now
includes the target. Whole-image items keep a null target, which is still
unique per image because nulls are not distinct in the constraint.

Revision ID: 20261124_0012
Revises: 20261123_0011
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261124_0012"
down_revision: str | None = "20261123_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Add the target columns and widen the item uniqueness to the target."""
    op.add_column("batch_items", sa.Column("target_key", sa.String(64), nullable=True))
    op.add_column("batch_items", sa.Column("target_geometry", JSONB, nullable=True))
    op.add_column("batch_items", sa.Column("target_region", JSONB, nullable=True))
    op.drop_constraint("uq_batch_item", "batch_items", type_="unique")
    op.create_unique_constraint(
        "uq_batch_item",
        "batch_items",
        ["batch_id", "media_id", "target_key"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    """Remove target items, then restore one item per image."""
    op.execute("DELETE FROM batch_items WHERE target_key IS NOT NULL")
    op.drop_constraint("uq_batch_item", "batch_items", type_="unique")
    op.create_unique_constraint(
        "uq_batch_item", "batch_items", ["batch_id", "media_id"]
    )
    op.drop_column("batch_items", "target_region")
    op.drop_column("batch_items", "target_geometry")
    op.drop_column("batch_items", "target_key")
