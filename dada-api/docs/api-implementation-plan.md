# DADA API v1 Implementation Plan

## Objective and boundary

Implement the server-side contract required by the existing DADA App without
moving API responsibilities into this repository's browser client. The API is
a separately deployed Python service and owns durable state, authorization,
upload validation, annotation concurrency, active-learning orchestration, and
project events.

This plan is implemented in the `dada-api` package. The concrete
active-learning algorithms, model training, and GPU integration are deferred.
All surrounding HTTP, persistence, queueing, state-machine, and worker boundary
code is implemented now so that the later active-learning component can receive
durable requests and report results without changing the public API.

The generated OpenAPI document is the executable interface definition. It must
remain compatible with [api-contract.md](../../dada-app/docs/api-contract.md)
and with the request and response shapes used in
`src/features/projects/project-api.ts` and
`src/features/annotation/annotation-api.ts`.

## Recommended service shape

Use a modular monolith initially, with boundaries that can later be split
without changing the public API:

```text
FastAPI application
  auth and authorization
  projects, classes, and members
  uploads and media metadata       -> S3-compatible object storage
  iterations and annotations       -> PostgreSQL
  leases and idempotency           -> PostgreSQL transactions
  event tickets and event delivery -> Redis pub/sub (optional initially)
  learning orchestration           -> Celery/Redis -> learning adapter
```

FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Pydantic 2, and an S3-compatible
object store are suitable defaults. A database-backed outbox should connect
committed state changes to WebSocket events and worker jobs. Redis may support
fan-out and rate limiting, but correctness must not depend on ephemeral Redis
state. In particular, leases, idempotency results, iteration state, and job
state remain durable.

Development and production-like local environments initially use
`postgres:17-alpine` and `redis:7.4-alpine` from the official Docker images.
Patch-level image digests should be recorded by each release for reproducible
deployment while retaining reviewed security updates.
Application containers never rely on Docker service names outside the composed
local environment; database and broker URLs remain ordinary settings.

The learning adapter is a versioned application port. Initially it is backed by
a deterministic stub that accepts jobs, records lifecycle updates, and returns
predictable results. The future active-learning implementation replaces that
adapter without importing FastAPI, database sessions, or HTTP schemas.

## Domain model and invariants

The first migration should establish these aggregates:

| Aggregate | Principal records | Important invariants |
| --- | --- | --- |
| Identity | users, refresh sessions, bootstrap records | Refresh rotation and revocation are atomic; bootstrap is idempotent |
| Project | projects, project members, classes | One owner; unique class name and display order per project; versioned edits |
| Ingestion | upload sessions, upload items, chunks, media, content objects | No absolute client paths; checksum and size verified before media is usable |
| Learning | dataset splits, iterations, iteration selections, model runs | Test split is immutable and excluded from acquisition; selection is reproducible |
| Annotation | leases, annotation documents, annotation objects | At most one active lease per selected media; submitted versions are immutable |
| Operations | idempotency records, outbox events, worker jobs | A repeated key returns the original result for the same user, route, and body |

Store original-image dimensions with media. Persist annotation geometry in
original-image pixel coordinates. Use database constraints for unique and
one-active-record rules where possible, and transactions plus row locking for
lease acquisition and iteration closure.

Project and iteration transitions must be explicit service operations rather
than arbitrary status updates. Every operation checks the caller's project
role (`owner`, `manager`, `annotator`, or `viewer`) and records an audit entry
for membership, lease revocation, annotation submission, and state changes.

## Delivery phases

Phases form a strict dependency hierarchy: a phase begins only after the prior
phase's exit gate passes. Each phase ends in a deployable API increment. GPU and
algorithm integration is outside this plan; the iteration state machine must
work end to end with the deterministic learning adapter.

### Phase 0: contract and service foundation

Status: completed on 2026-07-19. The exit gate was verified against the
official PostgreSQL and Redis Alpine containers, including migration drift,
readiness, and durable idempotency tests.

- Establish the existing `dada-api` package as the service boundary; add the
  application factory, settings, dependency injection, structured logging, and
  trace IDs.
- Add a local Compose file using official `postgres:17-alpine` and
  `redis:7.4-alpine` images, health checks, named volumes, and API/worker
  connection settings. PostgreSQL is authoritative; Redis is disposable.
- Add SQLAlchemy session management and Alembic, including a startup policy that
  checks migration state but never silently migrates production databases.
