---
phase: 24-flagship-domain-pack-foundation
plan: 05
subsystem: pipeline
tags: [pydantic, field_validator, typer, cli, enrichment, gap-closure]

requires:
  - phase: 24-flagship-domain-pack-foundation (24-02)
    provides: The 200-cleaned-document agent-security corpus and the live enrichment run that surfaced this gap
provides:
  - EnrichmentResult._truncate_document_type (mode="before" field_validator) truncating over-length document_type to <=100 chars instead of raising ValidationError
  - cmd_enrich exits non-zero (typer.Exit(code=1)) whenever enrich_document() returns any status starting with "skipped"
affects: [24-06 (enrichment re-run for the 90 affected cleaned_document artifacts)]

tech-stack:
  added: []
  patterns:
    - "Pydantic v2 mode='before' field_validator to pre-process/truncate a value ahead of the field's own max_length constraint, rather than raising or retrying"
    - "CLI exit-code check on an internal status-dict result (status.startswith('skipped')) placed after the success-path echoes, raised as typer.Exit(code=1) inside the existing try block so it is never swallowed by an unrelated except clause"

key-files:
  created:
    - tests/unit/test_cli_enrich.py
  modified:
    - src/knowledge_lake/pipeline/enrich.py
    - tests/unit/test_enrich.py
    - src/knowledge_lake/cli/app.py

key-decisions:
  - "Truncate document_type (not raise Field(max_length=100), not retry) — matches the plan's explicit prohibition against changing the bound, and document_type's actual downstream use as a short categorical filter/label"
  - "cmd_enrich's skipped-status check placed inside the existing try block, after the status/artifact_id/quality_score/cached echoes, so the operator still sees the printed failure status before the non-zero exit"

patterns-established:
  - "Any status-dict-returning pipeline function surfaced through a CLI command must have its failure-status literals explicitly checked for exit-code purposes — a function that 'never raises by design' (D-05) must not be assumed to imply CLI success"

requirements-completed: []

coverage:
  - id: D1
    description: "EnrichmentResult truncates an over-length (>100 char) document_type to exactly 100 chars via a mode='before' field_validator instead of raising ValidationError"
    verification:
      - kind: unit
        ref: "tests/unit/test_enrich.py#test_overlength_document_type_is_pydantic_truncated"
        status: pass
      - kind: unit
        ref: "tests/unit/test_enrich.py#test_overlength_document_type_is_truncated_not_rejected"
        status: pass
    human_judgment: false
  - id: D2
    description: "cmd_enrich exits 1 for any skipped_* enrichment status (skipped_enrichment_failed, skipped_budget_exceeded) while still exiting 0 for enriched/cached"
    verification:
      - kind: unit
        ref: "tests/unit/test_cli_enrich.py#TestCliEnrichExitCode::test_skipped_enrichment_failed_exits_1"
        status: pass
      - kind: unit
        ref: "tests/unit/test_cli_enrich.py#TestCliEnrichExitCode::test_skipped_budget_exceeded_exits_1"
        status: pass
      - kind: unit
        ref: "tests/unit/test_cli_enrich.py#TestCliEnrichExitCode::test_enriched_status_exits_0"
        status: pass
      - kind: unit
        ref: "tests/unit/test_cli_enrich.py#TestCliEnrichExitCode::test_cached_status_exits_0"
        status: pass
    human_judgment: false

duration: ~10min
completed: 2026-07-22
status: complete
---

# Phase 24 Plan 05: Enrich document_type Truncation + cmd_enrich Exit-Code Fix Summary

**Truncates over-length LLM `document_type` before Pydantic validation (mode="before" field_validator) and makes `cmd_enrich` exit non-zero on any `skipped_*` status, closing both root-cause defects behind 24-VERIFICATION.md gap #8's silent 45% enrichment failure.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-07-22T15:14:00Z (approx.)
- **Completed:** 2026-07-22T15:18:30Z
- **Tasks:** 2
- **Files modified:** 3 modified, 1 created

