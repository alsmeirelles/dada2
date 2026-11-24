"""Assisted annotation request and response schemas."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from dada_api.schemas.assignment import (
    CanonicalPolygonGeometry,
    Coordinate,
    RectangleGeometry,
)


class SamPrompt(BaseModel):
    """A point ``[x, y]`` or a box ``[x, y, width, height]`` in canonical image
    pixels."""

    type: Literal["point", "box"]
    coordinates: list[Coordinate] = Field(min_length=2, max_length=4)
    label: str | None = None


class SamPredictRequest(BaseModel):
    """A prompt from the annotator who owns the assignment (P7-07).

    ``request_id`` lets the client match an answer to its prompt; the server
    makes one up when it is omitted.
    """

    project_id: UUID
    assignment_id: UUID
    request_id: str | None = Field(default=None, min_length=1, max_length=64)
    prompts: list[SamPrompt] = Field(min_length=1, max_length=1)


class SamPredictResponse(BaseModel):
    """A suggestion for the annotator to preview, or ``no_suggestion``.

    ``geometry`` is a rectangle for detection and a polygon for segmentation,
    in canonical pixels. Nothing is saved: the suggestion reaches the draft
    only when the annotator accepts it there (A7-03).
    """

    request_id: str
    assignment_id: UUID
    status: Literal["suggestion", "no_suggestion"]
    geometry: (
        Annotated[
            RectangleGeometry | CanonicalPolygonGeometry, Field(discriminator="type")
        ]
        | None
    )
    score: float | None
    model: dict[str, Any]
