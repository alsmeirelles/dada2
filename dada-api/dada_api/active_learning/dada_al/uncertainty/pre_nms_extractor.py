"""Single-pass pre-NMS proposal-cluster extractor with the YOLO26 dual-head
terms (spec 4.3.2).

Surviving objects are found by NMS on the one-to-many branch, joined in
YOLO26 by the one-to-one survivors. Each object's cluster is every
one-to-many proposal scoring above 0.05 whose box overlaps it by
``proposal_cluster_iou_thresh``; class, localization, and mask uncertainty
are measured over that cluster, and its embedding is pooled from P3 to P5.
"""

import uuid

import numpy as np
import torch
from torchvision.ops import batched_nms

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
    NMS_IOU,
    Decoded,
    Pass,
    YoloAdapter,
    iou,
    read_rgb,
)
from dada_api.active_learning.dada_al.uncertainty import metrics

PROPOSAL_SCORE = 0.05
DUAL_MATCH_IOU = 0.30
MAX_ONE_TO_ONE = 300


def candidate_id(image_id: str, box: np.ndarray) -> str:
    """Return a UUID derived from an image and a rounded box, stable across
    runs."""
    rounded = ",".join(f"{value:.1f}" for value in box)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{image_id}:{rounded}"))


def references(
    dense: Decoded, sparse: Decoded | None, floor: float
) -> list[tuple[torch.Tensor, torch.Tensor, Decoded, int]]:
    """Return each surviving object with the branch prediction it came from.

    Args:
        dense: Decoded one-to-many branch.
        sparse: Decoded one-to-one branch, or None.
        floor: Least confidence of a candidate.

    Returns:
        ``(box, scores, branch, index)`` tuples in network pixels.
    """
    sources = [(dense, YoloAdapter.survivors(dense, floor))]
    if sparse is not None:
        confidence = sparse.scores.max(1).values
        top = confidence.argsort(descending=True)[:MAX_ONE_TO_ONE]
        sources.append((sparse, top[confidence[top] >= floor]))
    entries = [(branch, int(index)) for branch, indices in sources for index in indices]
    if not entries:
        return []
    boxes = torch.stack([branch.boxes[index] for branch, index in entries])
    scores = torch.stack([branch.scores[index] for branch, index in entries])
    confidence, labels = scores.max(1)
    kept = batched_nms(boxes, confidence, labels, NMS_IOU)
    return [
        (boxes[position], scores[position], *entries[position])
        for position in kept.tolist()
    ]


