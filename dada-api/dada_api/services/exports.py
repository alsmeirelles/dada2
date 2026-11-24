"""Annotated-dataset export as a ZIP streamed while it is written (D19).

Each split holds only images with a current accepted resolution, as the
display copies annotators saw, labelled in COCO or YOLO for detection and
segmentation and as a one-hot CSV for classification. ``provenance.json``
records what those formats cannot: the resolution versions, each image's
source and display copy, its annotation status, and the regions already
queried, so a partially labeled image is never mistaken for an exhaustive one.
"""

import csv
import io
import json
import posixpath
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.active_learning.contract import FULL_IMAGE_ORIGIN, TARGET_ORIGIN
from dada_api.core.errors import ApiError
from dada_api.models.batch import BatchPurpose
from dada_api.models.project import DatasetLayout, Project
from dada_api.services import learning_snapshots, storage

SCHEMA = "dada-export/1"
FORMATS: dict[str, tuple[str, ...]] = {
    "classification": ("csv",),
    "detection": ("coco", "yolo"),
    "segmentation": ("coco", "yolo"),
}
SPLITS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    DatasetLayout.split: (
        ("train", (BatchPurpose.initial_training, BatchPurpose.acquisition)),
        ("val", (BatchPurpose.validation,)),
        ("test", (BatchPurpose.test,)),
    ),
    DatasetLayout.single_batch: (("all", (BatchPurpose.initial_annotation,)),),
}
COORDINATE_PLANE = (
    "Pixels of each exported image, with any HEIF orientation already applied."
)


@dataclass(frozen=True)
class Entry:
    """One exported image.

    Attributes:
        name: Path inside the split's image folder.
        key: Storage key of the display copy.
        image: Manifest description of the image.
        annotations: Its manifest annotations.
        resolutions: The accepted resolutions it was built from.
    """

    name: str
    key: str
    image: dict[str, Any]
    annotations: list[dict[str, Any]]
    resolutions: list[dict[str, Any]]


@dataclass(frozen=True)
class Export:
    """Everything the archive needs, read before streaming starts.

    Attributes:
        project: Identity, name, task, and layout of the project.
        format: ``coco``, ``yolo``, or ``csv``.
        classes: Manifest categories in index order.
        splits: Each split's name and exported images.
        exported_at: When the export was requested.
    """

    project: dict[str, Any]
    format: str
    classes: list[dict[str, Any]]
    splits: list[tuple[str, list[Entry]]]
    exported_at: datetime


class _Buffer(io.RawIOBase):
    """Collects what the archive writes until the stream takes it.

    It cannot seek, so the archive writes each entry's sizes after its data.
    """

    def __init__(self) -> None:
        self.parts: list[bytes] = []

    def writable(self) -> bool:
        """Report that the buffer accepts writes."""
        return True

    def write(self, data: Any) -> int:
        """Keep one written block."""
        self.parts.append(bytes(data))
        return len(data)

    def take(self) -> bytes:
        """Return and forget everything written so far."""
        data = b"".join(self.parts)
        self.parts.clear()
        return data


def _image_name(image: dict[str, Any]) -> str:
    """Return an image's path inside its split folder.

    A display copy keeps the relative path it was uploaded under; an HEIC or
    HEIF source, exported as its WebP rendition, gains a ``.webp`` suffix.
    """
    if image["rendition"] == "source":
        return image["relative_path"]
    return f"{image['relative_path']}.webp"


def _resolution(row: tuple) -> dict[str, Any]:
    """Describe the accepted resolution of one resolved item."""
    _, _, item, resolution, _ = row
    entry: dict[str, Any] = {
        "resolution_id": resolution.id,
        "resolution_version": resolution.version,
        "origin": FULL_IMAGE_ORIGIN if item.target_key is None else TARGET_ORIGIN,
    }
    if item.target_key is not None:
        entry["roi_id"] = item.id
    return entry


