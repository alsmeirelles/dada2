"""DADA settings, the per-run configuration, and the candidate record (spec 4.1).

:class:`DADASettings` is what a project stores and the API validates: it is
imported by the catalog, so this module depends on pydantic alone. The task
and the acquisition budget come from each batch request, which turns the
settings into a :class:`DADAAlConfig`.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

if TYPE_CHECKING:
    import numpy as np


class TaskType(StrEnum):
    """The computer-vision task of a project."""

    CLASSIFICATION = "classification"
    DETECTION = "detection"
    SEGMENTATION = "segmentation"


class UncertaintyMethod(StrEnum):
    """How uncertainty is measured for a task."""

    PRE_NMS = "pre_nms"
    TTA_JITTER = "tta_jitter"
    DEEP_ENSEMBLE = "deep_ensemble"
    TTA_MULTIVIEW = "tta_multiview"


class PAITrainingMode(StrEnum):
    """How partially annotated images are trained on (spec 4.6)."""

    MODE_1_LOSS_MASK = "mode_1_loss_mask"
    MODE_2_VISUAL_MASK = "mode_2_visual_mask"


TASK_DEFAULTS: dict[TaskType, tuple[str, str, UncertaintyMethod]] = {
    TaskType.CLASSIFICATION: (
        "efficientnet_b1",
        "efficientnet_b5",
        UncertaintyMethod.DEEP_ENSEMBLE,
    ),
    TaskType.DETECTION: ("yolo26n.pt", "yolo26x.pt", UncertaintyMethod.PRE_NMS),
    TaskType.SEGMENTATION: (
        "yolo26n-seg.pt",
        "yolo26x-seg.pt",
        UncertaintyMethod.PRE_NMS,
    ),
}
TASK_METHODS: dict[TaskType, frozenset[UncertaintyMethod]] = {
    TaskType.CLASSIFICATION: frozenset(
        {UncertaintyMethod.DEEP_ENSEMBLE, UncertaintyMethod.TTA_MULTIVIEW}
    ),
    TaskType.DETECTION: frozenset(
        {UncertaintyMethod.PRE_NMS, UncertaintyMethod.TTA_JITTER}
    ),
    TaskType.SEGMENTATION: frozenset(
        {UncertaintyMethod.PRE_NMS, UncertaintyMethod.TTA_JITTER}
    ),
}
TASK_WEIGHTS: dict[TaskType, tuple[float, float, float | None]] = {
    TaskType.CLASSIFICATION: (1.0, 0.0, None),
    TaskType.DETECTION: (0.50, 0.50, None),
    TaskType.SEGMENTATION: (0.40, 0.30, 0.30),
}
ADVANCED = {"advanced": True}
YOLO_MODEL = re.compile(r"^yolo(11|12|26)[nsmlx](-seg)?\.pt$")
TIMM_MODEL = re.compile(r"^[a-z0-9][a-z0-9_.\-]*$")
WEIGHT_TOLERANCE = 1e-6


class DADASettings(BaseModel):
    """The configuration a project chooses for DADA.

    Omitted model names, uncertainty method, and uncertainty weights are
    resolved from the task, given as validation context, before the
    combination is checked: classification takes ``timm`` models and the
    ensemble or multi-view methods; detection and segmentation take YOLO11,
    YOLO12, or YOLO26 checkpoints (``-seg`` for segmentation) and the pre-NMS
    or TTA methods. The weights must sum to one over the task's terms.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    target_model_name: str | None = Field(
        default=None, description="Target model; the task default when omitted."
    )
    proxy_model_name: str | None = Field(
        default=None, description="Proxy model; the task default when omitted."
    )
    uncertainty_method: UncertaintyMethod | None = Field(
        default=None, description="Uncertainty method; the task default when omitted."
    )
    pai_training_mode: PAITrainingMode = Field(
        default=PAITrainingMode.MODE_1_LOSS_MASK,
        description="How partially annotated images are trained on.",
    )
    retain_helper_models: bool = Field(
        default=False, description="Keep proxy and helper checkpoints after use."
    )
    cls_ensemble_size: int = Field(
        default=3,
        ge=2,
        le=10,
        description="Proxies trained for the deep ensemble.",
        json_schema_extra=ADVANCED,
    )
    cls_tta_views: int = Field(
        default=5,
        ge=2,
        le=5,
        description="Geometric views of multi-view TTA.",
        json_schema_extra=ADVANCED,
    )
    cls_entropy_blend: float = Field(
        default=0.20,
        ge=0,
        le=1,
        description="Weight of entropy blended with BALD.",
        json_schema_extra=ADVANCED,
    )
    image_subpool_size: int = Field(
        default=2000,
        ge=1,
        description="Images scored per subpool.",
        json_schema_extra=ADVANCED,
    )
    subpool_renewal_interval: int = Field(
        default=2,
        ge=1,
        description="Iterations a subpool is reused.",
        json_schema_extra=ADVANCED,
    )
    max_object_candidates: int = Field(
        default=15000,
        ge=1,
        description="Ceiling of object candidates clustered.",
        json_schema_extra=ADVANCED,
    )
    candidate_conf_floor: float = Field(
        default=0.08,
        gt=0,
        lt=1,
        description="Least confidence of a candidate.",
        json_schema_extra=ADVANCED,
    )
    proposal_cluster_iou_thresh: float = Field(
        default=0.50,
        gt=0,
        lt=1,
        description="IoU grouping pre-NMS proposals.",
        json_schema_extra=ADVANCED,
    )
    annotated_iou_dedup_thresh: float = Field(
        default=0.50,
        gt=0,
        le=1,
        description="IoU that discards a known object.",
        json_schema_extra=ADVANCED,
    )
    pca_components: int = Field(
        default=50,
        ge=1,
        description="Dimensions kept by PCA.",
        json_schema_extra=ADVANCED,
    )
    num_clusters: int = Field(
        default=20, ge=1, description="K of the k-means.", json_schema_extra=ADVANCED
    )
    cls_weight: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Weight of class uncertainty.",
        json_schema_extra=ADVANCED,
    )
    loc_weight: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Weight of localization uncertainty.",
        json_schema_extra=ADVANCED,
    )
    mask_weight: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Weight of mask uncertainty.",
        json_schema_extra=ADVANCED,
    )
    yolo26_dual_head_weight: float = Field(
        default=0.40,
        ge=0,
        le=1,
        description="Weight of YOLO26 head disagreement.",
        json_schema_extra=ADVANCED,
    )
    shrinkage_kappa: float = Field(
        default=2.0,
        gt=0,
        description="Shrinkage constant for lone proposals.",
        json_schema_extra=ADVANCED,
    )
    mask_boundary_band_px: int = Field(
        default=3,
        ge=1,
        description="Radius of the mask boundary band.",
        json_schema_extra={"advanced": True, "unit": "px"},
    )
    roi_context_padding: float = Field(
        default=0.15,
        ge=0,
        le=1,
        description="Margin of the region around a target.",
        json_schema_extra=ADVANCED,
    )
    proxy_epochs: int = Field(
        default=10, ge=1, description="Training epochs of each proxy."
    )
    target_epochs: int = Field(
        default=50, ge=1, description="Training epochs of the target model."
    )
    batch_size: int = Field(default=16, ge=1, description="Training batch size.")
    image_size: int | None = Field(
        default=None,
        ge=32,
        description="Input size; 640 for YOLO and the target's own for timm.",
        json_schema_extra={"unit": "px"},
    )

    @model_validator(mode="after")
    def resolve_for_task(self, info: ValidationInfo) -> "DADASettings":
        """Fill the task defaults and refuse settings the task cannot use."""
        task = (info.context or {}).get("task")
        if task is None:
            return self
        task = TaskType(task)
        proxy, target, method = TASK_DEFAULTS[task]
        self.proxy_model_name = self.proxy_model_name or proxy
        self.target_model_name = self.target_model_name or target
        self.uncertainty_method = self.uncertainty_method or method
        if self.uncertainty_method not in TASK_METHODS[task]:
            raise ValueError(
                f"{self.uncertainty_method.value} does not apply to {task.value}"
            )
        for name in (self.proxy_model_name, self.target_model_name):
            if not _model_fits(task, name):
                raise ValueError(f"{name} is not a {task.value} model")

        cls, loc, mask = TASK_WEIGHTS[task]
        if task is TaskType.CLASSIFICATION:
            self.cls_weight, self.loc_weight, self.mask_weight = cls, loc, mask
            return self
        if task is TaskType.DETECTION and self.mask_weight not in (None, 0):
            raise ValueError("mask_weight applies to segmentation only")
        self.cls_weight = cls if self.cls_weight is None else self.cls_weight
        self.loc_weight = loc if self.loc_weight is None else self.loc_weight
        if task is TaskType.SEGMENTATION:
            self.mask_weight = mask if self.mask_weight is None else self.mask_weight
        else:
            self.mask_weight = None
        total = self.cls_weight + self.loc_weight + (self.mask_weight or 0.0)
        if abs(total - 1.0) > WEIGHT_TOLERANCE:
            raise ValueError("the uncertainty weights must sum to one")
        return self


