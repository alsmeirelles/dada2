"""Acquisition iteration, retry, completion-check, and statistics routes."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import get_current_user, require_project_action
from dada_api.db.session import get_session
from dada_api.models.project import Project
from dada_api.models.user import User
from dada_api.schemas.learning import (
    IterationPage,
    IterationResponse,
    StatisticsResponse,
)
from dada_api.services import learning_runs
from dada_api.services.authorization import ProjectAction

router = APIRouter()


def _now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(UTC)


@router.get("/projects/{project_id}/iterations", response_model=IterationPage)
async def list_iterations(
    cursor: str | None = Query(default=None),
    project: Project = Depends(require_project_action(ProjectAction.read_project)),
    session: AsyncSession = Depends(get_session),
) -> IterationPage:
    """List a project's acquisition iterations, oldest first.

    Iterations carry aggregate progress only, never peer identity or content.

    Args:
        cursor: Opaque cursor from a previous page.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        One page of iterations, the current one, and the next cursor.
    """
    return await learning_runs.iteration_page(session, project, cursor)


@router.get(
    "/projects/{project_id}/iterations/{iteration_id}",
    response_model=IterationResponse,
)
async def read_iteration(
    iteration_id: str,
    project: Project = Depends(require_project_action(ProjectAction.read_project)),
    session: AsyncSession = Depends(get_session),
) -> IterationResponse:
    """Return one iteration with its counts, state, and metrics.

    Args:
        iteration_id: First run attempt identifying the iteration.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The iteration.
    """
    return await learning_runs.iteration(session, project, iteration_id)


@router.post(
    "/projects/{project_id}/iterations/{iteration_id}/close",
    response_model=IterationResponse,
)
async def close_iteration(
    iteration_id: str,
    project: Project = Depends(require_project_action(ProjectAction.read_project)),
    session: AsyncSession = Depends(get_session),
) -> IterationResponse:
    """Check an iteration's completion and open the next one when it is due.

    The server opens iterations on its own; this idempotent check only lets
    a client reconcile a missed event.

    Args:
        iteration_id: First run attempt identifying the iteration.
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        The iteration after the check.
    """
    return await learning_runs.close(session, project, iteration_id, _now())


@router.post(
    "/projects/{project_id}/iterations/{iteration_id}/retry",
    response_model=IterationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_iteration(
    iteration_id: str,
    project: Project = Depends(require_project_action(ProjectAction.manage_learning)),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> IterationResponse:
    """Queue a new attempt of a failed iteration over the same snapshots.

    Args:
        iteration_id: First run attempt identifying the iteration.
        project: Project authorized to manage learning.
        user: Owner or manager recorded as the actor.
        session: Active database session.

    Returns:
        The iteration with its new attempt.
    """
    return await learning_runs.retry(session, user, project, iteration_id, _now())


@router.get("/projects/{project_id}/statistics", response_model=StatisticsResponse)
async def read_statistics(
    project: Project = Depends(require_project_action(ProjectAction.read_project)),
    session: AsyncSession = Depends(get_session),
) -> StatisticsResponse:
    """Return the loop's progress and every target-model evaluation.

    Args:
        project: Project resolved and authorized by the dependency.
        session: Active database session.

    Returns:
        Progress counts and evaluations ordered by iteration.
    """
    return await learning_runs.statistics(session, project)
