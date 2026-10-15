"""The ``two_stage_segmentation_consensus`` pipeline for polygon instances."""

import statistics
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import numpy as np

from dada_api.consensus import candidates, catalog, mask_refinement, masks
from dada_api.consensus.numeric import at_least, quantize
from dada_api.consensus.protocol import PipelineOutput, ResolverInput
from dada_api.services.annotation_documents import MAX_CANONICAL_RING_POINTS
from dada_api.services.label_formats import ring_is_simple


@dataclass(frozen=True)
class Instance:
    """One rasterized instance with its bounding box for the prefilter."""

    mask: np.ndarray
    bbox: list[float]


def _valid_ring(ring: list[float]) -> bool:
    """Return whether a traced ring is a usable canonical polygon ring."""
    points = list(zip(ring[0::2], ring[1::2], strict=True))
    return (
        3 <= len(points) <= MAX_CANONICAL_RING_POINTS
        and len(set(points)) >= 3
        and ring_is_simple(points)
    )


def resolve(resolver_input: ResolverInput) -> PipelineOutput:
    """Resolve one image's instances: identify, decide, then refine masks.

    Masks are rasterized at the original size with the even-odd rule.
    crowd-kit and STAPLE only refine the geometry of an instance whose
    existence and class are already decided. A refined mask whose
    post-processing changed it materially, or whose outline cannot be a
    valid polygon, needs review (``topology_invalid``) and contributes no
    geometry.

    Args:
        resolver_input: Verified input of one run.

    Returns:
        One decision per candidate instance.
    """
    parameters = resolver_input.configuration["parameters"]
    thresholds = resolver_input.configuration["review_thresholds"]
    width, height = resolver_input.width, resolver_input.height
    overlap = (
        masks.mask_iou if parameters["matching_metric"] == "iou" else masks.mask_dice
    )

    def parse(stored: dict[str, Any]) -> Instance:
        """Rasterize one stored polygon."""
        mask = masks.rasterize(stored["coordinates"], width, height)
        return Instance(mask, masks.bounding_box(mask) or [0, 0, 0, 0])

    def refine(
        values: list[Instance],
    ) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
        """Aggregate the supporting masks, clean them up, and trace them."""
        raw, refinement = mask_refinement.refine(
            parameters["mask_refinement"], [value.mask for value in values]
        )
        final, post = masks.post_process(
            raw, parameters["post_processing"], width, height
        )
        rings, tracing = masks.polygonize(
            final, parameters["post_processing"]["simplify_tolerance"]
        )
        pairs = [overlap(a.mask, b.mask) for a, b in combinations(values, 2)]
        agreement = statistics.median(pairs) if pairs else None
        reasons = []
        if agreement is not None and not at_least(
            agreement, thresholds["minimum_median_overlap"]
        ):
            reasons.append("geometry_below_threshold")
        usable = bool(rings) and all(_valid_ring(ring) for ring in rings)
        if post["material_change"] or not usable:
            reasons.append("topology_invalid")
        return (
            {"type": "polygon", "coordinates": rings} if usable else None,
            reasons,
            {
                "median_overlap": float(quantize(agreement))
                if agreement is not None
                else None,
                "matching_metric": parameters["matching_metric"],
                "supporting_masks": len(values),
                "area": int(final.sum()),
                "refinement": refinement,
                "post_processing": post,
                "polygonization": tracing,
            },
        )

    geometry = candidates.Geometry(
        parse=parse,
        overlap=lambda a, b: overlap(a.mask, b.mask),
        may_overlap=lambda a, b: masks.boxes_intersect(a.bbox, b.bbox),
        bounds=lambda value: list(value.bbox),
        refine=refine,
        threshold=parameters["matching_threshold"],
    )
    return candidates.resolve(
        resolver_input,
        geometry,
        {
            catalog.PIPELINES["segmentation"].id: catalog.VERSION,
            parameters["class_strategy"]["strategy"]: catalog.VERSION,
            parameters["mask_refinement"]["strategy"]: catalog.VERSION,
        },
    )
