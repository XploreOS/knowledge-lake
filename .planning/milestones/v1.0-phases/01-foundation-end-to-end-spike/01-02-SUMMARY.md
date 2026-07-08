---
phase: 01-foundation-end-to-end-spike
plan: "02"
subsystem: registry
tags: [registry, alembic, uuidv7, lineage, postgresql, sqlalchemy, tdd]
status: complete

dependency_graph:
  requires:
    - plan 01 (pydantic-settings config, pytest infra, compose stack)
  provides:
    - knowledge_lake.ids (new_id helper — prefixed UUIDv7)
    - knowledge_lake.version (pipeline_version helper)
    - knowledge_lake.registry (SQLAlchemy models + repo + db)
    - Alembic migration 0001_core_schema (full core table set)
  affects:
    - Plan 03 (storage): get_artifact_by_hash is the dedup lookup for put_raw
    - Plan 05 (lineage): parent_artifact_id self-FK powers the recursive-CTE ancestry
    - All plans: every artifact creation stamps pipeline_version + new_id

tech_stack:
  added:
    - uuid-utils 0.16.2 (UUIDv7 generation on Python 3.12)
    - alembic 1.18.5 (already in deps; now configured and active)
  patterns:
    - Prefixed UUIDv7 IDs (src_/doc_/chk_/art_) via single uuid_utils import — one-line swap at Python 3.14
    - pipeline_version = importlib.metadata.version + git rev-parse --short HEAD; graceful pkg-only fallback
    - Unified self-referencing artifacts node table (not separate documents/chunks tables)
    - SQLAlchemy 2.0 declarative Mapped[] typed models
    - Alembic env.py reads DB URL from Settings with programmatic override for test isolation
    - ORM-only queries in repo.py (no raw SQL) for T-01-03 SQL injection prevention

key_files:
  created:
    - src/knowledge_lake/ids.py (new_id helper — prefixed UUIDv7)
    - src/knowledge_lake/version.py (pipeline_version helper)
    - src/knowledge_lake/registry/__init__.py
    - src/knowledge_lake/registry/models.py (Source, Artifact, LineageEvent, Job, Dataset)
    - src/knowledge_lake/registry/db.py (engine/session from Settings.database_url)
    - src/knowledge_lake/registry/repo.py (create_source, create_*_artifact, get_artifact_by_hash, get_artifact, list_children)
    - src/knowledge_lake/registry/alembic/__init__.py
    - src/knowledge_lake/registry/alembic/env.py
    - src/knowledge_lake/registry/alembic/script.py.mako
    - src/knowledge_lake/registry/alembic/versions/__init__.py
    - src/knowledge_lake/registry/alembic/versions/0001_core_schema.py
    - alembic.ini
    - tests/unit/test_ids.py
    - tests/unit/test_version.py
    - tests/unit/test_registry.py
    - tests/unit/test_artifact_fields.py
    - tests/integration/test_migrations.py

decisions:
  - Unified artifacts node table (not separate documents/chunks) enables FOUND-07 as a single recursive CTE
  - uuid_utils import isolated to ids.py only — Python 3.14 stdlib swap is one line
  - importlib.metadata imported as module (not from-import) to allow correct mock patching in tests
  - LineageEvent.relationship column aliased to edge_type Python attr to avoid SQLAlchemy name conflict
  - Alembic env.py checks for programmatic sqlalchemy.url override before falling back to Settings
  - alembic.ini uses script_location = src/knowledge_lake/registry/alembic (in-package path)
  - migration JSON DEFAULT uses sa.text("'{}'") not string literal to avoid PostgreSQL quoting issue
  - klake_test PostgreSQL database used for migration integration tests (isolated from klake dev DB)

metrics:
  duration: "~45 minutes"
  completed: "2026-07-03"
  tasks_completed: 3
  files_created: 17
  tests_passing: 54
---

# Phase 01 Plan 02: Registry Foundation — IDs, Models, Alembic Summary

