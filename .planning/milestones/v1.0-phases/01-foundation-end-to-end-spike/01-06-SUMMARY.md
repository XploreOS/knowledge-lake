---
phase: 01-foundation-end-to-end-spike
plan: "06"
subsystem: api-dagster
tags: [api, dagster, lineage, search, fastapi, assets, resources, found-07, found-01, d-01, d-02]
status: complete

dependency_graph:
  requires:
    - 01-05 (pipeline functions ingest/parse/chunk/embed/index/search + lineage.resolve_ancestry)
    - 01-01 (FastAPI app skeleton, GET /health)
    - 01-01 (dagster_defs/definitions.py minimal skeleton)
  provides:
    - knowledge_lake.api.app: GET /search, GET /lineage/{artifact_id}
    - knowledge_lake.api.schemas: SearchHit, LineageNode, LineageGraph
    - knowledge_lake.dagster_defs.assets: ingest_raw_document, parsed_document, chunk_document, embed_chunks, index_chunks
    - knowledge_lake.dagster_defs.resources: PostgresResource, MinIOResource, QdrantResource, LiteLLMResource
    - knowledge_lake.dagster_defs.definitions: updated Definitions with assets + EnvVar resources
    - tests/integration/test_api_lineage.py (24 tests)
    - tests/integration/test_dagster_assets.py (15 tests)
  affects:
    - All later phases: API search + lineage surface, Dagster materialization path
    - Phase 01 success criteria: FOUND-07 complete (CLI + API), FOUND-01 complete (Dagster materializes)

tech_stack:
  added:
    - "FastAPI TestClient (httpx/starlette) for integration test assertions"
    - "dagster.Config subclass (IngestConfig) for per-run asset configuration"
    - "dagster.ConfigurableResource for typed resource injection"
    - "dagster.materialize() API for in-process asset graph execution in tests"
  patterns:
    - "API endpoints call pipeline.search() and lineage.resolve_ancestry() — same functions as CLI (D-02)"
    - "top_k bounded [1, 100] via FastAPI Query(ge=1, le=100) — ASVS V5 input validation (T-01-14)"
    - "Dagster assets call pipeline functions via deps ordering — no IO managers for bytes (Pitfall 7)"
    - "Dagster resources use EnvVar from first connection — no hardcoded URLs (Pitfall 14)"
    - "from __future__ import annotations removed from assets.py — Dagster Config requires real type objects"

key_files:
  created:
    - src/knowledge_lake/api/schemas.py (SearchHit, LineageNode, LineageGraph pydantic schemas)
    - src/knowledge_lake/dagster_defs/assets.py (5 pipeline assets calling existing plain functions)
    - src/knowledge_lake/dagster_defs/resources.py (4 ConfigurableResources with EnvVar fields)
    - tests/integration/test_api_lineage.py (24 tests for search + lineage API)
    - tests/integration/test_dagster_assets.py (15 tests for Dagster definitions + materialization)
  modified:
    - src/knowledge_lake/api/app.py (added /search and /lineage/{artifact_id} endpoints)
    - src/knowledge_lake/dagster_defs/definitions.py (registered assets + EnvVar resources)

decisions:
  - "API endpoints are thin JSON wrappers over pipeline.search() and lineage.resolve_ancestry() — no behavior re-implementation (D-02)"
  - "Dagster assets use deps= ordering chain; no IO managers for object bytes (Pitfall 7)"
  - "from __future__ import annotations removed from assets.py — Dagster's Config/pythonic_config system requires real type annotations at class definition time"
  - "IngestConfig.fixture_path/url pattern preserves hermetic testing (D-05) through Dagster materialization path"
  - "raw_artifact_id aliased from artifact_id in ingest result — ingest_file/ingest_url return artifact_id; assets expose it as raw_artifact_id for clarity in the chain"

metrics:
  duration: "~28 minutes"
  completed: "2026-07-03"
  tasks_completed: 2
  files_created: 5
  files_modified: 2
  tests_passing: 215
---

# Phase 01 Plan 06: FastAPI Search + Lineage API + Dagster Assets Summary

One-liner: FastAPI GET /search + GET /lineage/{id} endpoints calling the same pipeline functions as the CLI (FOUND-07 API, D-02), plus five Dagster software-defined assets wrapping ingest→parse→chunk→embed→index with EnvVar-based resources (D-01, Pitfall 14) — 39 new integration tests, 215 passing total.

## What Was Built

### Task 1 — FastAPI search + lineage endpoints (FOUND-07 API, D-02)

**`api/schemas.py`** — Pydantic models for the API wire format:
- `SearchHit`: id, score, document, section_path, page, chunk_id, text
- `LineageNode`: the six FOUND-06 fields (id, artifact_type, content_hash, created_at, pipeline_version, storage_uri) plus source_id, parent_artifact_id, depth, section_path, page, mime_type
- `LineageGraph`: artifact_id + nodes (used as a return type reference; response is list[LineageNode] directly)

