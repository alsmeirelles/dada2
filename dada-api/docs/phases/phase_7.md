# Phase 7 pending decisions

This is the canonical decision record for Phase 7. It contains the shared API
decisions `P7-01`–`P7-09` and the App decisions `A7-01`–`A7-03` from the
[API implementation plan](../api-implementation-plan.md) and the
[App adaptation plan](../../../dada-app/docs/annotator-disagreement-adaptation-plan.md).

The individual decision records below are the source of truth for Phase 7 decision status; the register summarizes them. Phase 7 implementation must not begin until the pending decisions are resolved and approved here. App issues I7-04 and I7-05 are implementation stages: address and verify them when implementation begins; they do not block starting the phase. Their details and evidence are tracked in [Phase 7 App issues](../../../dada-app/docs/issues_before_phase7.md).

When a decision is approved, replace its pending status with **APPROVED** and
record the chosen behavior, its main reason, any contract change, how it will be
verified, the approving owner, and the approval date. Add further detail only
when the decision needs it. This file is the source of truth for those
resolutions; the two implementation plans retain the phase gate and link here.

## Decision register

| ID | Area | Required outcome | Status |
| --- | --- | --- | --- |
| `P7-01` | Active-learning run and dataset export boundary | Exact accepted annotations given to the internal active-learning worker, its selection result, temporary run/artifact retention, and the final annotated-dataset export | **APPROVED** |
| `P7-02` | Active-learning selection | Initial task adapter, uncertainty ranking, media versus object targets, deterministic ties, object context, and unavailable-adapter behavior | **APPROVED** |
| `P7-03` | Iteration stopping and recovery | Validation metric per task, optional target, maximum iterations, evaluation point, and retry behavior | **APPROVED** |
| `P7-04` | Assisted segmentation | Whether it ships in Phase 7 and, if so, the provider, minimal request/result contract, authorization, timeout, and non-vote rule | **APPROVED** |
| `P7-05` | Quality statistics | Published metrics, formulas, authorized roles, and minimum-sample suppression | **APPROVED** |
| `P7-06` | HEIC/HEIF ingestion and browser rendition | Accepted types, decoder, original retention, deterministic lossless WebP rendition, pixel-coordinate invariant, delivery contract, App selection behavior, and verification | **APPROVED** |
| `P7-07` | Assistance model lifecycle and contract | Model availability, provider and authorized request/result behavior | **APPROVED** |
| `P7-08` | Batch and evaluation contract | Snapshots, jobs, evaluation cadence and recovery semantics | **APPROVED** |
| `P7-09` | DADA selection edge cases | Budget, clustering, insufficient candidates and reproducibility | **APPROVED** |
| `A7-01` | Acquisition activity UX | User-visible random/active-learning states, failure message, and retry action | **APPROVED** |
| `A7-02` | Quality presentation | Manager-visible values, suppression display, accessible table, and no annotator ranking | **APPROVED** |
| `A7-03` | Assisted-segmentation UX | Trigger, preview, accept/discard/edit, and safe failure without changing the draft | **APPROVED** |

## Fixed Phase 7 constraints

The resolutions below must preserve these existing decisions:

- Any training and evaluation used for selection are internal to the active-learning solution. Exporting, deploying, or experimenting with production models is outside the application scope.
- The durable product is an annotated dataset. Its export contains accepted
  resolutions and their media/target provenance; raw submissions, unresolved
  annotations, imported seeds, model seeds, and consensus proposals are
  excluded.
- The initial training batch does not count as an acquisition iteration. Each
  acquisition follows accepted resolutions; fixed test data is used only for
  final evaluation.
- Random acquisition may run only after the initial images are resolved.
  Active learning requests a batch from the selected solution using the accepted training set and eligible pool. Static `single_batch` projects do not acquire.
- Classification active learning selects media. Model-guided detection and
  segmentation select object targets inside media. The target's model-generated
  box or mask identifies the object to annotate, while the source image remains
  visible. The annotator labels only that target.
- Active learning and consensus are independent choices. A selected target may
  use either annotation mode; the model target cue is never a consensus vote.
- Training uses accepted `initial_training` data plus accepted acquisition data
  from earlier iterations. Validation is evaluation-only and the fixed test
  split is final-evaluation-only. Detection/segmentation training uses accepted
  selected object annotations and source-media context, never unselected
  objects from the image.
- A model seed is optional per-assignment draft assistance. It is never a
  submission, consensus vote, resolution proposal, or canonical resolution.
- Assisted-segmentation output is an aid for the annotator who owns the active
  assignment. It is never an independent vote.
