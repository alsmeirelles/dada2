# Consensus Engine Requirements

**Status:** Draft — implementation blocked  
**Target phase:** Phase 6  
**Decision record:** `docs/phases/phase_6.md` (must exist and be approved before implementation)

## Purpose and approval gate

This document is the blocking requirements specification for the DADA
consensus engine. It defines the complete cross-task behavior required from
submission readiness through automated resolution, manager review,
adjudication, provenance, and performance evidence.

Phase 6 **must not start implementation** until:

1. decisions `P6-01`–`P6-07` and App decisions `A6-01`–`A6-04` are resolved in
   `docs/phases/phase_6.md` with rationale, alternatives, contract/data effects,
   approver, and date;
2. every `[TO DECIDE]` item in this document is replaced by the approved
   outcome or a link to it;
3. the document status is changed to **Approved** with approver and date;
4. the classification, detection, and segmentation annexes are consistent
   with the approved resolver catalog and parameter schemas; and
5. the API plan and App plan link to the approved revision.

Exploratory fixtures and dependency spikes may be used to decide an item. They
must not become production resolver code before approval.

## Normative scope

This document and its task annexes are normative together:

- [Classification consensus](consensus/classification.md)
- [Detection consensus](consensus/detection.md)
- [Segmentation consensus](consensus/segmentation.md)

The engine includes:

- readiness detection after all required assignments have submissions;
- durable resolution-job scheduling and execution;
- task-specific normalization, matching, aggregation, and quality gates;
- proposed and accepted immutable resolution versions;
- disagreement diagnostics and raw-to-canonical evidence;
- manager evidence, retry, acceptance, editing, replacement, and adjudication;
- deterministic provenance and idempotent replay;
- project-scoped annotator-performance observations; and
- privacy-safe state, errors, audit records, and events.

Training, active-learning acquisition, model serving, named annotator ranking,
partial quorum, and browser-side consensus calculations are outside Phase 6.
Phase 7 consumes only accepted resolutions produced under this contract.

## Actors and authorization

| Actor | Required behavior |
| --- | --- |
| Annotator | May submit only their own assignment. Before submission they receive no peer identity, document, vote, metric, proposal, or resolution detail. After submission visibility follows decision `P5-06`. |
| Project owner/manager | May read evidence and history, retry an approved resolver configuration, accept a proposal, or adjudicate when authorized. Contributor/adjudicator conflicts follow `P6-04`. |
| Global administrator | Has the same project-resource authority currently defined by the centralized authorization matrix; actions remain project-audited. |
| Consensus worker | Uses a scoped internal identity and accepts only durable commands. It cannot call manager HTTP actions or bypass project/task/configuration validation. |

The authorization matrix must contain explicit actions for reading evidence,
running resolution, adjudicating, and reading aggregate performance. Route
visibility in the App is only a convenience; the API enforces every action.

## Domain states and invariants

An item follows this resolution lifecycle:

```text
awaiting_submissions -> resolution_queued -> resolving
  -> proposed -> accepted
  -> review_required -> accepted
  -> failed
```

The approved Phase 6 decision may collapse `proposed` into an atomic automatic
acceptance transition, but persistence and events must still distinguish the
resolver output from the accepted canonical version.

Required invariants:

1. Raw submissions and submitted document revisions are immutable.
2. A resolution run references one complete, ordered input snapshot and one
   configuration fingerprint.
3. At most one active job exists for the same item and configuration
   fingerprint.
4. At most one resolution version is accepted for an item at a time.
5. Retrying or adjudicating creates a new version and supersedes history; it
   never updates raw evidence in place.
6. Batch/iteration completion depends on accepted resolutions for every item,
   not on submission count alone.
7. Missing required submissions block automated resolution in the first
   release. A waived or reassigned assignment follows the approved Phase 5
   policy and may not reduce consensus below two independent submissions.
8. Training and exports can reference accepted resolution IDs only.

## Functional requirements

### CE-F01 — readiness and scheduling

- The final required submission transaction records item readiness and a
  transactional outbox entry exactly once.
- Duplicate final-submission requests or outbox delivery cannot schedule
  duplicate active runs.
- Single-annotation mode creates its canonical resolution transactionally in
  Phase 5 and does not invoke a statistical resolver.
- Consensus mode snapshots submission IDs, document versions/content hashes,
  policy version, ordered annotator IDs, task, class catalog version, media
  identity/dimensions, and resolver configuration before dispatch.

### CE-F02 — resolver registry and capabilities

- Clients select only registered, task-compatible pipeline IDs exposed by
  `/api/v1/capabilities`; arbitrary package names, classes, modules, or code are
  rejected.
- Every pipeline and sub-strategy has a typed, closed parameter schema with
  defaults, bounds, descriptions, and compatibility metadata.
- Capabilities expose adapter semantic version and installed dependency version.
- A missing/incompatible optional dependency removes the capability and yields
  a stable unavailable error. The engine never substitutes another algorithm.
- Provisional Phase 2 policy IDs are migrated according to `P6-02`.

### CE-F03 — input normalization

