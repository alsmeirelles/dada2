"""Closed resolver configurations carrying the first-release defaults of P6-02."""

from fractions import Fraction
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ADVANCED = {"advanced": True}
HALF = Fraction(1, 2)
DICE_DEFAULT = 2 / 3


class Closed(BaseModel):
    """A frozen configuration object that rejects unknown keys and non-finite
    numbers, so a stored configuration always means exactly one thing."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Ratio(Closed):
    """An exact vote ratio, compared by cross-multiplication and never as a
    float."""

    numerator: int = Field(ge=0, le=1000)
    denominator: int = Field(ge=1, le=1000)

    @model_validator(mode="after")
    def _at_most_one(self) -> "Ratio":
        """Reject ratios above one."""
        if self.numerator > self.denominator:
            raise ValueError("a ratio cannot exceed one")
        return self

    @property
    def fraction(self) -> Fraction:
        """The ratio as an exact fraction."""
        return Fraction(self.numerator, self.denominator)


class CategoricalVote(Closed):
    """One categorical vote per rater, decided by the configured rule."""

    strategy: Literal["categorical_vote"] = "categorical_vote"
    decision_rule: Literal["plurality", "strict_majority", "supermajority"] = Field(
        "supermajority",
        description="How the winning outcome is chosen before the support gate.",
    )


class MultilabelBinaryVote(Closed):
    """An explicit positive or negative vote for every class of the image."""

    strategy: Literal["multilabel_binary_vote"] = "multilabel_binary_vote"


class DirichletVote(Closed):
    """A Dirichlet posterior over the human vote counts with a symmetric
    prior."""

    strategy: Literal["dirichlet_vote"] = "dirichlet_vote"
    alpha: float = Field(
        0.5,
        ge=0.1,
        le=10,
        description="Prior count per outcome; 0.5 is the Jeffreys prior.",
        json_schema_extra=ADVANCED,
    )
    minimum_posterior: float = Field(
        0.9,
        ge=0.5,
        le=0.999,
        description="Probability the selected outcome must have of being the "
        "most likely one.",
    )


class ReliabilityWeightedVote(Closed):
    """Votes weighted by accuracies frozen from expert-adjudicated evidence."""

    strategy: Literal["reliability_weighted_vote"] = "reliability_weighted_vote"


class DawidSkene(Closed):
    """Votes read through annotator confusion matrices frozen from a
    calibration corpus."""

    strategy: Literal["dawid_skene"] = "dawid_skene"


ClassificationStrategy = Annotated[
    MultilabelBinaryVote | DirichletVote | ReliabilityWeightedVote | DawidSkene,
    Field(discriminator="strategy"),
]
CandidateStrategy = Annotated[
    CategoricalVote | DirichletVote | ReliabilityWeightedVote | DawidSkene,
    Field(discriminator="strategy"),
]


class CoordinateMedian(Closed):
    """The per-coordinate median of the supporting boxes."""

    strategy: Literal["coordinate_median"] = "coordinate_median"


class TrimmedMeanBox(Closed):
    """The per-coordinate mean after trimming the most extreme boxes."""

    strategy: Literal["trimmed_mean_box"] = "trimmed_mean_box"
    trim_fraction: float = Field(
        0.2,
        ge=0,
        le=0.4,
        description="Share of boxes trimmed from each end of every coordinate.",
    )


class WeightedBoxFusion(Closed):
    """Support-weighted coordinate fusion; human boxes weigh the same, so it
    is the coordinate mean."""

    strategy: Literal["weighted_box_fusion"] = "weighted_box_fusion"


BoxRefinement = Annotated[
    CoordinateMedian | TrimmedMeanBox | WeightedBoxFusion,
    Field(discriminator="strategy"),
]


class SegmentationMajorityVote(Closed):
    """crowd-kit's pixel majority vote over the supporting masks."""

    strategy: Literal["segmentation_majority_vote"] = "segmentation_majority_vote"


class SegmentationEM(Closed):
    """crowd-kit's expectation-maximization mask aggregation."""

    strategy: Literal["segmentation_em"] = "segmentation_em"


class SegmentationRASA(Closed):
    """crowd-kit's RASA mask aggregation."""

    strategy: Literal["segmentation_rasa"] = "segmentation_rasa"


class Staple(Closed):
    """DADA's native STAPLE estimate over the supporting masks."""

    strategy: Literal["staple"] = "staple"
    pixel_threshold: float = Field(
        0.5,
        gt=0,
        lt=1,
        description="Posterior probability at which a pixel joins the mask.",
    )


MaskRefinement = Annotated[
    SegmentationMajorityVote | SegmentationEM | SegmentationRASA | Staple,
    Field(discriminator="strategy"),
]


class AreaThreshold(Closed):
    """An area limit stated in pixels and as a share of the image; a region is
    affected only when it is below both."""

    pixels: int = Field(ge=1)
    image_ratio: float = Field(gt=0, lt=1)


