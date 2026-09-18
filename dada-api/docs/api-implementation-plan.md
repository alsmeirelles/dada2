# DADA App and API Revised Implementation Plan

## Revision scope and current baseline

This plan supersedes the earlier API-only plan. It covers the existing DADA
App and the remaining DADA API implementation, including independent redundant
annotation, disagreement measurement, automated consensus, and manual
adjudication. Detailed frontend work is maintained in the
[DADA App adaptation plan](../../dada-app/docs/annotator-disagreement-adaptation-plan.md).

The baseline for this revision is:

- The App is an implemented React/TypeScript client. Its project wizard,
  annotation workspace, activity dashboard, API client, recovery support, and
  real-time client currently implement a single-submission-per-image contract.
- API Phase 0 was completed on 2026-07-19. It provides the FastAPI foundation,
  PostgreSQL/Alembic, Redis connectivity, errors, tracing, idempotency,
  readiness, CI, and generated OpenAPI.
- API Phase 1 was completed on 2026-08-12. It provides administrator bootstrap,
  users, refresh-session rotation/revocation, capabilities, minimal project
  persistence, and centralized project-role authorization.
- API Phase 2 was completed on 2026-08-26. It provides project CRUD,
  ordered classes, project membership, activation-prerequisite validation,
  versioned annotation-policy defaults, consensus-group validation, policy and
  membership auditing, and the related authorization actions.
- API Phases 3 and 4 were completed in September 2026. They provide resumable
  ingestion, fixed train/validation/test splits, reproducible initial batches,
  assignment generation, user administration, and password management.
- Assignment queues, annotation documents, consensus workers, learning,
  iteration execution, and real-time delivery remain for Phases 5–9. No legacy
  annotation rows need migration, so assignment-scoped annotation should be
  introduced directly.

The generated API OpenAPI document remains the executable interface. App types
should ultimately be generated from it; handwritten types may remain only for
view state that is not part of the wire contract.

## Product behavior

Every selected image set (initial training, validation, test, or an acquisition
iteration) receives an immutable annotation-policy snapshot before annotation
starts. Acquisition uses either active-learning ranking or reproducible random
selection, according to project configuration. The policy supports two modes:

1. `single`: one eligible annotator submits one document for each selected
   image. That submission is promoted to the resolved annotation without a
   statistical consensus run.
2. `consensus`: every selected image is independently annotated by the
   configured group. When all required submissions arrive, the API measures
   disagreement and runs the configured task-specific resolver. A low-quality
   or ambiguous result enters manual review instead of silently becoming
   training truth.

The project stores a versioned default policy. Each selected set stores a copy,
so later membership, default-policy, threshold, or algorithm changes cannot
alter in-flight work or its provenance. Owners/managers may change the policy
only while the set is `preparing`. Re-running a resolver creates a new
resolution version; it never mutates raw submissions.

For the first release, `consensus` means an explicit group of at least two
project members authorized to annotate (`owner`, `manager`, or `annotator`)
and one assignment per group member per image. The required submission count
therefore equals the snapshotted
group size. A later extension may support a larger pool with a smaller quorum,
but it should not be included in the first schema or UI unless there is a
concrete need.

## Terminology and state model

- **Selection**: the reproducible set of media chosen randomly or by active
  learning.
- **Annotation batch**: a selected set plus its policy snapshot and progress.
  It has purpose `initial_training`, `validation`, `test`, or `acquisition` and
  may belong to an iteration.
- **Assignment**: one annotator's obligation to annotate one batch item.
- **Lease**: a temporary exclusive edit lock on one assignment, not on the
  underlying image.
- **Submission**: the annotator's immutable completed document. Draft versions
  remain scoped to its assignment.
- **Resolution**: the immutable canonical annotation derived from one or more
  submissions, including provenance and disagreement diagnostics.
- **Adjudication**: an authorized human decision that creates a resolution when
  automation requests review or its result is rejected.

Batch states are:

```text
preparing -> annotating -> resolving -> resolved -> closed
                 |             |          |
                 +-------------+----------+-> failed
                               \-> review_required -> resolved
```

Iteration states become:

```text
preparing -> annotating -> consolidating -> closing -> training -> ready
                 |              |              |          |
                 +--------------+--------------+----------+-> failed
```

An iteration may close only when every batch item has an accepted resolution,
not merely when every image has one submission. Training, evaluation, and
active-learning acquisition consume only accepted resolution versions. Raw
submissions remain available for audit and quality analytics but never enter a
training export directly.

## Consensus behavior by task

Consensus is a versioned API-worker operation, not a browser calculation. The
overall workflow is the same for every task: normalize immutable submissions,
run a task-compatible resolver chosen from server capabilities, preserve full
provenance, and require manual review when configured quality gates fail.
The blocking cross-task specification is
[Consensus Engine Requirements](consensus-engine-requirements.md); it must be
approved before Phase 6 implementation. Task-specific algorithms, inputs,
metrics, and test fixtures are defined in:

| Task | Detailed strategy |
| --- | --- |
| Classification | [classification consensus](consensus/classification.md) |
| Detection | [detection consensus](consensus/detection.md) |
| Segmentation | [segmentation consensus](consensus/segmentation.md) |

Detection and segmentation always use two stages: (1) class-agnostic object or
instance identification followed by Cleanlab-backed class/existence
disambiguation, then (2) box or mask refinement only for accepted candidates.
STAPLE is therefore only a segmentation refinement option after instance/class
alignment; it is not a universal resolver.

Cleanlab is the first registered adapter family for class resolution. crowd-kit
is the first registered adapter family for segmentation mask refinement. A
user chooses only a typed strategy identifier and parameters exposed by
`GET /api/v1/capabilities` for the project's task and installed package
versions. The API never accepts arbitrary package class names or code from a
client.

