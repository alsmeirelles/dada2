"""Golden replay of box overlap, agreement, and refinement (D12)."""

import json
from pathlib import Path
from typing import Any

import pytest

from dada_api.consensus import boxes
from dada_api.consensus.protocol import PipelineError

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/consensus/geometry/boxes.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", FIXTURES["iou"])
def test_iou_replays_its_golden_fixture(case: dict[str, Any]) -> None:
    for _ in range(2):
        assert boxes.iou(case["a"], case["b"]) == case["expected"]
        assert boxes.iou(case["b"], case["a"]) == case["expected"]


@pytest.mark.parametrize(
    "case", FIXTURES["median_pairwise_iou"], ids=lambda case: case["name"]
)
def test_median_pairwise_iou_replays_its_golden_fixture(case: dict[str, Any]) -> None:
    for _ in range(2):
        assert boxes.median_pairwise_iou(case["boxes"]) == case["expected"]


def test_low_geometric_agreement_falls_below_the_default_gate() -> None:
    agreement = boxes.median_pairwise_iou(
        [[0, 0, 10, 10], [5, 0, 10, 10], [0, 0, 10, 10]]
    )

    assert agreement == pytest.approx(50 / 150)
    assert agreement < 0.5


@pytest.mark.parametrize("case", FIXTURES["refine"], ids=lambda case: case["name"])
def test_refinement_replays_its_golden_fixture(case: dict[str, Any]) -> None:
    for _ in range(2):
        refined = boxes.refine(
            case["strategy"], case["boxes"], case["width"], case["height"]
        )
        assert refined == case["expected"]


def test_each_refinement_matches_its_hand_computed_corners() -> None:
    supporting = [
        [10, 10, 20, 20],
        [12, 8, 20, 22],
        [9, 11, 19, 20],
        [11, 10, 21, 19],
        [40, 30, 20, 20],
    ]

    median = boxes.refine({"strategy": "coordinate_median"}, supporting, 100, 100)
    trimmed = boxes.refine(
        {"strategy": "trimmed_mean_box", "trim_fraction": 0.2}, supporting, 100, 100
    )
    fused = boxes.refine({"strategy": "weighted_box_fusion"}, supporting, 100, 100)

    assert median == [11, 10, 32 - 11, 30 - 10]
    assert trimmed == pytest.approx([11, 31 / 3, 94 / 3 - 11, 91 / 3 - 31 / 3])
    assert fused == pytest.approx([16.4, 13.8, 36.4 - 16.4, 34 - 13.8])


@pytest.mark.parametrize(
    "case", FIXTURES["refine_invalid"], ids=lambda case: case["name"]
)
def test_a_box_without_area_after_clipping_is_invalid_output(
    case: dict[str, Any],
) -> None:
    with pytest.raises(PipelineError) as raised:
        boxes.refine(case["strategy"], case["boxes"], case["width"], case["height"])

    assert raised.value.code == "resolver_output_invalid"