One-liner: Prefixed UUIDv7 ID generation (`new_id`), `pipeline_version` stamping, SQLAlchemy 2.0 self-referencing artifacts node table with all six FOUND-06 lineage fields, a repo layer for hash-lookup and node creation (all ORM, no raw SQL), and Alembic migration #1 that builds the full core schema (sources + artifacts + lineage_events + jobs + datasets) on an empty PostgreSQL database.

## What Was Built

### Checkpoint: Package legitimacy gate (Resolved — approved)

User confirmed uuid-utils 0.16.2 (github.com/aminalaee/uuid-utils) on PyPI is legitimate and approved install. `uv add uuid-utils` ran successfully; `uv.lock` pins version 0.16.2.

### Task 1 — Prefixed UUIDv7 IDs and pipeline_version helpers (TDD)

**RED phase:** Wrote 20 failing tests across test_ids.py and test_version.py covering prefix assertions (src_/doc_/chk_/art_), UUIDv7 structure (version nibble == 7), time-sortability, unknown-kind ValueError, uniqueness, and pipeline_version format with/without git SHA, fallback to "0.0.0", never-raise contract.

**GREEN phase:**
- `ids.py`: `new_id(kind)` maps 5 entity kinds to type-prefixed UUIDv7 strings via `uuid_utils.uuid7()`. The library import is isolated to this single module — upgrading to Python 3.14 stdlib is a one-line change.
- `version.py`: `pipeline_version()` returns `"pkg+sha"` inside a git checkout and `"pkg"` alone when git is unavailable. Uses `importlib.metadata.version()` (module-level access) so the mock patch works correctly in tests. Graceful fallback to `"0.0.0"` when package is not installed.
- All 20 tests green.

### Task 2 — SQLAlchemy registry models + repo layer (TDD)

**RED phase:** Wrote 23 failing tests across test_registry.py and test_artifact_fields.py covering model structure, source CRUD, raw/parsed/chunk artifact creation, parent linkage, ID prefix assertions, `get_artifact_by_hash` returns/None, six FOUND-06 fields non-null on every artifact, and UNIQUE(content_hash, artifact_type) constraint enforcement.

**GREEN phase:**
- `registry/models.py`: SQLAlchemy 2.0 declarative `Mapped[...]` typed models for `Source`, `Artifact` (self-referencing via `parent_artifact_id`), `LineageEvent`, `Job`, `Dataset`. `UNIQUE(content_hash, artifact_type)` constraint via `UniqueConstraint`. All FOUND-06 fields on `Artifact`.
- `registry/db.py`: Engine/session factory built from `Settings.database_url`; `get_session()` context manager with auto-commit/rollback.
- `registry/repo.py`: `create_source`, `create_raw_artifact`, `create_parsed_artifact`, `create_chunk_artifact` (each calls `new_id()` and `pipeline_version()`), `get_artifact_by_hash` (ORM select with parameterized WHERE), `get_artifact`, `list_children`. Zero raw SQL strings.
- All 23 tests green.

### Task 3 — Alembic setup + migration #1 (FOUND-09)

- `alembic.ini`: `script_location = src/knowledge_lake/registry/alembic`; no DB URL in the file.
- `env.py`: `target_metadata = Base.metadata`; DB URL resolved from Settings with programmatic override (for test isolation); async driver normalised to sync.
- `0001_core_schema.py`: Creates sources, artifacts (self-FK + 4 indexes + UNIQUE constraint), lineage_events (2 indexes), empty jobs and datasets. `downgrade()` drops all tables in reverse order.
- Integration tests: `alembic upgrade head` on empty DB → all 5 tables + indexes + unique constraint present; `downgrade base` → all tables gone; `upgrade head` again → all tables restored.
- 11 integration tests green; 104 total unit+integration tests green.

## Acceptance Criteria Verification

