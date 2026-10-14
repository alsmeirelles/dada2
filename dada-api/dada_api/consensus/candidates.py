"""Two-stage candidate resolution shared by detection and segmentation."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from dada_api.consensus import class_strategies, matching
from dada_api.consensus.class_strategies import NO_OBJECT, Vote
from dada_api.consensus.protocol import (
    Candidate,
    PipelineError,
    PipelineOutput,
    ResolverInput,
)

REGION_PADDING = 0.1


@dataclass(frozen=True)
class Shape:
    """One raw object, or one reviewer's object, entering a run.

    Attributes:
        source_id: Submission or review submission identifier.
        object_id: Object identifier inside its source document.
        rater: Annotator identifier.
        index: Annotator index inside the run.
        class_id: Chosen class, None for a reviewer's ``no_object``.
        value: Parsed geometry, None for a ``no_object`` review.
    """

    source_id: str
    object_id: str
    rater: str
    index: int
    class_id: str | None
    value: Any


@dataclass(frozen=True)
class Geometry:
    """The task-specific geometry operations of a two-stage pipeline.

    Attributes:
        parse: Turns a stored geometry into a comparable value.
        overlap: Symmetric overlap between two values.
        may_overlap: Cheap prefilter, or None.
        bounds: Bounding box ``[x, y, width, height]`` of one value.
        refine: Fuses supporting values into a canonical geometry; returns
            the geometry (None when unusable), extra reasons, and metrics.
        threshold: Inclusive matching threshold.
    """

    parse: Callable[[dict[str, Any]], Any]
    overlap: Callable[[Any, Any], float]
    may_overlap: Callable[[Any, Any], bool] | None
    bounds: Callable[[Any], list[float]]
    refine: Callable[
        [list[Any]], tuple[dict[str, Any] | None, list[str], dict[str, Any]]
    ]
    threshold: float


@dataclass(frozen=True)
class Proto:
    """A candidate before its decision: identity, members, and reviews."""

    key: str
    ordinal: int
    members: list[Shape]
    reviews: list[Shape]
    region: list[float] | None
    ambiguous: bool


def _key(members: list[Shape]) -> str:
    """Return the deterministic identity of a candidate group."""
    refs = ",".join(sorted(f"{shape.source_id}:{shape.object_id}" for shape in members))
    return "c-" + hashlib.sha256(refs.encode()).hexdigest()[:32]


def _region(
    geometry: Geometry, members: list[Shape], width: int, height: int
) -> list[float]:
    """Return the padded, clipped box a reviewer is shown for a candidate."""
    corners = [geometry.bounds(shape.value) for shape in members]
    x1 = min(box[0] for box in corners)
    y1 = min(box[1] for box in corners)
    x2 = max(box[0] + box[2] for box in corners)
    y2 = max(box[1] + box[3] for box in corners)
    pad_x, pad_y = (x2 - x1) * REGION_PADDING, (y2 - y1) * REGION_PADDING
    x1, y1 = max(0.0, x1 - pad_x), max(0.0, y1 - pad_y)
    x2, y2 = min(float(width), x2 + pad_x), min(float(height), y2 + pad_y)
    return [float(x1), float(y1), float(x2 - x1), float(y2 - y1)]


def _raters(
    resolver_input: ResolverInput, geometry: Geometry
) -> tuple[list[str], list[list[Shape]]]:
    """Return the initial annotators in run order with their parsed objects."""
    submissions = sorted(
        (source for source in resolver_input.sources if source.kind == "submission"),
        key=lambda source: source.annotator_index,
    )
    return [source.annotator_id for source in submissions], [
        [
            Shape(
                source.id,
                entry["id"],
                source.annotator_id,
                source.annotator_index,
                entry["class_id"],
                geometry.parse(entry["geometry"]),
            )
            for entry in source.objects
        ]
        for source in submissions
    ]


def _reviews(
    resolver_input: ResolverInput, geometry: Geometry
) -> dict[str, list[Shape]]:
    """Return each candidate's reviewer evidence as shapes."""
    reviews: dict[str, list[Shape]] = {}
    for source in resolver_input.sources:
        if source.kind != "review":
            continue
        evidence = source.evidence or {}
        is_object = evidence.get("decision") == "object"
        reviews.setdefault(source.candidate_key, []).append(
            Shape(
                source.id,
                source.candidate_key,
                source.annotator_id,
                source.annotator_index,
                evidence["class_id"] if is_object else None,
                geometry.parse(evidence["geometry"]) if is_object else None,
            )
        )
    return reviews


