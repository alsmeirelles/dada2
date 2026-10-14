"""Golden replay of rasterization, polygonization, mask matching, and clean-up."""

import json
from pathlib import Path
from typing import Any

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("cv2")

from dada_api.consensus import masks, matching  # noqa: E402

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/consensus/geometry/masks.json").read_text(
        encoding="utf-8"
    )
)
POLYGONS = {case["name"]: case for case in FIXTURES["polygons"]}


def rows(mask: Any) -> list[str]:
    return ["".join("#" if value else "." for value in row) for row in mask.tolist()]


def signed_area(ring: list[float]) -> float:
    x, y = ring[0::2], ring[1::2]
    return (
        sum(
            x[i] * y[(i + 1) % len(x)] - x[(i + 1) % len(x)] * y[i]
            for i in range(len(x))
        )
        / 2
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


@pytest.mark.parametrize("case", FIXTURES["polygons"], ids=lambda case: case["name"])
def test_rasterize_and_polygonize_replay_their_golden_fixture(
    case: dict[str, Any],
) -> None:
    expected = case["expected"]
    for _ in range(2):
        mask = masks.rasterize(case["rings"], case["width"], case["height"])
        rings, diagnostics = masks.polygonize(mask, case["simplify_tolerance"])

        assert mask.shape == (case["height"], case["width"])
        assert int(mask.sum()) == expected["area"]
        assert masks.checksum(mask) == expected["checksum"]
        assert masks.bounding_box(mask) == expected["bounding_box"]
        if "mask" in expected:
            assert rows(mask) == expected["mask"]
        assert rings == expected["rings"]
        assert diagnostics == expected["diagnostics"]


def test_a_hole_survives_with_the_opposite_orientation() -> None:
    case = POLYGONS["polygon_with_hole"]
    mask = masks.rasterize(case["rings"], case["width"], case["height"])

    rings, diagnostics = masks.polygonize(mask)

    assert not mask[9, 9]
    assert diagnostics["outer_rings"] == 1
    assert diagnostics["holes"] == 1
    assert signed_area(rings[0]) > 0
    assert signed_area(rings[1]) < 0


def test_even_odd_fill_does_not_depend_on_ring_order() -> None:
    first, second = POLYGONS["polygon_with_hole"], POLYGONS["hole_ring_listed_first"]

    assert first["expected"]["checksum"] == second["expected"]["checksum"]


def test_an_island_inside_a_hole_follows_its_outer_ring_and_hole() -> None:
    case = POLYGONS["island_inside_hole"]
    mask = masks.rasterize(case["rings"], case["width"], case["height"])

    rings, _ = masks.polygonize(mask)

    assert [signed_area(ring) > 0 for ring in rings] == [True, False, True]
    assert mask[10, 10]
    assert not mask[6, 6]


def test_disconnected_regions_are_ordered_top_then_left() -> None:
    case = POLYGONS["disconnected_regions"]
    mask = masks.rasterize(case["rings"], case["width"], case["height"])

    rings, diagnostics = masks.polygonize(mask)

    assert diagnostics["outer_rings"] == 2
    assert [min(ring[1::2]) for ring in rings] == [1.0, 6.0]
    assert all(signed_area(ring) > 0 for ring in rings)


def test_a_one_pixel_structure_is_dropped_and_counted() -> None:
    case = POLYGONS["thin_one_pixel_structure_dropped"]
    mask = masks.rasterize(case["rings"], case["width"], case["height"])

    rings, diagnostics = masks.polygonize(mask)

    assert int(mask.sum()) == 20
    assert rings == []
    assert diagnostics["dropped_degenerate"] == 1


def test_simplification_keeps_fewer_points_of_the_same_mask() -> None:
    traced = POLYGONS["star_traced"]["expected"]["rings"]
    simplified = POLYGONS["star_simplified"]["expected"]["rings"]

    assert len(simplified) == len(traced) == 1
    assert len(simplified[0]) < len(traced[0])


def test_an_empty_mask_has_no_rings_box_or_overlap() -> None:
    empty = np.zeros((4, 5), dtype=bool)

    rings, diagnostics = masks.polygonize(empty)

    assert rings == []
    assert diagnostics["outer_rings"] == diagnostics["dropped_degenerate"] == 0
    assert masks.bounding_box(empty) is None
    assert masks.mask_iou(empty, empty) == 0.0
    assert masks.mask_dice(empty, empty) == 0.0


def test_mask_iou_and_dice_count_pixels() -> None:
    a = np.zeros((4, 10), dtype=bool)
    b = np.zeros((4, 10), dtype=bool)
    a[:, 0:6] = True
    b[:, 3:9] = True

    assert masks.mask_iou(a, b) == 12 / 36
    assert masks.mask_dice(a, b) == 24 / 48


def test_the_checksum_covers_the_shape() -> None:
    assert masks.checksum(np.zeros((2, 8), dtype=bool)) != masks.checksum(
        np.zeros((4, 4), dtype=bool)
    )


def test_touching_extents_do_not_intersect() -> None:
    assert not masks.boxes_intersect([0, 0, 10, 10], [10, 0, 10, 10])
    assert masks.boxes_intersect([0, 0, 10, 10], [9, 9, 10, 10])


@pytest.mark.parametrize("case", FIXTURES["matching"], ids=lambda case: case["name"])
def test_mask_grouping_replays_its_golden_fixture(case: dict[str, Any]) -> None:
    objects = []
    for rater in case["objects"]:
        row = []
        for rings in rater:
            mask = masks.rasterize(rings, case["width"], case["height"])
            row.append((mask, masks.bounding_box(mask)))
        objects.append(row)
    metric = masks.mask_iou if case["metric"] == "iou" else masks.mask_dice

    for _ in range(2):
        grouping = matching.group(
            objects,
            lambda first, second: metric(first[0], second[0]),
            case["threshold"],
            lambda first, second: masks.boxes_intersect(first[1], second[1]),
        )
        assert as_json(grouping) == case["expected"]


@pytest.mark.parametrize(
    "case", FIXTURES["post_processing"], ids=lambda case: case["name"]
)
def test_post_processing_replays_its_golden_fixture(case: dict[str, Any]) -> None:
    mask = masks.rasterize(case["rings"], case["width"], case["height"])
    for _ in range(2):
        processed, diagnostics = masks.post_process(
            mask, case["settings"], case["width"], case["height"]
        )
        assert masks.checksum(processed) == case["expected"]["checksum"]
        assert diagnostics == case["expected"]["diagnostics"]
    assert masks.checksum(mask) == case["expected"]["diagnostics"]["raw_checksum"]


def test_disabled_post_processing_returns_the_mask_unchanged() -> None:
    case = next(
        item
        for item in FIXTURES["post_processing"]
        if item["name"] == "every_step_disabled"
    )
    mask = masks.rasterize(case["rings"], case["width"], case["height"])

    processed, diagnostics = masks.post_process(
        mask, case["settings"], case["width"], case["height"]
    )

    assert np.array_equal(processed, mask)
    assert diagnostics["material_change"] is False


def test_the_memory_estimate_is_one_byte_per_mask_pixel() -> None:
    assert masks.estimated_bytes(2048, 1024, 5) == 2048 * 1024 * 5
