"""Binary instance masks at original image size: rasterization, polygonization,
overlap, checksums, and optional clean-up (P6-03, D14)."""

import hashlib
from collections.abc import Sequence
from typing import Any

import cv2
import numpy as np

from dada_api.consensus.numeric import at_least, quantize

SHIFT = 8
MATERIAL_CHANGE = 0.2


def rasterize(rings: Sequence[Sequence[float]], width: int, height: int) -> np.ndarray:
    """Rasterize a polygon with the even-odd rule at the original image size.

    Each ring is filled on its own with fixed-point sub-pixel coordinates and
    the fills are combined by XOR, so the fill rule never depends on OpenCV's
    own convention. Integer coordinates are pixel centers, as in OpenCV, and a
    filled ring includes the pixels its boundary passes through.

    Args:
        rings: Flat rings ``[x1, y1, x2, y2, ...]`` in original-image pixels.
        width: Original image width.
        height: Original image height.

    Returns:
        A boolean mask of shape ``(height, width)``.
    """
    mask = np.zeros((height, width), dtype=bool)
    for ring in rings:
        points = np.rint(
            np.asarray(ring, dtype=np.float64).reshape(-1, 2) * (1 << SHIFT)
        )
        layer = np.zeros((height, width), dtype=np.uint8)
        cv2.fillPoly(
            layer, [points.astype(np.int32)], 1, lineType=cv2.LINE_8, shift=SHIFT
        )
        mask ^= layer.astype(bool)
    return mask


def _origin(contour: np.ndarray) -> tuple[int, int]:
    """Return a contour's topmost, then leftmost, coordinate for ordering."""
    points = contour.reshape(-1, 2)
    return int(points[:, 1].min()), int(points[:, 0].min())


def _ring(
    contour: np.ndarray, simplify_tolerance: float | None, positive: bool
) -> list[float] | None:
    """Turn one traced contour into an oriented flat ring.

    Args:
        contour: OpenCV contour of integer pixel coordinates.
        simplify_tolerance: ``approxPolyDP`` epsilon, or None to keep it as is.
        positive: Whether the ring must have a positive signed area.

    Returns:
        The ring, or None when it has fewer than three distinct points or no
        area.
    """
    if simplify_tolerance is not None:
        contour = cv2.approxPolyDP(contour, simplify_tolerance, True)
    points = contour.reshape(-1, 2).astype(np.int64)
    x, y = points[:, 0], points[:, 1]
    twice_area = int(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))
    if len({(px, py) for px, py in points.tolist()}) < 3 or twice_area == 0:
        return None
    if (twice_area > 0) != positive:
        points = points[::-1]
    return points.astype(np.float64).ravel().tolist()


def polygonize(
    mask: np.ndarray, simplify_tolerance: float | None = None
) -> tuple[list[list[float]], dict[str, Any]]:
    """Trace a mask into flat polygon rings that keep its holes.

    ``findContours`` with ``RETR_CCOMP`` gives outer boundaries and their
    holes; ``CHAIN_APPROX_SIMPLE`` only drops the middle points of straight
    runs. Outer rings have a positive shoelace area in image coordinates
    (x right, y down) and holes a negative one. Outer rings are ordered by
    their topmost, then leftmost, coordinate, each followed by its holes in
    the same order. A ring with fewer than three distinct points or no area
    is dropped and counted, and so are the holes of a dropped outer ring.

    Args:
        mask: Boolean mask.
        simplify_tolerance: Optional ``approxPolyDP`` epsilon in pixels.

    Returns:
        The rings and the polygonization diagnostics.
    """
    contours, hierarchy = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )
    parents = [int(link[3]) for link in hierarchy[0]] if contours else []
    rings: list[list[float]] = []
    outer_rings = holes = dropped = 0
    outers = [index for index, parent in enumerate(parents) if parent == -1]
    for outer in sorted(outers, key=lambda index: _origin(contours[index])):
        children = sorted(
            (index for index, parent in enumerate(parents) if parent == outer),
            key=lambda index: _origin(contours[index]),
        )
        ring = _ring(contours[outer], simplify_tolerance, positive=True)
        if ring is None:
            dropped += 1 + len(children)
            continue
        rings.append(ring)
        outer_rings += 1
        for child in children:
            ring = _ring(contours[child], simplify_tolerance, positive=False)
            if ring is None:
                dropped += 1
                continue
            rings.append(ring)
            holes += 1
    return rings, {
        "library": "opencv",
        "library_version": cv2.__version__,
        "retrieval": "RETR_CCOMP",
        "approximation": "CHAIN_APPROX_SIMPLE",
        "simplify_tolerance": simplify_tolerance,
        "outer_rings": outer_rings,
        "holes": holes,
        "dropped_degenerate": dropped,
    }


def mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    """Return the intersection over union of two masks.

    Args:
        a: Boolean mask.
        b: Boolean mask of the same shape.

    Returns:
        The IoU, or 0.0 when both masks are empty.
    """
    union = int(np.count_nonzero(a | b))
    return int(np.count_nonzero(a & b)) / union if union else 0.0


def mask_dice(a: np.ndarray, b: np.ndarray) -> float:
    """Return the Dice coefficient of two masks.

    Args:
        a: Boolean mask.
        b: Boolean mask of the same shape.

    Returns:
        The Dice coefficient, or 0.0 when both masks are empty.
    """
    total = int(np.count_nonzero(a)) + int(np.count_nonzero(b))
    return 2 * int(np.count_nonzero(a & b)) / total if total else 0.0


