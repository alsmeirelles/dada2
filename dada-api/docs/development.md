# DADA API Development

This guide covers the Phase 0 service foundation. Concrete active-learning and
GPU workers are intentionally not part of this phase.

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
make run
```

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

Settings use the `DADA_` prefix. Important Phase 0 values are documented in
`.env.example`: database and Redis URLs, CORS origins, trace/log settings,
capability limits, upload chunk size, and JWT/cursor signing secrets. `VITE_*`
settings belong to the App and must not be copied into the API environment.

The official `postgres:17-alpine` and `redis:7.4-alpine` images are used for
local infrastructure. Redis is disposable; PostgreSQL is authoritative.

## Current placeholders

Existing prototype authentication, user, queue, and inference routes remain so
later phases can evolve them without losing behavior. Project schemas and route
placeholders are present for OpenAPI generation; they return `501` until Phase
2. The default administrator bootstrap is implemented in Phase 1, not by API
startup or migration code.
