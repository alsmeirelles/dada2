"""Native statistical decisions of one class or existence case from its human votes."""

import math
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from scipy import integrate, special

from dada_api.consensus import numeric
from dada_api.consensus.protocol import PipelineError

NO_OBJECT = "no_object"
POSITIVE = "positive"
NEGATIVE = "negative"
BINARY_OUTCOMES = (POSITIVE, NEGATIVE)
DAWID_SKENE_MINIMUM_POSTERIOR = 0.9
MINIMUM_WEIGHT = 0.5
MAXIMUM_WEIGHT = 2.0
CLASS_TIE = "class_tie"
SUPPORT_BELOW_THRESHOLD = "support_below_threshold"
POSTERIOR_BELOW_THRESHOLD = "posterior_below_threshold"


@dataclass(frozen=True)
class Vote:
    """One rater's observation of one case.

    Attributes:
        rater: Stable annotator identifier; it orders the votes and selects
            the rater's calibration, and is never shown to peers.
        outcome: A class id, ``no_object``, ``positive``, or ``negative``.
    """

    rater: str
    outcome: str


@dataclass(frozen=True)
class Decision:
    """The outcome a strategy selected for one case and whether it passed.

    Attributes:
        outcome: Selected outcome; None when no unique winner exists.
        passed: Whether every quality gate passed.
        reasons: Closed failure reasons, empty when the decision passed.
        metrics: JSON-serializable diagnostics with quantized floats.
    """

    outcome: str | None
    passed: bool
    reasons: tuple[str, ...]
    metrics: dict[str, Any]


Rule = Callable[
    [dict[str, Any], Fraction, list[Vote], dict[str, int], dict[str, Any], Any],
    Decision,
]


def decide(
    strategy: dict[str, Any],
    minimum_support: Fraction,
    votes: Sequence[Vote],
    outcomes: Sequence[str],
    calibration: dict[str, Any] | None = None,
) -> Decision:
    """Decide one case with a normalized class strategy (P6-02, D12).

    The votes are sorted by rater first, so any permutation of the same votes
    yields the same decision and the same floating-point sums.

    Args:
        strategy: Normalized class strategy configuration.
        minimum_support: Exact share of valid votes the winner needs.
        votes: One vote per rater.
        outcomes: Ordered outcome space; every outcome appears in the metrics.
        calibration: Frozen snapshot of a conditional strategy (D11).

    Returns:
        The decision with its vote-distribution and strategy diagnostics.

    Raises:
        PipelineError: ``invalid_input`` for empty, duplicated, or
            out-of-space votes, a non-binary multi-label space, or a weight
            outside the frozen bounds; ``resolver_unavailable`` when a
            conditional strategy lacks a snapshot for a voting rater.
    """
    ordered = _ordered(strategy, votes, outcomes)
    counts = {outcome: 0 for outcome in outcomes}
    for vote in ordered:
        counts[vote.outcome] += 1
    metrics = _distribution(counts, len(ordered))
    rule = RULES[strategy["strategy"]]
    return rule(strategy, minimum_support, ordered, counts, metrics, calibration)


def _ordered(
    strategy: dict[str, Any], votes: Sequence[Vote], outcomes: Sequence[str]
) -> list[Vote]:
    """Validate the votes against the outcome space and sort them by rater.

    Args:
        strategy: Normalized class strategy configuration.
        votes: Votes as received.
        outcomes: Ordered outcome space.

    Returns:
        The votes in rater order.

    Raises:
        PipelineError: ``invalid_input`` when the votes cannot be decided.
    """
    if not votes:
        raise PipelineError("invalid_input", "a decision needs at least one vote")
    if (
        strategy["strategy"] == "multilabel_binary_vote"
        and tuple(outcomes) != BINARY_OUTCOMES
    ):
        raise PipelineError(
            "invalid_input", "multilabel_binary_vote decides positive or negative"
        )
    unknown = sorted({vote.outcome for vote in votes} - set(outcomes))
    if unknown:
        raise PipelineError("invalid_input", f"votes outside the outcomes: {unknown}")
    repeated = Counter(vote.rater for vote in votes)
    duplicated = sorted(rater for rater, count in repeated.items() if count > 1)
    if duplicated:
        raise PipelineError("invalid_input", f"raters voted twice: {duplicated}")
    return sorted(votes, key=lambda vote: vote.rater)


