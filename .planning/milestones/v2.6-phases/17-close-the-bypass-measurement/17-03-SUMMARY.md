---
phase: 17-close-the-bypass-measurement
plan: 03
subsystem: pipeline
tags: [clean, boilerplate, cli, api, mcp, process-crawled, quality-audit]

# Dependency graph
requires:
  - phase: 17-01
    provides: "clean() accepts an optional in-memory parsed_doc kwarg and always returns a cleaned_doc key; WR-05 parent-scoped content_hash"
provides:
  - "process_crawled (CLI/API/MCP shared entry point) threads its in-memory parsed_doc into clean(parsed_id, src_id, parsed_doc=parsed_doc) and passes clean_result['cleaned_doc'] (not the raw parsed_doc) as chunk()'s third argument"
  - "Test proof (test_process_crawled_clean.py) that clean() sits between parse() and chunk(), chunk() never re-parents to the cleaned artifact, clean() failures fall into the existing failed-count path, and the empty-chunks boundary is absorbed by the existing continue branch"
affects: [17-04-quality-audit, 18-gate-decouple]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Function-local pipeline-stage imports (parse/clean/chunk/embed/index imported inside process_crawled's body, not at module level) require test mocks to patch the SOURCE module each stage function lives in, not the consuming module's namespace — the route.py 'patch the consumer' gotcha only applies to module-level imports"

key-files:
  created:
    - tests/unit/test_process_crawled_clean.py
  modified:
    - src/knowledge_lake/pipeline/process.py

key-decisions:
  - "Deviated from the plan's read_first mocking guidance: patched the SOURCE modules (knowledge_lake.pipeline.parse.parse, .clean.clean, .chunk.chunk, .embed.embed, .index.index) instead of knowledge_lake.pipeline.process.parse/.clean/.chunk/.embed/.index, because process_crawled imports these functions as FUNCTION-LOCAL imports (inside the function body, executed fresh each call) rather than module-level imports — patching the consuming module's namespace raises AttributeError since process.py never carries those names as module attributes (verified empirically before writing the test file)."
  - "Split Task 1's tdd=true work into a true RED/GREEN pair (3 tests, then the process.py change) and Task 2's boundary tests into a separate, immediately-green test commit, matching the plan's task boundaries exactly rather than writing all 5 tests in one pass."

requirements-completed: [CLEAN-02]

coverage:
  - id: D1
    description: "process_crawled calls clean(parsed_id, src_id, parsed_doc=parsed_doc) between parse() and chunk(), and passes clean_result['cleaned_doc'] (not the raw parsed_doc) as chunk()'s third argument; chunk()'s parsed_artifact_id stays unchanged"
    requirement: "CLEAN-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_process_crawled_clean.py::TestProcessCrawledCleanWiring::test_clean_called_with_parse_result_parsed_doc"
        status: pass
      - kind: unit
        ref: "tests/unit/test_process_crawled_clean.py::TestProcessCrawledCleanWiring::test_chunk_receives_cleaned_doc_not_raw_parsed_doc"
        status: pass
      - kind: unit
        ref: "tests/unit/test_process_crawled_clean.py::TestProcessCrawledCleanWiring::test_chunk_parsed_artifact_id_unchanged"
        status: pass
    human_judgment: false
  - id: D2
    description: "process_crawled's existing except Exception block absorbs clean()'s ValueError failure mode into result['failed'] with no new except-branch and no propagated exception"
    requirement: "CLEAN-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_process_crawled_clean.py::TestProcessCrawledCleanBoundaries::test_clean_failure_counted_as_failed_not_processed"
        status: pass
    human_judgment: false
  - id: D3
    description: "A document whose cleaned sections produce zero chunks still increments result['processed'] via the existing 'if not chunks_list: processed += 1; continue' branch, with embed()/index() never called"
    requirement: "CLEAN-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_process_crawled_clean.py::TestProcessCrawledCleanBoundaries::test_empty_chunks_still_counted_processed_no_embed_index"
        status: pass
    human_judgment: false

duration: 8min
completed: 2026-07-16
status: complete
---

# Phase 17 Plan 03: Close the Bypass — process_crawled CLI/API/MCP Parity Summary

**Inserted `clean()` between `parse()` and `chunk()` inside `pipeline/process.py::process_crawled` — the single function shared by CLI, API, and MCP entry points — closing the CLI half of the clean-stage bypass with zero new failure modes.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-16T05:07:33Z (prior plan completion timestamp)
- **Completed:** 2026-07-16T05:15:00Z
- **Tasks:** 2
- **Files modified:** 2 (`src/knowledge_lake/pipeline/process.py`, `tests/unit/test_process_crawled_clean.py`)

## Accomplishments

- `process_crawled()` now calls `clean(parsed_id, src_id, parsed_doc=parsed_doc)` immediately after `parse()`, and passes `clean_result["cleaned_doc"]` — not the raw `parsed_doc` — as `chunk()`'s third positional argument. `chunk()`'s first argument (`parsed_artifact_id`) stays `parsed_id`, unchanged: chunks are never re-parented to the cleaned artifact.
- No new `except` branch was added: `clean()`'s call sits inside the same per-document `try:` block that already catches `parse`/`chunk`/`embed`/`index` failures into `result["failed"]` — proven by a dedicated failure-path test that mocks `clean()` raising `ValueError` (its documented exception) and asserts `process_crawled()` does not propagate it.
- The CLEAN-02 empty-sections boundary case (a document whose cleaned sections all clean down to empty text, so `chunk()` returns `[]`) is absorbed by the pre-existing `if not chunks_list: processed += 1; continue` branch with no code change needed — proven by a test asserting `embed()`/`index()` are never called for that document.
- `klake process` (`process_crawled`) now has full parity with Plan 17-02's Dagster `clean_document -> chunk_document` path: both routes clean text before chunking, closing the exact CLI code path the original 28%-garbage audit ran against.
- Zero regressions: full suite (`tests/unit` + `tests/integration`) — 982 passed, 3 skipped, 6 xfailed, 0 failed.

## Task Commits

1. **Task 1: Insert clean() into process_crawled's parse-chunk pipeline** (tdd=true, full RED → GREEN cycle)
   - `290a34a` (test) — RED: 3 failing tests for clean()-wiring call order and argument identity
   - `9e0a225` (feat) — GREEN: `clean()` inserted between `parse()` and `chunk()`, `cleaned_doc` threaded to `chunk()`
2. **Task 2: Error-handling parity and empty-sections boundary tests**
   - `9294d50` (test) — 2 additional tests proving the existing except/continue branches absorb `clean()`'s new failure mode and empty-chunks case with no new branch (both passed immediately since Task 1's GREEN commit already implements the correct behavior)

