---
phase: 04-enrichment-embedding-search
plan: 03
subsystem: index-search
tags: [qdrant, fastapi, typer, pydantic]

# Dependency graph
requires:
  - phase: 04-enrichment-embedding-search
    provides: "Plan 01's register_vector_collection/get_current_vector_collection registry functions and IndexSettings; Plan 02's enrich_document()/create_enriched_artifact (quality_score column, metadata_ JSON with document_type/keywords)"
provides:
  - "plugins/builtin/qdrant_store.py — ensure_aliased_collection()/reindex()/copy_all_points()/get_collection_dim() (D-06, INDEX-02)"
  - "pipeline/index.py — alias-aware index() payload join (domain/document_type/keywords/quality_score) + reindex_collection() (INDEX-01, INDEX-02)"
  - "pipeline/search.py — filterable search(domain=, document_type=, min_quality_score=) (INDEX-03)"
  - "klake search --domain/--document-type/--min-quality-score, klake reindex; GET /search filter params, POST /reindex (D-02 wiring)"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Qdrant alias-based zero-downtime reindex: create next versioned physical collection -> populate via caller-supplied upsert_fn -> single update_collection_aliases() call containing both delete-old-alias and create-new-alias operations, so the alias never resolves to nothing mid-swap; the prior physical collection is retained, never auto-dropped"
    - "search.py couples to qdrant_client.models Filter/FieldCondition/MatchValue/Range directly (RESEARCH.md's own verified Code Example) — an accepted simplification since only one VectorStorePlugin implementation exists today"

key-files:
  created:
    - tests/unit/test_index_alias.py
    - tests/unit/test_index_payload.py
    - tests/unit/test_search_filters.py
    - tests/integration/test_qdrant_alias_reindex.py
  modified:
    - src/knowledge_lake/plugins/protocols.py
    - src/knowledge_lake/plugins/builtin/qdrant_store.py
    - src/knowledge_lake/pipeline/index.py
    - src/knowledge_lake/pipeline/search.py
    - src/knowledge_lake/api/schemas.py
    - src/knowledge_lake/cli/app.py
    - src/knowledge_lake/api/app.py
    - tests/unit/test_plugin_resolver.py

key-decisions:
  - "Alias swap is one atomic update_collection_aliases() call carrying both DeleteAliasOperation (only when an old alias target exists) and CreateAliasOperation — verified live against the real docker-compose Qdrant server, not just mocked"
  - "index()'s enrichment join (domain, document_type, keywords, quality_score) is looked up once per index() call via a single get_session() block, not once per chunk"
  - "reindex_collection() resolves the alias's current dim via the new get_collection_dim() rather than requiring the caller to pass it, so 'klake reindex' needs no --dim flag"

patterns-established:
  - "VectorStorePlugin Protocol extension requires updating every runtime_checkable isinstance fixture in the codebase (tests/unit/test_plugin_resolver.py's DummyStore) — a structural-typing Protocol checks presence of every member, so adding methods to protocols.py is a breaking change to any hand-written Protocol-conformance stub, not just to real implementations"

requirements-completed: [INDEX-01, INDEX-02, INDEX-03]

coverage:
  - id: D1
    description: "ensure_aliased_collection() creates a versioned physical collection (klake_chunks_v1) behind an alias only the first time an alias is used; every subsequent call is a no-op"
    requirement: "INDEX-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_index_alias.py::TestEnsureAliasedCollection"
        status: pass
    human_judgment: false
  - id: D2
    description: "reindex() creates the next versioned collection, populates it via upsert_fn, then atomically repoints the alias in one update_collection_aliases() call — verified live against a real Qdrant server: search through the alias returns the same points post-reindex, and the old physical collection remains independently queryable"
    requirement: "INDEX-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_index_alias.py::TestReindex, TestCopyAllPoints, TestNextVersionName"
        status: pass
      - kind: integration
        ref: "tests/integration/test_qdrant_alias_reindex.py::TestAliasBootstrapAndReindex::test_ensure_aliased_collection_then_reindex_preserves_search"
        status: pass
    human_judgment: false
  - id: D3
    description: "index() extends each chunk's Qdrant payload with domain (from Source.config['domain']), document_type, keywords, and quality_score from the sibling enriched_document artifact; degrades to null/empty (never blocks) when no enrichment has run yet"
    requirement: "INDEX-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_index_payload.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "search() accepts optional domain/document_type/min_quality_score kwargs that build a Qdrant Filter and narrow ANN results; calling search() with none of them is byte-for-byte backward compatible with the pre-Phase-4 signature"
    requirement: "INDEX-03"
    verification:
      - kind: unit
        ref: "tests/unit/test_search_filters.py"
        status: pass
    human_judgment: false
  - id: D5
    description: "klake search/reindex and GET /search / POST /reindex all delegate to the same pipeline.search.search()/pipeline.index.reindex_collection() with no duplicated logic (D-02)"
    requirement: "INDEX-02, INDEX-03"
    verification:
      - kind: unit
        ref: "acceptance-criteria commands: CLI command registration ({'search','reindex'} subset of registered_commands), API route registration ('/reindex' in app.routes) — both print True; full suite (461 passed, 1 skipped) including integration tests"
        status: pass
    human_judgment: false