def _distribution(counts: dict[str, int], valid_votes: int) -> dict[str, Any]:
    """Build the diagnostics every strategy records about the raw votes.

    Args:
        counts: Votes per outcome in outcome order.
        valid_votes: Number of votes.

    Returns:
        Vote counts, the top count's support, margin, and normalized
        entropy; a unique winner later replaces the support with its own.
    """
    top, second = [*sorted(counts.values(), reverse=True), 0][:2]
    return {
        "votes": dict(counts),
        "valid_votes": valid_votes,
        "support": {"numerator": top, "denominator": valid_votes},
        "margin": top - second,
        "normalized_entropy": _metric(_normalized_entropy(counts, valid_votes)),
    }


def _normalized_entropy(counts: dict[str, int], valid_votes: int) -> float:
    """Return the Shannon entropy of the votes divided by its maximum.

    Args:
        counts: Votes per outcome.
        valid_votes: Number of votes.

    Returns:
        A value in [0, 1]; 0 when the space has a single outcome.
    """
    if len(counts) == 1:
        return 0.0
    shares = [count / valid_votes for count in counts.values() if count]
    entropy = sum(-share * math.log(share) for share in shares)
    return entropy / math.log(len(counts))


def _metric(value: float) -> float:
    """Return a continuous metric as a plain float quantized to six places.

    Args:
        value: Finite metric.

    Returns:
        The quantized float.
    """
    return float(numeric.quantize(value))


def _unique_top(scores: dict[str, Any]) -> str | None:
    """Return the only outcome holding the highest score.

    Args:
        scores: Comparable score per outcome.

    Returns:
        The winner, or None when several outcomes share the highest score.
    """
    best = max(scores.values())
    leaders = [outcome for outcome, score in scores.items() if score == best]
    return leaders[0] if len(leaders) == 1 else None


def _supported(winner: str, counts: dict[str, int], minimum_support: Fraction) -> bool:
    """Return whether the winner's exact vote share meets the support gate.

    Args:
        winner: Selected outcome.
        counts: Votes per outcome.
        minimum_support: Inclusive exact threshold.

    Returns:
        True when the share is at least the threshold.
    """
    return Fraction(counts[winner], sum(counts.values())) >= minimum_support


def _strict_majority(winner: str, counts: dict[str, int]) -> bool:
    """Return whether the winner holds more than half of the unweighted votes.

    Args:
        winner: Selected outcome.
        counts: Votes per outcome.

    Returns:
        True for a strict majority.
    """
    return counts[winner] * 2 > sum(counts.values())


def _tie(metrics: dict[str, Any]) -> Decision:
    """Return the review decision of a tie for the top, which nothing breaks.

    Args:
        metrics: Diagnostics of the case.

    Returns:
        A failed decision without an outcome.
    """
    return Decision(None, False, (CLASS_TIE,), metrics)


def _result(
    winner: str, counts: dict[str, int], reasons: list[str], metrics: dict[str, Any]
) -> Decision:
    """Return a decision for a unique winner and its failed gates.

    The recorded support becomes the winner's own vote share, which differs
    from the top count when a weighted strategy selects another outcome.

    Args:
        winner: Selected outcome.
        counts: Unweighted votes per outcome.
        reasons: Failed gates in canonical order.
        metrics: Diagnostics of the case.

    Returns:
        The decision, passed when no gate failed.
    """
    metrics["support"] = {
        "numerator": counts[winner],
        "denominator": sum(counts.values()),
    }
    return Decision(winner, not reasons, tuple(reasons), metrics)


def _categorical(
    strategy: dict[str, Any],
    minimum_support: Fraction,
    votes: list[Vote],
    counts: dict[str, int],
    metrics: dict[str, Any],
    calibration: Any,
) -> Decision:
    """Decide by the configured rule plus the common support gate.

    Because the policy floor keeps the support threshold above one half, the
    three rules reach the same decisions and differ only in the recorded rule
    (D12).

    Args:
        strategy: ``categorical_vote`` configuration.
        minimum_support: Exact support threshold.
        votes: Votes in rater order.
        counts: Votes per outcome.
        metrics: Diagnostics to extend.
        calibration: Unused.

    Returns:
        The decision.
    """
    metrics["decision_rule"] = strategy["decision_rule"]
    winner = _unique_top(counts)
    if winner is None:
        return _tie(metrics)
    passed = _supported(winner, counts, minimum_support)
    if strategy["decision_rule"] == "strict_majority":
        passed = passed and _strict_majority(winner, counts)
    return _result(winner, counts, [] if passed else [SUPPORT_BELOW_THRESHOLD], metrics)


