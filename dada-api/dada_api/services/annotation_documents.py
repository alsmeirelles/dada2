"""Pure validation and hashing of full-image annotation documents.

Nothing here touches the database or HTTP. The request schemas already
guarantee the structure and the size limits, so a draft is stored as sent;
this module adds the task and geometry rules a submission must satisfy.

Coordinates are original-image pixels: a rectangle is ``[x, y, width,
height]`` and a polygon is a list of flat rings ``[x1, y1, x2, y2, ...]``.
"""

import hashlib
import json
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

from dada_api.services.label_formats import ring_is_simple

MAX_OBJECTS = 1000
MAX_RING_POINTS = 1000
EMPTY_ALLOWED_TASKS = frozenset({"detection", "segmentation"})
GEOMETRY_BY_TASK = {
    "classification": None,
    "detection": "rectangle",
    "segmentation": "polygon",
}


@dataclass(frozen=True)
class DocumentError:
    """One reason a submitted document is refused."""

    object_id: str | None
    code: str


def content_hash(objects: list[dict[str, Any]]) -> str:
    """Return the SHA-256 of the objects' canonical JSON form.

    Args:
        objects: Annotation objects as stored.

    Returns:
        A hex digest that is equal for equal documents regardless of key order.
    """
    canonical = json.dumps(objects, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_submission(
    task_type: str,
    objects: list[dict[str, Any]],
    class_ids: Collection[str],
    width: int,
    height: int,
) -> list[DocumentError]:
    """Return every rule a document breaks before it may be submitted.

    An image may carry several classes. An empty document is the explicit
    "nothing here" answer for detection and segmentation; a classification
    needs at least one class, and each class only once.

    Args:
        task_type: The project's task.
        objects: Structurally valid annotation objects.
        class_ids: Identifiers of the project's classes.
        width: Original image width in pixels.
        height: Original image height in pixels.

    Returns:
        The errors found, empty when the document may be submitted.
    """
    errors: list[DocumentError] = []
    if not objects and task_type not in EMPTY_ALLOWED_TASKS:
        errors.append(DocumentError(None, "empty_not_allowed"))

    seen_ids: set[str] = set()
    seen_classes: set[str] = set()
    for item in objects:
        object_id = item["id"]
        if object_id in seen_ids:
            errors.append(DocumentError(object_id, "duplicate_object_id"))
        seen_ids.add(object_id)

        if item["class_id"] not in class_ids:
            errors.append(DocumentError(object_id, "unknown_class"))
        if task_type == "classification":
            if item["class_id"] in seen_classes:
                errors.append(DocumentError(object_id, "duplicate_class"))
            seen_classes.add(item["class_id"])

        geometry = item["geometry"]
        kind = geometry["type"] if geometry else None
        if kind != GEOMETRY_BY_TASK[task_type]:
            errors.append(DocumentError(object_id, "wrong_geometry"))
        elif kind == "rectangle":
            code = _rectangle_error(geometry["coordinates"], width, height)
            if code:
                errors.append(DocumentError(object_id, code))
        elif kind == "polygon":
            for ring in geometry["coordinates"]:
                code = _ring_error(ring, width, height)
                if code:
                    errors.append(DocumentError(object_id, code))
                    break
    return errors


def _rectangle_error(coordinates: list[float], width: int, height: int) -> str | None:
    """Return why a box is invalid, or None when it lies inside the image."""
    x, y, box_width, box_height = coordinates
    if box_width <= 0 or box_height <= 0:
        return "degenerate_geometry"
    if x < 0 or y < 0 or x + box_width > width or y + box_height > height:
        return "out_of_bounds"
    return None


def _ring_error(ring: list[float], width: int, height: int) -> str | None:
    """Return why a polygon ring is invalid, or None when it is usable."""
    if len(ring) % 2:
        return "wrong_geometry"
    points = [(ring[i], ring[i + 1]) for i in range(0, len(ring), 2)]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(set(points)) < 3:
        return "degenerate_geometry"
    if not all(0 <= x <= width and 0 <= y <= height for x, y in points):
        return "out_of_bounds"
    if not ring_is_simple(points):
        return "self_intersecting"
    return None
