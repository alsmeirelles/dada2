"""The DADA active-learning step of one request (spec 5, D8).

When the request plans an evaluation, the target model is trained on the
accepted training data and measured on validation, and on test when the run
is final or the metric target was reached; the trained target model then
becomes the project's assistance model. Unless the run stops there, a proxy
is trained, the image subpool is scored, the gatekeeper removes known
objects, and DADA selects the batch, returned as a selection manifest in the
pool's format with padded regions around object targets.
"""

import copy
import shutil
from pathlib import Path
from typing import Any

import torch

from dada_api.active_learning.contract import (
    TARGET_ORIGIN,
    AssistanceModel,
    BatchRequest,
    BatchResult,
    Evaluation,
    StageReporter,
    read_assistance_model,
    read_manifest,
    write_assistance_model,
)
from dada_api.active_learning.dada_al.acquisition import dada_selector
from dada_api.active_learning.dada_al.acquisition.subpool_manager import (
    SubpoolManager,
)
from dada_api.active_learning.dada_al.config.schema import (
    CandidateItem,
    DADAAlConfig,
    TaskType,
    UncertaintyMethod,
)
from dada_api.active_learning.dada_al.dataset import pai_schema
from dada_api.active_learning.dada_al.models.timm_adapter import (
    TimmClassificationAdapter,
)
from dada_api.active_learning.dada_al.models.yolo_adapter import YoloAdapter
from dada_api.active_learning.dada_al.uncertainty.cls_extractor import (
    ClassificationExtractor,
)
from dada_api.active_learning.dada_al.uncertainty.pre_nms_extractor import (
    PreNMSExtractor,
)
from dada_api.active_learning.dada_al.uncertainty.tta_extractor import TTAExtractor

SOLUTION_ID = "dada"
SOLUTION_VERSION = "1.0.0"


