# Decisions for Phase 5 implementation

## API decisions
Phase 5 has the pending decisions below. Remarks are made for some of them and any other decisions during implementation
should be registered.

| ID | Pending decision | Required documented outcome |
| --- | --- | --- |
| `P5-01` | Acquisition-strategy project contract | Field name and enum, default for new projects, mutability before/after activation, version/audit behavior, development-reset treatment, and OpenAPI examples |
| `P5-02` | Random acquisition semantics | Sampling algorithm/order, seed lifecycle, fingerprint, and provenance. The eligible pool, completed/cancelled/incomplete-item handling, final undersized-batch rule, and `iteration_batch_size` requested-size rule are fixed by the [Phase 4.1 revision plan](phase-4-annotation-sequence-revision-plan.md). |
| `P5-03` | Image-assignment access | Direct assigned-image access without annotation leases or claims; queue ordering; disconnect and recovery behavior; manager reassignment; and concurrent visibility of the same image to the configured consensus group |
| `P5-04` | Assignment reassignment and submission lifecycle | Reassignment authority and audit before submission; immutable full-image submission revisions; whether submitted work may reopen; duplicate-completion response; and return of cancelled/incomplete images to the eligible train pool |
| `P5-05` | Full-image annotation document contract | Versioned classification/detection/segmentation image-document schemas; explicit single-label vs. multi-label configuration; object entries within detection/segmentation documents; coordinate precision; empty-annotation semantics; geometry limits; validation errors; and payload/complexity limits |
| `P5-06` | Blindness release boundary | Exactly what aggregate state an annotator may read before submission, after own submission, after item resolution, and after batch closure; event redaction rules |

### P5-01

Default acquisition strategy is RANDOM selection from unlabeled pool. The acquisition strategy may be changed to active learning
after activation for prepared split projects. A static `single_batch` project
cannot use or switch to active learning, has no later acquisition iterations,
and may still use consensus annotation.

## P5-03

Automatically save annotated objects at fixed 10 minute intervals. Recover from the last saved configuration (automatically saved or user manually
save the image work).

During optional consensus, the same image may have objects assigned to different annotators. New objects are not created at this stage.

Manager reassignment while still at an annotator's responsibility is not supported

## P5-04

Manager reassignment or reopen before and after submission is possible. Managers may reopen for the same annotator or reassign a submission for correction before it goes
into consensus resolution. Annotators may not cancel or reject assignments for themselves. Managers may cancel the assignment but should be warned that cancelling will
return the images to the unlabeled training pool.

## P5-05

Empty annotations are possible for detection and segmentation projects and annotators may explicitly mark an image as empty.
Multi-label for detection and segmentation should be supported.
Reject unknown classes and malformed or self-intersecting geometry.

Before assignment distribution, an owner or manager may import YOLO detection
or COCO segmentation labels. Match source class indexes to the prepared project
class `display_order`; retain file, mapping, actor, and validation provenance.
An accepted import creates editable seed documents only. When an annotator saves
or submits seeded work, it becomes that annotator's draft/submission with an
immutable link to the import; the import is never a submission, consensus vote,
or accepted resolution.

## P5-06

Before submission, show only the annotator’s assignment and project instructions.
Do not reveal peer annotations, agreement, submission counts, consensus status, or identity.
After their own submission, show that their work was received, but keep peer evidence hidden while collection continues.
After resolution, allow managers and authorized reviewers to inspect evidence.

## APP decisions

| ID | Pending App decision | Required documented outcome |
| --- | --- | --- |
| `A5-01` | Acquisition-strategy setup UX | Control placement and wording, default shown to users, validation, review summary, draft recovery, settings visibility, and treatment when the API says the setting is locked |
| `A5-02` | Random-acquisition presentation | Explanation of unlabeled-pool eligibility and reproducibility, manager visibility of seed/strategy provenance, empty/exhausted-pool messaging, and removal of model-guided language |
| `A5-03` | Image-assignment queue UX | Direct assigned-image queue ordering/filtering, navigation, offline and stale-version recovery, manager reassignment messaging, accessibility behavior, and no annotation-lease controls |
| `A5-04` | Submission and recovery UX | Reopen rules, success terminology, stale-draft reconciliation choices, recovery expiry/display, empty-annotation confirmation, and visibility after own submission |

### A5-01

Place the acquisition-strategy choice in project setup beside the learning
settings. Offer **Random acquisition** and **Active learning**, with Random
selected by default. Explain that the choice controls future training
acquisition batches only; it does not alter the fixed train, validation, and
test splits or the initial annotation batches. For Random projects, also let
the owner choose `split` or static `single_batch`; the latter has no held-out
sets or acquisition loop but permits consensus.

Persist the server-returned value in the project review, draft recovery, and
project settings views. The review must state that random acquisition selects
from the eligible unlabeled training pool after the preceding image batch has
an accepted canonical resolution. If the API reports that the setting is
locked, render it read-only with the server's value and explain when it became
locked; do not retain a conflicting browser-only draft.

### A5-02

For Random acquisition, use plain language: “Randomly selected from the
remaining eligible training images.” Do not show model scores, confidence,
ranking, training progress, or any model-guided terminology.

Managers may inspect the completed batch's strategy, server-generated seed,
input fingerprint, requested size, selected size, and selection time. Explain
that validation and test images are never eligible, completed training images
are excluded, and cancelled or incomplete training images may return to the
pool. When the pool is empty, show that acquisition has finished; when fewer
images remain than `iteration_batch_size`, state that the final batch may be
smaller.

### A5-03

Show a caller-specific queue of direct complete-image assignments. Do not show
claim, lease, renewal, expiry, release, or lease-loss controls. A consensus
annotator can open the same image independently of peers; the queue must never
hide an assignment because another annotator is working on that image.

Provide filters for batch purpose and personal state (`available`, `in
progress`, `submitted`), deterministic ordering supplied by the API, and
keyboard-accessible next/previous navigation. Store unsaved work against the
`assignment_id` and its version. On offline use or a stale-version response,
retain the local draft, refetch the assignment, and offer a clear resume or
reconciliation path. Display manager reassignment or reopen controls only when
the authorized API action exists; annotators have no self-cancel action.

### A5-04

Autosave full-image work every ten minutes and provide an explicit Save action.
On return, restore the newest server or local recovery draft for the same
`assignment_id`, identify its save time, and never present recovery data as a
submitted annotation.

Before final submission, require confirmation for an explicitly empty
detection or segmentation image. Submit through an idempotency key and show
**Submission received** after success. Do not state that the image is resolved:
in single mode it awaits the canonical-resolution response, while in consensus
mode it awaits the other required submissions and then consensus or
adjudication. After submission, keep peer evidence, peer progress, and
consensus diagnostics hidden. If a manager reopens or reassigns work, preserve
the annotator's recoverable draft and explain the new assignment state.

Only owners/managers may reach the import screen, which appears before
assignment distribution. Show import parsing/mapping errors and an explicit
accept/discard step. A seeded draft may say that it began from imported labels,
but it must identify the saving annotator as the author of the saved work and
must not describe the import as a resolved annotation.