async def prepare(
    session: AsyncSession,
    project: Project,
    export_format: str | None,
    now: datetime,
) -> Export:
    """Read every accepted resolution the archive will contain.

    Args:
        session: Active database session.
        project: Project being exported.
        export_format: Requested format; the task's first format when None.
        now: Time of the request.

    Returns:
        The export, ready to stream.

    Raises:
        ApiError: 422 ``export_format_not_supported`` when the format does
            not fit the task.
    """
    supported = FORMATS[project.task_type]
    chosen = export_format or supported[0]
    if chosen not in supported:
        raise ApiError(
            422,
            "export_format_not_supported",
            "This format is not available for the project's task.",
            details={"supported": list(supported)},
        )
    classes = await learning_snapshots.categories(session, project)
    index_of = {item["class_id"]: item["id"] for item in classes}
    splits = []
    for name, purposes in SPLITS[project.dataset_layout]:
        rows = await session.execute(
            learning_snapshots.resolved_items(project, purposes)
        )
        entries = []
        for _, group in groupby(rows, key=lambda row: row[0].id):
            group = list(group)
            image, annotations = learning_snapshots.describe(
                group[0][0],
                group[0][1],
                [
                    (item, resolution, iteration)
                    for _, _, item, resolution, iteration in group
                ],
                index_of,
            )
            entries.append(
                Entry(
                    name=_image_name(image),
                    key=image["file_name"],
                    image=image,
                    annotations=annotations,
                    resolutions=[_resolution(row) for row in group],
                )
            )
        splits.append((name, entries))
    return Export(
        project={
            "id": project.id,
            "name": project.name,
            "task_type": project.task_type,
            "dataset_layout": project.dataset_layout,
        },
        format=chosen,
        classes=classes,
        splits=splits,
        exported_at=now,
    )


def file_name(export: Export) -> str:
    """Return a safe download name built from the project name and format."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", export.project["name"]).strip("-.")
    return f"{stem or 'dataset'}-{export.format}.zip"


def _ring_area(ring: list[float]) -> float:
    """Return the shoelace area of a flat ring."""
    xs, ys = ring[0::2], ring[1::2]
    return abs(sum(xs[i] * ys[i - 1] - xs[i - 1] * ys[i] for i in range(len(xs)))) / 2


def _coco(export: Export, entries: list[Entry]) -> bytes:
    """Return one split's COCO document.

    ``file_name`` is the path inside the split's image folder and
    ``category_id`` the class index, as label imports read them. Each ring of
    a polygon is one COCO polygon, and every annotation names the resolution
    it comes from.
    """
    images, annotations = [], []
    for number, entry in enumerate(entries, start=1):
        images.append(
            {
                "id": number,
                "file_name": entry.name,
                "width": entry.image["width"],
                "height": entry.image["height"],
            }
        )
        for annotation in entry.annotations:
            item: dict[str, Any] = {
                "id": len(annotations) + 1,
                "image_id": number,
                "category_id": annotation["category_id"],
                "bbox": annotation["bbox"],
                "area": annotation["bbox"][2] * annotation["bbox"][3],
                "iscrowd": 0,
                "resolution_id": annotation["resolution_id"],
                "resolution_version": annotation["resolution_version"],
            }
            if "segmentation" in annotation:
                item["segmentation"] = annotation["segmentation"]
                item["area"] = sum(
                    _ring_area(ring) for ring in annotation["segmentation"]
                )
            annotations.append(item)
    document = {
        "info": {
            "description": export.project["name"],
            "date_created": export.exported_at.isoformat(),
        },
        "images": images,
        "annotations": annotations,
        "categories": [
            {"id": item["id"], "name": item["name"]} for item in export.classes
        ],
    }
    return json.dumps(document, ensure_ascii=False).encode()


def _yolo(task_type: str, entry: Entry) -> bytes:
    """Return one image's YOLO label file, normalized by its canonical size.

    A detection line is ``class cx cy w h``. A segmentation line is
    ``class x1 y1 x2 y2 ...`` with the object's largest ring, since a line
    holds one polygon; COCO keeps every ring.
    """
    width, height = entry.image["width"], entry.image["height"]
    lines = []
    for annotation in entry.annotations:
        if task_type == "segmentation":
            ring = max(annotation["segmentation"], key=_ring_area)
            values = [
                value / (width if index % 2 == 0 else height)
                for index, value in enumerate(ring)
            ]
        else:
            x, y, box_width, box_height = annotation["bbox"]
            values = [
                (x + box_width / 2) / width,
                (y + box_height / 2) / height,
                box_width / width,
                box_height / height,
            ]
        lines.append(
            " ".join(
                [str(annotation["category_id"]), *(f"{value:.6f}" for value in values)]
            )
        )
    return "".join(f"{line}\n" for line in lines).encode()


def _data_yaml(export: Export) -> bytes:
    """Return the YOLO dataset description of the exported splits."""
    lines = ["path: ."]
    lines.extend(f"{name}: images/{name}" for name, _ in export.splits)
    lines.append("names:")
    lines.extend(
        f"  {item['id']}: {json.dumps(item['name'], ensure_ascii=False)}"
        for item in export.classes
    )
    return "".join(f"{line}\n" for line in lines).encode()


def _csv(export: Export, split: str, entries: list[Entry]) -> bytes:
    """Return one split's classification table: the image path from the
    archive root, then one 0/1 column per class in index order."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["path", *(item["name"] for item in export.classes)])
    for entry in entries:
        present = {annotation["category_id"] for annotation in entry.annotations}
        writer.writerow(
            [
                f"images/{split}/{entry.name}",
                *(int(item["id"] in present) for item in export.classes),
            ]
        )
    return buffer.getvalue().encode()


