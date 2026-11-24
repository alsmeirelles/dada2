"""The extended COCO-PAI manifest and the training folders built from it
(spec 4.6.1).

A manifest lists exhaustively labeled, partially labeled, and unlabeled
images; a partially labeled image lists the regions annotators answered.
Training folders link every image under ``images/<media id>.<ext>`` with its
YOLO label file, so labels stay in the canonical pixel plane the annotators
drew on.
"""

import math
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from dada_api.active_learning.contract import (
    CONFIRMED_OBJECT,
    EXHAUSTIVELY_LABELED,
    EXPLICIT_HARD_NEGATIVE,
    PARTIALLY_LABELED,
    ManifestRef,
    read_manifest,
)

EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
EXIF_ORIENTATION = 0x0112


class Open(BaseModel):
    """A manifest record that keeps fields it does not name."""

    model_config = ConfigDict(extra="allow")


class QueriedROI(Open):
    """A region annotators were asked about, as ``xyxy`` canonical pixels."""

    roi_id: str
    bbox_xyxy: list[float]
    al_iteration: int | None = None
    resolution: Literal["CONFIRMED_OBJECT", "EXPLICIT_HARD_NEGATIVE"] | None = None


class PAIImage(Open):
    """One image of a manifest."""

    id: str
    file_name: str
    media_type: str
    width: int
    height: int
    annotation_status: str
    queried_rois: list[QueriedROI] = []


class PAIAnnotation(Open):
    """One accepted object, or one proposed target in a selection."""

    id: str
    image_id: str
    category_id: int | None = None
    bbox: list[float] | None = None
    segmentation: list[list[float]] | None = None
    roi_id: str | None = None


class PAICategory(Open):
    """A project class and its index."""

    id: int
    name: str
    class_id: str


class PAIManifest(Open):
    """A ``dada-coco-pai/1`` manifest."""

    info: dict[str, Any]
    categories: list[PAICategory]
    images: list[PAIImage]
    annotations: list[PAIAnnotation]


def load(media_root: str, ref: ManifestRef) -> PAIManifest:
    """Read and parse a verified manifest.

    Args:
        media_root: Media root of the request.
        ref: Manifest reference.

    Returns:
        The manifest.
    """
    return PAIManifest.model_validate(read_manifest(media_root, ref))


def regions(manifest: PAIManifest) -> dict[str, list[list[float]]]:
    """Return the answered regions of each partially labeled image.

    Args:
        manifest: Training manifest.

    Returns:
        ``xyxy`` regions keyed by media id; exhaustive images are absent.
    """
    return {
        image.id: [
            roi.bbox_xyxy
            for roi in image.queried_rois
            if roi.resolution in (CONFIRMED_OBJECT, EXPLICIT_HARD_NEGATIVE)
        ]
        for image in manifest.images
        if image.annotation_status == PARTIALLY_LABELED
    }


def link_image(media_root: str, image: PAIImage, folder: Path) -> Path:
    """Expose one image under ``folder`` with the extension of its format.

    The file is linked, or copied when links are not allowed. A JPEG whose
    EXIF orientation is set is written as PNG pixels without that rotation,
    because annotations live in the stored pixel plane and image readers
    would otherwise rotate it.

    Args:
        media_root: Media root of the request.
        image: Manifest image.
        folder: Destination folder.

    Returns:
        Path of the exposed image.
    """
    from PIL import Image

    source = Path(media_root) / image.file_name
    folder.mkdir(parents=True, exist_ok=True)
    if image.media_type == "image/jpeg":
        with Image.open(source) as opened:
            if opened.getexif().get(EXIF_ORIENTATION, 1) != 1:
                target = folder / f"{image.id}.png"
                opened.save(target)
                return target
    target = folder / f"{image.id}{EXTENSIONS[image.media_type]}"
    if not target.exists():
        try:
            os.symlink(source, target)
        except OSError:
            target.write_bytes(source.read_bytes())
    return target


def _clip(value: float) -> float:
    """Clip a normalized coordinate to ``[0, 1]``."""
    return min(max(value, 0.0), 1.0)


