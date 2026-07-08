---
phase: "06-healthcare-domain-pack-full-surface-validation"
plan: "03"
subsystem: "cli/api"
status: complete
tags: ["cli", "api", "domain-pack", "fastapi", "typer", "iface-01", "iface-02", "domain-01"]
dependency_graph:
  requires:
    - "knowledge_lake.domains.loader.DomainLoader (06-01)"
    - "knowledge_lake.config.settings.DomainSettings (06-02)"
    - "knowledge_lake.pipeline.ingest.normalize_url"
    - "knowledge_lake.registry.repo.create_source / get_source_by_normalized_url"
  provides:
    - "klake init --domain <name> CLI command"
    - "klake index --collection <name> CLI command"
    - "GET /sources (list sources)"
    - "GET /sources/{source_id} (get source or 404)"
    - "GET /documents (list artifacts)"
    - "GET /documents/{artifact_id} (get artifact or 404)"
    - "GET /datasets (list datasets)"
    - "GET /datasets/{dataset_id} (get dataset or 404)"
    - "POST /domains/load (register domain pack sources)"
    - "GET /domains/{name}/sources (list sources.yaml entries)"
    - "api/schemas.py: SourceListItem, ArtifactOut, DatasetOut, DomainLoadRequest, DomainLoadResponse"
  affects:
    - "src/knowledge_lake/cli/app.py"
    - "src/knowledge_lake/api/app.py"
    - "src/knowledge_lake/api/schemas.py"
    - "tests/unit/test_cli_init_index.py"
    - "tests/integration/test_api_new_endpoints.py"
    - "tests/integration/test_domain_init.py"
tech_stack:
  added: []
  patterns:
    - "cmd_init uses URL dedup via get_source_by_normalized_url before create_source (idempotent)"
    - "_DOMAIN_NAME_RE at api/app.py module level for defence-in-depth path traversal guard"
    - "_register_domain_sources() shared helper (D-02: no behavior re-implementation between CLI and API)"
    - "domains_root parent resolution: if name == 'domains' use parent (handles default relative path)"
    - "domain name validated in Pydantic schema (DomainLoadRequest.pattern) AND in endpoint handler (defence-in-depth)"
key_files:
  created:
    - tests/unit/test_cli_init_index.py
    - tests/integration/test_api_new_endpoints.py
    - tests/integration/test_domain_init.py
  modified:
    - src/knowledge_lake/cli/app.py
    - src/knowledge_lake/api/app.py
    - src/knowledge_lake/api/schemas.py
decisions:
  - "domains_root parent resolution: settings.domain.domains_root defaults to 'domains' (the folder path), but DomainLoader.from_name() expects the project root containing domains/; resolved by checking if the resolved path name is 'domains' and using .parent"
  - "_register_domain_sources() helper shared between CLI cmd_init and POST /domains/load (D-02 compliance — no behavior duplication)"
  - "DomainLoadRequest uses Pydantic pattern validator AND endpoint re-validates against _DOMAIN_NAME_RE for defence-in-depth against T-06-08"
  - "cmd_index is a thin wrapper over reindex_collection() — 'index' is canonical IFACE-01 name, 'reindex' kept as power-user alias"
  - "list_sources_endpoint domain filter applied in Python (not DB JSON operator) for SQLite/Postgres DB-agnostic behaviour"
metrics:
  duration: "4 minutes"
  completed_date: "2026-07-07"
  tasks_completed: 3
  files_created: 3
  files_modified: 3
  tests_passing: 12
---

# Phase 06 Plan 03: CLI init/index Commands and 8 New API Endpoints Summary

**One-liner:** klake init --domain (bulk source registration) and klake index (reindex alias) CLI commands plus 8 additive REST endpoints completing the D-07 API surface gap audit

## What Was Built

### Task 1: Wave 0 Test Stubs

Three test files created with xfail stubs following the existing project test pattern:

- `tests/unit/test_cli_init_index.py` — 3 stubs (init command exists, init help, index help)
- `tests/integration/test_api_new_endpoints.py` — 8 stubs for all new API endpoints
- `tests/integration/test_domain_init.py` — 1 stub for DB registration after klake init

