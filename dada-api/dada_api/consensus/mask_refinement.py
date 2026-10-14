"""Refinement of one accepted instance's supporting masks with crowd-kit or the
native STAPLE (P6-03, D12)."""

from collections.abc import Sequence
from typing import Any

import numpy as np

from dada_api.consensus import catalog, staple
from dada_api.consensus.numeric import at_least
from dada_api.consensus.protocol import PipelineError

CROWD_KIT = {
    "segmentation_majority_vote": "SegmentationMajorityVote",
    "segmentation_em": "SegmentationEM",
    "segmentation_rasa": "SegmentationRASA",
}
CROWD_KIT_THRESHOLD = 0.5


def _staple(
    strategy: dict[str, Any], masks: Sequence[np.ndarray]
) -> tuple[np.ndarray, dict[str, Any]]:
    """Keep the pixels whose STAPLE posterior meets the configured threshold.

    The posterior takes one value per distinct vote pattern, so each value is
    compared once with the quantized ``at_least``.
    """
    probabilities, diagnostics = staple.staple(masks)
    threshold = strategy["pixel_threshold"]
    levels, inverse = np.unique(probabilities, return_inverse=True)
    keep = np.array([at_least(float(level), threshold) for level in levels])
    return keep[inverse].reshape(probabilities.shape), {
        "strategy": strategy["strategy"],
        "pixel_threshold": threshold,
        "staple": diagnostics,
    }


def _crowd_kit(
    strategy: dict[str, Any], masks: Sequence[np.ndarray]
) -> tuple[np.ndarray, dict[str, Any]]:
    """Run the crowd-kit segmentation aggregator a strategy names.

    Raises:
        PipelineError: ``resolver_unavailable`` when the installed crowd-kit
            is not the pinned version.
    """
    name = strategy["strategy"]
    version = catalog.installed_version("crowd-kit")
    if version != catalog.PINS["crowd-kit"]:
        raise PipelineError(
            "resolver_unavailable",
            f"{name} needs crowd-kit {catalog.PINS['crowd-kit']}, found {version}",
        )
    import pandas as pd
    from crowdkit import aggregation

    frame = pd.DataFrame(
        {
            "task": "t",
            "worker": [f"w{rater}" for rater in range(len(masks))],
            "segmentation": [np.asarray(mask, dtype=bool) for mask in masks],
        }
    )
    aggregator = getattr(aggregation, CROWD_KIT[name])()
    mask = np.asarray(aggregator.fit_predict(frame).loc["t"], dtype=bool)
    return mask, {
        "strategy": name,
        "package": "crowd-kit",
        "version": version,
        "pixel_threshold": CROWD_KIT_THRESHOLD,
    }


def refine(
    strategy: dict[str, Any], masks: Sequence[np.ndarray]
) -> tuple[np.ndarray, dict[str, Any]]:
    """Aggregate the supporting masks of one accepted instance into one mask.

    It only refines geometry: the instance's existence and class were already
    decided and nothing here can change them. crowd-kit's segmentation
    aggregators binarize at their built-in 0.5; STAPLE uses the configured
    ``pixel_threshold``, inclusively.

    Args:
        strategy: Normalized ``mask_refinement`` configuration.
        masks: Boolean supporting masks of the same shape.

    Returns:
        The refined boolean mask and its diagnostics: the strategy, the
        threshold applied, the crowd-kit package and version, or the STAPLE
        diagnostics.

    Raises:
        PipelineError: ``resolver_unavailable`` when the installed crowd-kit
            is not the pinned version.
    """
    if strategy["strategy"] == "staple":
        return _staple(strategy, masks)
    return _crowd_kit(strategy, masks)
