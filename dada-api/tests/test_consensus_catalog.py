"""Resolver catalog, typed configuration, and quantization tests."""

import tomllib
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from dada_api.consensus import catalog, numeric

TWO_THIRDS = {"numerator": 2, "denominator": 3}


def test_empty_configurations_take_the_p6_02_defaults() -> None:
    assert catalog.normalize("classification", {}, {}) == (
        {"class_strategy": {"strategy": "multilabel_binary_vote"}},
        {"minimum_support": TWO_THIRDS},
    )
    assert catalog.normalize("detection", {}, {}) == (
        {
            "class_strategy": {
                "strategy": "categorical_vote",
                "decision_rule": "supermajority",
            },
            "matching_iou": 0.5,
            "box_refinement": {"strategy": "coordinate_median"},
        },
        {"minimum_support": TWO_THIRDS, "minimum_median_iou": 0.5},
    )
    parameters, thresholds = catalog.normalize("segmentation", {}, {})
    assert parameters["matching_metric"] == "iou"
    assert parameters["matching_threshold"] == 0.5
    assert parameters["mask_refinement"] == {"strategy": "segmentation_majority_vote"}
    assert parameters["post_processing"] == {
        "remove_components_below": None,
        "fill_holes_below": None,
        "simplify_tolerance": None,
    }
    assert thresholds == {"minimum_support": TWO_THIRDS, "minimum_median_overlap": 0.5}


def test_dice_matching_defaults_both_overlap_values_to_two_thirds() -> None:
    parameters, thresholds = catalog.normalize(
        "segmentation", {"matching_metric": "dice"}, {}
    )
    assert parameters["matching_threshold"] == pytest.approx(2 / 3)
    assert thresholds["minimum_median_overlap"] == pytest.approx(2 / 3)


def test_an_explicit_value_is_kept() -> None:
    parameters, thresholds = catalog.normalize(
        "detection",
        {"class_strategy": {"strategy": "dirichlet_vote", "alpha": 1.0}},
        {"minimum_support": {"numerator": 3, "denominator": 4}},
    )
    assert parameters["class_strategy"] == {
        "strategy": "dirichlet_vote",
        "alpha": 1.0,
        "minimum_posterior": 0.9,
    }
    assert thresholds["minimum_support"] == {"numerator": 3, "denominator": 4}


@pytest.mark.parametrize(
    ("task_type", "parameters", "thresholds", "error_type"),
    [
        ("detection", {"agreement": 0.7}, {}, "extra_forbidden"),
        ("detection", {}, {"agreement": 0.7}, "extra_forbidden"),
        (
            "detection",
            {},
            {"minimum_support": {"numerator": 1, "denominator": 2}},
            "value_error",
        ),
        (
            "detection",
            {},
            {"minimum_support": {"numerator": 4, "denominator": 3}},
            "value_error",
        ),
        (
            "detection",
            {"class_strategy": {"strategy": "dirichlet_vote", "alpha": 20}},
            {},
            "less_than_equal",
        ),
        ("detection", {"matching_iou": float("inf")}, {}, "finite_number"),
        (
            "classification",
            {"class_strategy": {"strategy": "categorical_vote"}},
            {},
            "union_tag_invalid",
        ),
        (
            "detection",
            {"class_strategy": {"strategy": "multilabel_binary_vote"}},
            {},
            "union_tag_invalid",
        ),
        (
            "segmentation",
            {"mask_refinement": {"strategy": "staple", "pixel_threshold": 1.0}},
            {},
            "less_than",
        ),
    ],
)
def test_invalid_configurations_are_refused(
    task_type: str, parameters: dict, thresholds: dict, error_type: str
) -> None:
    with pytest.raises(ValidationError) as raised:
        catalog.normalize(task_type, parameters, thresholds)
    assert error_type in {error["type"] for error in raised.value.errors()}


def test_pins_match_the_consensus_extra() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    declared = dict(
        requirement.split("==")
        for requirement in pyproject["project"]["optional-dependencies"]["consensus"]
    )
    assert declared == catalog.PINS


def test_unavailable_reasons_never_substitute_another_strategy() -> None:
    pinned = catalog.PINS.get

    def missing(_: str) -> None:
        return None

    def wrong(_: str) -> str:
        return "0.0.1"

    requires = ("numpy",)
    assert catalog.unavailable_reason("x", "1.0.0", requires, installed=pinned) is None
    assert (
        catalog.unavailable_reason("x", "1.0.0", requires, installed=missing)
        == "dependency_missing"
    )
    assert (
        catalog.unavailable_reason("x", "1.0.0", requires, installed=wrong)
        == "dependency_incompatible"
    )
    assert (
        catalog.unavailable_reason(
            "x",
            "1.0.0",
            requires,
            installed=pinned,
            quarantined=frozenset({"x@1.0.0"}),
        )
        == "quarantined"
    )
    assert (
        catalog.unavailable_reason(
            "x", "1.0.0", requires, profiled=False, installed=pinned
        )
        == "resource_profile_unvalidated"
    )


def test_capabilities_describe_every_pipeline_with_typed_fields() -> None:
    described = catalog.capabilities(installed=catalog.PINS.get)

    assert described["classification"]["geometry_strategies"] == []
    rasa = next(
        strategy
        for strategy in described["segmentation"]["geometry_strategies"]
        if strategy["id"] == "segmentation_rasa"
    )
    assert rasa["unavailable_reason"] is None
    conditional = {
        strategy["id"]
        for strategy in described["detection"]["class_strategies"]
        if strategy["conditional"]
    }
    assert conditional == {"reliability_weighted_vote", "dawid_skene"}

    support = described["detection"]["review_thresholds"][0]
    assert support["name"] == "minimum_support"
    assert support["kind"] == "ratio"
    assert support["minimum"] == {"numerator": 1, "denominator": 2}
    assert support["minimum_inclusive"] is False

    dirichlet = next(
        strategy
        for strategy in described["detection"]["class_strategies"]
        if strategy["id"] == "dirichlet_vote"
    )
    alpha = next(item for item in dirichlet["parameters"] if item["name"] == "alpha")
    assert (alpha["minimum"], alpha["maximum"], alpha["advanced"]) == (0.1, 10, True)

    segmentation_names = [
        item["name"] for item in described["segmentation"]["parameters"]
    ]
    assert segmentation_names == [
        "matching_metric",
        "matching_threshold",
        "post_processing.remove_components_below",
        "post_processing.fill_holes_below",
        "post_processing.simplify_tolerance",
    ]


def test_quantization_compares_at_six_decimal_places() -> None:
    assert numeric.quantize(2 / 3) == Decimal("0.666667")
    assert numeric.at_least(2 / 3, 0.666667)
    assert numeric.at_least(0.5, 0.5)
    assert numeric.at_least(0.4999995, 0.5)
    assert not numeric.at_least(0.499999, 0.5)
    with pytest.raises(ValueError):
        numeric.quantize(float("nan"))
