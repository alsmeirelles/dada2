# Phase 4.1 annotation-sequence revision plan

**Status:** Required before Phase 5 starts. [Phase 5.1](phases/phase_5.1.md)
is additionally required before Phase 6 and supersedes the prior all-group
consensus-assignment interpretation. This document records the accepted
correction to Phase 4. It is an implementation plan, not evidence that the
correction has been delivered.

## Purpose

Phase 4 must establish a permanent pre-annotation `train`, `validation`, and
`test` split. It must queue all validation and test media for the initial
annotation run, but it must queue only the first training batch from the train
split. The current full-train initial batch behavior must be replaced before
Phase 5 work begins.

Phase 4.1 also adds static random projects and audited annotation-label
seeding. These are preparation-time features: they must be complete before any
annotation assignment is distributed.

## Dataset layout

Every project records one immutable `dataset_layout` when its dataset is
prepared:

| Layout | Availability | Prepared work | Later lifecycle |
| --- | --- | --- | --- |
| `split` | Random or active-learning projects | Train, validation, and test membership; all validation/test images; first training batch | Accepted resolutions feed training/evaluation and later acquisition batches |
| `single_batch` | Random projects only | One all-images `initial_annotation` batch | Static annotation only; no splits, validation/test evaluation, model training, or acquisition iterations |

`single_batch` rejects active learning and has no `initial_training_size` or
`iteration_batch_size`. It is a static annotation project, but may use either
single annotation or consensus policy.

For `split`, the configured validation/test sizes and the first-training-batch
selection are materialized while the project is still a draft. Dataset layout,
media inventory, class-index mapping, and split sizes become preparation-locked
once label import begins. Changing one resets the prepared layout and all draft
label imports; the owner/manager must prepare and import again before
activation.

## Adopted workflow

The following numbered flow applies to `split` projects. A `single_batch`
project prepares all activation media as one `initial_annotation` batch,
optionally imports labels, distributes assignments, resolves the batch by its
single/consensus policy, and then closes. It never enters acquisition,
training, or evaluation.

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
6. The first acquisition iteration may start only after every image in the
   validation, test, and initial-training batches has an accepted canonical
   resolution. Submitted assignments alone are insufficient. A `single`-mode
   batch creates that canonical resolution directly from its required
   submission; a `consensus`-mode batch requires consensus resolution or
   adjudication.
   - With random acquisition, select the first training acquisition batch from
     the eligible train pool at that point.
   - With active learning, first train and evaluate from the accepted initial
     resolutions, then select the first model-guided training acquisition
     batch.
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

Each annotation batch item is one complete image. Every assigned annotator
annotates the full image without claiming or leasing it. Detection and
segmentation objects are entries in that image-level submission. Consensus may
derive object/instance-level `resolution_work_item` records for manual review;
only those resolution work items may use a lease, under the Phase 6 policy.

## Label import and seeded annotation work

An owner or manager may import labels only after media, classes, and dataset
layout have been prepared and before any annotation assignment is distributed.
Imports are available for both layouts and both annotation modes.

The initial supported adapters are:

- YOLO detection label sidecars compatible with YOLOv10-or-later detection
  syntax; and
- COCO segmentation documents.

YOLO labels match media by normalized relative path with the image suffix
removed. COCO labels match `images.file_name` by normalized relative path. In
both formats, source class indexes (`class_id` or `category_id`) must match the
prepared project class `display_order`; imports never infer classes by name or
database ID.

Each import records immutable audit provenance: actor, time, format/version,
source-file hashes, class-index-map snapshot, image mappings, parsing results,
and validation errors. The review must reject unknown class indexes, malformed
geometry, duplicate source labels for an image, unmatched paths, and unsafe
paths. Images without a label file remain valid unlabelled images.

Accepted imports create audited seed documents, not submissions or canonical
resolutions. When assignments are distributed, each assigned annotator receives
an independent editable copy of that image's seed document. Saving it creates
the annotator's own draft or submission and preserves a link to the import in
provenance. The consensus engine consumes only those annotator submissions;
imported seed documents never count as votes or accepted resolutions. In single
mode, the user's submitted document creates the canonical resolution. In
consensus mode, consensus or adjudication does so after the required user
submissions arrive.

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
- Redefine `first_acquisition_ready` to require accepted canonical resolutions
  for the three initial batches, not merely assignments or every item in the
  train split. Single-mode batches resolve directly; consensus-mode batches
  resolve through consensus or adjudication.
- Define the training-pool lifecycle in the persistence/service contract:
  completed batch items are ineligible; items not fully annotated when a batch
  is cancelled or incomplete become eligible again; validation and test items
  are never eligible.
- Update API schemas, examples, OpenAPI output, activation responses, and all
  relevant HTTP/service tests.
- Add draft-only dataset preparation and reset operations; enforce the
  `dataset_layout`/acquisition-strategy compatibility rule before activation.
- Add import-session, imported-seed-document, and import-audit persistence;
  owner/manager-only upload, parse, preview, accept, and discard operations;
  and atomic assignment seeding at batch start.

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
- Add a dataset-layout setup step and a label-import step after classes/media
  preparation and before activation. Present split membership or all-images
  single-batch preparation, import preview/errors, and the preparation-reset
  consequence before allowing the user to continue.

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
- The readiness guard succeeds only after all three initial batches have
  accepted resolutions for every image.
- A cancelled or incomplete training batch returns its media to the eligible
  pool; completed training media cannot be selected twice.
- A final acquisition batch may contain fewer than `iteration_batch_size`
  eligible items.
- A random `single_batch` project creates one all-images batch, rejects active
  learning, creates no dataset splits or iterations, and still supports
  consensus.
- YOLO detection and COCO segmentation imports reject invalid index/path/
  geometry input, retain audit provenance, seed each assigned annotator's
  editable document, and never become a consensus vote or canonical resolution
  on their own.
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
