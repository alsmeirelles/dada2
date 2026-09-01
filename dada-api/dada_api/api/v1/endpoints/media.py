"""Project media inventory routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import require_project_action
from dada_api.db.session import get_session
from dada_api.models.project import Project
from dada_api.schemas.media import MediaPage, MediaResponse
from dada_api.services import ingestion
from dada_api.services.authorization import ProjectAction

router = APIRouter()


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
