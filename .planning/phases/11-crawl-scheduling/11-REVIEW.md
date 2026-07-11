---
phase: 11-crawl-scheduling
reviewed: 2026-07-10T12:00:00Z
depth: standard
files_reviewed: 15
files_reviewed_list:
  - infra/dagster/dagster.yaml
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/config/settings.py
  - src/knowledge_lake/dagster_defs/definitions.py
  - src/knowledge_lake/dagster_defs/sensors.py
  - src/knowledge_lake/domains/models.py
  - src/knowledge_lake/pipeline/crawl.py
  - src/knowledge_lake/registry/alembic/versions/0009_crawl_scheduling.py
  - src/knowledge_lake/registry/models.py
  - src/knowledge_lake/registry/repo.py
  - tests/integration/test_migrations.py
  - tests/unit/test_recrawl_gate.py
  - tests/unit/test_recrawl_sensor.py
  - tests/unit/test_registry.py
  - tests/unit/test_set_schedule_cli.py
findings:
  critical: 2
  warning: 3
  info: 2
  total: 7
status: issues_found
---

# Phase 11: Code Review Report

**Reviewed:** 2026-07-10T12:00:00Z
**Depth:** standard
**Files Reviewed:** 15
**Status:** issues_found

## Summary

Phase 11 adds crawl scheduling to Knowledge Lake: a new Alembic migration (0009) adding crawl columns to sources, a Dagster sensor that evaluates cron due-ness and emits RunRequests, a change-detection gate (`recrawl_source`), and a `set-schedule` CLI command with cron validation. The implementation is architecturally sound and follows existing codebase patterns. However, two critical issues exist in tests (tests cannot pass as written without a database connection), and several warnings about reliance on Dagster private APIs and deprecated module paths in dagster.yaml.

## Critical Issues

### CR-01: CLI tests test_accepts_valid_cron and test_clear_schedule fail without DB

**File:** `tests/unit/test_set_schedule_cli.py:63-106`
**Issue:** The tests patch `knowledge_lake.cli.app.set_source_schedule` but do NOT patch `knowledge_lake.registry.db.get_session`. For `test_accepts_valid_cron`, the cron passes validation at line 1203 of `app.py`, then execution proceeds to line 1207 where `get_session()` is called -- this attempts a real PostgreSQL connection. Similarly, `test_clear_schedule` enters the `if clear:` branch at line 1189 which immediately calls `get_session()`. Both tests will raise a connection error (psycopg OperationalError) in any environment without a running PostgreSQL instance, making them non-functional unit tests.
**Fix:**
```python
def test_accepts_valid_cron() -> None:
    mock_set_schedule = MagicMock(return_value=True)
    mock_session = MagicMock()

    with patch(
        "knowledge_lake.cli.app.set_source_schedule",
        mock_set_schedule,
    ), patch(
        "knowledge_lake.registry.db.get_session",
        return_value=MagicMock(__enter__=MagicMock(return_value=mock_session), __exit__=MagicMock(return_value=False)),
    ):
        result = runner.invoke(app, ["set-schedule", "src_001", "--cron", "0 3 * * *"])

    assert result.exit_code == 0
    mock_set_schedule.assert_called_once()
```
Alternatively, patch `knowledge_lake.cli.app.get_session` (the lazy import target within the function) using a context-manager-compatible mock.

### CR-02: Sensor imports from Dagster private API (`dagster._utils.schedules`)

**File:** `src/knowledge_lake/dagster_defs/sensors.py:27`
**Issue:** The sensor imports `get_latest_completed_cron_tick` and `get_next_cron_tick` from `dagster._utils.schedules`, a private internal module (prefixed with underscore). Private APIs carry no stability guarantees between Dagster minor versions. Since the project pins Dagster at 1.13.x and a minor version bump (e.g., 1.14.x) could remove or rename these functions without deprecation notice, this creates a hard runtime failure risk that would crash the sensor daemon with an ImportError and silently disable all scheduled recrawls.
**Fix:** Dagster 1.13.x exposes `is_valid_cron_string` publicly but not the tick computation functions. The safest fix is to add a thin wrapper module (`knowledge_lake/dagster_defs/_cron.py`) that isolates the private import behind a try/except with a fallback to the `croniter` library directly (which Dagster vendors internally):
```python
# knowledge_lake/dagster_defs/_cron.py
try:
    from dagster._utils.schedules import (
        get_latest_completed_cron_tick,
        get_next_cron_tick,
    )
except ImportError:
    from croniter import croniter
    from datetime import datetime

    def get_next_cron_tick(cron_str: str, after: datetime, tz: str) -> datetime:
        return croniter(cron_str, after).get_next(datetime)

    def get_latest_completed_cron_tick(cron_str: str, before: datetime, tz: str) -> datetime:
        return croniter(cron_str, before).get_prev(datetime)
```
Pin `croniter` as an explicit dependency (it is already a transitive dependency of Dagster).

