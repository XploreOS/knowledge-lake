---
phase: 11-crawl-scheduling
plan: 04
subsystem: cli/domains
tags: [crawl-schedule, cron-validation, cli, domain-init]
dependency_graph:
  requires: [11-02]
  provides: [set-schedule-cli, source-entry-crawl-schedule, domain-init-schedule-persist]
  affects: [11-05]
tech_stack:
  added: []
  patterns: [cron-validation-at-write, column-not-config]
key_files:
  created: []
  modified:
    - src/knowledge_lake/domains/models.py
    - src/knowledge_lake/cli/app.py
decisions:
  - "D-05a: crawl_schedule persisted as column kwarg, never inside Source.config"
  - "D-03: Cron validated with is_valid_cron_string (dagster vendored croniter) at both write paths"
  - "set_source_schedule imported at module level for test patchability"
metrics:
  duration: 3m
  completed: 2026-07-10
status: complete
---

# Phase 11 Plan 04: Schedule-Setting Paths Summary

Operator-facing set/clear of crawl_schedule via sources.yaml at domain-init and a klake set-schedule CLI verb, both guarded by Dagster's is_valid_cron_string so malformed cron never reaches the DB.

## What Was Built

1. **SourceEntry.crawl_schedule field** - Optional[str] field on the Pydantic model used by DomainLoader to read sources.yaml. Defaults to None (no auto-recrawl).

2. **domain-init cron persistence** - cmd_init now validates entry.crawl_schedule with is_valid_cron_string before passing it as a column kwarg to create_source. Invalid cron emits a stderr warning and persists None instead of aborting the whole init.

3. **klake set-schedule command** - New Typer command accepting source_id, --cron, and --clear. Validates cron before any write; --clear sets schedule to None; unknown source_id returns non-zero exit.

## Task Completion

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | SourceEntry.crawl_schedule field | 44a0fea | src/knowledge_lake/domains/models.py |
| 2 | Persist crawl_schedule at domain-init with cron validation | f67bdbd | src/knowledge_lake/cli/app.py |
| 3 | klake set-schedule command (set/clear with validation) | f417a5b | src/knowledge_lake/cli/app.py |

## Verification Results

- `pytest tests/unit/test_set_schedule_cli.py -x -q` - 3 passed
- `from knowledge_lake.cli.app import app` - imports cleanly with new command
- SourceEntry constructs with crawl_schedule=None (default) and accepts valid cron strings

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] git add for gitignored tracked file**
- **Found during:** Task 1 commit
- **Issue:** `.gitignore` has `domains/` rule that blocks `git add` on the already-tracked `src/knowledge_lake/domains/models.py`
- **Fix:** Used `git add -f` since the file is already tracked in git history
- **Files modified:** none (commit workflow only)

**2. [Rule 3 - Blocking] Test patchability requires module-level import**
- **Found during:** Task 3
- **Issue:** Tests patch `knowledge_lake.cli.app.set_source_schedule` which requires the symbol to exist at module level, not just as a local import inside the function
- **Fix:** Added `from knowledge_lake.registry.repo import set_source_schedule` at module level in app.py (verified no circular import issues)
- **Files modified:** src/knowledge_lake/cli/app.py

## Threat Model Compliance

- T-11-CRON (mitigate): Both write paths (domain-init and set-schedule CLI) validate cron with is_valid_cron_string before any DB write. Malformed cron never reaches the database.
- T-11-SC (mitigate): No new package added; is_valid_cron_string imported from dagster._utils.schedules (vendored croniter engine).

## Self-Check: PASSED
