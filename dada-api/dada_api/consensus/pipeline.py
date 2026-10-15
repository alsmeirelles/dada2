"""Dispatch of a resolver input to the pipeline adapter registered for it."""

from collections.abc import Callable

from dada_api.consensus import classification, detection, segmentation
from dada_api.consensus.protocol import PipelineError, PipelineOutput, ResolverInput

Adapter = Callable[[ResolverInput], PipelineOutput]
ADAPTERS: dict[str, Adapter] = {
    "statistical_class_consensus": classification.resolve,
    "two_stage_detection_consensus": detection.resolve,
    "two_stage_segmentation_consensus": segmentation.resolve,
}


def run(resolver_input: ResolverInput) -> PipelineOutput:
    """Run the adapter of the input's pipeline, never substituting another.

    Args:
        resolver_input: Complete, verified input of one run.

    Returns:
        The adapter's proposal.

    Raises:
        PipelineError: ``resolver_unavailable`` when no adapter is registered.
    """
    adapter = ADAPTERS.get(resolver_input.pipeline)
    if adapter is None:
        raise PipelineError(
            "resolver_unavailable", f"no adapter for {resolver_input.pipeline}"
        )
    return adapter(resolver_input)
