"""Eligibility gates and frozen parameters of the conditional class strategies."""

import json
from fractions import Fraction

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from dada_api.consensus import calibration
from dada_api.consensus.calibration import Reference
from dada_api.consensus.class_strategies import Vote, decide
from dada_api.consensus.protocol import PipelineError

OUTCOMES = ["cat", "dog", "bird"]
POOL = ["caio", "ana", "bia"]
ANA_SLIPS = {7, 26, 45}
BIA_SLIPS = {4, 11, 18, 33, 50}
TWO_THIRDS = Fraction(2, 3)


def references(
    rater: str, per_outcome: dict[str, int], correct: int
) -> list[Reference]:
    """Build a rater's references, the first ``correct`` of them agreeing."""
    built = []
    for outcome, count in per_outcome.items():
        built += [Reference(rater, outcome, outcome) for _ in range(count)]
    wrong = {"cat": "dog", "dog": "cat", "bird": "cat"}
    return [
        reference
        if index < correct
        else Reference(rater, wrong[reference.reference], reference.reference)
        for index, reference in enumerate(built)
    ]


def corpus(size: int = 60) -> list[list[Vote]]:
    """Synthetic items where caio always reports a cat as a dog."""
    items = []
    for index in range(size):
        truth = OUTCOMES[index % 3]
        slip = OUTCOMES[(index + 1) % 3]
        items.append(
            [
                Vote("caio", "dog" if truth == "cat" else truth),
                Vote("bia", slip if index in BIA_SLIPS else truth),
                Vote("ana", slip if index in ANA_SLIPS else truth),
            ]
        )
    return items


def votes(**outcomes: str) -> list[Vote]:
    return [Vote(rater, outcome) for rater, outcome in outcomes.items()]


def test_reliability_weights_are_smoothed_normalized_accuracies() -> None:
    evidence = (
        references("ana", {"cat": 20, "dog": 20}, 36)
        + references("bia", {"cat": 20, "dog": 20}, 30)
        + references("caio", {"cat": 20, "dog": 20}, 20)
        + references("outsider", {"cat": 1}, 0)
    )

    result = calibration.reliability_weights(evidence, POOL, ["cat", "dog"])

    assert result.eligible
    assert result.missing == ()
    assert result.parameters == {
        "weights": {
            "ana": round(114 / 92, 6),
            "bia": round(96 / 92, 6),
            "caio": round(66 / 92, 6),
        }
    }
    assert set(result.report["raters"]) == {"ana", "bia", "caio"}
    assert result.report["raters"]["bia"] == {
        "decisions": 40,
        "agreements": 30,
        "references_per_outcome": {"cat": 20, "dog": 20},
    }
    assert (
        calibration.reliability_weights(evidence[::-1], POOL, ["cat", "dog"]) == result
    )


def test_reliability_weights_are_clipped_without_renormalizing() -> None:
    evidence = references("ana", {"cat": 50, "dog": 50}, 100)
    for rater in ("bia", "caio", "davi"):
        evidence += references(rater, {"cat": 50, "dog": 50}, 0)

    result = calibration.reliability_weights(
        evidence, ["ana", "bia", "caio", "davi"], ["cat", "dog"]
    )

    assert result.parameters == {
        "weights": {"ana": 2.0, "bia": 0.5, "caio": 0.5, "davi": 0.5}
    }


def test_eligible_weights_feed_the_reliability_strategy() -> None:
    evidence = (
        references("ana", {"cat": 20, "dog": 20}, 36)
        + references("bia", {"cat": 20, "dog": 20}, 30)
        + references("caio", {"cat": 20, "dog": 20}, 20)
    )
    snapshot = calibration.reliability_weights(
        evidence, POOL, ["cat", "dog"]
    ).parameters

    decision = decide(
        {"strategy": "reliability_weighted_vote"},
        TWO_THIRDS,
        votes(ana="cat", bia="cat", caio="dog"),
        ["cat", "dog"],
        snapshot,
    )

    assert (decision.outcome, decision.passed) == ("cat", True)
    assert decision.metrics["weighted_support"] == round((114 + 96) / 276, 6)


def test_reliability_names_every_missing_decision_and_outcome() -> None:
    evidence = references("ana", {"cat": 28, "dog": 2}, 30) + references(
        "bia", {"cat": 10, "dog": 2}, 12
    )

    result = calibration.reliability_weights(evidence, POOL, ["cat", "dog"])

    assert not result.eligible
    assert result.parameters == {}
    assert result.missing == (
        {
            "requirement": "observations_per_outcome",
            "rater": "ana",
            "outcome": "dog",
            "required": 5,
            "found": 2,
        },
        {
            "requirement": "decisions_per_rater",
            "rater": "bia",
            "required": 30,
            "found": 12,
        },
        {
            "requirement": "observations_per_outcome",
            "rater": "bia",
            "outcome": "dog",
            "required": 5,
            "found": 2,
        },
        {
            "requirement": "decisions_per_rater",
            "rater": "caio",
            "required": 30,
            "found": 0,
        },
        {
            "requirement": "observations_per_outcome",
            "rater": "caio",
            "outcome": "cat",
            "required": 5,
            "found": 0,
        },
        {
            "requirement": "observations_per_outcome",
            "rater": "caio",
            "outcome": "dog",
            "required": 5,
            "found": 0,
        },
    )
    json.dumps(result.report)


