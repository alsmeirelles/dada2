"""DADA selection: PCA, mini-batch k-means, and uncertainty-weighted quotas
(spec 4.4.2, P7-09).

The request's budget Q is authoritative. Clusters are capped by the candidate
count, each cluster's share is its mean uncertainty over the sum of means, or
equal when every score is zero, and integer quotas follow the largest
remainder method with capacity-aware redistribution. Ties are broken by the
candidates' stable identifiers and the seed is the request's.
"""

import math

import numpy as np

from dada_api.active_learning.dada_al.config.schema import CandidateItem, DADAAlConfig

SEED_MODULUS = 2**32
KMEANS_BATCH = 1024
INSUFFICIENT = "insufficient_candidates"
NONE_FOUND = "no_candidates"


def _rank(candidate: CandidateItem) -> tuple[float, str]:
    """Sort key: most uncertain first, then by stable identifier."""
    return (-candidate.total_uncertainty, candidate.candidate_id)


def allocate_quotas(sizes: list[int], weights: list[float], budget: int) -> list[int]:
    """Split a budget among clusters in proportion to their weights.

    Each round gives every open cluster the floor of its share, capped by
    what it still holds, then hands the units left over to the largest
    remainders, the lowest cluster index first on a tie. Clusters that fill
    up close, and the rest of the budget is shared again among the others.
    Zero weights everywhere mean equal shares.

    Args:
        sizes: Candidates in each cluster.
        weights: Non-negative weight of each cluster.
        budget: Units to allocate; at most the total size is given.

    Returns:
        The quota of each cluster.
    """
    quotas = [0] * len(sizes)
    target = min(budget, sum(sizes))
    while sum(quotas) < target:
        remaining = target - sum(quotas)
        open_clusters = [k for k in range(len(sizes)) if quotas[k] < sizes[k]]
        total = sum(weights[k] for k in open_clusters)
        shares = {
            k: remaining * (weights[k] / total if total > 0 else 1 / len(open_clusters))
            for k in open_clusters
        }
        for k in open_clusters:
            quotas[k] += min(math.floor(shares[k]), sizes[k] - quotas[k])
        left = target - sum(quotas)
        for k in sorted(open_clusters, key=lambda k: (-(shares[k] % 1), k)):
            if left == 0:
                break
            if quotas[k] < sizes[k]:
                quotas[k] += 1
                left -= 1
    return quotas


def cluster(features: np.ndarray, config: DADAAlConfig, seed: int) -> np.ndarray:
    """Project features with PCA and group them with mini-batch k-means.

    Args:
        features: L2-normalized embeddings of shape ``(N, D)``.
        config: Run configuration.
        seed: Seed of the request.

    Returns:
        One cluster label per candidate.
    """
    from sklearn.cluster import MiniBatchKMeans
    from sklearn.decomposition import PCA

    state = seed % SEED_MODULUS
    components = min(config.pca_components, features.shape[0], features.shape[1])
    reduced = PCA(n_components=components, random_state=state).fit_transform(features)
    clusters = min(config.num_clusters, features.shape[0])
    return MiniBatchKMeans(
        n_clusters=clusters, batch_size=KMEANS_BATCH, random_state=state
    ).fit_predict(reduced)


def select(
    candidates: list[CandidateItem],
    config: DADAAlConfig,
    seed: int,
    labels: np.ndarray | None = None,
) -> tuple[list[CandidateItem], str | None]:
    """Choose up to Q candidates, diverse and uncertain (Algorithm 1).

    Args:
        candidates: Candidates that passed the gatekeeper.
        config: Run configuration carrying the budget Q.
        seed: Seed of the request.
        labels: Cluster labels to use instead of clustering, for tests.

    Returns:
        The chosen candidates, most uncertain first, and the reason when
        fewer than Q were available.
    """
    budget = config.acquisition_budget_q
    if not candidates:
        return [], NONE_FOUND
    if len(candidates) <= budget:
        reason = INSUFFICIENT if len(candidates) < budget else None
        return sorted(candidates, key=_rank), reason
    if labels is None:
        labels = cluster(
            np.stack([candidate.feature_vector for candidate in candidates]),
            config,
            seed,
        )
    members: dict[int, list[CandidateItem]] = {}
    for candidate, label in zip(candidates, labels, strict=True):
        members.setdefault(int(label), []).append(candidate)
    order = sorted(members)
    groups = [sorted(members[label], key=_rank) for label in order]
    weights = [
        sum(item.total_uncertainty for item in group) / len(group) for group in groups
    ]
    quotas = allocate_quotas([len(group) for group in groups], weights, budget)
    chosen = [
        item
        for group, quota in zip(groups, quotas, strict=True)
        for item in group[:quota]
    ]
    return sorted(chosen, key=_rank), None


def queried_roi(
    box: tuple[float, float, float, float], padding: float, width: int, height: int
) -> list[float]:
    """Expand a box by a margin of its own size on each side, inside the image.

    Args:
        box: ``xyxy`` box in canonical pixels.
        padding: Margin as a fraction of the box's width and height.
        width: Image width.
        height: Image height.

    Returns:
        The context region as ``xyxy``.
    """
    x1, y1, x2, y2 = box
    pad_x, pad_y = (x2 - x1) * padding, (y2 - y1) * padding
    return [
        max(0.0, x1 - pad_x),
        max(0.0, y1 - pad_y),
        min(float(width), x2 + pad_x),
        min(float(height), y2 + pad_y),
    ]
