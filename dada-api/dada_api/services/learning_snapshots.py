"""Immutable manifests of accepted annotations and eligible media (D3).

A manifest lists images by their display bytes and canonical dimensions and
annotations taken only from current accepted resolutions. It is written once
under the project's learning folder and named by the digest of its canonical
JSON, so the same content always yields the same file.
"""

import hashlib
from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.active_learning.contract import (
    MANIFEST_SCHEMA,
    ManifestRef,
    canonical_bytes,
)
from dada_api.models.annotation import ResolvedAnnotation
from dada_api.models.batch import AnnotationBatch, BatchItem, BatchPurpose, ItemStatus
from dada_api.models.media import ContentObject, Media
from dada_api.models.project import Project, ProjectClass
from dada_api.services import storage

ROLE_PURPOSES = {
    "training": (BatchPurpose.initial_training, BatchPurpose.acquisition),
    "validation": (BatchPurpose.validation,),
    "test": (BatchPurpose.test,),
}
EXHAUSTIVE = "EXHAUSTIVELY_LABELED"
UNLABELED = "UNLABELED"
FULL_IMAGE_ORIGIN = "FULL_IMAGE"


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
    resolution: ResolvedAnnotation, media_id: str, index_of: dict[str, int]
) -> list[dict[str, Any]]:
    """Convert one accepted resolution's objects into manifest annotations."""
    annotations = []
    for position, item in enumerate(resolution.objects):
        entry: dict[str, Any] = {
            "id": f"{resolution.id}:{position}",
            "image_id": media_id,
            "category_id": index_of[item["class_id"]],
            "resolution_id": resolution.id,
            "resolution_version": resolution.version,
            "origin": FULL_IMAGE_ORIGIN,
        }
        geometry = item.get("geometry")
        if geometry is not None and geometry["type"] == "rectangle":
            entry["bbox"] = list(geometry["coordinates"])
        elif geometry is not None:
            entry["segmentation"] = [list(ring) for ring in geometry["coordinates"]]
            entry["bbox"] = _bounds(geometry["coordinates"])
        annotations.append(entry)
    return annotations


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
    rows = await session.execute(
        select(Media, ContentObject, ResolvedAnnotation)
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
        .where(
            AnnotationBatch.project_id == project.id,
            AnnotationBatch.purpose.in_(ROLE_PURPOSES[role]),
            BatchItem.status == ItemStatus.resolved,
        )
        .order_by(Media.relative_path, Media.id, ResolvedAnnotation.id)
    )
    images: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    for media, content, resolution in rows:
        if not images or images[-1]["id"] != media.id:
            images.append(_image(media, content, EXHAUSTIVE))
        annotations.extend(_annotations(resolution, media.id, index_of))
    return _manifest(project, role, classes, images, annotations)


async def pool(
    session: AsyncSession, project: Project, media_ids: Sequence[str]
) -> dict[str, Any]:
    """Return the manifest of the eligible unlabeled media.

    Args:
        session: Active database session.
        project: Project being snapshotted.
        media_ids: Eligible media identifiers.

    Returns:
        The manifest, images ordered by relative path, without annotations.
    """
    rows = await session.execute(
        select(Media, ContentObject)
        .join(ContentObject, ContentObject.id == Media.content_object_id)
        .where(Media.id.in_(list(media_ids)))
        .order_by(Media.relative_path, Media.id)
    )
    images = [_image(media, content, UNLABELED) for media, content in rows]
    return _manifest(project, "pool", await categories(session, project), images, [])


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
