---
phase: "10"
plan: "01"
subsystem: vector-store
tags: [testing, red-scaffold, hybrid-retrieval, qdrant, tdd]
dependency_graph:
  requires: []
  provides: [unit-red-hybrid, integration-red-migration]
  affects: [10-06-PLAN, 10-07-PLAN]
tech_stack:
  added: []
  patterns: [xfail-red-scaffold, mock-store-fixture, integration-marker-gating]
key_files:
  created:
    - tests/unit/test_qdrant_hybrid.py
    - tests/integration/test_qdrant_hybrid_migration.py
  modified: []
decisions:
  - "Used xfail(strict=False) for all RED tests — allows clean collection and suite-green while Plan 10-06/10-07 implement the features"
  - "Reused __new__ + MagicMock fixture pattern from test_qdrant_payload_indexes.py for self-contained unit tests"
  - "Reused store/alias fixture pattern from test_qdrant_alias_reindex.py for integration tests"
  - "test_upsert_legacy_shape asserts _is_named was called to verify the shape-branching logic exists (prevents false-pass on current implementation)"
metrics:
  duration: "6m 8s"
  completed: "2026-07-10T05:15:16Z"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
status: complete
---

# Phase 10 Plan 01: RED Test Scaffold for Hybrid Retrieval Summary

Wave 0 RED test scaffold establishing the RETR-01 store + migration acceptance contract for Plans 10-06 and 10-07. Created 6 unit tests (mock-client) and 5 integration tests (live-Qdrant) that collect cleanly and define the concrete automated targets for named-vector creation, hybrid prefetch/RRF assembly, server preflight, upsert shape branching, and the re-embedding migration.

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | 0d896ab | test(10-01): add RED unit scaffold for hybrid retrieval store (RETR-01) |
| 2 | 8c79b10 | test(10-01): add RED integration scaffold for hybrid migration (RETR-01) |

## Task Details

### Task 1: Unit RED scaffold

Created `tests/unit/test_qdrant_hybrid.py` with 6 test functions:
- `test_named_create_config` — asserts named dense+sparse create-path (D-05, D-13)
- `test_get_dim_named` — asserts get_collection_dim handles named vector dict (Pitfall 2)
- `test_hybrid_prefetch_limits` — asserts prefetch branches + RRF (D-11, D-12, D-14)
- `test_server_preflight` — asserts RuntimeError on server < 1.10 (D-07)
- `test_upsert_named_shape` — asserts dict vector with dense+sparse keys (D-09)
- `test_upsert_legacy_shape` — asserts bare list vector + _is_named branch (D-09)

All 6 report as xfailed; full unit suite remains green (383 passed).

### Task 2: Integration RED scaffold

Created `tests/integration/test_qdrant_hybrid_migration.py` with 5 test functions:
- `test_reembed_parity` — count parity gate before alias swap (D-06)
- `test_all_points_have_sparse` — all migrated points carry sparse vector (D-05)
- `test_idf_modifier_set` — Modifier.IDF on sparse vector config (D-13)
- `test_payload_indexes_survive` — keyword indexes survive named recreate (D-14)
- `test_dense_both_shapes` — dense search works on legacy + named (D-09)

Module carries `pytestmark = pytest.mark.integration` so tests are excluded from default unit runs. All 5 collect cleanly.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_upsert_legacy_shape false-pass prevention**
- **Found during:** Task 1
- **Issue:** The test initially xpassed because the current `upsert()` already passes bare vectors — the test didn't actually verify the shape-branching logic.
- **Fix:** Added `store._is_named.assert_called()` to require the branching helper to be consulted, ensuring the test stays RED until Plan 10-06 adds the `_is_named` branch.
- **Files modified:** tests/unit/test_qdrant_hybrid.py
- **Commit:** 0d896ab

## Verification Results

| Check | Result |
|-------|--------|
| `pytest tests/unit/test_qdrant_hybrid.py -q` | 6 xfailed, exit 0 |
| `pytest tests/integration/test_qdrant_hybrid_migration.py --collect-only -q` | 5 collected, 0 errors |
| `pytest tests/unit -q` | 383 passed, 7 xfailed, full suite green |

## Self-Check: PASSED

- [x] `tests/unit/test_qdrant_hybrid.py` exists
- [x] `tests/integration/test_qdrant_hybrid_migration.py` exists
- [x] Commit 0d896ab found in git log
- [x] Commit 8c79b10 found in git log
