"""Golden replay of crowd-kit and STAPLE mask refinement, and version pinning."""

import json
import time
import tracemalloc
from pathlib import Path
from typing import Any

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("pandas")
pytest.importorskip("crowdkit")

from dada_api.consensus import catalog, mask_refinement  # noqa: E402
from dada_api.consensus.protocol import PipelineError  # noqa: E402

FIXTURES = json.loads(
    (
        Path(__file__).parent / "fixtures/consensus/geometry/mask_refinement.json"
    ).read_text(encoding="utf-8")
)
CROWD_KIT_STRATEGIES = [
    "segmentation_majority_vote",
    "segmentation_em",
    "segmentation_rasa",
]
MASK_QUEUE_SECONDS = 15 * 60
MASK_QUEUE_BYTES = 4 * 2**30


def grid(rows: list[str]) -> Any:
    return np.array([[cell == "#" for cell in row] for row in rows], dtype=bool)


def rows(mask: Any) -> list[str]:
    return ["".join("#" if value else "." for value in row) for row in mask.tolist()]


@pytest.mark.parametrize("case", FIXTURES["cases"], ids=lambda case: case["name"])
def test_refinement_replays_its_golden_fixture(case: dict[str, Any]) -> None:
    supporting = [grid(mask) for mask in case["masks"]]
    for _ in range(2):
        refined, diagnostics = mask_refinement.refine(case["strategy"], supporting)
        assert refined.dtype == bool
        assert rows(refined) == case["expected"]["mask"]
        assert diagnostics == case["expected"]["diagnostics"]


@pytest.mark.parametrize(
    "case",
    [
        case
        for case in FIXTURES["cases"]
        if case["strategy"]["strategy"] == "segmentation_majority_vote"
    ],
    ids=lambda case: case["name"],
)
def test_majority_vote_keeps_pixels_marked_by_at_least_half(
    case: dict[str, Any],
) -> None:
    supporting = [grid(mask) for mask in case["masks"]]

    refined, _ = mask_refinement.refine(case["strategy"], supporting)

    votes = np.sum(supporting, axis=0)
    assert np.array_equal(refined, 2 * votes >= len(supporting))


def test_the_three_crowd_kit_adapters_disagree_on_noisy_masks() -> None:
    noisy = [
        case for case in FIXTURES["cases"] if case["name"].endswith("noisy_four_raters")
    ]

    assert len({tuple(case["expected"]["mask"]) for case in noisy}) == len(noisy) == 3


@pytest.mark.parametrize("installed", ["1.4.1", None])
@pytest.mark.parametrize("name", CROWD_KIT_STRATEGIES)
def test_a_crowd_kit_version_other_than_the_pin_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, name: str, installed: str | None
) -> None:
    monkeypatch.setattr(catalog, "installed_version", lambda distribution: installed)
    supporting = [grid(["##", ".#"]), grid(["#.", ".#"])]

    with pytest.raises(PipelineError) as raised:
        mask_refinement.refine({"strategy": name}, supporting)

    assert raised.value.code == "resolver_unavailable"


def test_staple_does_not_depend_on_crowd_kit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog, "installed_version", lambda distribution: None)
    supporting = [grid(["##", ".#"]), grid(["##", ".#"])]

    refined, diagnostics = mask_refinement.refine(
        {"strategy": "staple", "pixel_threshold": 0.5}, supporting
    )

    assert rows(refined) == ["##", ".#"]
    assert diagnostics["pixel_threshold"] == 0.5
    assert "package" not in diagnostics


def test_rasa_on_five_full_size_masks_fits_the_mask_queue_limits() -> None:
    generator = np.random.default_rng(2048)
    ys, xs = np.mgrid[0:2048, 0:2048]
    supporting = []
    for _ in range(5):
        x, y = 1024 + generator.normal(0, 20, 2)
        width, height = 614 * (1 + generator.normal(0, 0.03, 2))
        supporting.append(((xs - x) / width) ** 2 + ((ys - y) / height) ** 2 <= 1)
    del ys, xs

    tracemalloc.start()
    started = time.perf_counter()
    refined, _ = mask_refinement.refine({"strategy": "segmentation_rasa"}, supporting)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert refined.shape == (2048, 2048)
    assert elapsed < MASK_QUEUE_SECONDS
    assert peak < MASK_QUEUE_BYTES
