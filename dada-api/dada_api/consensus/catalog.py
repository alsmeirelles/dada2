"""The versioned resolver catalog: pipelines, strategies, descriptors, and
availability."""

import types
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from dada_api.consensus import config

VERSION = "1.0.0"
PINS = {
    "numpy": "2.4.6",
    "scipy": "1.17.1",
    "opencv-python-headless": "4.13.0.92",
    "pandas": "3.0.6",
    "crowd-kit": "1.4.2",
}
NUMERIC = ("numpy", "scipy")
MASKS = (*NUMERIC, "opencv-python-headless")
CROWD_KIT = (*MASKS, "pandas", "crowd-kit")


@dataclass(frozen=True)
class Strategy:
    """One selectable sub-strategy of a pipeline.

    Attributes:
        model: Closed configuration model; its ``strategy`` default is the ID.
        requires: Distributions that must be installed at their pinned version.
        conditional: Whether project evidence decides eligibility (P6-01).
        profiled: Whether its resource profile passed the Phase 6 limits.
        version: Implementation semantic version.
    """

    model: type[config.Closed]
    requires: tuple[str, ...] = NUMERIC
    conditional: bool = False
    profiled: bool = True
    version: str = VERSION

    @property
    def id(self) -> str:
        """The strategy identifier clients send."""
        return self.model.model_fields["strategy"].default


@dataclass(frozen=True)
class Pipeline:
    """The single top-level resolver pipeline of one task type.

    Attributes:
        id: Pipeline identifier stored as the policy ``resolver``.
        configuration: Closed model of ``parameters`` plus ``review_thresholds``.
        class_strategies: Selectable class/existence strategies.
        geometry_strategies: Selectable box or mask refinements.
        requires: Distributions every run of the pipeline needs.
        version: Pipeline semantic version.
    """

    id: str
    configuration: type[config.Closed]
    class_strategies: tuple[Strategy, ...]
    geometry_strategies: tuple[Strategy, ...]
    requires: tuple[str, ...]
    version: str = VERSION


DIRICHLET = Strategy(config.DirichletVote)
RELIABILITY = Strategy(config.ReliabilityWeightedVote, conditional=True)
DAWID_SKENE = Strategy(config.DawidSkene, conditional=True)
CANDIDATE_STRATEGIES = (
    Strategy(config.CategoricalVote),
    DIRICHLET,
    RELIABILITY,
    DAWID_SKENE,
)
PIPELINES = {
    "classification": Pipeline(
        id="statistical_class_consensus",
        configuration=config.ClassificationConfiguration,
        class_strategies=(
            Strategy(config.MultilabelBinaryVote),
            DIRICHLET,
            RELIABILITY,
            DAWID_SKENE,
        ),
        geometry_strategies=(),
        requires=NUMERIC,
    ),
    "detection": Pipeline(
        id="two_stage_detection_consensus",
        configuration=config.DetectionConfiguration,
        class_strategies=CANDIDATE_STRATEGIES,
        geometry_strategies=(
            Strategy(config.CoordinateMedian),
            Strategy(config.TrimmedMeanBox),
            Strategy(config.WeightedBoxFusion),
        ),
        requires=NUMERIC,
    ),
    "segmentation": Pipeline(
        id="two_stage_segmentation_consensus",
        configuration=config.SegmentationConfiguration,
        class_strategies=CANDIDATE_STRATEGIES,
        geometry_strategies=(
            Strategy(config.SegmentationMajorityVote, requires=CROWD_KIT),
            Strategy(config.SegmentationEM, requires=CROWD_KIT),
            Strategy(config.SegmentationRASA, requires=CROWD_KIT),
            Strategy(config.Staple, requires=MASKS),
        ),
        requires=MASKS,
    ),
}


def pipeline_for(task_type: str) -> Pipeline:
    """Return the pipeline of a task type.

    Args:
        task_type: Project task type.

    Returns:
        The task's pipeline.
    """
    return PIPELINES[task_type]