# Metrics
duration: ~35min
completed: 2026-07-06
status: complete
---

# Phase 4 Plan 3: Index/Search (Qdrant Aliasing, Enrichment Payload, Filterable Search) Summary

**Qdrant alias-based collection management with zero-downtime reindex, an extended chunk payload carrying enrichment metadata, and filterable, backward-compatible semantic search across CLI/API — closing STATE.md's second Phase-4 blocker (Qdrant collection aliasing)**

## Performance

- **Duration:** ~35 min
- **Tasks completed:** 3 of 3 (autonomous plan, no checkpoints)
- **Files modified:** 12 (4 created, 8 modified)

## Accomplishments

- `plugins/builtin/qdrant_store.py`: `ensure_aliased_collection()` (idempotent first-time alias bootstrap), `reindex()` (next-version creation + populate + single atomic `update_collection_aliases()` alias swap), `copy_all_points()` (scroll+upsert between collections), `get_collection_dim()`, `_next_version_name()`, `_resolve_alias_target()`, `_distance_from_name()` — all mirrored onto the `VectorStorePlugin` Protocol (INDEX-02, D-06)
- `pipeline/index.py`: `index()` now bootstraps the alias-backed collection via `ensure_aliased_collection()` (registering the new alias->physical mapping via `registry_repo.register_vector_collection()` only on first create) and joins in `domain`/`document_type`/`keywords`/`quality_score` from the sibling enrichment before building each chunk's payload — enrichment absence degrades to null/empty, never blocks indexing (INDEX-01, D-07, D-01). New `reindex_collection()` resolves the alias's current dim, drives `vstore.reindex()` with `copy_all_points` as the default upsert_fn, and registers the new mapping (INDEX-02)
- `pipeline/search.py`: `search()` gains keyword-only `domain`/`document_type`/`min_quality_score` filters, building a `qdrant_client.models.Filter` with `FieldCondition`/`MatchValue`/`Range` conditions; zero filter kwargs is byte-for-byte backward compatible (INDEX-03)
- `api/schemas.py`: `SearchHit` extended additively with `domain`/`document_type`/`keywords`/`quality_score`; new `ReindexResponse`
- `cli/app.py`: `klake search` gains `--domain`/`--document-type`/`--min-quality-score`; new `klake reindex` command
- `api/app.py`: `GET /search` gains matching query params (bounded `min_quality_score` via `ge=0.0, le=1.0`); new `POST /reindex` endpoint, both delegating to the same pipeline functions the CLI uses (D-02)
- Live integration test (`tests/integration/test_qdrant_alias_reindex.py`) proves the atomic alias-swap behavior against the real docker-compose Qdrant server: bootstrap v1, upsert 3 points, reindex to v2, confirm the alias transparently now resolves to v2's points, and confirm v1 remains independently queryable by its physical name until explicitly dropped

## Task Commits

Each task was committed atomically:

1. **Task 1: Qdrant alias bootstrap + atomic reindex (ensure_aliased_collection, reindex, copy_all_points) — INDEX-02** - `a6a0be5` (feat)
2. **Task 2: index() payload extension — domain/document_type/keywords/quality_score join (D-07, INDEX-01)** - `88bbd99` (feat)
3. **Task 3: search() filters + klake search/reindex CLI + /search filters + /reindex API (INDEX-02, INDEX-03)** - `36160fb` (feat)

## Files Created/Modified

