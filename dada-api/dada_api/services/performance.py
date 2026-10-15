"""Immutable annotator performance observations derived at acceptance (P6-07)."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.consensus.numeric import at_least, quantize
from dada_api.models.annotation import AnnotationSubmission, ResolvedAnnotation
from dada_api.models.batch import BatchItem
from dada_api.models.consensus import ResolutionInput, ReviewSubmission
from dada_api.models.media import ContentObject, Media
from dada_api.models.project import ProjectClass
from dada_api.models.resolution import (
    PerformanceObservation,
    ResolutionObjectEvidence,
)

MINIMUM_DECISIONS = 30
SECONDARY_METRICS = ("mask_dice",)
MINIMUM_CELL = 5
AUTOMATED_CONSENSUS = "automated_consensus"
HUMAN_ADJUDICATION = "human_adjudication"
WEIGHTING_SOURCES = (HUMAN_ADJUDICATION, "gold_standard")


@dataclass(frozen=True)
class Part:
    """What one candidate contributed to an accepted resolution.

    Attributes:
        key: Candidate key, ``image`` for an image-wide decision.
        objects: Objects the candidate contributes, before renumbering.
        evaluation_source: ``automated_consensus`` or ``human_adjudication``.
        canonical_ids: IDs the objects received in the resolution.
    """

    key: str
    objects: list[dict[str, Any]]
    evaluation_source: str
    canonical_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Observer:
    """One rater's document entering the resolution."""

    kind: str
    id: str
    annotator_id: str
    assignment_id: str | None
    objects: list[dict[str, Any]]
    candidate_key: str | None = None


async def _observers(
    session: AsyncSession, source_input: ResolutionInput
) -> list[Observer]:
    """Load every submission and review the accepted resolution was built on."""
    observers = []
    for reference in source_input.source_inputs:
        if reference.get("kind", "submission") == "submission":
            submission = await session.get(
                AnnotationSubmission, reference["submission_id"]
            )
            observers.append(
                Observer(
                    "submission",
                    submission.id,
                    reference["annotator_id"],
                    reference["assignment_id"],
                    submission.objects,
                )
            )
        else:
            review = await session.get(
                ReviewSubmission, reference["review_submission_id"]
            )
            evidence = review.evidence
            if "class_ids" in evidence:
                objects = [
                    {"id": class_id, "class_id": class_id}
                    for class_id in evidence["class_ids"]
                ]
            elif evidence.get("decision") == "object":
                objects = [
                    {
                        "id": reference["candidate_key"],
                        "class_id": evidence["class_id"],
                        "geometry": evidence["geometry"],
                    }
                ]
            else:
                objects = []
            observers.append(
                Observer(
                    "review",
                    review.id,
                    reference["reviewer_id"],
                    None,
                    objects,
                    reference["candidate_key"],
                )
            )
    return observers


async def supersede(session: AsyncSession, resolution: ResolvedAnnotation) -> None:
    """Close the summary eligibility of a superseded version's observations.

    The observations themselves are never rewritten or deleted.

    Args:
        session: Active database session.
        resolution: The version being superseded.
    """
    await session.execute(
        update(PerformanceObservation)
        .where(PerformanceObservation.resolution_id == resolution.id)
        .values(summary_eligible=False)
    )


async def record(
    session: AsyncSession,
    *,
    project_id: str,
    task_type: str,
    resolution: ResolvedAnnotation,
    source_input: ResolutionInput | None,
    parts: list[Part],
    candidates: list[dict[str, Any]],
    duplicates: list[dict[str, str]],
) -> None:
    """Write the raw-to-canonical evidence and observations of one accepted
    resolution, in the same transaction.

    A resolution with no evidence snapshot (single mode) has nothing to
    compare and records nothing.

    Args:
        session: Active database session; the caller commits.
        project_id: Project of the image.
        task_type: Project task type.
        resolution: The accepted version.
        source_input: Evidence snapshot the resolution was built on.
        parts: Candidate contributions with their canonical IDs.
        candidates: Candidate decisions of the accepted proposal, if any.
        duplicates: Same-rater duplicates the proposal reported.
    """
    if source_input is None:
        return
    observers = await _observers(session, source_input)
    if task_type == "classification":
        await _classes(session, project_id, resolution, observers, parts)
    else:
        width, height = (
            await session.execute(
                select(ContentObject.width, ContentObject.height)
                .join(Media, Media.content_object_id == ContentObject.id)
                .join(BatchItem, BatchItem.media_id == Media.id)
                .where(BatchItem.id == resolution.batch_item_id)
            )
        ).one()
        _objects(
            session,
            project_id=project_id,
            task_type=task_type,
            resolution=resolution,
            observers=observers,
            parts=parts,
            candidates=candidates,
            duplicates=duplicates,
            width=width,
            height=height,
        )
    await session.flush()


