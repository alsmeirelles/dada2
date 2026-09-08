# DADA App / API v1 Contract

This document defines the contract required by the App. The API's generated
OpenAPI document is ultimately authoritative; CI should generate TypeScript
types from it and fail when incompatible changes are introduced.

All routes are relative to `VITE_API_BASE_URL`. Identifiers are opaque UUID
strings. JSON fields use `snake_case`, timestamps use UTC RFC 3339, and omitted
optional fields differ from explicit `null`.

## Common conventions

List endpoints use cursor pagination:

```json
{ "items": [], "next_cursor": null }
```

Errors use one envelope regardless of status code:

```json
{
  "error": {
    "code": "lease_expired",
    "message": "The annotation lease has expired.",
    "details": {},
    "trace_id": "opaque-trace-id"
  }
}
```

Expected statuses include `400` invalid request, `401` unauthenticated, `403`
forbidden, `404` missing, `409` state/version conflict, `413` upload too large,
`422` semantic validation failure, `429` throttled, and `503` temporarily
unavailable. A `429` or `503` should include `Retry-After` where meaningful.

## Capability and authentication endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Process health; already implemented |
| `GET` | `/api/v1/capabilities` | Formats, limits, chunk policy, task/tool support |
| `POST` | `/api/v1/auth/token` | Log in; already implemented |
| `POST` | `/api/v1/auth/refresh` | Rotate access credentials |
| `POST` | `/api/v1/auth/logout` | Revoke the refresh session |
| `GET` | `/api/v1/auth/me` | Current user; already implemented |

The capability response must include `supported_image_media_types`,
`max_file_bytes`, `max_project_files`, `upload_chunk_bytes`,
`supported_task_types`, and `realtime_transport`.

## User administration and credentials — Phase 4

Global user administration is distinct from project membership. All `/users`
routes require `is_administrator=true`; project owner and manager roles do not
grant access. The authenticated self-service password route is available to
every active user.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/users` | Cursor-paginated administrator user list; supports optional active-state filtering |
| `POST` | `/api/v1/users` | Create an account |
| `GET` | `/api/v1/users/{user_id}` | Read one account for editing |
| `PATCH` | `/api/v1/users/{user_id}` | Versioned administrator update of profile/access fields |
| `POST` | `/api/v1/users/{user_id}/reset-password` | Administrator password reset |
| `DELETE` | `/api/v1/users/{user_id}` | Terminal administrator account removal |
| `POST` | `/api/v1/auth/me/password` | Authenticated user's password change |

```ts
type UserRead = {
  id: string
  username: string // immutable after creation
  display_name: string
  is_active: boolean
  is_administrator: boolean
  version: number
  created_at: string
}

type UserCreate = {
  username: string
  display_name: string
  password: string
  is_active?: boolean // defaults to true
  is_administrator?: boolean // defaults to false
}

type UserUpdate = {
  version: number
  display_name?: string
  is_active?: boolean
  is_administrator?: boolean
}

type AdministratorPasswordReset = { new_password: string }
type PasswordChange = { current_password: string; new_password: string }
```

Passwords must contain 8–128 characters. They are write-only: neither API nor
App responses, logs, trace data, local storage, query cache, recovery data, or
error messages may contain them. Password reset/change, account deactivation,
and removal revoke the target's refresh sessions.

`DELETE` is permanent and returns `204`. Its `If-Match` header carries the bare
expected version, with surrounding quotes tolerated; a missing or unreadable
header returns `400 invalid_if_match`. It returns `409 user_in_use` while the
user owns a project or has retained domain/audit references; set
`is_active=false` to revoke access without deleting those records. The API also
returns `409 last_active_administrator` when an action would remove the final
active administrator, `409 self_administration_change` when an administrator
tries to remove their own access, `409 version_conflict` for stale updates,
`409 username_taken` for duplicate creation, and `400 current_password_incorrect`
when self-service verification fails.

`last_active_administrator` is reported in preference to
`self_administration_change` when both apply, so the sole administrator of an
installation is told what actually blocks the change.

## Project resources

`Project` contains:

```json
{
  "id": "uuid",
  "name": "Road defects",
  "description": null,
  "task_type": "detection",
  "status": "draft",
  "owner_id": "uuid",
  "initial_training_size": 100,
  "test_set_size": 50,
  "iteration_batch_size": 25,
  "version": 1,
  "created_at": "2026-07-18T12:00:00Z",
  "updated_at": "2026-07-18T12:00:00Z"
}
```

`task_type` is `classification`, `detection`, or `segmentation`. Project status
transitions are:

```text
draft -> ingesting -> ready -> active <-> training -> completed
                           \-> failed (recoverable through an explicit action)