**`api/app.py`** (extended):
- `GET /search?q=...&top_k=...&collection=...` — FastAPI Query params with `ge=1, le=100` on top_k (ASVS V5, T-01-14). Calls `pipeline.search.search()` — same function as `klake search`. Maps Hit objects → SearchHit pydantic models. Returns empty list for whitespace queries.
- `GET /lineage/{artifact_id}` — calls `lineage.resolve_ancestry()` — same function as `klake lineage`. Maps dicts → LineageNode models. Returns 404 with `{"detail": "..."}` body for unknown artifact IDs (LookupError → HTTPException 404).
- `GET /health` — unchanged

**`tests/integration/test_api_lineage.py`** (24 tests):
- Health still returns ok
- /search: 200, hits list, score in [0,1], citation fields (document/section_path/page/chunk_id), top_k limiting, default top_k, empty query → []
- /search validation: top_k=0 → 422, top_k=-1 → 422, top_k=999 → 422 (ASVS V5)
- /lineage: 200, JSON array, ≥3 nodes, six FOUND-06 fields on every node, first node = requested chunk, raw_document in chain, non-empty content_hash
- /lineage 404: unknown id → 404, detail field present in body
- OpenAPI: /openapi.json served, /search and /lineage in paths, /health in paths

### Task 2 — Dagster assets + resources (D-01, phase close)

**`dagster_defs/resources.py`** — Four ConfigurableResources:
- `PostgresResource(database_url)` — registry SQLAlchemy URL
- `MinIOResource(endpoint_url, bucket, access_key_id, secret_access_key, region)` — S3 credentials
- `QdrantResource(qdrant_url)` — vector store URL
- `LiteLLMResource(litellm_url)` — model gateway URL

All fields have defaults but production definitions.py wires them via `EnvVar("KLAKE_*")` (Pitfall 14).

**`dagster_defs/assets.py`** — Five software-defined assets:

| Asset | Calls | Input | Output dict keys |
|-------|-------|-------|-----------------|
| `ingest_raw_document` | `ingest_file` or `ingest_url` | `IngestConfig` | source_id, raw_artifact_id, collection |
| `parsed_document` | `parse()` | ingest output | artifact_id, parsed_doc, source_id, collection |
| `chunk_document` | `chunk()` | parsed output | chunks, parsed_artifact_id, source_id, collection |
| `embed_chunks` | `embed()` | chunk output | vectors, dim, chunks, parsed_artifact_id, collection |
| `index_chunks` | `index()` | embed output | chunk_artifact_ids, collection, chunk_count |

Ordering: `deps=[ingest_raw_document]` → `deps=[parsed_document]` → `deps=[chunk_document]` → `deps=[embed_chunks]`. No IO managers for object bytes — bytes travel through S3/registry/Qdrant directly (Pitfall 7).

`IngestConfig` extends `dagster.Config` — provides fixture_path/url/source_name/collection/mime_type as per-run materialization config.

**`dagster_defs/definitions.py`** (updated):
- Registers all five assets
- Resources wired via `EnvVar("KLAKE_DATABASE_URL")`, `EnvVar("KLAKE_STORAGE__*")`, `EnvVar("KLAKE_QDRANT_URL")`, `EnvVar("KLAKE_LITELLM_URL")`

**`tests/integration/test_dagster_assets.py`** (15 tests):
- `TestDefinitionsLoad`: importable, has ≥5 assets, has resources, job binds
- `TestResourcesUseEnvVar`: all four resource classes importable, instantiable with literal values
- `TestAssetsModule`: assets importable, no IOManager in source, imports from pipeline (D-01)
- `TestAssetMaterialization`: materialize succeeds, produces raw_artifact_id with doc_ prefix, lineage resolves after materialize

## Final Test Run

```
215 passed, 29 warnings
```

- 61 unit tests (unchanged from Plan 05)
- 154 integration tests:
  - Prior: test_storage, test_raw_immutable, test_migrations, test_lineage, test_demo_spike
  - New: test_api_lineage (24), test_dagster_assets (15)
  - Total new integration tests: 39

## Acceptance Criteria Verification

