"""Deterministic development solution that exercises the loop without a model.

It is registered only in the development and test environments (D11). It
ranks the pool by a hash of the seed and each media id, and reports a
synthetic metric equal to the share of known images with at least one
accepted answer, so the same request always gives the same answer and the
metric grows with every iteration. For detection and segmentation it proposes
one object target in the middle of each image never queried before, and its
assistant answers a prompt with a box around it, so object targets and
assisted annotation can be exercised locally too.
"""

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dada_api.active_learning.contract import (
    MANIFEST_SCHEMA,
    TARGET_ORIGIN,
    AssistanceModel,
    AssistanceProvider,
    AssistanceRequest,
    AssistanceResult,
    BaseModelAdapter,
    BatchRequest,
    BatchResult,
    Evaluation,
    StageReporter,
    read_manifest,
    write_assistance_model,
)

SOLUTION_ID = "deterministic"
SOLUTION_VERSION = "1.0.0"
REGION_PADDING = 0.15


class DeterministicConfiguration(BaseModel):
    """Settings of the deterministic solution."""

    model_config = ConfigDict(extra="forbid")

    retain_helper_models: bool = Field(
        default=False,
        description="Keep the per-attempt artifact folders after a success.",
    )


def _rank(seed: int, media_id: str) -> str:
    """Return the stable sort key of one candidate."""
    return hashlib.sha256(f"{seed}:{media_id}".encode()).hexdigest()


def _geometry(task: str, box: list[float]) -> dict[str, Any]:
    """Return a box as a rectangle, or as a polygon for segmentation."""
    if task == "detection":
        return {"type": "rectangle", "coordinates": box}
    x, y, width, height = box
    ring = [x, y, x + width, y, x + width, y + height, x, y + height]
    return {"type": "polygon", "coordinates": [ring]}


def _target(task: str, image: dict[str, Any], roi_id: str) -> tuple[dict, dict]:
    """Propose the middle quarter of an image and its padded region."""
    width, height = image["width"], image["height"]
    box = [width / 4, height / 4, width / 2, height / 2]
    pad_x, pad_y = box[2] * REGION_PADDING, box[3] * REGION_PADDING
    roi = {
        "roi_id": roi_id,
        "bbox_xyxy": [
            max(0.0, box[0] - pad_x),
            max(0.0, box[1] - pad_y),
            min(float(width), box[0] + box[2] + pad_x),
            min(float(height), box[1] + box[3] + pad_y),
        ],
    }
    annotation: dict[str, Any] = {
        "id": roi_id,
        "image_id": image["id"],
        "roi_id": roi_id,
        "bbox": box,
        "origin": TARGET_ORIGIN,
    }
    if task == "segmentation":
        annotation["segmentation"] = _geometry(task, box)["coordinates"]
    return roi, annotation


class DeterministicAdapter(BaseModelAdapter):
    """Reproducible selection and evaluation for development and tests."""

    def select_batch(
        self, request: BatchRequest, report_stage: StageReporter | None = None
    ) -> BatchResult:
        """Evaluate synthetically and choose the first ranked candidates.

        Args:
            request: Immutable request of one attempt.
            report_stage: Optional progress callback.

        Returns:
            The evaluations and the chosen batch.
        """
        report = report_stage or (lambda _: None)
        report("training")
        training = read_manifest(request.media_root, request.training)
        pool = (
            read_manifest(request.media_root, request.pool)
            if request.pool is not None
            else None
        )
        labelled = {image["id"] for image in training["images"]}
        unlabelled = {
            image["id"] for image in (pool["images"] if pool is not None else [])
        }
        value = round(len(labelled) / max(len(labelled | unlabelled), 1), 6)

        evaluations: list[Evaluation] = []
        plan = request.evaluation
        stop = False
        if plan is not None:
            report("evaluating")
            evaluations.append(self._evaluation("validation", plan.metric, value))
            stop = plan.target is not None and value >= plan.target
            if plan.final or stop:
                evaluations.append(self._evaluation("test", plan.metric, value))
            if request.task != "classification":
                self._retain(request)

        if request.purpose == "final_evaluation" or stop or pool is None:
            return self._result(request, None, None, evaluations, stop)

        report("selecting")
        ranked = sorted(
            pool["images"], key=lambda image: _rank(request.seed, image["id"])
        )
        selection = {
            "info": {**pool["info"], "role": "selection", "schema": MANIFEST_SCHEMA},
            "categories": pool["categories"],
            "images": [],
            "annotations": [],
        }
        if request.task == "classification":
            selection["images"] = ranked[: request.requested_size]
            chosen = len(selection["images"])
        else:
            fresh = [image for image in ranked if not image["queried_rois"]]
            for index, image in enumerate(fresh[: request.requested_size]):
                roi, annotation = _target(
                    request.task, image, f"roi-{request.iteration}-{index}"
                )
                selection["images"].append(
                    {**image, "queried_rois": [*image["queried_rois"], roi]}
                )
                selection["annotations"].append(annotation)
            chosen = len(selection["annotations"])
        shortfall = (
            "insufficient_candidates" if chosen < request.requested_size else None
        )
        return self._result(request, selection, shortfall, evaluations, False)

    @staticmethod
    def _retain(request: BatchRequest) -> None:
        """Publish this iteration's synthetic target model for assistance."""
        write_assistance_model(
            request.assistance_dir,
            AssistanceModel(
                solution_id=SOLUTION_ID,
                solution_version=SOLUTION_VERSION,
                task=request.task,
                class_ids=[item.id for item in request.classes],
                iteration=request.iteration,
                request_id=request.request_id,
                weights=None,
            ),
        )

    @staticmethod
    def _evaluation(split: str, metric: str, value: float) -> Evaluation:
        """Build one synthetic evaluation."""
        return Evaluation(
            split=split,
            metric=metric,
            value=value,
            metrics={metric: value},
            model={"name": SOLUTION_ID, "version": SOLUTION_VERSION},
        )

    @staticmethod
    def _result(
        request: BatchRequest,
        selection: dict[str, Any] | None,
        shortfall: str | None,
        evaluations: list[Evaluation],
        stop: bool,
    ) -> BatchResult:
        """Build the result envelope."""
        return BatchResult(
            request_id=request.request_id,
            solution_id=SOLUTION_ID,
            solution_version=SOLUTION_VERSION,
            selection=selection,
            shortfall_reason=shortfall,
            stop_reason="metric_target" if stop else None,
            evaluations=evaluations,
            provenance={"ranking": "sha256(seed:media_id)", "seed": request.seed},
        )


class DeterministicAssistant(AssistanceProvider):
    """Answers a prompt with a box around it, without any model."""

    def suggest(self, request: AssistanceRequest) -> AssistanceResult:
        """Return the prompt box, or a quarter-size box centred on the point.

        Args:
            request: The prompt and its image.

        Returns:
            The suggestion in the task's geometry.
        """
        prompt = request.prompt.coordinates
        if request.prompt.type == "box":
            box = list(prompt)
        else:
            side = min(request.width, request.height) / 4
            x1 = min(max(prompt[0] - side / 2, 0.0), request.width - side)
            y1 = min(max(prompt[1] - side / 2, 0.0), request.height - side)
            box = [x1, y1, side, side]
        return AssistanceResult(
            request_id=request.request_id,
            status="suggestion",
            geometry=_geometry(request.task, box),
            score=1.0,
            model={
                "solution": SOLUTION_ID,
                "version": SOLUTION_VERSION,
                "iteration": request.model.iteration,
            },
        )
