---
phase: 11-crawl-scheduling
plan: 01
subsystem: tests
tags: [tdd, red-scaffold, sched-01, sched-02, wave-0]
dependency_graph:
  requires: []
  provides: [test-scaffold-recrawl-gate, test-scaffold-recrawl-sensor, test-scaffold-set-schedule-cli, migration-head-chain-assertion]
  affects: [tests/unit, tests/integration/test_migrations.py]
tech_stack:
  added: []
  patterns: [guarded-import-skipif, dagster-build_sensor_context, async-mock-monkeypatch]
key_files:
  created:
    - tests/unit/test_recrawl_gate.py
    - tests/unit/test_recrawl_sensor.py
    - tests/unit/test_set_schedule_cli.py
  modified:
    - tests/integration/test_migrations.py
decisions:
  - "Sensor tests monkeypatch a _get_now helper for deterministic time control (avoids timezone.utc mocking complexity)"
  - "Gate tests use _FakeCrawler class with async fetch_page returning _FakePage.markdown for controlled content"
  - "Migration head-chain assertion uses skipif guard on 0009 module import (no live DB needed for chain read)"
metrics:
  duration: 3m
  completed: "2026-07-10T10:58:30Z"
  tasks: 3
  files: 4
status: complete
---

# Phase 11 Plan 01: RED Test Scaffold Summary

Guarded unit test scaffold for SCHED-01 (recrawl sensor) and SCHED-02 (change gate) with 11 total test functions that skip cleanly until implementation plans land their target symbols.

## What Was Built

### tests/unit/test_recrawl_gate.py (5 tests)
- `test_unchanged_skips_no_raw` — signature match skips crawl_source, only bumps last_crawled_at
- `test_changed_recrawls` — different signature triggers full crawl_source
- `test_nonce_noise_unchanged` — dynamic tokens normalized away produce stable signature
- `test_null_hash_forces_crawl` — NULL last_content_hash always crawls
- `test_staleness_forces_refresh` — stale source crawls despite matching hash

### tests/unit/test_recrawl_sensor.py (3 tests)
- `test_emits_deterministic_run_key` — run_key = `{sid}:{fire.isoformat()}`
- `test_skips_not_due` — source with future next_fire yields SkipReason
- `test_run_key_stable_within_window` — idempotent within same cron window

### tests/unit/test_set_schedule_cli.py (3 tests)
- `test_rejects_bad_cron` — malformed cron rejected pre-write
- `test_accepts_valid_cron` — valid 5-field cron persists
- `test_clear_schedule` — `--clear` writes None

### tests/integration/test_migrations.py (extended)
- Added `crawl_schedule`, `last_crawled_at`, `last_content_hash` to `TestSourcesSchema.REQUIRED_COLUMNS`
- Added `TestMigrationHeadChain` class asserting 0009 revision/down_revision (skipif 0009 absent)

## Deviations from Plan

None - plan executed exactly as written.

## Threat Surface Validation

| Threat ID | Test Coverage |
|-----------|--------------|
| T-11-SSRF | `test_recrawl_gate.py` asserts `validate_public_url` is called before fetch_page |
| T-11-THRASH | `test_unchanged_skips_no_raw` asserts crawl_source NOT called on unchanged pages |
| T-11-TICKSTORM | `test_run_key_stable_within_window` asserts deterministic run_key dedup |
| T-11-CRON | `test_rejects_bad_cron` asserts malformed cron rejected at CLI entry |
| T-11-WRITE | Sensor tests monkeypatch only `list_scheduled_sources` (no DB write mocks) |
| T-11-SC | No `import croniter` in any test file — uses `dagster._utils.schedules` only |

## Verification Results

```
tests/unit/test_recrawl_gate.py:      5 skipped, 0 errors
tests/unit/test_recrawl_sensor.py:    3 skipped, 0 errors
tests/unit/test_set_schedule_cli.py:  3 skipped, 0 errors
Full unit suite:                      407 passed, 11 skipped, 0 errors
```

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | f05f605 | RED scaffold for SCHED-02 change gate |
| 2 | 58d6646 | RED scaffold for SCHED-01 recrawl sensor |
| 3 | 73fe0f1 | RED scaffold for CLI set-schedule + migration head chain |
