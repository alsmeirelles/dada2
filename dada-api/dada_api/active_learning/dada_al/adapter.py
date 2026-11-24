"""The API-facing entry points of DADA: the batch-selection adapter and the
assisted-annotation provider.

They are the only classes the catalog names. The selection adapter resolves
the project's settings for the request and runs one orchestrator step; the
provider answers a prompt with the retained target model (D18): a box picks
the instance that overlaps it most, a point the most confident instance that
contains it.
"""

from pathlib import Path

import numpy as np

from dada_api.active_learning.contract import (
    AdapterError,
    AssistanceProvider,
    AssistanceRequest,
    AssistanceResult,
    BaseModelAdapter,
    BatchRequest,
    BatchResult,
    StageReporter,
)
from dada_api.active_learning.dada_al.config.schema import DADAAlConfig
from dada_api.active_learning.dada_al.dataset.pai_schema import snap
from dada_api.active_learning.dada_al.pipeline.al_loop import (
    SOLUTION_ID,
    SOLUTION_VERSION,
    ActiveLearningOrchestrator,
)


class DADAAdapter(BaseModelAdapter):
    """DADA behind the shared batch-selection contract."""

    def select_batch(
        self, request: BatchRequest, report_stage: StageReporter | None = None
    ) -> BatchResult:
        """Evaluate as planned and choose the next batch with DADA.

        Args:
            request: Immutable request of one attempt.
            report_stage: Optional progress callback.

        Returns:
            The evaluations and the chosen batch.
        """
        config = DADAAlConfig.for_request(
            request.configuration, request.task, request.requested_size
        )
        return ActiveLearningOrchestrator(
            request, config, report_stage or (lambda _: None)
        ).step()


class DADAAssistant(AssistanceProvider):
    """Suggests a box or mask with the project's retained YOLO target model."""

    def suggest(self, request: AssistanceRequest) -> AssistanceResult:
        """Answer one prompt.

        Args:
            request: The prompt, its image, and the retained model.

        Returns:
            The chosen instance, or ``no_suggestion`` when none fits.

        Raises:
            AdapterError: ``model_missing`` when the model has no weights.
        """
        import torch
        from PIL import Image
        from ultralytics import YOLO

        if request.model.weights is None:
            raise AdapterError("model_missing", "the retained model has no weights")
        with Image.open(request.image_path) as opened:
            pixels = np.array(opened.convert("RGB"))
        result = YOLO(str(Path(request.model_dir) / request.model.weights)).predict(
            np.ascontiguousarray(pixels[..., ::-1]),
            device="cuda:0" if torch.cuda.is_available() else "cpu",
            retina_masks=True,
            verbose=False,
        )[0]
        boxes = result.boxes.xyxy.cpu().numpy()
        scores = result.boxes.conf.cpu().numpy()
        masks = (
            result.masks.data.cpu().numpy() > 0.5 if result.masks is not None else None
        )
        chosen = self._choose(request, boxes, scores, masks)
        provenance = {
            "solution": SOLUTION_ID,
            "version": SOLUTION_VERSION,
            "iteration": request.model.iteration,
        }
        if chosen is None:
            return AssistanceResult(
                request_id=request.request_id, status="no_suggestion", model=provenance
            )
        geometry = self._geometry(request, boxes[chosen], masks, chosen)
        if geometry is None:
            return AssistanceResult(
                request_id=request.request_id, status="no_suggestion", model=provenance
            )
        return AssistanceResult(
            request_id=request.request_id,
            status="suggestion",
            geometry=geometry,
            score=float(scores[chosen]),
            model=provenance,
        )

    @staticmethod
    def _choose(
        request: AssistanceRequest,
        boxes: np.ndarray,
        scores: np.ndarray,
        masks: np.ndarray | None,
    ) -> int | None:
        """Return the instance answering the prompt, or None."""
        from dada_api.active_learning.dada_al.uncertainty.metrics import iou_matrix

        if len(boxes) == 0:
            return None
        values = request.prompt.coordinates
        if request.prompt.type == "box":
            x, y, width, height = values
            overlaps = iou_matrix(np.array([[x, y, x + width, y + height]]), boxes)[0]
            best = int(overlaps.argmax())
            return best if overlaps[best] > 0 else None
        px, py = values
        inside = [
            index
            for index, box in enumerate(boxes)
            if (
                masks is not None
                and masks[index][
                    min(int(py), masks.shape[1] - 1), min(int(px), masks.shape[2] - 1)
                ]
            )
            or (masks is None and box[0] <= px <= box[2] and box[1] <= py <= box[3])
        ]
        if not inside:
            return None
        return max(inside, key=lambda index: (scores[index], -index))

    @staticmethod
    def _geometry(
        request: AssistanceRequest,
        box: np.ndarray,
        masks: np.ndarray | None,
        chosen: int,
    ) -> dict | None:
        """Return the chosen instance in the task's document geometry."""
        width, height = request.width, request.height
        if request.task == "detection":
            x1, y1 = snap(box[0], 0, width, -1), snap(box[1], 0, height, -1)
            x2, y2 = snap(box[2], 0, width, 1), snap(box[3], 0, height, 1)
            if x2 <= x1 or y2 <= y1:
                return None
            return {"type": "rectangle", "coordinates": [x1, y1, x2 - x1, y2 - y1]}
        from dada_api.active_learning.dada_al.models.yolo_adapter import (
            canonical_ring,
            outline,
        )

        if masks is None:
            return None
        points = outline(masks[chosen][:height, :width])
        ring = canonical_ring(points, width, height) if points is not None else None
        if ring is None:
            return None
        return {"type": "polygon", "coordinates": [ring]}
