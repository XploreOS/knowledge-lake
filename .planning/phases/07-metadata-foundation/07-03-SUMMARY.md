---
phase: 07-metadata-foundation
plan: "03"
subsystem: vector-store
tags: [qdrant, payload-indexes, search-filters, tdd, unit-test, pytest, MatchAny]

requires:
  - phase: 07-metadata-foundation
    plan: "01"
    provides: RED-state test scaffold for ensure_payload_indexes (3 failing tests)

provides:
  - QdrantVectorStore.ensure_payload_indexes(collection: str) -> None with 7 KEYWORD fields
  - ensure_aliased_collection() wired: calls ensure_payload_indexes(physical) before return
  - reindex() wired: calls ensure_payload_indexes(next_physical) after upsert_fn, before alias swap
  - search() extended with source_name, format, tags, source_id kwargs; MatchAny for multi-tag
  - TestSearchSourceFilters class with 7 GREEN tests

affects:
  - 07-04-PLAN.md (CLI/API surface delegates to search() with new filter kwargs)

tech-stack:
  added: []
  patterns:
    - "ensure_payload_indexes uses lazy import of PayloadSchemaType inside method body — mirrors existing lazy import style in the class"
    - "tags filter: single tag uses MatchValue; multiple tags uses MatchAny (D-11)"
    - "ensure_payload_indexes always receives physical collection name, never the alias (Pitfall 1)"
    - "format parameter uses # noqa: A002 to silence builtin-shadowing linter warning"

key-files:
  created: []
  modified:
    - src/knowledge_lake/plugins/builtin/qdrant_store.py
    - src/knowledge_lake/pipeline/search.py
    - tests/unit/test_search_filters.py

key-decisions:
  - "ensure_payload_indexes uses lazy local import of PayloadSchemaType to mirror existing qdrant_store.py lazy import pattern"
  - "_KEYWORD_FIELDS list defined inside ensure_payload_indexes method: 7 fields (domain, document_type, source_name, format, source_id, tags, keywords)"
  - "tags filter uses MatchValue for single-element list and MatchAny for multi-element list (D-11, per RESEARCH.md Pattern 3)"
  - "format as kwarg name accepted despite shadowing builtin: builtin not used in function scope, noqa comment added"
  - "search() D-13 backward-compat note added to docstring: new filter kwargs only effective on points indexed after Phase 7"

requirements-completed:
  - PAYLOAD-02

coverage:
  - id: D1
    description: "ensure_payload_indexes() added to QdrantVectorStore with 7 KEYWORD fields; 3 RED tests from Plan 01 now GREEN"
    requirement: PAYLOAD-02
    verification:
      - kind: unit
        ref: "tests/unit/test_qdrant_payload_indexes.py (3 tests GREEN)"
        status: pass
    human_judgment: false
  - id: D2
    description: "ensure_aliased_collection() calls ensure_payload_indexes(physical) before return (D-08)"
    requirement: PAYLOAD-02
    verification:
      - kind: unit
        ref: "tests/unit/test_qdrant_payload_indexes.py::TestEnsureAliasedCollectionCallsIndexes"
        status: pass
    human_judgment: false
  - id: D3
    description: "reindex() calls ensure_payload_indexes(next_physical) after upsert_fn, before alias swap (D-08, Pitfall 4)"
    requirement: PAYLOAD-02
    verification:
      - kind: unit
        ref: "tests/unit/test_qdrant_payload_indexes.py::TestReindexCallsIndexes"
        status: pass
    human_judgment: false
  - id: D4
    description: "search() accepts source_name, format, source_id, tags kwargs; tags uses MatchAny for multi-value (D-10, D-11)"
    requirement: PAYLOAD-02
    verification:
      - kind: unit
        ref: "tests/unit/test_search_filters.py::TestSearchSourceFilters (7 tests GREEN)"
        status: pass
    human_judgment: false
  - id: D5
    description: "No regressions: 339 unit tests pass after all changes"
    requirement: PAYLOAD-02
    verification:
      - kind: unit
        ref: "uv run pytest tests/unit/ -q — 339 passed, 20 xpassed"
        status: pass
    human_judgment: false

duration: 3min
completed: 2026-07-08
status: complete
---

# Phase 07 Plan 03: Metadata Foundation — Payload Index Implementation Summary

