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
AcquisitionStrategyName = Literal["random", "active_learning"]
DatasetLayoutName = Literal["split", "single_batch"]
EvaluationMetricName = Literal["accuracy", "f1", "map50", "mean_iou"]
CompletionReasonName = Literal["max_iterations", "metric_target", "pool_exhausted"]
HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"
SIZE_FIELDS = (
    "initial_training_size",
    "test_set_size",
    "test_set_percentage",
    "validation_set_size",
    "validation_set_percentage",
    "iteration_batch_size",
)
LEARNING_FIELDS = (
    "learning_solution",
    "learning_configuration",
    "evaluation_metric",
    "evaluation_interval",
    "metric_target",
)


class LearningSettings(BaseModel):
    """Optional active-learning settings shared by create and update (D1).

    They are accepted only with the ``active_learning`` strategy; omitted
    values receive the defaults of the selected solution and task.
    """

    learning_solution: str | None = Field(default=None, min_length=1, max_length=64)
    learning_configuration: dict[str, Any] | None = None
    evaluation_metric: EvaluationMetricName | None = None
    evaluation_interval: int | None = Field(default=None, ge=1, le=1000)
    metric_target: float | None = Field(default=None, gt=0, le=1)


class ProjectCreate(LearningSettings):
    """Create-project request contract.

    A ``split`` project requires ``iteration_batch_size``,
    ``max_acquisition_iterations``, and one count or percentage for each
    held-out split. ``initial_training_size`` is optional: when omitted, the
    first training batch uses ``iteration_batch_size``.

    A ``single_batch`` project annotates every image once and never trains, so
    it accepts no size, no iteration limit, and only the ``random``
    acquisition strategy.
    """

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    task_type: TaskType
    acquisition_strategy: AcquisitionStrategyName = "random"
    dataset_layout: DatasetLayoutName = "split"
    initial_training_size: int | None = Field(default=None, ge=1)
    test_set_size: int | None = Field(default=None, ge=1)
    test_set_percentage: float | None = Field(default=None, gt=0, lt=100)
    validation_set_size: int | None = Field(default=None, ge=1)
    validation_set_percentage: float | None = Field(default=None, gt=0, lt=100)
    iteration_batch_size: int | None = Field(default=None, ge=1)
    max_acquisition_iterations: int | None = Field(default=None, ge=1, le=10_000)

    @model_validator(mode="before")
    @classmethod
    def validate_split_size_definitions(cls, value: Any) -> Any:
        """Require one count or percentage for each held-out split."""
        if not isinstance(value, dict) or value.get("dataset_layout") == "single_batch":
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

    @model_validator(mode="after")
    def validate_dataset_layout(self) -> "ProjectCreate":
        """Enforce the layout's size rules and its acquisition compatibility."""
        if self.acquisition_strategy == "random" and any(
            getattr(self, name) is not None for name in LEARNING_FIELDS
        ):
            raise ValueError("learning settings require the active_learning strategy")
        if self.dataset_layout == "split":
            if self.iteration_batch_size is None:
                raise ValueError("a split project requires iteration_batch_size")
            if self.max_acquisition_iterations is None:
                raise ValueError("a split project requires max_acquisition_iterations")
            return self
        if self.acquisition_strategy != "random":
            raise ValueError("single_batch requires the random acquisition strategy")
        if any(
            getattr(self, name) is not None
            for name in (*SIZE_FIELDS, "max_acquisition_iterations")
        ):
            raise ValueError("single_batch accepts no split or iteration sizes")
        return self


class ProjectUpdate(LearningSettings):
    """Optimistically versioned editable project fields.

    ``acquisition_strategy``, ``max_acquisition_iterations``, and the learning
    settings may change on a ``split`` project, before or after activation.
    They decide how later acquisition iterations run; they never alter the
    fixed splits, the initial batches, or a run already created.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    acquisition_strategy: AcquisitionStrategyName | None = None
    max_acquisition_iterations: int | None = Field(default=None, ge=1, le=10_000)
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def keep_the_iteration_limit(self) -> "ProjectUpdate":
        """Refuse clearing the iteration limit of a split project."""
        if (
            "max_acquisition_iterations" in self.model_fields_set
            and self.max_acquisition_iterations is None
        ):
            raise ValueError("max_acquisition_iterations cannot be cleared")
        return self


class ProjectResponse(BaseModel):
    """Project representation expected by the App."""

    id: UUID
    name: str
    description: str | None
    task_type: TaskType
    status: ProjectStatus
    owner_id: UUID
    acquisition_strategy: AcquisitionStrategyName
    dataset_layout: DatasetLayoutName
    initial_training_size: int | None
    test_set_size: int | None
    test_set_percentage: float | None
    validation_set_size: int | None
    validation_set_percentage: float | None
    iteration_batch_size: int | None
    max_acquisition_iterations: int | None
    learning_solution: str | None
    learning_solution_version: str | None
    learning_configuration: dict[str, Any]
    evaluation_metric: EvaluationMetricName | None
    evaluation_interval: int | None
    metric_target: float | None
    completion_reason: CompletionReasonName | None
    dataset_prepared_at: datetime | None
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
