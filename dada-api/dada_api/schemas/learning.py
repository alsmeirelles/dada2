"""Acquisition iteration and statistics response schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from dada_api.schemas.project import (
    AcquisitionStrategyName,
    CompletionReasonName,
    EvaluationMetricName,
)

IterationStatusName = Literal[
    "training", "preparing", "annotating", "consolidating", "ready", "failed"
]


class EvaluationView(BaseModel):
    """One target-model evaluation on a held-out split."""

    iteration: int
    split: Literal["validation", "test"]
    metric: EvaluationMetricName
    value: float
    metrics: dict[str, float]
    model: dict[str, Any]
    created_at: datetime


class IterationResponse(BaseModel):
    """One acquisition iteration: its latest run attempt plus its batch (D6).

    ``id`` is the first attempt's identifier and stays stable across retries.
    ``stage`` is reported by the worker while ``status`` is ``training``.
    Counts are zero until the iteration has a batch, and ``eta_seconds`` is
    always null in Phase 7.
    """

    id: str
    number: int
    purpose: Literal["selection", "final_evaluation"]
    status: IterationStatusName
    stage: Literal["training", "evaluating", "selecting"] | None
    strategy: AcquisitionStrategyName
    attempt: int
    solution: str | None
    solution_version: str | None
    batch_id: str | None
    requested_size: int
    selected_count: int | None
    shortfall_reason: str | None
    stop_reason: Literal["metric_target"] | None
    failure_code: str | None
    failure_detail: str | None
    total_count: int
    resolved_count: int
    review_required_count: int
    available_count: int
    total_assignment_count: int
    submitted_assignment_count: int
    eta_seconds: int | None
    metrics: dict[str, float]
    evaluations: list[EvaluationView]
    started_at: datetime
    completed_at: datetime | None


class IterationPage(BaseModel):
    """Cursor-paginated iterations plus the most recent one."""

    items: list[IterationResponse]
    current_iteration: IterationResponse | None
    next_cursor: str | None = None


class StatisticsResponse(BaseModel):
    """Acquisition progress and the target-model evaluations so far."""

    project_id: str
    acquisition_strategy: AcquisitionStrategyName
    max_acquisition_iterations: int | None
    completed_iterations: int
    completion_reason: CompletionReasonName | None
    evaluation_metric: EvaluationMetricName | None
    metric_target: float | None
    evaluations: list[EvaluationView]
