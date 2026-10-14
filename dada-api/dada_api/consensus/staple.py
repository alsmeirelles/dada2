"""DADA's native binary STAPLE estimate of an instance mask from its raters' masks
(P6-03)."""

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
from scipy.special import expit

from dada_api.consensus.numeric import quantize

INITIAL_PERFORMANCE = 0.99
BOUND = 1e-12


def _diagnostics(
    iterations: int,
    converged: bool,
    prior: float,
    sensitivity: np.ndarray,
    specificity: np.ndarray,
) -> dict[str, Any]:
    """Return the quantized STAPLE diagnostics."""
    return {
        "iterations": iterations,
        "converged": converged,
        "prior": float(quantize(prior)),
        "sensitivity": [float(quantize(value)) for value in sensitivity],
        "specificity": [float(quantize(value)) for value in specificity],
    }


def staple(
    masks: Sequence[np.ndarray], max_iterations: int = 100, tolerance: float = 1e-6
) -> tuple[np.ndarray, dict[str, Any]]:
    """Estimate per-pixel foreground probabilities with binary STAPLE.

    This is the expectation-maximization of Warfield, Zou, and Wells (2004)
    over the full image. The prior ``f`` is the mean foreground fraction of
    all masks, and every rater starts with sensitivity ``p`` and specificity
    ``q`` of 0.99. The E-step computes, in log space,
    ``W = f·Πp^D(1-p)^(1-D) / (f·Πp^D(1-p)^(1-D) + (1-f)·Πq^(1-D)(1-q)^D)``;
    the M-step sets ``p = ΣW·D / ΣW`` and ``q = Σ(1-W)(1-D) / Σ(1-W)``. It
    stops once no ``p`` or ``q`` moves by ``tolerance`` or more, or after
    ``max_iterations``.

    Pixels with the same votes share one posterior, so each step runs over
    the distinct vote patterns weighted by their pixel counts; this is the
    same estimate and keeps every sum independent of the image size. ``p``
    and ``q`` are kept within ``BOUND`` of 0 and 1 so their logarithms stay
    finite. When every mask is empty, or every mask is full, the posterior is
    that constant and no iteration runs.

    Args:
        masks: One boolean mask per rater, all of the same shape.
        max_iterations: Iteration limit.
        tolerance: Largest change of ``p`` and ``q`` that counts as converged.

    Returns:
        The probability map, shaped like the masks, and diagnostics with the
        iteration count, convergence, prior, and per-rater sensitivity and
        specificity, quantized.
    """
    shape = masks[0].shape
    codes = np.zeros(masks[0].size, dtype=np.int64)
    for rater, mask in enumerate(masks):
        codes |= np.asarray(mask, dtype=bool).ravel().astype(np.int64) << rater
    patterns, inverse, counts = np.unique(
        codes, return_inverse=True, return_counts=True
    )
    votes = ((patterns[:, None] >> np.arange(len(masks))) & 1).astype(bool)
    foreground_votes = int((votes.sum(axis=1) * counts).sum())
    prior = foreground_votes / (codes.size * len(masks))
    counts = counts.astype(np.float64)

    sensitivity = np.full(len(masks), INITIAL_PERFORMANCE)
    specificity = np.full(len(masks), INITIAL_PERFORMANCE)
    if prior in (0, 1):
        return np.full(shape, float(prior)), _diagnostics(
            0, True, prior, sensitivity, specificity
        )

    iterations, converged = 0, False
    while iterations < max_iterations and not converged:
        iterations += 1
        log_foreground = math.log(prior) + np.where(
            votes, np.log(sensitivity), np.log1p(-sensitivity)
        ).sum(axis=1)
        log_background = math.log1p(-prior) + np.where(
            votes, np.log1p(-specificity), np.log(specificity)
        ).sum(axis=1)
        weights = expit(log_foreground - log_background)
        present = counts * weights
        absent = counts * (1 - weights)
        updated_sensitivity = np.clip(
            (present[:, None] * votes).sum(axis=0) / present.sum(), BOUND, 1 - BOUND
        )
        updated_specificity = np.clip(
            (absent[:, None] * ~votes).sum(axis=0) / absent.sum(), BOUND, 1 - BOUND
        )
        change = max(
            np.abs(updated_sensitivity - sensitivity).max(),
            np.abs(updated_specificity - specificity).max(),
        )
        sensitivity, specificity = updated_sensitivity, updated_specificity
        converged = bool(change < tolerance)

    probabilities = weights[inverse].reshape(shape)
    return probabilities, _diagnostics(
        iterations, converged, prior, sensitivity, specificity
    )