```

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET/POST` | `/api/v1/projects` | List or create projects |
| `GET/PATCH` | `/api/v1/projects/{project_id}` | Read or versioned update |
| `POST` | `/api/v1/projects/{project_id}/activate` | Freeze setup and initialize splits |
| `GET/POST/PATCH/DELETE` | `/api/v1/projects/{project_id}/classes[/{class_id}]` | Ordered classes and colors |
| `GET/POST` | `/api/v1/projects/{project_id}/members` | List or invite members |
| `PATCH/DELETE` | `/api/v1/projects/{project_id}/members/{user_id}` | Change role or remove member |

Classes contain `id`, `name`, `color` as `#RRGGBB`, `display_order`, and
`version`. Class names are unique within a project.

## Recursive dataset ingestion

The App first builds a local manifest and then creates an upload session:

```json
{
  "files": [
    {
      "client_file_id": "local-opaque-id",
      "relative_path": "camera-a/day-01/frame-0001.jpg",
      "file_name": "frame-0001.jpg",
      "media_type": "image/jpeg",
      "size_bytes": 481239,
      "sha256": "lowercase-hex"
    }
  ]
}
```

The response reports each item as `upload_required`, `already_present`, or
`rejected`, with a stable `reason` when rejected, and the per-file progress a
client needs to resume. The upload routes are the fixed paths in the table
below. The initial self-hosted deployment stores bytes on persistent server
volumes; a future cloud deployment may introduce signed object-storage URLs
without exposing a client-local path.

```json
{
  "id": "uuid",
  "status": "pending",
  "expires_at": "2026-09-02T14:00:00Z",
  "error": null,
  "items": [
    {
      "client_file_id": "local-opaque-id",
      "disposition": "upload_required",
      "reason": null,
      "size_bytes": 481239,
      "received_bytes": 0
    }
  ]
}
```

Rejection reasons are `invalid_relative_path`, `unsupported_media_type`, and
`file_too_large`. Deduplication is scoped to one project: identical content is
stored once and may be referenced by more than one relative path.

Upload status is `pending`, `uploading`, `processing`, `completed`, or `failed`.
The App must wait for `completed` before activating the project. A failed
session includes a structured `error` and remains queryable for recovery.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/projects/{project_id}/uploads` | Create session from manifest |
| `GET` | `/api/v1/uploads/{upload_id}` | Resume/status and per-file progress |
| `PUT` | `/api/v1/uploads/{upload_id}/files/{client_file_id}` | Upload/acknowledge a chunk |
| `POST` | `/api/v1/uploads/{upload_id}/complete` | Verify checksums and start processing |
| `DELETE` | `/api/v1/uploads/{upload_id}` | Cancel an incomplete session |
| `GET` | `/api/v1/projects/{project_id}/media` | Paginated media inventory |

Chunk requests carry `Upload-Offset` and `X-Chunk-SHA256`. The API acknowledges
the next expected offset in both the `Upload-Offset` response header and the
response body, so an interrupted upload resumes mid-file rather than restarting
it. Session expiry is advertised as `upload_session_ttl_hours` in
`/api/v1/capabilities`. Completing a session is idempotent.

Cancelling a session and deleting a project both purge immediately and
permanently; no restore window exists. `DELETE /api/v1/projects/{project_id}` is
owner-only and returns `204`.

## Annotation batches — Phase 4

Activating a project freezes its train/test split and opens two batches: `test`
over the whole held-out half, and `initial_training` over a random selection
from the rest. The project moves from `draft` to `active` in the same
transaction, so an active project always has its batches.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/projects/{project_id}/batches` | Cursor-paginated batch inventory |
| `GET` | `/api/v1/projects/{project_id}/batches/{batch_id}` | Policy snapshot and progress |
| `PATCH` | `/api/v1/projects/{project_id}/batches/{batch_id}` | Replace the policy while `preparing` |
| `POST` | `/api/v1/projects/{project_id}/batches/{batch_id}/start` | Freeze it and generate assignments |

```ts
type BatchPurpose = 'initial_training' | 'test' | 'acquisition'
type BatchStatus =
  | 'preparing' | 'annotating' | 'resolving'
  | 'review_required' | 'resolved' | 'closed' | 'failed'

type Batch = {
  id: string
  project_id: string
  purpose: BatchPurpose
  status: BatchStatus
  mode: 'single' | 'consensus'
  annotator_ids: string[]
  resolver: string | null
  resolver_version: string | null
  parameters: Record<string, number | string | boolean>
  review_thresholds: Record<string, number>
  source_policy_version: number
  selection_strategy: string
  selection_seed: number
  selection_input_fingerprint: string
  requested_size: number
  total_items: number         // images in the batch
  total_assignments: number   // items x annotators, 0 before start
  submitted_assignments: number
  started_at: string | null
  created_at: string
  updated_at: string
}
```

