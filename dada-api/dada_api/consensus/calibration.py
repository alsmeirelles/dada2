"""Frozen evidence snapshots that make the conditional class strategies eligible."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import special

from dada_api.consensus import numeric
from dada_api.consensus.class_strategies import MAXIMUM_WEIGHT, MINIMUM_WEIGHT, Vote
from dada_api.consensus.protocol import PipelineError

MAX_ITERATIONS = 100
TOLERANCE = 1e-6
DECISIONS_PER_RATER = 30
REFERENCES_PER_OUTCOME = 5
CALIBRATION_ITEMS = 50
RATERS_PER_ITEM = 3
OBSERVATIONS_PER_RATER = 20
OBSERVATIONS_PER_OUTCOME = 5


@dataclass(frozen=True)
class Reference:
    """One past decision of a rater next to its independent reference outcome.

    Attributes:
        rater: Stable annotator identifier.
        submitted: Outcome the rater submitted.
        reference: Expert-adjudicated or gold outcome of the same decision.
    """

    rater: str
    submitted: str
    reference: str


@dataclass(frozen=True)
class Calibration:
    """The eligibility verdict and frozen parameters of a conditional strategy.

    Attributes:
        eligible: Whether every evidence and convergence gate passed.
        missing: The exact gaps, each naming its requirement.
        parameters: The snapshot ``decide`` consumes; empty when ineligible.
        report: The counts the verdict was computed from.
    """

    eligible: bool
    missing: tuple[dict[str, Any], ...]
    parameters: dict[str, Any]
    report: dict[str, Any]


@dataclass(frozen=True)
class Fit:
    """The final state of a Dawid-Skene expectation-maximization run.

    Attributes:
        priors: Outcome prior per outcome index.
        confusion: Probabilities indexed by rater, true, and observed outcome.
        iterations: Completed iterations.
        converged: Whether the log-likelihood change fell below the tolerance.
        log_likelihood: Final log-likelihood of the corpus.
    """

    priors: np.ndarray
    confusion: np.ndarray
    iterations: int
    converged: bool
    log_likelihood: float


def reliability_weights(
    references: Sequence[Reference], pool: Sequence[str], outcomes: Sequence[str]
) -> Calibration:
    """Derive annotator weights from independent reference outcomes (P6-02).

    The weight is the Beta(2,2)-smoothed accuracy divided by the pool's mean
    smoothed accuracy, then clipped to the frozen bounds without
    renormalizing. References of raters outside the pool are ignored.

    Args:
        references: Expert-adjudicated or gold decisions.
        pool: Every annotator the snapshot must cover.
        outcomes: Outcome space each rater must have been checked on.

    Returns:
        The calibration; weights only when every pool rater is covered.

    Raises:
        PipelineError: ``invalid_input`` when a reference names an outcome
            outside the outcome space.
    """
    _require_outcomes(
        {reference.submitted for reference in references}
        | {reference.reference for reference in references},
        outcomes,
    )
    raters = sorted(pool)
    decisions = Counter(reference.rater for reference in references)
    agreements = Counter(
        reference.rater
        for reference in references
        if reference.submitted == reference.reference
    )
    coverage = Counter(
        (reference.rater, reference.reference) for reference in references
    )
    missing = []
    for rater in raters:
        if decisions[rater] < DECISIONS_PER_RATER:
            missing.append(
                {
                    "requirement": "decisions_per_rater",
                    "rater": rater,
                    "required": DECISIONS_PER_RATER,
                    "found": decisions[rater],
                }
            )
        for outcome in outcomes:
            if coverage[rater, outcome] < REFERENCES_PER_OUTCOME:
                missing.append(
                    {
                        "requirement": "observations_per_outcome",
                        "rater": rater,
                        "outcome": outcome,
                        "required": REFERENCES_PER_OUTCOME,
                        "found": coverage[rater, outcome],
                    }
                )
    report = {
        "raters": {
            rater: {
                "decisions": decisions[rater],
                "agreements": agreements[rater],
                "references_per_outcome": {
                    outcome: coverage[rater, outcome] for outcome in outcomes
                },
            }
            for rater in raters
        }
    }
    if missing:
        return Calibration(False, tuple(missing), {}, report)
    raw = {rater: (agreements[rater] + 2) / (decisions[rater] + 4) for rater in raters}
    mean = sum(raw.values()) / len(raw)
    weights = {
        rater: _quantized(min(max(value / mean, MINIMUM_WEIGHT), MAXIMUM_WEIGHT))
        for rater, value in raw.items()
    }
    return Calibration(True, (), {"weights": weights}, report)


def dawid_skene(
    items: Sequence[Sequence[Vote]],
    pool: Sequence[str],
    outcomes: Sequence[str],
    max_iterations: int = MAX_ITERATIONS,
) -> Calibration:
    """Estimate frozen Dawid-Skene priors and confusion matrices (P6-02).

    Only votes of pool raters are used, and only items where at least three
    distinct pool raters voted enter the calibration corpus.

    Args:
        items: Votes of past items, one sequence per item.
        pool: Every annotator the snapshot must cover.
        outcomes: Ordered outcome space.
        max_iterations: Iteration limit after which the fit has not converged.

    Returns:
        The calibration; parameters only when the corpus is sufficient and
        the fit converged.

    Raises:
        PipelineError: ``invalid_input`` when a vote names an outcome outside
            the outcome space or a rater voted twice in one item.
    """
    _require_outcomes({vote.outcome for item in items for vote in item}, outcomes)
    for item in items:
        raters_of_item = [vote.rater for vote in item]
        if len(set(raters_of_item)) != len(raters_of_item):
            raise PipelineError("invalid_input", "a rater voted twice in one item")
    members = set(pool)
    raters = sorted(members)
    corpus = []
    for item in items:
        votes = sorted(
            (vote for vote in item if vote.rater in members),
            key=lambda vote: vote.rater,
        )
        if len(votes) >= RATERS_PER_ITEM:
            corpus.append(votes)
    per_rater = Counter(vote.rater for item in corpus for vote in item)
    per_outcome = Counter(vote.outcome for item in corpus for vote in item)
    missing = []
    if len(corpus) < CALIBRATION_ITEMS:
        missing.append(
            {
                "requirement": "calibration_items",
                "required": CALIBRATION_ITEMS,
                "found": len(corpus),
            }
        )
    for rater in raters:
        if per_rater[rater] < OBSERVATIONS_PER_RATER:
            missing.append(
                {
                    "requirement": "observations_per_rater",
                    "rater": rater,
                    "required": OBSERVATIONS_PER_RATER,
                    "found": per_rater[rater],
                }
            )
    for outcome in outcomes:
        if per_outcome[outcome] < OBSERVATIONS_PER_OUTCOME:
            missing.append(
                {
                    "requirement": "observations_per_outcome",
                    "outcome": outcome,
                    "required": OBSERVATIONS_PER_OUTCOME,
                    "found": per_outcome[outcome],
                }
            )
    report: dict[str, Any] = {
        "items": len(items),
        "calibration_items": len(corpus),
        "observations_per_rater": {rater: per_rater[rater] for rater in raters},
        "observations_per_outcome": {
            outcome: per_outcome[outcome] for outcome in outcomes
        },
    }
    if missing:
        return Calibration(False, tuple(missing), {}, report)
    fit = _fit(corpus, raters, outcomes, max_iterations)
    report |= {
        "iterations": fit.iterations,
        "converged": fit.converged,
        "log_likelihood": _quantized(fit.log_likelihood),
    }
    if not fit.converged:
        gap = {"requirement": "convergence", "iterations": fit.iterations}
        return Calibration(False, (gap,), {}, report)
    parameters = {
        "priors": {
            outcome: _quantized(fit.priors[index])
            for index, outcome in enumerate(outcomes)
        },
        "confusion": {
            rater: {
                true: {
                    observed: _quantized(fit.confusion[r, k, o])
                    for o, observed in enumerate(outcomes)
                }
                for k, true in enumerate(outcomes)
            }
            for r, rater in enumerate(raters)
        },
        "iterations": fit.iterations,
    }
    return Calibration(True, (), parameters, report)


def _fit(
    corpus: list[list[Vote]],
    raters: list[str],
    outcomes: Sequence[str],
    max_iterations: int,
) -> Fit:
    """Run deterministic expectation-maximization from the vote fractions.

    Each iteration is an M-step with additive smoothing 1 followed by an
    E-step; the fit converges when the log-likelihood changes by less than
    ``TOLERANCE`` between two iterations, so a single iteration never does.

    Args:
        corpus: Calibration items, each with its votes in rater order.
        raters: Pool raters in sorted order.
        outcomes: Ordered outcome space.
        max_iterations: Iteration limit.

    Returns:
        The final parameters and convergence state.
    """
    rater_index = {rater: index for index, rater in enumerate(raters)}
    outcome_index = {outcome: index for index, outcome in enumerate(outcomes)}
    flat = [(i, vote) for i, item in enumerate(corpus) for vote in item]
    item_of = np.array([i for i, _ in flat])
    rater_of = np.array([rater_index[vote.rater] for _, vote in flat])
    observed = np.array([outcome_index[vote.outcome] for _, vote in flat])
    size = len(outcomes)
    labels = np.zeros((len(corpus), size))
    np.add.at(labels, (item_of, observed), 1.0)
    labels /= labels.sum(axis=1, keepdims=True)
    previous = None
    for iteration in range(1, max_iterations + 1):
        priors = (labels.sum(axis=0) + 1) / (len(corpus) + size)
        counts = np.zeros((len(raters), size, size))
        np.add.at(counts, (rater_of, slice(None), observed), labels[item_of])
        confusion = (counts + 1) / (counts.sum(axis=2, keepdims=True) + size)
        scores = np.tile(np.log(priors), (len(corpus), 1))
        np.add.at(scores, item_of, np.log(confusion[rater_of, :, observed]))
        evidence = special.logsumexp(scores, axis=1)
        labels = np.exp(scores - evidence[:, None])
        likelihood = float(evidence.sum())
        if previous is not None and abs(likelihood - previous) < TOLERANCE:
            return Fit(priors, confusion, iteration, True, likelihood)
        previous = likelihood
    return Fit(priors, confusion, max_iterations, False, likelihood)


def _require_outcomes(found: set[str], outcomes: Sequence[str]) -> None:
    """Refuse calibration evidence that names an outcome outside the space.

    Args:
        found: Outcomes named by the evidence.
        outcomes: Ordered outcome space.

    Raises:
        PipelineError: ``invalid_input`` naming the unknown outcomes.
    """
    unknown = sorted(found - set(outcomes))
    if unknown:
        raise PipelineError("invalid_input", f"outcomes outside the space: {unknown}")


def _quantized(value: float) -> float:
    """Return a parameter or diagnostic as a plain float quantized to six places.

    Args:
        value: Finite value, possibly a NumPy scalar.

    Returns:
        The quantized float.
    """
    return float(numeric.quantize(value))
