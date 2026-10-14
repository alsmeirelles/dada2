SHELL := /usr/bin/env bash
.SHELLFLAGS := -e -o pipefail -c

ifneq (,$(wildcard .env))
include .env
export
endif

DADA_API_HOST ?= 0.0.0.0
DADA_API_PORT ?= 8000
DADA_ENVIRONMENT ?= development
UV_CACHE_DIR ?= .uv-cache
CELERY_POOL ?= prefork
DADA_CONSENSUS_STANDARD_MEMORY_BYTES ?= 1073741824
DADA_CONSENSUS_MASK_MEMORY_BYTES ?= 4294967296
export UV_CACHE_DIR

.DEFAULT_GOAL := help

.PHONY: help
help:
	@printf '%s\n' \
	  'sync             Install locked runtime dependencies.' \
	  'sync-dev         Install locked runtime, development, and consensus dependencies.' \
	  'infra-up         Start PostgreSQL and Redis and wait for health.' \
	  'infra-down       Stop local infrastructure without deleting volumes.' \
	  'rebuild          Delete the local database volume, recreate it, and migrate.' \
	  'migrate          Upgrade the database explicitly to the migration head.' \
	  'migration-check  Fail if ORM metadata differs from migration head.' \
	  'bootstrap-admin  Create the initial administrator. Safe to rerun.' \
	  'run              Run the API; does not migrate or seed the database.' \
	  'relay            Run the consensus outbox relay.' \
	  'worker-standard  Run the classification and detection consensus worker.' \
	  'worker-mask      Run the segmentation consensus worker.' \
	  'openapi          Export the generated OpenAPI document.' \
	  'lint             Run Ruff lint and formatting checks.' \
	  'test             Run the pytest suite.' \
	  'check            Run all local quality gates.'

.PHONY: sync sync-dev
sync:
	uv sync --frozen

sync-dev:
	uv sync --extra dev --extra consensus --frozen

.PHONY: infra-up infra-down rebuild
infra-up:
	docker compose up -d --wait postgres redis

infra-down:
	docker compose down

rebuild:
	@if [[ '$(DADA_ENVIRONMENT)' != 'development' ]]; then \
		printf '%s\n' 'Refusing to rebuild: DADA_ENVIRONMENT must be development.' >&2; \
		exit 1; \
	fi
	docker compose down --volumes
	$(MAKE) infra-up
	$(MAKE) migrate

.PHONY: migrate migration-check
migrate:
	uv run alembic upgrade head

migration-check:
	uv run alembic check

.PHONY: bootstrap-admin
bootstrap-admin:
	uv run dada-api bootstrap-admin

.PHONY: run
run:
	uv run uvicorn dada_api.main:app --host '$(DADA_API_HOST)' --port '$(DADA_API_PORT)' --reload

.PHONY: relay worker-standard worker-mask
relay:
	uv run dada-api consensus-relay

worker-standard:
	uv run celery -A dada_api.workers.celery_app worker -Q consensus.standard -n 'standard@%h' --pool '$(CELERY_POOL)' -c 4 --max-memory-per-child $$(( $(DADA_CONSENSUS_STANDARD_MEMORY_BYTES) / 1024 ))

worker-mask:
	uv run celery -A dada_api.workers.celery_app worker -Q consensus.mask -n 'mask@%h' --pool '$(CELERY_POOL)' -c 1 --max-memory-per-child $$(( $(DADA_CONSENSUS_MASK_MEMORY_BYTES) / 1024 ))

.PHONY: openapi
openapi:
	uv run dada-api export-openapi --output openapi.json

.PHONY: lint test check
lint:
	uv run ruff check dada_api tests alembic
	uv run ruff format --check dada_api tests alembic

test:
	uv run pytest

check: lint test openapi
	git diff --exit-code -- openapi.json
