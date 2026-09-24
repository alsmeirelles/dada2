"""Owner/manager label imports: upload, validation, acceptance, and discard.

An import belongs to a prepared draft and snapshots the class-index map and
media inventory it was created against. Any change to either resets the
preparation and deletes the import, so the snapshot always describes the
current project while the import exists.
"""

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.core.config import get_settings
from dada_api.core.errors import ApiError
from dada_api.models.label_import import (
    AnnotationImport,
    AnnotationImportFile,
    ImportedSeedDocument,
    ImportFormat,
    ImportStatus,
)
from dada_api.models.media import ContentObject, Media
from dada_api.models.project import Project, ProjectClass
from dada_api.models.user import User
from dada_api.schemas.label_import import AnnotationImportCreate
from dada_api.services import audit, datasets, ingestion, label_formats, selection

TASK_FORMATS = {
    "detection": ImportFormat.yolo_detection,
    "segmentation": ImportFormat.coco_segmentation,
}
PARSERS = {
    ImportFormat.yolo_detection: (
        label_formats.parse_yolo_detection,
        label_formats.YOLO_PARSER_VERSION,
    ),
    ImportFormat.coco_segmentation: (
        label_formats.parse_coco_segmentation,
        label_formats.COCO_PARSER_VERSION,
    ),
}


def _import_conflict() -> ApiError:
    """Return the error for a project that already holds an import."""
    return ApiError(
        409,
        "import_already_exists",
        "The project already has a label import; discard it or reset the dataset.",
    )


async def create_import(
    session: AsyncSession,
    actor: User,
    project: Project,
    request: AnnotationImportCreate,
) -> AnnotationImport:
    """Open an import session for a prepared draft and record its manifest.

    Args:
        session: Active database session.
        actor: User creating the import.
        project: Authorized project.
        request: Validated format and file manifest.

    Returns:
        The persisted import.

    Raises:
        ApiError: 409 when the project is not a prepared draft or already has
            an import; 422 when the format does not fit the task or the
            manifest exceeds the advertised limits.
    """
    if project.status != "draft":
        raise ApiError(
            409,
            "project_not_draft",
            "Labels can only be imported into a draft project.",
            details={"status": project.status},
        )
    if project.dataset_prepared_at is None:
        raise ApiError(409, "dataset_not_prepared", "Prepare the dataset first.")
    if TASK_FORMATS.get(project.task_type) != request.format:
        raise ApiError(
            422,
            "import_not_supported",
            "This label format does not match the project's task.",
            details={"task_type": project.task_type},
        )

    settings = get_settings()
    if len(request.files) > settings.max_project_files:
        raise ApiError(
            422,
            "too_many_files",
            "The manifest exceeds the supported file count.",
            details={"limit": settings.max_project_files},
        )
    if any(
        entry.size_bytes > settings.max_import_file_bytes for entry in request.files
    ):
        raise ApiError(
            422,
            "file_too_large",
            "A label file exceeds the supported size.",
            details={"limit": settings.max_import_file_bytes},
        )
    client_ids = [entry.client_file_id for entry in request.files]
    if len(set(client_ids)) != len(client_ids):
        raise ApiError(
            422,
            "duplicate_client_file_id",
            "The manifest repeats a client file identifier.",
        )

    existing = await session.scalar(
        select(AnnotationImport.id).where(AnnotationImport.project_id == project.id)
    )
    if existing is not None:
        raise _import_conflict()

    classes = await session.execute(
        select(ProjectClass.display_order, ProjectClass.id).where(
            ProjectClass.project_id == project.id
        )
    )
    label_import = AnnotationImport(
        project_id=project.id,
        format=request.format,
        parser_version=PARSERS[ImportFormat(request.format)][1],
        status=ImportStatus.uploading,
        created_by=actor.id,
        class_index_map={str(order): class_id for order, class_id in classes},
        media_fingerprint=selection.fingerprint(
            await datasets.ordered_media_ids(session, project)
        ),
    )
    session.add(label_import)
    await session.flush()
    for entry in request.files:
        session.add(
            AnnotationImportFile(
                import_id=label_import.id,
                client_file_id=entry.client_file_id,
                relative_path=ingestion.printable(entry.relative_path),
                sha256=entry.sha256,
                size_bytes=entry.size_bytes,
            )
        )
    audit.record(
        session,
        actor,
        project.id,
        "label_import.created",
        "annotation_import",
        label_import.id,
        after={
            "format": request.format,
            "parser_version": label_import.parser_version,
            "files": len(request.files),
        },
    )
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise _import_conflict() from error
    await session.refresh(label_import)
    return label_import