All 12 stubs collect without ImportError. All xpassed after Tasks 2 and 3.

### Task 2: CLI Commands in cli/app.py

**`klake init --domain <name>`:**
- Path traversal guard: domain name validated against `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$`
- Loads domain pack via `DomainLoader.from_name(domain, root=root)`
- domains_root parent resolution handles default `"domains"` relative path
- Iterates `loader.sources`, skips `ingest_type == "upload"` entries
- Registers crawl-type sources with URL dedup via `get_source_by_normalized_url`
- Catches `IntegrityError` for race-condition dedup safety
- Prints: `"Registered N sources from <domain> pack."`, optional dedup and upload lines
- Exits 1 on FileNotFoundError (domain pack not found)

**`klake index --collection <name>`:**
- Thin wrapper over `pipeline.index.reindex_collection()` — canonical IFACE-01 name
- `--collection` option defaulting to `"klake_chunks"` matching `cmd_reindex`
- `cmd_reindex` kept intact as power-user alias

### Task 3: 8 New API Endpoints

**api/schemas.py additions:**
- `SourceListItem` — source registry view with domain extracted from config JSON
- `ArtifactOut` — artifact document view with all FOUND-06 fields
- `DatasetOut` — dataset view with row_count
- `DomainLoadRequest` — Pydantic pattern validates `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$` (T-06-08)
- `DomainLoadResponse` — loaded_count, skipped_count, upload_required_count

**api/app.py additions:**
- `GET /sources` — pagination (limit/offset) + optional domain filter (Python-side JSON filter for DB-agnosticism)
- `GET /sources/{source_id}` — `session.get()` primary key lookup, 404 on miss
- `GET /documents` — pagination + optional `artifact_type`/`source_id` ORM filters
- `GET /documents/{artifact_id}` — `session.get()`, 404 on miss
- `GET /datasets` — pagination via ORM select
- `GET /datasets/{dataset_id}` — `session.get()`, 404 on miss
- `POST /domains/load` — Pydantic validates name; defence-in-depth _DOMAIN_NAME_RE; delegates to `_register_domain_sources()` helper
- `GET /domains/{name}/sources` — validates name against `_DOMAIN_NAME_RE`; loads DomainLoader; returns `[s.model_dump() for s in loader.sources]`; 404 on FileNotFoundError

`_register_domain_sources()` shared helper implements D-02: no logic duplicated between CLI and API.

## Threat Mitigations Applied

| Threat ID | Mitigation |
|-----------|------------|
| T-06-08 | DomainLoadRequest.pattern validates name in Pydantic schema; POST /domains/load handler also checks _DOMAIN_NAME_RE (defence-in-depth) |
| T-06-09 | GET /domains/{name}/sources validates name against _DOMAIN_NAME_RE before any DomainLoader call |
| T-06-11 | All list/get endpoints use SQLAlchemy ORM select() with bound parameters — no raw SQL |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] domains_root path semantics mismatch**
- **Found during:** Task 2 (verification run showing `domains/domains/nosuchpack` path)
- **Issue:** `settings.domain.domains_root` defaults to `"domains"` (the domains folder path), but `DomainLoader.from_name(name, root=root)` expects a project root that *contains* a `domains/` subdirectory, constructing `root / "domains" / name`
- **Fix:** Added resolution logic: if `Path(domains_root).resolve().name == "domains"`, use the parent as the loader root; otherwise use the resolved path directly
- **Files modified:** `src/knowledge_lake/cli/app.py` (cmd_init), `src/knowledge_lake/api/app.py` (load_domain_endpoint, list_domain_sources_endpoint, _register_domain_sources helper)
- **Commit:** cb1c972, 1ccefc6

## Known Stubs

None — all implementations are wired. The test stubs in test_api_new_endpoints.py and test_domain_init.py require a live PostgreSQL/MinIO/Qdrant compose stack to run (marked `@pytest.mark.integration`). They are Wave 0 xfail stubs designed to flip to xpass once verified against the live stack.

## Threat Flags

None — no new network endpoints beyond the 8 planned. All 8 endpoints were in the pre-approved threat model in PLAN.md.

## Self-Check: PASSED

All created files verified to exist on disk. All 3 task commits found in git log.
