"""Dagster recrawl sensor and op-based job (SCHED-01, D-12/D-13/D-14/D-15/D-16/D-17).

This module provides the first-ever Dagster @sensor for Knowledge Lake:

  recrawl_sensor  — evaluates cron due-ness for each scheduled source and emits
                    deterministic, deduplicated RunRequests targeting recrawl_source_job.
  recrawl_op      — single op that drives the change-gated recrawl_source() pipeline.
  recrawl_source_job — op-based job tagged for QueuedRunCoordinator concurrency.
  RecrawlConfig   — Pydantic-backed run config carrying source_id.

Architecture decisions:
  D-12: @sensor in sensors.py, minimum_interval_seconds=60, registered via Definitions.
  D-13: Op-based recrawl_source_job reusing pipeline.crawl.recrawl_source.
  D-14: Deterministic run_key = f"{source_id}:{fire.isoformat()}" (cron fire, not now).
  D-15: Cursor watermark via context.update_cursor(now.isoformat()).
  D-16: Per-source concurrency=1 via klake/source tag + QueuedRunCoordinator.
  D-17: DB writes only in the op; sensor is side-effect-free apart from cursor.

Cron helpers come from dagster._utils.schedules (Dagster's vendored croniter engine).
No external croniter dependency is imported (Pitfall 1, T-11-SC).
"""

from datetime import UTC, datetime

import dagster as dg
from dagster._utils.schedules import get_latest_completed_cron_tick, get_next_cron_tick

# ── Helpers (patchable for tests) ────────────────────────────────────────────


def _get_now() -> datetime:
    """Return current UTC time. Exists as a seam for deterministic test control."""
    return datetime.now(UTC)


def list_scheduled_sources() -> list:
    """Load scheduled sources from the registry. Wraps the repo helper with its own session.

    Extracted as a module-level function so tests can patch it without touching DB.
    """
    from knowledge_lake.registry import repo
    from knowledge_lake.registry.db import get_session

    with get_session() as session:
        return repo.list_scheduled_sources(session)


# ── Run Config ───────────────────────────────────────────────────────────────


class RecrawlConfig(dg.Config):
    """Run-time configuration for the recrawl op (mirrors assets.py IngestConfig style)."""

    source_id: str
    """Primary key of the Source to re-crawl."""


# ── Op ───────────────────────────────────────────────────────────────────────


@dg.op(retry_policy=dg.RetryPolicy(max_retries=2, delay=1, backoff=dg.Backoff.EXPONENTIAL))
def recrawl_op(context: dg.OpExecutionContext, config: RecrawlConfig) -> dict:
    """Drive the change-gated recrawl for a single source (D-13/D-17).

    Lazy-imports recrawl_source and runs it via asyncio.run. All DB writes
    (touch_source_crawl) happen inside recrawl_source — this op performs no
    registry mutations itself.
    """
    import asyncio

    from knowledge_lake.pipeline.crawl import recrawl_source

    result = asyncio.run(recrawl_source(config.source_id))
    context.log.info("recrawl.op.done", extra={"result": result})
    return result


# ── Job ──────────────────────────────────────────────────────────────────────


@dg.job(tags={"klake/kind": "recrawl"})
def recrawl_source_job():
    """Op-based job targeting recrawl_op. Tagged for the QueuedRunCoordinator."""
    recrawl_op()


# ── Sensor ───────────────────────────────────────────────────────────────────


@dg.sensor(
    job=recrawl_source_job,
    minimum_interval_seconds=60,
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def recrawl_sensor(context: dg.SensorEvaluationContext):
    """Evaluate cron due-ness for scheduled sources and emit RunRequests (D-12).

    Side-effect-free apart from context.update_cursor (D-15/D-17).
    Deterministic run_key from the cron fire timestamp, not now (D-14).
    Tags runs with klake/source for per-source concurrency (D-16).
    """
    now = _get_now()
    scheduled = list_scheduled_sources()

    requests: list[dg.RunRequest] = []
    for src in scheduled:
        base = src.last_crawled_at or src.created_at
        # D-04: due when now >= next cron fire after the base time
        if now >= get_next_cron_tick(src.crawl_schedule, base, "UTC"):
            # D-14: fire = the most recent completed cron tick at/before now
            fire = get_latest_completed_cron_tick(src.crawl_schedule, now, "UTC")
            requests.append(
                dg.RunRequest(
                    run_key=f"{src.id}:{fire.isoformat()}",
                    run_config=dg.RunConfig(
                        ops={"recrawl_op": RecrawlConfig(source_id=src.id)}
                    ),
                    tags={"klake/source": src.id},
                )
            )

    # D-15: cursor watermark (only side-effect in the sensor)
    context.update_cursor(now.isoformat())

    if requests:
        return dg.SensorResult(run_requests=requests)
    return dg.SkipReason("no sources due")
