"""Project quality statistics for owners and managers (D20, P7-05).

Three measures describe how annotation went, never who did it:

- **review rate**: resolved items that needed reviewers or an expert, over
  resolved items;
- **resolution rate**: resolved items over items that were not cancelled;
- **agreement**: the median, over the first-round candidates of resolved
  items, of the task's consensus metric: the winner's vote share for
  classification, the median pairwise box IoU for detection, and the median
  pairwise mask IoU or Dice for segmentation.

An item is one image, or one object target in model-guided acquisition. Every
value stays hidden until 30 items are resolved, and any value resting on
fewer than 5 observations is hidden too. Single-mode items have no consensus
run, so they add nothing to the agreement.
"""

import statistics
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.models.batch import AnnotationBatch, BatchItem, ItemStatus
from dada_api.models.consensus import ResolutionInput, ResolutionWorkItem
from dada_api.models.project import Project
from dada_api.models.resolution import ResolutionProposal, ResolutionRun
from dada_api.services.performance import MINIMUM_CELL, MINIMUM_DECISIONS

FIRST_ROUND = 1


@dataclass(frozen=True)
class ItemQuality:
    """What one batch item contributes to the project's quality.

    Attributes:
        status: The item's status.
        reviewed: Whether reviewers or an expert were needed for its current
            evidence.
        agreement: ``(metric, value)`` pairs of its first-round candidates.
    """

    status: str
    reviewed: bool
    agreement: list[tuple[str, float]]


def agreement(
    task_type: str, candidates: list[dict[str, Any]]
) -> list[tuple[str, float]]:
    """Return the agreement values a first-round proposal records.

    Args:
        task_type: The project's task.
        candidates: The proposal's candidate decisions.

    Returns:
        One ``(metric, value)`` pair per candidate that has one: a candidate
        supported by a single geometry has no pairwise overlap.
    """
    values = []
    for candidate in candidates:
        metrics = candidate.get("metrics", {})
        if task_type == "classification":
            support = metrics.get("support")
            if support and support["denominator"]:
                values.append(
                    ("winner_support", support["numerator"] / support["denominator"])
                )
        elif task_type == "detection":
            if metrics.get("median_iou") is not None:
                values.append(("box_iou", metrics["median_iou"]))
        elif metrics.get("median_overlap") is not None:
            values.append(
                (f"mask_{metrics['matching_metric']}", metrics["median_overlap"])
            )
    return values


async def collect(session: AsyncSession, project: Project) -> list[ItemQuality]:
    """Read what every batch item of a project contributes.

    Only the item's current evidence generation counts, and its first round
    is the latest run over the first input of that generation.

    Args:
        session: Active database session.
        project: Project being measured.

    Returns:
        One entry per batch item.
    """
    items = list(
        await session.execute(
            select(BatchItem.id, BatchItem.status)
            .join(AnnotationBatch, AnnotationBatch.id == BatchItem.batch_id)
            .where(AnnotationBatch.project_id == project.id)
        )
    )
    current_input = and_(
        ResolutionInput.batch_item_id == BatchItem.id,
        ResolutionInput.evidence_generation == BatchItem.initial_evidence_generation,
    )
    reviewed = set(
        await session.scalars(
            select(ResolutionWorkItem.batch_item_id)
            .join(
                ResolutionInput,
                ResolutionInput.id == ResolutionWorkItem.resolution_input_id,
            )
            .join(BatchItem, current_input)
            .join(AnnotationBatch, AnnotationBatch.id == BatchItem.batch_id)
            .where(AnnotationBatch.project_id == project.id)
            .distinct()
        )
    )
    first_round: dict[str, list[dict[str, Any]]] = {}
    for item_id, candidates in await session.execute(
        select(ResolutionRun.batch_item_id, ResolutionProposal.candidates)
        .join(ResolutionProposal, ResolutionProposal.run_id == ResolutionRun.id)
        .join(ResolutionInput, ResolutionInput.id == ResolutionRun.resolution_input_id)
        .join(BatchItem, current_input)
        .join(AnnotationBatch, AnnotationBatch.id == BatchItem.batch_id)
        .where(
            AnnotationBatch.project_id == project.id,
            ResolutionInput.run_number == FIRST_ROUND,
        )
        .order_by(ResolutionRun.batch_item_id, ResolutionRun.sequence.desc())
    ):
        first_round.setdefault(item_id, candidates)
    return [
        ItemQuality(
            status=status,
            reviewed=item_id in reviewed,
            agreement=agreement(project.task_type, first_round.get(item_id, [])),
        )
        for item_id, status in items
    ]


def report(task_type: str, items: list[ItemQuality]) -> dict[str, Any]:
    """Aggregate the items into the published measures, suppressing small
    samples (P7-05).

    Args:
        task_type: The project's task.
        items: What each batch item contributes.

    Returns:
        The quality report.
    """
    counted = [item for item in items if item.status != ItemStatus.cancelled]
    resolved = [item for item in counted if item.status == ItemStatus.resolved]
    suppressed = len(resolved) < MINIMUM_DECISIONS

    def share(numerator: int, denominator: int) -> float | None:
        """Return a ratio unless it must stay hidden."""
        if suppressed or denominator < MINIMUM_CELL:
            return None
        return round(numerator / denominator, 6)

    values: dict[str, list[float]] = {}
    for item in resolved:
        for metric, value in item.agreement:
            values.setdefault(metric, []).append(value)
    return {
        "task_type": task_type,
        "total_items": len(counted),
        "resolved_items": len(resolved),
        "minimum_decisions": MINIMUM_DECISIONS,
        "minimum_cell": MINIMUM_CELL,
        "suppressed": suppressed,
        "review_rate": share(sum(item.reviewed for item in resolved), len(resolved)),
        "resolution_rate": share(len(resolved), len(counted)),
        "agreement": [
            {
                "metric": metric,
                "observations": len(found),
                "median": None
                if suppressed or len(found) < MINIMUM_CELL
                else round(statistics.median(found), 6),
            }
            for metric, found in sorted(values.items())
        ],
    }
