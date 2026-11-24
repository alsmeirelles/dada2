"""Bounded uncertainty measures of DADA (spec 4.3).

Every function takes NumPy arrays and returns a float clipped to ``[0, 1]``:
normalized entropies, the BALD mutual information, its augmented-simplex
form for sigmoid detectors with the lone-proposal shrinkage, the YOLO26
dual-head Jensen-Shannon disagreement, IoU dispersions, DFL edge entropy, and
the mask boundary-band and prototype-coefficient measures.
"""

import numpy as np
from scipy import ndimage

EPSILON = 1e-12
DFL_BINS = 16


def _unit(value: float) -> float:
    """Clip a measure to ``[0, 1]`` against rounding."""
    return float(min(max(value, 0.0), 1.0))


def normalized_entropy(probabilities: np.ndarray) -> np.ndarray:
    """Return the Shannon entropy of each distribution divided by ``log C``.

    Args:
        probabilities: Distributions along the last axis.

    Returns:
        Entropies in ``[0, 1]``, one per distribution.
    """
    p = np.clip(probabilities, EPSILON, 1.0)
    classes = probabilities.shape[-1]
    return np.clip(-(p * np.log(p)).sum(-1) / np.log(classes), 0.0, 1.0)


def bald(passes: np.ndarray) -> float:
    """Return the normalized mutual information of several predictions.

    Args:
        passes: Distributions of shape ``(M, C)``.

    Returns:
        ``H(mean) - mean(H)``.
    """
    return _unit(normalized_entropy(passes.mean(0)) - normalized_entropy(passes).mean())


def classification_uncertainty(passes: np.ndarray, blend: float) -> float:
    """Return BALD blended with the predictive entropy (spec 4.3.1).

    The entropy keeps a boundary case on which every pass agrees, such as a
    50/50 split, above zero.

    Args:
        passes: Softmax distributions of shape ``(M, C)``.
        blend: Weight of the predictive entropy.

    Returns:
        ``(1 - blend) * BALD + blend * H(mean)``.
    """
    entropy = float(normalized_entropy(passes.mean(0)))
    return _unit((1 - blend) * bald(passes) + blend * entropy)


def augmented_simplex(scores: np.ndarray) -> np.ndarray:
    """Map independent sigmoid class scores onto a ``C + 1`` simplex.

    The background probability is ``1 - max`` of the scores (Formulation B).

    Args:
        scores: Sigmoid scores of shape ``(K, C)``.

    Returns:
        Distributions of shape ``(K, C + 1)``, background first.
    """
    background = 1.0 - scores.max(-1, keepdims=True)
    augmented = np.concatenate([background, scores], axis=-1)
    return augmented / np.clip(augmented.sum(-1, keepdims=True), EPSILON, None)


def background_simplex(classes: int) -> np.ndarray:
    """Return the pure-background distribution over ``classes + 1`` outcomes."""
    simplex = np.zeros(classes + 1)
    simplex[0] = 1.0
    return simplex


def shrinkage(count: int, kappa: float) -> float:
    """Return ``(K - 1) / (K + kappa)``, zero for a lone proposal."""
    return (count - 1) / (count + kappa)


def cluster_class_uncertainty(simplex: np.ndarray, kappa: float) -> float:
    """Return the shrunk one-to-many cluster BALD of one object.

    Args:
        simplex: Augmented distributions of the ``K`` proposals, the primary
            proposal first.
        kappa: Shrinkage constant.

    Returns:
        ``gamma * BALD + (1 - gamma) * H(primary)``.
    """
    gamma = shrinkage(len(simplex), kappa)
    primary = float(normalized_entropy(simplex[0]))
    return _unit(gamma * bald(simplex) + (1 - gamma) * primary)


def jensen_shannon(first: np.ndarray, second: np.ndarray) -> float:
    """Return the normalized Jensen-Shannon divergence of two distributions."""
    middle = normalized_entropy((first + second) / 2)
    return _unit(
        float(middle)
        - (float(normalized_entropy(first)) + float(normalized_entropy(second))) / 2
    )