async def _classes(
    session: AsyncSession,
    project_id: str,
    resolution: ResolvedAnnotation,
    observers: list[Observer],
    parts: list[Part],
) -> None:
    """Record one positive-or-negative agreement per rater and project class."""
    source = parts[0].evaluation_source if parts else AUTOMATED_CONSENSUS
    canonical = {
        entry["class_id"]: canonical_id
        for part in parts
        for entry, canonical_id in zip(part.objects, part.canonical_ids, strict=True)
    }
    all_classes = sorted(
        await session.scalars(
            select(ProjectClass.id).where(ProjectClass.project_id == project_id)
        )
    )
    for observer in observers:
        submitted = {entry["class_id"]: entry["id"] for entry in observer.objects}
        for class_id, object_id in sorted(submitted.items()):
            session.add(
                ResolutionObjectEvidence(
                    resolution_id=resolution.id,
                    batch_item_id=resolution.batch_item_id,
                    evidence_key=f"{observer.kind}:{observer.id}:{object_id}",
                    source_kind=observer.kind,
                    submission_id=observer.id
                    if observer.kind == "submission"
                    else None,
                    review_submission_id=(
                        observer.id if observer.kind == "review" else None
                    ),
                    annotator_id=observer.annotator_id,
                    source_object_id=object_id,
                    candidate_key="image",
                    canonical_object_id=canonical.get(class_id),
                    outcome=("retained" if class_id in canonical else "false_positive"),
                )
            )
        for class_id in all_classes:
            claimed, accepted = class_id in submitted, class_id in canonical
            session.add(
                PerformanceObservation(
                    project_id=project_id,
                    annotator_id=observer.annotator_id,
                    assignment_id=observer.assignment_id,
                    submission_id=observer.id
                    if observer.kind == "submission"
                    else None,
                    review_submission_id=(
                        observer.id if observer.kind == "review" else None
                    ),
                    batch_item_id=resolution.batch_item_id,
                    resolution_id=resolution.id,
                    resolution_version=resolution.version,
                    observation_key=f"{observer.kind}:{observer.id}:{class_id}",
                    evaluation_source=source,
                    task_type="classification",
                    submitted_class_id=class_id if claimed else None,
                    canonical_class_id=class_id if accepted else None,
                    outcome={
                        (True, True): "retained",
                        (True, False): "false_positive",
                        (False, True): "missed_object",
                        (False, False): "not_applicable",
                    }[(claimed, accepted)],
                    metric_name="class_agreement",
                    metric_value=1.0 if claimed == accepted else 0.0,
                    weighting_eligible=source in WEIGHTING_SOURCES,
                    summary_eligible=True,
                )
            )


def _metrics(task_type: str, width: int, height: int) -> Any:
    """Return the geometry agreement measure of a task.

    Geometry libraries are imported here, so only accepting a detection or
    segmentation resolution loads them.
    """
    if task_type == "detection":
        from dada_api.consensus import boxes

        return lambda raw, canonical: {
            "box_iou": boxes.iou(raw["coordinates"], canonical["coordinates"])
        }

    from dada_api.consensus import masks

    def measure(raw: dict[str, Any], canonical: dict[str, Any]) -> dict[str, float]:
        """Return mask IoU and Dice against the canonical instance."""
        first = masks.rasterize(raw["coordinates"], width, height)
        second = masks.rasterize(canonical["coordinates"], width, height)
        return {
            "mask_iou": masks.mask_iou(first, second),
            "mask_dice": masks.mask_dice(first, second),
        }

    return measure


def _match(
    raws: list[dict[str, Any]],
    canonicals: list[tuple[dict[str, Any], str]],
    measure: Any,
) -> dict[int, int]:
    """Match one rater's objects to an image-wide decision one-to-one by their
    primary overlap, keeping pairs at or above one half."""
    from scipy.optimize import linear_sum_assignment

    if not raws or not canonicals:
        return {}
    scores = [
        [
            next(iter(measure(raw["geometry"], canonical["geometry"]).values()))
            for canonical, _ in canonicals
        ]
        for raw in raws
    ]
    rows, columns = linear_sum_assignment(scores, maximize=True)
    return {
        int(row): int(column)
        for row, column in zip(rows, columns, strict=True)
        if at_least(scores[row][column], 0.5)
    }


