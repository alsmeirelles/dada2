"""Golden fixtures, replay, and input rules of the native class strategies."""

import json
import math
from fractions import Fraction
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from dada_api.consensus.class_strategies import Decision, Vote, decide
from dada_api.consensus.protocol import PipelineError

FIXTURES = sorted(
    (Path(__file__).parent / "fixtures" / "consensus" / "class_strategies").glob(
        "*.json"
    )
)
TWO_THIRDS = Fraction(2, 3)
CANDIDATE = ["cat", "dog", "no_object"]
BINARY = ["positive", "negative"]
SUPERMAJORITY = {"strategy": "categorical_vote", "decision_rule": "supermajority"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run(case: dict, votes: list[Vote] | None = None) -> Decision:
    support = case["minimum_support"]
    return decide(
        case["strategy"],
        Fraction(support["numerator"], support["denominator"]),
        votes if votes is not None else [Vote(**vote) for vote in case["votes"]],
        case["outcomes"],
        case.get("calibration"),
    )


def as_json(decision: Decision) -> dict:
    return {
        "outcome": decision.outcome,
        "passed": decision.passed,
        "reasons": list(decision.reasons),
        "metrics": decision.metrics,
    }


def votes(**outcomes: str) -> list[Vote]:
    return [Vote(rater, outcome) for rater, outcome in outcomes.items()]


def test_the_golden_catalog_covers_every_strategy() -> None:
    strategies = {load(path)["strategy"]["strategy"] for path in FIXTURES}

    assert strategies == {
        "categorical_vote",
        "multilabel_binary_vote",
        "dirichlet_vote",
        "reliability_weighted_vote",
        "dawid_skene",
    }


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_every_golden_case_replays_to_its_recorded_decision(path: Path) -> None:
    case = load(path)

    first, second = as_json(run(case)), as_json(run(case))

    assert first == case["expected"]
    assert second == case["expected"]
    assert json.loads(json.dumps(first)) == case["expected"]


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_any_vote_order_reaches_the_same_decision(path: Path) -> None:
    case = load(path)
    received = [Vote(**vote) for vote in case["votes"]]

    for shift in range(len(received)):
        rotated = received[shift:] + received[:shift]
        assert as_json(run(case, rotated)) == case["expected"]
        assert as_json(run(case, rotated[::-1])) == case["expected"]


def test_a_tie_is_not_broken_by_the_outcome_order() -> None:
    tied = votes(ana="cat", bia="dog")

    for outcomes in (CANDIDATE, CANDIDATE[::-1]):
        decision = decide(SUPERMAJORITY, TWO_THIRDS, tied, outcomes)
        assert (decision.outcome, decision.passed) == (None, False)
        assert decision.reasons == ("class_tie",)


def test_the_decision_rules_differ_only_below_the_policy_floor() -> None:
    weak = votes(ana="cat", bia="cat", caio="dog", davi="no_object")
    below_floor = Fraction(1, 2)

    def rule(name: str, support: Fraction) -> Decision:
        strategy = {"strategy": "categorical_vote", "decision_rule": name}
        return decide(strategy, support, weak, CANDIDATE)

    assert rule("plurality", below_floor).passed
    assert rule("supermajority", below_floor).passed
    assert rule("strict_majority", below_floor).reasons == ("support_below_threshold",)
    for name in ("plurality", "strict_majority", "supermajority"):
        assert rule(name, TWO_THIRDS).reasons == ("support_below_threshold",)


def test_the_dirichlet_posterior_matches_exact_closed_forms() -> None:
    uniform = {"strategy": "dirichlet_vote", "alpha": 1.0, "minimum_posterior": 0.5}

    binary = decide(
        uniform, TWO_THIRDS, votes(a="positive", b="positive", c="negative"), BINARY
    )
    three = decide(uniform, TWO_THIRDS, votes(a="cat", b="cat", c="dog"), CANDIDATE)

    assert binary.metrics["posterior"] == 0.6875
    assert three.metrics["posterior"] == round(275 / 432, 6)


@pytest.mark.parametrize(
    ("strategy", "cast", "outcomes"),
    [
        (SUPERMAJORITY, [], CANDIDATE),
        (SUPERMAJORITY, votes(ana="cat", bia="horse"), CANDIDATE),
        (SUPERMAJORITY, [Vote("ana", "cat"), Vote("ana", "dog")], CANDIDATE),
        ({"strategy": "multilabel_binary_vote"}, votes(ana="cat"), CANDIDATE),
        ({"strategy": "multilabel_binary_vote"}, votes(ana="positive"), BINARY[::-1]),
    ],
    ids=["empty", "unknown_outcome", "duplicate_rater", "not_binary", "binary_order"],
)
def test_undecidable_votes_are_invalid_input(
    strategy: dict, cast: list[Vote], outcomes: list[str]
) -> None:
    with pytest.raises(PipelineError) as error:
        decide(strategy, TWO_THIRDS, cast, outcomes)

    assert error.value.code == "invalid_input"


@pytest.mark.parametrize(
    ("strategy", "calibration"),
    [
        ({"strategy": "reliability_weighted_vote"}, None),
        ({"strategy": "reliability_weighted_vote"}, {"weights": {"ana": 1.0}}),
        ({"strategy": "dawid_skene"}, None),
        (
            {"strategy": "dawid_skene"},
            {
                "priors": {"cat": 0.5, "dog": 0.3, "no_object": 0.2},
                "confusion": {
                    "ana": {
                        true: {observed: 1 / 3 for observed in CANDIDATE}
                        for true in CANDIDATE
                    }
                },
            },
        ),
    ],
    ids=["no_weights", "uncalibrated_rater", "no_snapshot", "no_confusion"],
)
def test_conditional_strategies_without_evidence_are_unavailable(
    strategy: dict, calibration: dict | None
) -> None:
    with pytest.raises(PipelineError) as error:
        decide(
            strategy, TWO_THIRDS, votes(ana="cat", bia="cat"), CANDIDATE, calibration
        )

    assert error.value.code == "resolver_unavailable"


@pytest.mark.parametrize("weight", [0.0, 0.49, 2.01, math.inf, math.nan])
def test_weights_outside_the_frozen_bounds_are_invalid(weight: float) -> None:
    calibration = {"weights": {"ana": 1.0, "bia": weight}}

    with pytest.raises(PipelineError) as error:
        decide(
            {"strategy": "reliability_weighted_vote"},
            TWO_THIRDS,
            votes(ana="cat", bia="cat"),
            CANDIDATE,
            calibration,
        )

    assert error.value.code == "invalid_input"


def confusion(outcomes: list[str]) -> dict:
    return {
        true: {observed: 0.8 if observed == true else 0.1 for observed in outcomes}
        for true in outcomes
    }


@pytest.mark.parametrize(
    "snapshot",
    [
        {
            "priors": {"cat": 0.5, "dog": 0.5},
            "confusion": {"ana": confusion(CANDIDATE), "bia": confusion(CANDIDATE)},
        },
        {
            "priors": {"cat": 0.4, "dog": 0.4, "no_object": 0.2},
            "confusion": {
                "ana": confusion(CANDIDATE),
                "bia": {
                    key: row
                    for key, row in confusion(CANDIDATE).items()
                    if key != "no_object"
                },
            },
        },
        {
            "priors": {"cat": 0.4, "dog": 0.4, "no_object": 0.2},
            "confusion": {
                "ana": confusion(CANDIDATE),
                "bia": {
                    key: {**row, "bird": 0.0}
                    for key, row in confusion(CANDIDATE).items()
                },
            },
        },
    ],
    ids=["priors", "confusion_row", "confusion_column"],
)
def test_a_dawid_skene_snapshot_of_another_outcome_space_is_unavailable(
    snapshot: dict,
) -> None:
    with pytest.raises(PipelineError) as error:
        decide(
            {"strategy": "dawid_skene"},
            TWO_THIRDS,
            votes(ana="cat", bia="cat"),
            CANDIDATE,
            snapshot,
        )

    assert error.value.code == "resolver_unavailable"