class PostProcessing(Closed):
    """Optional mask clean-up. Every step is off unless configured, because
    each one can change the topology of an accepted instance."""

    remove_components_below: AreaThreshold | None = Field(
        None,
        description="Remove disconnected components smaller than this area.",
        json_schema_extra=ADVANCED,
    )
    fill_holes_below: AreaThreshold | None = Field(
        None,
        description="Fill holes smaller than this area.",
        json_schema_extra=ADVANCED,
    )
    simplify_tolerance: float | None = Field(
        None,
        gt=0,
        le=10,
        description="Polygon simplification tolerance.",
        json_schema_extra={"advanced": True, "unit": "px"},
    )


class SupportThresholds(Closed):
    """The common class-quality gate: the winning outcome's share of the
    valid votes."""

    minimum_support: Ratio = Field(
        Ratio(numerator=2, denominator=3),
        description="Share of valid votes the winning outcome needs; it must "
        "exceed one half.",
        json_schema_extra={
            "minimum": {"numerator": 1, "denominator": 2},
            "minimum_inclusive": False,
            "maximum": {"numerator": 1, "denominator": 1},
            "maximum_inclusive": True,
        },
    )

    @model_validator(mode="after")
    def _above_half(self) -> "SupportThresholds":
        """Enforce the hard majority floor that no project may weaken."""
        if self.minimum_support.fraction <= HALF:
            raise ValueError("minimum_support must exceed one half")
        return self


class ClassificationParameters(Closed):
    """Settings of ``statistical_class_consensus``."""

    class_strategy: ClassificationStrategy = MultilabelBinaryVote()


class DetectionParameters(Closed):
    """Settings of ``two_stage_detection_consensus``."""

    class_strategy: CandidateStrategy = CategoricalVote()
    matching_iou: float = Field(
        0.5,
        gt=0,
        le=1,
        description="Minimum IoU for two raters' boxes to describe one object.",
    )
    box_refinement: BoxRefinement = CoordinateMedian()


class DetectionThresholds(SupportThresholds):
    """Detection gates: class support plus box agreement."""

    minimum_median_iou: float = Field(
        0.5,
        gt=0,
        le=1,
        description="Minimum median pairwise IoU of an accepted object's boxes.",
    )


class SegmentationParameters(Closed):
    """Settings of ``two_stage_segmentation_consensus``."""

    class_strategy: CandidateStrategy = CategoricalVote()
    matching_metric: Literal["iou", "dice"] = Field(
        "iou",
        description="Overlap measure used to match masks and to gate their agreement.",
    )
    matching_threshold: float = Field(
        0.5,
        gt=0,
        le=1,
        description="Minimum overlap for two raters' masks to describe one instance.",
    )
    mask_refinement: MaskRefinement = SegmentationMajorityVote()
    post_processing: PostProcessing = PostProcessing()

    @model_validator(mode="before")
    @classmethod
    def _metric_default(cls, data: Any) -> Any:
        """Default a Dice match to 2/3, the equivalent of IoU 0.5."""
        if (
            isinstance(data, dict)
            and data.get("matching_metric") == "dice"
            and "matching_threshold" not in data
        ):
            return {**data, "matching_threshold": DICE_DEFAULT}
        return data


class SegmentationThresholds(SupportThresholds):
    """Segmentation gates: class support plus mask agreement."""

    minimum_median_overlap: float = Field(
        0.5,
        gt=0,
        le=1,
        description="Minimum median pairwise overlap, in the matching metric, "
        "of an accepted instance's masks.",
    )


class ClassificationConfiguration(Closed):
    """A complete classification resolver configuration."""

    parameters: ClassificationParameters = ClassificationParameters()
    review_thresholds: SupportThresholds = SupportThresholds()


class DetectionConfiguration(Closed):
    """A complete detection resolver configuration."""

    parameters: DetectionParameters = DetectionParameters()
    review_thresholds: DetectionThresholds = DetectionThresholds()


class SegmentationConfiguration(Closed):
    """A complete segmentation resolver configuration."""

    parameters: SegmentationParameters = SegmentationParameters()
    review_thresholds: SegmentationThresholds = SegmentationThresholds()

    @model_validator(mode="before")
    @classmethod
    def _overlap_default(cls, data: Any) -> Any:
        """Default the agreement gate to the Dice equivalent when matching by
        Dice."""
        if not isinstance(data, dict):
            return data
        parameters = data.get("parameters") or {}
        thresholds = data.get("review_thresholds") or {}
        if (
            parameters.get("matching_metric") == "dice"
            and "minimum_median_overlap" not in thresholds
        ):
            thresholds = {**thresholds, "minimum_median_overlap": DICE_DEFAULT}
            return {**data, "review_thresholds": thresholds}
        return data
