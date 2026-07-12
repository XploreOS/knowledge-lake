---
phase: 11-crawl-scheduling
plan: 05
subsystem: dagster-sensor
tags: [sched-01, sensor, dagster, run-coordinator, wave-3]
dependency_graph:
  requires: [11-02, 11-03]
  provides: [recrawl-sensor, recrawl-source-job, queued-run-coordinator]
  affects: [src/knowledge_lake/dagster_defs/, infra/dagster/dagster.yaml]
tech_stack:
  added: []
  patterns: [dagster-sensor, dagster-op-job, cron-helpers-from-dagster-vendored, queued-run-coordinator-per-unique-value]
key_files:
  created:
    - src/knowledge_lake/dagster_defs/sensors.py
  modified:
    - src/knowledge_lake/dagster_defs/definitions.py
    - infra/dagster/dagster.yaml
    - tests/unit/test_recrawl_sensor.py
decisions:
  - "Cron helpers sourced from dagster._utils.schedules (no external croniter dependency)"
  - "_get_now and list_scheduled_sources exposed as module-level patchable seams for tests"
  - "Removed from __future__ import annotations to avoid Dagster Config resolution failure"
  - "Fixed test scaffold base-time edge case where get_next_cron_tick returns same tick as base (Rule 1)"
metrics:
  duration: 4m
  completed: "2026-07-10T16:49:35Z"
  tasks: 3
  files: 4
status: complete
---

# Phase 11 Plan 05: Dagster Recrawl Sensor Summary

Wired the first-ever Dagster @sensor for the Knowledge Lake: recrawl_sensor evaluates cron due-ness per scheduled source, emits deterministic deduplicated RunRequests targeting the op-based recrawl_source_job, with per-source concurrency=1 enforced by QueuedRunCoordinator.

## What Was Built

### Task 1: sensors.py (RecrawlConfig + recrawl_op + recrawl_source_job + recrawl_sensor)

Created `src/knowledge_lake/dagster_defs/sensors.py` containing:

- **RecrawlConfig(dg.Config)** — Pydantic-backed run config carrying `source_id`
- **recrawl_op** — drives `recrawl_source(source_id)` via `asyncio.run` with exponential backoff retry (max 2)
- **recrawl_source_job** — op-based job tagged `klake/kind: recrawl`
- **recrawl_sensor** — @sensor with `minimum_interval_seconds=60`, `DefaultSensorStatus.RUNNING`:
  - Reads scheduled sources via a patchable `list_scheduled_sources()` wrapper
  - Evaluates cron due-ness using `get_next_cron_tick(schedule, base, "UTC")`
  - Emits `RunRequest` with deterministic `run_key=f"{src.id}:{fire.isoformat()}"` (D-14)
  - Tags runs with `{"klake/source": src.id}` for coordinator concurrency (D-16)
  - Calls `context.update_cursor(now.isoformat())` as its only side-effect (D-15/D-17)
  - Returns `SkipReason` when no sources are due (Pitfall 6)

### Task 2: Definitions Registration

Added `recrawl_sensor` to `sensors=` and `recrawl_source_job` to `jobs=` in the Dagster Definitions call.

### Task 3: QueuedRunCoordinator

Replaced `DefaultRunCoordinator` in `infra/dagster/dagster.yaml` with `QueuedRunCoordinator` and `tag_concurrency_limits` enforcing `klake/source` per-unique-value limit of 1.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `from __future__ import annotations` incompatibility with Dagster Config**
- **Found during:** Task 1
- **Issue:** `from __future__ import annotations` makes all annotations lazy strings, preventing Dagster from resolving Config subclasses at decoration time (`DagsterInvalidPythonicConfigDefinitionError`).
- **Fix:** Removed `from __future__ import annotations`, used explicit types instead.
- **Files modified:** src/knowledge_lake/dagster_defs/sensors.py
- **Commit:** f49e824

**2. [Rule 1 - Bug] Fixed test scaffold base-time edge case**
- **Found during:** Task 1 (test verification)
- **Issue:** `test_skips_not_due` used `last_crawled_at` exactly on the cron tick time (03:00), causing `get_next_cron_tick(schedule, base)` to return the same tick (03:00), making `now (03:01) >= next_fire (03:00)` true instead of false.
- **Fix:** Changed `last_crawled_at` to 03:01 (after the tick) so `get_next_cron_tick` returns the next day's 03:00.
- **Files modified:** tests/unit/test_recrawl_sensor.py
- **Commit:** f49e824

## Verification Results

- `pytest tests/unit/test_recrawl_sensor.py -x -q` — 3 passed
- `pytest tests/unit/test_recrawl_gate.py -x -q` — 5 passed (all phase tests green)
- No `import croniter` in sensors.py (confirmed via grep)
- `dagster._utils.schedules` used for cron helpers
- Definitions load successfully with sensor and job registered
- dagster.yaml validates with QueuedRunCoordinator + tag_concurrency_limits

## TDD Gate Compliance

- RED: test_recrawl_sensor.py existed as a skipif-guarded scaffold (Wave 0, Plan 11-01)
- GREEN: sensors.py created, all 3 tests pass (commit f49e824)
- test(11-01) commit exists as the RED gate from Plan 11-01
- feat(11-05) commit exists as the GREEN gate

## Known Stubs

None — all components are fully wired to their production dependencies.

## Self-Check: PASSED
