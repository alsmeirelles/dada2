"""Default annotation policy persistence and its ordered consensus group."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dada_api.db.base import Base


class AnnotationMode(StrEnum):
    """How many independent submissions a selected image requires."""

    single = "single"
    consensus = "consensus"


class AnnotationPolicyDefault(Base):
    """The project's default annotation policy.

    Later phases snapshot this record into each annotation batch, so editing it
    never changes work that has already started.
    """

    __tablename__ = "annotation_policy_defaults"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        unique=True,
    )
    mode: Mapped[AnnotationMode] = mapped_column(
        Enum(AnnotationMode, name="annotation_mode"),
        default=AnnotationMode.single,
    )
    resolver: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolver_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    review_thresholds: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class AnnotationPolicyAnnotator(Base):
    """One annotator's place in a policy's ordered group.

    The group is normalized rather than a JSON column because later phases
    generate one assignment per member and must join on the user.
    """

    __tablename__ = "annotation_policy_annotators"
    __table_args__ = (
        UniqueConstraint("policy_id", "user_id", name="uq_policy_annotator"),
        UniqueConstraint("policy_id", "position", name="uq_policy_annotator_position"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("annotation_policy_defaults.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer)
