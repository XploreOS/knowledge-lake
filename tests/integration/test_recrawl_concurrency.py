"""SCHED-01 per-source recrawl concurrency (D-16).

Exercises Dagster's REAL QueuedRunCoordinator dequeue decision
(`QueuedRunCoordinatorDaemon._get_runs_to_dequeue`) against an ephemeral
DagsterInstance seeded with genuine QUEUED runs, using the EXACT
`tag_concurrency_limits` parsed from the shipped ``infra/dagster/dagster.yaml``
(the same file mounted read-only into the dagster-webserver / dagster-daemon
compose services). No network, no crawling, no external services — the whole
thing runs on an ephemeral SQLite instance.

This is the durable regression guard behind Phase 11's human-verification item
#2 ("live per-source concurrency serialization"). It also fails if anyone
weakens the ``klake/source`` limit in dagster.yaml, because the assertions are
evaluated against whatever limit that file declares.

Two properties are proven:
  * same-source runs serialize to 1 while different sources run concurrently;
  * a queued same-source run is HELD while another same-source run is in flight,
    and a different source is unaffected.

The daemon internals used here are private Dagster APIs; imports are guarded so
the module SKIPS (rather than errors) if a future Dagster release moves them —
mirroring the guarded-import convention in tests/unit/test_recrawl_gate.py.
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from pathlib import Path

import pytest
import yaml

# ── Guarded imports (private daemon internals + test utils) ───────────────────
try:
    from dagster._core.remote_origin import RegisteredCodeLocationOrigin
    from dagster._core.storage.dagster_run import DagsterRunStatus
    from dagster._core.test_utils import create_run_for_test, instance_for_test
    from dagster._daemon.run_coordinator.queued_run_coordinator_daemon import (
        QueuedRunCoordinatorDaemon,
    )
    from dagster._grpc.types import RemoteJobOrigin, RemoteRepositoryOrigin

    _HAS_DAGSTER_INTERNALS = True
except Exception:  # pragma: no cover - depends on Dagster internal layout
    _HAS_DAGSTER_INTERNALS = False

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _HAS_DAGSTER_INTERNALS,
        reason="Dagster QueuedRunCoordinator daemon internals not importable in this version",
    ),
]

KEY = "klake/source"
SRC_A = "src_alpha"
SRC_B = "src_beta"

_DAGSTER_YAML = Path(__file__).resolve().parents[2] / "infra" / "dagster" / "dagster.yaml"


def _live_run_coordinator() -> dict:
    """Parse the shipped dagster.yaml run_coordinator block (skip if absent)."""
    if not _DAGSTER_YAML.is_file():
        pytest.skip(f"dagster.yaml not found at {_DAGSTER_YAML}")
    cfg = yaml.safe_load(_DAGSTER_YAML.read_text())
    rc = cfg.get("run_coordinator")
    if not rc or rc.get("class") != "QueuedRunCoordinator":
        pytest.skip("dagster.yaml does not configure QueuedRunCoordinator")
    return rc


def _overrides() -> dict:
    rc = _live_run_coordinator()
    limits = rc.get("config", {}).get("tag_concurrency_limits", [])
    # Config-drift guard: the per-source serialization limit must be present.
    src_limit = next((limit for limit in limits if limit.get("key") == KEY), None)
    assert src_limit is not None, (
        f"dagster.yaml no longer declares a tag_concurrency_limits entry for {KEY!r} "
        "— per-source recrawl serialization (D-16) would be lost."
    )
    assert src_limit.get("limit") == 1, (
        f"expected {KEY} concurrency limit of 1, got {src_limit.get('limit')}"
    )
    assert src_limit.get("value", {}).get("applyLimitPerUniqueValue") is True, (
        f"{KEY} limit must apply per unique value so different sources stay concurrent"
    )
    return {"run_coordinator": {"module": rc["module"], "class": rc["class"], "config": rc["config"]}}


def _origin() -> "RemoteJobOrigin":
    # Queued runs require a remote_job_origin; the coordinator only reads tags/status.
    return RemoteJobOrigin(
        RemoteRepositoryOrigin(RegisteredCodeLocationOrigin("test_location"), "test_repo"),
        "recrawl_source_job",
    )


def _queue(instance, source_id: str, status) -> None:
    create_run_for_test(
        instance,
        job_name="recrawl_source_job",
        remote_job_origin=_origin(),
        status=status,
        tags={KEY: source_id},
    )


def _daemon() -> "QueuedRunCoordinatorDaemon":
    d = QueuedRunCoordinatorDaemon(interval_seconds=1)
    if getattr(d, "_logger", None) is None:
        d._logger = logging.getLogger("test-queued-daemon")
    return d


def _dequeue_by_source(instance) -> Counter:
    cc = instance.get_concurrency_config()
    runs = _daemon()._get_runs_to_dequeue(instance, cc, fixed_iteration_time=time.time())
    return Counter(r.tags.get(KEY) for r in runs)


def test_same_source_serialized_cross_source_concurrent() -> None:
    """3 queued A + 2 queued B, nothing in flight → dequeue exactly 1 A and 1 B."""
    with instance_for_test(overrides=_overrides()) as instance:
        assert type(instance.run_coordinator).__name__ == "QueuedRunCoordinator"
        for _ in range(3):
            _queue(instance, SRC_A, DagsterRunStatus.QUEUED)
        for _ in range(2):
            _queue(instance, SRC_B, DagsterRunStatus.QUEUED)

        got = _dequeue_by_source(instance)

        assert got.get(SRC_A, 0) == 1, f"same-source must serialize to 1, got {got.get(SRC_A, 0)}"
        assert got.get(SRC_B, 0) == 1, f"different source must dequeue concurrently, got {got.get(SRC_B, 0)}"


def test_inflight_same_source_is_held() -> None:
    """1 A in flight + 2 queued A + 1 queued B → dequeue 0 A (held) and 1 B."""
    with instance_for_test(overrides=_overrides()) as instance:
        _queue(instance, SRC_A, DagsterRunStatus.STARTED)  # already running
        for _ in range(2):
            _queue(instance, SRC_A, DagsterRunStatus.QUEUED)
        _queue(instance, SRC_B, DagsterRunStatus.QUEUED)

        got = _dequeue_by_source(instance)

        assert got.get(SRC_A, 0) == 0, f"same-source must be held while one is in flight, got {got.get(SRC_A, 0)}"
        assert got.get(SRC_B, 0) == 1, f"different source must be unaffected, got {got.get(SRC_B, 0)}"
