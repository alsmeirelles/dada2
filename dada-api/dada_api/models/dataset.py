"""Frozen train, validation, and test membership created at activation."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from dada_api.db.base import Base


class SplitName(StrEnum):
    """Which part of the frozen dataset a media item belongs to."""

    train = "train"
    validation = "validation"
    test = "test"


class DatasetSplit(Base):
    """One media item's permanent train, validation, or test assignment.

    Rows are written once, in the activation transaction, and never updated.
    Validation and test are annotated but excluded from active-learning
    acquisition, so this membership keeps both evaluation sets honest.
    """

    __tablename__ = "dataset_splits"
    __table_args__ = (
        UniqueConstraint("project_id", "media_id", name="uq_dataset_split_media"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    media_id: Mapped[str] = mapped_column(
        ForeignKey("media.id", ondelete="CASCADE"),
        index=True,
    )
    split: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
