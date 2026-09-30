"""Project media inventory and signed image content routes."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import require_project_action
from dada_api.core import media_urls
from dada_api.db.session import get_session
from dada_api.models.project import Project
from dada_api.schemas.media import MediaPage, MediaResponse
from dada_api.services import ingestion, storage
from dada_api.services.authorization import ProjectAction

router = APIRouter()


@router.get(
    "/media/{media_id}/content",
    response_class=StreamingResponse,
    responses={200: {"content": {"image/*": {}}}},
)
async def media_content(
    media_id: str,
    expires: int = Query(),
    signature: str = Query(),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Stream one image's bytes to the holder of a signed link.

    The signature is the authorization: it is issued only inside an
    assignment the caller owns and expires shortly after, so no bearer token
    is needed and none is ever placed in a URL.

    Args:
        media_id: Media item being served.
        expires: Expiry time from the signed link, as a Unix timestamp.
        signature: Signature from the signed link.
        session: Active database session.

    Returns:
        The image bytes with their media type.
    """
    media_urls.verify_media_url(media_id, expires, signature, datetime.now(UTC))
    content = await ingestion.get_media_content(session, media_id)
    return StreamingResponse(
        storage.iter_media(content.storage_key),
        media_type=content.media_type,
        headers={
            "Content-Length": str(content.size_bytes),
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/projects/{project_id}/media", response_model=MediaPage)
async def list_media(
    cursor: str | None = Query(default=None),
    project: Project = Depends(require_project_action(ProjectAction.read_project)),
    session: AsyncSession = Depends(get_session),
) -> MediaPage:
    """List a project's ingested images ordered by relative path.

    Args:
        cursor: Opaque cursor from a previous page.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        One page of media with the cursor for the next one.
    """
    rows, next_cursor = await ingestion.list_media(session, project, cursor)
    return MediaPage(
        items=[
            MediaResponse(
                id=media.id,
                relative_path=media.relative_path,
                media_type=content.media_type,
                size_bytes=content.size_bytes,
                sha256=content.sha256,
                width=content.width,
                height=content.height,
                created_at=media.created_at,
            )
            for media, content in rows
        ],
        next_cursor=next_cursor,
    )
