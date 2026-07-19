"""Health-check schemas."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """API health response."""

    status: str
    service: str


class DependencyStatus(BaseModel):
    """Readiness state for one external dependency."""

    status: str
    detail: str | None = None


class ReadinessResponse(BaseModel):
    """Aggregate dependency and migration readiness state."""

    status: str
    service: str
    dependencies: dict[str, DependencyStatus]
