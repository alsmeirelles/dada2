"""Bootstrap administrator record marking the initial identity of an installation."""

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from dada_api.db.base import Base

SINGLETON_ID = 1


class BootstrapRecord(Base):
    """The single record identifying the bootstrapped administrator.

    The check constraint keeps the table a singleton so a second bootstrap can
    never create a competing initial identity.
    """

    __tablename__ = "bootstrap_records"
    __table_args__ = (CheckConstraint("id = 1", name="ck_bootstrap_singleton"),)

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=False,
        default=SINGLETON_ID,
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