def test_dawid_skene_learns_a_systematic_confusion_deterministically() -> None:
    result = calibration.dawid_skene(corpus(), POOL, OUTCOMES)

    assert result.eligible
    assert result.missing == ()
    assert result.report == {
        "items": 60,
        "calibration_items": 60,
        "observations_per_rater": {"ana": 60, "bia": 60, "caio": 60},
        "observations_per_outcome": {"cat": 40, "dog": 81, "bird": 59},
        "iterations": 20,
        "converged": True,
        "log_likelihood": -105.948529,
    }
    assert result.parameters["iterations"] == 20
    assert result.parameters["priors"] == {
        "cat": 0.313302,
        "dog": 0.353626,
        "bird": 0.333072,
    }
    assert result.parameters["confusion"]["caio"]["cat"] == {
        "cat": 0.046002,
        "dog": 0.90473,
        "bird": 0.049267,
    }
    shuffled = [item[::-1] for item in corpus()]
    assert calibration.dawid_skene(shuffled, POOL[::-1], OUTCOMES) == result
    json.dumps(result.parameters)


def test_a_learned_confusion_sends_a_plain_majority_to_review() -> None:
    snapshot = calibration.dawid_skene(corpus(), POOL, OUTCOMES).parameters
    conflicting = votes(ana="cat", bia="dog", caio="dog")
    agreeing = votes(ana="cat", bia="cat", caio="dog")
    categorical = {"strategy": "categorical_vote", "decision_rule": "supermajority"}

    plain = decide(categorical, TWO_THIRDS, conflicting, OUTCOMES)
    latent = decide(
        {"strategy": "dawid_skene"}, TWO_THIRDS, conflicting, OUTCOMES, snapshot
    )
    confirmed = decide(
        {"strategy": "dawid_skene"}, TWO_THIRDS, agreeing, OUTCOMES, snapshot
    )

    assert (plain.outcome, plain.passed) == ("dog", True)
    assert (latent.outcome, latent.passed) == ("cat", False)
    assert latent.reasons == ("support_below_threshold", "posterior_below_threshold")
    assert latent.metrics["posterior"] == 0.515293
    assert (confirmed.outcome, confirmed.passed) == ("cat", True)
    assert confirmed.metrics["posterior"] == 0.990012


def test_dawid_skene_needs_enough_calibration_items() -> None:
    result = calibration.dawid_skene(corpus(30), POOL, OUTCOMES)

    assert not result.eligible
    assert result.parameters == {}
    assert result.missing == (
        {"requirement": "calibration_items", "required": 50, "found": 30},
    )
    assert "iterations" not in result.report


def test_dawid_skene_ignores_items_with_fewer_than_three_pool_raters() -> None:
    items = [
        [
            vote if vote.rater != "ana" else Vote("outsider", vote.outcome)
            for vote in item
        ]
        for item in corpus()
    ]

    result = calibration.dawid_skene(items, POOL, OUTCOMES)

    assert result.report["items"] == 60
    assert result.report["calibration_items"] == 0
    assert result.missing[0] == {
        "requirement": "calibration_items",
        "required": 50,
        "found": 0,
    }
    assert {
        "requirement": "observations_per_rater",
        "rater": "ana",
        "required": 20,
        "found": 0,
    } in result.missing


def test_dawid_skene_needs_every_outcome_observed() -> None:
    items = [
        [
            Vote(vote.rater, "cat" if vote.outcome == "bird" else vote.outcome)
            for vote in item
        ]
        for item in corpus()
    ]
    items[0] = [Vote("ana", "bird"), Vote("bia", "bird"), Vote("caio", "bird")]

    result = calibration.dawid_skene(items, POOL, OUTCOMES)

    assert result.missing == (
        {
            "requirement": "observations_per_outcome",
            "outcome": "bird",
            "required": 5,
            "found": 3,
        },
    )


@pytest.mark.parametrize("limit", [1, 2])
def test_dawid_skene_without_convergence_is_ineligible(limit: int) -> None:
    result = calibration.dawid_skene(corpus(), POOL, OUTCOMES, max_iterations=limit)

    assert not result.eligible
    assert result.parameters == {}
    assert result.missing == ({"requirement": "convergence", "iterations": limit},)
    assert result.report["converged"] is False
    json.dumps(result.report)


@pytest.mark.parametrize(
    "stray",
    [Reference("ana", "horse", "cat"), Reference("ana", "cat", "horse")],
    ids=["submitted", "reference"],
)
def test_reliability_evidence_outside_the_outcome_space_is_invalid(
    stray: Reference,
) -> None:
    evidence = references("ana", {"cat": 20, "dog": 20}, 36) + [stray]

    with pytest.raises(PipelineError) as error:
        calibration.reliability_weights(evidence, POOL, ["cat", "dog"])

    assert error.value.code == "invalid_input"


@pytest.mark.parametrize(
    "stray",
    [
        [Vote("ana", "horse"), Vote("bia", "cat"), Vote("caio", "dog")],
        [
            Vote("ana", "cat"),
            Vote("ana", "dog"),
            Vote("bia", "cat"),
            Vote("caio", "dog"),
        ],
    ],
    ids=["unknown_outcome", "duplicate_rater"],
)
def test_dawid_skene_items_that_cannot_be_votes_are_invalid(stray: list[Vote]) -> None:
    with pytest.raises(PipelineError) as error:
        calibration.dawid_skene([*corpus(), stray], POOL, OUTCOMES)

    assert error.value.code == "invalid_input"