def normalize(
    task_type: str, parameters: dict[str, Any], review_thresholds: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate a configuration and fill every omitted value with its default.

    Args:
        task_type: Project task type.
        parameters: Requested pipeline parameters.
        review_thresholds: Requested quality gates.

    Returns:
        The complete parameters and thresholds as plain JSON values.

    Raises:
        pydantic.ValidationError: When a key is unknown, a value is out of
            bounds, or a gate would weaken the hard majority floor.
    """
    model = pipeline_for(task_type).configuration.model_validate(
        {"parameters": parameters, "review_thresholds": review_thresholds}
    )
    dumped = model.model_dump(mode="json")
    return dumped["parameters"], dumped["review_thresholds"]


def installed_version(distribution: str) -> str | None:
    """Return a distribution's installed version without importing it.

    Args:
        distribution: Distribution name.

    Returns:
        The installed version, or None when it is absent.
    """
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


UnavailableReason = Literal[
    "dependency_missing",
    "dependency_incompatible",
    "quarantined",
    "resource_profile_unvalidated",
]


def unavailable_reason(
    identifier: str,
    version: str,
    requires: tuple[str, ...],
    *,
    profiled: bool = True,
    installed: Callable[[str], str | None] = installed_version,
    quarantined: frozenset[str] = frozenset(),
) -> UnavailableReason | None:
    """Explain why a pipeline or strategy cannot run, never substituting one.

    Args:
        identifier: Pipeline or strategy identifier.
        version: Its implementation version.
        requires: Distributions it needs at their pinned versions.
        profiled: Whether its resource profile passed.
        installed: Lookup of installed distribution versions.
        quarantined: ``identifier@version`` keys an operator quarantined.

    Returns:
        The typed reason, or None when it is available.
    """
    if f"{identifier}@{version}" in quarantined:
        return "quarantined"
    for distribution in requires:
        found = installed(distribution)
        if found is None:
            return "dependency_missing"
        if found != PINS[distribution]:
            return "dependency_incompatible"
    if not profiled:
        return "resource_profile_unvalidated"
    return None


def selected_strategies(task_type: str, parameters: dict[str, Any]) -> list[Strategy]:
    """Return the class and geometry strategies a stored configuration selects.

    Args:
        task_type: Project task type.
        parameters: Normalized pipeline parameters.

    Returns:
        The selected strategies, class strategy first.
    """
    pipeline = pipeline_for(task_type)
    chosen = {
        parameters["class_strategy"]["strategy"],
        *(
            parameters[name]["strategy"]
            for name in ("box_refinement", "mask_refinement")
            if name in parameters
        ),
    }
    return [
        strategy
        for strategy in (*pipeline.class_strategies, *pipeline.geometry_strategies)
        if strategy.id in chosen
    ]


def configuration_unavailable_reason(
    task_type: str,
    parameters: dict[str, Any],
    *,
    installed: Callable[[str], str | None] = installed_version,
    quarantined: frozenset[str] = frozenset(),
) -> UnavailableReason | None:
    """Explain why a stored configuration cannot run now, if it cannot.

    Args:
        task_type: Project task type.
        parameters: Normalized pipeline parameters.
        installed: Lookup of installed distribution versions.
        quarantined: ``identifier@version`` keys an operator quarantined.

    Returns:
        The first typed reason found, or None when every part is available.
    """
    pipeline = pipeline_for(task_type)
    reason = unavailable_reason(
        pipeline.id,
        pipeline.version,
        pipeline.requires,
        installed=installed,
        quarantined=quarantined,
    )
    for strategy in selected_strategies(task_type, parameters):
        reason = reason or unavailable_reason(
            strategy.id,
            strategy.version,
            strategy.requires,
            profiled=strategy.profiled,
            installed=installed,
            quarantined=quarantined,
        )
    return reason


BOUNDS = {
    "ge": ("minimum", True),
    "gt": ("minimum", False),
    "le": ("maximum", True),
    "lt": ("maximum", False),
}


def _bounds(field: FieldInfo) -> dict[str, Any]:
    """Read the numeric bounds a field declares through ``Field(ge=…)``."""
    bounds: dict[str, Any] = {}
    for item in field.metadata:
        for attribute, (side, inclusive) in BOUNDS.items():
            value = getattr(item, attribute, None)
            if value is not None:
                bounds[side] = value
                bounds[f"{side}_inclusive"] = inclusive
    return bounds


def _kind(annotation: Any) -> tuple[str, list[str] | None]:
    """Map a field annotation to a descriptor kind and its enum options."""
    if get_origin(annotation) is Literal:
        return "enum", [str(option) for option in get_args(annotation)]
    if annotation is config.Ratio:
        return "ratio", None
    if annotation is config.AreaThreshold:
        return "area", None
    if annotation is bool:
        return "boolean", None
    if annotation is int:
        return "integer", None
    return "number", None


def describe(model: type[BaseModel], prefix: str = "") -> list[dict[str, Any]]:
    """Describe every client-settable field of a configuration model.

    Strategy choices (discriminated unions) are described as strategies, not
    as fields, and nested setting groups are flattened with dotted names.

    Args:
        model: Configuration model to describe.
        prefix: Dotted prefix of a nested group.

    Returns:
        One descriptor per field, carrying its bounds and help text.
    """
    descriptors: list[dict[str, Any]] = []
    for name, field in model.model_fields.items():
        if name == "strategy" or field.discriminator is not None:
            continue
        annotation = field.annotation
        nullable = False
        if get_origin(annotation) in (Union, types.UnionType):
            options = [arg for arg in get_args(annotation) if arg is not type(None)]
            nullable = len(options) < len(get_args(annotation))
            annotation = options[0]
        if (
            isinstance(annotation, type)
            and issubclass(annotation, config.Closed)
            and annotation not in (config.Ratio, config.AreaThreshold)
        ):
            descriptors.extend(describe(annotation, f"{prefix}{name}."))
            continue

        kind, enum_options = _kind(annotation)
        extra = dict(field.json_schema_extra or {})
        default = field.default
        descriptors.append(
            {
                "name": f"{prefix}{name}",
                "kind": kind,
                "default": (
                    default.model_dump(mode="json")
                    if isinstance(default, BaseModel)
                    else default
                ),
                "nullable": nullable,
                "options": enum_options,
                "minimum": None,
                "maximum": None,
                "minimum_inclusive": None,
                "maximum_inclusive": None,
                **_bounds(field),
                **{key: extra[key] for key in extra if key not in ("advanced", "unit")},
                "advanced": bool(extra.get("advanced", False)),
                "unit": extra.get("unit"),
                "help": field.description,
            }
        )
    return descriptors


def capabilities(
    installed: Callable[[str], str | None] = installed_version,
    quarantined: frozenset[str] = frozenset(),
) -> dict[str, dict[str, Any]]:
    """Describe every pipeline for ``GET /api/v1/capabilities``.

    Args:
        installed: Lookup of installed distribution versions.
        quarantined: ``identifier@version`` keys an operator quarantined.

    Returns:
        Task type mapped to its pipeline description.
    """

    def strategy(item: Strategy) -> dict[str, Any]:
        """Describe one strategy with its availability and parameters."""
        return {
            "id": item.id,
            "version": item.version,
            "conditional": item.conditional,
            "unavailable_reason": unavailable_reason(
                item.id,
                item.version,
                item.requires,
                profiled=item.profiled,
                installed=installed,
                quarantined=quarantined,
            ),
            "dependencies": {name: installed(name) for name in item.requires},
            "parameters": describe(item.model),
        }

    result: dict[str, dict[str, Any]] = {}
    for task_type, pipeline in PIPELINES.items():
        fields = pipeline.configuration.model_fields
        result[task_type] = {
            "id": pipeline.id,
            "version": pipeline.version,
            "unavailable_reason": unavailable_reason(
                pipeline.id,
                pipeline.version,
                pipeline.requires,
                installed=installed,
                quarantined=quarantined,
            ),
            "class_strategies": [strategy(item) for item in pipeline.class_strategies],
            "geometry_strategies": [
                strategy(item) for item in pipeline.geometry_strategies
            ],
            "parameters": describe(fields["parameters"].annotation),
            "review_thresholds": describe(fields["review_thresholds"].annotation),
        }
    return result
