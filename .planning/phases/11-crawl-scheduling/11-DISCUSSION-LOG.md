# Phase 11: Crawl Scheduling - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-10
**Phase:** 11-crawl-scheduling
**Mode:** `--auto` — all gray areas auto-selected; recommended (first) option chosen for each without interactive prompts.
**Areas discussed:** Schema migration shape, Schedule format & due-check, Change-detection gate, Max-staleness policy, Sensor mechanics

---

## Schema migration shape (0009)

| Option | Description | Selected |
|--------|-------------|----------|
| Additive forward-only, all nullable, no backfill | Alembic `0009` (down_revision `0008`) adds 3 nullable columns; existing rows get NULL; opt-in | ✓ |
| Nullable columns + backfill defaults | Add columns then backfill `crawl_schedule`/staleness defaults for all sources | |
| Separate `source_schedule` table | Normalize schedule/watermark into a side table joined to `sources` | |

**Auto-selected:** Additive forward-only, all nullable, no backfill (recommended).
**Notes:** Matches ROADMAP's forward-only migration note and the `0006`/`0007`/`0008` additive precedent. NULL `crawl_schedule` = unscheduled, so the sensor is disable-able independently of the schema (rollback requirement).

---

## Schedule format & due-check

| Option | Description | Selected |
|--------|-------------|----------|
| Cron string (UTC) + croniter due-check | `crawl_schedule` = 5-field cron; `next_fire = croniter(sched, base=last_crawled_at or created_at)`; due when `now >= next_fire` | ✓ |
| Interval seconds | Store a plain re-crawl interval in seconds; due when `now - last_crawled_at > interval` | |
| Named cadence enum (daily/weekly/monthly) | Fixed presets mapped to intervals | |

**Auto-selected:** Cron string (UTC) + croniter due-check (recommended).
**Notes:** Cron is Dagster-native, matches the daemon tick model, and gives operators wall-clock cadence control. Use a maintained cron lib (croniter, likely already a Dagster transitive dep — confirm at research); no hand-rolled parsing.

---

## Change-detection gate (SCHED-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse silver normalizer, hash seed page pre-`put_raw` | SHA256 over `remove_boilerplate()`/`_normalize_whitespace()` output of the fetched seed markdown; compare to `last_content_hash` before any raw write | ✓ |
| Hash after full parse+clean, gate downstream | Let raw/bronze/parse/clean run, then compare `cleaned_document.content_hash` and skip enrich/embed only | |
| Raw-bytes comparison | Compare raw HTML bytes to last fetch | |

**Auto-selected:** Reuse silver normalizer, hash seed page pre-`put_raw` (recommended).
**Notes:** Raw-bytes comparison is an explicit REQUIREMENTS.md anti-feature (WORM/spend thrash). Gating post-clean still writes the immutable raw object every tick. Pre-`put_raw` seed probe using the *same* silver normalizer is the only option that keeps the WORM raw zone and LLM spend untouched for unchanged content while keeping "changed" consistent with the silver zone. Source-level (seed-page) signature for v2.0; per-page deferred.

---

## Max-staleness forced refresh

| Option | Description | Selected |
|--------|-------------|----------|
| Global setting + per-source override | `KLAKE_CRAWL__MAX_STALENESS_DAYS` (default 30) + optional `crawl_config.max_staleness_days`; force re-ingest when exceeded | ✓ |
| Global setting only | Single global threshold, no per-source override | |
| No forced refresh | Trust the change gate entirely | |

**Auto-selected:** Global setting + per-source override (recommended).
**Notes:** Catches change-gate false negatives (normalizer over-stripping a real edit). Measured against `last_crawled_at` (updated every attempt) so the forced deep refresh fires once per staleness window, not every skipped tick. Per-source override reuses the Phase 8 `Source.config.crawl_config` nesting.

---

## Sensor mechanics (SCHED-01)

| Option | Description | Selected |
|--------|-------------|----------|
| op-based `recrawl_source_job`, `run_key=source_id:fire_ts`, cursor watermark, per-source concurrency=1 | Sensor emits deterministic RunRequests targeting an op that wraps `crawl_source()`; cursor advances each tick; concurrency limited per source | ✓ |
| Wrap crawl as a Dagster asset + asset sensor | Turn the crawl into a materializable asset and use an asset/multi-asset sensor | |
| Dagster `@schedule` per source | One schedule object per scheduled source instead of a single sensor | |

**Auto-selected:** op-based `recrawl_source_job` + deterministic run_key + cursor + per-source concurrency (recommended).
**Notes:** `run_key = source_id:cron_fire_timestamp` (fire time, not `now`) makes tick storms and daemon restarts idempotent — Dagster dedups on it. Crawl is not an asset (asset graph starts at ingest), so an op-based job is the natural target; it calls `crawl_source()` and duplicates no crawl logic. DB writes (`last_crawled_at`/`last_content_hash`) happen in the op, not the side-effect-free sensor.

---

## Claude's Discretion
- Cron library choice and whether to pin it directly (confirm what Dagster ships).
- Sensor `minimum_interval_seconds`; concurrency via Dagster pools vs run-tag limits.
- Whether the change gate is a `recrawl=True` branch inside `crawl_source()` or a thin `recrawl_source()` wrapper.
- Exact CLI verb for set/clear schedule; optional REST exposure.
- Whether the seed-page probe reuses the crawler adapter or a lighter direct GET (must still pass SSRF `validate_public_url`).

## Deferred Ideas
- Per-page granular change detection on deep crawls (single-column scope keeps it source-level for v2.0).
- Auto-discovery scheduling (DISCOVER-01) — v2.1.
- Sitemap-first re-crawl using `<lastmod>` (SITEMAP-01) — v2.1.
- Adaptive schedule tuning based on observed change frequency — not requested.