class ActiveLearningOrchestrator:
    """Runs one DADA iteration for one batch request."""

    def __init__(
        self, request: BatchRequest, config: DADAAlConfig, report: StageReporter
    ) -> None:
        """Prepare the adapters of the request's task.

        Args:
            request: Immutable request of one attempt.
            config: Resolved run configuration.
            report: Stage callback.
        """
        self.request = request
        self.config = config
        self.report = report
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.artifacts = Path(request.artifact_dir)
        self.state = Path(request.state_dir)
        if config.task is TaskType.CLASSIFICATION:
            self.adapter: Any = TimmClassificationAdapter(
                request.media_root,
                len(request.classes),
                config.target_model_name,
                image_size=config.image_size,
                batch_size=config.batch_size,
                device=self.device,
            )
        else:
            retained = read_assistance_model(request.assistance_dir)
            teacher = (
                Path(request.assistance_dir) / retained.weights
                if retained is not None and retained.weights
                else None
            )
            self.adapter = YoloAdapter(
                config.task.value,
                request.media_root,
                self.state / "weights",
                image_size=config.image_size,
                batch_size=config.batch_size,
                device=self.device,
                mode=config.pai_training_mode,
                teacher=teacher,
            )

    def step(self) -> BatchResult:
        """Evaluate when planned, then select unless the run stops.

        Returns:
            The evaluations, the selection, and their provenance.
        """
        request = self.request
        training = pai_schema.load(request.media_root, request.training)
        provenance: dict[str, Any] = {
            "seed": request.seed,
            "proxy_model": self.config.proxy_model_name,
            "target_model": self.config.target_model_name,
            "uncertainty_method": self.config.uncertainty_method.value,
        }
        if self.config.task is TaskType.CLASSIFICATION:
            provenance["excluded_images"] = sum(
                1
                for image in training.images
                if len(
                    {
                        annotation.category_id
                        for annotation in training.annotations
                        if annotation.image_id == image.id
                    }
                )
                != 1
            )
        evaluations: list[Evaluation] = []
        stop = False
        if request.evaluation is not None:
            evaluations, stop = self._evaluate(training)
        if request.purpose == "final_evaluation" or stop or request.pool is None:
            return self._result(None, None, evaluations, stop, provenance)
        selection, shortfall = self._select(training, provenance)
        return self._result(selection, shortfall, evaluations, False, provenance)

    def _evaluate(self, training: pai_schema.PAIManifest) -> tuple[list, bool]:
        """Train and measure the target model as the plan asks (P7-03)."""
        plan = self.request.evaluation
        self.report("training")
        checkpoint = self.adapter.train(
            self.config.target_model_name,
            training,
            epochs=self.config.target_epochs,
            seed=self.request.seed,
            output=self.artifacts / "target",
            name="target",
        )
        self.report("evaluating")
        model = {
            "solution": SOLUTION_ID,
            "version": SOLUTION_VERSION,
            "name": self.config.target_model_name,
            "iteration": self.request.iteration,
            "request_id": self.request.request_id,
            "training_snapshot": self.request.training.sha256,
        }
        evaluations = [self._measure(checkpoint, "validation", plan.validation, model)]
        stop = plan.target is not None and evaluations[0].value >= plan.target
        if plan.final or stop:
            evaluations.append(self._measure(checkpoint, "test", plan.test, model))
        if self.config.task is not TaskType.CLASSIFICATION:
            self._retain(checkpoint)
        return evaluations, stop

    def _measure(
        self, checkpoint: Path, split: str, ref: Any, model: dict[str, Any]
    ) -> Evaluation:
        """Measure the target model on one held-out split."""
        metric = self.request.evaluation.metric
        values = self.adapter.evaluate(
            checkpoint,
            pai_schema.load(self.request.media_root, ref),
            metric,
            self.artifacts / split,
        )
        return Evaluation(
            split=split,
            metric=metric,
            value=values[metric],
            metrics=values,
            model={**model, "snapshot": ref.sha256},
        )

    def _retain(self, checkpoint: Path) -> None:
        """Make the new target model the project's assistance model (D18)."""
        folder = Path(self.request.assistance_dir)
        folder.mkdir(parents=True, exist_ok=True)
        name = f"target-{self.request.iteration}-{self.request.attempt}.pt"
        shutil.copyfile(checkpoint, folder / name)
        write_assistance_model(
            str(folder),
            AssistanceModel(
                solution_id=SOLUTION_ID,
                solution_version=SOLUTION_VERSION,
                task=self.config.task.value,
                class_ids=[item.id for item in self.request.classes],
                iteration=self.request.iteration,
                request_id=self.request.request_id,
                weights=name,
            ),
        )
        for stale in folder.glob("target-*.pt"):
            if stale.name != name:
                stale.unlink()

    def _select(
        self, training: pai_schema.PAIManifest, provenance: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        """Train the proxy, score the subpool, and choose the batch."""
        request, config = self.request, self.config
        pool = read_manifest(request.media_root, request.pool)
        manager = SubpoolManager(request.state_dir, config)
        subpool = [
            pai_schema.PAIImage.model_validate(image)
            for image in manager.image_subpool(
                pool["images"], request.iteration, request.seed
            )
        ]
        self.report("training")
        output = self.artifacts / "proxy"
        if config.task is TaskType.CLASSIFICATION:
            ensemble = config.uncertainty_method is UncertaintyMethod.DEEP_ENSEMBLE
            checkpoints = self.adapter.train_many(
                config.proxy_model_name,
                training,
                seeds=list(range(1, config.cls_ensemble_size + 1)) if ensemble else [1],
                epochs=config.proxy_epochs,
                output=output,
                name="proxy",
            )
            self.report("selecting")
            candidates = ClassificationExtractor(self.adapter, config).extract(
                checkpoints, subpool, request.media_root
            )
        else:
            checkpoint = self.adapter.train(
                config.proxy_model_name,
                training,
                epochs=config.proxy_epochs,
                seed=request.seed,
                output=output,
                name="proxy",
            )
            self.report("selecting")
            extractor = (
                PreNMSExtractor
                if config.uncertainty_method is UncertaintyMethod.PRE_NMS
                else TTAExtractor
            )
            candidates = [
                candidate
                for candidate in extractor(self.adapter, config).extract(
                    self.adapter.load(checkpoint), subpool, request.media_root
                )
                if candidate.bbox_xyxy[2] - candidate.bbox_xyxy[0]
                >= 1 / pai_schema.GRID
                and candidate.bbox_xyxy[3] - candidate.bbox_xyxy[1]
                >= 1 / pai_schema.GRID
            ]
        candidates = manager.gatekeeper(candidates, pool)
        chosen, shortfall = dada_selector.select(candidates, config, request.seed)
        provenance.update(subpool_images=len(subpool), candidates=len(candidates))
        return self._manifest(pool, chosen), shortfall

    def _manifest(
        self, pool: dict[str, Any], chosen: list[CandidateItem]
    ) -> dict[str, Any]:
        """Write the chosen images or targets in the pool's format."""
        by_id = {image["id"]: image for image in pool["images"]}
        selection = {
            "info": {**pool["info"], "role": "selection"},
            "categories": pool["categories"],
            "images": [],
            "annotations": [],
        }
        if self.config.task is TaskType.CLASSIFICATION:
            selection["images"] = [by_id[candidate.image_id] for candidate in chosen]
            return selection
        images: dict[str, dict[str, Any]] = {}
        for index, candidate in enumerate(chosen):
            source = by_id[candidate.image_id]
            image = images.setdefault(candidate.image_id, copy.deepcopy(source))
            roi_id = f"roi-{self.request.iteration}-{index}"
            annotation, region = self._target(candidate, source, roi_id)
            image["queried_rois"].append(
                {
                    "roi_id": roi_id,
                    "bbox_xyxy": region,
                    "al_iteration": self.request.iteration,
                }
            )
            selection["annotations"].append(annotation)
        selection["images"] = list(images.values())
        return selection

    def _target(
        self, candidate: CandidateItem, image: dict[str, Any], roi_id: str
    ) -> tuple[dict[str, Any], list[float]]:
        """Describe one target and its padded region on the 1/64 grid."""
        width, height = image["width"], image["height"]
        x1, y1, x2, y2 = (
            pai_schema.snap(candidate.bbox_xyxy[0], 0, width, -1),
            pai_schema.snap(candidate.bbox_xyxy[1], 0, height, -1),
            pai_schema.snap(candidate.bbox_xyxy[2], 0, width, 1),
            pai_schema.snap(candidate.bbox_xyxy[3], 0, height, 1),
        )
        annotation: dict[str, Any] = {
            "id": roi_id,
            "image_id": candidate.image_id,
            "roi_id": roi_id,
            "category_id": int(candidate.pred_class_probs.argmax()),
            "bbox": [x1, y1, x2 - x1, y2 - y1],
            "origin": TARGET_ORIGIN,
            "uncertainty": candidate.total_uncertainty,
        }
        if candidate.segmentation is not None:
            rings = candidate.segmentation
            annotation["segmentation"] = rings
            xs = [value for ring in rings for value in ring[0::2]]
            ys = [value for ring in rings for value in ring[1::2]]
            x1, y1, x2, y2 = min(x1, *xs), min(y1, *ys), max(x2, *xs), max(y2, *ys)
        region = dada_selector.queried_roi(
            (x1, y1, x2, y2), self.config.roi_context_padding, width, height
        )
        region = [
            pai_schema.snap(region[0], 0, x1, -1),
            pai_schema.snap(region[1], 0, y1, -1),
            pai_schema.snap(region[2], x2, width, 1),
            pai_schema.snap(region[3], y2, height, 1),
        ]
        return annotation, region

    def _result(
        self,
        selection: dict[str, Any] | None,
        shortfall: str | None,
        evaluations: list[Evaluation],
        stop: bool,
        provenance: dict[str, Any],
    ) -> BatchResult:
        """Build the result envelope."""
        return BatchResult(
            request_id=self.request.request_id,
            solution_id=SOLUTION_ID,
            solution_version=SOLUTION_VERSION,
            selection=selection,
            shortfall_reason=shortfall,
            stop_reason="metric_target" if stop else None,
            evaluations=evaluations,
            provenance=provenance,
        )
