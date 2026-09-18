# Phase 4.1 annotation-sequence revision plan

**Status:** Required before Phase 5 starts. This document records the accepted
correction to Phase 4. It is an implementation plan, not evidence that the
correction has been delivered.

## Purpose

Phase 4 must establish a permanent pre-annotation `train`, `validation`, and
`test` split. It must queue all validation and test media for the initial
annotation run, but it must queue only the first training batch from the train
split. The current full-train initial batch behavior must be replaced before
Phase 5 work begins.

## Adopted workflow

1. A draft project is created from its media pool and configured with its
   held-out validation/test sizes and `iteration_batch_size`.
2. `initial_training_size` is optional. If supplied at project creation, it is
   the requested size of the first training batch. If omitted,
   `iteration_batch_size` is the requested size of the first training batch.
3. Activation deterministically freezes every activation-media item into one
   immutable split: train, validation, or test.
4. The initial annotation run creates exactly three batches:
   - every validation item;
   - every test item; and
   - one `initial_training` batch from previously unselected train items, sized
     by the resolved first-training-batch size.
5. Train items not selected for `initial_training` remain in the frozen train
   split and the unlabeled training pool. They have no initial batch item.
6. The first acquisition iteration may start only after all assignments in the
   validation, test, and initial-training batches are complete under the
   applicable assignment policy.
7. Each acquisition iteration creates one training batch from the eligible
   unlabeled training pool. It uses `iteration_batch_size` as its requested
   size. The initial training batch is not counted as an acquisition iteration.
8. A final training batch smaller than `iteration_batch_size` is allowed when
   fewer eligible training items remain.
9. An item that has not been fully annotated when its training batch is
   cancelled or otherwise ends incomplete returns to the eligible unlabeled
   training pool. A later iteration may select it again. Items that completed
   annotation remain excluded from later training-batch selection.
10. Validation media is used for iterative evaluation. Test media is evaluated
    only at the end and must not control acquisition, model selection, or
    stopping.
11. The user-configured maximum number of acquisition iterations limits the
    number of batches after `initial_training`. The optional user-selected
    validation-metric stopping threshold remains a Phase 7 active-learning
    decision; it must be documented before that work begins.

## Required API correction

- Make `initial_training_size` nullable/optional in project creation and retain
  its resolved value or absence in the project contract. Define the resolved
  first-training-batch size as `initial_training_size` when present, otherwise
  `iteration_batch_size`.
- Validate activation capacity against resolved validation size, resolved test
  size, and the resolved first-training-batch size. Do not require capacity for
  the entire train split to be queued.
- Change activation to persist all three `DatasetSplit` memberships while
  creating batch items only for validation, test, and the selected first train
  batch.
- Preserve deterministic selection provenance for the initial training draw:
  strategy, seed, ordered input fingerprint, requested size, selected media,
  and resolved size. Preserve equivalent split-selection provenance.
- Redefine `first_acquisition_ready` to require only the three initial batches,
  not every item in the train split.
- Define the training-pool lifecycle in the persistence/service contract:
  completed batch items are ineligible; items not fully annotated when a batch
  is cancelled or incomplete become eligible again; validation and test items
  are never eligible.
- Update API schemas, examples, OpenAPI output, activation responses, and all
  relevant HTTP/service tests.

## Required App correction

- Make the first-training-batch override optional in project creation. Explain
  that an omitted override uses `iteration_batch_size`.
- Replace all statements that activation queues the full training split.
  Project review and activity screens must show: all validation items, all test
  items, and the resolved first training batch.
- Calculate initial work from the three initial batches, not from all train
  media. Display the remaining unlabeled training-pool count when available
  from the API.
- Keep subsequent acquisition-batch size distinct from the optional first-batch
  override in form validation, draft recovery, summaries, and project settings.
- Update component and browser tests for the revised wording, request shape,
  and work estimates.

## Development-data reset

This is a development-stage correction. Before implementing the revised
activation path, delete existing development projects and all dependent
splits, batches, assignments, submissions, resolutions, artifacts, and uploads
according to the repository's approved local reset procedure. Rebuild projects
from their source media after the revised policy is deployed. No compatibility
or backfill behavior is required for existing development projects.

The reset procedure, target environments, ownership, and verification query
must be recorded with the implementation change. It must not be used for a
production environment without a separately approved migration and retention
plan.

## Required verification

- Absolute and percentage validation/test configurations freeze the intended
  three-way membership.
- With an explicit `initial_training_size`, the initial training batch has that
  size; without it, it has `iteration_batch_size`.
- Validation and test batches contain their complete frozen splits; remaining
  train items have no batch item and remain eligible.
- The readiness guard succeeds after only the three initial batches are fully
  annotated.
- A cancelled or incomplete training batch returns its media to the eligible
  pool; completed training media cannot be selected twice.
- A final acquisition batch may contain fewer than `iteration_batch_size`
  eligible items.
- Development reset removes old policy data and rebuilt projects follow the
  revised behavior.

## Remaining decisions before later phases

The following are intentionally unresolved and retain their phase gates:

- **Phase 5:** active-learning strategy contract and default; random sampling
  algorithm, seed lifecycle, and UI/provenance; assignment/lease, submission,
  document, and blindness policies.
- **Phase 7:** the available validation metrics, user threshold UX and
  validation, comparison direction, evaluation cadence, active-learning
  algorithm, and how the iteration limit and metric threshold interact. The
  test set remains final-evaluation-only regardless of that decision.

Phase 5 must not start until every required item in this document is
implemented and verified, existing development projects are reset and rebuilt,
and the Phase 5 decision gates in both implementation plans are satisfied.
