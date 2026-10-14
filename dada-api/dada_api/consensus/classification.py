"""The ``statistical_class_consensus`` pipeline for multi-label image
classification."""

from fractions import Fraction

from dada_api.consensus import catalog, class_strategies
from dada_api.consensus.class_strategies import NEGATIVE, POSITIVE, Vote
from dada_api.consensus.protocol import (
    Candidate,
    PipelineError,
    PipelineOutput,
    ResolverInput,
)

IMAGE_KEY = "image"


def _class_sets(resolver_input: ResolverInput) -> dict[str, set[str]]:
    """Return the classes each rater marked, keyed by rater.

    Annotators contribute their submitted labels and reviewers the classes of
    their image review. A class a rater did not mark is an explicit negative
    observation, so every rater votes on every class.

    Raises:
        PipelineError: ``invalid_input`` when a review carries no class list.
    """
    marked: dict[str, set[str]] = {}
    for source in resolver_input.sources:
        if source.kind == "submission":
            marked[source.annotator_id] = {
                entry["class_id"] for entry in source.objects
            }
        else:
            class_ids = (source.evidence or {}).get("class_ids")
            if not isinstance(class_ids, list):
                raise PipelineError("invalid_input", "an image review lists no classes")
            marked[source.annotator_id] = set(class_ids)
    return marked


def resolve(resolver_input: ResolverInput) -> PipelineOutput:
    """Decide every class of one image with the configured strategy.

    The image passes only when every class passes its gates. Its objects are
    the classes decided positive; an image left with no class at all goes to
    review, because a classification document needs at least one class.

    Args:
        resolver_input: Verified input of one run.

    Returns:
        One image-level candidate with per-class diagnostics and the exact
        observation matrix used.

    Raises:
        PipelineError: For invalid input or an unavailable strategy.
    """
    parameters = resolver_input.configuration["parameters"]
    thresholds = resolver_input.configuration["review_thresholds"]
    strategy = parameters["class_strategy"]
    minimum_support = Fraction(
        thresholds["minimum_support"]["numerator"],
        thresholds["minimum_support"]["denominator"],
    )
    marked = _class_sets(resolver_input)
    calibration = resolver_input.calibration or {}

    decisions = {}
    matrix = {}
    for class_id in resolver_input.class_ids:
        votes = [
            Vote(rater=rater, outcome=POSITIVE if class_id in classes else NEGATIVE)
            for rater, classes in sorted(marked.items())
        ]
        matrix[class_id] = {vote.rater: vote.outcome for vote in votes}
        decisions[class_id] = class_strategies.decide(
            strategy,
            minimum_support,
            votes,
            class_strategies.BINARY_OUTCOMES,
            calibration.get(class_id),
        )

    positive = [
        class_id
        for class_id in resolver_input.class_ids
        if decisions[class_id].outcome == POSITIVE
    ]
    reasons: list[str] = []
    for class_id in resolver_input.class_ids:
        for reason in decisions[class_id].reasons:
            if reason not in reasons:
                reasons.append(reason)
    if not positive and class_strategies.SUPPORT_BELOW_THRESHOLD not in reasons:
        reasons.append(class_strategies.SUPPORT_BELOW_THRESHOLD)

    return PipelineOutput(
        candidates=[
            Candidate(
                key=IMAGE_KEY,
                ordinal=0,
                scope="image",
                passed=not reasons,
                reasons=reasons,
                objects=[
                    {
                        "id": f"label-{index}",
                        "class_id": class_id,
                        "geometry": None,
                        "attributes": {},
                    }
                    for index, class_id in enumerate(positive, start=1)
                ],
                metrics={
                    "classes": {
                        class_id: {
                            "outcome": decision.outcome,
                            "passed": decision.passed,
                            "reasons": list(decision.reasons),
                            **decision.metrics,
                        }
                        for class_id, decision in decisions.items()
                    }
                },
            )
        ],
        diagnostics={"stage": "classification", "observation_matrix": matrix},
        versions={
            catalog.PIPELINES["classification"].id: catalog.VERSION,
            strategy["strategy"]: catalog.VERSION,
        },
    )