- The worker validates the complete input snapshot independently of HTTP
  submission validation and fails closed on changed/missing content.
- Geometry uses original-image pixel coordinates and recorded source
  dimensions. Non-finite, out-of-bounds, degenerate, or task-incompatible
  content cannot enter a resolver silently.
- Empty annotations are valid where the approved task schema permits them and
  participate explicitly in disagreement measurement.
- Normalization ordering and all rasterization/matching inputs are deterministic
  and included in provenance.

### CE-F04 — task-specific resolution

- Classification follows the classification annex for declared single-label or
  multi-label projects, including explicit negative observations and review on
  ties or unusable output.
- Detection first identifies candidate objects class-agnostically, resolves
  existence/class, then refines only boxes supporting accepted candidates.
- Segmentation first identifies instances class-agnostically, resolves
  existence/class, then aggregates only masks supporting accepted instances.
- Same-annotator duplicate objects never become independent votes.
- No resolver may select an annotator, class display order, or random output as
  an undocumented tie breaker.

### CE-F05 — quality gates and outcomes

- Each run computes the approved task-specific metrics and threshold decisions.
- Ties, insufficient support, ambiguous matches, invalid/degenerate output,
  failed topology, or metrics below an approved threshold produce
  `review_required` rather than an arbitrary canonical result.
- A successful run persists a proposed result and, where automatic acceptance
  criteria permit, an accepted immutable canonical document.
- Threshold boundaries and floating-point comparison/rounding rules are
  explicit, versioned, and fixture-tested.

### CE-F06 — diagnostics and evidence

- Persist task-stage diagnostics, source-to-candidate and source-to-canonical
  mappings, unmatched reasons, vote/support distributions, geometry metrics,
  excluded outliers, and threshold outcomes.
- Manager evidence returns raw submissions, proposal, accepted/superseded
  history, diagnostics, and provenance through paginated/lazy resources where
  necessary.
- Ordinary assignment/queue/event responses contain no raw peer evidence or
  named peer status.

### CE-F07 — retries and configuration history

- An authorized manager may retry only with a currently registered typed
  configuration and the expected evidence/resolution version.
- A retry creates a new run/configuration fingerprint. Stale configuration,
  stale evidence, and concurrent retry return stable conflicts.
- Failed, superseded, and successful runs remain auditable. Retrying cannot
  erase or mutate an earlier output.

### CE-F08 — acceptance and adjudication

- An authorized manager may accept a valid proposal, edit from the proposal,
  edit from a selected raw submission, or submit a replacement canonical
  document.
- Every action is versioned, idempotent, explicitly audited, and validates the
  resulting document against the project task/classes/media.
- Adjudication records actor, contributor-conflict status, action/source,
  rationale when required, input version, canonical hash, and superseded
  resolution.
- Stale adjudication returns `409` without discarding the App's local recovery
  document.

### CE-F09 — provenance and deterministic replay

Every run records at least:

- pipeline, adapter, and dependency names/versions;
- complete typed parameters and review thresholds;
- ordered submission IDs, document versions, and content hashes;
- class catalog and media version/dimensions;
- normalized-input and configuration hashes;
- random seed when an approved algorithm uses randomness;
- worker/job identity, attempt, timestamps, duration, and execution outcome;
- raw resolver output checksum and canonical document checksum; and
- threshold decision and accepted/superseded resolution identity.

Replaying identical normalized inputs with the same versions, parameters, and
seed must produce the same result bytes or a documented canonical-equivalent
representation.

### CE-F10 — annotator-performance evidence

- Acceptance or adjudication writes immutable, project-scoped observations
  tied to assignment, submission, item, resolution ID/version, task, class,
  source-to-canonical mapping, metric, and evaluation source.
- Detection/segmentation unmatched cases retain distinct false-positive,
  missed-object, duplicate, ambiguous-match, empty, and invalid-topology
  outcomes instead of invented zero-overlap values.
- Superseding a resolution preserves old observations and excludes them from
  current summaries according to the approved `P6-07` policy.
- Automated-consensus observations do not automatically weight the same
  annotator in later consensus runs.

### CE-F11 — audit and events

- Audit entries cover scheduling, retry, automatic outcome, manual acceptance,
  adjudication, failure recovery, and supersession without embedding full
  annotation documents or secrets.
- Committed events include `resolution.started`, `resolution.completed`,
  `resolution.review_required`, and `resolution.adjudicated` with monotonic
  project sequence support when Phase 8 enables delivery.
- Event payloads contain identifiers and privacy-safe state only; REST remains
  authoritative.

## Persistence requirements

The approved schema must represent resolution runs, ordered inputs, immutable
proposals/resolved documents, accepted/superseded versions, adjudications,
object/instance evidence, worker jobs, outbox events, and performance
observations. Database constraints must enforce active-job and accepted-version
uniqueness where possible. Content hashes use one documented canonical JSON
encoding.

Large raster masks or derived evidence may use the configured artifact store,
but PostgreSQL retains authoritative identity, checksums, ownership, lifecycle,
and links. Cleanup/retention behavior is part of `P6-07` and Phase 8 operations.

## HTTP contract requirements