def _labels(
    export: Export, split: str, entries: list[Entry]
) -> list[tuple[str, bytes]]:
    """Return one split's label files in the chosen format."""
    if export.format == "coco":
        return [(f"annotations/{split}.json", _coco(export, entries))]
    if export.format == "csv":
        return [(f"annotations/{split}.csv", _csv(export, split, entries))]
    return [
        (
            f"labels/{split}/{posixpath.splitext(entry.name)[0]}.txt",
            _yolo(export.project["task_type"], entry),
        )
        for entry in entries
    ]


def _provenance(export: Export) -> bytes:
    """Return the record of where every exported label and image came from."""
    document = {
        "schema": SCHEMA,
        "exported_at": export.exported_at.isoformat(),
        "format": export.format,
        "project": export.project,
        "coordinate_plane": COORDINATE_PLANE,
        "classes": [
            {"index": item["id"], "name": item["name"], "class_id": item["class_id"]}
            for item in export.classes
        ],
        "splits": {
            split: [
                {
                    "file": f"images/{split}/{entry.name}",
                    "media_id": entry.image["id"],
                    "relative_path": entry.image["relative_path"],
                    "source_sha256": entry.image["source_sha256"],
                    "rendition": entry.image["rendition"],
                    "width": entry.image["width"],
                    "height": entry.image["height"],
                    "annotation_status": entry.image["annotation_status"],
                    "queried_rois": entry.image["queried_rois"],
                    "resolutions": entry.resolutions,
                }
                for entry in entries
            ]
            for split, entries in export.splits
        },
    }
    return json.dumps(document, ensure_ascii=False, indent=2).encode()


def _write_text(archive: zipfile.ZipFile, name: str, data: bytes, stamp: tuple) -> None:
    """Add one compressed text file to the archive."""
    info = zipfile.ZipInfo(name, stamp)
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, data)


def stream(export: Export) -> Iterator[bytes]:
    """Yield the archive while it is written, one image block at a time.

    Images are stored as they are, since they are already compressed; label
    files and the provenance record are deflated. Memory stays bounded by
    one image block and one split's label files.

    Args:
        export: The prepared export.

    Yields:
        Consecutive bytes of the ZIP archive.
    """
    buffer = _Buffer()
    stamp = export.exported_at.timetuple()[:6]
    with zipfile.ZipFile(buffer, "w") as archive:
        for split, entries in export.splits:
            for entry in entries:
                info = zipfile.ZipInfo(f"images/{split}/{entry.name}", stamp)
                info.file_size = storage.media_path(entry.key).stat().st_size
                with archive.open(info, "w") as target:
                    for chunk in storage.iter_media(entry.key):
                        target.write(chunk)
                        if data := buffer.take():
                            yield data
            for name, data in _labels(export, split, entries):
                _write_text(archive, name, data, stamp)
            if data := buffer.take():
                yield data
        if export.format == "yolo":
            _write_text(archive, "data.yaml", _data_yaml(export), stamp)
        _write_text(archive, "provenance.json", _provenance(export), stamp)
    if data := buffer.take():
        yield data
