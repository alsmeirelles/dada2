# Phase 5.1 — consensus cohort and review-assignment revision

**Status:** Required before Phase 6 implementation.
**Scope:** This plan revises the Phase 4/5 consensus-assignment contract. It
does not implement a resolver. It introduces the durable readiness event and
the minimum input-snapshot, work-item, review-assignment, review-submission, and
outbox foundation that Phase 6 consumes. Phase 6 implements worker execution,
resolver output handling, proposals, canonical resolutions, and adjudication.

## Purpose

Phase 4/5 currently create one full-image assignment for every member of a
batch's snapshotted consensus group. That model is replaced with a larger
eligible annotator pool and fixed per-image cohorts:

1. each image is initially assigned to exactly
   `required_consensus_annotations` independent annotators;
2. when every member of that initial cohort has submitted, a Phase 6 consensus
   job evaluates all candidates in that image from one immutable input
   snapshot;
3. candidates that meet every automatic quality gate become canonical;
4. a classification result or detection/segmentation candidate that does not
   meet a gate receives `required_consensus_reviewers` additional, scoped
   review assignments;
5. a second worker run evaluates the original and review submissions together;
6. candidates meeting the gates then become canonical; remaining candidates
   require expert adjudication; and
7. a batch is resolved only when every non-cancelled image has an accepted
   canonical resolution.

For this contract, consensus means a canonical decision from independent
submissions: an image-level label set for classification, and a matched
candidate's existence, class, and box or mask for detection and segmentation.
The worker is scheduled for an image case, but derives and evaluates every
candidate within that image.

## Frozen policy contract

Consensus policy has an ordered **eligible pool** plus two positive integers:

| Field | Rule |
| --- | --- |
| `annotator_ids` | Ordered eligible consensus pool. Every member must retain annotation authority when a batch starts. |
| `required_consensus_annotations` | Number of initial full-image assignments per image. Minimum 2; maximum the pool size. |
| `required_consensus_reviewers` | Number of additional candidate-review assignments when automatic resolution requires review. Minimum 1. |

Both count fields are nullable in persistence and on the wire. A `single`
policy requires both fields to be absent or `null`. A `consensus` policy
requires both values and applies the bounds above. The App initializes a policy
being changed from `single` to `consensus` with two initial annotations and one
reviewer; those defaults are not stored on a `single` policy. Database checks
mirror the API rules.

The initial image cohort and each review cohort must be immutable once created. A
review cohort is selected from eligible pool members who are not in the initial
cohort or an earlier review cohort for the same candidate. Therefore the
initial pool must contain at least
`required_consensus_annotations + required_consensus_reviewers` members for a
policy that permits automatic review escalation. The API rejects an invalid
policy rather than reusing an earlier voter as an ostensibly independent
reviewer.

At batch start, `initial_round_robin_v1` selects each initial cohort from the
ordered frozen pool. For zero-based item position `i`, it takes
`required_consensus_annotations` consecutive distinct members beginning at
`i mod pool_size`, wrapping at the end. Items use their existing deterministic
media order. Persist the item position, selected member IDs, ordered input pool,
and algorithm version with the assignments. This balances work, allows a pool
larger than the required cohort, and makes selection auditable.

When Phase 6 requests review evidence, `review_round_robin_v1` starts after the
item's initial cohort, incorporates the candidate's stable ordinal, and walks
the ordered pool while skipping every initial annotator and earlier reviewer
for that candidate. It returns exactly `required_consensus_reviewers` distinct
members. Persist the candidate key and stable ordinal, exclusions, selected
members, ordered input pool, and algorithm version. Keep both selectors behind
a modular interface so a later policy version can name a different strategy.

Changing either required count, the eligible pool, resolver, parameters, or
quality thresholds creates a later policy version and affects only batches
still `preparing`. It never changes an existing cohort, submission, worker
input snapshot, or past accepted resolution.

## Assignment and review workflow

### Initial full-image work

