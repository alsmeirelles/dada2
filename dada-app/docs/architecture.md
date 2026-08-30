# DADA App System Architecture

## Deployment boundary

The DADA App and DADA API are independent network services. The API will
normally run on GPU-capable infrastructure while annotators access the App from
ordinary workstations.

```text
Browser -> DADA App static web host -> DADA API -> database
                                      -> self-hosted persistent volume
                                      -> active-learning workers / GPU models
```

The browser communicates directly with the API over HTTPS. In the initial
self-hosted deployment, images, masks, and other large artifacts live on
configured host paths bind-mounted into the API/worker containers; the browser
accesses them only through API-controlled URLs. The storage boundary permits a
later migration to cloud object storage and short-lived signed URLs without
changing the App contract. The API remains the authority for users, projects,
membership, media metadata, annotations, leases, and iteration state. The App
may cache server data but must not become a second source of truth.

## Responsibilities

### App

- Let a user select a local dataset directory.
- Recursively discover and review supported image files.
- Upload bytes with progress, retry, resume, cancellation, and checksums.
- Render task-specific annotation tools.
- Acquire and renew annotation leases and recover from lost leases.
- Display active-learning queues, training progress, ETA, and statistics.
- Keep unsaved edits locally only as short-lived recovery data.

### API

- Authenticate and authorize every request and real-time connection.
- Own project, membership, class, media, annotation, and iteration records.
- Issue upload sessions and verify uploaded content.
- Allocate annotation work atomically and enforce leases.
- Normalize and validate annotation geometry.
- Coordinate active-learning selection and GPU work.
- Publish project events and signed artifact URLs.

## Configuration and networking

The compiled App receives public, non-secret settings at build/deployment time:

| Setting | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | Absolute API origin, without a trailing slash |
| `VITE_REALTIME_URL` | Optional WebSocket URL when it cannot be derived |
| `VITE_UPLOAD_CHUNK_BYTES` | Client upload chunk size, bounded by API policy |

Secrets must never be placed in `VITE_*` variables. The API allowlists the App
origins with CORS, supports `Authorization` and upload headers, and exposes the
headers needed for resumable uploads. HTTPS/WSS is mandatory outside local
development.

## Browser directory ingestion

Directory selection is a source-selection operation, not remote path sharing.
The App recursively walks files supplied by the browser and creates a manifest.

- Preserve each file's path relative to the selected root as metadata.
- Normalize separators to `/`; reject absolute paths and `..` traversal.
- Never transmit the selected root's absolute local path.
- Accept formats advertised by `GET /api/v1/capabilities`; initially JPEG, PNG,
  and WebP are recommended.
- Skip hidden files/directories and unsupported files by default and report
  them in the review screen.
- Identify a file by SHA-256 plus byte length, not filename alone.
- Treat equal content at multiple relative paths as a reviewable duplicate.
- Do not follow symbolic links supplied through drag-and-drop APIs.

Chrome and Firefox expose directory selection differently. The implementation
must use progressive enhancement: a directory picker when supported and an
`<input type="file" webkitdirectory multiple>` fallback. The manifest review
and upload behavior remains identical.

## Authentication and authorization

The existing API returns a bearer access token. The App sends it in the
`Authorization: Bearer` header. Access tokens should be short-lived; a refresh
token flow must be added before production. Refresh credentials should use a
Secure, HttpOnly, SameSite cookie when deployment topology permits it, or an
explicitly documented alternative. Project roles are `owner`, `manager`,
`annotator`, and `viewer`; global administration remains separate.

## Real-time behavior

REST controls durable state. A project-scoped WebSocket publishes hints that
state changed: media availability, lease changes, upload processing, iteration
transitions, training progress, and ETA. Events carry monotonically increasing
sequence numbers. After reconnect or a sequence gap, the App refetches REST
resources rather than treating events as durable history.

Polling with exponential backoff is the required fallback when WebSocket is
unavailable.

## Annotation coordinates

All persisted geometry uses original-image pixel coordinates, independent of
canvas zoom and device pixel ratio. Rectangle geometry is `[x, y, width,
height]`. Polygon rings are flat coordinate arrays `[x1, y1, x2, y2, ...]` with
at least three distinct points. Classification annotations contain class IDs
without geometry. The API validates bounds and may return normalized geometry.

## Reliability rules

- All mutating create/complete calls accept an `Idempotency-Key`.
- Editable resources carry a `version`; stale updates return `409 Conflict`.
- Upload chunks are retryable and independently acknowledged.
- A lease must be renewed before expiry; submission after expiry is rejected
  unless the API explicitly restores that lease to the same user.
- Client timestamps are informational. Server timestamps decide ordering and
  expiry.
- Structured errors use the contract in `api-contract.md` and include a trace
  ID for support.
