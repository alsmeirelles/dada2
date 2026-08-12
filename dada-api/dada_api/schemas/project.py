"""Project contract schemas used by the v1 OpenAPI surface."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

TaskType = Literal["classification", "detection", "segmentation"]
ProjectStatus = Literal[
    "draft", "ingesting", "ready", "active", "training", "completed", "failed"
]


class ProjectCreate(BaseModel):
    """Create-project request contract."""

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    task_type: TaskType
    initial_training_size: int = Field(ge=1)
    test_set_size: int = Field(ge=1)
    iteration_batch_size: int = Field(ge=1)


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
    test_set_size: int
    iteration_batch_size: int
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectPage(BaseModel):
    """Cursor-paginated project collection."""

    items: list[ProjectResponse]
    next_cursor: str | None = None
