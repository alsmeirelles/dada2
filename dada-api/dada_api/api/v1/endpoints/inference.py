"""Assisted annotation endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dada_api.api.deps import get_current_user
from dada_api.db.session import get_session
from dada_api.models.user import User
from dada_api.schemas.inference import SamPredictRequest, SamPredictResponse
from dada_api.services import assistance


def get_dispatcher() -> assistance.Dispatcher:
    """Return what sends prompts to the assistance worker; tests replace it."""
    from dada_api.workers.celery_app import dispatch_assistance

    return dispatch_assistance


router = APIRouter()


@router.post("/sam-predict", response_model=SamPredictResponse)
async def predict(
    request: SamPredictRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    dispatch: assistance.Dispatcher = Depends(get_dispatcher),
) -> SamPredictResponse:
    """Suggest a box or polygon for a prompt on the caller's open assignment.

    The project's latest target model answers within the configured timeout
    (D18). The suggestion is only returned; it reaches the draft when the
    annotator accepts it there, so a timeout or failure changes nothing.

    Args:
        request: The prompt and the assignment it belongs to.
        user: The annotator.
        session: Active database session.
        dispatch: Sender to the assistance worker.

    Returns:
        The suggestion, or ``no_suggestion``.
    """
    return await assistance.suggest(session, user, request, dispatch)
