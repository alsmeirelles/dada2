"""Manifest validation, resumable chunk intake, and promotion into media."""

import hashlib
import logging
import unicodedata
from datetime import UTC, datetime, timedelta

from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.config import get_settings
from dada_api.core.cursors import decode_cursor, encode_cursor
from dada_api.core.errors import ApiError
from dada_api.models.media import ContentObject, Media
from dada_api.models.project import Project
from dada_api.models.upload import (
    UploadChunk,
    UploadDisposition,
    UploadItem,
    UploadSession,
    UploadStatus,
)
from dada_api.schemas.upload import UploadSessionCreate
from dada_api.services import storage

logger = logging.getLogger(__name__)

PAGE_SIZE = 200
READ_BLOCK_BYTES = 1024 * 1024
DIGEST_BATCH_SIZE = 1000


def normalize_relative_path(raw: str) -> str | None:
    """Return the canonical form of a client relative path, or None if unsafe.

    Unicode is normalised to NFC so that two spellings of the same name collide
    instead of creating two dataset entries for one file.

    Args:
        raw: Relative path as sent by the client.

    Returns:
        The normalised path, or None when it is absolute, escapes the root, or
        carries control characters.
    """
    candidate = unicodedata.normalize("NFC", raw).replace("\\", "/").strip()
    if not candidate or candidate.startswith("/"):
        return None
    if any(ord(character) < 32 for character in candidate):
        return None

    segments = candidate.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        return None
    if ":" in segments[0]:
        return None
    return "/".join(segments)


def _printable(value: str) -> str:
    """Return a value safe to persist, dropping control characters.

    A rejected entry still records what the client sent so an operator can see
    it, but PostgreSQL refuses NUL bytes outright, so an unsafe name must never
    reach a query parameter verbatim.
    """
    return "".join(character for character in value if ord(character) >= 32)


def _ensure_active(upload: UploadSession) -> None:
    """Raise when a session can no longer accept work.

    Args:
        upload: Session being used.

    Raises:
        ApiError: 409 when the session is finished or past its expiry.
    """
    if upload.status in (UploadStatus.completed, UploadStatus.failed):
        raise ApiError(
            409,
            "upload_not_active",
            "The upload session is already finished.",
            details={"status": upload.status},
        )
    if upload.expires_at <= datetime.now(UTC):
        raise ApiError(409, "upload_session_expired", "The upload session has expired.")


async def list_items(session: AsyncSession, upload: UploadSession) -> list[UploadItem]:
    """Return a session's items in a deterministic order."""
    return list(
        await session.scalars(
            select(UploadItem)
            .where(UploadItem.session_id == upload.id)
            .order_by(UploadItem.created_at, UploadItem.id)
        )
    )


async def create_session(
    session: AsyncSession,
    project: Project,
    request: UploadSessionCreate,
) -> UploadSession:
    """Create an upload session and classify every manifest entry.

    Args:
        session: Active database session.
        project: Authorized project.
        request: Validated manifest.

    Returns:
        The persisted session with its classified items.

    Raises:
        ApiError: 422 when the manifest exceeds the advertised file count or
            repeats a client file identifier.
    """
    settings = get_settings()
    if len(request.files) > settings.max_project_files:
        raise ApiError(
            422,
            "too_many_files",
            "The manifest exceeds the supported file count.",
            details={"limit": settings.max_project_files},
        )

    client_ids = [entry.client_file_id for entry in request.files]
    if len(set(client_ids)) != len(client_ids):
        raise ApiError(
            422,
            "duplicate_client_file_id",
            "The manifest repeats a client file identifier.",
        )

    upload = UploadSession(
        project_id=project.id,
        status=UploadStatus.pending,
        expires_at=datetime.now(UTC)
        + timedelta(hours=settings.upload_session_ttl_hours),
    )
    session.add(upload)
    await session.flush()

    stored = await _stored_digests(session, project, request)
    allowed_types = settings.image_media_types
    seen_paths: set[str] = set()

    for entry in request.files:
        normalized = normalize_relative_path(entry.relative_path)
        reason: str | None = None
        if normalized is None or normalized in seen_paths:
            reason = "invalid_relative_path"
        elif entry.media_type.lower() not in allowed_types:
            reason = "unsupported_media_type"
        elif entry.size_bytes > settings.max_file_bytes:
            reason = "file_too_large"

        if normalized is not None:
            seen_paths.add(normalized)

        if reason is not None:
            disposition = UploadDisposition.rejected
        elif (entry.sha256, entry.size_bytes) in stored:
            disposition = UploadDisposition.already_present
        else:
            disposition = UploadDisposition.upload_required

        session.add(
            UploadItem(
                session_id=upload.id,
                client_file_id=entry.client_file_id,
                relative_path=normalized or _printable(entry.relative_path),
                file_name=_printable(entry.file_name),
                media_type=entry.media_type.lower(),
                size_bytes=entry.size_bytes,
                sha256=entry.sha256,
                disposition=disposition,
                rejection_reason=reason,
                received_bytes=0,
            )
        )

    await session.commit()
    await session.refresh(upload)
    return upload


