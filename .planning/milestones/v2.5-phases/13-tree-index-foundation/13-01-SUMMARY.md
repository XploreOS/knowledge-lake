---
phase: 13-tree-index-foundation
plan: "01"
subsystem: testing
tags: [pytest, tree-index, dagster, plugin-protocol, wave-0-scaffold, tdd-red-state]

# Dependency graph
requires: []
provides:
  - Wave 0 test scaffold for TREE-01..04 in tests/unit/test_tree_index.py
  - Wave 0 test scaffold for TREE-05 in tests/unit/test_tree_index_asset.py
  - IndexerPlugin + PageIndexIndexer conformance stubs in test_builtin_plugins.py
  - Multi-section ParsedDoc fixture (§1, §1.1, §2, §2.1 is_table) for nesting + page_end tests
  - In-memory SQLite + _patch_engine + fake_storage fixture chain for tree_index tests
affects:
  - 13-02 (protocols plan reads these tests for done criteria)
  - 13-03 (config plan reads these tests for done criteria)
  - 13-04 (pipeline plan turns RED→GREEN for test_tree_index.py)
  - 13-05 (plugin plan turns RED→GREEN for test_builtin_plugins.py IndexerPlugin tests)
  - 13-06 (asset plan turns RED→GREEN for test_tree_index_asset.py)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Wave-0 test-first scaffold — write failing tests before any implementation (RED state by design)
    - In-memory SQLite test engine pattern verbatim from test_enrich.py (StaticPool + _patch_engine autouse)
    - FakeStorage monkeypatch pattern at module level (mirrors test_enrich.py fake_storage)
    - Multi-section ParsedDoc fixture with is_table=True for table-leaf coverage

key-files:
  created:
    - tests/unit/test_tree_index.py
    - tests/unit/test_tree_index_asset.py
  modified:
    - tests/unit/test_builtin_plugins.py

key-decisions:
  - "Wave 0 tests use ImportError as the explicit RED signal — correct before Plan 13-04 ships"
  - "Multi-section fixture uses 4 sections (§1, §1.1, §2, §2.1 is_table) to exercise nesting + page_end derivation"
  - "test_asset_input_shape_matches_chunk_document uses inspect.signature on .op.compute_fn.decorated_fn to verify fan-out shape parity"

patterns-established:
  - "Pipeline test pattern: import module as *_module alias at file top so ImportError surfaces at collection time"
  - "Seeded fixture for tree tests: Source→raw→parsed chain (no cleaned artifact — tree parents off parsed_document per D-07)"

requirements-completed:
  - TREE-01
  - TREE-02
  - TREE-03
  - TREE-04
  - TREE-05

coverage:
  - id: D1
    description: "test_tree_index.py — 6 test stubs covering TREE-01..04 in RED state (ImportError until Plan 13-04)"
    requirement: TREE-01
    verification:
      - kind: unit
        ref: "tests/unit/test_tree_index.py (grep -c 'def test_' returns 6)"
        status: pass
    human_judgment: false
  - id: D2
    description: "test_tree_index_asset.py — 2 test stubs covering TREE-05 in RED state (ImportError until Plan 13-06)"
    requirement: TREE-05
    verification:
      - kind: unit
        ref: "tests/unit/test_tree_index_asset.py (grep -c 'def test_' returns 2)"
        status: pass
    human_judgment: false
  - id: D3
    description: "test_builtin_plugins.py extended with IndexerPlugin import + TestIndexerPluginBuiltin (2 new stubs)"
    requirement: TREE-05
    verification:
      - kind: unit
        ref: "tests/unit/test_builtin_plugins.py (grep -c 'IndexerPlugin' returns ≥1)"
        status: pass
    human_judgment: false

# Metrics
duration: 8min
completed: 2026-07-13
status: complete
---

# Phase 13 Plan 01: Wave 0 Test Scaffold Summary