def _binary(
    strategy: dict[str, Any],
    minimum_support: Fraction,
    votes: list[Vote],
    counts: dict[str, int],
    metrics: dict[str, Any],
    calibration: Any,
) -> Decision:
    """Decide one class of a multi-label image as positive or negative.

    Both outcomes share the same threshold, so a class meeting neither goes
    to review.

    Args:
        strategy: ``multilabel_binary_vote`` configuration.
        minimum_support: Exact threshold of either outcome.
        votes: Votes in rater order.
        counts: Positive and negative votes.
        metrics: Diagnostics.
        calibration: Unused.

    Returns:
        The decision.
    """
    winner = _unique_top(counts)
    if winner is None:
        return _tie(metrics)
    passed = _supported(winner, counts, minimum_support)
    return _result(winner, counts, [] if passed else [SUPPORT_BELOW_THRESHOLD], metrics)


def _dirichlet(
    strategy: dict[str, Any],
    minimum_support: Fraction,
    votes: list[Vote],
    counts: dict[str, int],
    metrics: dict[str, Any],
    calibration: Any,
) -> Decision:
    """Decide by the count winner under a symmetric Dirichlet posterior.

    The posterior is recorded even for a tie: tied outcomes share the same
    posterior parameters, so either one gives the same probability.

    Args:
        strategy: ``dirichlet_vote`` configuration.
        minimum_support: Exact raw support threshold.
        votes: Votes in rater order.
        counts: Votes per outcome.
        metrics: Diagnostics to extend.
        calibration: Unused.

    Returns:
        The decision.
    """
    parameters = {
        outcome: count + strategy["alpha"] for outcome, count in counts.items()
    }
    top = max(counts, key=counts.__getitem__)
    posterior = _largest_probability(top, parameters)
    metrics["posterior"] = _metric(posterior)
    winner = _unique_top(counts)
    if winner is None:
        return _tie(metrics)
    reasons = []
    if not _supported(winner, counts, minimum_support):
        reasons.append(SUPPORT_BELOW_THRESHOLD)
    if not numeric.at_least(posterior, strategy["minimum_posterior"]):
        reasons.append(POSTERIOR_BELOW_THRESHOLD)
    return _result(winner, counts, reasons, metrics)


def _largest_probability(outcome: str, parameters: dict[str, float]) -> float:
    """Return the probability that an outcome's latent share is the largest.

    Two outcomes use the exact regularized incomplete beta function. More
    outcomes integrate the Gamma representation of the Dirichlet:
    ``P = ∫ f_w(x) Π_j F_j(x) dx`` over ``[0, ∞)``.

    Args:
        outcome: Outcome whose probability is computed; it holds at least one
            vote, so its Gamma density is finite at zero.
        parameters: Dirichlet posterior parameter per outcome.

    Returns:
        The probability, clamped to [0, 1].
    """
    shape = parameters[outcome]
    others = [value for key, value in parameters.items() if key != outcome]
    if len(others) == 1:
        return float(special.betainc(others[0], shape, 0.5))
    log_normalizer = special.gammaln(shape)

    def integrand(x: float) -> float:
        """Gamma density of the outcome times the others' Gamma CDFs."""
        density = math.exp(special.xlogy(shape - 1, x) - x - log_normalizer)
        return density * math.prod(special.gammainc(other, x) for other in others)

    value, _ = integrate.quad(integrand, 0, math.inf, epsabs=1e-12, epsrel=1e-10)
    return min(max(value, 0.0), 1.0)


def _snapshot(
    strategy: dict[str, Any], calibration: dict[str, Any] | None
) -> dict[str, Any]:
    """Return the frozen calibration of a conditional strategy.

    Args:
        strategy: Conditional strategy configuration.
        calibration: Snapshot linked to the batch, if any.

    Returns:
        The snapshot.

    Raises:
        PipelineError: ``resolver_unavailable`` without a snapshot.
    """
    if calibration is None:
        raise PipelineError(
            "resolver_unavailable", f"{strategy['strategy']} needs a calibration"
        )
    return calibration


def _require_raters(votes: list[Vote], calibrated: dict[str, Any]) -> None:
    """Refuse a decision when a voting rater has no calibrated parameters.

    Args:
        votes: Votes in rater order.
        calibrated: Parameters keyed by rater.

    Raises:
        PipelineError: ``resolver_unavailable`` naming the uncalibrated raters.
    """
    missing = [vote.rater for vote in votes if vote.rater not in calibrated]
    if missing:
        raise PipelineError("resolver_unavailable", f"uncalibrated raters: {missing}")


