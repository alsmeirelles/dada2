"""Assisted segmentation inference endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from dada_api.api.deps import RequireAnnotator
from dada_api.models.user import User
from dada_api.schemas.inference import SamPredictRequest, SamPredictResponse

router = APIRouter()


@router.post("/sam-predict", response_model=SamPredictResponse)
async def predict_sam_polygons(
    _: SamPredictRequest,
    __: User = Depends(RequireAnnotator),
) -> SamPredictResponse:
    """Run SAM prompted segmentation for an assigned image."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="SAM inference is not implemented yet.",
    )
