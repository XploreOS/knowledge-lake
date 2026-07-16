---
phase: 19-section-classifier-patterns
plan: 01
subsystem: pipeline
tags: [quality-predicates, datatrove, tiktoken, pure-function, zero-io]

# Dependency graph
requires:
  - phase: 18-gate-decouple
    provides: "Precedent for duplication-for-isolation (crawl.py's frozen _GATE_BOILERPLATE_PATTERNS) reused here for token_count()"
provides:
  - "pipeline/quality/ package: PredicateResult, run_predicates(), compute_substance_signals(), and 7 check_* predicates"
  - "Zero-I/O quality primitive consumable by Plan 19-04 (classify_sections) and Phase 20 (QUAL-03 chunk substance gate)"
affects: [19-04-section-classifier, 20-chunk-substance-gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Duplication-for-isolation: pipeline/quality/constants.py duplicates tiktoken token_count() rather than importing pipeline.chunk (which pulls registry.db/storage.s3 at module scope)"
    - "Exemption-predicate override: check_table_exemption/check_domain_allowlist unconditionally short-circuit run_predicates() to passed=True when they themselves pass"
    - "Subprocess-isolated import-boundary test: proving a zero-I/O contract in-process is unreliable when conftest.py has autouse fixtures that import the forbidden modules first"

key-files:
  created:
    - src/knowledge_lake/pipeline/quality/__init__.py
    - src/knowledge_lake/pipeline/quality/constants.py
    - src/knowledge_lake/pipeline/quality/predicates.py
    - tests/unit/test_quality_predicates.py
  modified: []

key-decisions:
  - "PredicateResult implemented as dataclass(frozen=True), matching domains/models.py's ValidationResult precedent (Claude's Discretion per CONTEXT.md)"
  - "check_terminal_punct_ratio added as a 7th predicate beyond D-11's named six, to satisfy D-03's substance-threshold description explicitly (documented in predicates.py's module docstring)"
  - "Import-boundary test runs in a subprocess, not in-process sys.modules inspection, because tests/conftest.py's autouse _clear_settings_cache fixture imports knowledge_lake.registry.db (and sqlalchemy) before every test body regardless of what pipeline.quality does"

patterns-established:
  - "Zero-I/O pipeline submodules duplicate small helpers from heavier siblings rather than importing them, with an explicit rationale comment citing the precedent"

requirements-completed: [QUAL-01]

coverage:
  - id: D1
    description: "pipeline/quality/ package with 7 pure check_* predicates, PredicateResult, run_predicates() combinator, and compute_substance_signals() helper — zero I/O/S3/Dagster dependencies"
    requirement: "QUAL-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_quality_predicates.py (29 tests)"
        status: pass
      - kind: unit
        ref: "pytest tests/unit/test_quality_predicates.py --cov=knowledge_lake.pipeline.quality --cov-branch --cov-fail-under=100"
        status: pass
    human_judgment: false
  - id: D2
    description: "Zero-I/O contract: importing knowledge_lake.pipeline.quality never transitively loads sqlalchemy, boto3, or dagster"
    requirement: "QUAL-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_quality_predicates.py#test_import_does_not_pull_in_sqlalchemy_boto3_dagster (subprocess-isolated)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Exemption predicates (check_table_exemption, check_domain_allowlist) unconditionally override threshold failures when run_predicates() places them first"
    requirement: "QUAL-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_quality_predicates.py#test_run_predicates_exemption_short_circuits_before_threshold_fails"
        status: pass
    human_judgment: false

duration: 6min
completed: 2026-07-16
status: complete
---

# Phase 19 Plan 1: Quality Predicate Module Summary

**Zero-I/O `pipeline/quality/` package with 7 composable substance predicates (token floor, alpha ratio, link density, stopword ratio, terminal-punct ratio, table/domain-allowlist exemptions) and a `run_predicates()` combinator, backed by 100%-branch-covered tests — the deterministic-first primitive Plan 19-04's section classifier and Phase 20's chunk substance gate will both consume.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-16T17:09:25Z
- **Completed:** 2026-07-16T17:14:40Z
- **Tasks:** 2
- **Files modified:** 4 (all new)

## Accomplishments
- Built `pipeline/quality/constants.py` — local `tiktoken` encoder + `token_count()` (duplicated, not imported, from `pipeline/chunk.py`), and `STOP_WORDS_SET`/`TERMINAL_PUNCTUATION_SET` from DataTrove's static constants (never its tokenizer factory, per RESEARCH.md Pitfall 1)
- Built `pipeline/quality/predicates.py` — `PredicateResult` dataclass, 7 `check_*` predicates (the D-11 six plus `check_terminal_punct_ratio`), `compute_substance_signals()`, and `run_predicates()` with documented exemption-override + ordering-determinism semantics
- Built `pipeline/quality/__init__.py` re-exporting the full public surface with `__all__`
- Wrote `tests/unit/test_quality_predicates.py` — 29 tests covering every predicate's pass/fail/boundary branch, all three `run_predicates()` termination paths (including an explicit A-first vs B-first ordering-determinism pair), `compute_substance_signals()`'s empty/non-empty branches, and a subprocess-isolated zero-I/O import-boundary test — 100% branch coverage on the package

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement pipeline/quality/ pure predicate package** - `73165ee` (feat)
2. **Task 2: Write tests/unit/test_quality_predicates.py with 100% branch coverage** - `3b5972f` (test)

**Plan metadata:** (this commit)

## Files Created/Modified
- `src/knowledge_lake/pipeline/quality/__init__.py` - Public re-exports, `__all__`
- `src/knowledge_lake/pipeline/quality/constants.py` - `STOP_WORDS_SET`, `TERMINAL_PUNCTUATION_SET`, `_LINK_PATTERN`, local `token_count()`
- `src/knowledge_lake/pipeline/quality/predicates.py` - `PredicateResult`, 7 `check_*` predicates, `compute_substance_signals()`, `run_predicates()`, `_EXEMPTION_PREDICATES`
- `tests/unit/test_quality_predicates.py` - 29 tests, 100% branch coverage

## Decisions Made
- `PredicateResult` as `dataclass(frozen=True)` (Claude's Discretion, matches `ValidationResult` precedent in `domains/models.py`)
- Added `check_terminal_punct_ratio` as a 7th predicate to satisfy D-03's explicit substance-threshold description (documented in the module docstring as a non-exhaustive reading of D-11)
- Import-boundary test runs in a subprocess rather than checking `sys.modules` in-process — see Deviations below

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug/environment mismatch] Import-boundary test moved to subprocess isolation**
- **Found during:** Task 2 (writing the zero-I/O import-boundary test)
- **Issue:** The plan specified an in-process `sys.modules` check after `import knowledge_lake.pipeline.quality`. Running it showed `sqlalchemy` already present — not because `pipeline.quality` imports it, but because `tests/conftest.py`'s autouse `_clear_settings_cache` fixture imports `knowledge_lake.registry.db` (which imports SQLAlchemy) before every single test body runs in this suite, including this one. An in-process check can never pass here regardless of `pipeline.quality`'s actual behavior.
- **Fix:** Rewrote the test to shell out via `subprocess.run([sys.executable, "-c", ...])`, importing `knowledge_lake.pipeline.quality` in complete isolation from `conftest.py`'s fixtures and asserting `sys.modules` there. This proves the actual QUAL-01 claim instead of a claim invalidated by test-harness plumbing.
- **Files modified:** `tests/unit/test_quality_predicates.py`
- **Verification:** `uv run pytest tests/unit/test_quality_predicates.py --cov=knowledge_lake.pipeline.quality --cov-branch --cov-fail-under=100 -q` — 29 passed, 100% branch coverage
- **Committed in:** `3b5972f` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 environment mismatch)
**Impact on plan:** No scope creep — the test asserts exactly the property the plan intended (QUAL-01's zero-I/O contract), just measured correctly given this repo's test-harness reality.

## Issues Encountered
None beyond the deviation above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `pipeline/quality/` is ready for Plan 19-04 (`classify_sections()`) to import and wire into `clean.py`'s section-level filtering, and for Phase 20's chunk substance gate (QUAL-03) to reuse the identical predicates per D-12.
- Full unit suite verified green after this plan: `uv run pytest tests/unit -q` → 821 passed, 1 xfailed (pre-existing), 0 failed.
- Known gap carried forward (not fixed in this phase, per RESEARCH.md Pitfall 2): no builtin parser currently sets `Section.is_table=True`, so `check_table_exemption()` is forward-looking infrastructure only — the domain allowlist (`check_domain_allowlist`, wired in a later plan) is the effective safety net for tabular clinical content today. Already flagged in STATE.md's tech-debt list scope for future phases.

---
*Phase: 19-section-classifier-patterns*
*Completed: 2026-07-16*
