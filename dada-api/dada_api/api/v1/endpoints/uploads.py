"""Resumable dataset ingestion routes."""

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import require_project_action, require_upload_action
from dada_api.db.session import get_session
from dada_api.models.project import Project
from dada_api.models.upload import UploadSession
from dada_api.schemas.upload import (
    UploadChunkResponse,
    UploadItemResponse,
    UploadSessionCreate,
    UploadSessionResponse,
)
from dada_api.services import ingestion
from dada_api.services.authorization import ProjectAction

router = APIRouter()

SHA256_HEX = r"^[0-9a-f]{64}$"


async def _session_response(
    session: AsyncSession,
    upload: UploadSession,
) -> UploadSessionResponse:
    """Build the session representation including per-file progress."""
    items = await ingestion.list_items(session, upload)
    return UploadSessionResponse(
        id=upload.id,
        status=upload.status,
        items=[
            UploadItemResponse(
                client_file_id=item.client_file_id,
                disposition=item.disposition,
                reason=item.rejection_reason,
                size_bytes=item.size_bytes,
                received_bytes=item.received_bytes,
            )
            for item in items
        ],
        error=upload.error,
        expires_at=upload.expires_at,
    )


@router.post(
    "/projects/{project_id}/uploads",
    response_model=UploadSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload_session(
    request: UploadSessionCreate,
    project: Project = Depends(require_project_action(ProjectAction.update_project)),
    session: AsyncSession = Depends(get_session),
) -> UploadSessionResponse:
    """Create an upload session and classify every file in the manifest.

    Args:
        request: Validated manifest describing the client's local files.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The created session with each file's disposition.
    """
    upload = await ingestion.create_session(session, project, request)
    return await _session_response(session, upload)


@router.get("/uploads/{upload_id}", response_model=UploadSessionResponse)
async def read_upload_session(
    upload: UploadSession = Depends(require_upload_action(ProjectAction.read_project)),
    session: AsyncSession = Depends(get_session),
) -> UploadSessionResponse:
    """Report session status and per-file progress so a client can resume.

    Args:
        upload: Session resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The session with its items.
    """
    return await _session_response(session, upload)


@router.put(
    "/uploads/{upload_id}/files/{client_file_id}",
    response_model=UploadChunkResponse,
)
async def upload_chunk(
    client_file_id: str,
    request: Request,
    response: Response,
    upload_offset: int = Header(alias="Upload-Offset", ge=0),
    chunk_sha256: str = Header(alias="X-Chunk-SHA256", pattern=SHA256_HEX),
    upload: UploadSession = Depends(
        require_upload_action(ProjectAction.update_project)
    ),
    session: AsyncSession = Depends(get_session),
) -> UploadChunkResponse:
    """Accept one verified chunk and acknowledge the next expected offset.

    Args:
        client_file_id: Client identifier of the file being uploaded.
        request: Raw request carrying the chunk bytes.
        response: Response used to echo the accepted offset.
        upload_offset: Offset the chunk starts at.
        chunk_sha256: Digest the client computed for these bytes.
        upload: Session resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The file's accepted offset and declared size.
    """
    item = await ingestion.get_item(session, upload, client_file_id)
    item = await ingestion.store_chunk(
        session,
        upload,
        item,
        upload_offset,
        chunk_sha256,
        await request.body(),
    )
    response.headers["Upload-Offset"] = str(item.received_bytes)
    return UploadChunkResponse(
        client_file_id=item.client_file_id,
        received_bytes=item.received_bytes,
        size_bytes=item.size_bytes,
    )


@router.post("/uploads/{upload_id}/complete", response_model=UploadSessionResponse)
async def complete_upload_session(
    upload: UploadSession = Depends(
        require_upload_action(ProjectAction.update_project)
    ),
    session: AsyncSession = Depends(get_session),
) -> UploadSessionResponse:
    """Verify every uploaded file and promote it into the project's media.

    Args:
        upload: Session resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The session in its final state.
    """
    completed = await ingestion.complete_session(session, upload)
    return await _session_response(session, completed)


@router.delete("/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_upload_session(
    upload: UploadSession = Depends(
        require_upload_action(ProjectAction.update_project)
    ),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Cancel a session and permanently purge its temporary parts.

    Args:
        upload: Session resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        An empty response.
    """
    await ingestion.cancel_session(session, upload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