- Define Pydantic request/response schemas and generate the initial OpenAPI
  document for all v1 routes, marking unimplemented operations only in a
  development build if necessary.
- Implement the common error envelope, cursor encoding, idempotency middleware,
  CORS policy, health/readiness endpoints, and database transaction boundaries.
- Add CI for formatting, static checks, migrations, unit/integration tests, and
  an OpenAPI compatibility check.

Exit gate: documented commands start PostgreSQL and Redis, migrate a clean
database, and run the API; `/health` and readiness distinguish process health
from dependency health; errors match the contract; the frontend TypeScript
client can be checked against generated OpenAPI types.

### Phase 1: identity, capabilities, and authorization

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

### Phase 2: project setup

- Implement project list/create/read/versioned update and explicit activation.
- Implement ordered class CRUD with color validation and optimistic versions.
- Implement member listing, invitation, role change, and removal, including
  protections for the sole owner.
- Keep projects in `draft` until ingestion begins; reject activation until
  classes, media, and requested split sizes are valid.

Exit gate: the App can create a draft, add classes and collaborators, list the
project, and receive stable `409` or `422` errors for invalid transitions.

### Phase 3: resumable ingestion and media

- Validate manifests, normalized relative paths, advertised media types,
  project/file limits, duplicate content, and client file IDs.
- Implement upload sessions and chunk acknowledgement using `Content-Range`,
  `Upload-Offset`, and `X-Chunk-SHA256` as sent by the current App.
- Persist acknowledged offsets so retries and process restarts resume safely.
- On completion, verify full-file SHA-256, inspect/decode the image, record its
  dimensions, quarantine invalid content, and promote the object atomically.
- Process completion asynchronously and expose durable per-item status. Make
  completion idempotent and cancellation safe.

Exit gate: nested paths, unsupported and corrupt images, duplicate content,
wrong offsets/checksums, interrupted uploads, retry, cancellation, size limits,
and concurrent completion are integration-tested against real object storage.

### Phase 4: activation, splits, and initial iterations

- Atomically freeze setup, create immutable train/test membership, and create
  the initial annotation iteration.
- Seed random choices deterministically and record seed, selection strategy,
  model/run IDs, and selected media.
- Implement iteration list/detail and the idempotent close reconciliation
  operation, including `409 iteration_incomplete` counts.
- Use a fake deterministic training/acquisition adapter to exercise transitions
  independently of any GPU worker.

Exit gate: the same recorded seed/input reproduces selection; test media never
enters acquisition; invalid status transitions roll back completely.

### Phase 5: queues, leases, and annotations

- Implement queue reads and atomic acquisition of a requested or next item.
- Store lease expiry using server time; implement owned renewal, release,
  expiry, and authorized manager revocation.
- Implement draft save with optimistic annotation versions and idempotent final
  completion. Validate class membership, task type, bounds, rectangles, polygon
  rings, and classification's null geometry.
- Close an iteration automatically when its last selected item is completed,
  while retaining the explicit close route for reconciliation.

Exit gate: a concurrency test with multiple database connections proves that
only one annotator can acquire an item. Expired leases cannot submit, stale
versions return `409`, and repeated completion cannot duplicate annotations or
advance state twice.

### Phase 6: learning boundary, metrics, and assisted segmentation contract

- Define a versioned worker command/result protocol and durable job records.
- Define the learning service port and connect iteration closure to training and
  acquisition jobs through the transactional outbox and Celery/Redis.
- Provide a deterministic adapter that consumes jobs and exercises successful,
  retryable, failed, duplicated, and delayed outcomes. Do not implement the
  real active-learning selection or training algorithms in this phase.
- Report progress, ETA, failure details, retries, model/run identity, and
  statistics without trusting worker-supplied authorization context.
- Implement project and lease authorization, schemas, job dispatch, and result
  handling for assisted segmentation. A production SAM adapter is deferred;
  the deterministic adapter may return a documented unavailable result where a
  meaningful fake prediction would be misleading.

Exit gate: fake-worker tests cover success, retry, timeout, duplicate result,
and permanent failure; iteration requests reach the adapter and adapter results
advance durable state without direct coupling to active-learning code.

### Phase 7: real-time delivery and production hardening

- Issue short-lived, single-use, project-scoped WebSocket tickets.
- Publish committed outbox events with per-project monotonic sequence numbers.
- Support reconnect and event gaps by ensuring every event is only an
  invalidation hint and all authoritative state remains readable over REST.
