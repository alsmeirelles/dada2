"""Project quality report schema."""

from typing import Literal

from pydantic import BaseModel

from dada_api.schemas.project import TaskType

AgreementMetricName = Literal["winner_support", "box_iou", "mask_iou", "mask_dice"]


class AgreementSummary(BaseModel):
    """The median first-round agreement of one consensus metric.

    ``median`` is null when the report is suppressed or fewer than
    ``minimum_cell`` candidates measured it.
    """

    metric: AgreementMetricName
    observations: int
    median: float | None


class QualityReport(BaseModel):
    """Project-level quality measures for owners and managers (D20).

    An item is one image or one object target. Every rate and median is null
    until ``minimum_decisions`` items are resolved, and a value backed by
    fewer than ``minimum_cell`` observations is null as well. Nothing here
    names or ranks an annotator.
    """

    task_type: TaskType
    total_items: int
    resolved_items: int
    minimum_decisions: int
    minimum_cell: int
    suppressed: bool
    review_rate: float | None
    resolution_rate: float | None
    agreement: list[AgreementSummary]