Algorithm name alone is insufficient provenance. Every resolution records the
adapter/resolver name and semantic version, package version where applicable,
parameters, input submission IDs and content hashes, output document hash,
per-item metrics, threshold decision, timestamps, and worker/job identity.
Identical inputs plus resolver/package versions and parameters must be
idempotent.

The first release uses explicit, configurable review thresholds and a
conservative fallback: invalid geometry, a classification tie, insufficient
object support, failed instance matching, or agreement below threshold produces
`review_required`. It must never select one annotator arbitrarily. Empty
annotations are valid submissions when the task permits no objects; empty vs.
non-empty disagreement must be measured rather than rejected as malformed.

## Target service shape

Use a modular monolith with durable boundaries that can later be split:

```text
FastAPI application
  identity and project authorization
  projects, members, classes, policy defaults
  ingestion and media metadata             -> self-hosted persistent volume
  selections, batches, assignments, leases -> PostgreSQL
  drafts, submissions, resolutions          -> PostgreSQL
  outbox and worker jobs                     -> PostgreSQL -> Celery/Redis
  learning adapter                           -> selection/training workers
  consensus adapter                          -> task-specific resolver workers
  event delivery                             -> Redis fan-out (optional)
```

PostgreSQL is authoritative. Redis/Celery may transport work and events, but
correctness must survive duplicate, delayed, and lost messages. Selection,
assignments, leases, submissions, resolution state, job state, idempotency, and
outbox events remain durable.

## Persistence model and invariants

The remaining migrations should introduce these records:

| Aggregate | Principal records | Important invariants |
| --- | --- | --- |
| Project setup | projects, project_members, classes, annotation_policy_defaults | one owner; policy versions are optimistic and group members are annotators in the project |
| Ingestion | upload_sessions, upload_items, chunks, content_objects, media | checksums and dimensions verified before media is usable; no client absolute paths |
| Learning | dataset_splits, iterations, iteration_selections, model_runs | immutable validation/test splits; project-selected active-learning or random acquisition; reproducible seed, strategy, input, and model/run IDs where applicable |
| Annotation work | annotation_batches, batch_items, annotation_assignments, leases | unique `(batch_item_id, annotator_id)`; at most one active lease per assignment; policy is immutable after annotation starts |
| Annotation evidence | annotation_documents, annotation_objects, submissions | drafts belong to one assignment; a submitted revision is immutable; at most one accepted submission per assignment |
| Resolution | resolution_runs, resolution_inputs, resolved_annotations, adjudications | accepted canonical version is explicit; raw inputs are never overwritten; one active resolution job per item/config fingerprint |
| Annotator performance | resolution_object_evidence, annotator_performance_observations, annotator_performance_summaries | observations are project-scoped, immutable, and tied to the accepted resolution version; summaries are regenerable caches, never the source of truth |
| Operations | idempotency_records, outbox_events, worker_jobs, audit_entries | repeated keys return the original result for the same actor, route, and body |

Persist all geometry in original-image pixel coordinates and retain original
dimensions. A lease is exclusive only for an assignment. Consequently, two
configured annotators may simultaneously lease different assignments for the
same media, while the same assignment can never have two live leases.

Annotators must not receive peer drafts, submissions, identities, agreement
scores, or consensus results until they submit their own assignment. This
prevents anchoring. Owners/managers may access raw evidence for review and
audit. Member removal must not delete evidence; an in-flight assignment is
explicitly reassigned or waived by an audited manager action. Waiver/reassignment
rules may not reduce a consensus batch below two independent submissions.

### Annotator performance evidence

The API must persist the evidence needed for future project-scoped annotator
confidence weights as soon as an accepted resolution exists. It is not enough
to retain raw submissions and infer these values later: object/instance
matching and final geometry can change when a resolution is retried or
adjudicated.

For every source submission compared with an accepted resolved annotation, the
worker creates immutable `annotator_performance_observations` linked to
`project_id`, `annotator_id`, `assignment_id`, `submission_id`, `batch_item_id`,
`resolution_id`, and `resolution_version`. Each observation records its
evaluation source (`automated_consensus`, `human_adjudication`, or future
`gold_standard`), task, class/object mapping, metric name/value, and whether it
is eligible for future weighting. Observations are never rewritten when a new
resolution version replaces an older one; the old version is superseded in
queries, not erased.

`resolution_object_evidence` records the deterministic mapping between every
raw object/instance and a canonical resolved object (or an explicit unmatched
reason). This permits unambiguous performance measures:

- **Class retention/confusion:** whether the submitted image/object class was
  retained after consensus, plus submitted-to-canonical class confusion counts.
- **Detection geometry:** box IoU for every raw box matched to its kept
  canonical object, plus separate false-positive, missed-object, duplicate,
  and ambiguous-match observations. Do not encode all unmatched cases as IoU
  zero because that loses their cause.
- **Segmentation geometry:** mask IoU and Dice for every raw mask matched to
  its kept canonical instance, plus separate unmatched/empty/invalid-topology
  observations.
- **Classification:** selected-vs-canonical class correctness; in multi-label
  projects, per-class positive/negative agreement rather than a single image
  score.

Maintain `annotator_performance_summaries` as an asynchronously refreshed,
regenerable project-and-task cache with sample size, class confusion matrix,
class retention rate, box/mask IoU and Dice distributions, false-positive and
miss rates, and separate values by evaluation source. It must never replace
individual observations or mix projects.

These metrics are initially reporting evidence, not inputs to the consensus
algorithm. Future confidence weighting must use human-adjudicated/gold evidence
or cross-fitted/leave-one-out estimates; using a rater's own consensus-influenced
result to weight that same rater would create a self-reinforcing bias. Ordinary
annotators never receive named performance data. Owners/managers may access
authorized aggregate/project views, with privacy policy controls.

## Revised HTTP contract

Existing project, upload, iteration, inference, event, and statistics routes
remain, with the following additions or semantic changes.