async def _stored_digests(
    session: AsyncSession,
    project: Project,
    request: UploadSessionCreate,
) -> set[tuple[str, int]]:
    """Return which of the manifest's digests the project already stores.

    The lookup is batched because a manifest may carry as many files as
    ``max_project_files`` advertises, which is far above the number of bind
    parameters a single statement accepts.
    """
    digests = [entry.sha256 for entry in request.files]
    found: set[tuple[str, int]] = set()
    for start in range(0, len(digests), DIGEST_BATCH_SIZE):
        rows = await session.execute(
            select(ContentObject.sha256, ContentObject.size_bytes).where(
                ContentObject.project_id == project.id,
                ContentObject.sha256.in_(digests[start : start + DIGEST_BATCH_SIZE]),
            )
        )
        found.update((digest, size) for digest, size in rows)
    return found


async def get_item(
    session: AsyncSession,
    upload: UploadSession,
    client_file_id: str,
) -> UploadItem:
    """Return one item of a session by its client identifier.

    Raises:
        ApiError: 404 when the session has no such item.
    """
    item = await session.scalar(
        select(UploadItem).where(
            UploadItem.session_id == upload.id,
            UploadItem.client_file_id == client_file_id,
        )
    )
    if item is None:
        raise ApiError(404, "not_found", "The upload item does not exist.")
    return item


async def store_chunk(
    session: AsyncSession,
    upload: UploadSession,
    item: UploadItem,
    byte_offset: int,
    checksum: str,
    data: bytes,
) -> UploadItem:
    """Verify and persist one chunk, advancing the item's accepted offset.

    Args:
        session: Active database session.
        upload: Session receiving the chunk.
        item: Item the chunk belongs to.
        byte_offset: Offset the chunk starts at.
        checksum: Digest the client computed for these bytes.
        data: Raw chunk bytes.

    Returns:
        The item with its updated accepted offset.

    Raises:
        ApiError: 409 when the session is inactive, the file was rejected, or
            the offset does not continue the item; 422 when the chunk checksum
            fails or the upload exceeds the declared size.
    """
    _ensure_active(upload)
    if item.disposition == UploadDisposition.rejected:
        raise ApiError(
            409,
            "file_rejected",
            "The manifest check rejected this file.",
            details={"reason": item.rejection_reason},
        )

    digest = hashlib.sha256(data).hexdigest()
    if digest != checksum:
        raise ApiError(
            422, "checksum_mismatch", "The chunk does not match its checksum."
        )

    if byte_offset != item.received_bytes:
        accepted = await session.scalar(
            select(UploadChunk).where(
                UploadChunk.item_id == item.id,
                UploadChunk.byte_offset == byte_offset,
            )
        )
        if accepted is not None and accepted.checksum == digest:
            return item
        raise ApiError(
            409,
            "offset_mismatch",
            "The chunk does not continue from the accepted offset.",
            details={"expected_offset": item.received_bytes},
        )

    if byte_offset + len(data) > item.size_bytes:
        raise ApiError(
            422,
            "file_too_large",
            "The upload exceeds the declared file size.",
            details={"size_bytes": item.size_bytes},
        )

    storage.write_chunk(upload.id, item.id, byte_offset, data)
    session.add(
        UploadChunk(
            item_id=item.id,
            byte_offset=byte_offset,
            byte_length=len(data),
            checksum=digest,
        )
    )
    item.received_bytes = byte_offset + len(data)
    upload.status = UploadStatus.uploading
    await session.commit()
    await session.refresh(item)
    return item


async def complete_session(
    session: AsyncSession,
    upload: UploadSession,
) -> UploadSession:
    """Verify every uploaded file and promote it into the project's media.

    Repeating the call on a completed session returns it unchanged.

    Args:
        session: Active database session.
        upload: Session being completed.

    Returns:
        The session in its final state.

    Raises:
        ApiError: 409 when a required file is still incomplete; 422 when a
            file fails verification.
    """
    if upload.status == UploadStatus.completed:
        return upload

    _ensure_active(upload)
    items = await list_items(session, upload)
    outstanding = [
        item.client_file_id
        for item in items
        if item.disposition == UploadDisposition.upload_required
        and item.received_bytes < item.size_bytes
    ]
    if outstanding:
        raise ApiError(
            409,
            "upload_not_complete",
            "Some files have not been fully uploaded.",
            details={"pending": outstanding},
        )

    upload.status = UploadStatus.processing
    await session.commit()

    try:
        for item in items:
            if item.disposition == UploadDisposition.rejected:
                continue
            content = await _content_object_for(session, upload, item)
            await _ensure_media(session, upload, content, item.relative_path)
    except ApiError as error:
        await session.rollback()
        upload.status = UploadStatus.failed
        upload.error = {"code": error.code, "message": error.message}
        await session.commit()
        raise

    upload.status = UploadStatus.completed
    await session.commit()
    _purge_parts(upload.id)
    await session.refresh(upload)
    return upload


