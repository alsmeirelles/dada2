# DADA API Development

This guide covers the Phase 0 service foundation, the Phase 1 identity, session,
and authorization layer, the Phase 2 project setup, membership, and annotation
policy, the Phase 3 ingestion and media store, and the Phase 4 user
administration, activation, and annotation batches. Concrete active-learning and
GPU workers are intentionally not part of these phases.

## Prerequisites

- Python 3.11 or newer
- `uv`
- Docker with Compose v2

Copy `.env.example` to `.env` and replace development credentials when the
services are reachable outside your machine. Never commit `.env`.

## Start the service

```bash
make sync-dev
make infra-up
make migrate
make bootstrap-admin
make run
```

A freshly migrated database contains no users and exposes no route that can
create one. `make bootstrap-admin` creates the initial administrator; see
[Administrator bootstrap](#administrator-bootstrap) below.

The default install deliberately excludes CUDA and model packages. When the
concrete learning implementation is developed later, install its isolated
dependency extra with `uv sync --extra learning`.

The API listens on `http://localhost:8000` by default. `GET /health` is a
dependency-free liveness probe. `GET /ready` returns success only when
PostgreSQL and Redis respond and PostgreSQL is at the Alembic migration head.
API startup checks neither creates nor upgrades tables. Run `make migrate`
explicitly during deployment.

PostgreSQL uses a named Docker volume. `make infra-down` stops containers but
keeps the data. Deleting the volume is intentionally not provided as a Make
target because it is destructive.

## Quality gates

```bash
make lint
make test
make migration-check
make openapi
make check
```

The normal test suite skips external-service integration tests. With the
Compose services migrated and healthy, run them with:

```bash
DADA_RUN_INTEGRATION=1 make test
```

`make openapi` writes `openapi.json`. The committed file is the API contract
artifact and CI fails when generated output differs.

## Configuration

Settings use the `DADA_` prefix and are documented in `.env.example`: database
and Redis URLs, CORS origins, trace/log settings, capability limits, upload
chunk size, storage roots, JWT/cursor signing secrets, refresh credential
lifetime and cookie policy, and the bootstrap administrator identity. `VITE_*`
settings belong to the App and must not be copied into the API environment.

The official `postgres:17-alpine` and `redis:7.4-alpine` images are used for
local infrastructure. Redis is disposable; PostgreSQL is authoritative.

### Storage roots

Ingested bytes live on the filesystem, under two separately configured roots:

| Setting | Holds | Default |
| --- | --- | --- |
| `DADA_MEDIA_ROOT` | Promoted, verified media | `var/media` |
| `DADA_UPLOAD_PARTS_ROOT` | In-flight upload parts | `var/upload-parts` |

Relative values resolve against the `dada-api` directory; both are resolved to
absolute paths at startup. Startup refuses a configuration where they are equal:
cancelling an upload purges the parts root outright, so promoted media must
never sit inside that blast radius.

On the shared server these are host paths bind-mounted into the API container.
Neither path is ever exposed to a client. `services/storage.py` is the only
module that touches the filesystem, so migrating to an object store later
replaces that module without changing any route or the App.

Both roots are created on first use, never at import time, so the application
factory keeps its no-startup-side-effects guarantee.

## Administrator bootstrap

A migrated database contains no users, and no HTTP route can create the first
one. The initial administrator is created from the command line:

```bash
make bootstrap-admin
```

The command reads `DADA_SEED_ADMIN_USERNAME`, `DADA_SEED_ADMIN_DISPLAY_NAME`,
and `DADA_SEED_ADMIN_PASSWORD`. Anything left unset is prompted for
interactively, with the password read without echo. The password is hashed with
Argon2 and is never logged or stored in plaintext.

The command is safe to rerun: repeating it with the same username reports the
existing administrator and leaves the stored password hash untouched. Repeating
it with a *different* username is refused with a non-zero exit code rather than
resolved by guessing. Changing which identity is the bootstrap administrator
requires the explicit command:

```bash
uv run dada-api replace-bootstrap-admin
```

Replacement creates the new administrator and repoints the bootstrap record at
it, then asks whether the previous administrator should lose its global
authority. The previous account always survives; only the flag is at stake. A
run with no answer available — non-interactive, or standard input at EOF —
keeps that authority, because withdrawing someone's access is never the safe
default to assume.

API startup neither creates nor resets credentials.

## User administration

Once the first administrator exists, further accounts are created over HTTP.
These routes are global authority: they require `is_administrator` and are not
reachable through any project role, however senior.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/users` | Cursor-paginated list, optional `active` filter |
| `POST` | `/api/v1/users` | Create an account |
| `GET` | `/api/v1/users/{user_id}` | Read one account |
| `PATCH` | `/api/v1/users/{user_id}` | Versioned update of profile and access |
| `POST` | `/api/v1/users/{user_id}/reset-password` | Administrator password reset |
| `DELETE` | `/api/v1/users/{user_id}` | Terminal removal, version in `If-Match` |
| `POST` | `/api/v1/auth/me/password` | Any active user changes their own password |

`username` is immutable after creation and is simply absent from the update
contract. `display_name`, `is_active`, and `is_administrator` are editable with
an optimistic `version`; a stale one returns `409 version_conflict`.

Deletion is terminal and carries the expected version in `If-Match` — the bare
number, quotes tolerated. A missing or unreadable header is
`400 invalid_if_match`. Deletion is refused with `409 user_in_use` while
anything still references the account: an owned project, an audit entry the
user authored, the bootstrap record, a snapshotted consensus group, or an
assignment. Those references exist so history stays truthful, so
`is_active=false` is the reversible way to withdraw access instead.

Two protections guard the installation. Withdrawing administration or access
from the only active administrator returns `409 last_active_administrator`,
which is checked first because it is the more specific fact. With another
administrator still active, an administrator withdrawing their *own* access
returns `409 self_administration_change`. Demoting a peer stays allowed.

Password reset, self-service change, and deactivation revoke every refresh
session the target holds. Deletion removes them outright. Passwords are 8–128
characters and never appear in a response, a log line, or an audit payload.

## Sessions and refresh credentials

`POST /api/v1/auth/token` returns a short-lived bearer access token and sets a
refresh cookie. `POST /api/v1/auth/refresh` rotates that credential and returns
a new access token; `POST /api/v1/auth/logout` revokes the session.

Rotation is single-use. Presenting a credential that was already rotated is
treated as a replay: the request fails with `refresh_token_replayed` and every
credential in that rotation family is revoked.

The cookie is `HttpOnly`, `SameSite`, scoped to `/api/v1/auth`, and `Secure` by
default. Keeping it first-party requires App and API to share one origin, which
the deployment topology provides with a local reverse proxy (Nginx) in front of
both. Set `DADA_REFRESH_COOKIE_SECURE=false` only for plain-HTTP local
development; leave it `true` everywhere else.

## Authorization

Global authority is the `is_administrator` flag on a user. Authority inside a
project comes from project membership with the roles `owner`, `manager`,
`annotator`, and `viewer`.

Every project-scoped decision goes through one function in
`dada_api/services/authorization.py`; routes never decide for themselves. A
global administrator passes every project check with owner-equivalent
authority, while `owner_id` keeps recording the truthful creator.

## Project setup

Projects, ordered classes, membership, and the default annotation policy are
live. Creating a project writes the project, its owner's membership row, and a
`single`-mode policy in one transaction, because project authority is resolved
from membership rather than from `owner_id`.

Membership is granted to an existing username. Email invitation is deferred, so
an unknown username is `404 user_not_found` rather than a pending invitation. A
project keeps exactly one owner, enforced by a partial unique index; removing,
demoting, or duplicating that owner returns `409 sole_owner_protected`.

The default policy is `single` or `consensus`. A consensus policy needs at least
two distinct project members whose role carries annotation authority (`owner`,
`manager`, or `annotator`) and a resolver advertised for the project's task.
Policy edits are optimistically versioned; a stale `version` returns `409`.
Later phases snapshot this default into each annotation batch, so editing it
never changes work already in flight.

Membership and policy changes write an audit entry in the same transaction as
the change, carrying the request's trace ID.

`POST /api/v1/projects/{id}/activate` validates prerequisites and reports what
is missing before doing anything. See [Activation and batches](#activation-and-batches).

## Consensus resolvers

`dada_api/services/resolvers.py` is the single registry of resolver identifiers
advertised per task through `GET /api/v1/capabilities`. Clients may only choose
an advertised identifier; anything else is `422 unsupported_resolver`.

The current identifiers are a **provisional catalog**. Clients discover and
persist them without hard-coding behavior around their names. Phase 6 will
migrate them to the target pipeline vocabulary: `cleanlab_multiannotator`,
`two_stage_detection_consensus`, and `two_stage_segmentation_consensus`.
`staple` remains a segmentation-refinement option, never a top-level resolver.
The Phase 2 parameter contract is closed: clients send `parameters: {}` and
may expose only `review_thresholds.agreement`. Resolver-specific schemas,
defaults, package versions, and advanced controls belong to Phase 6; the API
stores the fields opaquely until then.

## Dataset ingestion

A client builds a local manifest, creates a session, sends chunks, and completes
the session:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/projects/{project_id}/uploads` | Create a session from a manifest |
| `PUT` | `/api/v1/uploads/{upload_id}/files/{client_file_id}` | Send one verified chunk |
| `POST` | `/api/v1/uploads/{upload_id}/complete` | Verify, inspect, and promote |
| `GET` | `/api/v1/uploads/{upload_id}` | Status and per-file progress |
| `DELETE` | `/api/v1/uploads/{upload_id}` | Cancel and purge parts |
| `GET` | `/api/v1/projects/{project_id}/media` | Paginated media inventory |

Each manifest entry is classified as `upload_required`, `already_present`, or
`rejected` with a stable reason. Chunk requests carry `Upload-Offset` and
`X-Chunk-SHA256`; the response acknowledges the next expected offset in both the
`Upload-Offset` header and its body, so an interrupted upload resumes mid-file.

Accepted offsets live in PostgreSQL rather than process memory, so an upload
survives an API restart. Completion verifies each file's declared digest against
the assembled bytes, reads the original pixel dimensions with Pillow, and
promotes the file. Completion is idempotent.

Deduplication is scoped to the project: identical content uploaded twice is
stored once and referenced by two `media` rows, while two projects holding the
same image keep independent copies. This makes deleting a project a single
directory removal with no cross-project reference counting.

## Activation and batches

Activation is the moment a configured project becomes work. The current Phase 4
implementation is superseded by the required [Phase 4.1 annotation-sequence
revision plan](phase-4-annotation-sequence-revision-plan.md): activation must
freeze `dataset_splits` for every image, create complete `test` and `validation`
batches plus the resolved first `initial_training` image batch, copy the
project's default policy onto each, and move the project from `draft` to
`active`.

Random projects may instead prepare a static `single_batch` layout: one
all-images initial annotation batch, no train/validation/test rows, and no
later training or acquisition iterations. Both layouts may use consensus.
Before activation and before assignments exist, an owner/manager may import
YOLO detection or COCO segmentation labels. Imports are audited seed documents
that prefill each annotator's own draft; they are not submissions, votes, or
canonical resolutions.

The test half is drawn from the whole dataset first and the training set from
what remains, so no image can reach both. That ordering is what makes the
evaluation set genuinely held out rather than filtered out later.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/projects/{project_id}/batches` | Paginated batch inventory |
| `GET` | `/api/v1/projects/{project_id}/batches/{batch_id}` | Policy snapshot and progress |
| `PATCH` | `/api/v1/projects/{project_id}/batches/{batch_id}` | Edit the policy while `preparing` |
| `POST` | `/api/v1/projects/{project_id}/batches/{batch_id}/start` | Freeze it and generate assignments |

A batch carries a **copy** of the policy, not a reference to it. Editing the
project default afterwards cannot reach work already in flight. The copy is
editable while the batch is `preparing`; after `start` it is frozen and a
further `PATCH` returns `409 policy_locked`, while a second start returns
`409 batch_already_started`.

Starting generates assignments atomically: one per snapshotted annotator per
image in `consensus` mode, and one unclaimed assignment per image in `single`
mode, where the policy names no owner. Validation runs before anything is
created, so a refused start leaves no partial work behind.

Image counts and assignment counts are reported separately, because one image
carries one assignment per configured annotator and the two never coincide in
consensus mode.

### Reproducible selection

Each batch records `selection_strategy`, `selection_seed`, and
`selection_input_fingerprint` — the SHA-256 of the ordered candidate list.
`services/selection.py` touches neither the database nor HTTP, so a stored
selection can be recomputed from those recorded fields and compared.

The seed is generated by the server, never supplied by a client: it is
provenance, not a request parameter. The candidate order is
`(relative_path, id)`, the same order the media inventory route returns, so the
selection input is something a client can already read.

An acquisition batch is created only after all initial image batch items have
accepted consensus resolutions. Random acquisition may then select from the
eligible train pool; active learning additionally needs a trained/evaluated
model. The learning port delivers that orchestration, and the `purpose` column
already carries the acquisition value.

## Deletion and retention

Cancelling an upload and deleting a project both purge immediately and
permanently. There is no restore window in this release.

Database records are committed first and the filesystem tree is removed
afterwards. A storage failure is logged at error level rather than raised: the
domain change already succeeded, and orphaned bytes that nothing references are
preferable to rows describing media the API can no longer serve.

`DELETE /api/v1/projects/{project_id}` is owner-only. Managers may not delete a
project, matching the existing treatment of `activate_project`.

## Current placeholders

The assisted-segmentation inference route remains a `501` placeholder until
Phase 7. The prototype `/api/v1/queue` routes were removed in Phase 5; see
[Image assignments](#image-assignments-phase-5).

`GET /api/v1/capabilities` is served from validated settings and now advertises
`upload_session_ttl_hours` alongside the existing upload limits, which this
phase began enforcing.

## Dataset preparation (Phase 4.1)

A draft is prepared explicitly once its classes and media are in place, and
activation only locks what preparation materialised. Decision records are in
[phase_4.1.md](phases/phase_4.1.md).

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/projects/{project_id}/dataset-layout` | Layout, split sizes, batches, training pool, import |
| `POST` | `/api/v1/projects/{project_id}/dataset-layout/prepare` | Draw the split and open the initial batches |
| `DELETE` | `/api/v1/projects/{project_id}/dataset-layout` | Discard the preparation and its import |

`dataset_layout` and `acquisition_strategy` are chosen at project creation.
`split` requires `iteration_batch_size`; `initial_training_size` is optional
and falls back to it. `single_batch` accepts no sizes and only `random`.

Preparing a `split` project draws test from the ordered inventory, validation
from the remainder, and the first training batch from what is left; each batch
records the seed and fingerprint of its own draw. Train images not drawn have
no batch item and form the eligible training pool. Capacity is checked against
the held-out sets and the first batch only (`409 preparation_incomplete` with
`insufficient_media`).

Adding or removing a class, changing a class `display_order`, or promoting new
media resets a prepared draft in the same transaction and records a
`dataset.reset` audit entry with the reason. Renaming or recolouring a class
does not. Batches of a prepared draft cannot be started
(`409 project_not_active`) until activation closes the import review.

## Label import (Phase 4.1)

Owners and managers may seed a prepared draft with existing labels: YOLO
detection sidecars for detection projects and COCO polygon segmentation for
segmentation projects. A project holds at most one import.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/projects/{project_id}/annotation-imports` | Open an import from a file manifest |
| `POST` | `/api/v1/annotation-imports/{import_id}/files/{client_file_id}` | Send one whole file |
| `POST` | `/api/v1/annotation-imports/{import_id}/validate` | Parse and report |
| `POST` | `/api/v1/annotation-imports/{import_id}/accept` | Persist the seed documents |
| `GET` | `/api/v1/annotation-imports/{import_id}` | Status, files, and report |
| `DELETE` | `/api/v1/annotation-imports/{import_id}` | Discard an import that is not accepted |

Files are capped by `DADA_MAX_IMPORT_FILE_BYTES` (advertised in
`/capabilities`) and retained verbatim with their digests as provenance. Any
parse error — unsafe or unmatched path, ambiguous or duplicate image, unknown
class index, malformed line, out-of-bounds or self-intersecting geometry, or a
run-length encoded mask — rejects the whole import; it is then discarded and
started again. Activation reports `label_import` while an import is not
accepted. Starting a batch copies each seeded image's objects into the draft
of every assignment on it and keeps the link as provenance; the seed is never
a submission, vote, or resolution.

## Development data reset

Phase 4.1 changes what activation produces, so development projects created
earlier must be removed and rebuilt from their source media. No compatibility
path exists for them. This procedure is for local development databases only
and must never be run against production.

1. Delete each existing project with `DELETE /api/v1/projects/{project_id}` as
   its owner or an administrator. This purges its rows and its media tree.
2. Alternatively, for a throwaway local database, run `make rebuild`, then
   `make bootstrap-admin`. `make rebuild` deletes the PostgreSQL Compose volume,
   recreates the local services, and migrates the empty database. It refuses to
   run unless `DADA_ENVIRONMENT=development`.
3. Verify that the following returns zero in every column, and that no project
   directory remains under `DADA_MEDIA_ROOT`:

   ```sql
   SELECT (SELECT count(*) FROM projects),
          (SELECT count(*) FROM dataset_splits),
          (SELECT count(*) FROM annotation_batches),
          (SELECT count(*) FROM media);
   ```

4. Recreate the projects through the App from their source folders.

Migration `20260930_0008` (Phase 5) requires every assignment to name its
annotator. It fails on a database that still holds a single-mode batch started
before Phase 5, so run this reset before upgrading such a database.

## Image assignments (Phase 5)

Annotation work is a direct, complete-image assignment: one annotator, one
image. Opening an assignment claims nothing, so every annotator in a consensus
group works the same image independently. Decisions are recorded in
[phase_5.md](phases/phase_5.md#decisões).

| Method | Endpoint | Who | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/projects/{project_id}/assignments` | assignee | The caller's own queue, with `purpose`/`state` filters and own counts |
| `GET` | `/api/v1/projects/{project_id}/assignments/{assignment_id}` | assignee | Image metadata, a signed image URL, and the current objects |
| `PUT` | `/api/v1/projects/{project_id}/assignments/{assignment_id}/draft` | assignee | Save the draft; `version` must be current |
| `POST` | `/api/v1/projects/{project_id}/assignments/{assignment_id}/submit` | assignee | Immutable submission; send an `Idempotency-Key` |
| `GET` | `/api/v1/media/{media_id}/content` | signed link | Image bytes; the signature and expiry are the authorization |
| `GET` | `/api/v1/projects/{project_id}/batches/{batch_id}/assignments` | owner, manager | Every assignment of a batch, without content |
| `POST` | `/api/v1/projects/{project_id}/assignments/{assignment_id}/reopen` | owner, manager | Give submitted work back as a new revision |
| `POST` | `/api/v1/projects/{project_id}/assignments/{assignment_id}/reassign` | owner, manager | Move the image to another annotator |
| `POST` | `/api/v1/projects/{project_id}/batch-items/{item_id}/cancel` | owner, manager | Return an unresolved training image to the pool |

**Starting a batch.** A single-mode batch deals its images in turn to the
policy group, or to every owner, manager, and annotator when the group is
empty. The current all-group consensus assignment behavior is superseded before
Phase 6 by the [Phase 5.1 cohort and review-assignment revision](phases/phase_5.1.md):
a consensus batch selects and records an initial cohort for each image.

**Assignment lifecycle.** An assignment is `pending`, then `in_progress` after
its first draft save, then `submitted`. `reassigned` and `cancelled` are
terminal. A stale `version` returns `409 version_conflict`. A repeated submit
returns `409 assignment_already_submitted`, or the original response when it
reuses its `Idempotency-Key`. Only the assignee may read or write an
assignment; everyone else gets `403 assignment_not_owned`.

**Validation.** Drafts are checked for structure only. Submissions must also
meet the task and geometry rules, and a failure returns `422 invalid_document`
with one `{object_id, code}` per problem. Detection and segmentation may be
submitted empty; classification needs at least one class.

**Resolution.**

- In single mode the submission becomes version 1 of the image's
  `resolved_annotations` in the same transaction, and a batch whose every
  remaining image is resolved moves to `resolved`.
- In consensus mode the image becomes `awaiting_resolution` once every active
  assignment has submitted. The resolution itself is Phase 6.

**Blindness.** Batch routes are a manager view (`manage_annotation_policy`):
they name the group and count everyone's submissions. Annotators use their own
queue, which carries no peer information.

**Image links.** Each assignment detail carries a path to
`/api/v1/media/{media_id}/content`. The path is signed with
`DADA_JWT_SECRET_KEY` and valid for one hour; a tampered or expired link
returns `403 invalid_media_url`.

**Acquisition strategy.** `PATCH /api/v1/projects/{project_id}` accepts
`acquisition_strategy` on `split` projects, and records the change in the
audit log. A `single_batch` project returns
`422 acquisition_strategy_not_allowed`.
