"""Pure parsers turning YOLO detection and COCO segmentation labels into seeds.

Nothing here touches the database or HTTP. A parser receives the source files,
the project's media keyed by normalised relative path, and the class-index map,
and returns one seed document per labelled image plus every error it found.
Any error rejects the whole import, so a partial result is never persisted.

Geometry is converted to original-image pixel coordinates: a rectangle is
``[x, y, width, height]`` and a polygon is a list of flat rings
``[x1, y1, x2, y2, ...]``, matching the annotation document contract.
"""

import json
import math
import posixpath
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from dada_api.services.ingestion import normalize_relative_path

YOLO_PARSER_VERSION = "yolo-detection/1"
COCO_PARSER_VERSION = "coco-segmentation/1"
YOLO_TOLERANCE = 1e-6


@dataclass(frozen=True)
class SourceFile:
    """One uploaded label file."""

    file_id: str
    relative_path: str
    content: bytes


@dataclass(frozen=True)
class MediaTarget:
    """One project image a label may describe, with its original dimensions."""

    media_id: str
    width: int
    height: int


@dataclass(frozen=True)
class LabelError:
    """One reason an import cannot be accepted."""

    code: str
    file_id: str
    detail: str


@dataclass
class ParseResult:
    """Seed documents by media identifier, with the file each came from."""

    documents: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)
    errors: list[LabelError] = field(default_factory=list)


def _document(task_type: str, objects: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a seed document in the annotation document shape."""
    return {"task_type": task_type, "objects": objects}


def _object(class_id: str, kind: str, coordinates: list[Any]) -> dict[str, Any]:
    """Return one annotation object with a server-generated identifier."""
    return {
        "id": str(uuid4()),
        "class_id": class_id,
        "geometry": {"type": kind, "coordinates": coordinates},
        "attributes": {},
    }


def _is_number(value: Any) -> bool:
    """Return whether a decoded JSON value is a finite number, not a boolean."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def parse_yolo_detection(
    files: Sequence[SourceFile],
    media_index: dict[str, MediaTarget],
    class_index: dict[int, str],
) -> ParseResult:
    """Parse YOLO detection sidecars into rectangle seed documents.

    A label file matches the image whose relative path equals the label's path
    with both suffixes removed, so ``a/b.txt`` labels ``a/b.jpg``. Each
    non-empty line is ``class cx cy w h`` in normalised coordinates. An empty
    file is an explicit empty image.

    Normalised values may exceed the image by ``YOLO_TOLERANCE`` because
    exporters round to a few decimals; such boxes are clamped to the image.

    Args:
        files: Uploaded label files.
        media_index: Project images keyed by normalised relative path.
        class_index: Class identifiers keyed by ``display_order``.

    Returns:
        The seed documents and every error found.
    """
    stems: dict[str, list[MediaTarget]] = {}
    for path, target in media_index.items():
        stems.setdefault(posixpath.splitext(path)[0], []).append(target)

    result = ParseResult()
    for source in files:
        path = normalize_relative_path(source.relative_path)
        if path is None:
            result.errors.append(
                LabelError("invalid_relative_path", source.file_id, "unsafe path")
            )
            continue
        stem, suffix = posixpath.splitext(path)
        if suffix.lower() != ".txt":
            result.errors.append(
                LabelError("malformed_label", source.file_id, "not a .txt label file")
            )
            continue
        matches = stems.get(stem, [])
        if not matches:
            result.errors.append(
                LabelError("unmatched_path", source.file_id, "no image at this path")
            )
            continue
        if len(matches) > 1:
            result.errors.append(
                LabelError(
                    "ambiguous_media_match",
                    source.file_id,
                    "more than one image shares this path",
                )
            )
            continue
        target = matches[0]
        if target.media_id in result.documents:
            result.errors.append(
                LabelError(
                    "duplicate_source_label",
                    source.file_id,
                    "another label file describes this image",
                )
            )
            continue
        objects = _yolo_objects(source, target, class_index, result.errors)
        if objects is not None:
            result.documents[target.media_id] = (
                source.file_id,
                _document("detection", objects),
            )
    return result