async def list_files(
    session: AsyncSession,
    label_import: AnnotationImport,
) -> list[tuple[str, str, int, str, bool]]:
    """Return an import's files without their content, in manifest order.

    Returns:
        Client identifier, relative path, size, digest, and whether received.
    """
    rows = await session.execute(
        select(
            AnnotationImportFile.client_file_id,
            AnnotationImportFile.relative_path,
            AnnotationImportFile.size_bytes,
            AnnotationImportFile.sha256,
            AnnotationImportFile.received_at,
        )
        .where(AnnotationImportFile.import_id == label_import.id)
        .order_by(AnnotationImportFile.client_file_id)
    )
    return [
        (client_id, path, size, digest, received_at is not None)
        for client_id, path, size, digest, received_at in rows
    ]


def _require_open(label_import: AnnotationImport) -> None:
    """Refuse to change an import that has already been accepted.

    Raises:
        ApiError: 409 when the import is accepted.
    """
    if label_import.status == ImportStatus.accepted:
        raise ApiError(
            409,
            "import_accepted",
            "An accepted import is final; reset the dataset to replace it.",
        )


async def store_file(
    session: AsyncSession,
    label_import: AnnotationImport,
    client_file_id: str,
    data: bytes,
) -> AnnotationImportFile:
    """Receive one whole label file and verify it against the manifest.

    Sending identical bytes again is accepted as a retry.

    Args:
        session: Active database session.
        label_import: Import receiving the file.
        client_file_id: Client identifier from the manifest.
        data: The complete file content.

    Returns:
        The received file.

    Raises:
        ApiError: 404 when the manifest has no such file, 409 when the import
            is no longer uploading, 422 when the bytes do not match the
            declared size and digest.
    """
    if label_import.status != ImportStatus.uploading:
        raise ApiError(
            409,
            "import_not_uploading",
            "The import no longer accepts files.",
            details={"status": label_import.status},
        )
    item = await session.scalar(
        select(AnnotationImportFile).where(
            AnnotationImportFile.import_id == label_import.id,
            AnnotationImportFile.client_file_id == client_file_id,
        )
    )
    if item is None:
        raise ApiError(404, "not_found", "The import file does not exist.")
    if len(data) != item.size_bytes or hashlib.sha256(data).hexdigest() != item.sha256:
        raise ApiError(
            422,
            "checksum_mismatch",
            "The file does not match its declared size and checksum.",
        )

    if item.content is None:
        item.content = data
        item.received_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(item)
    return item


async def _parse(
    session: AsyncSession,
    label_import: AnnotationImport,
) -> tuple[label_formats.ParseResult, int, dict[str, str]]:
    """Run the import's parser over its stored files.

    Returns:
        The parse result, the project's media count, and client file
        identifiers keyed by stored file identifier.
    """
    media_rows = await session.execute(
        select(Media.relative_path, Media.id, ContentObject.width, ContentObject.height)
        .join(ContentObject, ContentObject.id == Media.content_object_id)
        .where(Media.project_id == label_import.project_id)
    )
    media_index = {
        path: label_formats.MediaTarget(media_id, width, height)
        for path, media_id, width, height in media_rows
    }
    files = list(
        await session.scalars(
            select(AnnotationImportFile)
            .where(AnnotationImportFile.import_id == label_import.id)
            .order_by(AnnotationImportFile.client_file_id)
        )
    )
    parser = PARSERS[ImportFormat(label_import.format)][0]
    result = parser(
        [
            label_formats.SourceFile(item.id, item.relative_path, item.content or b"")
            for item in files
        ],
        media_index,
        {
            int(order): class_id
            for order, class_id in label_import.class_index_map.items()
        },
    )
    client_ids = {item.id: item.client_file_id for item in files}
    return result, len(media_index), client_ids


