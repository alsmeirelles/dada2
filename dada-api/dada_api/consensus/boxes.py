"""Box overlap and package-free box refinement for detection consensus (D12)."""

import itertools
import math
import statistics
from collections.abc import Sequence
from typing import Any

from dada_api.consensus.numeric import quantize
from dada_api.consensus.protocol import PipelineError


def _corners(box: Sequence[float]) -> tuple[float, float, float, float]:
    """Convert ``[x, y, width, height]`` to ``(x1, y1, x2, y2)``."""
    x, y, width, height = box
    return x, y, x + width, y + height


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    """Return the intersection over union of two boxes.

    Args:
        a: Box ``[x, y, width, height]`` with positive width and height.
        b: Box in the same form.

    Returns:
        The IoU, from 0 to 1.
    """
    ax1, ay1, ax2, ay2 = _corners(a)
    bx1, by1, bx2, by2 = _corners(b)
    width = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    height = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = width * height
    return intersection / (a[2] * a[3] + b[2] * b[3] - intersection)


def median_pairwise_iou(boxes: Sequence[Sequence[float]]) -> float | None:
    """Return the median IoU over every pair of an object's supporting boxes.

    It is the geometric agreement gate: low agreement requires review even
    when the class agreement is high.

    Args:
        boxes: Supporting boxes ``[x, y, width, height]``.

    Returns:
        The median pairwise IoU, or None for fewer than two boxes.
    """
    if len(boxes) < 2:
        return None
    return statistics.median(iou(a, b) for a, b in itertools.combinations(boxes, 2))


def _median(values: Sequence[float], strategy: dict[str, Any]) -> float:
    """Return the median of one coordinate (``coordinate_median``)."""
    return statistics.median(values)


def _trimmed_mean(values: Sequence[float], strategy: dict[str, Any]) -> float:
    """Return the mean of one coordinate after trimming ``floor(n * f)``
    values from each end (``trimmed_mean_box``)."""
    cut = math.floor(quantize(strategy["trim_fraction"]) * len(values))
    ordered = sorted(values)
    return statistics.fmean(ordered[cut : len(ordered) - cut])


def _mean(values: Sequence[float], strategy: dict[str, Any]) -> float:
    """Return the mean of one coordinate (``weighted_box_fusion`` with the
    equal weights of human boxes)."""
    return statistics.fmean(values)


AGGREGATES = {
    "coordinate_median": _median,
    "trimmed_mean_box": _trimmed_mean,
    "weighted_box_fusion": _mean,
}


def refine(
    strategy: dict[str, Any], boxes: Sequence[Sequence[float]], width: int, height: int
) -> list[float]:
    """Fuse the supporting boxes of one accepted object into one box.

    Each corner coordinate is aggregated on its own, and the result is
    clipped to the original image.

    Args:
        strategy: Normalized ``box_refinement`` configuration.
        boxes: Supporting boxes ``[x, y, width, height]``.
        width: Original image width in pixels.
        height: Original image height in pixels.

    Returns:
        The refined box ``[x, y, width, height]``.

    Raises:
        PipelineError: ``resolver_output_invalid`` when the clipped box has no
            area.
    """
    aggregate = AGGREGATES[strategy["strategy"]]
    columns = zip(*(_corners(box) for box in boxes), strict=True)
    x1, y1, x2, y2 = (float(aggregate(column, strategy)) for column in columns)
    x1, x2 = (min(max(value, 0.0), float(width)) for value in (x1, x2))
    y1, y2 = (min(max(value, 0.0), float(height)) for value in (y1, y2))
    if quantize(x2 - x1) <= 0 or quantize(y2 - y1) <= 0:
        raise PipelineError(
            "resolver_output_invalid", "the refined box has no area inside the image"
        )
    return [x1, y1, x2 - x1, y2 - y1]
