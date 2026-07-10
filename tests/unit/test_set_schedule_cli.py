"""RED scaffold for CLI set-schedule cron validation (SCHED-01/SCHED-02).

Tests validate that the set-schedule CLI command:
  - Rejects malformed cron strings with a non-zero exit code
  - Accepts valid 5-field cron strings and persists via set_source_schedule
  - Supports --clear to set schedule to None

All tests are guarded by a try/except import so the module collects cleanly
before the target symbols exist (Plan 11-04).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ── Guarded import ────────────────────────────────────────────────────────────

try:
    from typer.testing import CliRunner
    from knowledge_lake.cli.app import app
    from knowledge_lake.registry.repo import set_source_schedule  # noqa: F401

    _HAS_CLI = True
except Exception:
    _HAS_CLI = False

pytestmark = pytest.mark.skipif(
    not _HAS_CLI, reason="set-schedule CLI pending (Plan 11-04)"
)

# ── Runner ────────────────────────────────────────────────────────────────────

if _HAS_CLI:
    runner = CliRunner()
else:
    runner = None  # type: ignore[assignment]


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_rejects_bad_cron() -> None:
    """Invoking set-schedule with a malformed cron string returns non-zero exit
    and does NOT call set_source_schedule.
    """
    mock_set_schedule = MagicMock()

    with patch(
        "knowledge_lake.cli.app.set_source_schedule",
        mock_set_schedule,
    ):
        result = runner.invoke(app, ["set-schedule", "src_001", "--cron", "not a cron"])

    assert result.exit_code != 0, (
        f"Expected non-zero exit for bad cron, got {result.exit_code}. "
        f"Output: {result.output!r}"
    )
    mock_set_schedule.assert_not_called()


def test_accepts_valid_cron() -> None:
    """A valid 5-field cron string persists via set_source_schedule."""
    mock_set_schedule = MagicMock()

    with patch(
        "knowledge_lake.cli.app.set_source_schedule",
        mock_set_schedule,
    ):
        result = runner.invoke(app, ["set-schedule", "src_001", "--cron", "0 3 * * *"])

    assert result.exit_code == 0, (
        f"Expected exit 0 for valid cron, got {result.exit_code}. "
        f"Output: {result.output!r}"
    )
    mock_set_schedule.assert_called_once()
    # Verify the cron value was passed
    call_args = mock_set_schedule.call_args
    assert "0 3 * * *" in str(call_args), (
        f"Expected cron '0 3 * * *' in set_source_schedule call, got {call_args}"
    )


def test_clear_schedule() -> None:
    """Invoking set-schedule with --clear writes None via set_source_schedule."""
    mock_set_schedule = MagicMock()

    with patch(
        "knowledge_lake.cli.app.set_source_schedule",
        mock_set_schedule,
    ):
        result = runner.invoke(app, ["set-schedule", "src_001", "--clear"])

    assert result.exit_code == 0, (
        f"Expected exit 0 for --clear, got {result.exit_code}. "
        f"Output: {result.output!r}"
    )
    mock_set_schedule.assert_called_once()
    # Verify None was passed as the schedule value
    call_args = mock_set_schedule.call_args
    assert "None" in str(call_args) or call_args[1].get("schedule") is None or (
        len(call_args[0]) > 1 and call_args[0][-1] is None
    ), (
        f"Expected None schedule in set_source_schedule call, got {call_args}"
    )
