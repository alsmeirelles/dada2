"""Registry and discovery of the active-learning solutions this API offers.

The API persists a solution's id and version with the project and every run,
and never substitutes one solution for another. A solution whose
dependencies are missing stays listed with a typed reason.
"""

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from dada_api.active_learning import deterministic
from dada_api.active_learning.contract import (
    AdapterError,
    AssistanceProvider,
    BaseModelAdapter,
)
from dada_api.active_learning.dada_al.config.schema import DADASettings
from dada_api.consensus.catalog import describe, installed_version
from dada_api.core.config import get_settings

DEVELOPMENT_ENVIRONMENTS = frozenset({"development", "test"})
METRICS: dict[str, tuple[str, ...]] = {
    "classification": ("accuracy", "f1"),
    "detection": ("map50",),
    "segmentation": ("mean_iou",),
}
UnavailableReason = Literal["dependency_missing"]


@dataclass(frozen=True)
class Solution:
    """One registered active-learning solution.

    ``adapter`` and ``assistant`` are import paths resolved only when a worker
    runs the solution, so the API never imports its heavy dependencies.
    ``assistant`` is None for a solution that offers no assisted annotation.
    """

    id: str
    version: str
    display_name: str
    description: str
    tasks: tuple[str, ...]
    development_only: bool
    requires: tuple[str, ...]
    configuration: type[BaseModel]
    adapter: str
    assistant: str | None


DETERMINISTIC = Solution(
    id=deterministic.SOLUTION_ID,
    version=deterministic.SOLUTION_VERSION,
    display_name="Deterministic (development)",
    description=(
        "Reproducible ranking without a model, to exercise the loop in "
        "development and tests."
    ),
    tasks=("classification", "detection", "segmentation"),
    development_only=True,
    requires=(),
    configuration=deterministic.DeterministicConfiguration,
    adapter="dada_api.active_learning.deterministic:DeterministicAdapter",
    assistant="dada_api.active_learning.deterministic:DeterministicAssistant",
)
DADA = Solution(
    id="dada",
    version="1.0.0",
    display_name="DADA",
    description=(
        "Diversity-aware data acquisition: clusters the embeddings of the most "
        "uncertain images or objects and fills each cluster's quota by its "
        "mean uncertainty."
    ),
    tasks=("classification", "detection", "segmentation"),
    development_only=False,
    requires=("torch", "torchvision", "ultralytics", "timm", "scikit-learn"),
    configuration=DADASettings,
    adapter="dada_api.active_learning.dada_al.adapter:DADAAdapter",
    assistant="dada_api.active_learning.dada_al.adapter:DADAAssistant",
)
PRODUCTION_SOLUTIONS: tuple[Solution, ...] = (DADA,)


def registered() -> list[Solution]:
    """Return the solutions of this environment, production ones first."""
    solutions = list(PRODUCTION_SOLUTIONS)
    if get_settings().environment in DEVELOPMENT_ENVIRONMENTS:
        solutions.append(DETERMINISTIC)
    return solutions


def find(solution_id: str) -> Solution | None:
    """Return a registered solution by id, or None."""
    return next((item for item in registered() if item.id == solution_id), None)


def unavailable_reason(
    solution: Solution,
    installed: Callable[[str], str | None] = installed_version,
) -> UnavailableReason | None:
    """Explain why a solution cannot run, without importing it.

    Args:
        solution: Registered solution.
        installed: Lookup of installed distribution versions.

    Returns:
        ``dependency_missing`` or None when it can run.
    """
    if any(installed(name) is None for name in solution.requires):
        return "dependency_missing"
    return None


def default_for(task_type: str) -> Solution | None:
    """Return the first available solution supporting a task."""
    return next(
        (
            item
            for item in registered()
            if task_type in item.tasks and unavailable_reason(item) is None
        ),
        None,
    )


def validate_configuration(
    solution: Solution, configuration: dict[str, Any], task: str
) -> dict[str, Any]:
    """Validate a configuration and return it with every default filled in.

    The task is given to the configuration model as validation context, so a
    solution can resolve task defaults and refuse incompatible settings.

    Args:
        solution: Registered solution.
        configuration: Client-supplied settings.
        task: The project's task.

    Returns:
        The complete normalized configuration.

    Raises:
        ValueError: With the validation errors when it is invalid.
    """
    try:
        model = solution.configuration.model_validate(
            configuration, context={"task": task}
        )
    except ValidationError as error:
        raise ValueError(
            error.errors(include_url=False, include_context=False)
        ) from error
    return model.model_dump(mode="json")


def runnable(solution_id: str, version: str) -> Solution:
    """Return an exact registered solution version that can run here.

    Args:
        solution_id: Persisted solution id.
        version: Persisted solution version.

    Returns:
        The solution.

    Raises:
        AdapterError: ``solution_unavailable`` when the version is not
            registered here or its dependencies are missing.
    """
    solution = find(solution_id)
    if solution is None or solution.version != version:
        raise AdapterError(
            "solution_unavailable", f"{solution_id}@{version} is not registered"
        )
    if unavailable_reason(solution) is not None:
        raise AdapterError(
            "solution_unavailable", f"{solution_id}@{version} lacks dependencies"
        )
    return solution


def _instantiate(path: str) -> Any:
    """Import ``module:Class`` and return a new instance of it."""
    module, _, name = path.partition(":")
    return getattr(importlib.import_module(module), name)()


def load_adapter(solution_id: str, version: str) -> BaseModelAdapter:
    """Instantiate the adapter of an exact registered solution version.

    Args:
        solution_id: Persisted solution id.
        version: Persisted solution version.

    Returns:
        A ready adapter.

    Raises:
        AdapterError: ``solution_unavailable`` when it cannot run here.
    """
    return _instantiate(runnable(solution_id, version).adapter)


def load_assistant(solution_id: str, version: str) -> AssistanceProvider:
    """Instantiate the assistance provider of an exact solution version.

    Args:
        solution_id: Solution that retained the target model.
        version: Its version.

    Returns:
        A ready provider.

    Raises:
        AdapterError: ``solution_unavailable`` when it cannot run here or
            offers no assistance.
    """
    solution = runnable(solution_id, version)
    if solution.assistant is None:
        raise AdapterError(
            "solution_unavailable", f"{solution_id}@{version} offers no assistance"
        )
    return _instantiate(solution.assistant)


def capabilities() -> list[dict[str, Any]]:
    """Describe every registered solution for ``GET /capabilities``."""
    return [
        {
            "id": item.id,
            "version": item.version,
            "display_name": item.display_name,
            "description": item.description,
            "supported_tasks": list(item.tasks),
            "development_only": item.development_only,
            "unavailable_reason": unavailable_reason(item),
            "parameters": describe(item.configuration),
        }
        for item in registered()
    ]
