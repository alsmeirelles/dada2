"""Resolution and validation of a project's active-learning settings (D1)."""

from typing import Any

from dada_api.active_learning import catalog
from dada_api.core.errors import ApiError
from dada_api.models.project import AcquisitionStrategy, Project
from dada_api.schemas.project import LEARNING_FIELDS

DEFAULT_METRICS = {
    "classification": "accuracy",
    "detection": "map50",
    "segmentation": "mean_iou",
}
DEFAULT_INTERVAL = 1
SNAPSHOT_FIELDS = (
    "max_acquisition_iterations",
    "learning_solution",
    "learning_solution_version",
    "learning_configuration",
    "evaluation_metric",
    "evaluation_interval",
    "metric_target",
)


def snapshot(project: Project) -> dict[str, Any]:
    """Return the project's learning settings, as recorded in the audit."""
    return {name: getattr(project, name) for name in SNAPSHOT_FIELDS}


def apply(project: Project, requested: dict[str, Any]) -> None:
    """Resolve the project's learning settings in place from a request.

    A random project carries no solution or evaluation settings. An
    active-learning project receives the defaults of its solution and task for
    every value the request leaves out; a request that changes the solution
    without a configuration starts from that solution's defaults.

    Args:
        project: Project whose strategy is already decided.
        requested: Learning fields the caller supplied, explicit nulls
            included.

    Raises:
        ApiError: 422 when a setting is not allowed, unknown, unavailable,
            incompatible with the task, or invalid.
    """
    if project.acquisition_strategy != AcquisitionStrategy.active_learning:
        if any(requested.get(name) is not None for name in LEARNING_FIELDS):
            raise ApiError(
                422,
                "learning_settings_not_allowed",
                "Learning settings apply only to active-learning projects.",
            )
        project.learning_solution = None
        project.learning_solution_version = None
        project.learning_configuration = {}
        project.evaluation_metric = None
        project.evaluation_interval = None
        project.metric_target = None
        return

    solution_id = requested.get("learning_solution") or project.learning_solution
    solution = (
        catalog.find(solution_id)
        if solution_id is not None
        else catalog.default_for(project.task_type)
    )
    if solution is None:
        raise ApiError(
            422,
            "learning_solution_unknown"
            if solution_id is not None
            else "learning_solution_unavailable",
            "No such active-learning solution is available.",
            details={"learning_solution": solution_id},
        )
    if project.task_type not in solution.tasks:
        raise ApiError(
            422,
            "learning_solution_incompatible",
            "The solution does not support the project's task.",
            details={"learning_solution": solution.id, "task": project.task_type},
        )
    reason = catalog.unavailable_reason(solution)
    if reason is not None:
        raise ApiError(
            422,
            "learning_solution_unavailable",
            "The solution cannot run on this server.",
            details={"learning_solution": solution.id, "reason": reason},
        )

    configuration = requested.get("learning_configuration")
    if configuration is None:
        configuration = (
            project.learning_configuration
            if solution.id == project.learning_solution
            else {}
        )
    try:
        configuration = catalog.validate_configuration(
            solution, configuration, project.task_type
        )
    except ValueError as error:
        raise ApiError(
            422,
            "learning_configuration_invalid",
            "The solution configuration is invalid.",
            details={"errors": error.args[0]},
        ) from error

    metric = (
        requested.get("evaluation_metric")
        or project.evaluation_metric
        or DEFAULT_METRICS[project.task_type]
    )
    if metric not in catalog.METRICS[project.task_type]:
        raise ApiError(
            422,
            "evaluation_metric_invalid",
            "The metric does not apply to the project's task.",
            details={"allowed": list(catalog.METRICS[project.task_type])},
        )

    project.learning_solution = solution.id
    project.learning_solution_version = solution.version
    project.learning_configuration = configuration
    project.evaluation_metric = metric
    project.evaluation_interval = (
        requested.get("evaluation_interval")
        or project.evaluation_interval
        or DEFAULT_INTERVAL
    )
    if "metric_target" in requested:
        project.metric_target = requested["metric_target"]
