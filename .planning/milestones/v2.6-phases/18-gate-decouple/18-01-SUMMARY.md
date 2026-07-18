---
phase: 18-gate-decouple
plan: "01"
subsystem: pipeline/crawl
tags: [gate-decouple, recrawl, boilerplate, signature, tdd]
dependency_graph:
  requires: []
  provides: [GATE-01]
  affects: [pipeline/crawl.py, tests/unit/test_gate_signature_pin.py]
tech_stack:
  added: []
  patterns: [frozen-copy pattern (mirrors _VOLATILE_PATTERNS), byte-stability pin test]
key_files:
  created:
    - tests/unit/test_gate_signature_pin.py
  modified:
    - src/knowledge_lake/pipeline/crawl.py
decisions:
  - id: GATE-01
    summary: Gate boilerplate patterns frozen as a static copy in crawl.py at 2026-07-15
    rationale: Phase 19 extends BOILERPLATE_PATTERNS in clean.py; without decoupling, every source's _signature() would change triggering re-crawl of all 34 sources
    date: "2026-07-16"
metrics:
  duration: 4m
  completed: "2026-07-16T12:41:12Z"
  tasks_completed: 2
  files_modified: 2
status: complete
requirements: [GATE-01]
---

# Phase 18 Plan 01: Gate Decouple Summary

**One-liner:** Froze gate-local boilerplate patterns in `_GATE_BOILERPLATE_PATTERNS` + `_gate_normalize()`, severing `_signature()` from `remove_boilerplate()` in clean.py so Phase 19 pattern extensions don't trigger spurious re-crawls.

## What Was Built

### Task 1 — Freeze gate-local boilerplate patterns in crawl.py (D-01 through D-04)

Added to `src/knowledge_lake/pipeline/crawl.py`:

- `_GATE_BOILERPLATE_PATTERNS: list[re.Pattern]` — module-private list with the 4 compiled patterns in the exact order from `BOILERPLATE_PATTERNS` in `clean.py` at the freeze date 2026-07-15 (GATE-01). Block comment explains the deliberate non-sync design.
- `_gate_normalize(text: str) -> str` — gate-local normalization function that applies `_GATE_BOILERPLATE_PATTERNS` then inlines `_normalize_whitespace()` from clean.py verbatim (4-line body, character-for-character match — Pitfall 3 guard).
- Updated `_signature()` to call `_gate_normalize(markdown or "")` instead of `remove_boilerplate(markdown or "")`.
- Removed `from knowledge_lake.pipeline.clean import remove_boilerplate` import entirely.
- Updated docstrings and comment blocks (removed all stale references to `remove_boilerplate`).

**Commit:** e037040

### Task 2 — Gate signature pinning test (D-05, D-06)

Created `tests/unit/test_gate_signature_pin.py`:

- `_FIXTURE` — multi-line string triggering all 4 gate patterns.
- `_EXPECTED_HASH = "339b473b8b9a5e14768c138521e98259440f384a3b1379814c342b833807f826"` — 64-char SHA256, hardcoded at implementation time (not computed at import).
- `test_gate_signature_byte_stable()` — asserts `_signature(_FIXTURE) == _EXPECTED_HASH` with clear failure message explaining re-crawl consequence.
- `test_gate_decoupled_from_clean_patterns()` — appends a simulated Phase 19 pattern to `BOILERPLATE_PATTERNS`, asserts `_signature()` is unchanged, restores the list in `finally` block.

**Commit:** 099ed54

## Verification Results

```
uv run pytest tests/unit/test_gate_signature_pin.py tests/unit/test_recrawl_gate.py -x -v
7 passed in 1.45s

uv run pytest tests/ -x
1000 passed, 3 skipped, 6 xfailed in 117.95s
```

Decoupling smoke check: PASS: gate is decoupled

Import check: OK (no ImportError, no AttributeError)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated stale comments referencing `remove_boilerplate`**
- **Found during:** Task 1 acceptance criteria check (`grep -c "remove_boilerplate"` returned 2, not 0)
- **Issue:** Two comment lines in the `_VOLATILE_PATTERNS` block section referenced `remove_boilerplate` — the acceptance criteria required all references to be 0
- **Fix:** Updated the SCHED-02 block comment to reference `_gate_normalize` and removed the stale mention
- **Files modified:** `src/knowledge_lake/pipeline/crawl.py`
- **Commit:** e037040 (included in Task 1 commit)

## Known Stubs

None — all symbols are fully implemented with real logic.

## Threat Flags

None. This is a pure internal refactoring of a normalization function within crawl.py. No new inputs, network calls, data paths, or authentication surfaces.

## Self-Check: PASSED

- [x] `src/knowledge_lake/pipeline/crawl.py` exists with `_GATE_BOILERPLATE_PATTERNS`, `_gate_normalize`, updated `_signature`
- [x] `tests/unit/test_gate_signature_pin.py` exists with `_EXPECTED_HASH` (64-char hex)
- [x] Commit e037040 exists (Task 1)
- [x] Commit 099ed54 exists (Task 2)
- [x] `grep -c "from knowledge_lake.pipeline.clean import remove_boilerplate" crawl.py` → 0
- [x] `grep -c "remove_boilerplate" crawl.py` → 0
- [x] Full suite 1000 passed, 0 failed