### Policy and batch administration

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET/PUT` | `/api/v1/projects/{project_id}/annotation-policy` | Read or version-update the default policy |
| `GET/PATCH` | `/api/v1/projects/{project_id}/batches/{batch_id}` | Read progress or update policy while `preparing` |
| `POST` | `/api/v1/projects/{project_id}/batches/{batch_id}/start` | Snapshot policy, validate members, and create assignments atomically |
| `GET` | `/api/v1/projects/{project_id}/batches/{batch_id}/resolutions` | List resolution/review status for managers |
| `GET` | `/api/v1/projects/{project_id}/batch-items/{item_id}/evidence` | Manager view of raw submissions, metrics, and resolution history |
| `POST` | `/api/v1/projects/{project_id}/batch-items/{item_id}/resolve` | Retry a resolver with a versioned configuration |
| `POST` | `/api/v1/projects/{project_id}/batch-items/{item_id}/adjudicate` | Submit an audited canonical document or accept a proposed result |
| `GET` | `/api/v1/projects/{project_id}/annotator-performance` | Authorized project-scoped aggregate performance summaries and sample sizes |

A policy representation includes `mode`, ordered `annotator_ids`,
`resolver`, `resolver_version`, task-specific `parameters`, review thresholds,
and `version`. In `single` mode, `annotator_ids` may be empty to mean any
eligible project annotator. In `consensus` mode the explicit snapshotted group
is required.

### Queue, leases, and annotation documents

The scoped iteration queue remains the normal annotator entry point, but it
returns the current user's assignments rather than globally locked images.
Queue items include `assignment_id`, `media_id`, the caller's assignment
status, and aggregate batch progress that does not disclose peer identities or
content. The lease-acquisition request may specify `assignment_id`; a “next”
request atomically selects one eligible assignment for the caller.

Lease, draft, completion, and assisted-segmentation routes may retain their
URLs, but completion returns the accepted submission and current item
resolution status. It does not imply that the media is resolved. Recovery
snapshots and optimistic versions are keyed by `assignment_id` plus the draft
version, not by media alone.

`GET /api/v1/media/{media_id}/annotations` must be replaced or narrowed because
“current annotation” is ambiguous. Use explicit views:

- the caller's assignment draft/submission while annotating;
- an accepted resolved annotation for normal consumers and exports; or
- manager-only evidence through the batch-item endpoint.

### Counts, errors, events, and authorization

Iteration/batch responses distinguish at least:

- total images and resolved images;
- total assignments and submitted assignments;
- available and leased assignments;
- items awaiting resolution and items requiring review.

Add stable conflict/error codes including `policy_locked`,
`invalid_consensus_group`, `assignment_not_owned`, `assignment_already_submitted`,
`resolution_not_ready`, `resolution_config_conflict`, and
`adjudication_required`.

Add authorization actions `manage_annotation_policy`, `read_annotation_evidence`,
`run_resolution`, `adjudicate`, and `read_annotator_performance`. Owners and
managers receive these actions; annotators do not. Continue to centralize the complete matrix in
`services/authorization.py`.

Add events `assignment.leased`, `assignment.released`,
`annotation.submitted`, `resolution.started`, `resolution.completed`,
`resolution.review_required`, and `resolution.adjudicated`. Events are hints;
REST remains authoritative. Annotator-facing event data must not leak blind
peer evidence.

## Concrete code changes

### DADA API

- Extend `models/project.py` and `schemas/project.py` with the default policy
  summary only after Phase 2 project CRUD is implemented; keep normalized
  policy/group tables in dedicated annotation models rather than JSON-only
  project columns.
- Add models and repositories under `dada_api/models/` and
  `dada_api/repositories/` for classes, members, ingestion, splits, iterations,
  batches, assignments, leases, documents, submissions, resolutions, raw-to-
  canonical object evidence, and annotator performance observations/summaries.
- Add Pydantic schemas under `dada_api/schemas/` for policy discriminated
  unions, assignment queues, evidence, diagnostics, and adjudication. Validate
  resolver/task compatibility at the service boundary.
- Replace the Phase 1 project placeholders in
  `api/v1/endpoints/projects.py`; add endpoints/modules for uploads, iterations,
  batches, assignments/leases, annotations, resolutions, statistics, and
  events. Retire the global prototype queue once the scoped assignment queue is
  live.
- Extend `services/authorization.py` with the new manager actions and add
  services for policy snapshotting, assignment generation, batch progress,
  resolution scheduling, and adjudication.
- Introduce independent `LearningAdapter` and `ConsensusResolver` ports. The
  consensus worker may use NumPy/SciPy/image libraries, Cleanlab, and crowd-kit,
  but FastAPI and ORM objects must not cross the port. Implement the registered
  adapters and two-stage detection/segmentation behavior specified in the
  [classification](consensus/classification.md),
  [detection](consensus/detection.md), and
  [segmentation](consensus/segmentation.md) strategy documents.
- Add Cleanlab and crowd-kit in an isolated, version-pinned consensus worker
  dependency group when Phase 6 begins. The API process does not import either
  package at startup; a missing or incompatible optional dependency causes a
  capability to be unavailable, never a silent strategy substitution.
- Use a transactional outbox to schedule resolution exactly after the last
  required submission commits. Worker result ingestion must tolerate retries,
  duplicate results, stale configuration, timeouts, and process restarts.
- Export only accepted resolved documents to training/evaluation. Record the
  exact resolution IDs in model-run dataset manifests.
- Derive and persist project-scoped annotator performance observations when a
  resolution is accepted or adjudicated, then rebuild affected summary rows
  idempotently. Keep resolver diagnostics separate from these per-annotator
  observations so later confidence-weight calculations can select only
  eligible evidence.
- Add Alembic migrations, deterministic OpenAPI regeneration, and database
  constraints for all stated uniqueness and immutability rules.

### DADA App

The complete file-level design, UX behavior, error handling, and browser test
plan is in the
[DADA App adaptation plan](../../dada-app/docs/annotator-disagreement-adaptation-plan.md).
The required changes are summarized here to make API dependencies explicit:

- Extend `features/projects/types.ts`, `NewProjectPage.tsx`, and
  `project-api.ts` with an annotation-strategy step. The owner selects `single`
  or `consensus`; consensus requires at least two validated project annotators,
  shows the task-appropriate resolver and thresholds, and summarizes the
  assignment cost (`images × annotators`) before creation/activation. Phase 5
  also adds the persisted active-learning/random acquisition choice and an
  accurate review summary for both paths.
- Because members are currently created after the project, keep the creation
  workflow transactional at the UX level: create the draft, add/resolve member
  usernames, save the policy using returned user IDs, upload, then activate.
  A failure leaves a resumable draft and reports which setup step remains.
- Revise `features/annotation/types.ts` and `annotation-api.ts` around
  assignments and separate submission/resolution status. Prefer generated
  OpenAPI types and small view-model adapters over duplicating wire shapes.
- Update `AnnotationWorkspacePage.tsx` so queue navigation, lease acquisition,
  draft recovery, completion, and shortcuts use `assignment_id`. Do not hide an
  image merely because another group member is editing their own assignment,
  and do not show peer names or annotations in the ordinary workspace.
- Update `ProjectActivityPage.tsx` to show image resolution progress separately
  from assignment submission progress, include `consolidating` and
  `review_required`, and link managers to unresolved items.
- Add a manager-only consensus review feature and route. Reuse the image/canvas
  rendering primitives to overlay color-coded submissions and the proposed
  resolution, display task-specific agreement metrics, and allow accepting,
  editing, or replacing the canonical document. Make provenance visible and
  every adjudication action explicit.
- Update real-time invalidation handling for assignment/resolution events and
  keep polling fallback. Update session recovery keys so two assignments for
  the same media cannot overwrite one another in browser storage.
- Add accessible explanations for consensus, disagreement, and review states;
  keyboard and 200% zoom behavior remain release requirements.

## Revised delivery phases

Phases remain a strict dependency order for the API. App work is listed at the
first phase where its backing contract becomes stable. Each phase ends in a
deployable, tested increment.

### Phase 0: service foundation — completed

- Implement project list/create/read/versioned update and explicit activation.
- Implement ordered class CRUD with color validation and optimistic versions.
- Implement member listing, ~~invitation~~, role change, and removal, including
  protections for the sole owner.
- Keep projects in `draft` until ingestion begins; reject activation until
  classes, media, and requested split sizes are valid.

### Phase 1: identity, capabilities, and authorization — completed

Initial build definitions:
- Preserve the existing login and current-user behavior.
- Implement an idempotent administrator bootstrap command. It reads the initial
  username, display name, and password from environment variables or interactive
  input, hashes the password with Argon2, creates the user only if no bootstrap
  administrator exists, and never logs or stores the plaintext secret.
- Give this user the global `administrator` flag and owner-equivalent authority
  over every project and system resource. Project creation still records its
  creator as the explicit project owner, and projects created by the bootstrap
  user record that user as owner. This preserves truthful `owner_id` values
  while giving the default administrator control of everything.
- Refuse ambiguous bootstrap changes: reruns are no-ops for the same identity,
  while changing the bootstrap identity requires an explicit administrative
  command. Normal API startup does not recreate or reset credentials.
- Add refresh-token rotation, logout/revocation, and a documented Secure,
  HttpOnly, SameSite cookie deployment policy.
- Implement `/api/v1/capabilities` from server configuration and object-store
  limits.
- Centralize project-role authorization and cover every role/action pair with
  parameterized tests.

Exit gate: an empty installation can be migrated and bootstrapped without an
HTTP endpoint; bootstrap reruns are safe; login, refresh rotation/replay
rejection, logout, expiry, CORS, administrator access, and project role denial
scenarios pass through real HTTP requests.

Updates:

- Preserve the verified 2026-08-12 behavior. The only follow-up is extending the
central role/action matrix in later phases; do not rewrite the completed
bootstrap or session work. Two already documented Phase 1 follow-ups are
scheduled as Phase 2 hygiene: align the App's current-user type with
`is_administrator`, and implement the approved prompt for optionally removing
the former administrator flag during `replace-bootstrap-admin`.

### Phase 2: project setup, members, and policy defaults — API completed 2026-08-26; App completed 2026-08-30

API work — completed as documented in [Phase 2](phases/phase_2.md):

- Implement project list/create/update, classes, member management, and
  activation prerequisites in place of the Phase 1 placeholders.
- Add versioned project policy defaults and consensus-group validation.
- Add the five new manager authorization actions and audit policy/member
  changes.
- Add the explicit `replace-bootstrap-admin` demotion prompt recorded in the
  Phase 1 completion notes without changing normal bootstrap idempotency.

App work — completed against the stable Phase 2 API contract:

- Add policy selection and cost review to the existing creation wizard.
- Resolve collaborator usernames to persisted member/user IDs before saving a
  consensus group; support resuming a partially created draft.
- Replace the stale current-user `role` field in `src/api/types.ts` with the
  Phase 1 `is_administrator` contract.
- Follow the App plan's
  [Phase 2 project-policy work](../../dada-app/docs/annotator-disagreement-adaptation-plan.md#phase-2-project-policy-setup).

Exit gate: the App can create a project in either mode; invalid groups,
duplicate members, members without annotation authority, stale policy
versions, and attempts
to activate incomplete setup return stable errors.

### Phase 3: resumable ingestion and media — completed 2026-09-06

- Implement manifest validation, resumable chunks, checksum verification,
  image inspection/dimensions, deduplication, cancellation, and promotion into
  the configured self-hosted persistent volume.
- Store media and temporary upload parts on configured host paths bind-mounted
  into the API/worker containers on the shared server. Do not introduce a cloud
  storage dependency in this phase. Keep the storage boundary adapter-based so
  a future migration to AWS or another cloud object store changes the adapter
  and migration tooling, not the ingestion contract.
- Immediately abort and purge all unpromoted upload parts when an upload is
  cancelled. Immediately and permanently purge a deleted project's media,
  derived artifacts, and database records, including audit records, after
  authorization and reference-safe cleanup complete.
- The App preserves recursive discovery/upload behavior, persists the server
  upload session and operation keys, resumes from acknowledged per-file
  offsets, and presents draft setup, member management, cancellation, and
  terminal deletion flows against this contract.

Exit gate: uploads survive API restart and all documented corrupt, duplicate,
offset, checksum, path, size, retry, and cancellation cases pass against the
configured shared-server volume store. Cancellation and project deletion leave
no readable media or temporary upload parts behind.

### Phase 4: activation, reproducible selections, annotation batches, and user administration — completed 2026-09-15

User administration is a separate global-administration workstream delivered
alongside batch activation. A project owner or manager never receives these
authorities.

#### User-administration API contract

All routes require a bearer access token. The `/users` routes require the
actor to have `is_administrator=true`; the self-service route requires only an
authenticated active user.

| Method | Endpoint | Request | Result |
| --- | --- | --- | --- |
| `GET` | `/api/v1/users` | Cursor and optional `active` filter | `UserPage` |
| `POST` | `/api/v1/users` | `UserCreate` | `201 UserRead` |
| `GET` | `/api/v1/users/{user_id}` | — | `UserRead` |
| `PATCH` | `/api/v1/users/{user_id}` | `UserUpdate` | `UserRead` |
| `POST` | `/api/v1/users/{user_id}/reset-password` | `AdministratorPasswordReset` | `204` |
| `DELETE` | `/api/v1/users/{user_id}` | `version` supplied by `If-Match` | `204` |
| `POST` | `/api/v1/auth/me/password` | `PasswordChange` | `204` |

`UserRead` contains `id`, `username`, `display_name`, `is_active`,
`is_administrator`, `version`, and `created_at`. Usernames are immutable after
creation. `UserCreate` requires `username`, `display_name`, and `password`,
and accepts `is_active` and `is_administrator` with safe defaults. `UserUpdate`
requires the expected `version` and may update only `display_name`,
`is_active`, and `is_administrator`. `AdministratorPasswordReset` contains
only `new_password`; `PasswordChange` contains `current_password` and
`new_password`. Passwords are 8–128 characters and are never returned, logged,
placed in audit metadata, or included in error responses.

Deletion is terminal, returns no restore affordance, and must fail with
`user_in_use` while the target owns a project or has retained domain/audit
references. Disabling (`is_active=false`) is the reversible way to remove a
user's access while those references remain. The API rejects deletion,
deactivation, or administrator-flag removal when it would leave no active
administrator (`last_active_administrator`), and rejects an administrator from
removing their own administration/access (`self_administration_change`).

Every password reset, self-service password change, deactivation, and deletion
revokes the target's refresh sessions. Existing bearer requests are rejected
when the user is inactive; access tokens remain bounded by their normal short
expiry. Audit entries record actor, target, action, and non-secret outcome.
Stable errors include `username_taken`, `user_in_use`,
`last_active_administrator`, `self_administration_change`, `version_conflict`,
and `current_password_incorrect`.

- Freeze train/validation/test membership, create full-coverage batches for all
  three splits, and record strategy, seed, and selection inputs.
- Create an annotation batch for each selected set, snapshot its policy, and
  generate assignments atomically when it starts.
- Add batch/iteration state services and prevent policy edits after start.

App work:

- Display the snapshotted policy, image count, assignment count, and group on
  manager activity views before annotation begins.
- Follow the App plan's
  [Phase 4 batch-visibility work](../../dada-app/docs/annotator-disagreement-adaptation-plan.md#phase-4-batch-visibility).
- Add the App plan's administrator user-management and self-service password
  flows against the contract above.

Exit gate: the same input and seed reproduce selection; test media never enters
acquisition; every consensus batch item has exactly one assignment per
snapshotted annotator; failed starts roll back completely. Administrators can
create, update, reset, disable, and safely remove eligible users; all users can
change their own password; no non-administrator can access global user actions.

### Mandatory decision gate for Phases 5–9

Phases 5–9 **must not start implementation** while any API decision in the
[API register](#pending-decision-register-for-phases-5-9) or App decision in
the [App register](../../dada-app/docs/annotator-disagreement-adaptation-plan.md#pending-decision-register-for-phases-5-9)
assigned to that phase is unresolved. Before code, migrations, schemas, or UI
work begins:

1. create or update `docs/phases/phase_N.md`;
2. add a **Decisions** section that resolves every decision ID assigned to the
   phase, including rationale, rejected alternatives, contract and migration
   effects, and the approving owner/date;
3. update the decision's status in this plan and link to the decision record;
4. regenerate or approve affected API schemas/examples before dependent App
   work begins; and
5. for Phase 6, also complete and approve
   [Consensus Engine Requirements](consensus-engine-requirements.md).
6. for Phase 5, also implement and verify every required correction in the
   [Phase 4.1 annotation-sequence revision plan](phase-4-annotation-sequence-revision-plan.md),
   then reset and rebuild development projects as that plan requires.

Discovery and experiments may inform a decision, but no production
implementation may be merged under the phase until this gate is satisfied.

### Phase 5: assignment queues, leases, drafts, and submissions

**Start gate:** first complete the [Phase 4.1 annotation-sequence revision
plan](phase-4-annotation-sequence-revision-plan.md), including its required
verification and development-project reset/rebuild. Then resolve API decisions
`P5-01`–`P5-06` and App decisions `A5-01`–`A5-04` in
`docs/phases/phase_5.md`, then change their status in both plans. Phase 5
implementation must not start before both prerequisites are satisfied.

- Extend project creation with an explicit acquisition strategy: use active
  learning or do not use active learning. Persist the choice as a versioned,
  API-visible project setting and return it in project reads.
- When active learning is not selected, acquisition batches are reproducible
  random selections from the current eligible unlabeled pool. They still
  record strategy, server-generated seed, ordered input fingerprint, requested
  size, and selected media IDs. Validation and test media are never eligible.
- When active learning is selected, acquisition is delegated to the versioned
  learning boundary delivered in Phase 7. Phase 5 defines the contract and
  state transition without inventing model scores or a temporary algorithm.

- Implement caller-scoped queues and atomic assignment leasing, renewal,
  release, expiry, and manager revocation/reassignment.
- Implement optimistic draft versions and immutable, idempotent final
  submissions with task/geometry validation.
- In single mode, create the canonical resolution transactionally from the
  submitted document. In consensus mode, transition the item to resolution
  readiness only after every required assignment is submitted.

App work:

- Add the active-learning choice to project creation and review. Explain that
  disabling it makes each acquisition batch a random sample of the remaining
  unlabeled pool; do not describe that path as model-guided.
- Convert the existing workspace, recovery, queue, and annotation API code from
  media-exclusive leases to assignment-exclusive leases while keeping peer
  work blind.
- Follow the App plan's
  [Phase 5 assignment-workspace work](../../dada-app/docs/annotator-disagreement-adaptation-plan.md#phase-5-assignment-workspace).

Exit gate: project creation persists the acquisition strategy and the
non-active-learning path produces a reproducible random acquisition that
excludes validation/test and already selected media. Concurrent database tests
prove that two group members can lease different assignments for the same
media, but no assignment can be leased twice; stale drafts, expired leases,
duplicate completions, and cross-user access fail correctly.

### Phase 6: consensus engine, diagnostics, and adjudication

**Start gate:** resolve API decisions `P6-01`–`P6-07` and App decisions
`A6-01`–`A6-04` in `docs/phases/phase_6.md`, complete every blocking item in
[Consensus Engine Requirements](consensus-engine-requirements.md), and mark
that document **Approved** before implementing the consensus engine.

- Define the versioned resolver command/result protocol and durable resolution
  jobs. First provide a deterministic fake covering success, ambiguity,
  invalid output, retries, duplicates, timeout, and permanent failure.
- Implement the user-selectable Cleanlab class resolvers, detection
  identification/class-disambiguation then box refinement, and segmentation
  instance/class disambiguation then crowd-kit/STAPLE mask refinement described
  in the [classification](consensus/classification.md),
  [detection](consensus/detection.md), and
  [segmentation](consensus/segmentation.md) strategy documents.
- Persist disagreement diagnostics, proposed/accepted resolution versions, and
  immutable provenance. Persist raw-to-canonical mappings and the task-specific
  annotator performance observations defined above. Enforce review thresholds
  and build manager evidence, retry, and adjudication endpoints.

App work:

- Add resolution progress to activity and implement the manager consensus
  review/adjudication screen.
- Follow the App plan's
  [Phase 6 resolution and adjudication work](../../dada-app/docs/annotator-disagreement-adaptation-plan.md#phase-6-resolution-and-adjudication).

Exit gate: golden fixtures for all three task types produce deterministic
results; low agreement reaches review; no raw submission is mutated; an
adjudication can close an item; duplicate worker results cannot create two
accepted resolutions; accepted and adjudicated fixtures create correct,
project-scoped class-retention and box/mask-agreement observations without
duplicating them on worker retry.

### Phase 7: learning boundary, exports, metrics, and assisted segmentation

**Start gate:** resolve API decisions `P7-01`–`P7-05` and App decisions
`A7-01`–`A7-03` in `docs/phases/phase_7.md`, then change their status in both
plans.

- Implement the versioned learning port, worker jobs, transactional outbox,
  deterministic training/acquisition adapter, progress, ETA, retries, and
  failure recovery.
- Generate dataset manifests only from accepted resolution IDs and include
  resolution provenance in model-run lineage.
- Implement authorized assisted-segmentation dispatch/results. Its output is an
  annotator aid inside an assignment, not an independent consensus vote.
- Add quality statistics such as review rate and inter-annotator agreement
  without using them to rank named workers in annotator-facing views. Add
  authorized project-level performance summaries sourced from the immutable
  observations, including class retention/confusion and box/mask IoU/Dice
  distributions; do not feed them back into consensus in this phase.
- Implement the corresponding App plan
  [Phase 7 learning and quality presentation](../../dada-app/docs/annotator-disagreement-adaptation-plan.md#phase-7-learning-and-quality-metrics).

Exit gate: unresolved/raw annotations cannot enter an export; fake-worker
success, retry, duplicate, delayed, timeout, and failure paths advance durable
state correctly.

### Phase 8: real-time delivery and production hardening

**Start gate:** resolve API decisions `P8-01`–`P8-04` and App decisions
`A8-01`–`A8-03` in `docs/phases/phase_8.md`, then change their status in both
plans.

- Add short-lived single-use WebSocket tickets, committed outbox events, and
  monotonic per-project sequences for assignments, resolutions, iterations,
  and training.
- Add rate limits, signed-URL expiry, metrics, tracing, backups, retention,
  resolver dependency/resource limits, and operational runbooks.
- Complete App event invalidation, polling fallback, reconnect, and sequence-gap
  reconciliation for the revised states.
- Complete the App plan's
  [Phase 8 real-time hardening](../../dada-app/docs/annotator-disagreement-adaptation-plan.md#phase-8-real-time-and-production-hardening).

Exit gate: tickets cannot be replayed or crossed between projects; blinded
evidence cannot leak through events; load tests cover upload, assignment
contention, consensus bursts, and event fan-out.

### Phase 9: coordinated release acceptance and documentation

**Start gate:** resolve API decisions `P9-01`–`P9-03` and App decisions
`A9-01`–`A9-02` in `docs/phases/phase_9.md`, then change their status in both
plans.

- Update App requirements, architecture, API contract, testing guide, API
  development guide, README files, and generated OpenAPI to use assignment and
  resolution terminology consistently.
- Add ADRs for policy snapshots, assignment-scoped leases, blind annotation,
  task-specific consensus, manual adjudication, PostgreSQL authority, outbox,
  and learning/consensus adapter boundaries.
- Publish a compatibility record tying the App release to an OpenAPI version,
  resolver versions, and migration head.
- Complete the App plan's
  [Phase 9 coordinated acceptance](../../dada-app/docs/annotator-disagreement-adaptation-plan.md#phase-9-coordinated-release-acceptance).

Exit gate: from clean infrastructure, a new developer can bootstrap, create
single and consensus projects, upload a dataset, have two independent browser
sessions annotate the same images, observe automatic resolution and a forced
manual-review case, then train through the deterministic worker using only the
documented commands.

## Test strategy

In addition to the existing authentication, ingestion, geometry, event, and
browser tests, the minimum regression matrix includes:

1. Policy version conflicts, task/resolver compatibility, group membership,
   policy locking, member removal, reassignment, and audit history.
2. Deterministic assignment generation and concurrent lease behavior at the
   assignment level, including simultaneous work on the same image.
3. Blindness: annotators cannot read peer drafts, submissions, identity,
   metrics, resolution state details, or manager evidence before submission.
4. Empty annotations, class disagreement, ties, missing/unmatched objects,
   invalid geometry, low overlap, resolver failure, and threshold boundaries.
5. Resolver idempotency, stale/duplicate worker results, provenance hashes,
   manual edits, re-resolution, and exactly one accepted resolution version.
6. Iteration closure based on resolved images rather than submission counts and
   strict exclusion of unresolved/raw evidence from exports.
7. Browser journeys for single mode, two-person consensus, simultaneous same
   image work, lease loss, offline recovery per assignment, automatic
   resolution, manual adjudication, polling fallback, and sequence gaps.
8. Project creation and iteration journeys for active-learning acquisition and
   reproducible random acquisition, including exclusion of validation/test and
   previously selected media.

Repository/service integration tests must use PostgreSQL rather than an
in-memory substitute. Consensus algorithm tests use small committed golden
fixtures; large/GPU benchmarks remain a separate environment. OpenAPI response
schemas, examples, error envelopes, idempotency, cursors, and required headers
are contract-tested, not just status codes.

## Decisions made and required before dependent phases

### Pending decision register for Phases 5–9

Every entry below is **PENDING**. “Document before start” means the decision
must be resolved in the matching `docs/phases/phase_N.md` under the mandatory
gate above. A phase cannot be declared started while one of its entries remains
pending. App-specific decisions are listed separately in the
[App decision register](../../dada-app/docs/annotator-disagreement-adaptation-plan.md#pending-decision-register-for-phases-5-9)
and share the same gate and decision record.

| ID | Pending decision | Required documented outcome |
| --- | --- | --- |
| `P5-01` | Acquisition-strategy project contract | Field name and enum, default for new projects, mutability before/after activation, version/audit behavior, development-reset treatment, and OpenAPI examples |
| `P5-02` | Random acquisition semantics | Sampling algorithm/order, seed lifecycle, fingerprint, and provenance. The eligible pool, completed/cancelled/incomplete-item handling, final undersized-batch rule, and `iteration_batch_size` requested-size rule are fixed by the [Phase 4.1 revision plan](phase-4-annotation-sequence-revision-plan.md). |
| `P5-03` | Lease lifecycle | Duration, renewal window, grace/expiry behavior, fairness and queue ordering, disconnect handling, manager revocation, and concurrent-claim semantics |
| `P5-04` | Assignment reassignment and submission lifecycle | Reassignment/waiver authority and audit, consensus minimum after changes, whether submitted work may reopen, revision policy, and duplicate-completion response |
| `P5-05` | Annotation document contract | Versioned classification/detection/segmentation schemas, explicit single-label vs. multi-label project configuration, coordinate precision, empty-annotation semantics, geometry limits, validation errors, and payload/complexity limits |
| `P5-06` | Blindness release boundary | Exactly what aggregate state an annotator may read before submission, after own submission, after item resolution, and after batch closure; event redaction rules |
| `P6-01` | Resolver/package catalog | Supported Cleanlab and crowd-kit versions, adapter versions, pipeline IDs, dependency isolation, compatibility policy, and capability fallback behavior |
| `P6-02` | Resolver configuration and quality gates | Typed parameters, defaults/bounds, task-specific thresholds, calibration dataset and approval evidence, tie/ambiguity rules, and migration from provisional policy IDs |
| `P6-03` | Segmentation refinement implementation | Maintained STAPLE dependency or approved internal implementation, supported crowd-kit strategies, rasterization/polygonization libraries, and reference fixtures |
| `P6-04` | Adjudicator independence | Whether a contributor may adjudicate the same item, conflict disclosure, role restrictions, optional independent-adjudicator mode, and audit fields |
| `P6-05` | Resolution job execution | Worker/queue topology, command/result envelopes, timeouts, retry/backoff limits, cancellation, stale/duplicate result handling, CPU/memory limits, and permanent-failure recovery |
| `P6-06` | Resolution acceptance/versioning | Automatic acceptance criteria, proposal vs. accepted states, retry configuration/version conflicts, supersession, one-active-result invariant, and adjudication precedence |
| `P6-07` | Evidence and performance policy | Raw evidence retention/access, raw-to-canonical mapping rules, observation eligibility, privacy/minimum-sample rules, and behavior when a resolution is superseded |
| `P7-01` | Learning and export protocol | Versioned command/result envelopes, manifest format, artifact storage, accepted-resolution lineage, transport-independent errors, and compatibility policy |
| `P7-02` | Active-learning implementation | Initial model/training adapter, acquisition score and tie-breaking, cold-start behavior, reproducibility inputs, model/run retention, and behavior when the adapter is unavailable |
| `P7-03` | Iteration and evaluation policy | Available user-selectable validation metrics and thresholds, comparison direction, training/evaluation cadence, interaction between the user-defined maximum acquisition-iteration count and metric threshold, retry/resume semantics, ETA/progress contract, and failure rollback. The initial training batch is excluded from the acquisition-iteration count and test evaluation is final-only, as fixed by the [Phase 4.1 revision plan](phase-4-annotation-sequence-revision-plan.md). |
| `P7-04` | Assisted-segmentation provider | Model/provider, request/result schema, artifact/version provenance, limits/timeouts, failure UX contract, and confirmation that suggestions never count as votes |
| `P7-05` | Quality-statistics publication | Metrics/formulas, authorized roles, minimum sample sizes, suppression/privacy rules, refresh cadence, and whether exports include aggregates |
| `P8-01` | Event delivery contract | WebSocket topology, ticket TTL/single-use rules, sequence scope and retention, event schemas/redaction, reconnect/gap algorithm, and polling fallback cadence |
| `P8-02` | Public and worker resource limits | Per-route/user/project rate limits, upload and signed-URL expiry, consensus/training concurrency, queue backpressure, and overload errors |
| `P8-03` | Reliability and data operations | Service objectives, metrics/alerts, trace sampling, backup schedule, restore drill, RPO/RTO, retention/purge schedule, and runbook owners |
| `P8-04` | Production deployment topology | API/worker/Redis/PostgreSQL placement, worker sizing/isolation, secret management, rolling restart behavior, and failure-domain assumptions |
| `P9-01` | Release compatibility freeze | Supported App/API/OpenAPI, migration head, resolver/package versions, browser matrix, and upgrade/downgrade compatibility window |
| `P9-02` | Release and migration procedure | Deployment order, database migration/rollback rules, worker drain, feature flags if any, rollback limits, and backup checkpoint |
| `P9-03` | Acceptance ownership | Canonical acceptance dataset, performance/accessibility/security thresholds, responsible approvers, evidence location, and release sign-off procedure |

### Phase 3 storage and retention — settled

Phase 3 uses a self-hosted, filesystem-backed content store on configured host
paths bind-mounted into Docker containers on the shared server. This project
has no cloud-storage budget. The storage adapter remains an explicit boundary
so a later AWS or other cloud migration is possible without changing the App
or HTTP ingestion contract.

Cancellation and project deletion use immediate purge: cancel aborts the
upload and removes all temporary parts; deleting a project permanently removes
its media, derived artifacts, domain records, and audit records after safe
reference cleanup. There is no restore window in the initial release. A future
phase may add the alternative policy of immediate temporary-part cleanup plus
soft deletion of projects for a fixed grace period, with a restore flow and a
scheduled permanent purge.

The Phase 1 deployment decision remains unchanged: a reverse proxy presents
App and API as one origin so refresh cookies remain first-party and
SameSite-compatible. The Phase 2 identity decision also remains unchanged:
administrators create user accounts directly; email invitation is deferred.

### Phase 2 resolver-policy decisions

The Phase 2 resolver identifiers form a **provisional catalog**, not a
permanent algorithm vocabulary. Clients must discover and persist the
task-compatible ID returned by `GET /api/v1/capabilities` without branching on
or hard-coding it. When Phase 6 implements and validates the resolver workers,
it will migrate existing policy values to this target pipeline vocabulary:

| Task | Phase 2 provisional ID | Target pipeline ID |
| --- | --- | --- |
| Classification | `majority_vote` | `cleanlab_multiannotator` |
| Detection | `two_stage_box_fusion` | `two_stage_detection_consensus` |
| Segmentation | `two_stage_mask_fusion` | `two_stage_segmentation_consensus` |

The target ID identifies the complete versioned pipeline, not an individual
refinement package. Box refinement and segmentation mask refinement remain
typed sub-strategy choices within their respective pipelines; `staple` is never
a top-level resolver ID. Phase 9 freezes the supported release vocabulary and
records its compatibility with the App, OpenAPI, resolver versions, and
migration head.

The Phase 2 parameter contract is deliberately minimal and closed: the App
must send `parameters: {}` and may expose only
`review_thresholds.agreement`. It must not render a generic JSON editor or
algorithm-specific advanced controls. The API persists the fields for forward
compatibility, but their per-resolver meaning, defaults, bounds, and typed
capability descriptors are Phase 6 work. Until then the UI obtains the
resolver ID only from capabilities and treats the agreement threshold as a
generic review-policy value, not as an algorithm tuning control.

## Explicitly deferred work

- Adaptive annotator reliability weighting (for example Dawid-Skene) remains
  deferred as a consensus input. The project-scoped evidence and summaries
  required to evaluate it are delivered in Phases 6–7, but activation requires
  adequate adjudicated/gold or cross-fitted evidence, bias monitoring, and a
  separate policy/versioning decision.
- Partial quorums drawn from a larger annotator pool.
- Cross-image or temporal consensus for video.
- Automated annotator scoring, ranking, or punitive performance workflows.
- Additional production active-learning/model-training adapters beyond the
  initial Phase 7 decision. Every adapter must plug into the learning port
  without taking ownership of HTTP or persistence.

These deferrals do not defer the durable policy, assignments, independent raw
submissions, task-specific resolver boundary, disagreement metrics, manual
review, canonical resolutions, or provenance required by the feature.