`annotation_assignments` remains the record for an annotator's independent
full-image document. Each consensus `batch_item` receives exactly
`required_consensus_annotations` rows, not one row for every batch-pool member.
The existing uniqueness constraint `(batch_item_id, annotator_id)` remains.
When all active initial assignments are submitted, the item becomes
`awaiting_resolution`. In the same transaction, Phase 5.1 writes exactly one
`consensus.initial_evidence_ready.v1` domain event for that batch item and
cohort generation. Its payload identifies the project, batch, batch item,
policy version, cohort-selection provenance, and ordered assignment,
submission, and content-hash inputs. Phase 6 consumes the event and creates its
versioned worker job and immutable resolver input snapshot.

The batch item stores an `initial_evidence_generation`. Reopening or reassigning
submitted initial work after readiness increments that generation and returns
the item to collection. The immutable earlier event remains audit evidence, but
Phase 6 rejects it as stale by comparing its generation with the batch item.
Completing the exact cohort again emits one event for the new generation. This
preserves the Phase 5 manager-correction workflow without letting an obsolete
snapshot enter consensus.

An initial full-image submission provides positive evidence for matched
candidates and an explicit `no_object` observation for candidates it does not
contain. The worker must not run just because a candidate has several positive
objects: it needs all submissions from the frozen initial cohort so absence is
measured rather than ignored.

### Candidate-scoped review work

When the first run cannot automatically accept a classification result, it
creates an image-level `resolution_work_item` and exactly
`required_consensus_reviewers` image-label review assignments. When it cannot
accept a detection or segmentation candidate, it creates a work item for that
candidate and the same number of candidate-scoped review assignments. A
candidate review assignment shows the source image and the single candidate
context; reviewers do not need to recreate or inspect unrelated objects in the
image.

Review submissions are immutable additional evidence, distinct from ordinary
full-image `annotation_submissions` and from an expert's final adjudication.
They are linked to the candidate work item, reviewer, parent image item, and
the run/input version that created them. The second worker run reads the
original snapshot plus these review submissions. It cannot rewrite, replace,
or silently count an earlier submission twice.

If the second run still fails a threshold, the candidate remains
`review_required` for an authorized owner/manager expert. Expert adjudication
creates a new canonical resolution version; it is not counted as another
independent consensus vote. An image reaches `resolved` only when all of its
candidates are accepted or adjudicated and no image-level blocking condition
remains.

## Required implementation changes

### API persistence and migrations

- Add `required_consensus_annotations` and
  `required_consensus_reviewers` to `annotation_policy_defaults` and
  `annotation_batches` as nullable integers. Require `null` in single mode and
  positive bounded values in consensus mode through database and API
  validation.
- Retain `annotation_batch_annotators` as the frozen eligible pool. Add either
  an `annotation_item_annotators` table or equivalent immutable cohort rows so
  the required initial cohort is queryable without inferring it from mutable
  membership.
- Keep `annotation_assignments` for initial full-image assignments. Add the
  minimum `resolution_inputs`, `resolution_work_items`, candidate
  review-assignment, review-submission, and `outbox_events` persistence needed
  to freeze the Phase 6 boundary. Do not overload a full-image assignment with
  a partial object document. Phase 6 populates work items from resolver output;
  Phase 5.1 supplies and tests the invariant-preserving creation service and
  reviewer workflow.
- Record initial/review cohort selection, run number, source input IDs/hashes,
  and candidate mapping in durable provenance. Add constraints preventing a
  reviewer from appearing twice in the same candidate's evidence cohort.
- Existing single policies migrate with both counts set to `null`. Existing
  development consensus batches must be reset/rebuilt; do not reinterpret
  already-created all-group assignments as selected cohorts.

### API services and contract

- Update `annotation_policy`, batch snapshotting, assignment generation, and
  progress counts to distinguish eligible-pool size from required initial
  assignment count. The affected API modules are
  `models/annotation_policy.py`, `models/batch.py`,
  `services/batches.py`, `services/assignments.py`, and their Pydantic schemas
  and endpoints.
- Replace the all-group assignment invariant with exactly one initial
  assignment for each selected cohort member. Preserve direct ownership,
  idempotent submission, draft recovery, and blindness.
