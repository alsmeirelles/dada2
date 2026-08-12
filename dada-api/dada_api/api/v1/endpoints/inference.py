"""Assisted segmentation inference endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from dada_api.api.deps import get_current_user
from dada_api.models.user import User
from dada_api.schemas.inference import SamPredictRequest, SamPredictResponse

router = APIRouter()


@router.post("/sam-predict", response_model=SamPredictResponse)
async def predict_sam_polygons(
    _: SamPredictRequest,
    __: User = Depends(get_current_user),
) -> SamPredictResponse:
    """Run SAM prompted segmentation for an assigned image.

    Args:
        _: Prompt payload.
        __: Authenticated user.

    Raises:
        HTTPException: 501 until Phase 6 implements the assisted segmentation
            contract and lease authorization.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="SAM inference is not implemented yet.",
    )
