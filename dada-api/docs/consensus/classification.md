# Classification Consensus Strategy

## Scope

This strategy resolves one or more independent classification submissions for
one selected image into an accepted canonical label set. It is implemented by
the API consensus worker, never by the browser. Raw submissions remain
immutable and are retained with the resolution provenance.

The project configuration must state whether the task is **single-label** or
**multi-label**. A consensus resolver must not infer that distinction from the
observed labels.

## Inputs and normalization

For one batch item, load the accepted submission revision for every required
assignment in the policy snapshot. Validate that each submission uses only
active project classes and that classification objects have `geometry: null`.

Build a rater-by-class observation matrix:

- In single-label mode, each rater has exactly one selected class; an absent or
  malformed label is an invalid submission, not a negative vote.
- In multi-label mode, create one binary decision per class. A class absent
  from a valid submitted document is an explicit negative observation.
- A missing assignment, expired draft, or waived assignment is **missing**,
  not a negative class observation. First-release consensus batches do not run
  until their full configured group has submitted.

Record a stable `annotator_index`, class ordering, submission content hashes,
and the exact matrix passed to the resolver. The index is internal provenance;
it must not be returned to peer annotators.

## User-selectable Cleanlab resolver

Cleanlab is the first adapter for class resolution. The API must expose only
installed and validated resolver choices in `GET /api/v1/capabilities`, for
example under `consensus_resolvers.classification`. The client sends a stable
resolver identifier plus parameters; it never sends Python callables or package
class names.

The initial supported Cleanlab adapter is a multi-annotator consensus/label
quality resolver backed by Cleanlab's `multiannotator` functionality. It
returns consensus labels and per-example quality information. Additional
Cleanlab-supported strategies may be registered after they have a typed
configuration schema, fixture tests, documented package version range, and a
deterministic result adapter.

The configuration schema contains:

```json
{
  "resolver": "cleanlab_multiannotator",
  "resolver_version": "adapter-semver",
  "package_version": "installed-cleanlab-version",
  "parameters": {
    "pred_probs_source": "model_run_id-or-null",
    "quality_threshold": 0.75
  }
}
```

Model predicted probabilities are optional additional evidence. When supplied,
they must come from a recorded model run over the exact media version and are
never accepted from a browser request. The adapter must also support a
crowd-only path when no trusted model probabilities exist.

## Resolution rules

1. Run the selected registered Cleanlab adapter on the normalized matrix.
2. Convert its output to one canonical class (single-label) or a canonical set
   (multi-label), using an explicit threshold stored in the configuration.
3. Persist vote distribution, consensus confidence/quality, adapter output,
   input hashes, and any model-run identity.
4. Send the item to `review_required` when the result is tied, below the
   configured quality threshold, incompatible with project constraints, or the
   adapter reports an unusable/ambiguous output.
5. Otherwise persist a new accepted resolved annotation. This is a new record;
   it does not modify any submission.

For a simple two-rater tie, the resolver must request review rather than using
class display order, annotator order, or a random seed as an undocumented tie
breaker.

## Outputs and metrics

The canonical document uses the existing classification shape: one object per
accepted class with `geometry: null`. Store diagnostics including class vote
distribution, entropy, selected-label support, Cleanlab quality score(s), and
whether model probabilities were used.

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
below-threshold result, model-probability provenance, duplicate worker results,
and deterministic replay using the recorded package/adapter versions.
