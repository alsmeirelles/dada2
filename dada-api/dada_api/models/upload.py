"""Resumable upload session, per-file item, and accepted chunk persistence."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dada_api.db.base import Base


class UploadStatus(StrEnum):
    """Lifecycle of one upload session."""

    pending = "pending"
    uploading = "uploading"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class UploadDisposition(StrEnum):
    """What the API decided about one manifest entry."""

    upload_required = "upload_required"
    already_present = "already_present"
    rejected = "rejected"


class UploadSession(Base):
    """One attempt to ingest a manifest of images into a project."""

    __tablename__ = "upload_sessions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default=UploadStatus.pending)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class UploadItem(Base):
    """One file inside an upload session, with the client's declared metadata.

    ``received_bytes`` is the next offset the API expects, which is what lets a
    client resume in the middle of a file after an interruption.
    """

    __tablename__ = "upload_items"
    __table_args__ = (
        UniqueConstraint("session_id", "client_file_id", name="uq_upload_item_client"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("upload_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    client_file_id: Mapped[str] = mapped_column(String(128))
    relative_path: Mapped[str] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    disposition: Mapped[str] = mapped_column(String(32))
    rejection_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    received_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class UploadChunk(Base):
    """One accepted byte range of an upload item.

    Retained so a repeated chunk at a known offset is recognised as a retry of
    identical bytes instead of an offset conflict.
    """

    __tablename__ = "upload_chunks"
    __table_args__ = (
        UniqueConstraint("item_id", "byte_offset", name="uq_upload_chunk_offset"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    item_id: Mapped[str] = mapped_column(
        ForeignKey("upload_items.id", ondelete="CASCADE"),
        index=True,
    )
    byte_offset: Mapped[int] = mapped_column(BigInteger)
    byte_length: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
