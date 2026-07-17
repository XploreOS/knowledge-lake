---
phase: 21-index-time-dedup
plan: 01
subsystem: database
tags: [sqlalchemy, postgres, alembic, dedup, registry]

# Dependency graph
requires:
  - phase: 20-chunk-substance-gate-export-gate
    provides: chunk()'s substance-gated chunk dicts (dedup must run after this gate, per D-16/roadmap ordering)
provides:
  - ChunkDedupLedger SQLAlchemy model (registry/models.py)
  - Alembic migration 0011_chunk_dedup_ledger.py, applied to dev Postgres
  - claim_dedup_ledger_entry() — atomic first-writer-wins upsert (DEDUP-01/02)
  - get_dedup_ledger_entry() — pure lookup, never raises for a miss
  - append_dedup_contributor() — drift-proof contributor-count append (DEDUP-03)
affects: [21-02, 21-03, 21-04, 21-05, 21-06, 21-07, 21-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Atomic 'claim or return existing' upsert via INSERT ... ON CONFLICT DO NOTHING ... RETURNING(), never CursorResult.rowcount (unreliable, -1, under this project's psycopg3+SQLAlchemy2.0 pin)"
    - "Ledger uniqueness scoped to (collection, text_sha256), not text_sha256 alone — per-alias isolation (D-12)"
    - "Contributor count always derived from len(contributors) at append time — structurally cannot drift (D-13/T-21-02 mitigation)"

key-files:
  created:
    - src/knowledge_lake/registry/alembic/versions/0011_chunk_dedup_ledger.py
    - tests/unit/test_repo_dedup_ledger.py
  modified:
    - src/knowledge_lake/registry/models.py
    - src/knowledge_lake/registry/repo.py

key-decisions:
  - "contributors column uses the module's existing _JSON alias (not a new JSON().with_variant(JSONB) construct) per the plan's explicit Task 1 action text — RESEARCH.md's with_variant suggestion was considered but the plan's locked spec (reusing Source.config/Artifact.metadata_'s existing convention) takes precedence, and both are equally SQLite-harness-safe"
  - "ChunkDedupLedger.id uses new_id('artifact') (art_<uuidv7>), matching VectorCollection's own precedent for a generic, non-lineage registry row"

requirements-completed: [DEDUP-01, DEDUP-02, DEDUP-03]

coverage:
  - id: D1
    description: "ChunkDedupLedger table exists after alembic upgrade head, unique constraint scoped to (collection, text_sha256)"
    requirement: "DEDUP-01"
    verification:
      - kind: integration
        ref: "uv run alembic upgrade head / downgrade -1 / upgrade head round-trip against live dev Postgres 16 (this session)"
        status: pass
      - kind: unit
        ref: "python -c Base.metadata.create_all() against in-memory SQLite — no CompileError"
        status: pass
    human_judgment: false
  - id: D2
    description: "claim_dedup_ledger_entry() is atomic: exactly one of two concurrent claimants wins, proven via .returning() not .rowcount"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_repo_dedup_ledger.py::test_claim_second_call_same_key_loses_race"
        status: pass
      - kind: unit
        ref: "tests/unit/test_repo_dedup_ledger.py::test_claim_never_branches_on_rowcount"
        status: pass
      - kind: integration
        ref: "manual verification script against live healthlake-postgres-1 (this session): won1=True, won2=False"
        status: pass
    human_judgment: false
  - id: D3
    description: "Winning row's contributors == [primary] with contributor_count == 1; append_dedup_contributor derives count from len(contributors), never drifts across 1/2/5 appends"
    requirement: "DEDUP-03"
    verification:
      - kind: unit
        ref: "tests/unit/test_repo_dedup_ledger.py::test_claim_fresh_pair_creates_new_primary"
        status: pass
      - kind: unit
        ref: "tests/unit/test_repo_dedup_ledger.py::test_append_dedup_contributor_count_never_drifts"
        status: pass
    human_judgment: false
  - id: D4
    description: "get_dedup_ledger_entry() is a pure lookup (no insert, no raise) for both an unclaimed key and a claimed one, looked up by either text_sha256 or point_id"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_repo_dedup_ledger.py::test_get_dedup_ledger_entry_returns_none_for_unclaimed"
        status: pass
      - kind: unit
        ref: "tests/unit/test_repo_dedup_ledger.py::test_get_dedup_ledger_entry_finds_claimed_row"
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-07-17
status: complete
---

# Phase 21 Plan 01: Chunk Dedup Ledger Schema + Repo CRUD Summary

**Postgres-backed `chunk_dedup_ledger` table (migration 0011) plus `claim_dedup_ledger_entry`/`get_dedup_ledger_entry`/`append_dedup_contributor` in `registry/repo.py`, proven atomic via a live two-transaction Postgres race test and a 12-test SQLite unit-test file.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-17T12:38:41Z
- **Completed:** 2026-07-17T12:44:36Z
- **Tasks:** 2 completed
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- `ChunkDedupLedger` SQLAlchemy model added to `registry/models.py`, mirroring `VectorCollection`'s shape (prefixed-UUID PK, `server_default=func.now()`), with a `UniqueConstraint` scoped to `(collection, text_sha256)` per D-12
- Migration `0011_chunk_dedup_ledger.py` applied to the dev Postgres database (revision 0011); round-trip (`upgrade` → `downgrade -1` → `upgrade`) verified clean
- `claim_dedup_ledger_entry()` implements the atomic "first writer wins" upsert via `INSERT ... ON CONFLICT (collection, text_sha256) DO NOTHING ... RETURNING`, verified live against both the SQLite unit-test harness and the real dev Postgres 16 instance — confirmed the losing caller's `.returning()` result is empty while the winner's is non-empty, and that `.rowcount` is never referenced in the function body
- `get_dedup_ledger_entry()` and `append_dedup_contributor()` implemented exactly per the plan's D-11/D-13/D-23 semantics — contributor_count is always `len(contributors)`, never an independent counter

## Task Commits

Each task was committed atomically (Task 1 is `tdd="true"` but its behavior is schema/DDL existence — see TDD Gate Compliance note below; Task 2 followed the full RED/GREEN cycle):

1. **Task 1: ChunkDedupLedger model + Alembic migration 0011, applied** - `42abc8c` (feat)
2. **Task 2 (RED): failing tests for dedup ledger repo CRUD** - `5fd87ba` (test)
3. **Task 2 (GREEN): dedup ledger repo CRUD implementation** - `bd05d97` (feat)

## Files Created/Modified
- `src/knowledge_lake/registry/models.py` - added `ChunkDedupLedger(Base)` class after `VectorCollection`
- `src/knowledge_lake/registry/alembic/versions/0011_chunk_dedup_ledger.py` - new migration, revision `0011`, `down_revision "0010"`
- `src/knowledge_lake/registry/repo.py` - added `claim_dedup_ledger_entry()`, `get_dedup_ledger_entry()`, `append_dedup_contributor()`, plus the `pg_insert` import and `ChunkDedupLedger` to the models import block
- `tests/unit/test_repo_dedup_ledger.py` - new file, 12 tests covering every `<behavior>` item plus the D-12 cross-collection independence case

## Decisions Made
- **contributors column type:** Used the module's existing `_JSON` type alias (already backing `Source.config`/`Artifact.metadata_`/`DatasetExample.payload`) rather than introducing a new `JSON().with_variant(JSONB, "postgresql")` construct. RESEARCH.md recommended the `with_variant` form, but the plan's Task 1 `<action>` text explicitly locks in reusing `_JSON` for consistency with the rest of the file — both options are equally SQLite-harness-safe, so the plan's explicit instruction (the more authoritative, most-recently-reconciled source) was followed.
- **Ledger `id` prefix:** Used `new_id("artifact")` (`art_<uuidv7>`), matching `VectorCollection.id`'s own documented precedent for a generic, non-lineage registry row (RESEARCH.md Pitfall 4, option (a)).

## Deviations from Plan

None — plan executed exactly as written. The one judgment call (contributors column type) was explicitly pre-resolved by the plan's own action text, not a deviation from it.

## TDD Gate Compliance

Task 1 (`tdd="true"`) has no companion test file in `files_modified` — its `<behavior>` describes schema/DDL existence (table creation, unique constraint enforcement, SQLite compile-ability), which is proven via the acceptance criteria's direct shell/Python verification commands (`alembic upgrade/downgrade`, raw-SQL constraint violation, `Base.metadata.create_all()`) rather than a pytest RED/GREEN cycle. All of these were run and passed (see Accomplishments). Task 2 followed the full RED (`5fd87ba`, all 12 tests failing with `AttributeError`) → GREEN (`bd05d97`, all 12 tests passing) cycle per the plan's `tdd="true"` marking.

## Issues Encountered
- First implementation attempt of `claim_dedup_ledger_entry()`'s docstring included the literal substring `.rowcount` inside prose explaining why `.rowcount` is unreliable — this tripped the plan's own acceptance criterion ("no `.rowcount` reference in the function body", implemented as a literal substring test). Reworded the docstring to describe the same fact without the literal substring. No behavior change.
- Verified (out of caution, since RESEARCH.md's `pg_insert(...).on_conflict_do_nothing()` is a Postgres-dialect-specific construct) that SQLAlchemy correctly compiles and executes this construct against the SQLite in-memory test harness too — confirmed via a standalone script that the second insert's `.returning()` correctly returns empty while the first returns the row, both against SQLite and against live Postgres.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `ChunkDedupLedger` model, migration, and repo CRUD are ready for Plan 21-04's `dedup_chunks()` router (consumes `claim_dedup_ledger_entry()`'s `(row, is_new_primary)` tuple) and Plan 21-05's `index()` duplicate-routing branch (consumes `append_dedup_contributor()`/`get_dedup_ledger_entry()`)
- No blockers. The accepted architectural limitation (cross-domain dedup collision within one collection alias, D-12) remains flagged per this plan's `must_haves.prohibitions` — status `flagged-unverified`, not something this plan's scope resolves.

---
*Phase: 21-index-time-dedup*
*Completed: 2026-07-17*

## Self-Check: PASSED

All created/modified files confirmed present on disk; all 3 commit hashes (42abc8c, 5fd87ba, bd05d97) confirmed present in git log.
