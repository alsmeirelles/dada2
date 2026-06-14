"""Health-check schemas."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """API health response."""

    status: str
    service: str
