---
phase: 01-foundation-end-to-end-spike
plan: "01"
subsystem: foundation
tags: [walking-skeleton, compose-stack, pydantic-settings, pytest-infra, tdd]
status: complete

dependency_graph:
  requires: []
  provides:
    - knowledge_lake package (uv-managed, klake CLI entry point)
    - pydantic-settings config source (FOUND-02)
    - six-service compose stack (FOUND-01)
    - Wave 0 test infrastructure (pytest + conftest fixtures)
  affects:
    - All subsequent plans (use config/settings, test infra, compose stack)

tech_stack:
  added:
    - pydantic 2.13.4
    - pydantic-settings 2.14.2
    - sqlalchemy 2.0.51 + alembic 1.18.5 + psycopg[binary] 3.3.4
    - boto3 1.43.39
    - docling 2.108.0
    - sentence-transformers 5.6.0
    - qdrant-client 1.18.0
    - litellm 1.90.2
    - dagster 1.13.11 + dagster-webserver 1.13.11 + dagster-postgres 0.29.11
    - fastapi 0.139.0 + uvicorn 0.49.0
    - typer 0.24.2 (pinned >=0.12.5,<0.25.0; see deviations)
    - structlog 26.x + tenacity 9.1.4 + httpx 0.28.1 + xxhash 3.8.0 + orjson 3.11.9
    - dev: pytest 9.x + pytest-asyncio + pytest-cov + ruff + mypy
  patterns:
    - pydantic-settings with KLAKE_ prefix + __ nested delimiter + .env support
    - uv package management with lockfile
    - structlog configured at package import
    - Typer multi-command app with hidden status stub to force subcommand mode

key_files:
  created:
    - pyproject.toml (uv package, pinned deps, [project.scripts] klake entry, [tool.dagster] module)
    - uv.lock (fully resolved lockfile)
    - .gitignore (.env, data/ excluded; no secrets in git)
    - .env.example (KLAKE_* placeholders including AWS_BEDROCK_API_KEY)
    - Makefile (spike/up/down/test targets)
    - Dockerfile (python:3.12-slim + curl + uv sync)
    - docker-compose.yml (6 services + healthchecks + minio-init)
    - infra/litellm/config.yaml (cheap/strong/eval/embedding model aliases → Bedrock)
    - infra/postgres/init.sql (registry db + separate dagster_storage db)
    - infra/minio/README.md (immutability strategy documentation)
    - infra/qdrant/config.yaml (qdrant service config)
    - infra/dagster/dagster.yaml (dagster PostgreSQL run/event/schedule storage)
    - src/knowledge_lake/__init__.py (version + structlog init)
    - src/knowledge_lake/config/__init__.py
    - src/knowledge_lake/config/settings.py (Settings + StorageSettings + get_settings)
    - src/knowledge_lake/cli/__init__.py
    - src/knowledge_lake/cli/app.py (klake version command + hidden status stub)
    - src/knowledge_lake/api/__init__.py
    - src/knowledge_lake/api/app.py (FastAPI GET /health → 200)
    - src/knowledge_lake/dagster_defs/__init__.py
    - src/knowledge_lake/dagster_defs/definitions.py (minimal Definitions())
    - tests/__init__.py + tests/unit/__init__.py + tests/integration/__init__.py
    - tests/conftest.py (env-isolation autouse + settings fixture)
    - tests/unit/test_settings.py (17 TDD unit tests for FOUND-02)
    - tests/integration/test_compose_health.py (6 integration tests for FOUND-01)

decisions:
  - typer pinned <0.25.0 due to docling-core 2.85.0 compatibility (see deviations)
  - qdrant healthcheck uses bash TCP /dev/tcp (no curl/wget in qdrant:v1.13.6 image)
  - litellm healthcheck uses Python urllib (no curl in litellm image)
  - dagster services use venv binary paths (/app/.venv/bin/) + [tool.dagster] module discovery
  - dagster-postgres 0.29.11 added to runtime deps (version-matched to dagster 1.13.11)
  - LiteLLM config uses aws_bedrock_api_key (per user request — not access/secret key)
  - minio-init service bootstraps klake-data bucket with versioning + object-lock (FOUND-04 seam)

metrics:
  duration: "~59 minutes"
  completed: "2026-07-02"
  tasks_completed: 3
  files_created: 23
  tests_passing: 23
---

# Phase 01 Plan 01: Walking-Skeleton Foundation Summary

One-liner: uv-managed `knowledge-lake` package with typed pydantic-settings config, a fully-healthy six-service Docker Compose stack (`docker compose up` yields postgres/minio/qdrant/litellm/dagster/api all healthy), and Wave 0 pytest infrastructure that all later plans write against.

## What Was Built

### Task 1 — uv package scaffold + Wave 0 test infrastructure

- Initialized `knowledge-lake` package via `uv init --package` (import: `knowledge_lake`, CLI: `klake`)
- Added all pinned runtime deps from RESEARCH Standard Stack (see deviations for typer version change)
- Configured `[tool.pytest.ini_options]` (asyncio auto, testpaths=tests), ruff, mypy in pyproject.toml
- `[project.scripts] klake = "knowledge_lake.cli.app:app"` — `uv run klake version` returns `0.1.0` and exits 0
- Structured logging configured at package import via structlog
- `.env.example` with KLAKE_* placeholders only (no real secrets)
- Removed placeholder directories (configs/, services/, workspace/); data/ gitignored

### Task 2 — Typed pydantic-settings config source (FOUND-02, TDD)