def _model_fits(task: TaskType, name: str) -> bool:
    """Return whether a model name belongs to the task's model family."""
    match = YOLO_MODEL.match(name)
    if task is TaskType.CLASSIFICATION:
        return (
            match is None
            and not name.startswith("yolo")
            and bool(TIMM_MODEL.match(name))
        )
    if match is None:
        return False
    return (match.group(2) is not None) == (task is TaskType.SEGMENTATION)


class DADAAlConfig(DADASettings):
    """The resolved configuration of one run.

    ``acquisition_budget_q`` is the request's batch size: objects for
    detection and segmentation, images for classification, and zero for the
    final evaluation, which selects nothing.
    """

    task: TaskType
    acquisition_budget_q: int = Field(ge=0)

    @classmethod
    def for_request(
        cls, settings: dict[str, Any], task: str, budget: int
    ) -> "DADAAlConfig":
        """Resolve a project's stored settings for one request.

        Args:
            settings: The run's configuration.
            task: The project's task.
            budget: The request's batch size.

        Returns:
            The run configuration.
        """
        return cls.model_validate(
            {**settings, "task": task, "acquisition_budget_q": budget},
            context={"task": task},
        )


@dataclass
class CandidateItem:
    """One evaluated unit: a whole image for classification, a candidate
    object for detection and segmentation.

    Attributes:
        candidate_id: Deterministic UUID of the candidate.
        image_id: Media identifier of its image.
        bbox_xyxy: Box in canonical pixels, None for classification.
        segmentation: Polygon rings in canonical pixels, for segmentation.
        pred_class_probs: Class probabilities, shape ``(C,)``.
        cls_uncertainty: Class uncertainty in ``[0, 1]``.
        spatial_uncertainty: Localization and mask uncertainty in ``[0, 1]``.
        total_uncertainty: Combined uncertainty in ``[0, 1]``.
        feature_vector: L2-normalized embedding, shape ``(D,)``.
    """

    candidate_id: str
    image_id: str
    bbox_xyxy: tuple[float, float, float, float] | None
    segmentation: list[list[float]] | None
    pred_class_probs: "np.ndarray"
    cls_uncertainty: float
    spatial_uncertainty: float
    total_uncertainty: float
    feature_vector: "np.ndarray"
