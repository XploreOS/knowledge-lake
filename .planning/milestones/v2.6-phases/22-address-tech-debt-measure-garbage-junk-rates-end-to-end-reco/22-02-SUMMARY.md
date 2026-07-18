---
phase: 22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco
plan: 02
subsystem: cli
tags: [cli, typer, quality-audit, measurement]

requires:
  - phase: 22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco (Plan 22-01)
    provides: run_full_pipeline_audit() — chunk-level garbage rate + export-level junk rate measurement, {"rows": [...], "summary": {...}} return shape
provides:
  - "--full flag on klake quality-audit, wired to run_full_pipeline_audit()"
  - "Dual table/JSON output for the extended (chunk+export) measurement, mirroring the existing command's convention exactly"
affects: [22-03]

tech-stack:
  added: []
  patterns:
    - "Full-vs-non-full branch at the top of cmd_quality_audit(): --full short-circuits to run_full_pipeline_audit()+result[\"rows\"]/result[\"summary\"] and returns before reaching the pre-existing run_quality_audit() call, so the non---full path's control flow and call expression stay byte-identical"

key-files:
  created: []
  modified:
    - src/knowledge_lake/cli/app.py
    - tests/unit/test_cli_quality_audit.py

key-decisions:
  - "run_full_pipeline_audit()'s actual return shape (confirmed by reading src/knowledge_lake/pipeline/quality_audit.py directly) matched the plan's <interfaces> block exactly — no shape drift occurred during Plan 22-01's execution, so the CLI wiring needed no adjustment from what the plan specified"

patterns-established:
  - "--full's table view extends the existing per-source row with three right-aligned columns (chunks_kept, chunks_rejected, chunk_garbage_rate) using the same N/A-for-None display convention as the existing garbage_rate column, then prints a separate two-line corpus-wide summary block (chunk_garbage_rate vs baseline, export_junk_rate vs baseline) after the row loop"

requirements-completed: [MEAS-01]

coverage:
  - id: D1
    description: "klake quality-audit --full prints a per-source table with chunk-level columns (chunks_kept, chunks_rejected, chunk_garbage_rate) plus a corpus-wide summary block comparing chunk_garbage_rate/export_junk_rate against the 28%/33% baselines"
    requirement: "MEAS-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_cli_quality_audit.py::TestCliQualityAuditFullFlag::test_full_table_output_contains_chunk_columns_and_baseline"
        status: pass
    human_judgment: false
  - id: D2
    description: "klake quality-audit --full --json emits the exact {rows, summary} dict produced by run_full_pipeline_audit(), machine-parseable via json.loads()"
    requirement: "MEAS-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_cli_quality_audit.py::TestCliQualityAuditFullFlag::test_full_json_round_trips_rows_and_summary"
        status: pass
    human_judgment: false
  - id: D3
    description: "--full with zero rows prints the identical 'No sources found for domain ...' message as the non---full path (no second message introduced)"
    requirement: "MEAS-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_cli_quality_audit.py::TestCliQualityAuditFullFlag::test_full_empty_rows_prints_no_sources_message"
        status: pass
    human_judgment: false
  - id: D4
    description: "Existing (non---full) klake quality-audit behavior is byte-for-byte unchanged — the new flag is strictly additive, and --help lists --full alongside the pre-existing --domain/-d/--json options"
    requirement: "MEAS-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_cli_quality_audit.py (full file, 9/9 passing — 5 pre-existing + 4 new)"
        status: pass
      - kind: unit
        ref: "tests/unit/test_cli_quality_audit.py::TestCliQualityAuditHelp::test_help_lists_full_flag"
        status: pass
    human_judgment: false

duration: 6min
completed: 2026-07-17
status: complete
---

# Phase 22 Plan 02: CLI --full flag for quality-audit Summary

