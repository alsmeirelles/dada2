"""API capability discovery schemas."""

from typing import Any, Literal

from pydantic import BaseModel, Field

UnavailableReasonName = Literal[
    "dependency_missing",
    "dependency_incompatible",
    "quarantined",
    "resource_profile_unvalidated",
]


class ParameterDescriptor(BaseModel):
    """One settable resolver field, described so a client can render and
    validate it without hard-coding its meaning.

    ``name`` is dotted for fields inside a nested group. Ratio bounds and
    defaults are ``{"numerator", "denominator"}`` objects; an ``area`` value
    is ``{"pixels", "image_ratio"}``.
    """

    name: str
    kind: Literal["ratio", "number", "integer", "enum", "boolean", "area"]
    default: Any
    nullable: bool
    options: list[str] | None
    minimum: Any
    maximum: Any
    minimum_inclusive: bool | None
    maximum_inclusive: bool | None
    advanced: bool
    unit: str | None
    help: str | None


class StrategyCapability(BaseModel):
    """A selectable class or geometry strategy of a pipeline.

    A ``conditional`` strategy also depends on project evidence, reported by
    ``GET /projects/{project_id}/resolver-eligibility``. A non-null
    ``unavailable_reason`` means it cannot be selected; nothing is ever
    substituted for it.
    """

    id: str
    version: str
    conditional: bool
    unavailable_reason: UnavailableReasonName | None
    dependencies: dict[str, str | None]
    parameters: list[ParameterDescriptor]


class PipelineCapability(BaseModel):
    """The resolver pipeline of one task type, sent as the policy
    ``resolver``."""

    id: str
    version: str
    unavailable_reason: UnavailableReasonName | None
    class_strategies: list[StrategyCapability]
    geometry_strategies: list[StrategyCapability]
    parameters: list[ParameterDescriptor]
    review_thresholds: list[ParameterDescriptor]


class CapabilitiesResponse(BaseModel):
    """Limits and features that clients must discover at runtime."""

    supported_image_media_types: list[str] = Field(min_length=1)
    max_file_bytes: int = Field(gt=0)
    max_project_files: int = Field(gt=0)
    upload_chunk_bytes: int = Field(gt=0)
    upload_session_ttl_hours: int = Field(gt=0)
    max_import_file_bytes: int = Field(gt=0)
    supported_task_types: list[Literal["classification", "detection", "segmentation"]]
    supported_annotation_modes: list[Literal["single", "consensus"]]
    consensus_pipelines: dict[str, PipelineCapability]
    realtime_transport: Literal["websocket", "polling"]