**PAYLOAD-02 implementation: ensure_payload_indexes() added to QdrantVectorStore with 7 KEYWORD fields; wired in ensure_aliased_collection() and reindex(); search() extended with 4 new filter kwargs using MatchAny for multi-tag; all 15 tests GREEN including 7 new TestSearchSourceFilters tests**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-07-08T07:43:26Z
- **Completed:** 2026-07-08T07:46:30Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Added `ensure_payload_indexes(self, collection: str) -> None` to `QdrantVectorStore` with 7 KEYWORD fields: domain, document_type, source_name, format, source_id, tags, keywords
- Wired `ensure_payload_indexes(physical)` call in `ensure_aliased_collection()` before the return (D-08)
- Wired `ensure_payload_indexes(next_physical)` call in `reindex()` after `upsert_fn()` and before the alias swap (D-08, Pitfall 4 ordering)
- Updated module docstring to document `ensure_payload_indexes()`
- Turned 3 RED tests from Plan 01 GREEN (PAYLOAD-02)
- Added `MatchAny` to `search.py` imports (Pitfall 2 prevention from RESEARCH.md)
- Extended `search()` with 4 new kwargs: `source_name`, `format`, `tags`, `source_id`
- Implemented tags filter branching: single tag → `MatchValue`, multiple tags → `MatchAny` (D-11)
- Updated `search()` docstring with 4 new param descriptions and D-13 backward-compat note
- Added `TestSearchSourceFilters` class to `test_search_filters.py` with 7 new tests
- All 339 unit tests pass, no regressions

## Task Commits

1. **Task 1: Add ensure_payload_indexes() to QdrantVectorStore and wire call sites** — `41d4719` (feat)
2. **Task 2: Extend search() with 4 new filter kwargs and add TestSearchSourceFilters** — `d1e8e41` (feat)

## Files Created/Modified

- `src/knowledge_lake/plugins/builtin/qdrant_store.py` — `ensure_payload_indexes()` method added (lines ~142-176); call wired in `ensure_aliased_collection()` and `reindex()`; module docstring updated
- `src/knowledge_lake/pipeline/search.py` — `MatchAny` added to import; 4 new kwargs in `search()` signature; 4 new filter if-blocks; `log.info` updated; docstring extended
- `tests/unit/test_search_filters.py` — `MatchAny` added to import; `TestSearchSourceFilters` class with 7 methods added after `TestSearchCombinedFilters`

## Decisions Made

- `ensure_payload_indexes` uses a lazy local import `from qdrant_client.models import PayloadSchemaType` inside the method body — mirrors the existing lazy import style for `CreateAlias`/`DeleteAlias` elsewhere in the class
- `_KEYWORD_FIELDS` defined as a local list inside the method: `["domain", "document_type", "source_name", "format", "source_id", "tags", "keywords"]` (7 fields)
- `format` as a parameter name accepted despite shadowing Python builtin `format` — builtin is not used inside the function scope; `# noqa: A002` comment added as noted in the plan
- D-13 backward-compat note added to docstring: new filters only effective on points indexed after Phase 7

## Deviations from Plan

None — plan executed exactly as written. All acceptance criteria met.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Plan 04: CLI/API surface can delegate to `search()` using the new `source_name`, `format`, `tags`, `source_id` kwargs without any search.py changes needed

## Known Stubs

None — all filter kwargs are wired to real FieldCondition/MatchValue/MatchAny objects.

## Threat Flags

No new trust boundaries introduced. Per T-07-03-01/02/03 in plan threat model:
- T-07-03-01 (collection name in ensure_payload_indexes): accepted at low severity — collection_name is already validated at API boundary
- T-07-03-02 (tags list DoS): plan notes max_length=64 enforcement deferred to Plan 04 API boundary — documented as known gap
- T-07-03-03 (filter injection): accepted — Qdrant FieldCondition/MatchValue/MatchAny are strongly-typed model objects with no string concatenation

## Self-Check

- [x] `src/knowledge_lake/plugins/builtin/qdrant_store.py` contains `def ensure_payload_indexes`
- [x] `ensure_payload_indexes` appears 3 times in qdrant_store.py: definition + 2 call sites (5 total including module docstring + loop body)
- [x] `_KEYWORD_FIELDS` defined in qdrant_store.py
- [x] `src/knowledge_lake/pipeline/search.py` imports `MatchAny` (2+ hits: import + usage)
- [x] `search.py` contains `source_name: Optional[str] = None` in function signature
- [x] `search.py` contains `tags: Optional[list[str]] = None` in function signature
- [x] `tests/unit/test_search_filters.py` contains `class TestSearchSourceFilters`
- [x] `uv run pytest tests/unit/test_qdrant_payload_indexes.py -v` — 3 tests PASS (GREEN from RED)
- [x] `uv run pytest tests/unit/test_search_filters.py -v` — 12 tests PASS (5 existing + 7 new)
- [x] `uv run pytest tests/unit/ -q` — 339 passed, 20 xpassed, no regressions
- [x] Task 1 commit: `41d4719`
- [x] Task 2 commit: `d1e8e41`

## Self-Check: PASSED

---
*Phase: 07-metadata-foundation*
*Completed: 2026-07-08*
