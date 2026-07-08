---
phase: 07-metadata-foundation
plan: "01"
subsystem: testing
tags: [qdrant, payload-indexes, tdd, unit-test, pytest]

requires:
  - phase: 06-dagster-domain
    provides: QdrantVectorStore with ensure_aliased_collection and reindex methods

provides:
  - RED-state test scaffold for ensure_payload_indexes() on QdrantVectorStore
  - 3 failing test classes asserting call contracts for D-07/D-08/D-09

affects:
  - 07-03-PLAN.md (turns these tests GREEN by adding ensure_payload_indexes implementation)

tech-stack:
  added: []
  patterns:
    - "QdrantVectorStore.__new__ fixture pattern: bypasses __init__ to avoid real Qdrant connection in unit tests"
    - "monkeypatch.setattr(store, method, MagicMock()) for method-level call assertion on instances"

key-files:
  created:
    - tests/unit/test_qdrant_payload_indexes.py
  modified: []

key-decisions:
  - "mock_store fixture uses QdrantVectorStore.__new__ to bypass __init__; sets _client/_Distance/_PointStruct/_VectorParams as MagicMock — mirrors test_builtin_plugins.py style"
  - "7 fields asserted in TestEnsurePayloadIndexes: domain, document_type, source_name, format, source_id, tags, keywords (keywords added per RESEARCH.md Open Question 2 resolution)"

patterns-established:
  - "Pattern: QdrantVectorStore unit test fixture uses __new__ + manual attribute injection to avoid live client"

requirements-completed:
  - PAYLOAD-02

coverage:
  - id: D1
    description: "tests/unit/test_qdrant_payload_indexes.py created with 3 test classes in RED state — collected by pytest without import errors, all fail as expected until Plan 03 adds ensure_payload_indexes"
    requirement: PAYLOAD-02
    verification:
      - kind: unit
        ref: "tests/unit/test_qdrant_payload_indexes.py (3 tests FAIL — RED state confirmed)"
        status: fail
    human_judgment: false

duration: 2min
completed: 2026-07-08
status: complete
---

# Phase 07 Plan 01: Metadata Foundation — Test Scaffold Summary

**RED-state pytest scaffold for ensure_payload_indexes() with 3 failing test classes asserting call contracts for Qdrant payload index creation (D-07/D-08/D-09)**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-07-08T07:31:10Z
- **Completed:** 2026-07-08T07:33:30Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Created `tests/unit/test_qdrant_payload_indexes.py` with 3 test classes collected by pytest without import errors
- All 3 tests fail in RED state with AttributeError (ensure_payload_indexes method does not exist yet)
- No regressions in existing 324 unit tests
- Fixture uses `QdrantVectorStore.__new__` pattern — no real Qdrant server connection required

## Task Commits

1. **Task 1: Create test_qdrant_payload_indexes.py scaffold (RED state)** — `9177481` (test)

## Files Created/Modified

- `tests/unit/test_qdrant_payload_indexes.py` — 3 test classes: TestEnsurePayloadIndexes (asserts 7 create_payload_index calls), TestEnsureAliasedCollectionCallsIndexes (asserts call on new physical), TestReindexCallsIndexes (asserts call on next physical)

## Decisions Made

- 7 fields asserted in TestEnsurePayloadIndexes — includes `keywords` (not in PAYLOAD-02 gating criteria but noted in RESEARCH.md Open Question 2 as resolved addition; zero extra cost to include in RED test now)
- mock_store fixture uses `QdrantVectorStore.__new__` to bypass `__init__` — consistent with existing test harness patterns in `test_builtin_plugins.py`

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Plan 02 can proceed in parallel (extends test_index_payload.py and test_search_filters.py — independent of this file)
- Plan 03 depends on this file to turn RED tests GREEN by implementing `ensure_payload_indexes()` and wiring call sites

## Self-Check

- [x] `tests/unit/test_qdrant_payload_indexes.py` exists
- [x] 3 tests collected without errors
- [x] All 3 tests FAIL (RED state — AttributeError on missing method)
- [x] 324 existing unit tests still pass

---
*Phase: 07-metadata-foundation*
*Completed: 2026-07-08*