def iou_matrix(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Return the IoU of every pair of ``xyxy`` boxes.

    Args:
        first: Boxes of shape ``(N, 4)``.
        second: Boxes of shape ``(M, 4)``.

    Returns:
        IoUs of shape ``(N, M)``.
    """
    first = np.asarray(first, dtype=float).reshape(-1, 4)
    second = np.asarray(second, dtype=float).reshape(-1, 4)
    x1 = np.maximum(first[:, None, 0], second[None, :, 0])
    y1 = np.maximum(first[:, None, 1], second[None, :, 1])
    x2 = np.minimum(first[:, None, 2], second[None, :, 2])
    y2 = np.minimum(first[:, None, 3], second[None, :, 3])
    intersection = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_first = (first[:, 2] - first[:, 0]) * (first[:, 3] - first[:, 1])
    area_second = (second[:, 2] - second[:, 0]) * (second[:, 3] - second[:, 1])
    union = area_first[:, None] + area_second[None, :] - intersection
    return np.where(union > 0, intersection / np.clip(union, EPSILON, None), 0.0)


def dfl_entropy(edges: np.ndarray) -> float:
    """Return the normalized entropy of the four DFL edge distributions.

    Args:
        edges: Raw logits of shape ``(4, 16)`` for left, top, right, bottom.

    Returns:
        Mean edge entropy divided by ``log 16``.
    """
    shifted = edges - edges.max(-1, keepdims=True)
    distributions = np.exp(shifted) / np.exp(shifted).sum(-1, keepdims=True)
    return _unit(float(normalized_entropy(distributions).mean()))


def cluster_localization_uncertainty(
    ious: np.ndarray, weights: np.ndarray, tau: float, kappa: float, prior: float
) -> float:
    """Return the shrunk confidence-weighted IoU dispersion of one object.

    Args:
        ious: IoU of each proposal with the reference box, all ``>= tau``.
        weights: Normalized confidence weights of the proposals.
        tau: Clustering IoU threshold.
        kappa: Shrinkage constant.
        prior: Single-proposal localization uncertainty.

    Returns:
        ``gamma * dispersion + (1 - gamma) * prior``.
    """
    gamma = shrinkage(len(ious), kappa)
    dispersion = (1 - float((weights * ious).sum())) / (1 - tau)
    return _unit(gamma * _unit(dispersion) + (1 - gamma) * prior)


def pairwise_iou_dispersion(boxes: list[np.ndarray | None]) -> float:
    """Return one minus the mean pairwise IoU of one object across passes.

    A pass that missed the object contributes an IoU of zero with the others.

    Args:
        boxes: One ``xyxy`` box per pass, or None when it was missed.

    Returns:
        The dispersion.
    """
    pairs = [
        (boxes[i], boxes[j])
        for i in range(len(boxes))
        for j in range(i + 1, len(boxes))
    ]
    total = sum(
        float(iou_matrix(a, b)[0, 0]) if a is not None and b is not None else 0.0
        for a, b in pairs
    )
    return _unit(1 - total / max(len(pairs), 1))


def _disk(radius: int) -> np.ndarray:
    """Return a disk-shaped structuring element."""
    y, x = np.ogrid[-radius : radius + 1, -radius : radius + 1]
    return x * x + y * y <= radius * radius


def boundary_band_entropy(probabilities: np.ndarray, radius: int) -> float:
    """Return the mean binary entropy over the boundary band of a mask.

    The band is the dilation minus the erosion of the binarized mask, or the
    dilation alone when the erosion vanishes. A mask with no pixel above one
    half has no band and is as uncertain as possible.

    Args:
        probabilities: Mask probabilities of shape ``(H, W)``.
        radius: Band radius in pixels.

    Returns:
        Mean binary entropy in bits.
    """
    binary = probabilities > 0.5
    if not binary.any():
        return 1.0
    element = _disk(radius)
    dilated = ndimage.binary_dilation(binary, structure=element)
    eroded = ndimage.binary_erosion(binary, structure=element)
    band = dilated & ~eroded if eroded.any() else dilated
    p = np.clip(probabilities[band], EPSILON, 1 - EPSILON)
    return _unit(float(-(p * np.log2(p) + (1 - p) * np.log2(1 - p)).mean()))


def coefficient_dispersion(coefficients: np.ndarray, weights: np.ndarray) -> float:
    """Return the spherical variance of the proposals' mask coefficients.

    Args:
        coefficients: Coefficient vectors of shape ``(K, 32)``.
        weights: Normalized confidence weights of shape ``(K,)``.

    Returns:
        ``1 - ||sum(w * c / ||c||)||``.
    """
    norms = np.linalg.norm(coefficients, axis=-1, keepdims=True)
    unit = coefficients / (norms + EPSILON)
    return _unit(1 - float(np.linalg.norm((weights[:, None] * unit).sum(0))))


def mask_uncertainty(boundary: float, coefficients: float) -> float:
    """Return the even blend of the two mask measures."""
    return _unit(0.5 * boundary + 0.5 * coefficients)


def total_uncertainty(
    cls: float,
    loc: float,
    mask: float | None,
    cls_weight: float,
    loc_weight: float,
    mask_weight: float | None,
) -> float:
    """Return the convex combination of an object's uncertainties.

    Args:
        cls: Class uncertainty.
        loc: Localization uncertainty.
        mask: Mask uncertainty, None for detection.
        cls_weight: Weight of the class term.
        loc_weight: Weight of the localization term.
        mask_weight: Weight of the mask term, None for detection.

    Returns:
        The total uncertainty.
    """
    total = cls_weight * cls + loc_weight * loc
    if mask is not None and mask_weight is not None:
        total += mask_weight * mask
    return _unit(total)
