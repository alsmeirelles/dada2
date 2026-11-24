"""Immutable manifests of accepted annotations and eligible media (D3).

A manifest lists images by their display bytes and canonical dimensions and
annotations taken only from current accepted resolutions. An image annotated
whole is exhaustively labeled; one whose object targets alone were answered is
partially labeled and lists each answered target's region as a queried ROI,
confirmed or a hard negative. It is written once under the project's learning
folder and named by the digest of its canonical JSON, so the same content
always yields the same file.
"""

import hashlib
from collections.abc import Sequence
from itertools import groupby
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.active_learning.contract import (
    CONFIRMED_OBJECT,
    EXHAUSTIVELY_LABELED,
    EXPLICIT_HARD_NEGATIVE,
    FULL_IMAGE_ORIGIN,
    MANIFEST_SCHEMA,
    PARTIALLY_LABELED,
    TARGET_ORIGIN,
    UNLABELED,
    ManifestRef,
    canonical_bytes,
)
from dada_api.models.annotation import ResolvedAnnotation
from dada_api.models.batch import AnnotationBatch, BatchItem, BatchPurpose, ItemStatus
from dada_api.models.learning import LearningRun
from dada_api.models.media import ContentObject, Media
from dada_api.models.project import Project, ProjectClass
from dada_api.services import storage

ROLE_PURPOSES = {
    "training": (BatchPurpose.initial_training, BatchPurpose.acquisition),
    "validation": (BatchPurpose.validation,),
    "test": (BatchPurpose.test,),
}


async def categories(session: AsyncSession, project: Project) -> list[dict[str, Any]]:
    """Return the project's classes as manifest categories in index order."""
    rows = await session.scalars(
        select(ProjectClass)
        .where(ProjectClass.project_id == project.id)
        .order_by(ProjectClass.display_order)
    )
    return [
        {"id": item.display_order, "name": item.name, "class_id": item.id}
        for item in rows
    ]


def _image(media: Media, content: ContentObject, status: str) -> dict[str, Any]:
    """Describe one image by the bytes every consumer reads."""
    heif = content.media_type in storage.HEIF_MEDIA_TYPES
    return {
        "id": media.id,
        "file_name": storage.display_key(
            content.project_id, content.sha256, content.media_type, content.storage_key
        ),
        "media_type": storage.RENDITION_MEDIA_TYPE if heif else content.media_type,
        "width": content.width,
        "height": content.height,
        "relative_path": media.relative_path,
        "source_sha256": content.sha256,
        "rendition": f"webp-lossless/{storage.RENDITION_VERSION}" if heif else "source",
        "annotation_status": status,
        "queried_rois": [],
    }


def _bounds(rings: list[list[float]]) -> list[float]:
    """Return the ``[x, y, width, height]`` box enclosing every ring."""
    xs = [x for ring in rings for x in ring[0::2]]
    ys = [y for ring in rings for y in ring[1::2]]
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


def _annotations(
    resolution: ResolvedAnnotation,
    item: BatchItem,
    index_of: dict[str, int],
) -> list[dict[str, Any]]:
    """Convert one accepted resolution's objects into manifest annotations.

    The objects of an object target carry its ``roi_id``, the identifier of
    the target's item.
    """
    annotations = []
    for position, entry in enumerate(resolution.objects):
        annotation: dict[str, Any] = {
            "id": f"{resolution.id}:{position}",
            "image_id": item.media_id,
            "category_id": index_of[entry["class_id"]],
            "resolution_id": resolution.id,
            "resolution_version": resolution.version,
            "origin": FULL_IMAGE_ORIGIN if item.target_key is None else TARGET_ORIGIN,
        }
        if item.target_key is not None:
            annotation["roi_id"] = item.id
        geometry = entry.get("geometry")
        if geometry is not None and geometry["type"] == "rectangle":
            annotation["bbox"] = list(geometry["coordinates"])
        elif geometry is not None:
            annotation["segmentation"] = [
                list(ring) for ring in geometry["coordinates"]
            ]
            annotation["bbox"] = _bounds(geometry["coordinates"])
        annotations.append(annotation)
    return annotations


def _roi(
    item: BatchItem, resolution: ResolvedAnnotation, iteration: int | None
) -> dict[str, Any]:
    """Describe the query history of one answered object target."""
    x, y, width, height = item.target_region
    return {
        "roi_id": item.id,
        "bbox_xyxy": [x, y, x + width, y + height],
        "al_iteration": iteration,
        "resolution": CONFIRMED_OBJECT
        if resolution.objects
        else EXPLICIT_HARD_NEGATIVE,
    }


