"""Filesystem storage for in-flight upload parts and promoted project media.

This module is the only place that touches the storage medium. Replacing it
with an object-store implementation must not require changing any route,
schema, or service that calls it.

Paths are built exclusively from server-generated identifiers and verified
digests. No client-supplied file name or relative path ever reaches the
filesystem.
"""

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from dada_api.core.config import get_settings


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


def _part_path(session_id: str, item_id: str) -> Path:
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


def write_chunk(session_id: str, item_id: str, byte_offset: int, data: bytes) -> None:
    """Write one byte range of an upload item at the given offset.

    Args:
        session_id: Upload session owning the item.
        item_id: Server-generated upload item identifier.
        byte_offset: Offset the range starts at.
        data: Raw bytes to store.
    """
    path = _part_path(session_id, item_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "r+b" if path.exists() else "wb") as handle:
        handle.seek(byte_offset)
        handle.write(data)


def part_size(session_id: str, item_id: str) -> int:
    """Return how many bytes of an upload item are stored, zero when absent."""
    path = _part_path(session_id, item_id)
    return path.stat().st_size if path.exists() else 0


@contextmanager
def open_part(session_id: str, item_id: str) -> Iterator[BinaryIO]:
    """Open an upload item's stored bytes for reading."""
    with open(_part_path(session_id, item_id), "rb") as handle:
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
    shutil.move(str(_part_path(session_id, item_id)), str(target))


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