- On the final initial-cohort submission, lock the batch item, verify that the
  exact cohort submitted, and create the
  `consensus.initial_evidence_ready.v1` outbox event exactly once. A database
  uniqueness constraint on event type, batch item, and cohort generation is
  the final duplicate barrier.
- Define candidate-review assignment/review-submission schemas and authorized
  endpoints:
  - `GET /api/v1/projects/{project_id}/review-assignments`;
  - `GET /api/v1/projects/{project_id}/review-assignments/{assignment_id}`;
  - `PUT /api/v1/projects/{project_id}/review-assignments/{assignment_id}/draft`;
  - `POST /api/v1/projects/{project_id}/review-assignments/{assignment_id}/submit`.
  Assigned reviewers may read, save, and submit only their scoped candidate
  context. Owners/managers may inspect raw evidence through manager resources.
  Only the Phase 6 resolution service creates and dispatches review assignments.
- Batch and iteration closure continue to depend on accepted canonical image
  resolutions, never merely on a count of submissions or worker completions.

### App changes

- In project setup, show the eligible annotator pool from system registered
  users, initial annotation count, review count, exact total initial assignment
  estimate, and validation that the pool can supply distinct review annotators.
  Describe review work as the configured additional count per escalated
  candidate because its total cannot be known before resolution.
- Personal queues continue to show full-image initial assignments. Add a
  distinct candidate-review queue that opens the source image in contextual,
  candidate-scoped review mode and never exposes unrelated peer evidence.
- Manager activity distinguishes initial collection, automatic resolution,
  candidate review collection, expert adjudication, and resolved images.
- Preserve local recovery separately for initial assignments and candidate
  review assignments; stale updates must not discard either draft.

### Tests and acceptance

- Policy validation: counts are positive, initial count is at least two, the
  sum of initial and review counts fits the eligible pool, and stale policy
  updates fail.
- Deterministic cohort selection: the same frozen pool and items produce the
  same initial cohorts; rotations are balanced; every item has exactly the
  required count; review selection uses the stable candidate ordinal and never
  reuses an initial or earlier reviewer for that candidate.
- Readiness: fewer than all initial-cohort submissions does not queue work;
  the final one creates exactly one outbox event despite concurrent requests;
  reopen/reassignment advances the evidence generation and makes an earlier
  event stale.
- Evidence: omitted objects become `no_object`; a review submission is linked
  once to its candidate and second-run snapshot; no reviewer sees unrelated
  candidate evidence.
- Foundation boundary: input snapshots, work items, review assignments,
  immutable review submissions, and outbox rows enforce their uniqueness and
  authorization rules without implementing a resolver. Phase 6 verifies
  automatic acceptance, review escalation, second-run acceptance, expert
  adjudication, and stale/duplicate worker-result paths.
- Contract/App tests: setup validation and estimates, selected-cohort queue
  ownership, candidate-review blindness and recovery, and manager progress.
  Extend the existing `test_batches_http.py` and `test_assignments_http.py`
  coverage and the App's project, assignment, and consensus-review tests.

## Documentation and phase gates

Phase 5.1 supersedes only the earlier rule that every image receives an
assignment for every member of the consensus group. It leaves full-image
initial annotation, raw-submission immutability, import provenance, and the
accepted-resolution batch gate intact.

Model seeds are not part of this migration. Phase 7 may add an optional model
seed to a selected next-batch annotator's draft after model-guided acquisition;
it remains separate from imported seeds, review evidence, submissions, and
resolution proposals.

Phase 6 consumes `consensus.initial_evidence_ready.v1`; it owns conversion of
that domain event into a worker job, the command/result envelope, transport,
retry and timeout behavior, and permanent-failure recovery. Phase 6 cannot
start until this plan is implemented and verified, the Phase 6
decision record is complete, and the Consensus Engine Requirements are
approved. Phase 6 owns resolver packages, durable job execution, candidate
matching/aggregation, review work-item resolution, and expert adjudication.
