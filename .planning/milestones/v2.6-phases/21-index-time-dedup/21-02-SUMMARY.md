---
phase: 21-index-time-dedup
plan: 02
subsystem: pipeline
tags: [dedup, uuid5, sha256, pydantic-settings, tdd]

# Dependency graph
requires:
  - phase: 21-index-time-dedup
    provides: "Plan 21-01's ChunkDedupLedger schema + repo CRUD (Postgres ledger the router in Plan 21-04 will claim rows against)"
provides:
  - "normalize_for_dedup(text) — the exact-dedup key normalization (NFKC + whitespace collapse + strip, no casefold)"
  - "text_sha256_for(text) — SHA-256 hex digest of the normalized dedup key"
  - "point_id_for_text(text) — deterministic uuid5 Qdrant point ID derived from a frozen namespace"
  - "KLAKE_DEDUP_NAMESPACE — frozen uuid.UUID constant for uuid5 derivation"
  - "DedupSettings.contributor_cap — operator-tunable Qdrant contributors-payload cap, wired into Settings.dedup"
affects: [21-04-dedup-chunks-router, 21-05-index-duplicate-routing, 21-06-call-site-wiring, 21-07-call-site-wiring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Zero-I/O pure-function module (pipeline/dedup.py pure-function section) mirroring Phase 19's pipeline/quality/ convention — no DB/S3/Dagster/settings imports"
    - "Frozen module-level UUID namespace constant, never derived from settings/env/collection name"

key-files:
  created:
    - src/knowledge_lake/pipeline/dedup.py
    - tests/unit/test_index_dedup.py
  modified:
    - src/knowledge_lake/config/settings.py

key-decisions:
  - "KLAKE_DEDUP_NAMESPACE hardcoded as a literal uuid4-generated constant (94eca03b-54f1-4438-a007-2f835b9d2c07), never derived — a namespace change would silently orphan every previously-indexed point"
  - "normalize_for_dedup deliberately does not reuse clean.py's _normalize_whitespace() (D-03) — that function is line-oriented for cleaned-text readability, not an exact-key equality contract"

patterns-established:
  - "tests/unit/test_index_dedup.py structured as one test class per concern (TestNormalizeForDedup, TestTextSha256For, TestPointIdForText) for later plans (21-04, 21-05) to append classes to, not interleave"

requirements-completed: [DEDUP-01, DEDUP-02]

coverage:
  - id: D1
    description: "DedupSettings.contributor_cap (default 50) wired into Settings.dedup, resolvable via KLAKE_DEDUP__CONTRIBUTOR_CAP"
    requirement: "DEDUP-01"
    verification:
      - kind: other
        ref: "python -c \"from knowledge_lake.config.settings import Settings; s=Settings(_env_file=None); assert s.dedup.contributor_cap==50\" (manual verification command, plan <verify> block)"
        status: pass
    human_judgment: false
  - id: D2
    description: "normalize_for_dedup/text_sha256_for/point_id_for_text pure functions with exact NFKC+whitespace-collapse contract, no casefolding, and deterministic uuid5 point IDs"
    requirement: "DEDUP-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_index_dedup.py (15 tests across TestNormalizeForDedup, TestTextSha256For, TestPointIdForText)"
        status: pass
    human_judgment: false

# Metrics
duration: 5min
completed: 2026-07-17
status: complete
---

# Phase 21 Plan 02: Pure Dedup Primitives Summary

**Zero-I/O `normalize_for_dedup`/`text_sha256_for`/`point_id_for_text` primitives plus `DedupSettings.contributor_cap`, forming the exact-dedup key and deterministic point-ID scheme every later Phase 21 plan builds on.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-07-17T12:48:00Z
- **Completed:** 2026-07-17T12:50:03Z
- **Tasks:** 2 completed
- **Files modified:** 3 (1 modified, 2 created)

## Accomplishments
- `DedupSettings(BaseModel)` added to `settings.py` with a single `contributor_cap: int = 50` field, registered as `Settings.dedup`, resolvable via `KLAKE_DEDUP__CONTRIBUTOR_CAP`
- `pipeline/dedup.py` created: frozen `KLAKE_DEDUP_NAMESPACE` constant, `normalize_for_dedup()` (NFKC normalize + whitespace-run collapse + strip, no casefolding), `text_sha256_for()` (SHA-256 of normalized UTF-8 bytes), `point_id_for_text()` (deterministic uuid5 bare-UUID string)
- `tests/unit/test_index_dedup.py` created with 15 tests across 3 classes proving the empty-input edge case, NFKC precomposed/decomposed equivalence, no-casefolding distinctness, direct hash recomputation, and point-ID determinism across repeated calls (DEDUP-02's idempotent re-index guarantee)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add DedupSettings model** - `dd0f96e` (feat)
2. **Task 2: Pure dedup primitives (TDD)**
   - RED: `dfc4a2d` (test) — failing tests against nonexistent `pipeline.dedup` module
   - GREEN: `dd2b430` (feat) — implementation, all 15 tests pass

**Plan metadata:** (this commit)

_Note: Task 2 used the RED/GREEN TDD cycle per `tdd="true"`. No REFACTOR commit was needed — the GREEN implementation matched the plan's exact specified shape with no cleanup required._

## Files Created/Modified
- `src/knowledge_lake/config/settings.py` - Added `DedupSettings` class + `Settings.dedup` field registration
- `src/knowledge_lake/pipeline/dedup.py` - New module: `KLAKE_DEDUP_NAMESPACE`, `normalize_for_dedup()`, `text_sha256_for()`, `point_id_for_text()`
- `tests/unit/test_index_dedup.py` - New test file, 15 tests, class-per-concern structure for later plans to extend

## Decisions Made
- `KLAKE_DEDUP_NAMESPACE` hardcoded as the exact literal specified in the plan (`94eca03b-54f1-4438-a007-2f835b9d2c07`) — never regenerated, never derived from settings/env/collection name (D-05)
- `normalize_for_dedup` deliberately does not reuse `clean.py`'s `_normalize_whitespace()` (D-03) — kept the two normalization contracts decoupled per the plan's prohibition
- Test file structured with one class per concern (`TestNormalizeForDedup`, `TestTextSha256For`, `TestPointIdForText`) so Plan 21-04 (dedup_chunks() router tests) and Plan 21-05 (index() duplicate-routing tests) can append new classes without interleaving

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `pipeline/dedup.py`'s pure functions are ready for Plan 21-04 to import and wrap in a ledger-consuming `dedup_chunks()` router (same file, Wave 2)
- `DedupSettings.contributor_cap` is ready for Plan 21-05's `index()` duplicate routing to consume when capping the Qdrant contributors payload mirror
- Full unit test suite (937 tests + 1 xfailed) still green after this plan's changes — no regressions introduced by the new `Settings.dedup` field

---
*Phase: 21-index-time-dedup*
*Completed: 2026-07-17*

## Self-Check: PASSED

All created files and commit hashes verified present.
