"""Annotation queue endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from dada_api.api.deps import get_current_user
from dada_api.models.user import User
from dada_api.schemas.queue import (
    AnnotationSubmitRequest,
    AnnotationSubmitResponse,
    QueueItemResponse,
)

router = APIRouter()


@router.get("/next", response_model=QueueItemResponse)
async def get_next_queue_item(
    _: User = Depends(get_current_user),
) -> QueueItemResponse:
    """Lease the next image for annotation.

    Args:
        _: Authenticated user.

    Raises:
        HTTPException: 501 until Phase 5 implements project-scoped leasing.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Queue leasing is not implemented yet.",
    )


@router.post("/annotations", response_model=AnnotationSubmitResponse)
async def submit_annotations(
    payload: AnnotationSubmitRequest,
    _: User = Depends(get_current_user),
) -> AnnotationSubmitResponse:
    """Submit completed COCO-style polygons for a leased image.

    Args:
        payload: Submitted annotations.
        _: Authenticated user.

    Returns:
        The acceptance result.
    """
    return AnnotationSubmitResponse(
        status="accepted",
        accepted_annotations=len(payload.annotations),
    )