- Add rate limits, signed URL expiry, request/body limits, metrics, tracing,
  backup/restore drills, retention policies, and operational runbooks.

Exit gate: WebSocket ticket replay and cross-project use fail; reconnect and
sequence-gap browser scenarios pass; load tests cover chunk upload, queue
contention, event fan-out, and worker bursts.

### Phase 8: system documentation and release acceptance

- Create dedicated API run/development documentation covering prerequisites,
  environment variables, PostgreSQL and Redis startup, migrations,
  administrator bootstrap, API and worker processes, tests, and troubleshooting.
- Create a whole-system runbook covering the API and App together, CORS,
  HTTP/WebSocket URLs, service startup order, health checks, shutdown, volumes,
  and a first-login smoke test. Link rather than duplicate the App's existing
  build and container instructions.
- Record architectural decisions as individual ADR Markdown files with status,
  context, decision, consequences, and alternatives. At minimum cover the
  modular monolith, PostgreSQL as authority, Redis/Celery's disposable role,
  transactional outbox, administrator bootstrap, refresh credential storage,
  object storage, annotation leases, idempotency, and the learning adapter.
- Publish the generated OpenAPI document and an App/API compatibility record.

Exit gate: a new developer can start infrastructure, migrate, bootstrap the
administrator, run API/worker/App, log in, create a project, upload a small
dataset, annotate it, and observe a deterministic learning job using only the
documented commands.

## Cross-cutting API rules

- Return the common error envelope for application errors, including `trace_id`.
- Accept and persist `Idempotency-Key` on create/complete operations. Reject a
  reused key with a different request body.
- Use opaque signed cursors and deterministic ordering for every list route.
- Return `Retry-After` on actionable `429` and `503` responses.
- Never log bearer/refresh credentials, event tickets, signed URLs, image bytes,
  or annotation payloads at normal log levels.
- Reject absolute paths, traversal, invalid UTF-8/path normalization collisions,
  and client claims that exceed capabilities.
- Make OpenAPI examples part of schema tests so documentation cannot silently
  drift from the implementation.

## Test strategy and environments

API tests should follow the pyramid described in [testing.md](../../dada-app/docs/testing.md):

1. Pure unit tests for transitions, geometry, authorization matrices, cursor
   parsing, and selection rules.
2. Repository/service integration tests with PostgreSQL and S3-compatible
   storage, including transaction and concurrency behavior.
3. HTTP contract tests for schemas, statuses, headers, error envelopes,
   idempotency, and authentication.
4. Worker contract tests using a deterministic fake worker.
5. App-to-API browser tests for the critical product journeys in Chrome and
   Firefox.

CI should publish the OpenAPI artifact and compare it with the last released
version. A nightly environment should use the same PostgreSQL and object-store
major versions as production. GPU tests begin only when the separate concrete
active-learning implementation is integrated.

## First implementation slice

The first pull request should be deliberately narrow:

1. Application/settings skeleton, PostgreSQL session management, and Alembic.
2. Local Compose infrastructure with pinned PostgreSQL and Redis Alpine images.
3. Common error/trace handling and `/health` plus readiness.
4. OpenAPI schemas for capabilities and projects.
5. `GET /api/v1/capabilities` backed by validated settings.
6. CI with unit tests, a PostgreSQL integration test, migration verification,
   and OpenAPI export.

This slice validates deployment, configuration, schema conventions, and the
test harness before durable domain behavior is added.

## Decisions still required before their dependent phases

- Object-storage product, version, and local development strategy (required in
  Phase 3).
- Whether refresh cookies can be first-party in the intended deployment
  topology; if not, the approved credential-storage alternative (Phase 1).
- Dataset and object retention rules after upload cancellation or project
  deletion (Phase 3).
- Invitation identity: existing username only versus email/pending invitation
  (Phase 2).
- The versioned command/result payload the later active-learning package will
  implement (Phase 6). Celery with Redis is the transport, not the domain API.

## Deferred work

Only the concrete active-learning and GPU/model implementations are deferred.
The REST and WebSocket contracts, persistence, authentication and authorization,
project setup, ingestion, splits, iterations, queues, leases, annotations,
idempotency, worker dispatch/result handling, metrics surfaces, failure states,
and operational documentation are delivered by the phases above. Deferred code
must plug into the learning port and must not require contract or database
ownership changes.
