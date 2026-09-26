"""Project, membership, and object-class persistence."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from dada_api.db.base import Base


class ProjectRole(StrEnum):
    """Authority a user holds inside one project."""

    owner = "owner"
    manager = "manager"
    annotator = "annotator"
    viewer = "viewer"


class AcquisitionStrategy(StrEnum):
    """How training batches after the initial one will be selected."""

    random = "random"
    active_learning = "active_learning"


class DatasetLayout(StrEnum):
    """How a project's media is organised into annotation work.

    ``split`` freezes train, validation, and test membership. ``single_batch``
    annotates every image once in one static batch and never trains or
    acquires, so it is only available to random projects.
    """

    split = "split"
    single_batch = "single_batch"


class Project(Base):
    """Annotation project owned by exactly one user.

    ``owner_id`` always records the truthful creator. A global administrator
    holds owner-equivalent authority without being recorded as the owner.

    ``dataset_prepared_at`` is set while a draft's layout is materialised and
    cleared when that preparation is reset.
    """

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
    )
    acquisition_strategy: Mapped[str] = mapped_column(
        String(32), default=AcquisitionStrategy.random
    )
    dataset_layout: Mapped[str] = mapped_column(String(16), default=DatasetLayout.split)
    initial_training_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    test_set_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    test_set_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    validation_set_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validation_set_percentage: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    iteration_batch_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dataset_prepared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
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


ANNOTATION_ROLES = frozenset(
    {ProjectRole.owner, ProjectRole.manager, ProjectRole.annotator}
)


class ProjectMember(Base):
    """Role a user holds in one project."""

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
        Index(
            "uq_project_single_owner",
            "project_id",
            unique=True,
            postgresql_where=text("role = 'owner'"),
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
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[ProjectRole] = mapped_column(Enum(ProjectRole, name="project_role"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class ProjectClass(Base):
    """One object class annotators may assign inside a project."""

    __tablename__ = "project_classes"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_project_class_name"),
        UniqueConstraint("project_id", "display_order", name="uq_project_class_order"),
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
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str] = mapped_column(String(7))
    display_order: Mapped[int] = mapped_column(Integer)
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