**pytest RED-state scaffold for TREE-01..05 — 6 tree-index tests, 2 asset tests, and 2 IndexerPlugin conformance stubs all fail with ImportError until Wave 1/2 implementation ships**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-07-13T13:34:40Z
- **Completed:** 2026-07-13T13:42:56Z
- **Tasks:** 2 of 2
- **Files modified:** 3 (2 created, 1 extended)

## Accomplishments

- Created `tests/unit/test_tree_index.py` with 6 test stubs covering TREE-01..04: deterministic tree structure, storage key format, content-hash no-op, node fields + fallback, LLM budget cap, no-hardcoded-provider-model-ID enforcement
- Created `tests/unit/test_tree_index_asset.py` with 2 test stubs covering TREE-05: thin-shell delegation and fan-out input-shape parity with `chunk_document`
- Extended `tests/unit/test_builtin_plugins.py` with `IndexerPlugin` import and `TestIndexerPluginBuiltin` class (entry-point registration + runtime isinstance conformance)
- All 10 new test functions are collectible (parseable by pytest) and fail with `ModuleNotFoundError` — confirmed correct RED state

## Task Commits

1. **Task 1: Create tests/unit/test_tree_index.py** — `7b9ec56` (test)
2. **Task 2: Create test_tree_index_asset.py and extend test_builtin_plugins.py** — `b475cc0` (test)

## Files Created/Modified

- `tests/unit/test_tree_index.py` — 6-function test scaffold; fixtures: `engine`, `_patch_engine`, `session`, `seeded`, `fake_storage`, `multi_section_doc`; test classes: `TestDeterministicTree` (4 tests), `TestLlmMode` (2 tests)
- `tests/unit/test_tree_index_asset.py` — 2-function test scaffold; `TestTreeIndexDocumentAsset`: `test_asset_calls_pipeline`, `test_asset_input_shape_matches_chunk_document`
- `tests/unit/test_builtin_plugins.py` — `IndexerPlugin` added to import block; `TestIndexerPluginBuiltin` class appended with `test_pageindex_indexer_entry_point_registered` and `test_pageindex_indexer_satisfies_protocol`

## Decisions Made

- Used `import knowledge_lake.pipeline.tree_index as tree_index_module` at file top so `ModuleNotFoundError` surfaces at collection time (correct RED pattern matching test_enrich.py)
- Seeded fixture for tree tests uses Source→raw→parsed chain only (no `cleaned_artifact`) because tree artifact parents off `parsed_document` per D-07
- `test_asset_input_shape_matches_chunk_document` inspects `.op.compute_fn.decorated_fn` signature — matches Dagster's asset wrapping structure seen in `test_dagster_retry_policies.py`

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None — pytest unavailable as bare `pytest` command; used `/root/healthlake/.venv/bin/pytest` for verification. Confirmed RED state: `ModuleNotFoundError: No module named 'knowledge_lake.pipeline.tree_index'`.

## Stub Tracking

All files in this plan are intentional test stubs — they are the RED state. There are no unintentional stubs or placeholder values. The failing imports are the desired behavior until Wave 1/2 implementation plans ship.

## Threat Flags

None — test-only changes. All trust boundaries are in-memory (StaticPool SQLite, FakeStorage MagicMock). No production data accessible.

## Self-Check: PASSED

- `tests/unit/test_tree_index.py` — FOUND: 6 test functions confirmed
- `tests/unit/test_tree_index_asset.py` — FOUND: 2 test functions confirmed
- `tests/unit/test_builtin_plugins.py` — FOUND: IndexerPlugin import + 2 new stubs confirmed
- Commits 7b9ec56 and b475cc0 — FOUND: both in git log

## Next Phase Readiness

- Wave 0 complete: all Wave 1 and Wave 2 implementation tasks have concrete pytest targets
- Plans 13-02 (protocols), 13-03 (config), 13-04 (pipeline), 13-05 (plugin), 13-06 (asset) can now execute in parallel waves 1 and 2
- RED state is confirmed; each downstream plan will turn specific tests GREEN

---
*Phase: 13-tree-index-foundation*
*Completed: 2026-07-13*
