"""Phase 7 acquisition runs and the target-model evaluations they produce."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dada_api.db.base import Base

BATCH_RESOLVED_EVENT = "learning.batch_resolved.v1"


class LearningRunStatus(StrEnum):
    """Lifecycle of one attempt at choosing or evaluating an iteration.

    ``queued`` and ``running`` are the active states; at most one active run
    exists per project.
    """

    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


ACTIVE_LEARNING_RUN_STATUSES = (LearningRunStatus.queued, LearningRunStatus.running)


class LearningRunPurpose(StrEnum):
    """What a run is for: choosing the next batch, or the final evaluation."""

    selection = "selection"
    final_evaluation = "final_evaluation"


class CompletionReason(StrEnum):
    """Why a project stopped acquiring."""

    max_iterations = "max_iterations"
    metric_target = "metric_target"
    pool_exhausted = "pool_exhausted"


class LearningRun(Base):
    """One attempt at iteration ``iteration`` of a project's acquisition loop.

    The row is also the durable job: Celery only transports its identifier.
    Every attempt of an iteration shares the same snapshots, configuration,
    and seed, so a retry repeats exactly the same request.
    """

    __tablename__ = "learning_runs"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "iteration", "attempt", name="uq_learning_run_attempt"
        ),
        Index(
            "uq_learning_run_active",
            "project_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    iteration: Mapped[int] = mapped_column(Integer)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    purpose: Mapped[str] = mapped_column(String(32))
    strategy: Mapped[str] = mapped_column(String(32))
    solution: Mapped[str | None] = mapped_column(String(64), nullable=True)
    solution_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64))
    requested_size: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(BigInteger)
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    snapshots: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(
        String(32), default=LearningRunStatus.queued, index=True
    )
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    requested_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ModelEvaluation(Base):
    """A target-model metric reported by one run on one held-out split."""

    __tablename__ = "model_evaluations"
    __table_args__ = (
        UniqueConstraint("run_id", "split", name="uq_model_evaluation_split"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("learning_runs.id", ondelete="CASCADE"), index=True
    )
    iteration: Mapped[int] = mapped_column(Integer)
    split: Mapped[str] = mapped_column(String(16))
    metric: Mapped[str] = mapped_column(String(32))
    value: Mapped[float] = mapped_column(Float)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    model: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    snapshot: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
