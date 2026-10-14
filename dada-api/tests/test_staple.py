"""Native STAPLE against the published formula and its golden fixtures (P6-03)."""

import json
import math
from pathlib import Path
from typing import Any

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from dada_api.consensus import staple  # noqa: E402
from dada_api.consensus.numeric import quantize  # noqa: E402

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/consensus/geometry/staple.json").read_text(
        encoding="utf-8"
    )
)


def grid(rows: list[str]) -> Any:
    return np.array([[cell == "#" for cell in row] for row in rows], dtype=bool)


def reference(
    decisions: list[list[int]], max_iterations: int, tolerance: float
) -> tuple[list[float], list[float], list[float], int]:
    raters, pixels = len(decisions), len(decisions[0])
    f = sum(map(sum, decisions)) / (raters * pixels)
    p, q = [0.99] * raters, [0.99] * raters
    iterations, change = 0, math.inf
    while iterations < max_iterations and change >= tolerance:
        iterations += 1
        w = []
        for i in range(pixels):
            a, b = f, 1 - f
            for j in range(raters):
                d = decisions[j][i]
                a *= p[j] ** d * (1 - p[j]) ** (1 - d)
                b *= q[j] ** (1 - d) * (1 - q[j]) ** d
            w.append(a / (a + b))
        new_p = [
            sum(w[i] * decisions[j][i] for i in range(pixels)) / sum(w)
            for j in range(raters)
        ]
        new_q = [
            sum((1 - w[i]) * (1 - decisions[j][i]) for i in range(pixels))
            / sum(1 - value for value in w)
            for j in range(raters)
        ]
        change = max(abs(x - y) for x, y in zip(new_p + new_q, p + q, strict=True))
        p, q = new_p, new_q
    return w, p, q, iterations


@pytest.mark.parametrize("case", FIXTURES["cases"], ids=lambda case: case["name"])
def test_staple_replays_its_golden_fixture(case: dict[str, Any]) -> None:
    supporting = [grid(rows) for rows in case["masks"]]
    for _ in range(2):
        probabilities, diagnostics = staple.staple(
            supporting, case["max_iterations"], case["tolerance"]
        )
        assert probabilities.shape == supporting[0].shape
        assert [
            [float(quantize(value)) for value in row] for row in probabilities.tolist()
        ] == case["expected"]["probabilities"]
        assert diagnostics == case["expected"]["diagnostics"]


def test_one_iteration_matches_the_hand_computed_formula() -> None:
    supporting = [grid(["##.."]), grid(["#..."])]
    f = 3 / 8

    probabilities, diagnostics = staple.staple(supporting, max_iterations=1)

    both = f * 0.99 * 0.99 / (f * 0.99 * 0.99 + (1 - f) * 0.01 * 0.01)
    first_only = f * 0.99 * 0.01 / (f * 0.99 * 0.01 + (1 - f) * 0.01 * 0.99)
    neither = f * 0.01 * 0.01 / (f * 0.01 * 0.01 + (1 - f) * 0.99 * 0.99)
    expected = [both, first_only, neither, neither]
    assert probabilities[0].tolist() == pytest.approx(expected, abs=1e-12)
    assert first_only == pytest.approx(0.375)
    total = sum(expected)
    assert diagnostics["sensitivity"] == [
        float(quantize((both + first_only) / total)),
        float(quantize(both / total)),
    ]
    absent = sum(1 - value for value in expected)
    assert diagnostics["specificity"] == [
        float(quantize(2 * (1 - neither) / absent)),
        float(quantize((1 - first_only + 2 * (1 - neither)) / absent)),
    ]
    assert diagnostics["iterations"] == 1
    assert diagnostics["prior"] == f


@pytest.mark.parametrize("seed", [3, 11, 29])
def test_staple_matches_an_independent_reference_implementation(seed: int) -> None:
    generator = np.random.default_rng(seed)
    truth = np.zeros((6, 7), dtype=bool)
    truth[1:5, 2:6] = True
    supporting = [truth ^ (generator.random(truth.shape) < 0.15) for _ in range(4)]
    decisions = [mask.ravel().astype(int).tolist() for mask in supporting]

    probabilities, diagnostics = staple.staple(supporting)
    w, p, q, iterations = reference(decisions, 100, 1e-6)

    assert probabilities.ravel().tolist() == pytest.approx(w, abs=1e-9)
    assert diagnostics["iterations"] == iterations
    assert diagnostics["sensitivity"] == pytest.approx(p, abs=2e-6)
    assert diagnostics["specificity"] == pytest.approx(q, abs=2e-6)
    assert diagnostics["prior"] == pytest.approx(
        sum(map(sum, decisions)) / (4 * truth.size), abs=1e-6
    )


def test_identical_raters_recover_their_shared_mask() -> None:
    shared = grid([".##", ".#."])

    probabilities, diagnostics = staple.staple([shared, shared, shared])

    assert np.array_equal(probabilities >= 0.5, shared)
    assert diagnostics["converged"] is True
    assert math.isclose(diagnostics["prior"], 0.5)
