"""Verified image content and its appearances inside a project's dataset."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from dada_api.db.base import Base


class ContentObject(Base):
    """One verified byte sequence stored for a project.

    Content is identified by its digest and byte length rather than by file
    name. Rows are scoped to a project so deleting that project can purge its
    bytes without consulting references held by any other project.
    """

    __tablename__ = "content_objects"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "sha256", "size_bytes", name="uq_content_object_digest"
        ),
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
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    media_type: Mapped[str] = mapped_column(String(64))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class Media(Base):
    """One image in a project's dataset, at one path relative to the upload root.

    Two rows may share a content object because the same image genuinely
    appears at two paths in a scanned folder tree.
    """

    __tablename__ = "media"
    __table_args__ = (
        UniqueConstraint("project_id", "relative_path", name="uq_media_relative_path"),
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
    content_object_id: Mapped[str] = mapped_column(
        ForeignKey("content_objects.id", ondelete="CASCADE"),
        index=True,
    )
    relative_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
