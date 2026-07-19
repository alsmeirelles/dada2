# Testing and Browser Support

The App test suite and API test suite are independent quality gates. The API
implementation sequence and phase exit criteria are defined in
[api-implementation-plan.md](../../dada-api/docs/api-implementation-plan.md).

## Automated gates

Every change must pass:

```bash
npm run lint
npm test
npm run build
```

Linting includes TypeScript, React hooks, Fast Refresh, and JSX accessibility
rules. Unit tests cover environment validation, directory ingestion, recovery
snapshots, annotation geometry, viewport transforms, real-time reconnection,
and shared UI behavior.

## Supported browsers

The supported desktop targets are the two most recent stable versions of
Google Chrome and Mozilla Firefox. Before a release, verify both browsers with
the same remote API deployment:

1. Login, token expiry, logout, and protected-route redirects.
2. Recursive directory selection, including nested paths and rejected files.
3. Interrupted/resumed uploads and offline recovery messaging.
4. Classification, boxes, polygons, zoom/pan, shortcuts, and autosave.
5. Two simultaneous annotators competing for the same queue item.
6. WebSocket disconnection, polling fallback, reconnect, and sequence gaps.
7. Iteration closure, training progress, ETA, failures, and statistics.
8. Keyboard-only navigation at 200% zoom with reduced motion enabled.

Firefox uses the directory-input fallback rather than relying on the File
System Access API. Both paths must produce the same relative manifest.

## Recovery tests

While editing, simulate offline mode or terminate the tab before autosave. On
reopening the same image in the same tab, the App should restore the 24-hour
session snapshot without overwriting a newer API version. No recovery snapshot
contains tokens, image bytes, or absolute local paths.

## API quality gates

Every API change should pass formatting and static analysis, unit tests,
PostgreSQL/object-storage integration tests, migration verification, HTTP
contract tests, and an OpenAPI compatibility check. The API repository should
provide one command that runs this complete local gate.

Tests must use production-equivalent PostgreSQL behavior rather than replacing
transactions with an in-memory database. Object upload integration tests may
use a local S3-compatible service. Until the concrete active-learning package
is integrated, all learning work uses a deterministic adapter; GPU tests are
outside the current implementation phases.

The minimum API regression matrix includes:

1. Authentication expiry, refresh rotation, replay prevention, logout, and all
   project role/action combinations.
2. Manifest path normalization, limits, media inspection, checksum failures,
   resumed chunks, duplicate completion, and cancellation.
3. Project and iteration transition validation, immutable test splits, and
   reproducible selection metadata.
4. Concurrent lease acquisition, renewal/expiry races, stale annotation
   versions, duplicate submissions, and automatic iteration closure.
5. Worker retry, duplicate results, timeout/failure recovery, ETA, metrics, and
   assisted-segmentation lease authorization.
6. Event-ticket expiry/replay, project isolation, monotonic sequences,
   reconnect, and REST reconciliation after a sequence gap.

Contract tests must assert response schemas as well as status codes, including
the common error envelope, `trace_id`, `Retry-After`, pagination cursors,
idempotency behavior, and required CORS/exposed upload headers.

## App-to-API release suite

Before a coordinated release, run the browser scenarios above against the
candidate API deployment with no request mocking. Use two independent user
sessions for lease contention. Include at least one interrupted upload across
an API process restart and one iteration completed through the fake or staging
worker. The released App's expected OpenAPI version must be recorded with the
test result.