def _objects(
    session: AsyncSession,
    *,
    project_id: str,
    task_type: str,
    resolution: ResolvedAnnotation,
    observers: list[Observer],
    parts: list[Part],
    candidates: list[dict[str, Any]],
    duplicates: list[dict[str, str]],
    width: int,
    height: int,
) -> None:
    """Map every raw box or mask to the canonical document (P6-07).

    A source object of an accepted candidate is ``retained`` or
    ``class_changed`` with its overlap; one of a rejected candidate is a
    ``false_positive``; a same-rater duplicate is a ``duplicate``; and an
    annotator or reviewer who drew nothing for an accepted object records a
    ``missed_object``. Unmatched cases never get an invented zero overlap.
    """
    measure = _metrics(task_type, width, height)
    by_source = {observer.id: observer for observer in observers}
    by_key = {candidate["key"]: candidate for candidate in candidates}

    def note(
        observer: Observer,
        object_id: str | None,
        key: str,
        part: Part,
        outcome: str,
        canonical_id: str | None,
        raw: dict[str, Any] | None,
        canonical: dict[str, Any] | None,
    ) -> None:
        """Stage the evidence row and the observations of one source object."""
        reference = object_id or f"missed-{canonical_id}"
        if object_id is not None:
            session.add(
                ResolutionObjectEvidence(
                    resolution_id=resolution.id,
                    batch_item_id=resolution.batch_item_id,
                    evidence_key=f"{observer.kind}:{observer.id}:{object_id}",
                    source_kind=observer.kind,
                    submission_id=observer.id
                    if observer.kind == "submission"
                    else None,
                    review_submission_id=(
                        observer.id if observer.kind == "review" else None
                    ),
                    annotator_id=observer.annotator_id,
                    source_object_id=object_id,
                    candidate_key=key,
                    canonical_object_id=canonical_id,
                    outcome=outcome,
                )
            )
        values = (
            measure(raw["geometry"], canonical["geometry"])
            if raw is not None and canonical is not None
            else {"existence": None}
        )
        for name, value in values.items():
            session.add(
                PerformanceObservation(
                    project_id=project_id,
                    annotator_id=observer.annotator_id,
                    assignment_id=observer.assignment_id,
                    submission_id=(
                        observer.id if observer.kind == "submission" else None
                    ),
                    review_submission_id=(
                        observer.id if observer.kind == "review" else None
                    ),
                    batch_item_id=resolution.batch_item_id,
                    resolution_id=resolution.id,
                    resolution_version=resolution.version,
                    observation_key=f"{observer.kind}:{observer.id}:{reference}:{name}",
                    evaluation_source=part.evaluation_source,
                    task_type=task_type,
                    submitted_class_id=raw["class_id"] if raw is not None else None,
                    canonical_class_id=(
                        canonical["class_id"] if canonical is not None else None
                    ),
                    outcome=outcome,
                    metric_name=name,
                    metric_value=float(quantize(value)) if value is not None else None,
                    weighting_eligible=part.evaluation_source in WEIGHTING_SOURCES,
                    summary_eligible=True,
                )
            )

    duplicate_refs = {(entry["source_id"], entry["object_id"]) for entry in duplicates}
    covered: set[tuple[str, str]] = set()
    image_part = next((part for part in parts if part.key == "image"), None)
    for part in parts:
        if part.key == "image":
            continue
        canonicals = list(zip(part.objects, part.canonical_ids, strict=True))
        target, target_id = canonicals[0] if canonicals else (None, None)
        candidate = by_key.get(part.key, {"members": []})
        refs = [
            (member["source_id"], member["object_id"])
            for member in candidate["members"]
        ]
        reviewers = [
            observer
            for observer in observers
            if observer.kind == "review" and observer.candidate_key == part.key
        ]
        refs += [
            (observer.id, observer.objects[0]["id"])
            for observer in reviewers
            if observer.objects
        ]
        for source_id, object_id in refs:
            observer = by_source[source_id]
            raw = next(entry for entry in observer.objects if entry["id"] == object_id)
            covered.add((source_id, object_id))
            if target is None:
                note(
                    observer,
                    object_id,
                    part.key,
                    part,
                    "false_positive",
                    None,
                    raw,
                    None,
                )
            else:
                outcome = (
                    "retained"
                    if raw["class_id"] == target["class_id"]
                    else "class_changed"
                )
                note(
                    observer, object_id, part.key, part, outcome, target_id, raw, target
                )
        if target is None:
            continue
        drew = {source_id for source_id, _ in refs}
        for observer in observers:
            if observer.id in drew:
                continue
            if observer.kind == "submission" or observer in reviewers:
                note(
                    observer,
                    None,
                    part.key,
                    part,
                    "missed_object",
                    target_id,
                    None,
                    target,
                )

    for observer in observers:
        for raw in observer.objects:
            reference = (observer.id, raw["id"])
            if reference in duplicate_refs and reference not in covered:
                covered.add(reference)
                part = image_part or (parts[0] if parts else None)
                if part is not None:
                    note(
                        observer, raw["id"], "image", part, "duplicate", None, raw, None
                    )

    if image_part is None:
        return
    canonicals = list(zip(image_part.objects, image_part.canonical_ids, strict=True))
    for observer in observers:
        if observer.kind != "submission":
            continue
        raws = [
            entry
            for entry in observer.objects
            if (observer.id, entry["id"]) not in covered
        ]
        matched = _match(raws, canonicals, measure)
        for index, raw in enumerate(raws):
            if index in matched:
                canonical, canonical_id = canonicals[matched[index]]
                outcome = (
                    "retained"
                    if raw["class_id"] == canonical["class_id"]
                    else "class_changed"
                )
                note(
                    observer,
                    raw["id"],
                    "image",
                    image_part,
                    outcome,
                    canonical_id,
                    raw,
                    canonical,
                )
            else:
                note(
                    observer,
                    raw["id"],
                    "image",
                    image_part,
                    "false_positive",
                    None,
                    raw,
                    None,
                )
        hit = set(matched.values())
        for position, (canonical, canonical_id) in enumerate(canonicals):
            if position not in hit:
                note(
                    observer,
                    None,
                    "image",
                    image_part,
                    "missed_object",
                    canonical_id,
                    None,
                    canonical,
                )