**Plan metadata:** (this commit, following)

## Files Created/Modified

- `src/knowledge_lake/pipeline/process.py` — added `from knowledge_lake.pipeline.clean import clean` to the local-import block; inserted `clean_result = clean(parsed_id, src_id, parsed_doc=parsed_doc)` / `cleaned_doc = clean_result["cleaned_doc"]` between `parse()` and `chunk()`; changed `chunk(parsed_id, src_id, parsed_doc)` to `chunk(parsed_id, src_id, cleaned_doc)`; updated docstrings (`parse→clean→chunk→embed→index`) to reflect the new stage.
- `tests/unit/test_process_crawled_clean.py` (new) — `TestProcessCrawledCleanWiring` (3 tests: clean() called with parse's returned object, chunk() receives cleaned_doc not raw parsed_doc, parsed_artifact_id unchanged) and `TestProcessCrawledCleanBoundaries` (2 tests: clean() ValueError counted as failed not processed, empty-chunks case counted as processed with embed/index never called). Uses an in-memory SQLite engine (mirrors `test_clean_silver_key.py`'s fixture pattern) with a real seeded `raw_document` artifact, mocking only the pipeline-stage functions at their SOURCE modules.

## Decisions Made

- **Patched source modules, not the consuming module's namespace.** The plan's `<read_first>` pointed at the `pipeline/route.py` standing gotcha (patch the consumer's namespace because `from ... import search` binds at *module* import time). `process_crawled`'s imports are FUNCTION-LOCAL (`from knowledge_lake.pipeline.clean import clean` runs fresh inside the function body on every call), so `process.py` never has `parse`/`clean`/`chunk`/`embed`/`index` as module-level attributes — `patch("knowledge_lake.pipeline.process.clean")` raises `AttributeError` (verified empirically with a throwaway script before writing tests). The correct interception point for a function-local import is the SOURCE module the import statement reads from at call time (`knowledge_lake.pipeline.clean.clean`, etc.), which is what the shipped test file patches. This is documented in the test file's module docstring so a future reader isn't misled by the same gotcha reference.
- **Used a real in-memory SQLite-backed registry (not a fully mocked session)** for `get_session()`/`Artifact` queries, following the same `monkeypatch.setattr(registry_db, "get_engine", lambda: engine)` fixture pattern as `test_clean_silver_key.py`, since `process_crawled` builds its `unprocessed` query via real SQLAlchemy `select()`/`aliased()` constructs that a raw session mock would need to reimplement query semantics for — a real (if tiny) DB is simpler and closer to production behavior.
- **Split Task 1 and Task 2 into separate commits matching the plan's task boundaries** rather than writing all 5 tests in one pass: Task 1 (tdd=true) got a genuine RED (3 failing tests against unmodified `process.py`) → GREEN (implementation) cycle; Task 2's 2 boundary tests were added and committed afterward, passing immediately since they only exercise Task 1's already-shipped behavior.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected the mocking target from the plan's literal read_first pointer**
- **Found during:** Task 1 (writing the RED test file)
- **Issue:** The plan's `<read_first>` instructed patching at `knowledge_lake.pipeline.process.clean` (the consuming module's namespace), citing the `pipeline/route.py` module-level-import gotcha in STATE.md. `process_crawled` imports `parse`/`clean`/`chunk`/`embed`/`index` as FUNCTION-LOCAL imports, not module-level imports — `process.py` never carries those names as module attributes, so patching that target raises `AttributeError` at test-collection time (`does not have the attribute 'parse'`), a different failure mode than the gotcha it was citing.
- **Fix:** Patched the SOURCE modules instead (`knowledge_lake.pipeline.parse.parse`, `.clean.clean`, `.chunk.chunk`, `.embed.embed`, `.index.index`), which correctly intercepts the local `from X import Y` statement's read at call time. Verified with a throwaway script confirming both the failure mode of the plan's literal target and the success of the source-module target before writing any test.
- **Files modified:** tests/unit/test_process_crawled_clean.py (module docstring documents the deviation and reasoning inline for future readers)
- **Verification:** All 5 tests pass; full suite (982 passed, 0 failed) confirms no collateral breakage.
- **Committed in:** `290a34a` (Task 1 RED test commit)

