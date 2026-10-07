# Phase 6 pending decisions

This is the canonical register for all Phase 6 decisions. The API
implementation plan and App adaptation plan link here rather than duplicating
these entries.

## API approved decisions

| ID | Pending decision | Required documented outcome |
| --- | --- | --- |
| `P6-01` | Resolver/package catalog | Supported Cleanlab and crowd-kit versions, adapter versions, pipeline IDs, dependency isolation, compatibility policy, and capability fallback behavior |
| `P6-02` | Resolver configuration and quality gates | Typed parameters, defaults/bounds, task-specific thresholds, calibration dataset and approval evidence, tie/ambiguity rules, and migration from provisional policy IDs |
| `P6-03` | Segmentation refinement implementation | Maintained STAPLE dependency or approved internal implementation, supported crowd-kit strategies, rasterization/polygonization libraries, and reference fixtures |
| `P6-04` | Adjudicator independence | Whether a contributor may adjudicate the same item, conflict disclosure, role restrictions, optional independent-adjudicator mode, and audit fields |
| `P6-05` | Resolution job execution | Worker/queue topology, command/result envelopes, timeouts, retry/backoff limits, cancellation, stale/duplicate result handling, CPU/memory limits, and permanent-failure recovery |
| `P6-06` | Resolution acceptance/versioning | Automatic acceptance criteria, proposal vs. accepted states, retry configuration/version conflicts, supersession, one-active-result invariant, and adjudication precedence |
| `P6-07` | Evidence and performance policy | Raw evidence retention/access, raw-to-canonical mapping rules, observation eligibility, privacy/minimum-sample rules, and behavior when a resolution is superseded |
| `P6-08` | Resolution work-item and lease policy | Image-case versus derived object/instance work-item identity; creation, closure, and provenance; which manual review actions require a resolution lease; lease duration/renewal/revocation; and concurrent-adjudication conflict handling |

### P6-01 decision

The cleanlab package latest version as of 2026-10-05 is 2.9.0 and crowd-kit is 1.4.2. The solution should use these versions
or newer. All functionality should adjust to these version signatures and changes should be monitored by specific tests.

### P6-02 decision

Outputs pass automatically only when every project-defined, task-specific
criterion and threshold in the frozen batch policy is met. The policy records
`required_consensus_annotations`, `required_consensus_reviewers`, registered
resolver settings, and typed quality gates. The initial worker run evaluates
the selected initial cohort; a candidate that falls short receives the frozen
reviewer count and is evaluated again with the original and review evidence.

Owners/managers may change thresholds or metrics only for a later policy
version and batches still in `preparing`. A change never alters an active
cohort, worker input snapshot, or accepted resolution. Refer to the
[Consensus Engine Requirements](../consensus-engine-requirements.md), task
annexes, and [Phase 5.1](phase_5.1.md).

### P6-03 decision

The user should be able to choose from simple IoU or Dice with specified thresholds to keep overlapping regions or use provided
crowd-kit functionalities. Refer to decision P6-02 and specific consensus documents in docs/consensus.

### P6-04 decision
Only managers and owners can adjudicate on their own annotations or over annotator's data. Annotators have no way to resolve
annotations without passing through consensus, and they don't see the consensus data while it's still being decided. Annotator's
can see the final annotations after consensus is reached.

### P6-05 pending suggestions

The consensus dispatch sequence is decided. When all members of an image's
frozen initial cohort submit, an idempotent worker command resolves every
candidate in that image. If all automatic gates pass, the image resolves. If a
classification result or detection/segmentation candidate falls short, create
the configured number of independent scoped review assignments; after all
review submissions arrive, dispatch a second worker command over the original
and review evidence. Candidates still below threshold require expert
adjudication. The batch resolves only after every non-cancelled image resolves.

The execution mechanism remains pending: choose the queue/worker topology,
versioned command/result envelopes, timeout and resource limits, retry/backoff
policy, cancellation, stale/duplicate result rejection, and permanent-failure
recovery. It must preserve the Phase 5.1 frozen cohorts and immutable evidence.

### P6-06 decision
Automatic acceptance is the default when the relevant initial or review run
meets every frozen threshold. The resolver output is persisted as a
**resolution proposal** and the acceptance transaction creates the immutable
canonical resolution, preserving both states and provenance. A resolution
proposal is produced only by the consensus worker after the evidence snapshot has been
evaluated, and is accepted or adjudicated only by an authorized expert.

A **model seed** is separate Phase 7 preparation work. After active learning
selects the next batch, a completed model run may create an optional starting
annotation in each selected annotator's draft during batch preparation. It does
not count as a submission, consensus vote, resolution proposal, or canonical resolution;
only the annotator's saved submission enters the normal consensus flow.

### P6-07 decision

Retain all raw evidence indefinitely (as long as the project is not deleted). Annotators can see if an annotation was reached
through natural consensus, defined by the expert, adjudicated by manager/owner.

### P6-08 decision

Reviews are image-level for classification and candidate-level for detection
and segmentation. A classification result or detection/segmentation candidate
that misses an automatic gate creates a `resolution_work_item`; candidate work
items contain only that candidate's context and the source image, so reviewers
do not re-annotate unrelated objects. Their immutable review submissions are
additional independent evidence for the second consensus run. An expert
adjudication is a final canonical decision, not another consensus vote. Metrics
and evidence mappings retain this image/candidate granularity.

The optional review-lease scope, duration, renewal, revocation, and concurrent
expert-edit conflict behavior remain pending.


## App approved decisions

| ID | Pending App decision | Required documented outcome |
| --- | --- | --- |
| `A6-01` | Review queue information design | Default filters/sort, row diagnostics, pagination, lazy image/evidence loading, reason vocabulary, and aggregate vs. named evidence visibility |
| `A6-02` | Evidence comparison interaction | Overlay colors/patterns, side-by-side breakpoint, keyboard controls, task-specific metrics, large-object handling, and nonvisual equivalents |
| `A6-03` | Adjudication editing and confirmation | Starting source, draft/recovery key, accept/edit/replace/retry confirmations, unsaved-navigation behavior, and stale-version reconciliation |
| `A6-04` | Resolver configuration UX | Editable approved parameters, advanced-control disclosure, defaults/help text, threshold warnings, and provenance/history presentation |
