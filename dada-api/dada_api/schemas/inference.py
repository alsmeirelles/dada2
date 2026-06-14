"""Inference request and response schemas."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class SamPrompt(BaseModel):
    """Prompt sent to the assisted segmentation endpoint."""

    type: Literal["point", "box"]
    coordinates: list[float] = Field(min_length=2)
    label: str | None = None


class SamPredictRequest(BaseModel):
    """SAM prediction request."""

    image_id: str = Field(min_length=1)
    prompts: list[SamPrompt] = Field(min_length=1)


class SamPredictResponse(BaseModel):
    """SAM prediction response."""

    image_id: str
    polygons: list[dict[str, Any]]
    embedding_cache_key: str | None = None
