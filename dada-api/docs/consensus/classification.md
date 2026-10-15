# Classification Consensus Strategy

> **Phase 6 gate:** This document is a normative task annex to the
> [Consensus Engine Requirements](../consensus-engine-requirements.md). Do not
> implement it until that specification is **Approved** and decisions
> `P6-01`–`P6-08` are documented in `docs/phases/phase_6.md`.

## Scope

This strategy resolves one or more independent classification submissions for
one selected image into an accepted canonical label set. It is implemented by
the API consensus worker, never by the browser. Raw submissions remain
immutable and are retained with the resolution provenance.

The project configuration must state whether the task is **single-label** or
**multi-label**. A consensus resolver must not infer that distinction from the
observed labels.

## Inputs and normalization

For one image-level batch item, load the accepted submission revision for every required
assignment in the policy snapshot. Validate that each submission uses only
active project classes and that classification objects have `geometry: null`.

Build a rater-by-class observation matrix:

- In single-label mode, each rater has exactly one selected class; an absent or
  malformed label is an invalid submission, not a negative vote.
- In multi-label mode, create one binary decision per class. A class absent
  from a valid submitted document is an explicit negative observation.
- A missing assignment, expired draft, or waived assignment is **missing**,
  not a negative class observation. Consensus does not run until the complete
  frozen initial cohort defined by [Phase 5.1](../phases/phase_5.1.md) has
  submitted.

Record a stable `annotator_index`, class ordering, submission content hashes,
and the exact matrix passed to the resolver. The index is internal provenance;
it must not be returned to peer annotators.

## Native statistical class resolvers

Class resolution uses DADA-owned statistical implementations over human
annotation observations. It has no trained-model dependency. Model
predictions, predicted probabilities, embeddings, and model seeds are not
resolver inputs and cannot increase confidence or break a tie.

`GET /api/v1/capabilities` exposes only implemented and validated strategies,
for example under `consensus_resolvers.classification`. The client sends the
stable `statistical_class_consensus` pipeline identifier plus a typed strategy
configuration; it never sends Python callables, package class names, or an
arbitrary parameter object.

The Phase 6 native catalog is:

| Strategy | Use | Required behavior |
| --- | --- | --- |
| `categorical_vote` | Single-label observations | Selects by deterministic plurality, strict majority, or a configured supermajority. Ties and failed support gates require review. |
| `multilabel_binary_vote` | Multi-label observations | Treats each class as an explicit positive/negative decision and records the result and uncertainty for every class. |
| `dirichlet_vote` | Single-label or per-class binary observations | Uses a frozen prior and observed human counts to produce a posterior decision and uncertainty diagnostics. |
| `reliability_weighted_vote` | Single-label or per-class binary observations | Uses frozen annotator weights only when they were derived from independent gold or expert-adjudicated evidence. |
| `dawid_skene` | Single-label or per-class binary observations | Uses a sufficient multi-item human-label corpus to estimate annotator confusion and latent labels; the parameter snapshot is frozen for the batch. |

The first three strategies operate directly on the current item's votes.
`reliability_weighted_vote` and `dawid_skene` are conditional capabilities:
they are unavailable unless the policy's minimum sample, class coverage,
identifiability, and convergence rules pass. Automated consensus influenced by
the same annotator is not independent evidence for that annotator's weight.
GLAD and independent Bayesian classifier combination may be added later, after
their stronger cross-item assumptions and operational gates are approved.
Resolvers never silently fall back to another strategy.

Phase 6 implements and fixture-tests all five listed strategies. The first
three form the initial strategy set. The latter two are exposed with explicit
eligibility metadata and may be selected only when the project/batch has the
required frozen evidence snapshot. Their conditional availability is a runtime
data constraint, not a later implementation phase.

Each strategy has its own closed parameter schema. A categorical example is:

```json
{
  "resolver": "statistical_class_consensus",
  "resolver_version": "implementation-semver",
  "parameters": {
    "strategy": "categorical_vote",
    "decision_rule": "supermajority"
  },
  "review_thresholds": {
    "minimum_support": 0.67,
    "maximum_normalized_entropy": 0.7
  }
}
```

Unknown parameters are rejected. Priors, annotator-weight snapshots, and
cross-item calibration-corpus identities are recorded when applicable. All
calculations define numeric precision, convergence tolerance, maximum
iterations, initialization, and tie behavior so replay is deterministic.

## Resolution rules

1. Validate that the selected native strategy applies to the task mode and that
   every strategy-specific eligibility gate is met. An ineligible configured
   strategy fails with `resolver_unavailable`; it does not create review work
   or fall back to another strategy.
2. Run the strategy on the normalized human-observation matrix.
3. Convert its output to one canonical class (single-label) or a canonical set
   (multi-label), using an explicit threshold stored in the configuration.
4. Persist the vote distribution, support, uncertainty, algorithm diagnostics,
   parameter snapshot, and input hashes.
5. Send the item to `review_required` when the result is tied, below the
   configured quality threshold, incompatible with project constraints, or the
   strategy reports an ambiguous output. A numerical or convergence failure is
   an invalid resolver output handled by the Phase 6 failure policy.
6. Otherwise persist a resolution proposal for automatic acceptance under
   `P6-06`. Acceptance creates a new immutable canonical record;
   it does not modify any submission.

For a simple two-rater tie, the resolver must request review rather than using
class display order, annotator order, or a random seed as an undocumented tie
breaker.

## Outputs and metrics

The canonical document uses the existing classification shape: one object per
accepted class with `geometry: null`. Store diagnostics including class vote
distribution, normalized entropy, selected-label support, vote margin, and the
selected strategy's posterior, convergence, or weight diagnostics where
applicable.

Project statistics may aggregate agreement and review rates. They must not
expose annotator-specific quality or ranking to ordinary annotators.

## Per-annotator performance observations

When a resolution is accepted, emit one immutable, project-scoped performance
observation per annotator/class decision. For single-label projects record the
submitted class, canonical class, `class_retained` boolean, and a
submitted-to-canonical confusion-matrix contribution. For multi-label projects
record one observation per class with submitted and canonical positive/negative
values, so precision/recall-style summaries do not hide partial agreement.

Every observation references the source submission and accepted resolution
version, and labels its evaluation source as automated consensus, human
adjudication, or gold standard. Automated-consensus observations are useful
diagnostics but are not automatically eligible to weight the same annotator in
a future resolver run; eligibility follows the project policy described in the
general implementation plan.

## Tests

Fixture tests must cover unanimous agreement, majority agreement, two-rater
tie, multi-label partial agreement, malformed labels, missing data, a
below-threshold result, rejection of model-derived inputs, duplicate worker
results, and deterministic replay using the recorded implementation and
parameter-snapshot versions. Strategy tests also cover prior sensitivity,
zero/low-support classes, invalid or biased weights, insufficient cross-item
evidence, convergence failure, and stable results under equivalent input
ordering.