- `src/knowledge_lake/plugins/protocols.py` — `VectorStorePlugin.ensure_aliased_collection()`/`.reindex()`/`.copy_all_points()`/`.get_collection_dim()`, extended `.search(..., query_filter=)`
- `src/knowledge_lake/plugins/builtin/qdrant_store.py` — `ensure_aliased_collection()`, `reindex()`, `copy_all_points()`, `get_collection_dim()`, `_next_version_name()`, `_resolve_alias_target()`, `_distance_from_name()` helper refactored out of `ensure_collection`
- `src/knowledge_lake/pipeline/index.py` — extended payload (domain/document_type/keywords/quality_score), `reindex_collection()`
- `src/knowledge_lake/pipeline/search.py` — extended `search(..., domain=, document_type=, min_quality_score=)`
- `src/knowledge_lake/api/schemas.py` — extended `SearchHit`, new `ReindexResponse`
- `src/knowledge_lake/cli/app.py` — `--domain`/`--document-type`/`--min-quality-score` flags on `klake search`, new `klake reindex` command, updated module docstring
- `src/knowledge_lake/api/app.py` — extended `GET /search` query params, new `POST /reindex`, updated module docstring
- `tests/unit/test_index_alias.py` — 10 unit tests (mocked client) for bootstrap idempotency, version-name derivation, atomic-swap ordering (upsert_fn before alias swap, delete+create in one call, first-reindex has no delete), scroll/upsert point copying
- `tests/unit/test_index_payload.py` — 5 unit tests (in-memory-SQLite `get_engine()` monkeypatch harness, mirrors `test_enrich.py`'s pattern) for domain-from-config, domain-none-when-config-empty, enrichment-fields-present, register-only-on-first-create, empty-chunks-short-circuit
- `tests/unit/test_search_filters.py` — 5 unit tests (mocked embedder/vectorstore) for no-filter passthrough, backward compatibility, single-filter Filter construction (domain, min_quality_score), combined 3-condition Filter
- `tests/integration/test_qdrant_alias_reindex.py` — 1 live-Qdrant integration test proving the atomic alias-swap + old-collection-retention behavior end-to-end
- `tests/unit/test_plugin_resolver.py` — extended `DummyStore` fixture with the new Protocol methods (Rule 1 fix, see Deviations)

## Decisions Made

- The alias swap is issued as exactly one `update_collection_aliases()` call containing both a `DeleteAliasOperation` (only when an old alias target already exists — the very first reindex of a never-aliased collection has no delete) and a `CreateAliasOperation` — matches Qdrant's documented atomic multi-op guarantee and was independently verified live against this project's exact server/client versions (T-04-10 mitigation)
- `index()`'s domain/enrichment lookup happens once per `index()` call inside a single `get_session()` block, not once per chunk, to avoid N+1 registry queries per document
- `reindex_collection()` resolves the alias's current vector dimension via the new `get_collection_dim()` rather than requiring the caller to supply `--dim`, keeping `klake reindex` a single required flag (`--collection`)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `tests/unit/test_plugin_resolver.py`'s `DummyStore` fixture no longer satisfied `isinstance(s, VectorStorePlugin)`**
- **Found during:** Task 2's `uv run pytest tests/unit/ -q` full-suite run
- **Issue:** Task 1 extended the `VectorStorePlugin` Protocol with `ensure_aliased_collection`/`reindex`/`copy_all_points`/`get_collection_dim` and an extended `search(..., query_filter=)` signature. `Protocol.__instancecheck__` on a `runtime_checkable` Protocol requires every member to be present on the candidate object — the pre-existing `DummyStore` test fixture (a hand-written Protocol-conformance stub, not a real implementation) only implemented the original three methods, so `test_vectorstore_protocol_is_runtime_checkable` started failing.
- **Fix:** Added stub implementations of the four new methods (and the extended `search` signature) to `DummyStore`.
- **Files modified:** `tests/unit/test_plugin_resolver.py`
- **Commit:** `88bbd99`

No other deviations — the plan's action text was followed exactly for all three tasks, including the qdrant-client API shapes (`CreateAliasOperation`/`CreateAlias`/`DeleteAliasOperation`/`DeleteAlias`, `get_collections().collections`, `get_aliases().aliases`, `scroll(..., with_vectors=True, with_payload=True)`) which were verified directly against the installed qdrant-client 1.18.0 before writing any code.

## Issues Encountered

None. The live Qdrant integration test (`tests/integration/test_qdrant_alias_reindex.py`) passed on the first run against the running docker-compose service, confirming the atomic alias-swap and old-collection-retention behavior with no gaps between the mocked unit tests and real server behavior.

One pre-existing, unrelated warning observed throughout the run (not caused by this plan): `qdrant-client version 1.18.0 is incompatible with server version 1.13.6` — a version-skew warning from the installed client library against the docker-compose Qdrant image, present before this plan and not affecting any test outcome (all alias/reindex operations used in this plan are supported by both versions).

## User Setup Required

None. No new environment variables, migrations, or infrastructure changes were needed — this plan builds entirely on Plan 01's already-applied migration 0007 (`vector_collections` table) and the already-running Qdrant service.

## Next Phase Readiness

**COMPLETE.** All three tasks executed autonomously with no checkpoints (plan frontmatter `autonomous: true`). INDEX-01, INDEX-02, and INDEX-03 are fully implemented and verified:

- `uv run pytest tests/unit/test_index_alias.py tests/unit/test_index_payload.py tests/unit/test_search_filters.py -v` → 20 passed
- `uv run pytest tests/integration/test_qdrant_alias_reindex.py -v -m integration` → 1 passed (live Qdrant)
- `uv run pytest tests/unit/ -q` → 280 passed
- `uv run pytest tests/ -q` → 461 passed, 1 skipped (full suite, including all pre-existing integration tests)

Phase 04 (Enrichment, Embedding & Search) is now complete: all three plans (04-01 registry/settings foundation, 04-02 enrichment pipeline with resolved live-Bedrock checkpoint, 04-03 index/search) are done. No blockers carried forward to Phase 5.

---
*Phase: 04-enrichment-embedding-search*
*Completed: 2026-07-06*

## Self-Check: PASSED

All 4 created files and 8 modified files confirmed present on disk; all 3 task commits (`a6a0be5`, `88bbd99`, `36160fb`) confirmed present in git log.