def _reliability(
    strategy: dict[str, Any],
    minimum_support: Fraction,
    votes: list[Vote],
    counts: dict[str, int],
    metrics: dict[str, Any],
    calibration: dict[str, Any] | None,
) -> Decision:
    """Decide by frozen annotator weights, guarded by an unweighted majority.

    The unweighted strict majority keeps one historical weight from
    overriding the current human votes (P6-02).

    Args:
        strategy: ``reliability_weighted_vote`` configuration.
        minimum_support: Threshold of the weighted support.
        votes: Votes in rater order.
        counts: Unweighted votes per outcome.
        metrics: Diagnostics to extend.
        calibration: ``{"weights": {rater: weight}}``.

    Returns:
        The decision.

    Raises:
        PipelineError: ``resolver_unavailable`` without weights for every
            voter; ``invalid_input`` for a weight outside the frozen bounds.
    """
    weights = _snapshot(strategy, calibration)["weights"]
    _require_raters(votes, weights)
    used = {vote.rater: weights[vote.rater] for vote in votes}
    invalid = [
        rater
        for rater, weight in used.items()
        if not MINIMUM_WEIGHT <= weight <= MAXIMUM_WEIGHT
    ]
    if invalid:
        raise PipelineError("invalid_input", f"weights out of bounds: {invalid}")
    totals = {outcome: 0.0 for outcome in counts}
    for vote in votes:
        totals[vote.outcome] += used[vote.rater]
    total = sum(used.values())
    metrics["weights"] = {rater: _metric(weight) for rater, weight in used.items()}
    metrics["weighted_support"] = _metric(max(totals.values()) / total)
    winner = _unique_top(
        {key: numeric.quantize(value) for key, value in totals.items()}
    )
    if winner is None:
        return _tie(metrics)
    passed = numeric.at_least(
        totals[winner] / total, float(minimum_support)
    ) and _strict_majority(winner, counts)
    return _result(winner, counts, [] if passed else [SUPPORT_BELOW_THRESHOLD], metrics)


def _dawid_skene(
    strategy: dict[str, Any],
    minimum_support: Fraction,
    votes: list[Vote],
    counts: dict[str, int],
    metrics: dict[str, Any],
    calibration: dict[str, Any] | None,
) -> Decision:
    """Decide by the latent-label posterior under frozen confusion matrices.

    Args:
        strategy: ``dawid_skene`` configuration.
        minimum_support: Unused; the gate is the unweighted strict majority.
        votes: Votes in rater order.
        counts: Unweighted votes per outcome.
        metrics: Diagnostics to extend.
        calibration: ``{"priors": {...}, "confusion": {...}}``.

    Returns:
        The decision.

    Raises:
        PipelineError: ``resolver_unavailable`` without a confusion matrix
            for every voter, or when the snapshot's priors or confusion
            matrices cover another outcome space.
    """
    snapshot = _snapshot(strategy, calibration)
    confusion = snapshot["confusion"]
    _require_raters(votes, confusion)
    space = set(counts)
    if set(snapshot["priors"]) != space or any(
        set(rows) != space or any(set(row) != space for row in rows.values())
        for rows in confusion.values()
    ):
        raise PipelineError(
            "resolver_unavailable", "the calibration has another outcome space"
        )
    scores = {
        outcome: math.log(snapshot["priors"][outcome])
        + sum(math.log(confusion[vote.rater][outcome][vote.outcome]) for vote in votes)
        for outcome in counts
    }
    peak = max(scores.values())
    scaled = {outcome: math.exp(score - peak) for outcome, score in scores.items()}
    norm = sum(scaled.values())
    posterior = {outcome: value / norm for outcome, value in scaled.items()}
    metrics["posterior"] = _metric(max(posterior.values()))
    winner = _unique_top(
        {key: numeric.quantize(value) for key, value in posterior.items()}
    )
    if winner is None:
        return _tie(metrics)
    reasons = []
    if not _strict_majority(winner, counts):
        reasons.append(SUPPORT_BELOW_THRESHOLD)
    if not numeric.at_least(posterior[winner], DAWID_SKENE_MINIMUM_POSTERIOR):
        reasons.append(POSTERIOR_BELOW_THRESHOLD)
    return _result(winner, counts, reasons, metrics)


RULES: dict[str, Rule] = {
    "categorical_vote": _categorical,
    "multilabel_binary_vote": _binary,
    "dirichlet_vote": _dirichlet,
    "reliability_weighted_vote": _reliability,
    "dawid_skene": _dawid_skene,
}
