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
`rejected`, and supplies either resumable API URLs or signed object-storage
URLs. It must not require the API to access a client-local path.

```json
{
  "id": "uuid",
  "status": "pending",
  "items": [
    {
      "client_file_id": "local-opaque-id",
      "disposition": "upload_required"
    }
  ]
}
```

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

Chunk requests include an upload offset and checksum. The API acknowledges the
next offset. Session expiry, chunk limits, and rejected-file reasons are
explicit. Completing a session is idempotent.

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
