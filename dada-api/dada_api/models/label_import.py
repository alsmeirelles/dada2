"""Label import sessions, their source files, and the seed documents they produce."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dada_api.db.base import Base


class ImportFormat(StrEnum):
    """Source label formats the API can read, one per compatible task."""

    yolo_detection = "yolo_detection"
    coco_segmentation = "coco_segmentation"


class ImportStatus(StrEnum):
    """Lifecycle of one label import."""

    uploading = "uploading"
    validated = "validated"
    rejected = "rejected"
    accepted = "accepted"


class AnnotationImport(Base):
    """One owner/manager attempt to seed a prepared draft with existing labels.

    A project holds at most one import, so duplicate labels for an image are a
    property of a single import rather than a merge across several. The class
    index map and media fingerprint snapshot the preparation the import was
    validated against.
    """

    __tablename__ = "annotation_imports"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_annotation_import_project"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
    )
    format: Mapped[str] = mapped_column(String(32))
    parser_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default=ImportStatus.uploading)
    created_by: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
    )
    class_index_map: Mapped[dict[str, str]] = mapped_column(JSONB)
    media_fingerprint: Mapped[str] = mapped_column(String(64))
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class AnnotationImportFile(Base):
    """One source label file, retained verbatim as import provenance."""

    __tablename__ = "annotation_import_files"
    __table_args__ = (
        UniqueConstraint("import_id", "client_file_id", name="uq_import_file_client"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    import_id: Mapped[str] = mapped_column(
        ForeignKey("annotation_imports.id", ondelete="CASCADE"),
        index=True,
    )
    client_file_id: Mapped[str] = mapped_column(String(128))
    relative_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ImportedSeedDocument(Base):
    """The immutable labels an accepted import supplies for one image.

    A seed is never a submission, a consensus vote, or a resolution. It only
    prefills the editable work of each assignment for its image.
    """

    __tablename__ = "imported_seed_documents"
    __table_args__ = (
        UniqueConstraint("import_id", "media_id", name="uq_seed_document_media"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    import_id: Mapped[str] = mapped_column(
        ForeignKey("annotation_imports.id", ondelete="CASCADE"),
        index=True,
    )
    media_id: Mapped[str] = mapped_column(
        ForeignKey("media.id", ondelete="CASCADE"),
        index=True,
    )
    source_file_id: Mapped[str] = mapped_column(
        ForeignKey("annotation_import_files.id", ondelete="CASCADE"),
        index=True,
    )
    document: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