- RED: 17 failing unit tests covering defaults, nested storage mapping, env precedence, get_settings()
- GREEN: `Settings(BaseSettings)` with `env_prefix="KLAKE_"`, `env_nested_delimiter="__"`, `.env` support
- `StorageSettings` nested model for S3-compatible storage config
- Plugin swap keys: `embedder=local | litellm`, `parser=docling`, `vectorstore=qdrant`
- `get_settings()` cached accessor — single typed source, no scattered `os.getenv()` calls
- All 17 unit tests green

### Task 3 — Six-service compose stack (FOUND-01)

- `docker-compose.yml` with postgres/minio/qdrant/litellm/dagster-webserver/dagster-daemon/api + healthchecks
- postgres 16-alpine: `pg_isready` healthcheck; init.sql creates separate `dagster_storage` DB
- minio: `mc ready local` healthcheck; minio-init service creates bucket with versioning + object-lock (FOUND-04 seam)
- qdrant v1.13.6: bash TCP healthcheck on /healthz (no curl in image)
- litellm: Python urllib healthcheck on /health/liveliness; boots healthy without Bedrock creds (A5 confirmed)
- dagster-webserver + daemon: curl healthcheck on /server_info; uses [tool.dagster] module discovery
- api: `GET /health` → `{"status":"ok"}` with curl healthcheck
- All 6 integration tests pass; all 23 tests pass total

## Acceptance Criteria Verification

| Criterion | Status |
|-----------|--------|
| FOUND-01: `docker compose up` yields all services healthy | PASS — verified with `docker compose ps` |
| FOUND-02: typed pydantic-settings with KLAKE_ prefix + nested delimiter | PASS — 17 unit tests green |
| `klake version` prints version and exits 0 | PASS |
| ruff passes on src/ | PASS |
| pytest collects 23 tests, 23 pass | PASS |
| .env gitignored; .env.example has only placeholders | PASS |
| configs/, services/, workspace/ removed; data/ gitignored | PASS |
| No hardcoded service URLs — all via env | PASS |
| GET /health returns 200 from api service | PASS |
| LiteLLM healthy without AWS creds | PASS |
| Dagster uses separate database from registry | PASS |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Typer 0.26.8 incompatible with docling 2.108.0**
- **Found during:** Task 1 (uv add dependency resolution)
- **Issue:** `docling 2.108.0` → `docling-slim[standard] 2.108.0` → `docling-core 2.85.0` → `typer<0.25.0`. The RESEARCH Standard Stack specified typer 0.26.8, but docling-core 2.85.0 requires typer<0.25.0.
- **Fix:** Changed typer pin to `>=0.12.5,<0.25.0`; uv resolved to 0.24.2. Typer 0.24.2 provides all needed functionality for Phase 1 CLI.
- **Files modified:** `pyproject.toml`
- **Commit:** 35a0203

**2. [Rule 1 - Bug] qdrant container has no curl/wget/nc**
- **Found during:** Task 3 (docker healthcheck)
- **Issue:** qdrant:v1.13.6 uses `dash` as `/bin/sh` (no `/dev/tcp`) and has no curl/wget/nc installed.
- **Fix:** Changed qdrant healthcheck to use `/usr/bin/bash -c "exec 3<>/dev/tcp/127.0.0.1/6333 ..."` (bash TCP socket).
- **Files modified:** `docker-compose.yml`
- **Commit:** 0102265

**3. [Rule 1 - Bug] litellm container has no curl**
- **Found during:** Task 3 (docker healthcheck)
- **Issue:** litellm image has Python venv but no curl.
- **Fix:** Changed healthcheck to use `/app/.venv/bin/python3 -c "import urllib.request; ..."`.
- **Files modified:** `docker-compose.yml`
- **Commit:** 0102265

**4. [Rule 2 - Missing] LiteLLM Bedrock API key format**
- **Found during:** Task 3 (user request during execution)
- **Issue:** Plan used AWS access/secret key; user requested Bedrock API key format.
- **Fix:** Updated `infra/litellm/config.yaml` to use `aws_bedrock_api_key: os.environ/AWS_BEDROCK_API_KEY`; updated `.env.example` with `AWS_BEDROCK_API_KEY` placeholder; updated `docker-compose.yml` to pass `AWS_BEDROCK_API_KEY`.
- **Files modified:** `infra/litellm/config.yaml`, `.env.example`, `docker-compose.yml`
- **Commit:** 0102265

**5. [Rule 1 - Bug] dagster-postgres missing from initial deps + dagster binary path**
- **Found during:** Task 3 (dagster container startup)
- **Issue 1:** dagster-postgres was not in pyproject.toml deps, so it wasn't in the built image.
- **Issue 2:** Dagster binaries are in `/app/.venv/bin/`, not on PATH.
- **Issue 3:** Dagster webserver requires `[tool.dagster]` in pyproject.toml to discover the code location.
- **Fix:** Added `dagster-postgres==0.29.11` to deps; updated compose command to use absolute venv paths; added `[tool.dagster] module_name` to pyproject.toml.
- **Commit:** 0102265

## Known Stubs

None — all components are functional (not stubbed). The API returns real JSON from FastAPI; the Dagster definitions expose a real (empty) Definitions() object; config loads real values.

## Threat Flags

None — no new security-relevant surface beyond what was planned. The infra/litellm/config.yaml uses `os.environ/` references (not hardcoded keys); .env is gitignored.

## Self-Check

PASSED
