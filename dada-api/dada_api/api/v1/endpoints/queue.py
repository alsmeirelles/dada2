"""Annotation queue endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from dada_api.api.deps import RequireAnnotator
from dada_api.models.user import User
from dada_api.schemas.queue import (
    AnnotationSubmitRequest,
    AnnotationSubmitResponse,
    QueueItemResponse,
)

router = APIRouter()


@router.get("/next", response_model=QueueItemResponse)
async def get_next_queue_item(_: User = Depends(RequireAnnotator)) -> QueueItemResponse:
    """Lease the next image for annotation.

    The storage and active-learning queue implementation will replace this
    placeholder once image persistence is available.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Queue leasing is not implemented yet.",
    )


@router.post("/annotations", response_model=AnnotationSubmitResponse)
async def submit_annotations(
    payload: AnnotationSubmitRequest,
    _: User = Depends(RequireAnnotator),
) -> AnnotationSubmitResponse:
    """Submit completed COCO-style polygons for a leased image."""
    return AnnotationSubmitResponse(
        status="accepted",
        accepted_annotations=len(payload.annotations),
    )