def bounding_box(mask: np.ndarray) -> list[int] | None:
    """Return the pixel extent of a mask as ``[x, y, width, height]``.

    Args:
        mask: Boolean mask.

    Returns:
        The smallest box holding every foreground pixel, or None when empty.
    """
    rows = np.flatnonzero(mask.any(axis=1))
    columns = np.flatnonzero(mask.any(axis=0))
    if rows.size == 0:
        return None
    x, y = int(columns[0]), int(rows[0])
    return [x, y, int(columns[-1]) - x + 1, int(rows[-1]) - y + 1]


def boxes_intersect(a: Sequence[int], b: Sequence[int]) -> bool:
    """Return whether two pixel extents share a pixel, the cheap prefilter
    before a mask overlap.

    Args:
        a: Extent ``[x, y, width, height]`` from ``bounding_box``.
        b: Extent in the same form.

    Returns:
        True when the extents overlap.
    """
    return (
        a[0] < b[0] + b[2]
        and b[0] < a[0] + a[2]
        and a[1] < b[1] + b[3]
        and b[1] < a[1] + a[3]
    )


def checksum(mask: np.ndarray) -> str:
    """Return the SHA-256 of a mask's shape and packed bits.

    Args:
        mask: Boolean mask.

    Returns:
        The hex digest.
    """
    height, width = mask.shape
    digest = hashlib.sha256(f"{height}x{width}:".encode())
    digest.update(np.packbits(mask, axis=None).tobytes())
    return digest.hexdigest()


def _holes(mask: np.ndarray) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Label the holes of a mask: 4-connected background components that do
    not touch the image border.

    Returns:
        The background label image and ``(label, area)`` for every hole.
    """
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        (~mask).astype(np.uint8), connectivity=4
    )
    border = set(
        np.unique(
            np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1]))
        ).tolist()
    )
    return labels, [
        (label, int(stats[label, cv2.CC_STAT_AREA]))
        for label in range(1, count)
        if label not in border
    ]


def _shape(mask: np.ndarray) -> tuple[int, int, int]:
    """Return a mask's area, 8-connected component count, and hole count."""
    components = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)[0]
    return int(np.count_nonzero(mask)), components - 1, len(_holes(mask)[1])


def _below(area: int, threshold: dict[str, Any], width: int, height: int) -> bool:
    """Return whether an area is below both the pixel and the image-ratio
    limit of a normalized area threshold."""
    return area < threshold["pixels"] and not at_least(
        area, threshold["image_ratio"] * width * height
    )


def _relative_change(before: int, after: int) -> float:
    """Return ``|after - before| / before``, or 0.0 for an empty mask."""
    return abs(after - before) / before if before else 0.0


def post_process(
    mask: np.ndarray, settings: dict[str, Any], width: int, height: int
) -> tuple[np.ndarray, dict[str, Any]]:
    """Apply the configured mask clean-up and measure what it changed.

    Small 8-connected components are removed first, then small holes are
    filled. A region is affected only when its area is below both limits of
    its threshold. Simplification is applied later by ``polygonize``. A change
    of more than 20% in area, or in components plus holes, is material and
    requires review (P6-03).

    Args:
        mask: Raw aggregated boolean mask.
        settings: Normalized ``post_processing`` configuration.
        width: Original image width.
        height: Original image height.

    Returns:
        The processed mask and its diagnostics, including both checksums.
    """
    result = mask.copy()
    removed = filled = 0
    remove = settings["remove_components_below"]
    if remove is not None:
        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            result.astype(np.uint8), connectivity=8
        )
        small = [
            label
            for label in range(1, count)
            if _below(int(stats[label, cv2.CC_STAT_AREA]), remove, width, height)
        ]
        result[np.isin(labels, small)] = False
        removed = len(small)
    fill = settings["fill_holes_below"]
    if fill is not None:
        labels, holes = _holes(result)
        small = [label for label, area in holes if _below(area, fill, width, height)]
        result[np.isin(labels, small)] = True
        filled = len(small)

    area_before, components_before, holes_before = _shape(mask)
    area_after, components_after, holes_after = _shape(result)
    area_change = quantize(_relative_change(area_before, area_after))
    topology_change = quantize(
        _relative_change(
            components_before + holes_before, components_after + holes_after
        )
    )
    limit = quantize(MATERIAL_CHANGE)
    return result, {
        "raw_checksum": checksum(mask),
        "final_checksum": checksum(result),
        "area_before": area_before,
        "area_after": area_after,
        "components_before": components_before,
        "components_after": components_after,
        "holes_before": holes_before,
        "holes_after": holes_after,
        "removed_components": removed,
        "filled_holes": filled,
        "area_change": float(area_change),
        "topology_change": float(topology_change),
        "material_change": area_change > limit or topology_change > limit,
    }


def estimated_bytes(width: int, height: int, mask_count: int) -> int:
    """Estimate the memory of ``mask_count`` boolean masks of one image, for
    the pre-flight complexity check.

    Args:
        width: Original image width.
        height: Original image height.
        mask_count: Number of masks held at once.

    Returns:
        One byte per pixel per mask.
    """
    return width * height * mask_count