class PreNMSExtractor:
    """Scores the objects of an image subpool with a trained proxy."""

    def __init__(self, adapter: YoloAdapter, config: DADAAlConfig) -> None:
        """Bind the extractor to a YOLO adapter and the run configuration."""
        self.adapter = adapter
        self.config = config

    def extract(
        self, network: torch.nn.Module, images: list[PAIImage], media_root: str
    ) -> list[CandidateItem]:
        """Return the scored candidates of every image.

        Args:
            network: Loaded proxy model.
            images: Subpool images.
            media_root: Media root of the request.

        Returns:
            One candidate per surviving object.
        """
        candidates = []
        for image in images:
            step = self.adapter.forward(network, read_rgb(media_root, image))
            candidates.extend(self.score(network, image, step))
        return candidates

    def score(
        self, network: torch.nn.Module, image: PAIImage, step: Pass
    ) -> list[CandidateItem]:
        """Score every surviving object of one forward pass."""
        config = self.config
        dense = YoloAdapter.decode(network, step.one_to_many)
        sparse = (
            YoloAdapter.decode(network, step.one_to_one)
            if step.one_to_one is not None
            else None
        )
        found = references(dense, sparse, config.candidate_conf_floor)
        if not found:
            return []
        head = network.model[-1]
        dfl = head.reg_max > 1
        classes = dense.scores.shape[1]
        proposal = dense.scores.max(1).values > PROPOSAL_SCORE
        candidates = []
        boxes = torch.stack([found_box for found_box, *_ in found])
        features = roi_features(step.feats, boxes, head.stride).cpu().numpy()
        canonical = self.adapter.to_canonical(boxes, step, image.width, image.height)
        overlaps = iou(boxes, dense.boxes)
        for position, (box, scores, branch, index) in enumerate(found):
            members = torch.nonzero(
                proposal & (overlaps[position] >= config.proposal_cluster_iou_thresh)
            ).flatten()
            source, mask_index, coefficients = branch, index, None
            if branch.coefficients is not None:
                coefficients = branch.coefficients[[index]]
            if len(members) == 0:
                cluster_scores = scores[None]
                cluster_boxes = box[None]
            else:
                order = dense.scores[members].max(1).values.argsort(descending=True)
                members = members[order]
                cluster_scores = dense.scores[members]
                cluster_boxes = dense.boxes[members]
                source, mask_index = dense, int(members[0])
                if dense.coefficients is not None:
                    coefficients = dense.coefficients[members]
            confidence = cluster_scores.max(1).values.cpu().numpy()
            weights = confidence / confidence.sum()
            simplex = metrics.augmented_simplex(cluster_scores.cpu().numpy())
            cls = metrics.cluster_class_uncertainty(simplex, config.shrinkage_kappa)
            if dfl and len(members):
                prior = metrics.dfl_entropy(
                    dense.raw_boxes[members[0]].reshape(4, -1).cpu().numpy()
                )
            else:
                prior = 1.0 - float(confidence[0])
            loc = metrics.cluster_localization_uncertainty(
                iou(cluster_boxes, box[None]).flatten().cpu().numpy(),
                weights,
                config.proposal_cluster_iou_thresh,
                config.shrinkage_kappa,
                prior,
            )
            if sparse is not None:
                cls, loc = self._dual(sparse, box, simplex, cls, loc, classes)
            mask = None
            ring = None
            if config.task is TaskType.SEGMENTATION:
                probabilities = self.adapter.mask_probabilities(source, mask_index, box)
                ring = self.adapter.polygon(
                    probabilities, step, image.width, image.height
                )
                if ring is None:
                    continue
                boundary = metrics.boundary_band_entropy(
                    probabilities.cpu().numpy(),
                    max(1, round(config.mask_boundary_band_px * step.gain)),
                )
                dispersion = metrics.coefficient_dispersion(
                    coefficients.cpu().numpy(), weights
                )
                mask = metrics.mask_uncertainty(boundary, dispersion)
            total = metrics.total_uncertainty(
                cls, loc, mask, config.cls_weight, config.loc_weight, config.mask_weight
            )
            spatial = loc if mask is None else (loc + mask) / 2
            candidates.append(
                CandidateItem(
                    candidate_id=candidate_id(image.id, canonical[position]),
                    image_id=image.id,
                    bbox_xyxy=tuple(float(v) for v in canonical[position]),
                    segmentation=[ring] if ring is not None else None,
                    pred_class_probs=scores.cpu().numpy(),
                    cls_uncertainty=cls,
                    spatial_uncertainty=spatial,
                    total_uncertainty=total,
                    feature_vector=features[position],
                )
            )
        return candidates

    def _dual(
        self,
        sparse: Decoded,
        box: torch.Tensor,
        simplex: np.ndarray,
        cls: float,
        loc: float,
        classes: int,
    ) -> tuple[float, float]:
        """Blend in the YOLO26 one-to-one disagreement."""
        alpha = self.config.yolo26_dual_head_weight
        confidence = sparse.scores.max(1).values
        top = confidence.argsort(descending=True)[:MAX_ONE_TO_ONE]
        overlaps = iou(box[None], sparse.boxes[top]).flatten()
        if overlaps.numel() and overlaps.max() >= DUAL_MATCH_IOU:
            best = top[overlaps.argmax()]
            matched = metrics.augmented_simplex(
                sparse.scores[best][None].cpu().numpy()
            )[0]
            matched_iou = float(overlaps.max())
        else:
            matched = metrics.background_simplex(classes)
            matched_iou = 0.0
        disagreement = metrics.jensen_shannon(simplex.mean(0), matched)
        return (
            (1 - alpha) * cls + alpha * disagreement,
            (1 - alpha) * loc + alpha * (1 - matched_iou),
        )
