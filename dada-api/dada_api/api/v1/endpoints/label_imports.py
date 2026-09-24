"""Owner/manager label import routes for prepared draft projects."""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import (
    get_current_user,
    require_import_action,
    require_project_action,
)
from dada_api.db.session import get_session
from dada_api.models.label_import import AnnotationImport
from dada_api.models.project import Project
from dada_api.models.user import User
from dada_api.schemas.label_import import (
    AnnotationImportCreate,
    AnnotationImportResponse,
    ImportFileResponse,
)
from dada_api.services import label_imports as import_service
from dada_api.services.authorization import ProjectAction

router = APIRouter()


async def _represent(
    session: AsyncSession,
    label_import: AnnotationImport,
) -> AnnotationImportResponse:
    """Build an import response with its files and review report."""
    files = await import_service.list_files(session, label_import)
    return AnnotationImportResponse(
        id=label_import.id,
        project_id=label_import.project_id,
        format=label_import.format,
        parser_version=label_import.parser_version,
        status=label_import.status,
        created_by=label_import.created_by,
        report=label_import.report,
        files=[
            ImportFileResponse(
                client_file_id=client_id,
                relative_path=path,
                size_bytes=size,
                sha256=digest,
                received=received,
            )
            for client_id, path, size, digest, received in files
        ],
        created_at=label_import.created_at,
        validated_at=label_import.validated_at,
        accepted_at=label_import.accepted_at,
    )


@router.post(
    "/projects/{project_id}/annotation-imports",
    response_model=AnnotationImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_annotation_import(
    request: AnnotationImportCreate,
    project: Project = Depends(require_project_action(ProjectAction.update_project)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AnnotationImportResponse:
    """Open a label import for a prepared draft.

    Args:
        request: Validated format and file manifest.
        project: Project resolved and authorized by the dependency.
        user: Authenticated user recorded as the actor.
        session: Active database session.

    Returns:
        The created import with its manifest.
    """
    label_import = await import_service.create_import(session, user, project, request)
    return await _represent(session, label_import)


@router.get("/annotation-imports/{import_id}", response_model=AnnotationImportResponse)
async def read_annotation_import(
    label_import: AnnotationImport = Depends(
        require_import_action(ProjectAction.update_project)
    ),
    session: AsyncSession = Depends(get_session),
) -> AnnotationImportResponse:
    """Return an import's status, files, and report so a client can resume.

    Args:
        label_import: Import resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The import representation.
    """
    return await _represent(session, label_import)


@router.post(
    "/annotation-imports/{import_id}/files/{client_file_id}",
    response_model=ImportFileResponse,
)
async def upload_annotation_import_file(
    client_file_id: str,
    request: Request,
    label_import: AnnotationImport = Depends(
        require_import_action(ProjectAction.update_project)
    ),
    session: AsyncSession = Depends(get_session),
) -> ImportFileResponse:
    """Receive one whole label file, verified against the manifest.

    Args:
        client_file_id: Client identifier of the file from the manifest.
        request: Raw request carrying the file bytes.
        label_import: Import resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The received file.
    """
    item = await import_service.store_file(
        session, label_import, client_file_id, await request.body()
    )
    return ImportFileResponse(
        client_file_id=item.client_file_id,
        relative_path=item.relative_path,
        size_bytes=item.size_bytes,
        sha256=item.sha256,
        received=True,
    )


@router.post(
    "/annotation-imports/{import_id}/validate",
    response_model=AnnotationImportResponse,
)
async def validate_annotation_import(
    label_import: AnnotationImport = Depends(
        require_import_action(ProjectAction.update_project)
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AnnotationImportResponse:
    """Parse the import and return its path, class-index, and geometry report.

    Args:
        label_import: Import resolved and authorized by the dependency.
        user: Authenticated user recorded as the actor.
        session: Active database session.

    Returns:
        The import with its report.
    """
    validated = await import_service.validate(session, user, label_import)
    return await _represent(session, validated)


@router.post(
    "/annotation-imports/{import_id}/accept",
    response_model=AnnotationImportResponse,
)
async def accept_annotation_import(
    label_import: AnnotationImport = Depends(
        require_import_action(ProjectAction.update_project)
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AnnotationImportResponse:
    """Persist a validated import's immutable seed documents.

    Args:
        label_import: Import resolved and authorized by the dependency.
        user: Authenticated user recorded as the actor.
        session: Active database session.

    Returns:
        The accepted import.
    """
    accepted = await import_service.accept(session, user, label_import)
    return await _represent(session, accepted)


@router.delete(
    "/annotation-imports/{import_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def discard_annotation_import(
    label_import: AnnotationImport = Depends(
        require_import_action(ProjectAction.update_project)
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Discard an import that has not been accepted.

    Args:
        label_import: Import resolved and authorized by the dependency.
        user: Authenticated user recorded as the actor.
        session: Active database session.

    Returns:
        An empty response.
    """
    await import_service.discard(session, user, label_import)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
