"""Versioned batch-selection contract shared by every active-learning solution.

A solution receives one :class:`BatchRequest` and returns one
:class:`BatchResult`. It reads the immutable manifests the request names and
never touches the database, the HTTP layer, or canonical annotations. Nothing
here imports FastAPI or the ORM.
"""

import hashlib
import json
import math
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROTOCOL_VERSION = "learning.v1"
MANIFEST_SCHEMA = "dada-coco-pai/1"
STAGES = ("training", "evaluating", "selecting")
TaskName = Literal["classification", "detection", "segmentation"]
SplitName = Literal["validation", "test"]
StageReporter = Callable[[str], None]


class Frozen(BaseModel):
    """An immutable message that rejects unknown fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ManifestRef(Frozen):
    """One immutable manifest file, relative to the request's media root."""

    sha256: str = Field(min_length=64, max_length=64)
    path: str


class ClassEntry(Frozen):
    """One project class and the index its manifests use as category id."""

    id: str
    index: int
    name: str


class EvaluationPlan(Frozen):
    """The target-model evaluation a run must perform before selecting.

    ``test`` is given when the run is final or when reaching ``target`` would
    stop the loop; it is never used to choose anything.
    """

    metric: str
    target: float | None
    final: bool
    validation: ManifestRef
    test: ManifestRef | None


class BatchRequest(Frozen):
    """Everything a solution needs to evaluate and choose one batch.

    ``requested_size`` is authoritative (P7-09) and is zero for the final
    evaluation. ``artifact_dir`` belongs to this attempt; ``state_dir`` keeps
    solution state across iterations of the same project.
    """

    protocol_version: Literal["learning.v1"] = PROTOCOL_VERSION
    request_id: str
    attempt: int = Field(ge=1)
    project_id: str
    iteration: int = Field(ge=1)
    purpose: Literal["selection", "final_evaluation"]
    solution_id: str
    solution_version: str
    configuration: dict[str, Any]
    task: TaskName
    classes: list[ClassEntry]
    requested_size: int = Field(ge=0)
    seed: int
    media_root: str
    training: ManifestRef
    pool: ManifestRef | None
    evaluation: EvaluationPlan | None
    artifact_dir: str
    state_dir: str
    retain_helper_models: bool


class Evaluation(Frozen):
    """One target-model measurement on one held-out split."""

    split: SplitName
    metric: str
    value: float = Field(ge=0, le=1)
    metrics: dict[str, float]
    model: dict[str, Any]

    @field_validator("value")
    @classmethod
    def reject_non_finite(cls, value: float) -> float:
        """Refuse NaN and infinities before any comparison."""
        if not math.isfinite(value):
            raise ValueError("value must be finite")
        return value


class BatchResult(Frozen):
    """A solution's answer: its evaluations and, unless it stopped, a batch.

    ``selection`` is a manifest in the request's format whose ``images`` are
    the chosen media, best first. ``shortfall_reason`` explains a batch
    smaller than requested; ``stop_reason`` reports that the metric target was
    met, in which case there is no selection.
    """

    protocol_version: Literal["learning.v1"] = PROTOCOL_VERSION
    request_id: str
    solution_id: str
    solution_version: str
    selection: dict[str, Any] | None
    shortfall_reason: str | None = None
    stop_reason: Literal["metric_target"] | None = None
    evaluations: list[Evaluation] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class AdapterError(Exception):
    """A typed, permanent failure reported by a solution."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class BaseModelAdapter(ABC):
    """The single operation every active-learning solution implements."""

    @abstractmethod
    def select_batch(
        self, request: BatchRequest, report_stage: StageReporter | None = None
    ) -> BatchResult:
        """Evaluate as planned and choose the next batch.

        Args:
            request: Immutable request of one attempt.
            report_stage: Optional callback receiving ``training``,
                ``evaluating``, or ``selecting`` as the work progresses.

        Returns:
            The evaluations and the chosen batch.

        Raises:
            AdapterError: For a typed permanent failure.
        """


def canonical_bytes(manifest: dict[str, Any]) -> bytes:
    """Return a manifest's canonical JSON encoding.

    Args:
        manifest: Manifest to encode.

    Returns:
        Sorted, compact UTF-8 JSON.
    """
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()


def read_manifest(media_root: str, ref: ManifestRef) -> dict[str, Any]:
    """Read a manifest and refuse it when its bytes no longer match its digest.

    Args:
        media_root: Absolute media root of the request.
        ref: Manifest to read.

    Returns:
        The parsed manifest.

    Raises:
        AdapterError: ``invalid_input`` when the file changed or is missing.
    """
    path = Path(media_root) / ref.path
    try:
        data = path.read_bytes()
    except OSError as error:
        raise AdapterError(
            "invalid_input", f"manifest {ref.sha256} is missing"
        ) from error
    if hashlib.sha256(data).hexdigest() != ref.sha256:
        raise AdapterError("invalid_input", f"manifest {ref.sha256} changed")
    return json.loads(data)
