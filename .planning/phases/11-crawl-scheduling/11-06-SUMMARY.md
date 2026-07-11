---
phase: 11-crawl-scheduling
plan: 06
subsystem: crawl-scheduling
tags: [SCHED-02, recrawl-gate, anti-thrash, change-detection]
gap_closure: true
requires:
  - 11-03 (recrawl_source change gate)
provides:
  - Gate-local volatile-token suppression (_suppress_volatile) in pipeline/crawl.py
  - Behavior-verified SCHED-02 anti-thrash clause
affects:
  - src/knowledge_lake/pipeline/crawl.py (_signature, _suppress_volatile)
  - tests/unit/test_recrawl_gate.py
tech-stack:
  added: []
  patterns:
    - "Gate-local normalization layered on top of shared clean-stage helper (never modifying the shared helper)"
key-files:
  created: []
  modified:
    - src/knowledge_lake/pipeline/crawl.py
    - tests/unit/test_recrawl_gate.py
decisions:
  - "Volatile suppression is GATE-ONLY: remove_boilerplate / clean.py left byte-for-byte unchanged so silver-stage clean semantics and meaningful dates are preserved."
  - "ISO datetime pattern requires a TIME component, so bare effective/publication dates (e.g. 2026-01-01) are NOT suppressed."
metrics:
  duration: ~4m
  completed: 2026-07-11
status: complete
---

# Phase 11 Plan 06: Gate-Local Volatile-Token Suppression Summary

Closes the one behavior-unverified gap from 11-VERIFICATION.md truth #7: the recrawl change gate now neutralizes volatile machine-generated tokens (ISO-8601 timestamps, clock times, UUIDs, long hex nonces) so a page whose only inter-crawl delta is a dynamic timestamp/nonce yields a stable signature and skips re-ingest — satisfying SCHED-02's anti-thrash clause by construction rather than by assumption.

## What Changed

### `src/knowledge_lake/pipeline/crawl.py`
- Added `_VOLATILE_PLACEHOLDER`, `_VOLATILE_PATTERNS`, and `_suppress_volatile(text)` immediately above `_signature`. The four patterns match ISO-8601 datetimes (date + time), bare `HH:MM:SS` clock times, canonical UUIDs, and `>=16`-char hex nonces, replacing each with a fixed placeholder.
- Reworked `_signature` to apply `remove_boilerplate` first (D-06 boilerplate agreement preserved), then `_suppress_volatile`, then SHA256. `re` and `hashlib` were already imported at module level — no new imports.

### `tests/unit/test_recrawl_gate.py`
- Imports the gate's real `_signature` from `knowledge_lake.pipeline.crawl` in the guarded import block, so the test can never drift from the gate implementation.
- Removed the local `_signature` helper, the now-unused `from knowledge_lake.pipeline.clean import remove_boilerplate` import, and the unused `import hashlib`.
- Rewrote the tail of `test_nonce_noise_unchanged`: the self-fulfilling `if sig_a == sig_b / else` (which passed in both branches) is replaced with unconditional assertions — `sig_a == sig_b`, `crawl_source` not called, `touch_source_crawl` called once, `validate_public_url` called once.

## Verification

- `./.venv/bin/pytest tests/unit/test_recrawl_gate.py -x -q` → 5 passed. The nonce test now genuinely exercises suppression.
- `./.venv/bin/python -c "... _signature ..."` → `gate-normalizer OK`: nonce-only ISO timestamp delta yields identical signatures; bare-date delta (`2026-01-01` vs `2027-01-01`) yields different signatures.
- `./.venv/bin/pytest tests/unit/test_recrawl_sensor.py tests/unit/test_set_schedule_cli.py -q` → 6 passed (no regression).
- `git diff --stat` for commit `c2bdd19` shows only `pipeline/crawl.py` and `tests/unit/test_recrawl_gate.py` — `pipeline/clean.py` is NOT in the diff.

## Prohibitions honored
- `pipeline/clean.py` byte-for-byte unchanged (not in commit diff).
- Bare dates without a time component are not suppressed (ISO pattern requires a time component; asserted by the second `<automated>` check).
- All other gate tests (skip / changed / null / stale) stay green.
- The nonce test contains no conditional around its terminal assertions.

## Commits
- `c2bdd19` feat(11-06): gate-local volatile-token suppression closes SCHED-02 anti-thrash gap

## Deviations from Plan
None - plan executed exactly as written.

## Self-Check: PASSED
- FOUND: src/knowledge_lake/pipeline/crawl.py (modified, `_suppress_volatile` + updated `_signature`)
- FOUND: tests/unit/test_recrawl_gate.py (modified, imported `_signature`, unconditional nonce assertions)
- FOUND: commit c2bdd19