| Criterion | Status |
|-----------|--------|
| /search returns hits with score + citation (FOUND-07 API) | PASS — 24 tests confirming hit shape |
| /lineage/{id} returns six-field lineage graph (FOUND-07 API) | PASS — every node has all FOUND-06 fields |
| Unknown artifact 404 with detail body | PASS — TestLineageNotFound |
| OpenAPI docs served and list both endpoints | PASS — TestOpenAPISpec |
| top_k validated [1, 100] (ASVS V5, T-01-14) | PASS — 3 validation rejection tests |
| Endpoints call same pipeline/lineage functions as CLI (D-02) | PASS — no logic re-implementation in endpoints |
| Assets wrap (call) existing pipeline functions; no duplication (D-01) | PASS — test_assets_call_pipeline_functions |
| deps ordering; no IO managers for object bytes (Pitfall 7) | PASS — test_no_io_manager_imports_in_assets |
| Resources read config via EnvVar (Pitfall 14) | PASS — definitions.py uses EnvVar for all resource fields |
| Materialize succeeds yielding raw_artifact_id with doc_ prefix | PASS — test_dagster_materialize_produces_artifacts |
| Lineage resolves after Dagster materialize (same as in-process) | PASS — test_lineage_resolves_after_dagster_materialize |
| CLI/API surface unchanged (D-02) | PASS — cli/app.py and api health endpoint unchanged |
| FOUND-07 complete: lineage via API (completing CLI+API coverage) | PASS |
| FOUND-01: Dagster materializes pipeline (not just healthy) | PASS — D-01 satisfied |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `from __future__ import annotations` breaks Dagster Config resolution**
- **Found during:** Task 2 (Definitions load at import time)
- **Issue:** Dagster's `Config` and `ConfigurableResource` system uses `get_type_hints()` internally. With `from __future__ import annotations`, all annotations become lazy strings instead of real types, causing `DagsterInvalidPythonicConfigDefinitionError: Unable to resolve config type 'IngestConfig'`.
- **Fix:** Removed `from __future__ import annotations` from `assets.py`. Resources.py keeps it since ConfigurableResource field resolution works differently.
- **Files modified:** `src/knowledge_lake/dagster_defs/assets.py`
- **Commit:** b1db18a

**2. [Rule 1 - Bug] ingest_file/ingest_url return "artifact_id" not "raw_artifact_id"**
- **Found during:** Task 2 (first materialization run)
- **Issue:** The `ingest_raw_document` asset expected `result["raw_artifact_id"]` but `ingest_file`/`ingest_url` return `result["artifact_id"]` (run.py renames it after calling the stage functions).
- **Fix:** Added `result["raw_artifact_id"] = result["artifact_id"]` aliasing in the ingest asset after the pipeline call, making both keys available for downstream assets and tests.
- **Files modified:** `src/knowledge_lake/dagster_defs/assets.py`
- **Commit:** b1db18a

**3. [Rule 1 - Bug] Test used `defs.map_asset_specs(lambda)` — wrong API for Dagster 1.13**
- **Found during:** Task 2 (TestDefinitionsLoad tests)
- **Issue:** `Definitions.map_asset_specs()` in Dagster 1.13 takes only `func` and `selection` keyword arguments; passing a positional lambda raised `TypeError`.
- **Fix:** Replaced with `list(defs.assets or [])` which accesses the raw assets list directly.
- **Files modified:** `tests/integration/test_dagster_assets.py`
- **Commit:** b1db18a

**4. [Rule 2 - Missing critical functionality] Search test used default collection**
- **Found during:** Task 1 (test_search_returns_200 failing with Qdrant 404)
- **Issue:** Test seeded data into `klake_api_test` collection but search called with default `klake_chunks` collection (which didn't exist in the test run). Test missing `collection` parameter in request params.
- **Fix:** Updated all search test requests to pass `collection=COLLECTION_NAME` explicitly. Tests now search the correct seeded collection.
- **Files modified:** `tests/integration/test_api_lineage.py`
- **Commit:** 0b0aa57

## Threat Mitigations Applied

| Threat | Status | Evidence |
|--------|--------|---------|
| T-01-14 (API input validation — tampering/info disclosure) | Mitigated | `top_k` bounded [1,100] via FastAPI Query(ge=1, le=100); pydantic schema validation on all params; 3 validation rejection tests confirm 422 on out-of-bounds values |
| T-01-15 (Dagster resource config drift) | Mitigated | All four resources use `EnvVar("KLAKE_*")` in definitions.py — no hardcoded URLs or credentials |
| T-01-16 (Dagster path vs in-process path divergence) | Mitigated | Assets call the same pipeline functions; `test_lineage_resolves_after_dagster_materialize` asserts identical lineage from both paths |

## Known Stubs

None. All endpoints are fully functional:
- `GET /search` — calls real sentence-transformer embedder + Qdrant ANN search
- `GET /lineage/{id}` — calls real PostgreSQL recursive CTE via resolve_ancestry()
- Dagster assets — materialize the full pipeline against real services (MinIO + Postgres + Qdrant)

## Threat Flags

No new security-relevant surface beyond the planned threat model.
- `api/app.py` GET /search and GET /lineage are the planned T-01-14 surface — mitigated
- `dagster_defs/` is the planned T-01-15 surface — mitigated

## Self-Check

PASSED

- src/knowledge_lake/api/schemas.py: FOUND
- src/knowledge_lake/api/app.py (updated): FOUND
- src/knowledge_lake/dagster_defs/assets.py: FOUND
- src/knowledge_lake/dagster_defs/resources.py: FOUND
- src/knowledge_lake/dagster_defs/definitions.py (updated): FOUND
- tests/integration/test_api_lineage.py: FOUND
- tests/integration/test_dagster_assets.py: FOUND
- Commits e78e968, 0b0aa57, b1db18a: FOUND in git log
- 215 tests passing: CONFIRMED