async def validate(
    session: AsyncSession,
    actor: User,
    label_import: AnnotationImport,
) -> AnnotationImport:
    """Parse every received file and record the review report.

    The import becomes ``validated`` when nothing is wrong and ``rejected``
    otherwise. A rejected import can only be discarded and started again.

    Args:
        session: Active database session.
        actor: User requesting the review.
        label_import: Import being validated.

    Returns:
        The import with its report.

    Raises:
        ApiError: 409 when the import is accepted or a file has not arrived.
    """
    _require_open(label_import)
    pending = [
        client_id
        for client_id, _, _, _, received in await list_files(session, label_import)
        if not received
    ]
    if pending:
        raise ApiError(
            409,
            "import_files_incomplete",
            "Some label files have not been uploaded.",
            details={"pending": pending},
        )

    result, media_count, client_ids = await _parse(session, label_import)
    labelled = len(result.documents)
    label_import.report = {
        "labelled_images": labelled,
        "objects": sum(
            len(document["objects"]) for _, document in result.documents.values()
        ),
        "unlabelled_images": media_count - labelled,
        "errors": [
            {
                "code": error.code,
                "client_file_id": client_ids[error.file_id],
                "detail": error.detail,
            }
            for error in result.errors
        ],
    }
    label_import.status = (
        ImportStatus.rejected if result.errors else ImportStatus.validated
    )
    label_import.validated_at = datetime.now(UTC)
    audit.record(
        session,
        actor,
        label_import.project_id,
        "label_import.validated",
        "annotation_import",
        label_import.id,
        after={
            "status": label_import.status,
            "labelled_images": labelled,
            "errors": len(result.errors),
        },
    )
    await session.commit()
    await session.refresh(label_import)
    return label_import


async def accept(
    session: AsyncSession,
    actor: User,
    label_import: AnnotationImport,
) -> AnnotationImport:
    """Persist a validated import's seed documents.

    The stored files are parsed again rather than trusting an earlier
    preview; the parse is a pure function of those files and the snapshot.

    Args:
        session: Active database session.
        actor: User accepting the import.
        label_import: Import being accepted.

    Returns:
        The accepted import.

    Raises:
        ApiError: 409 unless the import is ``validated``.
    """
    if label_import.status != ImportStatus.validated:
        raise ApiError(
            409,
            "import_not_valid",
            "Only a validated import without errors can be accepted.",
            details={"status": label_import.status},
        )

    result, _, _ = await _parse(session, label_import)
    for media_id, (file_id, document) in result.documents.items():
        session.add(
            ImportedSeedDocument(
                import_id=label_import.id,
                media_id=media_id,
                source_file_id=file_id,
                document=document,
            )
        )
    label_import.status = ImportStatus.accepted
    label_import.accepted_at = datetime.now(UTC)
    audit.record(
        session,
        actor,
        label_import.project_id,
        "label_import.accepted",
        "annotation_import",
        label_import.id,
        after={"seeded_images": len(result.documents)},
    )
    await session.commit()
    await session.refresh(label_import)
    return label_import


async def discard(
    session: AsyncSession,
    actor: User,
    label_import: AnnotationImport,
) -> None:
    """Delete an import that has not been accepted.

    Args:
        session: Active database session.
        actor: User discarding the import.
        label_import: Import being discarded.

    Raises:
        ApiError: 409 when the import is accepted.
    """
    _require_open(label_import)
    audit.record(
        session,
        actor,
        label_import.project_id,
        "label_import.discarded",
        "annotation_import",
        label_import.id,
        before={"status": label_import.status, "format": label_import.format},
    )
    await session.delete(label_import)
    await session.commit()
