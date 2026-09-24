"""Draft dataset layout preparation, reset, and summary routes."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import get_current_user, require_project_action
from dada_api.db.session import get_session
from dada_api.models.project import Project
from dada_api.models.user import User
from dada_api.schemas.dataset import DatasetLayoutResponse
from dada_api.services import datasets as dataset_service
from dada_api.services.authorization import ProjectAction

router = APIRouter()


@router.get(
    "/projects/{project_id}/dataset-layout", response_model=DatasetLayoutResponse
)
async def read_dataset_layout(
    project: Project = Depends(require_project_action(ProjectAction.read_project)),
    session: AsyncSession = Depends(get_session),
) -> DatasetLayoutResponse:
    """Return a project's prepared layout, initial batches, and training pool.

    Args:
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The layout summary.
    """
    return DatasetLayoutResponse(
        **await dataset_service.layout_summary(session, project)
    )


@router.post(
    "/projects/{project_id}/dataset-layout/prepare",
    response_model=DatasetLayoutResponse,
    status_code=status.HTTP_201_CREATED,
)
async def prepare_dataset_layout(
    project: Project = Depends(require_project_action(ProjectAction.update_project)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DatasetLayoutResponse:
    """Materialise a draft's split membership and its initial batches.

    Args:
        project: Project resolved and authorized by the dependency.
        user: Authenticated user recorded as the actor.
        session: Active database session.

    Returns:
        The prepared layout summary.
    """
    prepared = await dataset_service.prepare(session, user, project)
    return DatasetLayoutResponse(
        **await dataset_service.layout_summary(session, prepared)
    )


@router.delete(
    "/projects/{project_id}/dataset-layout", status_code=status.HTTP_204_NO_CONTENT
)
async def reset_dataset_layout(
    project: Project = Depends(require_project_action(ProjectAction.update_project)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Discard a draft's preparation and its label import.

    Args:
        project: Project resolved and authorized by the dependency.
        user: Authenticated user recorded as the actor.
        session: Active database session.

    Returns:
        An empty response.
    """
    await dataset_service.reset(session, user, project)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
