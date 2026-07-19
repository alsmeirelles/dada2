# DADA API

Python API for the DADA annotation App and active-learning system. The service
is developed independently from the browser App while sharing the versioned v1
contract.

Phase 0 provides the FastAPI application foundation, PostgreSQL/Alembic
persistence boundary, Redis connectivity, health/readiness probes, structured
errors and tracing, CORS, durable idempotency, capability discovery, and the
generated OpenAPI artifact. Active-learning algorithms are deferred behind a
later worker adapter.

See:

- [API implementation plan](docs/api-implementation-plan.md)
- [Development and local operation](docs/development.md)
- [App/API contract](../dada-app/docs/api-contract.md)

Quick start:

```bash
cp .env.example .env
make sync-dev
make infra-up
make migrate
make run
```

The default API URL is `http://localhost:8000`; liveness and readiness are
available at `/health` and `/ready`.
