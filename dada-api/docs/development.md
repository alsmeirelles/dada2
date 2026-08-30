# DADA API Development

This guide covers the Phase 0 service foundation, the Phase 1 identity, session,
and authorization layer, and the Phase 2 project setup, membership, and
annotation policy. Concrete active-learning and GPU workers are intentionally
not part of these phases.

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
chunk size, JWT/cursor signing secrets, refresh credential lifetime and cookie
policy, and the bootstrap administrator identity. `VITE_*` settings belong to
the App and must not be copied into the API environment.

The official `postgres:17-alpine` and `redis:7.4-alpine` images are used for
local infrastructure. Redis is disposable; PostgreSQL is authoritative.

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
is missing. Freezing the dataset split and opening the first annotation batch
belong to Phase 4, and media does not exist before Phase 3, so every activation
attempt currently reports missing media.

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

## Current placeholders

Existing prototype queue and inference routes remain so later phases can evolve
them without losing behavior.

`GET /api/v1/capabilities` is served from validated settings. Phase 3 will add
limits for the configured self-hosted persistent-volume store; the storage
choice is settled, but the ingestion implementation has not yet been added.