- Phase 7 quality metrics must not create annotator-facing rankings or feed
  consensus weights. Project-level performance summaries use the immutable
  Phase 6 observations.
- An HEIC/HEIF source and its browser rendition share one canonical oriented
  pixel plane. The rendition has exactly the same width and height as the
  decoded primary source image, with no resize, crop, padding, or second
  orientation transform. Annotation geometry is stored in that plane.

## Resolution records

### P7-01 — Active-learning run and dataset export boundary

**Status:** **APPROVED**

**Purpose.** Define the small handoff between DADA and its internal
active-learning worker, and keep that handoff separate from the annotated
dataset delivered to the user. This prevents an iteration from training on the
wrong split, unresolved annotations, or unselected objects. It is not a general
training platform, model registry, or production-model export.


**Approved decision, clarified:** Use one internal run record for each batch request. The API supplies an immutable snapshot of accepted training resolutions and media, the eligible unlabeled pool, task, class mapping, requested size and solution configuration. Validation data, if supplied for evaluation, is separate from the acquisition pool. The selected solution returns an ordered batch of eligible media or object targets and provenance under the [shared contract](../active_learning/active_learning_requirements_specification.md#batch-selection-interface). Selection methods, training and model artifacts are solution internals. Performance evaluations use the target model at a user-selected frequency, not a proxy or helper model; cadence and stopping follow P7-03 and P7-08. Record evaluation results with target-model, data-snapshot and iteration provenance.

The API validates and records the batch, manages single-annotation or consensus workflows, and maintains accepted annotations in the canonical labeled pool. The next request uses a new accepted-data snapshot. Proxy and helper models and checkpoints are not kept by default. A configuration parameter may explicitly enable their retention. Temporary artifacts needed for a run or retry may be kept until no longer needed, then deleted unless retention is enabled. Record failures and retry against the same snapshot; retain run and evaluation provenance independently of helper artifacts.

Dataset export should be possible at any iteration (training, validation and test sets). Export the final accepted
annotations, media, classes, and provenance; do not export an application model or expose a generic training API. Dataset
export format for detection and segmentation should be selected by the user. Available formats: YOLO normalized or COCO.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09


### P7-02 — Active-learning selection

**Status:** **APPROVED**

**Purpose.** Give active learning an executable selection rule. This is the
core product decision: without it, the system knows when to run an iteration
but not how to choose the most useful next annotations.

**Approved decision:** use DADA as the active learning framework [DADA](../active_learning/dada_active_learning_requirements_specification.md).
Other frameworks can be implemented in the future and if another option exists, the user may select it from a dropdown.
General modularity requirements and architecture definitions for any active learning solution are defined in [AL](../active_learning/active_learning_requirements_specification.md)
and should be followed.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09


### P7-03 — Iteration stopping and recovery

**Status:** **APPROVED**

**Purpose.** Make the annotation loop stop and recover predictably. This keeps
the API, worker, and App from applying different stopping rules or advancing
after a failed iteration.


**Decision:** Let the user choose accuracy or F1 for classification, mAP@50 for
detection, and mean IoU for segmentation. Let the user choose when to evaluate, with possibilities to
evaluate the target model at every acquisition iteration or after every K iterations. Stop when the maximum acquisition count is reached or the optional metric target is met. Retry a failure from the same accepted-resolution snapshot as a new attempt.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09

### P7-04 — Assisted segmentation

**Status:** **APPROVED**

**Purpose.** Decide whether Phase 7 includes interactive segmentation help. If
it does, define enough of the boundary that a suggestion cannot bypass
assignment authorization or become annotation evidence by itself.

**Decision:** Implement the feature.

**Rationale:** Use the last trained model (if in active learning mode) to produce masks or bounding boxes for segmentation / detection assignments. Accept point/box prompts and return editable polygons in original-
image coordinates. A timeout leaves the draft unchanged. The annotator must
accept the suggestion before it becomes draft geometry, and it never counts as
a submission or vote. If the feature is deferred, approve that explicit
deferral and keep the current placeholder.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09

### P7-05 — Quality statistics

**Status:** **APPROVED**

**Purpose.** Ensure that published quality numbers have one meaning and do not
expose unreliable or private annotator comparisons.

**Decision:** Publish review rate, resolution rate, and the
task-appropriate agreement summaries. Owners and managers may see performance
summaries after at least 30 eligible decisions; hide cells below five
observations. Annotators do not receive named performance data or rankings.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09


### P7-07 — Assistance model lifecycle and contract

**Status:** **APPROVED**

**Decision needed:** Define the provider, model selection and retention, availability before the first target evaluation and outside AL mode, authorization, timeout, and request/result contracts for detection and segmentation assistance. Reconcile boxes, polygons and supported prompts with A7-03.

**Decision:** Use the latest compatible target model with an explicit assistance retention policy; report assistance unavailable when no compatible model exists. Authorize against the active assignment, impose a bounded timeout, and return typed geometry in canonical coordinates. Never persist a suggestion without explicit acceptance into the draft.

**Implementation suggestions:** Use an internal provider interface that loads the latest compatible retained target model and reports a stable unavailable reason when absent. Apply a configurable 30-second timeout; authorize project membership and the active assignment before reading media. Accept an assignment ID, canonical-plane point/box prompts and a request ID; return typed box or polygon geometry, model provenance and status. Reject invalid coordinates and keep drafts unchanged on timeout or failure. Define target-model retention and cleanup for assistance independently of helper-model retention.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09

### P7-08 — Batch and evaluation contract

**Status:** **APPROVED**

**Decision needed:** Specify versioned request/result schemas, snapshot and media access, job states, errors, idempotency and retry; define evaluation data requirements and delivery of results. Specify K bounds and first evaluation point, metric aggregation, threshold direction, empty validation and pool exhaustion behavior.

**Decision:** Use immutable identified snapshots and a durable idempotent job per iteration and attempt; retries use the same snapshots. Evaluations should be performed over the validation set (defined at project creation) and over the test set after the last iteration and persist target-model metrics and provenance. Evaluate after every K completed acquisition iterations, K >= 1, and stop on an explicitly configured threshold or maximum; define task-specific averaging and unavailable-data errors before implementation.

**Implementation suggestions:** Use a versioned manifest schema shared by input and selection output, preserving media references and adding selected object geometry when needed; include snapshot IDs, task, class mapping, requested size, solution version and configuration. Use queued, running, succeeded, failed and cancelled job states with structured errors and an idempotency key scoped to project, iteration and attempt. Retry as a new attempt against the same immutable snapshots. Persist evaluation data and model provenance; define macro F1 across classes and class-averaged IoU with an explicit absent-class rule, treat all listed metrics as higher-is-better, and report an unavailable-data error for empty validation. Define first evaluation at iteration K, with final test evaluation after the last iteration. The exact schema and rules require approval.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09

### P7-09 — DADA selection edge cases

**Status:** **APPROVED**

**Decision needed:** Resolve requested budget versus DADA configuration, insufficient candidates, empty or undersized clusters, zero uncertainty, quota redistribution, random seeds and tie-breaking.

**Decision:** The batch request is authoritative for Q. Cap clusters by candidate count, allocate by largest remainder with capacity-aware redistribution, use equal weights when all scores are zero, and return all available candidates with a reason when fewer than Q exist. Persist seeds and use stable identifiers for ties; define empty-pool behavior explicitly.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-10

### P7-06 — HEIC/HEIF ingestion and browser rendition

**Status:** **APPROVED**

**Decision.** The App and API accept `.heic` and `.heif` files with
`image/heic` and `image/heif` media types. Sequence extensions and media types
remain unsupported because one uploaded file must identify one dataset image.
The API adds `pillow-heif`, inspects the actual decoded format, and uses the
container's primary image. HEIF orientation and mirror transformations are
applied exactly once before dimensions are recorded.

The verified original bytes remain the content-addressed source. At upload
completion the API also creates one deterministic, versioned, lossless WebP
sidecar from the oriented primary image. The conversion uses a deterministic
8-bit sRGB RGB or RGBA pixel representation, preserves alpha when present,
carries the resulting color profile, and enables the WebP encoder's exact mode
to preserve transparent RGB values. It performs no resize, crop, padding,
sharpening, or other image alteration. Lossless WebP is required so conversion
introduces no
additional compression loss that could hide small objects. Here, source and
rendition being the same size means identical pixel width and height; their
encoded byte lengths are not expected to match.

`ContentObject.width` and `ContentObject.height` describe this canonical
oriented pixel plane. The signed media-content route serves the WebP sidecar as
`image/webp` for HEIC/HEIF sources and reports the sidecar byte length. Existing
JPEG, PNG, and WebP delivery remains unchanged. Browser annotation, review,
assisted segmentation, training, and evaluation use the same canonical
rendition. A consumer that decodes the retained original and applies its HEIF
transformations obtains the same dimensions and coordinate origin, so stored
boxes, polygons, and masks map directly to the original.

The sidecar key is derived from the project, source SHA-256, and rendition
version, for example `renders/v1/<source-sha>.webp`. This preserves the existing
source digest and deduplication invariant and requires no database migration.
Creation is atomic; duplicate source content reuses the existing sidecar. A
source is not promoted to usable media unless full decode and sidecar creation
succeed. CPU-bound decode/encode work runs in a bounded thread rather than on
the async event-loop thread. Invalid, unsupported, over-limit, or failed
conversions fail the upload with a stable structured error and never expose a
raw-only media record. Decode, declared/actual-format mismatch, and decoder
security-limit failures use `invalid_image`; a valid decoded image that cannot
be written as the required rendition uses `image_conversion_failed`.

The App uploads original bytes and does not bundle a HEIC decoder or transcode
in the browser. One shared format registry maps MIME types and extensions,
builds both file-input `accept` values, and filters formats against
`supported_image_media_types` from `/api/v1/capabilities`. Both new-project and
resumed-draft selection use that registry and describe HEIC/HEIF support in the
visible format help.

Learning manifests identify the source SHA-256 and rendition version. Image
consumers use the rendition path so the pixels presented to models and
assisted-segmentation providers are the pixels on which browser annotations
were drawn. Export metadata retains the canonical width, height, orientation
rule, and rendition identity alongside the original source identity.

**Rationale.** Raw HEIC delivery depends on browser support, while client-side
conversion duplicates a heavy codec in every browser and lets conversion
behavior vary by client. A server-created lossless rendition gives every App,
worker, and export one display plane, preserves the uploaded source for
provenance, and keeps storage changes small.

**Rejected alternatives.** Serving raw HEIC was rejected because the supported
Chrome and Firefox clients cannot rely on decoding it. Lossy WebP or JPEG was
rejected because additional compression can remove small annotation targets.
Browser-side conversion was rejected because it increases App complexity and
cannot enforce one decoder, orientation, and color policy. Replacing the source
with WebP was rejected because it breaks source checksums and provenance.
On-demand conversion was rejected because annotation requests would pay the
decode cost and could observe inconsistent failures.

**Contract and implementation effects.** The capability list adds
`image/heic` and `image/heif`; upload validation, format sniffing, storage,
signed media delivery, learning manifests, App selection, help text, and tests
change as described above. No annotation payload or geometry schema changes.
No data migration is required.

**Verification.** Commit representative 8-bit, 10-bit, portrait-oriented,
landscape, alpha, and invalid/truncated HEIC/HEIF fixtures. Tests must prove
format acceptance and spoof rejection, source checksum retention, deduplication,
atomic failure, rendition reuse, `image/webp` delivery, correct content length,
and exact canonical width/height. Decode each generated WebP and compare every
pixel with the deterministic 8-bit oriented source decode. App tests cover typed
and MIME-less files, both file inputs, capability filtering, and annotation in
the two latest Chrome and Firefox releases. An end-to-end geometry fixture must
draw and reload a small box and polygon at image edges and confirm unchanged
coordinates against the retained original.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-10-24

### A7-01 — Acquisition activity UX

**Status:** **APPROVED**

**Purpose.** Let users understand whether the next annotation batch is being
selected randomly or through active learning, and what they can do after a
failure.

**Decision:** Use one activity card. Show `Selecting randomly`,
or `Training`, `Evaluating`, and then `Selecting images`/`Selecting objects`.
Show ETA only when the API provides one. On failure, show the API reason and a
Retry action to authorized users.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09

### A7-02 — Quality presentation

**Status:** **APPROVED**

**Purpose.** Present quality statistics without turning missing or suppressed
data into misleading zeros and without creating annotator rankings.

**Decision still needed.** Define what owners/managers see, how insufficient
samples appear, and the accessible non-chart representation.

**Decision:** Add a manager-only Quality section with a small
table for review rate, agreement, and task metrics. Render suppressed values as
`Not enough data`. Do not add annotator-facing rankings. Charts and CSV export
can be added later if there is a concrete need.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09

### A7-03 — Assisted-segmentation UX

**Status:** **APPROVED**

**Purpose.** Keep model assistance under the annotator's control and prevent a
failed or unwanted suggestion from changing saved work.

**Decision:** Place an `Assist segmentation` action beside the
drawing tools. Preview the result before it changes the draft; let the annotator
accept, discard, or edit it. For an object-target assignment, limit edits to the
highlighted target. Offline and timeout errors leave the existing draft
unchanged.

**Approving owner:** DADA API/App owner

**Approval date:** 2026-11-09


## Resolution checklist

Before changing a status to **APPROVED**, record:

1. the chosen behavior and its main reason;
2. any API, App, worker, or data-model change;
3. the verification that will prove it works; and
4. the approver and approval date.

After all pending records are approved, the implementation plans refer to this record for their current status.