---

**Total deviations:** 1 auto-fixed (1 bug/blocking — mocking target correction)
**Impact on plan:** Necessary correction to make the plan's specified test behaviors executable at all; no scope creep, no change to the plan's required behaviors or acceptance criteria — all of which are met.

## Issues Encountered

None beyond the mocking-target deviation documented above, which was caught and resolved before any commit (RED test run failed for the *correct* reason — clean() not yet called — confirming the fix was sound before proceeding to GREEN).

## Next Phase Readiness

- CLEAN-02's caller-side wiring is now complete on both routes: Plan 17-02 (Dagster `clean_document`) and this plan (`process_crawled` CLI/API/MCP). Plan 17-04 (quality-audit) can measure post-clean chunk quality from either entry point with the same guarantee — no shortcut remains where a caller-side path bypasses the clean stage.
- No blockers. Full unit + integration suite (982 passed, 3 skipped, 6 xfailed, 0 failed) green; zero regressions.

---
*Phase: 17-close-the-bypass-measurement*
*Completed: 2026-07-16*

## Self-Check: PASSED

- FOUND: src/knowledge_lake/pipeline/process.py
- FOUND: tests/unit/test_process_crawled_clean.py
- FOUND: .planning/phases/17-close-the-bypass-measurement/17-03-SUMMARY.md
- FOUND commits: 290a34a, 9e0a225, 9294d50
