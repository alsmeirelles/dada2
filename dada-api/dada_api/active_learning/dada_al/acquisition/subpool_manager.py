"""Two-tier dynamic subpooling of DADA (spec 4.4.1).

Tier 1 samples an image subpool from the unlabeled and partially labeled
images and keeps it, in the solution's state folder, for
``subpool_renewal_interval`` iterations. Tier 2 is the object gatekeeper: it
drops candidates that overlap an answered object or a queried region and caps
how many candidates reach clustering.
"""

import json
import random
from pathlib import Path
from typing import Any

import numpy as np

from dada_api.active_learning.contract import EXHAUSTIVELY_LABELED
from dada_api.active_learning.dada_al.config.schema import (
    CandidateItem,
    DADAAlConfig,
    TaskType,
)
from dada_api.active_learning.dada_al.uncertainty.metrics import iou_matrix

STATE_FILE = "subpool.json"


class SubpoolManager:
    """Keeps a project's image subpool and filters its object candidates."""

    def __init__(self, state_dir: str, config: DADAAlConfig) -> None:
        """Bind the manager to a project's state folder.

        Args:
            state_dir: Solution state folder of the request.
            config: Run configuration.
        """
        self.path = Path(state_dir) / STATE_FILE
        self.config = config

    def image_subpool(
        self, images: list[dict[str, Any]], iteration: int, seed: int
    ) -> list[dict[str, Any]]:
        """Return the Tier-1 subpool of an iteration.

        The stored subpool is reused while it is younger than the renewal
        interval and still holds eligible images; a retry of the same
        iteration therefore sees the same subpool. Otherwise a new one is
        sampled uniformly with the request's seed.

        Args:
            images: Pool manifest images.
            iteration: Iteration of the request.
            seed: Seed of the request.

        Returns:
            The subpool, in pool order.
        """
        eligible = [
            image
            for image in images
            if image["annotation_status"] != EXHAUSTIVELY_LABELED
        ]
        known = {image["id"] for image in eligible}
        state = self._read()
        if (
            state is not None
            and 0
            <= iteration - state["iteration"]
            < self.config.subpool_renewal_interval
        ):
            kept = set(state["image_ids"]) & known
            if kept:
                return [image for image in eligible if image["id"] in kept]
        identifiers = sorted(known)
        sampled = set(
            random.Random(seed).sample(
                identifiers, min(self.config.image_subpool_size, len(identifiers))
            )
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"iteration": iteration, "seed": seed, "image_ids": sorted(sampled)}
            )
        )
        return [image for image in eligible if image["id"] in sampled]

    def _read(self) -> dict[str, Any] | None:
        """Return the stored subpool, if any."""
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None

    def gatekeeper(
        self, candidates: list[CandidateItem], pool: dict[str, Any]
    ) -> list[CandidateItem]:
        """Drop known objects and cap the candidates (Tier 2).

        For detection and segmentation, a candidate is discarded when its box
        overlaps an answered object or a queried region of its image at
        ``annotated_iou_dedup_thresh`` or more. The most uncertain
        ``max_object_candidates`` remain.

        Args:
            candidates: Raw candidates of the subpool.
            pool: Pool manifest, with each image's history.

        Returns:
            The surviving candidates.
        """
        if self.config.task is not TaskType.CLASSIFICATION:
            known: dict[str, list[list[float]]] = {}
            for image in pool["images"]:
                for roi in image.get("queried_rois", []):
                    known.setdefault(image["id"], []).append(roi["bbox_xyxy"])
            for annotation in pool["annotations"]:
                x, y, width, height = annotation["bbox"]
                known.setdefault(annotation["image_id"], []).append(
                    [x, y, x + width, y + height]
                )
            candidates = [
                candidate
                for candidate in candidates
                if not _overlaps(
                    candidate,
                    known.get(candidate.image_id, []),
                    self.config.annotated_iou_dedup_thresh,
                )
            ]
        if len(candidates) > self.config.max_object_candidates:
            candidates = sorted(
                candidates,
                key=lambda item: (-item.total_uncertainty, item.candidate_id),
            )[: self.config.max_object_candidates]
        return candidates


def _overlaps(
    candidate: CandidateItem, boxes: list[list[float]], threshold: float
) -> bool:
    """Return whether a candidate's box overlaps a known box enough."""
    if not boxes or candidate.bbox_xyxy is None:
        return False
    return bool(
        (
            iou_matrix(np.array([candidate.bbox_xyxy]), np.array(boxes)) >= threshold
        ).any()
    )
