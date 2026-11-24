"""Versioned batch-selection contract shared by every active-learning solution.

A solution receives one :class:`BatchRequest` and returns one
:class:`BatchResult`. It reads the immutable manifests the request names and
never touches the database, the HTTP layer, or canonical annotations. A
solution may also offer an :class:`AssistanceProvider` that turns an
annotator's prompt into a suggestion with its latest target model. Nothing
here imports FastAPI or the ORM.
"""

import hashlib
import json
import math
import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROTOCOL_VERSION = "learning.v1"
MANIFEST_SCHEMA = "dada-coco-pai/1"
STAGES = ("training", "evaluating", "selecting")
EXHAUSTIVELY_LABELED = "EXHAUSTIVELY_LABELED"
PARTIALLY_LABELED = "PARTIALLY_LABELED"
UNLABELED = "UNLABELED"
CONFIRMED_OBJECT = "CONFIRMED_OBJECT"
EXPLICIT_HARD_NEGATIVE = "EXPLICIT_HARD_NEGATIVE"
FULL_IMAGE_ORIGIN = "FULL_IMAGE"
TARGET_ORIGIN = "AL_OBJECT_QUERY"
ASSISTANCE_MODEL_FILE = "model.json"
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
    evaluation; for detection and segmentation it counts object targets.
    ``artifact_dir`` belongs to this attempt; ``state_dir`` keeps solution
    state across iterations of the same project. ``assistance_dir`` is where
    a solution that evaluates its target model keeps the latest one for
    assisted annotation (D18), described by an :class:`AssistanceModel`
    written last as ``model.json``.
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
    assistance_dir: str
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

    ``selection`` is a manifest in the request's format. For classification
    its ``images`` are the chosen media, best first, and it has no
    annotations. For detection and segmentation its ``annotations`` are the
    chosen object targets, best first: each names its ``image_id``, a
    ``roi_id`` found in that image's ``queried_rois`` with the padded
    ``bbox_xyxy`` context area, and the proposed ``bbox`` (``[x, y, width,
    height]``) or, for segmentation, ``segmentation`` rings. Its ``images``
    are the images those targets belong to. ``shortfall_reason`` explains a
    batch smaller than requested; ``stop_reason`` reports that the metric
    target was met, in which case there is no selection.
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


class AssistanceModel(Frozen):
    """The retained target model a solution leaves for assisted annotation.

    It is replaced at every evaluation and removed with its project (D18).
    ``weights`` is a file inside the assistance folder, when the solution
    needs one.
    """

    solution_id: str
    solution_version: str
    task: TaskName
    class_ids: list[str]
    iteration: int
    request_id: str
    weights: str | None


class Prompt(Frozen):
    """An annotator's point ``[x, y]`` or box ``[x, y, width, height]`` in
    canonical image pixels."""

    type: Literal["point", "box"]
    coordinates: list[float]


class AssistanceRequest(Frozen):
    """One prompt to answer with the retained target model."""

    request_id: str
    task: Literal["detection", "segmentation"]
    image_path: str
    width: int
    height: int
    prompt: Prompt
    model_dir: str
    model: AssistanceModel


class AssistanceResult(Frozen):
    """A suggestion in canonical pixels, or the answer that there is none.

    ``geometry`` is a ``rectangle`` for detection and a ``polygon`` for
    segmentation, in the document format; it is only shown to the annotator
    and never stored.
    """

    request_id: str
    status: Literal["suggestion", "no_suggestion"]
    geometry: dict[str, Any] | None = None
    score: float | None = None
    model: dict[str, Any] = Field(default_factory=dict)


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


class AssistanceProvider(ABC):
    """Answers assisted-annotation prompts with a solution's target model."""

    @abstractmethod
    def suggest(self, request: AssistanceRequest) -> AssistanceResult:
        """Return the suggestion for one prompt.

        Args:
            request: The prompt, its image, and the retained model.

        Returns:
            The suggestion, or ``no_suggestion`` when the model finds none.

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


def write_assistance_model(directory: str, model: AssistanceModel) -> None:
    """Publish the description of a retained target model, replacing the last.

    The description is renamed into place, so a reader sees either the
    previous model or the new one. A solution writes the weights it names
    before calling this.

    Args:
        directory: The request's ``assistance_dir``.
        model: The new retained model.
    """
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / f".{ASSISTANCE_MODEL_FILE}.{os.getpid()}.tmp"
    temporary.write_text(model.model_dump_json())
    os.replace(temporary, folder / ASSISTANCE_MODEL_FILE)


def read_assistance_model(directory: str) -> AssistanceModel | None:
    """Return the retained target model of an assistance folder, if any.

    Args:
        directory: The project's assistance folder.

    Returns:
        The description, or None when no readable model is retained.
    """
    try:
        return AssistanceModel.model_validate_json(
            (Path(directory) / ASSISTANCE_MODEL_FILE).read_text()
        )
    except (OSError, ValueError):
        return None
