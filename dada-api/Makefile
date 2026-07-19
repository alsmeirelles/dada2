SHELL := /usr/bin/env bash
.SHELLFLAGS := -e -o pipefail -c

ifneq (,$(wildcard .env))
include .env
export
endif

DADA_POSTGRES_CONTAINER_NAME ?= dada-postgres
DADA_POSTGRES_IMAGE ?= postgres:16-alpine
DADA_POSTGRES_HOST ?= localhost
DADA_POSTGRES_HOST_PORT ?= 5432
DADA_POSTGRES_CONTAINER_PORT ?= 5432
DADA_POSTGRES_USER ?= dada
DADA_POSTGRES_PASSWORD ?= dada
DADA_POSTGRES_DB ?= dada
DADA_API_HOST ?= 0.0.0.0
DADA_API_PORT ?= 8000

DADA_UV_CACHE_DIR ?=
ifneq ($(strip $(DADA_UV_CACHE_DIR)),)
override UV_CACHE_DIR := $(DADA_UV_CACHE_DIR)
export UV_CACHE_DIR
endif

.DEFAULT_GOAL := help

.PHONY: help
help:
	@printf '%s\n' 'Local targets:'
	@printf '  %-16s %s\n' 'sync' 'Install runtime dependencies with uv.'
	@printf '  %-16s %s\n' 'sync-dev' 'Install runtime and development dependencies with uv.'
	@printf '  %-16s %s\n' 'db-up' 'Start or reuse the local PostgreSQL Docker container.'
	@printf '  %-16s %s\n' 'db-init' 'Ensure PostgreSQL is running, create tables, and seed configured admin.'
	@printf '  %-16s %s\n' 'db-recreate' 'Remove and recreate the local PostgreSQL container. Requires CONFIRM=1.'
	@printf '  %-16s %s\n' 'run' 'Run the API locally with uvicorn.'
	@printf '  %-16s %s\n' 'clean' 'Remove local Python and tool caches.'
	@printf '%s\n' ''
	@printf '%s\n' 'Check targets:'
	@printf '  %-16s %s\n' 'lint' 'Run Ruff lint checks.'
	@printf '  %-16s %s\n' 'ruff' 'Alias for lint.'
	@printf '  %-16s %s\n' 'pytest' 'Run the pytest suite.'
	@printf '  %-16s %s\n' 'test' 'Run lint and pytest.'
	@printf '%s\n' ''
	@printf '%s\n' 'CI targets:'
	@printf '  %-16s %s\n' 'ci-sync' 'Install locked CI dependencies without local services.'
	@printf '  %-16s %s\n' 'ci-lint' 'Run CI lint checks.'
	@printf '  %-16s %s\n' 'ci-test' 'Run CI tests.'
	@printf '  %-16s %s\n' 'ci' 'Run the full CI check sequence.'

.PHONY: sync
sync:
	uv sync

.PHONY: sync-dev
sync-dev:
	uv sync --extra dev

.PHONY: ci-sync
ci-sync:
	uv sync --extra dev --frozen

.PHONY: lint ruff
lint ruff:
	uv run ruff check dada_api

.PHONY: ci-lint
ci-lint: lint

.PHONY: pytest
pytest:
	uv run pytest

.PHONY: ci-test
ci-test: pytest

.PHONY: test
test: lint pytest

.PHONY: ci
ci: ci-sync ci-lint ci-test

.PHONY: db-up
db-up:
	@if docker ps --format '{{.Names}}' | grep -Fxq '$(DADA_POSTGRES_CONTAINER_NAME)'; then \
		printf 'PostgreSQL container "%s" is already running.\n' '$(DADA_POSTGRES_CONTAINER_NAME)'; \
	elif docker ps -a --format '{{.Names}}' | grep -Fxq '$(DADA_POSTGRES_CONTAINER_NAME)'; then \
		printf 'Starting existing PostgreSQL container "%s".\n' '$(DADA_POSTGRES_CONTAINER_NAME)'; \
		docker start '$(DADA_POSTGRES_CONTAINER_NAME)' >/dev/null; \
	else \
		printf 'Creating PostgreSQL container "%s".\n' '$(DADA_POSTGRES_CONTAINER_NAME)'; \
		POSTGRES_USER="$${DADA_POSTGRES_USER}" \
		POSTGRES_PASSWORD="$${DADA_POSTGRES_PASSWORD}" \
		POSTGRES_DB="$${DADA_POSTGRES_DB}" \
		docker run \
			--name '$(DADA_POSTGRES_CONTAINER_NAME)' \
			--env POSTGRES_USER \
			--env POSTGRES_PASSWORD \
			--env POSTGRES_DB \
			-p '$(DADA_POSTGRES_HOST_PORT):$(DADA_POSTGRES_CONTAINER_PORT)' \
			-d '$(DADA_POSTGRES_IMAGE)' >/dev/null; \
	fi
	@printf 'Waiting for PostgreSQL readiness...\n'
	@until docker exec '$(DADA_POSTGRES_CONTAINER_NAME)' pg_isready \
		-U '$(DADA_POSTGRES_USER)' \
		-d '$(DADA_POSTGRES_DB)' >/dev/null 2>&1; do \
		sleep 1; \
	done
	@printf 'PostgreSQL is ready.\n'

.PHONY: db-init
db-init: db-up
	@if [[ -z "$${DADA_SEED_ADMIN_USERNAME:-}" || -z "$${DADA_SEED_ADMIN_PASSWORD:-}" ]]; then \
		printf '%s\n' 'No seed admin is configured. Set DADA_SEED_ADMIN_USERNAME and DADA_SEED_ADMIN_PASSWORD in .env or the runtime environment.'; \
	else \
		printf 'Configured seed admin: %s\n' "$${DADA_SEED_ADMIN_USERNAME}"; \
	fi
	@if [[ -z "$${DADA_SEED_SERVICE_USERNAME:-}" || -z "$${DADA_SEED_SERVICE_PASSWORD:-}" ]]; then \
		printf '%s\n' 'No service command user is configured. Set DADA_SEED_SERVICE_USERNAME and DADA_SEED_SERVICE_PASSWORD to seed it.'; \
	else \
		printf 'Configured service command user: %s\n' "$${DADA_SEED_SERVICE_USERNAME}"; \
	fi
	uv run python -m dada_api.db.init_db

.PHONY: db-recreate
db-recreate:
	@if [[ "$(CONFIRM)" != "1" ]]; then \
		printf '%s\n' 'This removes the local PostgreSQL container and its data. Rerun with CONFIRM=1 to continue.'; \
		exit 1; \
	fi
	@if docker ps -a --format '{{.Names}}' | grep -Fxq '$(DADA_POSTGRES_CONTAINER_NAME)'; then \
		docker rm -f '$(DADA_POSTGRES_CONTAINER_NAME)' >/dev/null; \
	fi
	$(MAKE) db-up

.PHONY: run
run: db-init
	uv run uvicorn dada_api.main:app --host '$(DADA_API_HOST)' --port '$(DADA_API_PORT)' --reload

.PHONY: clean
clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type d -name .ruff_cache -prune -exec rm -rf {} +
	find . -type f -name '*.py[co]' -delete
