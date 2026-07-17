---
phase: 21-index-time-dedup
plan: 06
subsystem: pipeline
tags: [dedup, qdrant, process, cli-api-mcp]

# Dependency graph
requires:
  - phase: 21-index-time-dedup (Plan 04)
    provides: "dedup_chunks(chunks, parsed_artifact_id, source_id, *, collection, settings=None) -> dict router function"
  - phase: 21-index-time-dedup (Plan 05)
    provides: "index()'s duplicate_chunks kwarg — contributor append, capped mirror, self-heal"
provides:
  - "process_crawled() (CLI/API/MCP shared entry point) now calls dedup_chunks() between chunk() and embed()/index()"
  - "embed() on this path receives only first-seen chunk text (dedup_result['new'])"
  - "index() on this path receives duplicate_chunks=dedup_result['duplicates']"
affects: [21-07-dagster-asset-wiring, 21-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "dedup_chunks() call site inserted immediately after the existing empty-chunks-list guard (never called with an empty list); embed()/index() downstream both consume dedup_result's new/duplicates buckets instead of the raw chunks_list"

key-files:
  created:
    - tests/unit/test_process_crawled_dedup.py
  modified:
    - src/knowledge_lake/pipeline/process.py
    - tests/unit/test_process_crawled_clean.py

key-decisions:
  - "Extended 5 existing test_process_crawled_clean.py tests (that mock chunk()/embed()/index() but not dedup_chunks) with a pass-through dedup_chunks mock (return_value={'new': chunks, 'duplicates': []}) — dedup_chunks() is now a real, unmocked stage in process_crawled()'s call chain and its production code reads chunk['text'], which those tests' bare {'chunk_id': 'c1'} mock dicts never carried. Without this fix all 5 tests would fail with KeyError('text') on the very first test run after wiring, even though this plan's own <files_modified> frontmatter didn't list test_process_crawled_clean.py — a Rule 3 (blocking issue) fix scoped entirely to keeping pre-existing tests green through the new required stage, not a behavior change to those tests' actual assertions."

requirements-completed: [DEDUP-01]

coverage:
  - id: D1
    description: "dedup_chunks() is called with the exact chunks_list object chunk() returned, plus parsed_id/src_id positionally and collection= as a keyword"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_process_crawled_dedup.py::TestProcessCrawledDedupWiring::test_dedup_chunks_called_with_chunks_list_identity_and_ids"
        status: pass
    human_judgment: false
  - id: D2
    description: "embed() is called with dedup_result['new'] specifically — never chunks_list, never dedup_result['duplicates']"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_process_crawled_dedup.py::TestProcessCrawledDedupWiring::test_embed_receives_dedup_new_not_chunks_list_not_duplicates"
        status: pass
    human_judgment: false
  - id: D3
    description: "index() is called with dedup_result['new'] as its first (chunks) argument and duplicate_chunks=dedup_result['duplicates']"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_process_crawled_dedup.py::TestProcessCrawledDedupWiring::test_index_receives_dedup_new_and_duplicate_chunks_kwarg"
        status: pass
    human_judgment: false
  - id: D4
    description: "chunk() returning an empty list still hits the pre-existing empty-guard branch and dedup_chunks() is never called for that document"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_process_crawled_dedup.py::TestProcessCrawledDedupBoundaries::test_empty_chunks_list_skips_dedup_chunks_entirely"
        status: pass
    human_judgment: false
  - id: D5
    description: "dedup_chunks() returning {'new': [], 'duplicates': [...]} (all-duplicates document) still calls embed([]) and index([], ..., duplicate_chunks=[...]) — not skipped"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_process_crawled_dedup.py::TestProcessCrawledDedupBoundaries::test_all_duplicates_still_calls_embed_and_index"
        status: pass
    human_judgment: false
  - id: D6
    description: "No regression in the existing CLEAN-02/domain-filters test suite for process_crawled() after dedup_chunks() becomes a real required stage"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_process_crawled_clean.py (7 tests, extended with pass-through dedup_chunks mocks)"
        status: pass
      - kind: unit
        ref: "tests/unit (full suite): 959 passed, 1 xfailed"
        status: pass
    human_judgment: false

# Metrics
duration: 8min
completed: 2026-07-17
status: complete
---

# Phase 21 Plan 06: process_crawled() dedup_chunks() Wiring Summary

**`process_crawled()` (the CLI/API/MCP shared entry point) now routes every chunk through `dedup_chunks()` between `chunk()` and `embed()`/`index()`, embedding only first-seen text and threading duplicates into `index()`'s `duplicate_chunks` kwarg — closing DEDUP-01's dead-code gap on the non-Dagster path.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-17T13:19:50Z
- **Completed:** 2026-07-17T13:27:23Z
- **Tasks:** 1 completed
- **Files modified:** 3 (2 modified, 1 created)

## Accomplishments
- `process.py`'s `chunk() -> embed() -> index()` chain became `chunk() -> empty-guard -> dedup_chunks() -> embed(new only) -> index(new, ..., duplicate_chunks=duplicates)`
- `dedup_chunks()` added to `process_crawled()`'s existing block of function-local imports, alongside `chunk`/`clean`/`embed`/`index`/`parse`
- The pre-existing `if not chunks_list: processed += 1; continue` guard is untouched — `dedup_chunks()` is never called with an empty list
- `total_chunks` continues to count chunks PRODUCED by `chunk()` (unchanged metric definition), independent of how many were embedded vs. deduped
- New `tests/unit/test_process_crawled_dedup.py` mirrors `test_process_crawled_clean.py`'s exact fixture chain (`engine`/`_patch_engine`/`source`/`_seed_raw_document`) and source-module patching convention (`knowledge_lake.pipeline.dedup.dedup_chunks`, not `knowledge_lake.pipeline.process`'s namespace) — proves all 5 `<behavior>` items via call-order/argument-identity assertions
- True TDD RED/GREEN split: RED commit's 4/5 new tests failed against the pre-wiring `process.py` (confirmed by temporarily reverting the implementation and re-running); GREEN commit reapplies the wiring and all 12 tests (5 new + 7 existing) pass

