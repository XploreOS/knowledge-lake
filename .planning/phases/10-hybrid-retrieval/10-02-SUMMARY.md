---
phase: 10-hybrid-retrieval
plan: "02"
subsystem: test-scaffolding
tags: [tdd, red-scaffold, search-mode, hybrid-retrieval, retr-03, d-08, d-09, d-10, d-14]
status: complete

dependency_graph:
  requires:
    - 10-01 (RED scaffold for QdrantVectorStore hybrid — store layer tests)
  provides:
    - RED test targets for Plans 10-04 (SearchSettings), 10-06/10-07 (pipeline.search mode), 10-08 (CLI/API surface)
  affects:
    - tests/unit/test_settings_search.py (NEW)
    - tests/unit/test_search_mode.py (NEW)
    - tests/unit/test_cli_search_mode.py (NEW)
    - tests/unit/test_api_search_mode.py (NEW)
    - tests/unit/test_search_filters.py (extended with D-14 assertion)

tech_stack:
  added: []
  patterns:
    - xfail(strict=False) with try/except ImportError guard for not-yet-existing symbols
    - monkeypatch get_embedder/get_vectorstore at pipeline module level (mirrors test_search_filters.py)
    - CliRunner + pipeline.search patch for CLI command mode-forwarding tests
    - TestClient + pipeline.search side_effect stub for API mode-forwarding tests

key_files:
  created:
    - tests/unit/test_settings_search.py
    - tests/unit/test_search_mode.py
    - tests/unit/test_cli_search_mode.py
    - tests/unit/test_api_search_mode.py
  modified:
    - tests/unit/test_search_filters.py

decisions:
  - xfail stubs point at specific plan numbers (10-04/10-06/10-07/10-08) so removal is traceable
  - D-14 filter parity asserted at pipeline layer (vstore.search kwargs); per-branch Prefetch.filter asserted at store layer in test_qdrant_hybrid.py (clean separation)
  - API test_api_mode_absent_uses_default xpassed (strict=False) — existing API already returns 200 without mode param, which is backward-compatible correct behavior

metrics:
  duration: "4m"
  completed: "2026-07-10"
  tasks_completed: 3
  files_changed: 5
---

# Phase 10 Plan 02: RED Test Scaffold — Mode Surface + Filter Parity Summary

**One-liner:** Wave 0 RED test scaffold for RETR-03 search-mode surface (settings, pipeline, CLI, API) and D-14 filter continuity in hybrid mode.

## What Was Built

Four new RED unit test files plus one extended file, encoding the RETR-03 acceptance behaviors and the D-14 filter-parity guarantee as concrete automated targets before any implementation exists.

### Task 1: Settings + pipeline mode RED scaffolds

**Files:** `tests/unit/test_settings_search.py`, `tests/unit/test_search_mode.py`

- `test_settings_search.py` (4 tests, all xfail): `test_search_mode_default_hybrid` asserts `Settings(_env_file=None).search.mode == "hybrid"` (D-08 default); `test_search_mode_env_dense/sparse` assert `KLAKE_SEARCH__MODE` env override paths; `test_search_settings_class_exported` asserts the `SearchSettings` class is directly importable. Module-scope try/except AttributeError guard prevents collection failures before Plan 10-04 adds `SearchSettings`.
- `test_search_mode.py` (4 tests, all xfail): `test_mode_threads_sparse_query` asserts mode='hybrid' forwards non-None `sparse_query` into vstore.search (D-09, D-03); `test_dense_mode_no_sparse_query` asserts mode='dense' passes `sparse_query=None` (back-compat); `test_fail_loud_missing_sparse_hybrid` and `_no_fallback` assert a ValueError/RuntimeError naming "sparse" and "reindex" is raised without silent dense degradation (D-10, T-10-03).

### Task 2: CLI + API mode RED scaffolds

**Files:** `tests/unit/test_cli_search_mode.py`, `tests/unit/test_api_search_mode.py`

- `test_cli_search_mode.py` (3 tests, all xfail): asserts `klake search <q> --mode hybrid` and `--mode dense` forward the mode kwarg into pipeline.search via CliRunner + monkeypatched stub; asserts `--mode` appears in `search --help` output.
- `test_api_search_mode.py` (5 tests, 4 xfail + 1 xpassed): asserts `GET /search?mode=hybrid/dense` forwards mode into pipeline.search (200 response); asserts `GET /search?mode=bogus` returns 422 (T-10-02 Literal validation); `test_api_mode_absent_uses_default` xpassed because the existing endpoint already returns 200 for a request without a mode param (backward-compatible correct behavior with strict=False).

### Task 3: D-14 prefetch-filter parity assertion

**File:** `tests/unit/test_search_filters.py` (extended)

Added `TestFilterPrefetchParity.test_filter_attaches_each_prefetch_branch` (xfail): calls `search("q", mode="hybrid", domain="healthcare")` and asserts `fake_vstore.search.call_args.kwargs["query_filter"]` is a non-None `Filter` with a `FieldCondition(key="domain", match.value="healthcare")`. This proves the Phase-7 filter builder output is preserved unchanged at the pipeline layer when mode='hybrid' (D-14). All 12 existing tests still pass.

## Verification Results

```
# Final verification run
collected 29 items
  test_settings_search.py: 4 xfailed
  test_search_mode.py: 4 xfailed
  test_cli_search_mode.py: 3 xfailed
  test_api_search_mode.py: 4 xfailed, 1 xpassed (strict=False — backward-compat)
  test_search_filters.py: 12 passed, 1 xfailed

Full unit suite: 383 passed, 23 xfailed, 21 xpassed — ZERO FAILURES
```

## Deviations from Plan

None — plan executed exactly as written. The one xpassed (`test_api_mode_absent_uses_default`) is expected: `strict=False` means an early pass is allowed; the test documents that the no-mode path already works, which is correct.

## Known Stubs

All test files are RED scaffolds by design — every xfail test is a stub targeting a specific future implementation plan. The stubs are intentional and tracked; they will be unwound as Plans 10-04, 10-06, 10-07, and 10-08 land.

## Threat Flags

None — this plan creates test files only. No network endpoints, auth paths, file access patterns, or schema changes introduced.

## Self-Check: PASSED

- tests/unit/test_settings_search.py: FOUND
- tests/unit/test_search_mode.py: FOUND
- tests/unit/test_cli_search_mode.py: FOUND
- tests/unit/test_api_search_mode.py: FOUND
- tests/unit/test_search_filters.py: FOUND (extended)
- Commit a961105: FOUND (Task 1)
- Commit ed6750f: FOUND (Task 2)
- Commit 8914da3: FOUND (Task 3)