def _yolo_objects(
    source: SourceFile,
    target: MediaTarget,
    class_index: dict[int, str],
    errors: list[LabelError],
) -> list[dict[str, Any]] | None:
    """Return one file's rectangles, or None after recording its first error."""
    try:
        text = source.content.decode("utf-8")
    except UnicodeDecodeError:
        errors.append(LabelError("malformed_label", source.file_id, "not UTF-8"))
        return None

    objects: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        tokens = line.split()
        if not tokens:
            continue
        try:
            if len(tokens) != 5:
                raise ValueError
            index = int(tokens[0])
            cx, cy, w, h = (float(token) for token in tokens[1:])
        except ValueError:
            errors.append(
                LabelError(
                    "malformed_label",
                    source.file_id,
                    f"line {number}: expected 'class cx cy w h'",
                )
            )
            return None
        if index not in class_index:
            errors.append(
                LabelError(
                    "unknown_class_index", source.file_id, f"line {number}: {index}"
                )
            )
            return None

        left, top, right, bottom = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
        if (
            not all(math.isfinite(value) for value in (cx, cy, w, h))
            or w <= 0
            or h <= 0
            or left < -YOLO_TOLERANCE
            or top < -YOLO_TOLERANCE
            or right > 1 + YOLO_TOLERANCE
            or bottom > 1 + YOLO_TOLERANCE
        ):
            errors.append(
                LabelError(
                    "invalid_geometry",
                    source.file_id,
                    f"line {number}: box outside the image or empty",
                )
            )
            return None

        left, top = max(left, 0.0), max(top, 0.0)
        right, bottom = min(right, 1.0), min(bottom, 1.0)
        objects.append(
            _object(
                class_index[index],
                "rectangle",
                [
                    left * target.width,
                    top * target.height,
                    (right - left) * target.width,
                    (bottom - top) * target.height,
                ],
            )
        )
    return objects


def parse_coco_segmentation(
    files: Sequence[SourceFile],
    media_index: dict[str, MediaTarget],
    class_index: dict[int, str],
) -> ParseResult:
    """Parse COCO segmentation documents into polygon seed documents.

    ``images[].file_name`` matches an image's normalised relative path, and
    ``category_id`` matches a class ``display_order``. An image listed without
    annotations is an explicit empty image. Polygon segmentations become rings;
    run-length encoded masks are not supported.

    Args:
        files: Uploaded COCO JSON files.
        media_index: Project images keyed by normalised relative path.
        class_index: Class identifiers keyed by ``display_order``.

    Returns:
        The seed documents and every error found.
    """
    result = ParseResult()
    for source in files:
        documents = _coco_documents(source, media_index, class_index, result)
        for media_id, objects in documents.items():
            result.documents[media_id] = (
                source.file_id,
                _document("segmentation", objects),
            )
    return result


def _coco_documents(
    source: SourceFile,
    media_index: dict[str, MediaTarget],
    class_index: dict[int, str],
    result: ParseResult,
) -> dict[str, list[dict[str, Any]]]:
    """Return one COCO file's objects by media, or nothing after its first error."""

    def fail(code: str, detail: str) -> dict[str, list[dict[str, Any]]]:
        result.errors.append(LabelError(code, source.file_id, detail))
        return {}

    try:
        data = json.loads(source.content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return fail("malformed_label", "not a UTF-8 JSON document")
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("images"), list)
        or not isinstance(data.get("annotations"), list)
    ):
        return fail("malformed_label", "missing 'images' or 'annotations' lists")

    targets: dict[Any, MediaTarget] = {}
    claimed = set(result.documents)
    for image in data["images"]:
        if not isinstance(image, dict) or not isinstance(image.get("file_name"), str):
            return fail("malformed_label", "an image entry lacks 'file_name'")
        path = normalize_relative_path(image["file_name"])
        if path is None:
            return fail("invalid_relative_path", image["file_name"])
        target = media_index.get(path)
        if target is None:
            return fail("unmatched_path", path)
        if target.media_id in claimed or image.get("id") in targets:
            return fail("duplicate_source_label", path)
        claimed.add(target.media_id)
        targets[image.get("id")] = target

    objects: dict[str, list[dict[str, Any]]] = {
        target.media_id: [] for target in targets.values()
    }
    for number, annotation in enumerate(data["annotations"]):
        if not isinstance(annotation, dict):
            return fail("malformed_label", f"annotation {number} is not an object")
        target = targets.get(annotation.get("image_id"))
        if target is None:
            return fail("unmatched_path", f"annotation {number}: unknown image_id")
        category = annotation.get("category_id")
        if (
            not isinstance(category, int)
            or isinstance(category, bool)
            or category not in class_index
        ):
            return fail("unknown_class_index", f"annotation {number}: {category}")
        rings = _coco_rings(annotation.get("segmentation"), target)
        if isinstance(rings, str):
            code, _, detail = rings.partition(":")
            return fail(code, f"annotation {number}: {detail}")
        objects[target.media_id].append(
            _object(class_index[category], "polygon", rings)
        )

    return objects