async def current_observations(
    session: AsyncSession, project_id: str
) -> list[PerformanceObservation]:
    """Return a project's observations that still count for summaries.

    Args:
        session: Active database session.
        project_id: Project identifier.

    Returns:
        Observations of current, non-superseded resolutions.
    """
    return list(
        await session.scalars(
            select(PerformanceObservation).where(
                PerformanceObservation.project_id == project_id,
                PerformanceObservation.summary_eligible.is_(True),
            )
        )
    )


def summarize(
    observations: list[PerformanceObservation],
) -> list[dict[str, Any]]:
    """Aggregate observations per annotator and evaluation source, suppressing
    small samples (P6-07).

    A named row with fewer than 30 decisions shows no numbers at all, and any
    outcome, metric, or class cell with fewer than 5 observations is hidden.
    Summaries are computed on read from the immutable observations, so they
    are always current and never need rebuilding (D24).

    Args:
        observations: Current, summary-eligible observations of one project.

    Returns:
        One summary per (annotator, evaluation source, task), sorted.
    """
    groups: dict[tuple[str, str, str], list[PerformanceObservation]] = {}
    for observation in observations:
        key = (
            observation.annotator_id,
            observation.evaluation_source,
            observation.task_type,
        )
        groups.setdefault(key, []).append(observation)

    def cell(count: int, value: Any) -> Any:
        """Hide a value backed by too few observations."""
        return value if count >= MINIMUM_CELL else None

    summaries = []
    for (annotator_id, source, task_type), rows in sorted(groups.items()):
        decisions = [row for row in rows if row.metric_name not in SECONDARY_METRICS]
        suppressed = len(decisions) < MINIMUM_DECISIONS
        outcomes: dict[str, int] = {}
        metrics: dict[str, list[float]] = {}
        classes: dict[str, list[float]] = {}
        for row in rows:
            outcomes[row.outcome] = outcomes.get(row.outcome, 0) + 1
            if row.metric_value is not None:
                metrics.setdefault(row.metric_name, []).append(row.metric_value)
            class_id = row.canonical_class_id or row.submitted_class_id
            if class_id is not None and row.metric_value is not None:
                classes.setdefault(class_id, []).append(row.metric_value)
        summaries.append(
            {
                "annotator_id": annotator_id,
                "evaluation_source": source,
                "task_type": task_type,
                "decisions": len(decisions),
                "suppressed": suppressed,
                "outcomes": None
                if suppressed
                else {
                    name: cell(count, count) for name, count in sorted(outcomes.items())
                },
                "metrics": None
                if suppressed
                else {
                    name: cell(len(values), round(sum(values) / len(values), 6))
                    for name, values in sorted(metrics.items())
                },
                "classes": None
                if suppressed
                else {
                    class_id: cell(len(values), round(sum(values) / len(values), 6))
                    for class_id, values in sorted(classes.items())
                },
            }
        )
    return summaries
