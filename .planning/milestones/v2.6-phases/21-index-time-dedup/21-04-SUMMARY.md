---
phase: 21-index-time-dedup
plan: 04
subsystem: pipeline
tags: [dedup, sqlalchemy, tdd, ledger]

# Dependency graph
requires:
  - phase: 21-index-time-dedup (Plan 01)
    provides: ChunkDedupLedger schema + claim_dedup_ledger_entry() atomic upsert
  - phase: 21-index-time-dedup (Plan 02)
    provides: normalize_for_dedup()/text_sha256_for()/point_id_for_text() pure primitives
provides:
  - "dedup_chunks(chunks, parsed_artifact_id, source_id, *, collection, settings=None) -> dict router function"
  - "_assert_dedup_conservation_invariant() — new+duplicates==total RuntimeError guard"
affects: [21-05-index-duplicate-routing, 21-06-call-site-wiring, 21-07-call-site-wiring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single get_session() transaction wraps the entire per-chunk claim loop, so auto-commit-on-clean-exit satisfies D-14's ordering invariant (ledger durable before any subsequent Qdrant write)"
    - "Conservation invariant asserted unconditionally inside the same session block, mirroring chunk.py's _assert_chunk_conservation_invariant log-then-raise shape"

key-files:
  created: []
  modified:
    - src/knowledge_lake/pipeline/dedup.py
    - tests/unit/test_index_dedup.py

key-decisions:
  - "settings resolution (`_ = settings or get_settings()`) kept per plan's explicit action text (mirrors embed()'s idiom) but assigned to `_` rather than `s` — the value is unused in this plan's scope and `s` tripped ruff F841; renaming to `_` preserves the settings-resolution side effect without a lint violation"
  - "Conservation-invariant RuntimeError test calls _assert_dedup_conservation_invariant directly with mismatched counts (chunk.py's own test precedent: test_chunk_conservation_invariant_raises_runtime_error_on_violation) rather than monkeypatching claim_dedup_ledger_entry to desync counts — by construction the per-chunk loop always appends to exactly one bucket per successful claim call, so a claim-level monkeypatch can only ever raise before reaching the invariant, never desync it silently"

requirements-completed: [DEDUP-01, DEDUP-02]

coverage:
  - id: D1
    description: "dedup_chunks([], ...) returns the empty-result dict without opening a DB session"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_index_dedup.py::TestDedupChunks::test_empty_input_returns_empty_result_without_opening_session"
        status: pass
    human_judgment: false
  - id: D2
    description: "All-distinct-text chunks route to new and every chunk is annotated with text_sha256/point_id"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_index_dedup.py::TestDedupChunks::test_all_distinct_text_routes_to_new_and_annotates_chunks"
        status: pass
    human_judgment: false
  - id: D3
    description: "Within-batch duplicate (two identical-text chunks in one call) routes first to new, second to duplicates"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_index_dedup.py::TestDedupChunks::test_within_batch_duplicate_routes_second_occurrence_to_duplicates"
        status: pass
    human_judgment: false
  - id: D4
    description: "Cross-call (cross-document) duplicate: two separate dedup_chunks() calls sharing identical text route the second call's chunk to duplicates — the corpus-wide guarantee"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_index_dedup.py::TestDedupChunks::test_cross_call_duplicate_routes_second_document_to_duplicates"
        status: pass
    human_judgment: false
  - id: D5
    description: "Re-processing the identical document (same parsed_artifact_id, same chunks) a second time routes every chunk to duplicates — end-to-end DEDUP-02 idempotent re-index through the real ledger"
    requirement: "DEDUP-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_index_dedup.py::TestDedupChunks::test_reprocessing_identical_document_is_idempotent"
        status: pass
    human_judgment: false
  - id: D6
    description: "_assert_dedup_conservation_invariant raises RuntimeError (never a bare assert) when new+duplicates != total, and passes silently when balanced; the real dedup_chunks() loop never trips it over a mixed batch"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_index_dedup.py::TestDedupChunks::test_conservation_invariant_raises_runtime_error_on_violation"
        status: pass
      - kind: unit
        ref: "tests/unit/test_index_dedup.py::TestDedupChunks::test_conservation_invariant_passes_silently_when_balanced"
        status: pass
      - kind: unit
        ref: "tests/unit/test_index_dedup.py::TestDedupChunks::test_dedup_chunks_never_violates_conservation_invariant_in_practice"
        status: pass
    human_judgment: false

# Metrics
duration: 9min
completed: 2026-07-17
status: complete
---

# Phase 21 Plan 04: dedup_chunks() Router Summary

**`dedup_chunks()` router added to `pipeline/dedup.py` — atomically claims every chunk against the corpus-wide `ChunkDedupLedger`, annotates it with `text_sha256`/`point_id`, and partitions into `new`/`duplicates`, proven end-to-end against a real SQLite ledger including cross-document idempotent re-index.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-07-17T12:58:11Z
- **Completed:** 2026-07-17T13:07:00Z
- **Tasks:** 2 completed
- **Files modified:** 2 (both modified, no new files)

## Accomplishments
- `dedup_chunks(chunks, parsed_artifact_id, source_id, *, collection, settings=None)` added to `pipeline/dedup.py`, extending Plan 21-02's pure-function baseline in the same file
- Empty-input guard returns immediately with zero DB session opened, mirroring `embed()`'s exact early-return idiom — verified by monkeypatching `get_session` to raise if invoked
- Every chunk (whether routed to `new` or `duplicates`) is annotated in place with `text_sha256`/`point_id`
- Single `get_session()` transaction wraps the whole per-chunk claim loop, satisfying D-14's ordering invariant: the ledger is durable before any subsequent `embed()`/`index()` Qdrant write for the batch
- `_assert_dedup_conservation_invariant()` mirrors `chunk.py::_assert_chunk_conservation_invariant`'s exact log-then-raise shape (`RuntimeError`, never a bare assert) — T-21-08 mitigation
- Proven idempotent end-to-end through the real ledger: re-processing the same document, and processing two separate documents with identical boilerplate text, both correctly route repeats to `duplicates`

## Task Commits

Each task was committed atomically (both `tdd="true"`; Task 2's tests were authored as Task 1's RED step per the TDD execution flow — see Deviations):

1. **Task 1 (TDD RED): failing tests for dedup_chunks() router** - `61aec6d` (test)
2. **Task 1 (TDD GREEN): dedup_chunks() implementation** - `05c984c` (feat)

**Plan metadata:** (this commit)

_Note: No REFACTOR commit was needed — the GREEN implementation matched the plan's exact specified shape with only one lint-driven adjustment (see Deviations)._

## Files Created/Modified
- `src/knowledge_lake/pipeline/dedup.py` - Added `_assert_dedup_conservation_invariant()` and `dedup_chunks()`, plus module-level imports (`datetime`, `structlog`, `Settings`/`get_settings`, `registry_repo`, `get_session`)
- `tests/unit/test_index_dedup.py` - Added `TestDedupChunks` class (8 tests) plus the SQLite `engine`/`_patch_engine` harness fixtures and `_chunk()` helper, appended after the existing pure-function test classes

## Decisions Made
- Settings resolution line (`_ = settings or get_settings()`) kept per the plan's explicit action text (mirrors `embed()`'s idiom exactly) but the result is bound to `_` rather than `s`, since the plan's scope does not yet consume settings inside this function and `s` tripped `ruff`'s F841 unused-variable check. This preserves the intended settings-resolution side effect (and future-extension symmetry with `embed()`) without a lint violation.
- The conservation-invariant `RuntimeError` test calls `_assert_dedup_conservation_invariant` directly with mismatched counts (mirroring `chunk.py`'s own `test_chunk_conservation_invariant_raises_runtime_error_on_violation` precedent) rather than monkeypatching `claim_dedup_ledger_entry` to desync the routing counts. By construction, the per-chunk loop appends every chunk to exactly one of `new_chunks`/`duplicate_chunks` per successful claim call — a monkeypatch that makes the claim call itself misbehave can only raise before the invariant check is reached (propagating immediately), it cannot silently desync the counts without also being a `_assert_dedup_conservation_invariant` unit test. A separate regression test (`test_dedup_chunks_never_violates_conservation_invariant_in_practice`) proves the real ledger-claim loop, run over a mixed distinct/duplicate batch, never trips the invariant.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Renamed unused `s` variable to `_` to satisfy ruff F841**
- **Found during:** Task 1 (GREEN implementation, running `uv run ruff check`)
- **Issue:** The plan's action text specifies `s = settings or get_settings()` mirroring `embed()`'s idiom, but this plan's scope for `dedup_chunks()` never consumes `s` (no settings-driven branching yet) — `ruff` flagged this as an unused local variable (F841), which would fail CI lint gates.
- **Fix:** Renamed the binding to `_` (Python's conventional "intentionally discarded" name), preserving the settings-resolution call (and its side effect / symmetry with `embed()`) while eliminating the lint error.
- **Files modified:** src/knowledge_lake/pipeline/dedup.py
- **Verification:** `uv run ruff check src/knowledge_lake/pipeline/dedup.py` — All checks passed.
- **Committed in:** 05c984c (Task 1 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 blocking lint fix)
**Impact on plan:** Purely mechanical (variable naming); no behavior change. No scope creep.

### Task-boundary note (not a deviation, a plan-authoring quirk)

Task 1 is `tdd="true"` with `<files>` naming only `pipeline/dedup.py`. Task 2 separately instructs extending `tests/unit/test_index_dedup.py` with the `TestDedupChunks` class covering the same `<behavior>` items. Following the standard TDD execution flow (RED: write the failing tests per `<behavior>` → GREEN: implement per `<action>`), Task 1's RED step necessarily created the full `TestDedupChunks` class (all 8 tests, matching Task 2's exact spec) before any implementation existed. By the time Task 2's action was reached, the file already existed and all 8 tests already passed — so Task 2 required no additional commit. This mirrors the same pattern documented in `21-03-SUMMARY.md`'s "Task-boundary note" (and STATE.md's Phase 17 P02 note on the inverse case). No plan content or test coverage was skipped; all of Task 2's acceptance criteria (full test file passes, cross-document idempotent-reindex proof) are satisfied by the tests as committed in `61aec6d`/`05c984c`.

## Issues Encountered

None beyond the lint fix described above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `dedup_chunks()`'s `{"new": [...], "duplicates": [...], "stats": {...}}` output is ready for Plan 21-05's `index()` duplicate-routing branch (consumes the `duplicate_chunks` list via `append_dedup_contributor()`/`get_dedup_ledger_entry()`/`set_payload()`) and Plans 21-06/21-07's call-site wiring (`embed()` receives only the `new` list)
- Full unit test suite (948 passed, 1 xfailed) green after this plan's changes — no regressions
- No blockers identified

---
*Phase: 21-index-time-dedup*
*Completed: 2026-07-17*

## Self-Check: PASSED

All modified files confirmed present on disk; both commit hashes (61aec6d, 05c984c) confirmed present in git log.