## Task Commits

Task 1 is `tdd="true"`, executed as a true RED -> GREEN pair:

1. **Task 1 (TDD RED): failing tests for dedup_chunks() wiring** - `5b482de` (test)
2. **Task 1 (TDD GREEN): wire dedup_chunks() into process_crawled()** - `3876e71` (feat)

**Plan metadata:** (this commit)

_Note: No REFACTOR commit was needed — the GREEN implementation matched the plan's exact specified shape with only the test-file deviation described below._

## Files Created/Modified
- `src/knowledge_lake/pipeline/process.py` - Added `dedup_chunks` import; inserted `dedup_result = dedup_chunks(chunks_list, parsed_id, src_id, collection=collection)` after the empty-chunks guard; `embed()`/`index()` now consume `dedup_result["new"]`/`dedup_result["duplicates"]`; module docstring gained a DEDUP-01 note mirroring the existing CLEAN-02 note
- `tests/unit/test_process_crawled_dedup.py` - New file: `TestProcessCrawledDedupWiring` (3 tests: chunks_list identity + parsed_id/src_id/collection, embed() receives dedup new only, index() receives new + duplicate_chunks=) and `TestProcessCrawledDedupBoundaries` (2 tests: empty-chunks-list skips dedup_chunks entirely, all-duplicates batch still calls embed()/index())
- `tests/unit/test_process_crawled_clean.py` - 5 pre-existing tests (3 in `TestProcessCrawledCleanWiring`, 2 in `TestProcessCrawledDomainFilters`) extended with a pass-through `dedup_chunks` mock so they keep passing now that `dedup_chunks()` is a real stage in the call chain

## Decisions Made
- Extended 5 existing `test_process_crawled_clean.py` tests with a pass-through `dedup_chunks` mock (`return_value={"new": chunks, "duplicates": []}`) rather than leaving them unmodified as the plan's acceptance criteria implied. `dedup_chunks()`'s real implementation reads `chunk["text"]` from every chunk dict; those 5 tests mock `chunk()` to return bare `{"chunk_id": "c1"}` dicts with no `"text"` key, so once `dedup_chunks()` became a real (unmocked) stage in the chain, each of those tests raised `KeyError: 'text'` before this fix. This is a Rule 3 (blocking issue) auto-fix scoped entirely to keeping pre-existing tests green through the newly-required stage — no assertion in those tests was changed, only the mock set was extended to cover the new call.
- Kept the module docstring update (new DEDUP-01 paragraph) as an additive note mirroring the existing CLEAN-02 paragraph's style, for future-reader parity between the two stage-insertion patterns in this same function.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Extended 5 test_process_crawled_clean.py tests with a pass-through dedup_chunks mock**
- **Found during:** Task 1 (GREEN implementation — running `test_process_crawled_clean.py` after wiring `dedup_chunks()` into `process.py`)
- **Issue:** The plan's acceptance criteria state "No existing test in `test_process_crawled_clean.py` regresses (dedup_chunks is mocked/patched in this NEW test file only; the clean-stage tests are untouched by this plan)". In practice, once `dedup_chunks()` became a real (unmocked) stage in `process_crawled()`'s call chain, every existing test that mocks `chunk()` to return `[{"chunk_id": "c1"}]` (no `"text"` key) hit `dedup_chunks()`'s real `text_sha256_for(chunk["text"])` call and raised `KeyError: 'text'` — a genuine regression the plan's own wiring instructions caused, contradicting the "untouched" expectation.
- **Fix:** Added a pass-through `mock_dedup = MagicMock(return_value={"new": [{"chunk_id": "c1"}], "duplicates": []})` plus its `patch("knowledge_lake.pipeline.dedup.dedup_chunks", mock_dedup)` to the 5 affected tests (3 in `TestProcessCrawledCleanWiring`, 2 in `TestProcessCrawledDomainFilters`). The 2 tests that don't reach `dedup_chunks()` (clean() raising before chunk() is called; chunk() returning `[]`) were left untouched, matching the plan's original expectation exactly for those cases.
- **Files modified:** tests/unit/test_process_crawled_clean.py
- **Verification:** `uv run pytest tests/unit/test_process_crawled_dedup.py tests/unit/test_process_crawled_clean.py -q` — 12 passed. Full suite: `uv run pytest tests/unit -q` — 959 passed, 1 xfailed, 0 failed.
- **Committed in:** 5b482de (RED/test commit, alongside the new test file — no behavior change to production code in this commit)

---

**Total deviations:** 1 auto-fixed (1 blocking test-regression fix)
**Impact on plan:** Purely test-side (extending mock coverage in 5 tests with a pass-through dedup_chunks mock); no production code behavior changed beyond what the plan's own `<action>` specified. No scope creep.

## Issues Encountered

None beyond the test-regression fix described above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `process_crawled()` is fully wired: the CLI/API/MCP shared path now dedupes chunk text at index time, mirroring the same `dedup_chunks()`/`index(duplicate_chunks=...)` contract Plans 21-04/21-05 built
- Full unit test suite (959 passed, 1 xfailed) green after this plan's changes — no regressions
- Plan 21-07 (Dagster asset call-site wiring) can follow the identical pattern established here
- No blockers identified

---
*Phase: 21-index-time-dedup*
*Completed: 2026-07-17*

## Self-Check: PASSED

All modified/created files confirmed present on disk; both commit hashes (5b482de, 3876e71) confirmed present in git log.
