"""Filesystem storage for in-flight upload parts and promoted project media.

This module is the only place that touches the storage medium. Replacing it
with an object-store implementation must not require changing any route,
schema, or service that calls it.

Paths are built exclusively from server-generated identifiers and verified
digests. No client-supplied file name or relative path ever reaches the
filesystem.
"""

import os
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from dada_api.core.config import get_settings

HEIF_MEDIA_TYPES = frozenset({"image/heic", "image/heif"})
RENDITION_VERSION = "v1"
RENDITION_MEDIA_TYPE = "image/webp"
LEARNING_DIRECTORY = "learning"


def _resolve_within(root: Path, *parts: str) -> Path:
    """Join path parts under a root and refuse anything that escapes it.

    Args:
        root: Configured storage root.
        *parts: Path components to append.

    Returns:
        The resolved absolute path.

    Raises:
        ValueError: When the resolved path falls outside the root.
    """
    candidate = root.joinpath(*parts).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("The resolved storage path escapes its configured root.")
    return candidate


def part_path(session_id: str, item_id: str) -> Path:
    """Return the filesystem path holding one item's uploaded bytes."""
    return _resolve_within(get_settings().upload_parts_root, session_id, item_id)


def media_storage_key(project_id: str, sha256: str) -> str:
    """Return the storage key for verified content belonging to a project.

    The two-level digest fan-out keeps directory entry counts manageable at the
    project file limit the API advertises.

    Args:
        project_id: Project owning the content.
        sha256: Verified lowercase hex digest of the content.

    Returns:
        The storage key, relative to the media root.
    """
    return f"{project_id}/{sha256[:2]}/{sha256[2:4]}/{sha256}"


def rendition_storage_key(project_id: str, sha256: str) -> str:
    """Return the key of the lossless WebP rendition of an HEIC/HEIF source.

    The key derives from the project, the source digest, and the rendition
    version (P7-06), so deduplicated sources share one rendition and no
    database column is needed.

    Args:
        project_id: Project owning the content.
        sha256: Verified digest of the source.

    Returns:
        The storage key, relative to the media root.
    """
    return f"{project_id}/renders/{RENDITION_VERSION}/{sha256}.webp"


def display_key(project_id: str, sha256: str, media_type: str, storage_key: str) -> str:
    """Return the key of the bytes browsers, workers, and exports use.

    Args:
        project_id: Project owning the content.
        sha256: Verified digest of the source.
        media_type: Media type of the source.
        storage_key: Key of the source.

    Returns:
        The rendition key for an HEIC/HEIF source, otherwise the source key.
    """
    if media_type in HEIF_MEDIA_TYPES:
        return rendition_storage_key(project_id, sha256)
    return storage_key


def media_path(storage_key: str) -> Path:
    """Return the filesystem path of a media key."""
    return _resolve_within(get_settings().media_root, storage_key)


def write_media(storage_key: str, writer: Callable[[Path], None]) -> None:
    """Create a media file atomically unless it already exists.

    The writer fills a temporary file in the destination folder, which is
    then renamed into place, so a reader never sees a partial file.

    Args:
        storage_key: Destination key.
        writer: Callable writing the complete file at the path it receives.
    """
    target = media_path(storage_key)
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        writer(temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def learning_key(project_id: str, *parts: str) -> str:
    """Return a key inside a project's learning folder.

    Args:
        project_id: Project owning the folder.
        *parts: Path components inside it.

    Returns:
        The key, relative to the media root.
    """
    return "/".join((project_id, LEARNING_DIRECTORY, *parts))


def write_learning_file(storage_key: str, data: bytes) -> None:
    """Write an immutable learning file atomically unless it already exists."""
    write_media(storage_key, lambda path: path.write_bytes(data))


def delete_learning_folder(storage_key: str) -> None:
    """Remove a learning folder and everything in it, when present."""
    path = media_path(storage_key)
    if path.exists():
        shutil.rmtree(path)


def write_chunk(session_id: str, item_id: str, byte_offset: int, data: bytes) -> None:
    """Write one byte range of an upload item at the given offset.

    Args:
        session_id: Upload session owning the item.
        item_id: Server-generated upload item identifier.
        byte_offset: Offset the range starts at.
        data: Raw bytes to store.
    """
    path = part_path(session_id, item_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "r+b" if path.exists() else "wb") as handle:
        handle.seek(byte_offset)
        handle.write(data)


def part_size(session_id: str, item_id: str) -> int:
    """Return how many bytes of an upload item are stored, zero when absent."""
    path = part_path(session_id, item_id)
    return path.stat().st_size if path.exists() else 0


@contextmanager
def open_part(session_id: str, item_id: str) -> Iterator[BinaryIO]:
    """Open an upload item's stored bytes for reading."""
    with open(part_path(session_id, item_id), "rb") as handle:
        yield handle


def promote_part(session_id: str, item_id: str, storage_key: str) -> None:
    """Move a verified upload part into its permanent media location.

    ``shutil.move`` is used rather than a rename because the parts root and the
    media root are separately configured and may be different filesystems.

    Args:
        session_id: Upload session owning the item.
        item_id: Server-generated upload item identifier.
        storage_key: Destination key from :func:`media_storage_key`.
    """
    target = _resolve_within(get_settings().media_root, storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(part_path(session_id, item_id)), str(target))


def iter_media(storage_key: str, chunk_bytes: int = 1024 * 1024) -> Iterator[bytes]:
    """Yield a promoted media file's bytes in chunks, closing it when done.

    Args:
        storage_key: Key from :func:`media_storage_key`.
        chunk_bytes: Size of each yielded chunk.

    Yields:
        Consecutive byte ranges of the stored file.
    """
    with open(_resolve_within(get_settings().media_root, storage_key), "rb") as handle:
        while chunk := handle.read(chunk_bytes):
            yield chunk


def delete_session_parts(session_id: str) -> None:
    """Remove every stored part of an upload session."""
    path = _resolve_within(get_settings().upload_parts_root, session_id)
    if path.exists():
        shutil.rmtree(path)


def delete_project_media(project_id: str) -> None:
    """Remove every stored media file belonging to a project."""
    path = _resolve_within(get_settings().media_root, project_id)
    if path.exists():
        shutil.rmtree(path)
