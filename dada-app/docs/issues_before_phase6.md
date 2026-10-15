# Phase 6 issues

| ID | Pending solution | Required documented outcome |
| --- | --- | --- |
| `I6-01` | Data selection during project creation has wrong count | Explicit issue addressing statement confirming resolution in this document |
| `I6-02` | A corrected submission after a validation error is refused as an idempotency conflict | Explicit issue addressing statement confirming resolution in this document |

## I6-01

When selecting images in the project creation phase, the pending images count initially displayed was increasing while images
were being added from multiple folders. This kept the project from being create as the minimum count was never reached.

## I6-02

Found while preparing Phase 6, by reading the App submit calls next to the API
idempotency middleware.

The App keyed an assignment submission as `submit:{assignment_id}:{version}`
and a candidate review as `review:{assignment_id}:{version}`. The API stores
every response below 500 under its key, including a `422 invalid_document`.
When an annotator corrected a rejected document and submitted again, the
version had not changed, so the same key arrived with a different body and the
API answered `409 idempotency_conflict`. The submission stayed blocked until
something else changed the version.
