SHELL := /usr/bin/env bash
.SHELLFLAGS := -e -o pipefail -c

ifneq (,$(wildcard .env))
include .env
export
endif

DADA_API_HOST ?= 0.0.0.0
DADA_API_PORT ?= 8000
UV_CACHE_DIR ?= .uv-cache
export UV_CACHE_DIR

.DEFAULT_GOAL := help

.PHONY: help
help:
	@printf '%s\n' \
	  'sync             Install locked runtime dependencies.' \
	  'sync-dev         Install locked runtime and development dependencies.' \
	  'infra-up         Start PostgreSQL and Redis and wait for health.' \
	  'infra-down       Stop local infrastructure without deleting volumes.' \
	  'migrate          Upgrade the database explicitly to the migration head.' \
	  'migration-check  Fail if ORM metadata differs from migration head.' \
	  'bootstrap-admin  Create the initial administrator. Safe to rerun.' \
	  'run              Run the API; does not migrate or seed the database.' \
	  'openapi          Export the generated OpenAPI document.' \
	  'lint             Run Ruff lint and formatting checks.' \
	  'test             Run the pytest suite.' \
	  'check            Run all local quality gates.'

.PHONY: sync sync-dev
sync:
	uv sync --frozen

sync-dev:
	uv sync --extra dev --frozen

.PHONY: infra-up infra-down
infra-up:
	docker compose up -d --wait postgres redis

infra-down:
	docker compose down

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