The final OpenAPI contract must include:

| Method | Endpoint | Requirement |
| --- | --- | --- |
| `GET` | `/api/v1/projects/{project_id}/batches/{batch_id}/resolutions` | Cursor/filtered manager queue with reason, state, counts, metrics summary, versions, and age |
| `GET` | `/api/v1/projects/{project_id}/batch-items/{item_id}/evidence` | Versioned manager evidence, diagnostics, proposal, history, and pagination/lazy links |
| `POST` | `/api/v1/projects/{project_id}/batch-items/{item_id}/resolve` | Idempotent retry with expected version and typed configuration |
| `POST` | `/api/v1/projects/{project_id}/batch-items/{item_id}/adjudicate` | Idempotent accept/edit/replace action with expected version |
| `GET` | `/api/v1/projects/{project_id}/annotator-performance` | Authorized aggregates with sample sizes and suppression rules |

Stable errors include `resolution_not_ready`, `resolution_config_conflict`,
`resolver_unavailable`, `resolver_output_invalid`, `resolution_in_progress`,
`adjudication_required`, `version_conflict`, and authorization/not-found errors
that do not disclose another project's item.

## Worker command/result protocol

The protocol is versioned independently of Celery/Redis and must support a
deterministic fake before external resolver packages are integrated. Commands
carry IDs and hashes, never ORM objects. Results carry command version,
configuration fingerprint, input fingerprint, outcome, diagnostics/artifact
references, output hash, timings, and typed failure information.

Required fake-worker scenarios are success, ambiguity, invalid output, retry,
duplicate result, stale result, timeout, worker crash, and permanent failure.
Result ingestion verifies all identities/fingerprints and commits state,
outbox, audit, and observations atomically.

## Security, privacy, and safety requirements

- Project isolation and role authorization apply to every evidence/artifact
  lookup, including signed or indirect URLs.
- Error bodies, logs, traces, events, and metrics do not contain raw annotation
  documents, images, credentials, or unauthorized annotator identities.
- Parser, geometry, rasterization, and package inputs have explicit size and
  complexity limits before expensive work begins.
- Resolver dependencies execute with approved CPU/memory/time limits and no
  ability to load arbitrary client code.
- Raw submissions and provenance remain immutable and reviewable after a bad
  resolver deployment or manual decision.

## Operability requirements

Expose queue depth, run duration, outcome/review/failure counts, retry count,
stale/duplicate result count, and resource-limit failures by pipeline/version
without annotator identity labels. Traces connect submission, outbox, job, run,
and result ingestion. Operators can identify and retry recoverable failures and
quarantine a capability version without changing stored evidence.

Timeouts, attempts, backoff, concurrency, artifact retention, and quarantine
behavior remain `[TO DECIDE: P6-05/P6-07]`.

## Verification and acceptance

Phase 6 requires:

1. unit tests for normalization, matching, aggregation, thresholds, canonical
   hashing, and every stable error;
2. committed golden fixtures for all cases listed in the three task annexes;
3. property tests for geometry bounds and deterministic ordering where useful;
4. PostgreSQL integration tests for scheduling, active-job uniqueness,
   immutable evidence, accepted-version uniqueness, retry, and adjudication;
5. duplicate, stale, timeout, crash, and permanent-failure worker tests;
6. authorization and blindness tests across every role and endpoint;
7. App contract tests for review, evidence, retry, acceptance, adjudication,
   accessibility, and stale-version recovery; and
8. deterministic replay using the exact approved dependency versions.

The Phase 6 exit gate is satisfied only when all three task pipelines pass
their golden fixtures, low-quality cases reach review, raw submissions remain
unchanged, one adjudication closes an item, duplicate results cannot create two
accepted versions, and performance observations remain correct and idempotent.

## Blocking decisions and approval record

| ID | Status | Must resolve before approval |
| --- | --- | --- |
| `P6-01` Resolver/package catalog | **PENDING** | Versions, pipeline IDs, compatibility and unavailable behavior |
| `P6-02` Configuration/quality gates | **PENDING** | Typed schemas, calibrated defaults/bounds, thresholds, ties, provisional-ID migration |
| `P6-03` Segmentation implementation | **PENDING** | STAPLE choice, crowd-kit set, rasterization/polygonization stack and fixtures |
| `P6-04` Adjudicator independence | **PENDING** | Contributor conflict policy, role restrictions and audit |
| `P6-05` Job execution | **PENDING** | Protocol, topology, timeouts, retries, cancellation, limits and recovery |
| `P6-06` Acceptance/versioning | **PENDING** | Proposal/acceptance transitions, retry conflicts, supersession and precedence |
| `P6-07` Evidence/performance policy | **PENDING** | Retention, access, mapping, eligibility, suppression and supersession behavior |

Approval metadata to complete after the decision record is accepted:

- **Approved by:** `[TO DECIDE]`
- **Approval date:** `[TO DECIDE]`
- **Approved decision record:** `[TO DECIDE: link to docs/phases/phase_6.md]`
- **OpenAPI baseline:** `[TO DECIDE]`
- **Resolver compatibility set:** `[TO DECIDE]`
