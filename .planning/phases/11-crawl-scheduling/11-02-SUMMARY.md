---
phase: 11-crawl-scheduling
plan: 02
subsystem: registry
tags: [schema, migration, orm, settings, crawl-scheduling]
dependency_graph:
  requires: [11-01]
  provides: [0009-migration, source-crawl-columns, repo-crawl-helpers, max-staleness-setting]
  affects: [11-03, 11-04, 11-05]
tech_stack:
  added: []
  patterns: [namedtuple-materialization, own-session-helper, additive-migration]
key_files:
  created:
    - src/knowledge_lake/registry/alembic/versions/0009_crawl_scheduling.py
  modified:
    - src/knowledge_lake/registry/models.py
    - src/knowledge_lake/registry/repo.py
    - src/knowledge_lake/config/settings.py
    - tests/unit/test_registry.py
decisions:
  - "Columns nullable with no server_default — forward-only additive (D-01)"
  - "touch_source_crawl uses own get_session() — Dagster op calls without session"
  - "_ScheduledSource namedtuple for DetachedInstanceError safety"
metrics:
  duration: 5m
  completed: 2026-07-10
  tasks: 3
  files: 5
status: complete
---

# Phase 11 Plan 02: Schema & Registry Plumbing Summary

Additive Alembic 0009 migration with three nullable Source columns, four repo helpers, and max_staleness_days setting for crawl scheduling substrate.

## Completed Tasks

| # | Name | Type | Commit | Key Files |
|---|------|------|--------|-----------|
| 1 | Alembic 0009 migration + Source ORM columns | auto/tdd | b8cb8d2 | 0009_crawl_scheduling.py, models.py |
| 2 | repo helpers (touch/list/set/create kwarg) | auto/tdd | a9188ab | repo.py |
| 3 | CrawlSettings.max_staleness_days | auto | fe027c2 | settings.py |

## What Was Built

1. **Migration 0009** (`0009_crawl_scheduling.py`): Adds `crawl_schedule` (String(255)), `last_crawled_at` (DateTime(tz)), `last_content_hash` (String(64)) to `sources` table. All nullable, no server_default, no backfill. Downgrade drops in reverse order.

2. **Source ORM columns**: Three `Mapped[Optional[...]]` columns on the Source model placed after `config`, before `created_at`. Fully typed with docstrings.

3. **Repo helpers** in `repo.py`:
   - `create_source(..., crawl_schedule=None)` — extended signature persists schedule
   - `list_scheduled_sources(session)` — returns `_ScheduledSource` namedtuples (DetachedInstanceError-safe)
   - `set_source_schedule(session, source_id, schedule)` — update/clear; returns bool
   - `touch_source_crawl(source_id, last_crawled_at=..., last_content_hash=None)` — own-session watermark updater

4. **CrawlSettings.max_staleness_days** — defaults to 30, reads `KLAKE_CRAWL__MAX_STALENESS_DAYS`

## Verification Results

- `alembic heads` outputs `0009 (head)`
- 44 registry unit tests pass (including 18 new TDD tests)
- 27 settings unit tests pass
- All four repo helpers import cleanly
- `create_source` signature includes `crawl_schedule` parameter
- Env override `KLAKE_CRAWL__MAX_STALENESS_DAYS=7` yields 7

## Deviations from Plan

None - plan executed exactly as written.

## Decisions Made

1. **Own-session pattern for touch_source_crawl**: Uses `from knowledge_lake.registry.db import get_session` as a deferred import inside the function body to avoid circular imports and allow Dagster ops to call without holding a session.
2. **Namedtuple materialization**: `list_scheduled_sources` materializes all Source fields into `_ScheduledSource` before returning, preventing DetachedInstanceError when sensor iterates after session close.
3. **No server_default on 0009 columns**: All three columns are nullable with no default — existing sources see NULL which means "not scheduled" / "never crawled" / "always crawl".

## Self-Check: PASSED