def yolo_lines(manifest: PAIManifest, image: PAIImage, task: str) -> list[str]:
    """Return an image's YOLO label lines, normalized by its canonical size.

    A segmentation object keeps its largest ring, since a YOLO line holds one
    polygon.

    Args:
        manifest: Manifest holding the image.
        image: Manifest image.
        task: ``detection`` or ``segmentation``.

    Returns:
        One line per annotated object.
    """
    lines = []
    for annotation in manifest.annotations:
        if annotation.image_id != image.id or annotation.category_id is None:
            continue
        if task == "segmentation" and annotation.segmentation:
            ring = max(annotation.segmentation, key=_ring_area)
            values = [
                _clip(value / (image.width if index % 2 == 0 else image.height))
                for index, value in enumerate(ring)
            ]
        else:
            x, y, width, height = annotation.bbox
            values = [
                _clip((x + width / 2) / image.width),
                _clip((y + height / 2) / image.height),
                _clip(width / image.width),
                _clip(height / image.height),
            ]
        lines.append(
            " ".join([str(annotation.category_id), *(f"{v:.6f}" for v in values)])
        )
    return lines


def _ring_area(ring: list[float]) -> float:
    """Return the shoelace area of a flat ring."""
    xs, ys = ring[0::2], ring[1::2]
    count = len(xs)
    return (
        abs(
            sum(
                xs[i] * ys[(i + 1) % count] - xs[(i + 1) % count] * ys[i]
                for i in range(count)
            )
        )
        / 2
    )


def write_split(
    manifest: PAIManifest, media_root: str, folder: Path, task: str
) -> Path:
    """Write one YOLO split: linked images and their label files.

    Args:
        manifest: Manifest of the split.
        media_root: Media root of the request.
        folder: Split folder; ``images`` and ``labels`` are created in it.
        task: ``detection`` or ``segmentation``.

    Returns:
        The ``images`` folder.
    """
    images = folder / "images"
    labels = folder / "labels"
    labels.mkdir(parents=True, exist_ok=True)
    for image in manifest.images:
        linked = link_image(media_root, image, images)
        (labels / f"{linked.stem}.txt").write_text(
            "\n".join(yolo_lines(manifest, image, task))
        )
    return images


def write_data_yaml(path: Path, train: Path, val: Path, names: list[str]) -> Path:
    """Write an Ultralytics dataset description.

    Args:
        path: File to write.
        train: Training images folder.
        val: Validation images folder.
        names: Class names in index order.

    Returns:
        The written file.
    """
    lines = [f"train: {train}", f"val: {val}", "names:"]
    lines += [f"  {index}: {name!r}" for index, name in enumerate(names)]
    path.write_text("\n".join(lines) + "\n")
    return path


def classification_items(
    manifest: PAIManifest, media_root: str, folder: Path
) -> tuple[list[tuple[Path, int]], int]:
    """Return the images with exactly one accepted class (D10).

    Args:
        manifest: Manifest of the split.
        media_root: Media root of the request.
        folder: Folder where the images are exposed.

    Returns:
        ``(path, class index)`` pairs and how many images were left out.
    """
    classes: dict[str, set[int]] = {}
    for annotation in manifest.annotations:
        classes.setdefault(annotation.image_id, set()).add(annotation.category_id)
    items = []
    for image in manifest.images:
        found = classes.get(image.id, set())
        if len(found) == 1 and image.annotation_status == EXHAUSTIVELY_LABELED:
            items.append((link_image(media_root, image, folder), found.pop()))
    return items, len(manifest.images) - len(items)


GRID = 64


def snap(value: float, low: float, high: float, direction: int = 0) -> float:
    """Put a coordinate on a 1/64-pixel grid inside ``[low, high]``.

    Grid values are exact binary fractions, so a box written as
    ``[x, y, width, height]`` adds back up to its corners exactly.

    Args:
        value: Coordinate in canonical pixels.
        low: Least allowed value.
        high: Greatest allowed value.
        direction: ``-1`` rounds down, ``1`` rounds up, ``0`` to nearest.

    Returns:
        The snapped coordinate.
    """
    scaled = value * GRID
    rounded = {-1: math.floor, 1: math.ceil, 0: round}[direction](scaled)
    return min(max(rounded / GRID, low), high)
