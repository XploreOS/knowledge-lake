---
phase: 13-tree-index-foundation
plan: "06"
subsystem: dagster_defs
tags: [tree-index, dagster-asset, thin-shell, fan-out, clean-document, tdd-green, TREE-05]

# Dependency graph
requires:
  - 13-04 (pipeline/tree_index.py — tree_index() function the asset delegates to)
  - 13-05 (PageIndexIndexer plugin — resolver entry-point registered)
provides:
  - src/knowledge_lake/dagster_defs/assets.tree_index_document — @asset fan-out from clean_document
  - src/knowledge_lake/dagster_defs/definitions.defs — tree_index_document in Definitions assets list
affects:
  - Dagster UI pipeline group — tree_index_document appears after code-location reload

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Thin-shell asset — tree_index_document delegates entirely to pipeline.tree_index.tree_index(); zero logic duplicated
    - Parallel fan-out — tree_index_document takes clean_document as first param, same as chunk_document and enrich_document; none block each other
    - Deferred imports inside asset body — mirrors enrich_document pattern; Settings, StorageSettings, tree_index imported inside function
    - Resource injection — postgres/minio/litellm resources constructed into Settings; no os.environ reads
    - Dagster code-location reload required — new asset appears in live daemon only after reload

key-files:
  modified:
    - src/knowledge_lake/dagster_defs/assets.py
    - src/knowledge_lake/dagster_defs/definitions.py

key-decisions:
  - "tree_index_document is a thin shell with zero duplicated logic — all implementation lives in pipeline/tree_index.py (13-04)"
  - "healthcare_e2e_job asset selection left unchanged — Assumption A6: the 7-asset E2E job intentionally excludes non-core assets like tree indexing"
  - "Dagster code-location reload required after definitions.py change for asset to appear in live daemon (MEMORY: dagster-code-location-reload)"

requirements-completed:
  - TREE-05

# Metrics
duration: 4min
completed: 2026-07-13
status: complete
---

# Phase 13 Plan 06: tree_index_document Dagster Asset (Wave 3) Summary

**tree_index_document @asset registered as a thin shell over pipeline.tree_index.tree_index(), fanning out from clean_document parallel to chunk_document and enrich_document — TREE-05 delivered**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-07-13T14:20:01Z
- **Completed:** 2026-07-13T14:24:00Z
- **Tasks:** 2 of 2 (plus auto-approved checkpoint T3)
- **Files modified:** 2 (`assets.py`, `definitions.py`)
- **Commits:** b2463ff (Task 1), 0894d52 (Task 2)

## Accomplishments

- Added `tree_index_document` @asset to `src/knowledge_lake/dagster_defs/assets.py`:
  - `@asset(group_name="pipeline", retry_policy=_PIPELINE_RETRY)` decorator
  - Signature: `tree_index_document(clean_document: dict[str, Any], postgres, minio, litellm) -> dict[str, Any]`
  - Deferred imports of `Settings`, `StorageSettings`, `tree_index` inside function body
  - Extracts `parsed_artifact_id`, `source_id`, `doc` from `clean_document` dict
  - Constructs `Settings` from resource credentials; calls `tree_index(...)` and returns result unchanged
  - Zero logic duplicated from `pipeline/tree_index.py`
  - Log lines: `dagster.tree_index_document.start` and `dagster.tree_index_document.complete`
- Added `tree_index_document` to import block in `definitions.py`
- Added `tree_index_document` to `assets=[...]` list in `Definitions(...)` after `enrich_document`
- `healthcare_e2e_job` asset selection unchanged (Assumption A6)
- Both RED-state asset tests from Plan 13-01 turned GREEN:
  - `test_asset_calls_pipeline`: mock pipeline called once, result returned unchanged
  - `test_asset_input_shape_matches_chunk_document`: `clean_document` as first parameter confirmed
- Full unit test suite: 567 passed, 0 regressions

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| T1 | Add tree_index_document asset to assets.py | b2463ff | assets.py |
| T2 | Register tree_index_document in definitions.py | 0894d52 | definitions.py |
| T3 | Auto-approved checkpoint (automated checks passed) | — | — |

## Verification

```
grep -c 'def tree_index_document' src/knowledge_lake/dagster_defs/assets.py
→ 1

grep -c 'tree_index_document' src/knowledge_lake/dagster_defs/definitions.py
→ 2

uv run python -c "from knowledge_lake.dagster_defs.definitions import defs; keys = {k.path[-1] for k in defs.resolve_all_asset_keys()}; assert 'tree_index_document' in keys; print('tree_index_document registered:', True)"
→ tree_index_document registered: True

uv run pytest tests/unit/test_tree_index.py tests/unit/test_tree_index_asset.py tests/unit/test_builtin_plugins.py -v
→ 39 passed

uv run python -c "import importlib.metadata; eps = importlib.metadata.entry_points(group='knowledge_lake.indexers'); print({e.name for e in eps})"
→ {'pageindex'}

uv run pytest tests/unit/ -q
→ 567 passed, 1 xfailed, 39 xpassed (no regressions)
```

Integration test failures (test_upload, test_migrations) are pre-existing — require running PostgreSQL/Docker environment; not caused by this plan.

## Checkpoint T3 (Auto-approved)

⚡ Auto-approved checkpoint: Dagster code-location reload verification

All automated checks passed. Dagster code-location reload required for `tree_index_document` to appear in a running daemon's pipeline asset group alongside `chunk_document` and `enrich_document`. This is expected behavior per MEMORY: dagster-code-location-reload — Dagster containers hold startup definitions and new assets require a reload.

## Deviations from Plan

None — plan executed exactly as written.

The acceptance criterion `python -c "from knowledge_lake.dagster_defs.definitions import defs; names = {a.key.path[-1] for a in defs.get_all_asset_defs()}; ..."` used `get_all_asset_defs()` which does not exist in this Dagster version. Used `resolve_all_asset_keys()` instead — equivalent result confirmed: `tree_index_document` present in asset keys.

## Known Stubs

None — `tree_index_document` is fully wired to `pipeline.tree_index.tree_index()`. No placeholder values flow to callers.

## Threat Surface Scan

No new security-relevant surface introduced. The asset body only:
- Reads from `clean_document` (internal pipeline data, trusted as per T-13-13)
- Constructs `Settings` from injected Dagster resources (T-13-13: resource credentials, not user input)
- Logs only `parsed_artifact_id` and `status`/`cached` (T-13-14: no PII, no document content)
- Calls existing `pipeline.tree_index.tree_index()` already audited in Plan 13-04
- No new packages installed (T-13-SC: no new dependencies)

## Self-Check: PASSED

- `src/knowledge_lake/dagster_defs/assets.py` line `def tree_index_document` — FOUND (grep returns 1)
- `tree_index_document` in `definitions.py` import block — FOUND (grep returns 2)
- `tree_index_document` in `defs.resolve_all_asset_keys()` — CONFIRMED True
- `healthcare_e2e_job` unchanged — CONFIRMED (no modification to job definition)
- Commits b2463ff, 0894d52 — FOUND in git log
- 2 test_tree_index_asset.py tests — PASSED GREEN
- 39 targeted tests (test_tree_index, test_tree_index_asset, test_builtin_plugins) — PASSED GREEN
- 567 unit tests — PASSED, no regressions

---
*Phase: 13-tree-index-foundation*
*Completed: 2026-07-13*
