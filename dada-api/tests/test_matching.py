"""Golden replay of class-agnostic candidate grouping (D13)."""

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy")

from dada_api.consensus import boxes, matching  # noqa: E402

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/consensus/geometry/matching.json").read_text(
        encoding="utf-8"
    )
)


def as_json(grouping: matching.Grouping) -> dict[str, Any]:
    return {
        "groups": [
            {
                "members": [[member.rater, member.index] for member in group.members],
                "ambiguous": group.ambiguous,
            }
            for group in grouping.groups
        ],
        "duplicates": [[member.rater, member.index] for member in grouping.duplicates],
    }


def table(entries: list[list[Any]]) -> Any:
    scores = {}
    for first, second, value in entries:
        scores[first, second] = scores[second, first] = value
    return lambda first, second: scores.get((first, second), 0.0)


@pytest.mark.parametrize("case", FIXTURES["box_cases"], ids=lambda case: case["name"])
def test_box_grouping_replays_its_golden_fixture(case: dict[str, Any]) -> None:
    for _ in range(2):
        grouping = matching.group(case["objects"], boxes.iou, case["threshold"])
        assert as_json(grouping) == case["expected"]


@pytest.mark.parametrize("case", FIXTURES["table_cases"], ids=lambda case: case["name"])
def test_scored_grouping_replays_its_golden_fixture(case: dict[str, Any]) -> None:
    overlap = table(case["overlaps"])
    for _ in range(2):
        grouping = matching.group(case["objects"], overlap, case["threshold"])
        assert as_json(grouping) == case["expected"]


def test_a_large_box_never_bridges_two_nearby_objects() -> None:
    big, left, right = [0, 0, 20, 10], [0, 0, 12, 10], [9, 0, 11, 10]

    grouping = matching.group([[big], [left], [right]], boxes.iou, 0.5)

    assert [len(group.members) for group in grouping.groups] == [2, 1]
    assert boxes.iou(left, right) < 0.5


def test_every_object_is_grouped_once_or_is_a_duplicate() -> None:
    objects = [
        [[0, 0, 10, 10], [1, 0, 10, 10], [40, 40, 10, 10]],
        [[0, 1, 10, 10], [41, 40, 10, 10], [80, 0, 5, 5]],
        [[60, 60, 5, 5]],
    ]

    grouping = matching.group(objects, boxes.iou, 0.5)

    placed = [member for group in grouping.groups for member in group.members]
    everything = [
        matching.Member(rater, index)
        for rater, items in enumerate(objects)
        for index in range(len(items))
    ]
    assert sorted(placed + list(grouping.duplicates)) == everything
    for group in grouping.groups:
        assert len({member.rater for member in group.members}) == len(group.members)


def test_a_rejecting_prefilter_means_no_overlap() -> None:
    objects = [[[0, 0, 10, 10]], [[0, 0, 10, 10]]]

    grouping = matching.group(
        objects, boxes.iou, 0.5, may_overlap=lambda first, second: False
    )

    assert [group.members for group in grouping.groups] == [
        (matching.Member(0, 0),),
        (matching.Member(1, 0),),
    ]