A batch holds a **copy** of the project's default policy, not a reference. The
UI must not suggest that editing the project default changes an active batch.
The copy is editable only while the batch is `preparing`; afterwards `PATCH`
returns `409 policy_locked` and a repeated start returns
`409 batch_already_started`. The `PATCH` body has no `version`: batch status,
not an optimistic version, is what decides whether the policy may change.

Show `total_items` and `total_assignments` as distinct numbers. In consensus
mode one image carries one assignment per configured annotator, so they never
coincide.

Acquisition batches, iteration records, and the routes below arrive with later
phases; `GET /iterations` and `GET /statistics` are not implemented yet.

## Iterations and splits

The API creates immutable train/test split membership when a project is
activated. The test set is annotated randomly as specified by the product
requirements but excluded from active-learning acquisition. Every iteration
records its selection strategy and model/run identifiers for reproducibility.

Iteration states are:

```text
preparing -> annotating -> closing -> training -> ready
                |                         |
                +-------------------------+-> failed
```

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/projects/{project_id}/iterations` | History and current iteration |
| `GET` | `/api/v1/projects/{project_id}/iterations/{iteration_id}` | Counts, status, ETA, metrics |
| `POST` | `/api/v1/projects/{project_id}/iterations/{iteration_id}/close` | Idempotent completion check |
| `GET` | `/api/v1/projects/{project_id}/statistics` | Project/iteration chart data |

The server normally closes an iteration automatically after every selected
item is complete. The explicit close operation lets clients safely reconcile a
missed event. It returns `409 iteration_incomplete` with remaining counts when
work is outstanding.

## Annotation queue and leases

The existing global `/api/v1/queue/next` placeholder is superseded by scoped
endpoints:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/projects/{project_id}/iterations/{iteration_id}/queue` | Available, leased, and completed counts/items |
| `POST` | `/api/v1/projects/{project_id}/iterations/{iteration_id}/leases` | Atomically acquire a specific or next item |
| `POST` | `/api/v1/leases/{lease_id}/renew` | Extend an owned lease |
| `DELETE` | `/api/v1/leases/{lease_id}` | Release without completion |
| `GET` | `/api/v1/media/{media_id}/annotations` | Current annotation document and version |
| `PUT` | `/api/v1/leases/{lease_id}/annotations` | Save a versioned draft |
| `POST` | `/api/v1/leases/{lease_id}/complete` | Validate and submit final annotations |

Lease acquisition is atomic. A successful response contains `lease_id`, media
metadata, a signed `image_url`, `expires_at`, `renew_after`, annotation version,
and any existing draft. Other users see that item as leased but receive no
sensitive user data beyond display information permitted by the project.

`renew_after` is the number of seconds after acquisition or the last renewal
before the App should renew. Queue responses contain `items`, status counts,
and `next_cursor`; each item contains `media_id`, `relative_path`, `status`,
dimensions, an optional thumbnail URL, and limited lease display information.
The iteration-list response includes the nullable `current_iteration` object.

Draft saving does not release the lease. Completion is idempotent and does.
Disconnecting does not immediately release a lease; expiry prevents two users
from editing during transient network loss. Owners/managers may explicitly
revoke abandoned leases through a separately authorized operation.

## Annotation documents

```json
{
  "media_id": "uuid",
  "task_type": "detection",
  "version": 3,
  "objects": [
    {
      "id": "client-stable-uuid",
      "class_id": "uuid",
      "geometry": {
        "type": "rectangle",
        "coordinates": [120.5, 90.0, 240.0, 180.0]
      },
      "attributes": {}
    }
  ]
}
```

For classification, objects use `geometry: null`. For segmentation, geometry
type is `polygon` and `coordinates` is an array of rings. The API response may
include normalized geometry and always returns the new version.

## Assisted segmentation

The existing `/api/v1/inference/sam-predict` route should additionally require
`project_id`, `lease_id`, and optional `embedding_cache_key`. The API verifies
that the user owns an active lease for the image. Coordinates follow the same
original-image pixel convention as stored annotations.

## Real-time endpoint

`GET /api/v1/projects/{project_id}/events` upgrades to WebSocket. Authentication
uses a short-lived WebSocket ticket obtained through an authenticated REST
request, avoiding access tokens in URLs.

The App obtains that ticket with
`POST /api/v1/projects/{project_id}/events/ticket`. The response contains
`ticket`, `expires_at`, and an optional deployment-specific `websocket_url`.
The single-use ticket may be placed in the WebSocket connection URL; bearer
access tokens must not be placed there.

```json
{
  "sequence": 418,
  "type": "lease.acquired",
  "project_id": "uuid",
  "occurred_at": "2026-07-18T12:00:00Z",
  "data": { "iteration_id": "uuid", "media_id": "uuid" }
}
```

Event types initially include `upload.progress`, `upload.completed`,
`lease.acquired`, `lease.released`, `annotation.completed`,
`iteration.status_changed`, `training.progress`, and `training.eta_updated`.
Events are invalidation signals; clients refetch authoritative resources.