## Accomplishments
- `EnrichmentResult._truncate_document_type` (Pydantic v2 `field_validator(mode="before")`) truncates any `document_type` longer than 100 characters to exactly 100 chars, ahead of `Field(max_length=100)`'s own constraint evaluation — an over-length LLM response no longer raises `ValidationError` and no longer silently produces `status="skipped_enrichment_failed"` with no artifact created.
- `cmd_enrich` now raises `typer.Exit(code=1)` whenever `enrich_document()`'s returned `status` starts with `"skipped"` (`skipped_enrichment_failed`, `skipped_budget_exceeded`), closing the silent-success-on-failure defect that let 90/200 (45%) of the agent-security corpus's real enrichment failures go uncounted by exit-code-based automation. `enriched`/`cached` statuses are unaffected and still exit 0.
- 6 new regression tests added (2 in `test_enrich.py`, 4 in new `test_cli_enrich.py`), each confirmed as a genuine RED reproduction of the gap before the corresponding fix landed.

## Task Commits

Each task was committed atomically (TDD RED -> GREEN per task):

1. **Task 1: Truncate over-length document_type before Pydantic validation**
   - `49a45eb` (test) - add failing regression tests for over-length document_type
   - `e624b1c` (feat) - truncate over-length document_type before Pydantic validation
2. **Task 2: Make cmd_enrich exit non-zero on any skipped_* enrichment status**
   - `87c3d80` (test) - add failing regression tests for cmd_enrich exit-code gap
   - `0893270` (feat) - cmd_enrich exits non-zero on any skipped_* enrichment status

## Files Created/Modified
- `src/knowledge_lake/pipeline/enrich.py` - Added `_truncate_document_type` field_validator (`mode="before"`) on `EnrichmentResult`, placed immediately after the existing `_bound_item_length` validator
- `tests/unit/test_enrich.py` - Added `test_overlength_document_type_is_pydantic_truncated` (pure-Pydantic) and `test_overlength_document_type_is_truncated_not_rejected` (full `enrich_document()` integration)
- `src/knowledge_lake/cli/app.py` - `cmd_enrich` now checks `result["status"].startswith("skipped")` after its existing echoes and raises `typer.Exit(code=1)`, inside the same `try` block, leaving the `except (ValueError, LookupError)` clause untouched
- `tests/unit/test_cli_enrich.py` (new) - 4 tests covering both skipped statuses (exit 1) and both success statuses (exit 0, no-regression guards), using the same `engine`/`_patch_engine`/`session`/`seeded` in-memory-SQLite fixture pattern as `test_cli_tree_index.py` and `test_enrich.py`

## Decisions Made
- Truncation (not raising the 100-char bound, not a shrink-and-retry strategy) chosen per the plan's explicit prohibition and because `document_type` is consumed downstream as a short categorical filter/label (Qdrant `FieldCondition`, `pipeline/index.py`, `plugins/builtin/qdrant_store.py`, Parquet export column), not free-form prose needing full length preserved.
- The exit-code check was placed after `cmd_enrich`'s existing status/artifact_id/quality_score/cached echoes so the operator still sees the failure status printed to stdout before the process exits non-zero — matching the plan's explicit ordering requirement.

## Deviations from Plan

None - plan executed exactly as written.

## TDD Gate Compliance

Both tasks followed the mandatory RED -> GREEN gate sequence, verified in git log:
- Task 1: `49a45eb` (test, RED — confirmed failing with the real `ValidationError` before the fix) -> `e624b1c` (feat, GREEN — all 19 tests in `test_enrich.py` pass)
- Task 2: `87c3d80` (test, RED — confirmed `test_skipped_enrichment_failed_exits_1` failed with `exit_code == 0` before the fix) -> `0893270` (feat, GREEN — all 4 new tests pass)

No REFACTOR commit was needed for either task (implementation was minimal and required no cleanup pass).

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Both root-cause defects behind 24-VERIFICATION.md gap #8 are fixed and regression-tested. `uv run pytest tests/unit/test_enrich.py tests/unit/test_cli_enrich.py -x` passes (23/23). Full `tests/unit` suite re-run: 1012 passed, 1 pre-existing unrelated xfailed, 0 regressions.
- Plan 24-06 (re-run enrichment against the 90 affected cleaned_document artifacts in the live corpus) can now proceed and trust `cmd_enrich`'s exit codes as a real pass/fail signal.
- `uv run python -c "..."` one-liner confirmed: `EnrichmentResult(summary="s", document_type="x"*150, quality_score=0.5).document_type` has length 100.

---
*Phase: 24-flagship-domain-pack-foundation*
*Completed: 2026-07-22*

## Self-Check: PASSED

All created/modified files confirmed present on disk; all 4 task commit hashes (49a45eb, e624b1c, 87c3d80, 0893270) confirmed present in git log.
