# DADA API

Python API for the DADA annotation App and active-learning system. The service
is developed independently from the browser App while sharing the versioned v1
contract.

The service includes the FastAPI application foundation, PostgreSQL/Alembic
persistence, Redis connectivity, identity and project authorization, dataset
ingestion, annotation batches, and the consensus-resolution engine.

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
make bootstrap-admin
```

Then run:

```bash
make run                              # terminal 1: the API
make consensus                        # terminal 2: relay and both worker queues
```

The consensus target supervises the outbox relay plus the standard and mask
worker queues; press `Ctrl-C` to stop all three. On Windows, use `make
consensus CELERY_POOL=solo`.

To discard an incompatible local development database and migrate a fresh one,
run `make rebuild`, then rerun `make bootstrap-admin`. The rebuild command
deletes the local PostgreSQL Compose volume and refuses to run unless
`DADA_ENVIRONMENT=development`.

The default API URL is `http://localhost:8000`; liveness and readiness are
available at `/health` and `/ready`.

A migrated database has no users and no route that can create the first one, so
`make bootstrap-admin` is required before the first login. It is idempotent and
safe to rerun.
