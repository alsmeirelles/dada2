"""Common API error response schemas."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    """Stable machine- and human-readable error details."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    trace_id: str


class ErrorEnvelope(BaseModel):
    """Envelope used for all API application errors."""

    error: ErrorBody