| Criterion | Status |
|-----------|--------|
| `alembic upgrade head` builds full core schema on empty PostgreSQL DB | PASS |
| Registry stores sources, artifacts (raw/parsed/chunk), lineage events, empty jobs/datasets | PASS — 5 tables created |
| Every artifact carries all six FOUND-06 lineage fields | PASS — 5 tests verify non-null fields per artifact type |
| UNIQUE(content_hash, artifact_type) prevents duplicate nodes | PASS — IntegrityError raised on dup insert |
| Entity IDs are UUIDv7 with short type prefixes, time-sortable | PASS — 12 tests verify prefix + v7 structure + sort order |
| pipeline_version = pkg+sha with pkg-only fallback | PASS — 8 tests verify format + fallback |
| get_artifact_by_hash is the dedup lookup for storage.put_raw | PASS — returns existing or None |
| No Base.metadata.create_all() in production code | PASS — only in docstring comments |
| No raw string SQL in repo.py | PASS — grep confirms zero string-formatted SQL |
| env.py reads DB URL from Settings (not hardcoded) | PASS — Settings.database_url with override |
| Alembic is the only schema authority (FOUND-09) | PASS — no create_all in production paths |
| downgrade → upgrade round-trips clean | PASS — TestMigrationRoundTrip passes |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] importlib.metadata from-import prevents mock patching**
- **Found during:** Task 1 TDD GREEN (test_fallback_version_when_package_not_found failed)
- **Issue:** Using `from importlib.metadata import version` binds the name at import time; the test's `patch("importlib.metadata.version", ...)` patches the module attribute but our local binding was already resolved.
- **Fix:** Changed to `import importlib.metadata` and called `importlib.metadata.version()` so the patch affects the module-level attribute correctly.
- **Files modified:** `src/knowledge_lake/version.py`
- **Commit:** 12b5ca6

**2. [Rule 1 - Bug] SQLAlchemy column named 'relationship' conflicts with ORM relationship()**
- **Found during:** Task 2 TDD GREEN (TypeError: 'MappedColumn' object is not callable)
- **Issue:** `LineageEvent.relationship = mapped_column(...)` shadows the `relationship()` import from `sqlalchemy.orm`, causing `relationship("Artifact", ...)` to fail with TypeError.
- **Fix:** Renamed Python attribute to `edge_type` with `mapped_column("relationship", ...)` column alias to preserve the actual DB column name.
- **Files modified:** `src/knowledge_lake/registry/models.py`
- **Commit:** d73d753

**3. [Rule 1 - Bug] JSON column server_default triple-quoted in PostgreSQL**
- **Found during:** Task 3 (migration run fails with InvalidTextRepresentation)
- **Issue:** `sa.Column("metadata", sa.JSON, server_default="'{}'"` was being rendered as `DEFAULT '''{}'''` by psycopg which is invalid JSON syntax.
- **Fix:** Changed to `server_default=sa.text("'{}'")`  which renders the literal correctly.
- **Files modified:** `src/knowledge_lake/registry/alembic/versions/0001_core_schema.py`
- **Commit:** 6a263f1

**4. [Rule 1 - Bug] env.py _get_db_url did not honour programmatic URL override**
- **Found during:** Task 3 (migration tests used test DB URL but env.py overrode with Settings.database_url, writing to wrong DB)
- **Issue:** `env.py` always called `get_settings().database_url` regardless of `config.set_main_option("sqlalchemy.url", ...)` set by the test fixture.
- **Fix:** `_get_db_url()` now checks `config.get_main_option("sqlalchemy.url")` first; falls back to Settings only when not set programmatically.
- **Files modified:** `src/knowledge_lake/registry/alembic/env.py`
- **Commit:** 6a263f1

## Known Stubs

None. Job and Dataset tables are intentionally minimal (id + status/name + created_at) — they satisfy FOUND-05's enumerated table set with empty schemas to be extended in later phases. This is by design per the plan, not a stub preventing the plan's goal.

## Threat Flags

No new security-relevant surface beyond what was planned:
- All registry SQL goes through SQLAlchemy ORM parameterized queries (T-01-03 mitigated)
- FOUND-06 six fields are non-null where required (T-01-04 mitigated — provenance stamped on every write)
- uuid-utils supply chain gate completed via blocking-human checkpoint (T-01-SC mitigated — uv.lock pins 0.16.2)

## Self-Check

PASSED