## Warnings

### WR-01: dagster.yaml uses deprecated `dagster.core.*` module paths

**File:** `infra/dagster/dagster.yaml:29,36`
**Issue:** The `run_launcher` module path `dagster.core.launcher` and `run_coordinator` module path `dagster.core.run_coordinator` use the legacy `dagster.core` namespace. In Dagster 1.x, the internal package reorganized to `dagster._core`. While backward-compatibility shims exist in Dagster 1.13.x, these paths emit deprecation warnings at daemon startup and may be removed in a future major version. This can cause the dagster-daemon to fail to start after a Dagster upgrade.
**Fix:**
```yaml
run_launcher:
  module: dagster._core.launcher
  class: DefaultRunLauncher

run_coordinator:
  module: dagster._core.run_coordinator
  class: QueuedRunCoordinator
```
Or better, use Dagster's preferred configuration syntax if available in 1.13.x that does not require explicit module paths.

### WR-02: test_staleness_forces_refresh patches wrong module for get_settings

**File:** `tests/unit/test_recrawl_gate.py:321-326`
**Issue:** The test patches `knowledge_lake.config.settings.get_settings` but the target function `recrawl_source` in `crawl.py` uses its own module-level import binding (`from knowledge_lake.config.settings import ... get_settings`). Patching the original definition site does not affect the already-resolved name in `crawl.py`. The test passes by coincidence because the default `CrawlSettings.max_staleness_days` is 30 (same as the mock value), but if the default ever changes this test would silently stop verifying staleness behavior.
**Fix:**
```python
patch(
    "knowledge_lake.pipeline.crawl.get_settings",
    return_value=MagicMock(
        crawl=MagicMock(max_staleness_days=30),
        crawler="crawl4ai",
    ),
),
```

### WR-03: Sensor does not guard against sources with timezone-naive created_at

**File:** `src/knowledge_lake/dagster_defs/sensors.py:109`
**Issue:** The sensor computes `base = src.last_crawled_at or src.created_at` and then passes it to `get_next_cron_tick(src.crawl_schedule, base, "UTC")`. If `created_at` is timezone-naive (which can happen with SQLite test databases or improperly configured PostgreSQL), the comparison `now >= get_next_cron_tick(...)` will either raise a TypeError ("can't compare offset-naive and offset-aware datetimes") or produce incorrect results depending on Dagster's croniter internals. The `_ScheduledSource` namedtuple materializes `created_at` directly from the ORM which may not always carry timezone info.
**Fix:** Add a defensive tz-attachment in the sensor:
```python
import pytz

base = src.last_crawled_at or src.created_at
if base.tzinfo is None:
    base = base.replace(tzinfo=timezone.utc)
```

## Info

### IN-01: Redundant explicit session.commit() inside get_session() context

**File:** `src/knowledge_lake/cli/app.py:1195,1212`
**Issue:** The `get_session()` context manager (in `registry/db.py:86`) auto-commits on clean exit. The explicit `session.commit()` calls in the `set-schedule` command at lines 1195 and 1212 are harmless duplicates (committing an already-committed session is a no-op in SQLAlchemy) but are inconsistent with other code paths (e.g., `crawl.py` uses `session.flush()` only). This inconsistency can confuse future developers about whether `get_session()` auto-commits or not.
**Fix:** Remove the explicit `session.commit()` calls or add a comment noting the auto-commit behavior.

### IN-02: test_recrawl_gate mock returns "crawl_schedule" key unused by production code

**File:** `tests/unit/test_recrawl_gate.py:106,158,218,269,319`
**Issue:** The mock return value for `_get_source_for_recrawl` includes a `"crawl_schedule"` key that is not consumed by `recrawl_source()`. The real `_get_source_for_recrawl` function (line 71-88 of `crawl.py`) does not include `crawl_schedule` in its return dict either. This is dead data in the mocks that adds noise without value.
**Fix:** Remove the `"crawl_schedule"` key from the mock return dicts.

---

_Reviewed: 2026-07-10T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