def _protos(
    resolver_input: ResolverInput,
    geometry: Geometry,
    shapes: list[list[Shape]],
) -> tuple[list[Proto], list[dict[str, str]]]:
    """Group raw objects into candidates, or reuse the frozen first round."""
    if resolver_input.candidates is not None:
        index = {
            (shape.source_id, shape.object_id): shape
            for rater in shapes
            for shape in rater
        }
        reviews = _reviews(resolver_input, geometry)
        return [
            Proto(
                frozen["key"],
                frozen["ordinal"],
                [
                    index[(member["source_id"], member["object_id"])]
                    for member in frozen["members"]
                ],
                reviews.get(frozen["key"], []),
                frozen["region"],
                False,
            )
            for frozen in resolver_input.candidates
            if frozen["scope"] == "candidate"
        ], []

    grouping = matching.group(
        [[shape.value for shape in rater] for rater in shapes],
        geometry.overlap,
        geometry.threshold,
        geometry.may_overlap,
    )
    groups = [
        (
            [shapes[member.rater][member.index] for member in found.members],
            found.ambiguous,
        )
        for found in grouping.groups
    ]
    keyed = sorted(
        ((_key(members), members, flag) for members, flag in groups),
        key=lambda entry: entry[0],
    )
    protos = [
        Proto(
            key,
            ordinal,
            members,
            [],
            _region(geometry, members, resolver_input.width, resolver_input.height),
            ambiguous,
        )
        for ordinal, (key, members, ambiguous) in enumerate(keyed)
    ]
    duplicates = [
        {
            "source_id": shapes[member.rater][member.index].source_id,
            "object_id": shapes[member.rater][member.index].object_id,
        }
        for member in grouping.duplicates
    ]
    return protos, duplicates


def _decide(
    resolver_input: ResolverInput,
    geometry: Geometry,
    proto: Proto,
    raters: list[str],
) -> tuple[Candidate, dict[str, str]]:
    """Decide one candidate's existence and class, then refine its geometry."""
    parameters = resolver_input.configuration["parameters"]
    thresholds = resolver_input.configuration["review_thresholds"]
    minimum_support = Fraction(
        thresholds["minimum_support"]["numerator"],
        thresholds["minimum_support"]["denominator"],
    )
    member_class = {shape.rater: shape.class_id for shape in proto.members}
    votes = [
        Vote(rater=rater, outcome=member_class.get(rater, NO_OBJECT))
        for rater in raters
    ] + [
        Vote(rater=review.rater, outcome=review.class_id or NO_OBJECT)
        for review in proto.reviews
    ]
    decision = class_strategies.decide(
        parameters["class_strategy"],
        minimum_support,
        votes,
        [*resolver_input.class_ids, NO_OBJECT],
        (resolver_input.calibration or {}).get("candidates"),
    )
    reasons = list(decision.reasons)
    if proto.ambiguous:
        reasons.append("ambiguous_match")
    metrics: dict[str, Any] = {"outcome": decision.outcome, **decision.metrics}
    objects: list[dict[str, Any]] = []
    if decision.outcome not in (None, NO_OBJECT):
        supporting = [shape.value for shape in proto.members] + [
            review.value for review in proto.reviews if review.value is not None
        ]
        try:
            refined, geometry_reasons, geometry_metrics = geometry.refine(supporting)
        except PipelineError:
            refined, geometry_reasons, geometry_metrics = None, ["topology_invalid"], {}
        reasons.extend(geometry_reasons)
        metrics.update(geometry_metrics)
        if refined is not None:
            objects = [
                {
                    "id": proto.key,
                    "class_id": decision.outcome,
                    "geometry": refined,
                    "attributes": {},
                }
            ]
    candidate = Candidate(
        key=proto.key,
        ordinal=proto.ordinal,
        scope="candidate",
        passed=not reasons,
        reasons=reasons,
        objects=objects,
        region=proto.region,
        members=[
            {
                "source_id": shape.source_id,
                "object_id": shape.object_id,
                "annotator_index": shape.index,
                "class_id": shape.class_id,
            }
            for shape in proto.members
        ],
        metrics=metrics,
    )
    return candidate, {vote.rater: vote.outcome for vote in votes}


def resolve(
    resolver_input: ResolverInput,
    geometry: Geometry,
    versions: dict[str, str],
) -> PipelineOutput:
    """Resolve every candidate of one image in two stages.

    Stage 1 matches objects without their class and decides each candidate's
    existence and class from every initial annotator's vote, where an
    annotator who drew nothing there votes ``no_object``. Stage 2 refines the
    geometry of accepted objects only. On a second round the first round's
    candidates are reused as frozen, and each reviewer adds one vote and,
    for an object, one supporting geometry.

    Args:
        resolver_input: Verified input of one run.
        geometry: Task-specific geometry operations.
        versions: Implementation versions to record.

    Returns:
        One decision per candidate. An image where every annotator drew
        nothing yields one passing, empty image case.
    """
    raters, shapes = _raters(resolver_input, geometry)
    protos, duplicates = _protos(resolver_input, geometry, shapes)
    if not protos:
        return PipelineOutput(
            candidates=[Candidate(key="image", ordinal=0, scope="image", passed=True)],
            diagnostics={"stage": resolver_input.task_type, "candidates": 0},
            versions=versions,
        )
    candidates, matrix = [], {}
    for proto in protos:
        candidate, votes = _decide(resolver_input, geometry, proto, raters)
        candidates.append(candidate)
        matrix[proto.key] = votes
    return PipelineOutput(
        candidates=candidates,
        diagnostics={
            "stage": resolver_input.task_type,
            "candidates": len(candidates),
            "duplicates": duplicates,
            "observation_matrix": matrix,
        },
        versions=versions,
    )
