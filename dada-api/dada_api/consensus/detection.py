"""The ``two_stage_detection_consensus`` pipeline for bounding boxes."""

from typing import Any

from dada_api.consensus import boxes, candidates, catalog
from dada_api.consensus.numeric import at_least, quantize
from dada_api.consensus.protocol import PipelineOutput, ResolverInput


def resolve(resolver_input: ResolverInput) -> PipelineOutput:
    """Resolve one image's boxes: identify objects, decide them, refine boxes.

    An accepted object's box is the configured refinement of every box that
    supports it, clipped to the image. Its supporting boxes must agree with a
    median pairwise IoU at or above the gate, otherwise the object needs
    review even when its class is unanimous.

    Args:
        resolver_input: Verified input of one run.

    Returns:
        One decision per candidate object.
    """
    parameters = resolver_input.configuration["parameters"]
    thresholds = resolver_input.configuration["review_thresholds"]

    def refine(
        values: list[list[float]],
    ) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
        """Fuse the supporting boxes and gate their agreement."""
        refined = boxes.refine(
            parameters["box_refinement"],
            values,
            resolver_input.width,
            resolver_input.height,
        )
        agreement = boxes.median_pairwise_iou(values)
        reasons = (
            []
            if agreement is None
            or at_least(agreement, thresholds["minimum_median_iou"])
            else ["geometry_below_threshold"]
        )
        return (
            {"type": "rectangle", "coordinates": refined},
            reasons,
            {
                "median_iou": float(quantize(agreement))
                if agreement is not None
                else None,
                "supporting_boxes": len(values),
            },
        )

    geometry = candidates.Geometry(
        parse=lambda stored: list(stored["coordinates"]),
        overlap=boxes.iou,
        may_overlap=None,
        bounds=lambda box: list(box),
        refine=refine,
        threshold=parameters["matching_iou"],
    )
    return candidates.resolve(
        resolver_input,
        geometry,
        {
            catalog.PIPELINES["detection"].id: catalog.VERSION,
            parameters["class_strategy"]["strategy"]: catalog.VERSION,
            parameters["box_refinement"]["strategy"]: catalog.VERSION,
        },
    )