def _coco_rings(segmentation: Any, target: MediaTarget) -> list[list[float]] | str:
    """Return validated rings, or an ``code:detail`` string naming the problem."""
    if isinstance(segmentation, dict):
        return "unsupported_geometry:run-length encoded masks are not supported"
    if not isinstance(segmentation, list) or not segmentation:
        return "invalid_geometry:missing polygon segmentation"

    rings: list[list[float]] = []
    for ring in segmentation:
        if (
            not isinstance(ring, list)
            or len(ring) % 2
            or not all(_is_number(value) for value in ring)
        ):
            return "invalid_geometry:a ring is not a flat list of coordinate pairs"
        points = [(float(ring[i]), float(ring[i + 1])) for i in range(0, len(ring), 2)]
        if len(points) > 1 and points[0] == points[-1]:
            points.pop()
        if len(set(points)) < 3:
            return "invalid_geometry:a ring has fewer than three distinct points"
        if not all(
            0 <= x <= target.width and 0 <= y <= target.height for x, y in points
        ):
            return "invalid_geometry:a ring leaves the image bounds"
        if not ring_is_simple(points):
            return "invalid_geometry:a ring intersects itself"
        rings.append([value for point in points for value in point])
    return rings


def _orientation(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> int:
    """Return the turn direction of ``a -> b -> c``: 1, -1, or 0 if collinear."""
    value = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (value > 0) - (value < 0)


def _within(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> bool:
    """Return whether collinear point ``c`` lies on segment ``a-b``."""
    inside_x = min(a[0], b[0]) <= c[0] <= max(a[0], b[0])
    inside_y = min(a[1], b[1]) <= c[1] <= max(a[1], b[1])
    return inside_x and inside_y


def _segments_intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    q1: tuple[float, float],
    q2: tuple[float, float],
) -> bool:
    """Return whether two closed segments share at least one point."""
    o1, o2 = _orientation(p1, p2, q1), _orientation(p1, p2, q2)
    o3, o4 = _orientation(q1, q2, p1), _orientation(q1, q2, p2)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and _within(p1, p2, q1))
        or (o2 == 0 and _within(p1, p2, q2))
        or (o3 == 0 and _within(q1, q2, p1))
        or (o4 == 0 and _within(q1, q2, p2))
    )


def ring_is_simple(points: Sequence[tuple[float, float]]) -> bool:
    """Return whether a closed ring never crosses or touches itself.

    Every pair of non-adjacent edges is compared, which is quadratic in the
    number of vertices and adequate for annotation polygons.

    Args:
        points: Ring vertices in order, without repeating the first point.

    Returns:
        True when no two non-adjacent edges meet.
    """
    count = len(points)
    edges = [(points[i], points[(i + 1) % count]) for i in range(count)]
    for i in range(count):
        for j in range(i + 2, count):
            if i == 0 and j == count - 1:
                continue
            if _segments_intersect(*edges[i], *edges[j]):
                return False
    return True
