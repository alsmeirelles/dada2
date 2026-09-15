"""Project contract schemas used by the v1 OpenAPI surface."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

TaskType = Literal["classification", "detection", "segmentation"]
ProjectStatus = Literal[
    "draft", "ingesting", "ready", "active", "training", "completed", "failed"
]
ProjectRoleName = Literal["owner", "manager", "annotator", "viewer"]
HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"


class ProjectCreate(BaseModel):
    """Create-project request contract."""

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    task_type: TaskType
    initial_training_size: int = Field(ge=1)
    test_set_size: int | None = Field(default=None, ge=1)
    test_set_percentage: float | None = Field(default=None, gt=0, lt=100)
    validation_set_size: int | None = Field(default=None, ge=1)
    validation_set_percentage: float | None = Field(default=None, gt=0, lt=100)
    iteration_batch_size: int = Field(ge=1)

    @model_validator(mode="before")
    @classmethod
    def validate_split_size_definitions(cls, value: Any) -> Any:
        """Require one count or percentage for each held-out split."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if (
            "validation_set_size" not in data
            and "validation_set_percentage" not in data
        ):
            data["validation_set_size"] = 1
        for prefix in ("test", "validation"):
            count = data.get(f"{prefix}_set_size")
            percentage = data.get(f"{prefix}_set_percentage")
            if (count is None) == (percentage is None):
                raise ValueError(
                    f"define exactly one of {prefix}_set_size or "
                    f"{prefix}_set_percentage"
                )
        return data


class ProjectUpdate(BaseModel):
    """Optimistically versioned editable project fields."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    version: int = Field(ge=1)


class ProjectResponse(BaseModel):
    """Project representation expected by the App."""

    id: UUID
    name: str
    description: str | None
    task_type: TaskType
    status: ProjectStatus
    owner_id: UUID
    initial_training_size: int
    test_set_size: int | None
    test_set_percentage: float | None
    validation_set_size: int | None
    validation_set_percentage: float | None
    iteration_batch_size: int
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectPage(BaseModel):
    """Cursor-paginated project collection."""

    items: list[ProjectResponse]
    next_cursor: str | None = None


class ProjectClassCreate(BaseModel):
    """Create-class request contract."""

    name: str = Field(min_length=1, max_length=100)
    color: str = Field(pattern=HEX_COLOR)
    display_order: int = Field(ge=0)


class ProjectClassUpdate(BaseModel):
    """Optimistically versioned editable class fields."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = Field(default=None, pattern=HEX_COLOR)
    display_order: int | None = Field(default=None, ge=0)
    version: int = Field(ge=1)


class ProjectClassResponse(BaseModel):
    """Object class representation expected by the App."""

    id: UUID
    name: str
    color: str
    display_order: int
    version: int

    model_config = {"from_attributes": True}


class ProjectClassPage(BaseModel):
    """Cursor-paginated class collection."""

    items: list[ProjectClassResponse]
    next_cursor: str | None = None


class ProjectMemberCreate(BaseModel):
    """Add-member request naming an existing user."""

    username: str = Field(min_length=3, max_length=64)
    role: ProjectRoleName


class ProjectMemberUpdate(BaseModel):
    """Role change for an existing member."""

    role: ProjectRoleName


class ProjectMemberResponse(BaseModel):
    """Membership representation expected by the App."""

    user_id: UUID
    username: str
    display_name: str
    role: ProjectRoleName


class ProjectMemberPage(BaseModel):
    """Cursor-paginated membership collection."""

    items: list[ProjectMemberResponse]
    next_cursor: str | None = None
