"""Three-pass TTA jitter extractor for detection and segmentation
(spec 4.3.3).

The proxy sees the original image, its horizontal flip, and a 0.85 rescale.
The detections of the other passes are mapped back to the original frame and
matched to the original pass by Hungarian assignment at IoU 0.5; a pass that
missed an object contributes the background distribution and an IoU of zero.
Class uncertainty is the augmented-simplex BALD over the passes and
localization uncertainty the pairwise IoU dispersion. For segmentation, the
mask term is the boundary-band entropy of the original pass, the only mask
measure the specification defines for this method.
"""

import cv2
import numpy as np
import torch
from scipy.optimize import linear_sum_assignment

from dada_api.active_learning.dada_al.acquisition.feature_extractor import (
    roi_features,
)
from dada_api.active_learning.dada_al.config.schema import (
    CandidateItem,
    DADAAlConfig,
    TaskType,
)
from dada_api.active_learning.dada_al.dataset.pai_schema import PAIImage
from dada_api.active_learning.dada_al.models.yolo_adapter import (
    YoloAdapter,
    read_rgb,
)
from dada_api.active_learning.dada_al.uncertainty import metrics
from dada_api.active_learning.dada_al.uncertainty.pre_nms_extractor import (
    candidate_id,
    references,
)

MATCH_IOU = 0.5
RESCALE = 0.85


class TTAExtractor:
    """Scores the objects of an image subpool by their stability under
    flipping and rescaling."""

    def __init__(self, adapter: YoloAdapter, config: DADAAlConfig) -> None:
        """Bind the extractor to a YOLO adapter and the run configuration."""
        self.adapter = adapter
        self.config = config

    def _detections(self, network: torch.nn.Module, pixels: np.ndarray):
        """Run one pass and return it with its objects in network pixels."""
        step = self.adapter.forward(network, pixels)
        dense = YoloAdapter.decode(network, step.one_to_many)
        sparse = (
            YoloAdapter.decode(network, step.one_to_one)
            if step.one_to_one is not None
            else None
        )
        return step, references(dense, sparse, self.config.candidate_conf_floor)

    def extract(
        self, network: torch.nn.Module, images: list[PAIImage], media_root: str
    ) -> list[CandidateItem]:
        """Return the scored candidates of every image.

        Args:
            network: Loaded proxy model.
            images: Subpool images.
            media_root: Media root of the request.

        Returns:
            One candidate per object of the original pass.
        """
        candidates = []
        for image in images:
            candidates.extend(self._image(network, image, read_rgb(media_root, image)))
        return candidates

    def _image(
        self, network: torch.nn.Module, image: PAIImage, pixels: np.ndarray
    ) -> list[CandidateItem]:
        """Score one image's objects across the three passes."""
        width, height = image.width, image.height
        step, found = self._detections(network, pixels)
        if not found:
            return []
        boxes = torch.stack([entry[0] for entry in found])
        original = self.adapter.to_canonical(boxes, step, width, height)
        classes = found[0][1].shape[0]

        flipped_step, flipped = self._detections(network, pixels[:, ::-1].copy())
        flipped_boxes = self._canonical(flipped, flipped_step, width, height)
        if len(flipped_boxes):
            flipped_boxes[:, [0, 2]] = width - flipped_boxes[:, [2, 0]]
        small = cv2.resize(
            pixels,
            (max(1, round(width * RESCALE)), max(1, round(height * RESCALE))),
            interpolation=cv2.INTER_LINEAR,
        )
        small_step, scaled = self._detections(network, small)
        scaled_boxes = self._canonical(
            scaled, small_step, small.shape[1], small.shape[0]
        )
        if len(scaled_boxes):
            scaled_boxes[:, [0, 2]] *= width / small.shape[1]
            scaled_boxes[:, [1, 3]] *= height / small.shape[0]

        passes = [
            (original, [entry[1] for entry in found]),
            (flipped_boxes, [entry[1] for entry in flipped]),
            (scaled_boxes, [entry[1] for entry in scaled]),
        ]
        matches = [self._match(original, other) for other, _ in passes[1:]]
        features = (
            roi_features(step.feats, boxes, network.model[-1].stride).cpu().numpy()
        )
        config = self.config
        candidates = []
        for index, (box, scores, branch, position) in enumerate(found):
            simplexes = [metrics.augmented_simplex(scores[None].cpu().numpy())[0]]
            matched_boxes = [original[index]]
            for (other_boxes, other_scores), match in zip(
                passes[1:], matches, strict=True
            ):
                partner = match.get(index)
                if partner is None:
                    simplexes.append(metrics.background_simplex(classes))
                    matched_boxes.append(None)
                else:
                    simplexes.append(
                        metrics.augmented_simplex(
                            other_scores[partner][None].cpu().numpy()
                        )[0]
                    )
                    matched_boxes.append(other_boxes[partner])
            cls = metrics.bald(np.stack(simplexes))
            loc = metrics.pairwise_iou_dispersion(matched_boxes)
            mask = None
            ring = None
            if config.task is TaskType.SEGMENTATION:
                probabilities = self.adapter.mask_probabilities(branch, position, box)
                ring = self.adapter.polygon(probabilities, step, width, height)
                if ring is None:
                    continue
                mask = metrics.boundary_band_entropy(
                    probabilities.cpu().numpy(),
                    max(1, round(config.mask_boundary_band_px * step.gain)),
                )
            total = metrics.total_uncertainty(
                cls, loc, mask, config.cls_weight, config.loc_weight, config.mask_weight
            )
            candidates.append(
                CandidateItem(
                    candidate_id=candidate_id(image.id, original[index]),
                    image_id=image.id,
                    bbox_xyxy=tuple(float(v) for v in original[index]),
                    segmentation=[ring] if ring is not None else None,
                    pred_class_probs=scores.cpu().numpy(),
                    cls_uncertainty=cls,
                    spatial_uncertainty=loc if mask is None else (loc + mask) / 2,
                    total_uncertainty=total,
                    feature_vector=features[index],
                )
            )
        return candidates

    def _canonical(self, found, step, width: int, height: int) -> np.ndarray:
        """Map a pass's objects back to its own image's pixels."""
        if not found:
            return np.zeros((0, 4))
        return self.adapter.to_canonical(
            torch.stack([entry[0] for entry in found]), step, width, height
        )

    @staticmethod
    def _match(original: np.ndarray, other: np.ndarray) -> dict[int, int]:
        """Pair objects one-to-one by IoU, keeping pairs at 0.5 or more."""
        if len(original) == 0 or len(other) == 0:
            return {}
        overlaps = metrics.iou_matrix(original, other)
        rows, columns = linear_sum_assignment(overlaps, maximize=True)
        return {
            int(row): int(column)
            for row, column in zip(rows, columns, strict=True)
            if overlaps[row, column] >= MATCH_IOU
        }