def _manifest(
    project: Project,
    role: str,
    classes: list[dict[str, Any]],
    images: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble a manifest in the shared format."""
    return {
        "info": {
            "schema": MANIFEST_SCHEMA,
            "project_id": project.id,
            "task": project.task_type,
            "role": role,
        },
        "categories": classes,
        "images": images,
        "annotations": annotations,
    }


def _resolved(project: Project, purposes: Sequence[str]):
    """Select every resolved item of some purposes with its image, current
    resolution, and the acquisition iteration that chose it."""
    return (
        select(
            Media, ContentObject, BatchItem, ResolvedAnnotation, LearningRun.iteration
        )
        .join(BatchItem, BatchItem.media_id == Media.id)
        .join(AnnotationBatch, AnnotationBatch.id == BatchItem.batch_id)
        .join(ContentObject, ContentObject.id == Media.content_object_id)
        .join(
            ResolvedAnnotation,
            and_(
                ResolvedAnnotation.batch_item_id == BatchItem.id,
                ResolvedAnnotation.superseded_at.is_(None),
            ),
        )
        .outerjoin(LearningRun, LearningRun.id == AnnotationBatch.model_run_id)
        .where(
            AnnotationBatch.project_id == project.id,
            AnnotationBatch.purpose.in_(purposes),
            BatchItem.status == ItemStatus.resolved,
        )
        .order_by(Media.relative_path, Media.id, BatchItem.position, BatchItem.id)
    )


def _describe(
    media: Media,
    content: ContentObject,
    answered: list[tuple[BatchItem, ResolvedAnnotation, int | None]],
    index_of: dict[str, int],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Describe one image from its answered items: exhaustive when a whole
    image was annotated, partial when only object targets were (D16)."""
    status = PARTIALLY_LABELED if answered else UNLABELED
    if any(item.target_key is None for item, _, _ in answered):
        status = EXHAUSTIVELY_LABELED
    image = _image(media, content, status)
    annotations = []
    for item, resolution, iteration in answered:
        if item.target_key is not None:
            image["queried_rois"].append(_roi(item, resolution, iteration))
        annotations.extend(_annotations(resolution, item, index_of))
    return image, annotations


async def accepted(session: AsyncSession, project: Project, role: str) -> dict:
    """Return the manifest of one role's images with accepted resolutions.

    Args:
        session: Active database session.
        project: Project being snapshotted.
        role: ``training``, ``validation``, or ``test``.

    Returns:
        The manifest, images ordered by relative path.
    """
    classes = await categories(session, project)
    index_of = {item["class_id"]: item["id"] for item in classes}
    rows = await session.execute(_resolved(project, ROLE_PURPOSES[role]))
    images: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    for _, group in groupby(rows, key=lambda row: row[0].id):
        group = list(group)
        media, content = group[0][0], group[0][1]
        image, found = _describe(
            media,
            content,
            [
                (item, resolution, iteration)
                for _, _, item, resolution, iteration in group
            ],
            index_of,
        )
        images.append(image)
        annotations.extend(found)
    return _manifest(project, role, classes, images, annotations)


async def pool(
    session: AsyncSession, project: Project, media_ids: Sequence[str]
) -> dict[str, Any]:
    """Return the manifest of the eligible media.

    An image whose object targets were already answered stays eligible and
    carries those answers and their regions, so a solution can avoid asking
    the same question twice (D16).

    Args:
        session: Active database session.
        project: Project being snapshotted.
        media_ids: Eligible media identifiers.

    Returns:
        The manifest, images ordered by relative path.
    """
    classes = await categories(session, project)
    index_of = {item["class_id"]: item["id"] for item in classes}
    answered: dict[str, list[tuple[BatchItem, ResolvedAnnotation, int | None]]] = {}
    for _, _, item, resolution, iteration in await session.execute(
        _resolved(project, ROLE_PURPOSES["training"]).where(
            Media.id.in_(list(media_ids)), BatchItem.target_key.is_not(None)
        )
    ):
        answered.setdefault(item.media_id, []).append((item, resolution, iteration))
    rows = await session.execute(
        select(Media, ContentObject)
        .join(ContentObject, ContentObject.id == Media.content_object_id)
        .where(Media.id.in_(list(media_ids)))
        .order_by(Media.relative_path, Media.id)
    )
    images: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    for media, content in rows:
        image, found = _describe(media, content, answered.get(media.id, []), index_of)
        images.append(image)
        annotations.extend(found)
    return _manifest(project, "pool", classes, images, annotations)


def write(project_id: str, manifest: dict[str, Any]) -> ManifestRef:
    """Persist a manifest once and return its reference.

    Args:
        project_id: Project owning the manifest.
        manifest: Manifest to persist.

    Returns:
        The digest of its canonical bytes and its key under the media root.
    """
    data = canonical_bytes(manifest)
    digest = hashlib.sha256(data).hexdigest()
    key = storage.learning_key(project_id, "snapshots", f"{digest}.json")
    storage.write_learning_file(key, data)
    return ManifestRef(sha256=digest, path=key)
