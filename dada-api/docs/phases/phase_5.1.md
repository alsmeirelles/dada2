# Phase 5.1 — consensus cohort and review-assignment revision

**Status:** Required before Phase 6 implementation.
**Scope:** This plan revises the Phase 4/5 consensus-assignment contract. It
does not implement a resolver; Phase 6 implements the worker and canonical
resolution lifecycle that consume this contract.

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

The initial image cohort and each review cohort must be immutable once created. A
review cohort is selected from eligible pool members who are not in the initial
cohort or an earlier review cohort for the same candidate. Therefore the
initial pool must contain at least
`required_consensus_annotations + required_consensus_reviewers` members for a
policy that permits automatic review escalation. The API rejects an invalid
policy rather than reusing an earlier voter as an ostensibly independent
reviewer.

At batch start, select the initial cohort for every item by a deterministic
round-robin over the ordered frozen pool. Persist the cohort position and its
member IDs with the item assignments. This balances work, allows a pool larger
than the required cohort, and makes the assignment selection auditable. The
selection algorithm/version and ordered input pool are provenance, not client
choices. Consider that the round-robin algorithm may be changed by another strategy in the future, so keep the selection
modular.

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
`awaiting_resolution`; Phase 6 writes a transactional-outbox command for the
first consensus run.

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
  `annotation_batches`, with database/API validation for consensus mode.
- Retain `annotation_batch_annotators` as the frozen eligible pool. Add either
  an `annotation_item_annotators` table or equivalent immutable cohort rows so
  the required initial cohort is queryable without inferring it from mutable
  membership.
- Keep `annotation_assignments` for initial full-image assignments. Add
  candidate review-assignment and review-submission records linked to
  `resolution_work_items`; do not overload a full-image assignment with a
  partial object document.
- Record initial/review cohort selection, run number, source input IDs/hashes,
  and candidate mapping in durable provenance. Add constraints preventing a
  reviewer from appearing twice in the same candidate's evidence cohort.
- Existing development batches must be reset/rebuilt. Do not reinterpret
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
  exact cohort submitted, and create the Phase 6 resolution-job outbox entry
  exactly once.
- Define candidate-review assignment/review-submission schemas and authorized
  endpoints. Only owners/managers can see raw evidence or dispatch/act on
  review; review annotators receive only their scoped candidate context.
- Batch and iteration closure continue to depend on accepted canonical image
  resolutions, never merely on a count of submissions or worker completions.

### App changes

- In project setup, show the eligible annotator pool from system registered users, initial annotation count, review
  count, total initial assignment estimate, and validation that the pool can
  supply distinct review annotators.
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
  required count.
- Readiness: fewer than all initial-cohort submissions does not queue work;
  the final one creates exactly one outbox event despite concurrent requests.
- Evidence: omitted objects become `no_object`; a review submission is linked
  once to its candidate and second-run snapshot; no reviewer sees unrelated
  candidate evidence.
- Resolution paths: initial automatic acceptance; initial review escalation;
  second-run automatic acceptance; expert adjudication; stale/duplicate worker
  results; cancellation; and batch closure only after every item resolves.
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

Phase 6 cannot start until this plan is implemented and verified, the Phase 6
decision record is complete, and the Consensus Engine Requirements are
approved. Phase 6 owns resolver packages, durable job execution, candidate
matching/aggregation, review work-item resolution, and expert adjudication.
