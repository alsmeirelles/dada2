"""Invariant-preserving Phase 6 input and candidate-review construction."""

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.errors import ApiError
from dada_api.models.batch import (
    AnnotationBatch,
    AnnotationBatchAnnotator,
    AnnotationItemAnnotator,
    BatchItem,
)
from dada_api.models.consensus import (
    OutboxEvent,
    ResolutionInput,
    ResolutionWorkItem,
    ReviewAssignment,
)
from dada_api.services import cohort_selection
from dada_api.services.assignments import INITIAL_EVIDENCE_READY_EVENT


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


async def create_initial_input(session: AsyncSession, event_id: str) -> ResolutionInput:
    """Consume one readiness event into an immutable initial input snapshot."""
    existing = await session.scalar(
        select(ResolutionInput).where(ResolutionInput.source_event_id == event_id)
    )
    if existing is not None:
        return existing

    event = await session.get(OutboxEvent, event_id)
    if event is None or event.event_type != INITIAL_EVIDENCE_READY_EVENT:
        raise ApiError(404, "not_found", "The readiness event does not exist.")
    item = await session.get(BatchItem, event.aggregate_id)
    if item is None:
        raise ApiError(404, "not_found", "The batch item does not exist.")
    if item.initial_evidence_generation != event.generation:
        raise ApiError(
            409,
            "stale_evidence_generation",
            "The readiness event belongs to an obsolete evidence generation.",
            details={"current_generation": item.initial_evidence_generation},
        )

    source_inputs = list(event.payload["inputs"])
    snapshot = ResolutionInput(
        batch_item_id=item.id,
        source_event_id=event.id,
        evidence_generation=event.generation,
        run_number=1,
        source_inputs=source_inputs,
        candidate_mapping={},
        content_hash=_hash(source_inputs),
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def create_review_work_item(
    session: AsyncSession,
    source_input: ResolutionInput,
    *,
    candidate_key: str,
    candidate_ordinal: int,
    scope: str,
    candidate_context: dict[str, Any],
) -> tuple[ResolutionWorkItem, list[ReviewAssignment]]:
    """Create one frozen work item and its distinct deterministic reviewers."""
    if scope not in {"image", "candidate"}:
        raise ValueError("scope must be image or candidate")
    existing = await session.scalar(
        select(ResolutionWorkItem).where(
            ResolutionWorkItem.resolution_input_id == source_input.id,
            ResolutionWorkItem.candidate_key == candidate_key,
        )
    )
    if existing is not None:
        rows = list(
            await session.scalars(
                select(ReviewAssignment)
                .where(ReviewAssignment.work_item_id == existing.id)
                .order_by(ReviewAssignment.position)
            )
        )
        return existing, rows

    item = await session.get(BatchItem, source_input.batch_item_id)
    batch = await session.get(AnnotationBatch, item.batch_id)
    pool = list(
        await session.scalars(
            select(AnnotationBatchAnnotator.user_id)
            .where(AnnotationBatchAnnotator.batch_id == batch.id)
            .order_by(AnnotationBatchAnnotator.position)
        )
    )
    initial = list(
        await session.scalars(
            select(AnnotationItemAnnotator.annotator_id)
            .where(
                AnnotationItemAnnotator.batch_item_id == item.id,
                AnnotationItemAnnotator.generation == source_input.evidence_generation,
            )
            .order_by(AnnotationItemAnnotator.position)
        )
    )
    earlier = list(
        await session.scalars(
            select(ReviewAssignment.reviewer_id)
            .join(
                ResolutionWorkItem,
                ResolutionWorkItem.id == ReviewAssignment.work_item_id,
            )
            .where(
                ResolutionWorkItem.batch_item_id == item.id,
                ResolutionWorkItem.candidate_key == candidate_key,
            )
        )
    )
    try:
        reviewers = cohort_selection.review_cohort(
            pool,
            item_position=item.position,
            initial_annotator_ids=initial,
            candidate_ordinal=candidate_ordinal,
            required=batch.required_consensus_reviewers,
            earlier_reviewer_ids=earlier,
        )
    except ValueError as exc:
        raise ApiError(
            409,
            "review_cohort_unavailable",
            "The frozen pool cannot supply the required independent reviewers.",
        ) from exc

    work_item = ResolutionWorkItem(
        resolution_input_id=source_input.id,
        batch_item_id=item.id,
        candidate_key=candidate_key,
        candidate_ordinal=candidate_ordinal,
        scope=scope,
        source_run_number=source_input.run_number,
        candidate_context=candidate_context,
    )
    session.add(work_item)
    await session.flush()
    excluded = initial + earlier
    assignments = [
        ReviewAssignment(
            work_item_id=work_item.id,
            reviewer_id=reviewer_id,
            position=position,
            selection_algorithm=cohort_selection.REVIEW_ALGORITHM,
            ordered_pool=pool,
            excluded_reviewer_ids=excluded,
        )
        for position, reviewer_id in enumerate(reviewers)
    ]
    session.add_all(assignments)
    await session.flush()
    return work_item, assignments