async def _content_object_for(
    session: AsyncSession,
    upload: UploadSession,
    item: UploadItem,
) -> ContentObject:
    """Return the project's content object for an item, promoting it if new."""
    existing = await session.scalar(
        select(ContentObject).where(
            ContentObject.project_id == upload.project_id,
            ContentObject.sha256 == item.sha256,
            ContentObject.size_bytes == item.size_bytes,
        )
    )
    if existing is not None:
        return existing

    _verify_part(upload, item)
    width, height = _read_dimensions(upload, item)
    storage_key = storage.media_storage_key(upload.project_id, item.sha256)
    storage.promote_part(upload.id, item.id, storage_key)

    content = ContentObject(
        project_id=upload.project_id,
        sha256=item.sha256,
        size_bytes=item.size_bytes,
        media_type=item.media_type,
        width=width,
        height=height,
        storage_key=storage_key,
    )
    session.add(content)
    await session.flush()
    return content


def _verify_part(upload: UploadSession, item: UploadItem) -> None:
    """Raise when stored bytes do not match the digest the client declared."""
    digest = hashlib.sha256()
    with storage.open_part(upload.id, item.id) as handle:
        for block in iter(lambda: handle.read(READ_BLOCK_BYTES), b""):
            digest.update(block)
    if digest.hexdigest() != item.sha256:
        raise ApiError(
            422,
            "checksum_mismatch",
            "The stored file does not match its declared checksum.",
            details={"client_file_id": item.client_file_id},
        )


def _read_dimensions(upload: UploadSession, item: UploadItem) -> tuple[int, int]:
    """Return an image's original pixel dimensions.

    Geometry is persisted in original-image coordinates in later phases, so the
    dimensions recorded here are what makes those annotations meaningful.
    """
    try:
        with storage.open_part(upload.id, item.id) as handle:
            with Image.open(handle) as image:
                return image.width, image.height
    except OSError as error:
        raise ApiError(
            422,
            "invalid_image",
            "The file could not be read as an image.",
            details={"client_file_id": item.client_file_id},
        ) from error


async def _ensure_media(
    session: AsyncSession,
    upload: UploadSession,
    content: ContentObject,
    relative_path: str,
) -> None:
    """Record the content's appearance at a path unless it is already recorded."""
    existing = await session.scalar(
        select(Media).where(
            Media.project_id == upload.project_id,
            Media.relative_path == relative_path,
        )
    )
    if existing is None:
        session.add(
            Media(
                project_id=upload.project_id,
                content_object_id=content.id,
                relative_path=relative_path,
            )
        )


async def cancel_session(session: AsyncSession, upload: UploadSession) -> None:
    """Abort a session and purge every part it has not promoted.

    Args:
        session: Active database session.
        upload: Session being cancelled.

    Raises:
        ApiError: 409 when the session already completed.
    """
    if upload.status == UploadStatus.completed:
        raise ApiError(
            409, "upload_not_active", "A completed session cannot be cancelled."
        )

    upload_id = upload.id
    await session.delete(upload)
    await session.commit()
    _purge_parts(upload_id)


def _purge_parts(upload_id: str) -> None:
    """Remove a session's temporary parts, logging a failure without raising.

    The database change is already committed by the time this runs. Turning a
    storage failure into a request failure would misreport work that did
    succeed, so the failure is logged for operators instead.
    """
    try:
        storage.delete_session_parts(upload_id)
    except OSError:
        logger.error("Failed to purge upload parts for session %s", upload_id)


async def count_media(session: AsyncSession, project: Project) -> int:
    """Return how many images a project has ingested."""
    return (
        await session.scalar(
            select(func.count())
            .select_from(Media)
            .where(Media.project_id == project.id)
        )
        or 0
    )


async def list_media(
    session: AsyncSession,
    project: Project,
    cursor: str | None,
) -> tuple[list[tuple[Media, ContentObject]], str | None]:
    """List a project's media in a deterministic order.

    Args:
        session: Active database session.
        project: Authorized project.
        cursor: Opaque cursor from a previous page.

    Returns:
        The page of media with their content, and the next cursor if any.
    """
    query = (
        select(Media, ContentObject)
        .join(ContentObject, Media.content_object_id == ContentObject.id)
        .where(Media.project_id == project.id)
        .order_by(Media.relative_path, Media.id)
    )
    if cursor is not None:
        position = decode_cursor(cursor)
        query = query.where(Media.relative_path > str(position["path"]))

    rows = [tuple(row) for row in await session.execute(query.limit(PAGE_SIZE + 1))]
    if len(rows) <= PAGE_SIZE:
        return rows, None
    page = rows[:PAGE_SIZE]
    return page, encode_cursor({"path": page[-1][0].relative_path})
