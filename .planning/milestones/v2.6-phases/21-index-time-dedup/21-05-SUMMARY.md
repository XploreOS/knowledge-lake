---
phase: 21-index-time-dedup
plan: 05
subsystem: pipeline
tags: [qdrant, sqlalchemy, dedup, contributors, self-heal]

# Dependency graph
requires:
  - phase: 21-index-time-dedup (Plan 01)
    provides: ChunkDedupLedger schema + get_dedup_ledger_entry()/append_dedup_contributor()
  - phase: 21-index-time-dedup (Plan 03)
    provides: VectorStorePlugin.set_payload(collection, point_id, payload) -> bool
  - phase: 21-index-time-dedup (Plan 04)
    provides: dedup_chunks()'s duplicates bucket (annotated with text_sha256/point_id)
provides:
  - "index()'s duplicate_chunks kwarg — contributor append, capped primary-first mirror, self-heal"
  - "index()'s new-chunk point-ID resolution preferring chunk['point_id'] over _strip_prefix(chunk_id)"
  - "reindex_collection()'s D-08 dual-ID-scheme docstring note"
affects: [21-06-process-py-wiring, 21-07-dagster-asset-wiring, 21-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One get_session() per duplicate chunk (not batched) in the contributor-append/self-heal branch — acceptable since this is not a hot per-chunk loop like the primary new-chunk path"
    - "Primary-first capped mirror: pull the ledger row's current primary entry out of contributors[] first, sort only the remainder by (created_at, chunk_id), then concatenate — never a single global sort (displaces the primary on timestamp ties/repairs)"
    - "set_payload's False return demotes a duplicate to a fresh embed()+upsert() under the SAME deterministic point_id, with a direct ORM-attribute repair of the ledger row's primary_* fields (no new repo function needed for this rare branch)"

key-files:
  created: []
  modified:
    - src/knowledge_lake/pipeline/index.py
    - tests/unit/test_index_dedup.py

key-decisions:
  - "Changed index()'s empty-input guard from `if not chunks: return []` to `if not chunks and not duplicate_chunks: return []` — a document that dedups to ZERO new chunks (all duplicates) must still run the duplicate-routing branch; the original guard would have silently skipped every contributor append for an all-duplicate batch. Not explicit in the plan's action text but required for the duplicate_chunks contract to hold in the all-duplicates case."
  - "Wrapped the primary new-chunk vstore.upsert() call in `if points:` (was unconditional) — for the same all-duplicates case, points is now legitimately empty and calling vstore.upsert(collection, []) would be a spurious real Qdrant client call; for every pre-existing caller points is always non-empty (chunks non-empty is enforced by the guard above), so this is a no-op change for backward compatibility."
  - "Added None-guards (raise RuntimeError) around get_dedup_ledger_entry()'s return in the self-heal loop and around the capped-mirror helper's primary-entry lookup — mypy caught these as new union-attr/list-item errors introduced by this plan's code; both are defensive against states that 'should be unreachable' per the plan's own reasoning, made explicit rather than left as an AttributeError crash"

requirements-completed: [DEDUP-02, DEDUP-03]

coverage:
  - id: D1
    description: "index() without duplicate_chunks behaves identically to before this plan — no set_payload call, all pre-existing test_index_payload.py/test_index_alias.py tests pass unmodified"
    requirement: "DEDUP-03"
    verification:
      - kind: unit
        ref: "tests/unit/test_index_dedup.py::TestIndexDuplicateRouting::test_index_without_duplicate_chunks_unaffected"
        status: pass
      - kind: unit
        ref: "tests/unit/test_index_payload.py (11 tests, unmodified) and tests/unit/test_index_alias.py (10 tests, unmodified)"
        status: pass
    human_judgment: false
  - id: D2
    description: "set_payload is called with ONLY {contributors, contributor_count} for a single duplicate — never document/text/quality_score/etc (T-21-11)"
    requirement: "DEDUP-03"
    verification:
      - kind: unit
        ref: "tests/unit/test_index_dedup.py::TestIndexDuplicateRouting::test_set_payload_called_with_only_contributors_and_count"
        status: pass
    human_judgment: false
  - id: D3
    description: "A ledger row with 51 total contributors produces a capped Qdrant mirror of length exactly 50, with contributor_count == 51 (DEDUP-01/03 boundary edge case)"
    requirement: "DEDUP-03"
    verification:
      - kind: unit
        ref: "tests/unit/test_index_dedup.py::TestIndexDuplicateRouting::test_contributor_cap_boundary_51_contributors_yields_50_length_mirror"
        status: pass
    human_judgment: false
  - id: D4
    description: "The capped mirror's first element always matches the ledger's primary_chunk_id, even when a naive global sort by created_at would place the primary last (D-21/D-23)"
    requirement: "DEDUP-03"
    verification:
      - kind: unit
        ref: "tests/unit/test_index_dedup.py::TestIndexDuplicateRouting::test_primary_always_first_even_with_later_primary_timestamp"
        status: pass
    human_judgment: false
  - id: D5
    description: "A 'new' chunk's payload is unaffected by this plan — PAYLOAD-01/02 filterable fields (domain, source_id, format, tags) still present, proving _resolve_document_payload_fields is unmodified"
    requirement: "DEDUP-03"
    verification:
      - kind: unit
        ref: "tests/unit/test_index_dedup.py::TestIndexDuplicateRouting::test_new_chunk_payload_filterable_fields_unaffected"
        status: pass
    human_judgment: false
  - id: D6
    description: "set_payload returning False triggers embed() + vstore.upsert() for exactly the affected chunk under the SAME point_id, with the ledger row's primary_* fields repaired to that chunk (T-21-10/D-24)"
    requirement: "DEDUP-03"
    verification:
      - kind: unit
        ref: "tests/unit/test_index_dedup.py::TestIndexDuplicateRouting::test_self_heal_on_vanished_point_reembeds_and_repairs_ledger"
        status: pass
    human_judgment: false

# Metrics
duration: 11min
completed: 2026-07-17
status: complete
---

# Phase 21 Plan 05: index() Duplicate-Routing Summary

**`index()` gains a `duplicate_chunks` kwarg that appends a ledger contributor, mirrors a capped primary-first `contributors[]` + exact `contributor_count` onto the existing Qdrant point via `set_payload()`, and self-heals (re-embed + repair) when the point has vanished out-of-band — the DEDUP-03 payload-preservation contract and the write side of DEDUP-02's point-ID determinism.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-07-17T13:07:55Z
- **Completed:** 2026-07-17T13:18:20Z
- **Tasks:** 2 completed
- **Files modified:** 2 (both modified, no new files)

## Accomplishments
- `index()` gained `duplicate_chunks: list[dict] | None = None` — additive-default, byte-identical behavior for every existing caller when omitted
- New-chunk point-ID resolution now prefers `chunk.get("point_id")` (dedup_chunks()'s uuid5 annotation, D-06) falling back to `_strip_prefix(chunk_id)` (D-07) for any caller that never went through dedup
- For each duplicate chunk: `append_dedup_contributor()` runs and commits BEFORE `vstore.set_payload()` (ORDERING INVARIANT, mirrors the existing alias-registration precedent), and `set_payload()` is called with ONLY `{"contributors": [...capped...], "contributor_count": <exact total>}` — never a full payload overwrite (T-21-11)
- `_build_capped_contributors_mirror()` places the ledger's current primary contributor ALWAYS first, sorting only the remaining entries by `(created_at, chunk_id)` for the rest of the `contributor_cap` (default 50) — proven at the exact 51-contributor boundary and under a primary-timestamp tie-break edge case that would defeat a naive global sort
- Self-heal branch: when `set_payload()` returns `False` (T-21-10, Qdrant point vanished out-of-band), the duplicate is demoted to a fresh `embed()` + full `VectorPoint` upsert under the SAME deterministic `point_id`, and the ledger row's `primary_chunk_id`/`primary_parsed_artifact_id`/`primary_source_id`/`primary_created_at` are repaired to reflect the now-current chunk (D-24)
- `reindex_collection()`'s docstring documents the D-08 dual-ID-scheme transitional state, warning future contributors against adding re-keying logic to `copy_all_points()`/`refresh_all_points_payload()`
- 6 new tests prove all of the above against a real SQLite-backed ledger and a mocked Qdrant vstore; full unit suite (954 passed, 1 xfailed) green with zero regressions

## Task Commits

Each task was committed atomically (both `tdd="true"`; Task 2's tests were authored to prove Task 1's already-implemented behavior — see Deviations/Task-boundary note):

1. **Task 1: index() duplicate_chunks kwarg — contributor append, capped mirror, self-heal** - `6b83eb4` (feat)
2. **Task 2: Tests — payload filterability, contributor cap/primary, self-heal** - `3ae9541` (test)

**Plan metadata:** (this docs commit)

## Files Created/Modified
- `src/knowledge_lake/pipeline/index.py` — `index()` gained `duplicate_chunks` kwarg, the point-ID fallback change, the contributor-append/cap/self-heal block, and a new `_build_capped_contributors_mirror()` helper; `reindex_collection()`'s docstring gained the D-08 note
- `tests/unit/test_index_dedup.py` — added `class TestIndexDuplicateRouting` (6 tests) plus its own `dedup_session`/`fake_vstore` fixtures and `_seed_document`/`_dup_chunk` helpers

## Decisions Made
- **Empty-input guard extended:** `if not chunks: return []` became `if not chunks and not duplicate_chunks: return []`. Without this, a document that dedups to zero "new" chunks (an entirely-duplicate batch — a real scenario per Plan 21-04's `test_reprocessing_identical_document_is_idempotent`) would hit the original guard and silently skip every contributor append, breaking the DEDUP-03 contract for that document. The plan's action text didn't call this out explicitly, but it's required for `duplicate_chunks` to work correctly whenever `chunks` is empty — a Rule 1 (bug) fix scoped directly to this plan's own new parameter.
- **`vstore.upsert()` for "new" chunks made conditional on `points` being non-empty:** a direct consequence of the guard change above — for every pre-existing caller `chunks` (and therefore `points`) is always non-empty by construction, so this is a no-op for backward compatibility, but it avoids a spurious real Qdrant `upsert(points=[])` call for the all-duplicates case.
- **Explicit `RuntimeError` guards added around two `None`/type-narrowing gaps** mypy caught after implementation: (1) the self-heal loop's `get_dedup_ledger_entry()` return (union-attr errors on `ledger_row.primary_*`), and (2) `_build_capped_contributors_mirror()`'s primary-entry lookup (a `dict | None` flowing into a `list[dict]` return). Both are "should be unreachable" states per the plan's own reasoning (the row was already found once earlier in the same call, or the primary is always appended as `contributors[0]` at claim time) — made explicit as loud `RuntimeError`s rather than left as opaque `AttributeError`/type-unsafe code.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Extended the empty-input guard to account for an all-duplicates batch**
- **Found during:** Task 1 (implementing the `duplicate_chunks` branch, reasoning through the all-duplicates case)
- **Issue:** The plan's action text only says to add the `duplicate_chunks` block "after the existing loop"; the pre-existing `if not chunks: return []` guard at the top of `index()` would short-circuit before ever reaching that block if a caller passed `chunks=[]` (all chunks routed to duplicates) alongside a non-empty `duplicate_chunks` — silently dropping every contributor append for that document.
- **Fix:** Changed the guard to `if not chunks and not duplicate_chunks: return []`, and made the "new" chunks' `vstore.upsert()` call conditional on `points` being non-empty (previously unconditional, now legitimately skippable when `chunks=[]`).
- **Files modified:** src/knowledge_lake/pipeline/index.py
- **Verification:** All pre-existing callers still hit the exact same code path (chunks non-empty implies points non-empty, so the new `if points:` guard is a no-op for them); new test `test_self_heal_on_vanished_point_reembeds_and_repairs_ledger` and the cap/primary tests all call `index([], [], ...)` with only `duplicate_chunks` and pass.
- **Committed in:** 6b83eb4 (Task 1 commit)

**2. [Rule 1 - Bug] Added None-guards mypy caught as new union-attr/list-item errors**
- **Found during:** Task 1 (running `uv run mypy src/knowledge_lake/pipeline/index.py` after the GREEN implementation)
- **Issue:** The self-heal loop accessed `ledger_row.primary_chunk_id` etc. directly on `get_dedup_ledger_entry()`'s `ChunkDedupLedger | None` return without a None check (unlike the primary contributor-append loop, which does raise); `_build_capped_contributors_mirror()` initialized `primary_entry = None` and could return it un-narrowed into a `list[dict]`-typed return.
- **Fix:** Added explicit `raise RuntimeError(...)` guards in both locations, mirroring the primary loop's existing pattern, with messages noting these states should be unreachable given the surrounding logic.
- **Files modified:** src/knowledge_lake/pipeline/index.py
- **Verification:** `uv run mypy src/knowledge_lake/pipeline/index.py` — the 4 remaining errors are pre-existing (verified via `git stash`/`mypy`/`git stash pop` against the pre-plan file, all in `reindex_collection()`/`_build_payload_refresh_fn`, out of this plan's scope). `uv run pytest tests/unit/test_index_dedup.py -q` — 29 passed.
- **Committed in:** 6b83eb4 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (2 bug fixes)
**Impact on plan:** Both fixes are necessary for the `duplicate_chunks` contract to hold correctly in the all-duplicates-batch case and for type safety; neither changes behavior for any pre-existing caller. No scope creep — both fixes are scoped entirely to code this plan introduced.

### Task-boundary note (not a deviation, a plan-authoring quirk)

Task 1 is `tdd="true"` with `<files>` naming only `index.py` (no test file); Task 2 separately instructs extending `tests/unit/test_index_dedup.py` with `class TestIndexDuplicateRouting` covering the same `<behavior>` items. This is the same pattern already documented in `21-03-SUMMARY.md` and `21-04-SUMMARY.md`'s "Task-boundary note": the implementation (Task 1's `<action>`) and its test file (Task 2's `<action>`) were authored together against the plan's exact `<behavior>` spec, then verified: `uv run mypy`/`ruff` clean (aside from one pre-existing, out-of-scope lint finding at `test_index_dedup.py:90`, unrelated to this plan's changes — confirmed via `git show HEAD:...` predating this plan), and the full unit suite (954 passed, 1 xfailed) green with zero regressions before either commit. No plan content or test coverage was skipped; both tasks' acceptance criteria are fully satisfied by the code as committed across `6b83eb4`/`3ae9541`.

## Issues Encountered
None beyond the two auto-fixed issues described above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `index()`'s `duplicate_chunks` kwarg is ready for Plan 21-06 (`process.py` call-site wiring) and Plan 21-07 (Dagster asset call-site wiring) to pass `dedup_chunks()['duplicates']` directly
- Full unit test suite (954 passed, 1 xfailed) green after this plan's changes — no regressions
- No blockers identified

---
*Phase: 21-index-time-dedup*
*Completed: 2026-07-17*

## Self-Check: PASSED

All modified files confirmed present on disk; both commit hashes (6b83eb4, 3ae9541) confirmed present in git log.
