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
- API project creation/listing and all ingestion, iteration, annotation,
  worker, and real-time behavior remain unimplemented placeholders. No queue or
  annotation migration has to be preserved, so the new assignment and
  resolution model should be introduced directly rather than retrofitted onto
  a single-annotation schema.

The generated API OpenAPI document remains the executable interface. App types
should ultimately be generated from it; handwritten types may remain only for
view state that is not part of the wire contract.

## Product behavior

Every selected image set (initial training, random test, or active-learning
iteration) receives an immutable annotation-policy snapshot before annotation
starts. The policy supports two modes:

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
  It has purpose `initial_training`, `test`, or `acquisition` and may belong to
  an iteration.
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
Task-specific algorithms, inputs, metrics, and test fixtures are defined in:

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
  ingestion and media metadata             -> object storage
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
| Learning | dataset_splits, iterations, iteration_selections, model_runs | immutable test split; reproducible selection seed, strategy, input, and model/run IDs |
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
  assignment cost (`images × annotators`) before creation/activation.
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

### Phase 2: project setup, members, and policy defaults

API work:

- Implement project list/create/update, classes, member management, and
  activation prerequisites in place of the Phase 1 placeholders.
- Add versioned project policy defaults and consensus-group validation.
- Add the five new manager authorization actions and audit policy/member
  changes.
- Add the explicit `replace-bootstrap-admin` demotion prompt recorded in the
  Phase 1 completion notes without changing normal bootstrap idempotency.

App work:

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

### Phase 3: resumable ingestion and media

- Implement manifest validation, resumable chunks, checksum verification,
  image inspection/dimensions, deduplication, cancellation, and object-store
  promotion.
- Preserve the App's existing recursive discovery/upload behavior and add only
  contract adaptations generated by OpenAPI.
- Apply the App plan's
  [Phase 3 ingestion alignment](../../dada-app/docs/annotator-disagreement-adaptation-plan.md#phase-3-ingestion-contract-alignment).

Exit gate: uploads survive API restart and all documented corrupt, duplicate,
offset, checksum, path, size, retry, and cancellation cases pass against the
chosen S3-compatible store.

### Phase 4: activation, reproducible selections, and annotation batches

- Freeze train/test membership, create initial/test/acquisition selections, and
  record strategy, seed, model/run identity, and selection inputs.
- Create an annotation batch for each selected set, snapshot its policy, and
  generate assignments atomically when it starts.
- Add batch/iteration state services and prevent policy edits after start.

App work:

- Display the snapshotted policy, image count, assignment count, and group on
  manager activity views before annotation begins.
- Follow the App plan's
  [Phase 4 batch-visibility work](../../dada-app/docs/annotator-disagreement-adaptation-plan.md#phase-4-batch-visibility).

Exit gate: the same input and seed reproduce selection; test media never enters
acquisition; every consensus batch item has exactly one assignment per
snapshotted annotator; failed starts roll back completely.

### Phase 5: assignment queues, leases, drafts, and submissions

- Implement caller-scoped queues and atomic assignment leasing, renewal,
  release, expiry, and manager revocation/reassignment.
- Implement optimistic draft versions and immutable, idempotent final
  submissions with task/geometry validation.
- In single mode, create the canonical resolution transactionally from the
  submitted document. In consensus mode, transition the item to resolution
  readiness only after every required assignment is submitted.

App work:

- Convert the existing workspace, recovery, queue, and annotation API code from
  media-exclusive leases to assignment-exclusive leases while keeping peer
  work blind.
- Follow the App plan's
  [Phase 5 assignment-workspace work](../../dada-app/docs/annotator-disagreement-adaptation-plan.md#phase-5-assignment-workspace).

Exit gate: concurrent database tests prove that two group members can lease
different assignments for the same media, but no assignment can be leased
twice; stale drafts, expired leases, duplicate completions, and cross-user
access fail correctly.

### Phase 6: consensus engine, diagnostics, and adjudication

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

Repository/service integration tests must use PostgreSQL rather than an
in-memory substitute. Consensus algorithm tests use small committed golden
fixtures; large/GPU benchmarks remain a separate environment. OpenAPI response
schemas, examples, error envelopes, idempotency, cursors, and required headers
are contract-tested, not just status codes.

## Decisions required before dependent phases

- Phase 3: select and pin the S3-compatible object-storage product and define
  cancellation/project-deletion retention.
- Phase 6: pin compatible Cleanlab and crowd-kit versions; define the initial
  capability-exposed strategy identifiers/parameter schemas; select the
  maintained STAPLE implementation or approve an internal implementation
  validated against reference fixtures; set initial per-task thresholds using
  representative labeled data rather than arbitrary defaults.
- Phase 6: decide whether manager adjudication may be performed by the same
  person who contributed a raw submission. The conservative default is to
  allow it but record the conflict in provenance; regulated deployments may
  require an independent adjudicator.
- Phase 7: define the learning command/result protocol and dataset export
  format. Celery/Redis is transport, not the domain contract.

The Phase 1 deployment decision remains unchanged: a reverse proxy presents
App and API as one origin so refresh cookies remain first-party and
SameSite-compatible. The Phase 2 identity decision also remains unchanged:
administrators create user accounts directly; email invitation is deferred.

## Explicitly deferred work

- Adaptive annotator reliability weighting (for example Dawid-Skene) remains
  deferred as a consensus input. The project-scoped evidence and summaries
  required to evaluate it are delivered in Phases 6–7, but activation requires
  adequate adjudicated/gold or cross-fitted evidence, bias monitoring, and a
  separate policy/versioning decision.
- Partial quorums drawn from a larger annotator pool.
- Cross-image or temporal consensus for video.
- Automated annotator scoring, ranking, or punitive performance workflows.
- A concrete production active-learning/model-training implementation; it must
  plug into the learning port without taking ownership of HTTP or persistence.

These deferrals do not defer the durable policy, assignments, independent raw
submissions, task-specific resolver boundary, disagreement metrics, manual
review, canonical resolutions, or provenance required by the feature.
