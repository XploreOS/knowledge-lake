"""RED scaffold for SCHED-01 recrawl sensor.

Tests validate that the Dagster recrawl_sensor:
  - Emits a deterministic run_key based on cron fire timestamp
  - Skips sources that are not yet due
  - Produces byte-identical run_keys within the same cron window (idempotent)

All tests are guarded by a try/except import so the module collects cleanly
before the target symbols exist (Plan 11-05).
"""

from __future__ import annotations

from collections import namedtuple
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

# ── Guarded import ────────────────────────────────────────────────────────────

try:
    from knowledge_lake.dagster_defs.sensors import (
        RecrawlConfig,  # noqa: F401
        recrawl_sensor,  # noqa: F401
        recrawl_source_job,  # noqa: F401
    )

    _HAS_SENSOR = True
except Exception:
    _HAS_SENSOR = False

pytestmark = pytest.mark.skipif(
    not _HAS_SENSOR, reason="recrawl_sensor pending (Plan 11-05)"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

# Import cron helpers for expected-value computation
from dagster._utils.schedules import get_latest_completed_cron_tick, get_next_cron_tick

# Materialized source row shape (mirrors repo._ScheduledSource)
_ScheduledSource = namedtuple(
    "_ScheduledSource",
    ["id", "url", "crawl_schedule", "last_crawled_at", "last_content_hash", "created_at", "config"],
)


def _make_source(
    sid: str = "src_001",
    url: str = "http://example.com/health",
    schedule: str = "0 3 * * *",
    last_crawled_at: datetime | None = None,
    created_at: datetime | None = None,
) -> _ScheduledSource:
    """Create a fake scheduled source row."""
    if created_at is None:
        created_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return _ScheduledSource(
        id=sid,
        url=url,
        crawl_schedule=schedule,
        last_crawled_at=last_crawled_at,
        last_content_hash="abc123" * 10 + "abcd",
        created_at=created_at,
        config={},
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_emits_deterministic_run_key() -> None:
    """A due source produces exactly one RunRequest whose run_key equals
    f'{sid}:{fire.isoformat()}' and whose tags include klake/source.
    """
    from dagster import RunRequest, build_sensor_context

    # Source last crawled 2 days ago, schedule is daily at 03:00 UTC
    sid = "src_due_001"
    now = datetime(2026, 7, 10, 4, 0, 0, tzinfo=timezone.utc)
    last_crawled = datetime(2026, 7, 8, 3, 0, 0, tzinfo=timezone.utc)

    source = _make_source(sid=sid, last_crawled_at=last_crawled)

    # Compute expected fire timestamp
    fire = get_latest_completed_cron_tick(source.crawl_schedule, now, "UTC")
    expected_run_key = f"{sid}:{fire.isoformat()}"

    with patch(
        "knowledge_lake.dagster_defs.sensors.list_scheduled_sources",
        return_value=[source],
    ), patch(
        "knowledge_lake.dagster_defs.sensors._get_now",
        return_value=now,
    ):
        context = build_sensor_context(cursor=None)
        result = recrawl_sensor(context)

    # Result should contain run requests
    if hasattr(result, "run_requests"):
        requests = result.run_requests
    else:
        requests = [result] if isinstance(result, RunRequest) else []

    assert len(requests) == 1, f"Expected 1 RunRequest, got {len(requests)}"
    req = requests[0]
    assert req.run_key == expected_run_key, (
        f"Expected run_key={expected_run_key!r}, got {req.run_key!r}"
    )
    assert req.tags.get("klake/source") == sid, (
        f"Expected tags to include klake/source={sid!r}, got {req.tags}"
    )
    # Cursor should be updated
    assert context.cursor is not None


def test_skips_not_due() -> None:
    """A source whose next fire is in the future yields a SkipReason and no RunRequest."""
    from dagster import SkipReason, build_sensor_context

    sid = "src_not_due"
    # Last crawled 1 minute after the 03:00 tick; next fire is ~23h59m away
    now = datetime(2026, 7, 10, 3, 2, 0, tzinfo=timezone.utc)
    last_crawled = datetime(2026, 7, 10, 3, 1, 0, tzinfo=timezone.utc)

    source = _make_source(sid=sid, last_crawled_at=last_crawled)

    # Verify the source is actually not due (next fire is tomorrow 03:00)
    next_fire = get_next_cron_tick(source.crawl_schedule, last_crawled, "UTC")
    assert now < next_fire, "Test setup error: source should not be due yet"

    with patch(
        "knowledge_lake.dagster_defs.sensors.list_scheduled_sources",
        return_value=[source],
    ), patch(
        "knowledge_lake.dagster_defs.sensors._get_now",
        return_value=now,
    ):
        context = build_sensor_context(cursor=None)
        result = recrawl_sensor(context)

    # Result should be a SkipReason (no run requests)
    if hasattr(result, "run_requests"):
        assert len(result.run_requests) == 0, (
            f"Expected 0 RunRequests for not-due source, got {len(result.run_requests)}"
        )
    else:
        assert isinstance(result, SkipReason), (
            f"Expected SkipReason for not-due source, got {type(result).__name__}"
        )


def test_run_key_stable_within_window() -> None:
    """Calling the sensor twice within the same cron window yields byte-identical run_keys."""
    from dagster import build_sensor_context

    sid = "src_stable"
    # Both calls happen after the 03:00 fire but before the next 03:00 fire
    now_1 = datetime(2026, 7, 10, 4, 0, 0, tzinfo=timezone.utc)
    now_2 = datetime(2026, 7, 10, 5, 30, 0, tzinfo=timezone.utc)
    last_crawled = datetime(2026, 7, 8, 3, 0, 0, tzinfo=timezone.utc)

    source = _make_source(sid=sid, last_crawled_at=last_crawled)

    # First evaluation
    with patch(
        "knowledge_lake.dagster_defs.sensors.list_scheduled_sources",
        return_value=[source],
    ), patch(
        "knowledge_lake.dagster_defs.sensors._get_now",
        return_value=now_1,
    ):
        ctx1 = build_sensor_context(cursor=None)
        result1 = recrawl_sensor(ctx1)

    # Second evaluation
    with patch(
        "knowledge_lake.dagster_defs.sensors.list_scheduled_sources",
        return_value=[source],
    ), patch(
        "knowledge_lake.dagster_defs.sensors._get_now",
        return_value=now_2,
    ):
        ctx2 = build_sensor_context(cursor=ctx1.cursor)
        result2 = recrawl_sensor(ctx2)

    # Extract run keys from both results
    def _get_run_keys(result):
        if hasattr(result, "run_requests"):
            return [r.run_key for r in result.run_requests]
        return []

    keys1 = _get_run_keys(result1)
    keys2 = _get_run_keys(result2)

    assert len(keys1) >= 1, "First evaluation should emit at least one RunRequest"
    assert keys1 == keys2, (
        f"Run keys must be identical within the same cron window. "
        f"First: {keys1}, Second: {keys2}"
    )
