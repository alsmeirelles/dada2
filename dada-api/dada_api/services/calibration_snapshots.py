"""Frozen calibration snapshots of the conditional class strategies (D11)."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.consensus import catalog, protocol
from dada_api.core.errors import ApiError
from dada_api.models.annotation import ResolvedAnnotation
from dada_api.models.batch import AnnotationBatch, BatchItem
from dada_api.models.project import Project, ProjectClass
from dada_api.models.resolution import (
    CalibrationSnapshot,
    PerformanceObservation,
    ResolutionProposal,
)
from dada_api.services.performance import SECONDARY_METRICS

CONDITIONAL = ("reliability_weighted_vote", "dawid_skene")
NO_OBJECT = "no_object"
POSITIVE, NEGATIVE = "positive", "negative"


@dataclass(frozen=True)
class Built:
    """A conditional strategy's evidence verdict and, when eligible, its
    parameters shaped as the pipeline reads them.

    Attributes:
        strategy: Strategy identifier.
        eligible: Whether every gate passed.
        missing: The exact unmet prerequisites.
        parameters: ``{class_id: snapshot}`` for classification, or
            ``{"candidates": snapshot}`` for detection and segmentation.
        corpus: Identifiers of the evidence used.
        report: Counts the verdict was computed from.
    """

    strategy: str
    eligible: bool
    missing: list[dict[str, Any]]
    parameters: dict[str, Any]
    corpus: dict[str, Any]
    report: dict[str, Any]


async def _class_ids(session: AsyncSession, project: Project) -> list[str]:
    """Return the project's classes in display order."""
    return list(
        await session.scalars(
            select(ProjectClass.id)
            .where(ProjectClass.project_id == project.id)
            .order_by(ProjectClass.display_order)
        )
    )


async def _references(
    session: AsyncSession, project: Project
) -> tuple[list[Any], list[str]]:
    """Return the expert-adjudicated decisions usable as reliability evidence.

    Only weighting-eligible observations of current resolutions count, so an
    annotator's weight never comes from automated consensus they influenced.
    """
    from dada_api.consensus import calibration

    rows = list(
        await session.scalars(
            select(PerformanceObservation).where(
                PerformanceObservation.project_id == project.id,
                PerformanceObservation.weighting_eligible.is_(True),
                PerformanceObservation.summary_eligible.is_(True),
                PerformanceObservation.metric_name.not_in(SECONDARY_METRICS),
                PerformanceObservation.outcome != "duplicate",
            )
        )
    )
    if project.task_type == "classification":
        references = [
            calibration.Reference(
                row.annotator_id,
                POSITIVE if row.submitted_class_id else NEGATIVE,
                POSITIVE if row.canonical_class_id else NEGATIVE,
            )
            for row in rows
        ]
    else:
        references = [
            calibration.Reference(
                row.annotator_id,
                row.submitted_class_id or NO_OBJECT,
                row.canonical_class_id or NO_OBJECT,
            )
            for row in rows
        ]
    return references, sorted({row.resolution_id for row in rows})


async def _matrices(
    session: AsyncSession, project: Project
) -> tuple[list[dict[str, dict[str, str]]], list[str]]:
    """Return the observation matrices of the project's current resolutions."""
    rows = (
        await session.execute(
            select(ResolutionProposal.diagnostics, ResolvedAnnotation.id)
            .join(
                ResolvedAnnotation,
                ResolvedAnnotation.proposal_id == ResolutionProposal.id,
            )
            .join(BatchItem, BatchItem.id == ResolvedAnnotation.batch_item_id)
            .join(AnnotationBatch, AnnotationBatch.id == BatchItem.batch_id)
            .where(
                AnnotationBatch.project_id == project.id,
                ResolvedAnnotation.superseded_at.is_(None),
            )
            .order_by(ResolvedAnnotation.created_at, ResolvedAnnotation.id)
        )
    ).all()
    return [diagnostics.get("observation_matrix", {}) for diagnostics, _ in rows], [
        resolution_id for _, resolution_id in rows
    ]


