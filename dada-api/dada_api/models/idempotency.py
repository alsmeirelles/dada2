"""Durable idempotent request result model."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from dada_api.db.base import Base


class IdempotencyRecord(Base):
    """Stored response for a mutating request and caller scope."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "scope", "method", "path", "key", name="uq_idempotency_request"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(1024))
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    response_content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