**`klake quality-audit --full [--json]` now reaches Plan 22-01's `run_full_pipeline_audit()` measurement (chunk-level garbage rate + export-level junk rate vs 28%/33% baselines) through the existing `quality-audit` command, with the pre-existing non---full path left byte-identical.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-17T18:20:00Z
- **Completed:** 2026-07-17T18:26:00Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- Added a `--full` Typer option to `cmd_quality_audit()` that branches at the top of the function: when set, calls `run_full_pipeline_audit(domain=domain)` and uses `result["rows"]`/`result["summary"]` for the rest of the function; when absent, the pre-existing `run_quality_audit(domain=domain)` call and control flow are completely untouched
- `--full` table output extends the existing per-source row format with three new right-aligned columns (`chunks_kept`, `chunks_rejected`, `chunk_garbage_rate` — same `N/A`-for-`None` convention, `:.1%` formatting), then prints a corpus-wide summary block after the row loop comparing `chunk_garbage_rate`/`export_junk_rate` against `baseline_chunk_garbage_rate`(28%)/`baseline_export_junk_rate`(33%)
- `--full --json` echoes `json.dumps(result)` — the whole `{"rows": ..., "summary": ...}` dict, not just rows — round-tripping exactly through `json.loads()`
- `--full` with zero rows reuses the identical `f"No sources found for domain {domain!r}."` message (no second message string introduced)
- Module docstring's command list updated to mention `--full` on the `quality-audit` line
- Confirmed `run_full_pipeline_audit()`'s actual committed return shape (by reading `src/knowledge_lake/pipeline/quality_audit.py` directly, per this plan's own read_first instruction) matched the plan's documented `<interfaces>` contract exactly — zero shape drift from Plan 22-01, so no CLI-side adjustment was needed

## Task Commits

Each task was committed atomically as separate TDD RED/GREEN commits (tdd="true"):

1. **Task 1 RED — failing tests for --full flag** - `d4a74b4` (test)
2. **Task 1 GREEN — implement --full wiring** - `609bdc8` (feat)

_Note: RED phase confirmed 4 genuine failures (`No such option '--full'`) before any implementation code existed, then GREEN made all 9 tests in the file pass (5 pre-existing + 4 new) with zero regressions — proper RED→GREEN TDD cycle, unlike Plan 22-01's tests-alongside-implementation convention._

## Files Created/Modified
- `src/knowledge_lake/cli/app.py` - `--full` Typer option on `cmd_quality_audit()`, extended table/summary/JSON output branches, module docstring update
- `tests/unit/test_cli_quality_audit.py` - New `TestCliQualityAuditFullFlag` class (3 tests: table output, JSON round-trip, empty-rows message) + `TestCliQualityAuditHelp.test_help_lists_full_flag`

## Decisions Made
- None beyond what's captured in `key-decisions` above — the plan's `<interfaces>` contract for `run_full_pipeline_audit()`'s return shape held exactly as documented against the actually-committed Plan 22-01 code, so no deviation was needed on that front.

## Deviations from Plan

None - plan executed exactly as written. The plan explicitly flagged a risk that `run_full_pipeline_audit()`'s return shape "may have shifted slightly during Plan 22-01's execution" — verified against the actual committed `quality_audit.py` source and confirmed it matches the plan's `<interfaces>` block exactly (same `{"rows": [...], "summary": {...}}` top-level shape, same row/summary key names).

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `klake quality-audit --domain healthcare --full` (and `--full --json`) is ready for Plan 22-03 (or a manual operator run) to invoke against the live dev stack's 34 healthcare sources for the "official" chunk-garbage-rate/export-junk-rate measurement named in RESEARCH.md's Sampling Rate section.
- `pytest` full suite: 1185 passed, 0 failed, 3 skipped, 6 xfailed (up from 1181 pre-plan — 4 new tests, 0 regressions).
- No architectural changes needed; CLI surface for `run_full_pipeline_audit()` (RESEARCH.md Wave 0 gap, deferred by Plan 22-01) is now closed.

---
*Phase: 22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco*
*Completed: 2026-07-17*

## Self-Check: PASSED

- FOUND: src/knowledge_lake/cli/app.py
- FOUND: tests/unit/test_cli_quality_audit.py
- FOUND: commit d4a74b4
- FOUND: commit 609bdc8