async def build(
    session: AsyncSession, project: Project, strategy: str, pool: list[str]
) -> Built:
    """Compute a conditional strategy's verdict over the project's evidence.

    Args:
        session: Active database session.
        project: Project whose evidence is used.
        strategy: ``reliability_weighted_vote`` or ``dawid_skene``.
        pool: Annotators who must all be covered.

    Returns:
        The verdict and, when eligible, the frozen parameters.
    """
    from dada_api.consensus import calibration
    from dada_api.consensus.class_strategies import Vote

    class_ids = await _class_ids(session, project)
    candidates = project.task_type != "classification"
    outcomes = [*class_ids, NO_OBJECT] if candidates else [POSITIVE, NEGATIVE]

    if strategy == "reliability_weighted_vote":
        references, resolutions = await _references(session, project)
        result = calibration.reliability_weights(references, pool, outcomes)
        parameters = (
            {"candidates": result.parameters}
            if candidates
            else {class_id: result.parameters for class_id in class_ids}
        )
        return Built(
            strategy,
            result.eligible,
            list(result.missing),
            parameters if result.eligible else {},
            {"resolution_ids": resolutions},
            result.report,
        )

    matrices, resolutions = await _matrices(session, project)
    if candidates:
        items = [
            [Vote(rater, outcome) for rater, outcome in sorted(votes.items())]
            for matrix in matrices
            for votes in matrix.values()
        ]
        result = calibration.dawid_skene(items, pool, outcomes)
        return Built(
            strategy,
            result.eligible,
            list(result.missing),
            {"candidates": result.parameters} if result.eligible else {},
            {"resolution_ids": resolutions},
            result.report,
        )

    fits = {
        class_id: calibration.dawid_skene(
            [
                [
                    Vote(rater, outcome)
                    for rater, outcome in sorted(matrix.get(class_id, {}).items())
                ]
                for matrix in matrices
                if matrix.get(class_id)
            ],
            pool,
            outcomes,
        )
        for class_id in class_ids
    }
    eligible = all(fit.eligible for fit in fits.values())
    return Built(
        strategy,
        eligible,
        [
            {**gap, "class_id": class_id}
            for class_id, fit in fits.items()
            for gap in fit.missing
        ],
        {class_id: fit.parameters for class_id, fit in fits.items()}
        if eligible
        else {},
        {"resolution_ids": resolutions},
        {class_id: fit.report for class_id, fit in fits.items()},
    )


async def freeze(
    session: AsyncSession, project: Project, batch: AnnotationBatch, pool: list[str]
) -> None:
    """Freeze a conditional strategy's snapshot onto a starting batch.

    Args:
        session: Active database session; the caller commits.
        project: Project of the batch.
        batch: Batch being started.
        pool: The batch's frozen eligible pool.

    Raises:
        ApiError: 422 ``resolver_unavailable`` naming every unmet prerequisite
            when the project's evidence is insufficient; no other strategy is
            substituted.
    """
    strategy = batch.parameters.get("class_strategy", {}).get("strategy")
    if strategy not in CONDITIONAL:
        return
    built = await build(session, project, strategy, pool)
    if not built.eligible:
        raise ApiError(
            422,
            "resolver_unavailable",
            "The project's evidence cannot calibrate this strategy yet.",
            details={"strategy": strategy, "missing": built.missing},
        )
    snapshot = CalibrationSnapshot(
        project_id=project.id,
        strategy=strategy,
        strategy_version=catalog.VERSION,
        corpus=built.corpus,
        parameters=built.parameters,
        eligibility=built.report,
        content_hash=protocol.fingerprint(built.parameters),
    )
    session.add(snapshot)
    await session.flush()
    batch.calibration_snapshot_id = snapshot.id


async def eligibility(
    session: AsyncSession, project: Project, pool: list[str]
) -> list[Built]:
    """Report whether each conditional strategy could be calibrated now.

    Args:
        session: Active database session.
        project: Project whose evidence is checked.
        pool: The default policy's eligible pool.

    Returns:
        One verdict per conditional strategy, naming every unmet prerequisite.
    """
    if not pool:
        return [
            Built(
                strategy,
                False,
                [{"requirement": "consensus_pool"}],
                {},
                {},
                {},
            )
            for strategy in CONDITIONAL
        ]
    return [await build(session, project, strategy, pool) for strategy in CONDITIONAL]
