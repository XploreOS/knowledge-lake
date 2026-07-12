# Phase 11: Crawl Scheduling - Research

**Researched:** 2026-07-10
**Domain:** Dagster sensors + cron scheduling, additive Alembic migration, normalized-text change detection over the crawl pipeline
**Confidence:** HIGH (all version-sensitive facts verified against the installed `.venv`: dagster 1.13.11, sensor/op/job wiring executed in-process)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Additive Alembic `0009` (`revision="0009"`, `down_revision="0008"`) adds three **nullable** columns to `sources`, mirroring `0006`/`0007`/`0008`: `crawl_schedule` `String(255)`; `last_crawled_at` `DateTime(timezone=True)`; `last_content_hash` `String(64)`. Forward-only — no backfill, no NOT NULL, no server default. Add matching `Mapped[...]` attributes with docstrings to `Source` (`registry/models.py:58`).
- **D-02:** `crawl_schedule IS NULL` ⇒ source is **not** auto-recrawled (sensor skips). Opt-in; satisfies the independent-rollback note.
- **D-03:** `crawl_schedule` = **5-field cron string**, interpreted in **UTC** (e.g. `"0 3 * * *"`).
- **D-04:** Due-check: `base = last_crawled_at or source.created_at`; `next_fire = <cron>(schedule, base).get_next()`; **due** when `now >= next_fire`. Use a maintained cron library — do **not** hand-roll cron parsing.
- **D-05:** Schedule set two ways: (a) `crawl_schedule:` key in `domains/*/sources.yaml`, persisted at `domain-init`; (b) a CLI verb to set/clear on an existing source. YAML is primary; CLI is the override. REST optional.
- **D-06:** Change signature = `SHA256` over **normalized** text using the **exact same** transform silver `clean()` applies — `remove_boilerplate()` → (`_normalize_whitespace()`). Reuse directly; no second normalizer.
- **D-07:** Gate runs at **crawl time, on the seed/canonical page, BEFORE any raw write.** Unchanged + within staleness → skip entirely, update only `last_crawled_at`. Changed or `last_content_hash IS NULL` → run full `crawl_source()`, then set `last_content_hash` + `last_crawled_at`.
- **D-08:** WORM-safe by construction — unchanged content never reaches `put_raw`. Complements (not replaces) the artifact-layer raw content-hash dedup no-op.
- **D-09:** v2.0 signature is **source-level, keyed on the seed page** (single `last_content_hash` column). Per-page granular tracking deferred.
- **D-10:** Max-staleness forced re-ingest even when signature unchanged. `KLAKE_CRAWL__MAX_STALENESS_DAYS` (default `30`), optional per-source override `crawl_config.max_staleness_days`. When `now - last_crawled_at > max_staleness`, bypass the gate.
- **D-11:** Staleness measured against `last_crawled_at`, updated on **every** re-crawl attempt (changed or skipped).
- **D-12:** `@sensor` in new `dagster_defs/sensors.py`, registered via `Definitions(sensors=[...])`. Modest `minimum_interval_seconds` (~60). Iterates non-NULL-schedule sources, emits one `RunRequest` per due source.
- **D-13:** Target = new **op-based** `recrawl_source_job` (crawl is not a pipeline asset). Single op reads `source_id` from run config, calls `crawl_source()` (via `asyncio.run`) behind the gate. Re-implements no crawl logic.
- **D-14:** Deterministic `run_key = f"{source_id}:{scheduled_fire_iso}"` where `scheduled_fire_iso` is the **cron fire timestamp** (not `now`).
- **D-15:** Sensor persists a **cursor watermark** (`context.update_cursor()`) = ISO timestamp of the last evaluation.
- **D-16:** Per-source concurrency = 1: tag runs `{"klake/source": source_id}` + a Dagster concurrency limit. Global crawl concurrency modest; per-host politeness stays in the Phase 8 `PerHostLimiter`.
- **D-17:** `last_crawled_at` / `last_content_hash` writes happen inside the crawl **op** after `crawl_source()` returns — never in the sensor. Sensor side-effect-free apart from its cursor.

### Claude's Discretion
- Cron library choice + whether to pin it as a direct dep — **confirm what Dagster already ships** (RESEARCHED — see below).
- Exact `minimum_interval_seconds`; concurrency via Dagster pools vs run-tag limits.
- Change-gate probe as `recrawl=True` branch inside `crawl_source()` vs a thin `recrawl_source()` wrapper — as long as D-06/D-07/D-08 hold, no crawl logic duplicated.
- Exact CLI verb/signature for set/clear schedule; whether a REST endpoint is added.
- Whether the seed-page probe reuses the crawler adapter or a lighter direct GET (must still pass Phase 8 SSRF `validate_public_url`).

### Deferred Ideas (OUT OF SCOPE)
- Per-page granular change detection on deep crawls (single `last_content_hash` column only).
- Auto-discovery scheduling (DISCOVER-01, v2.1).
- Sitemap-first re-crawl (SITEMAP-01, v2.1).
- Adaptive schedule tuning (not requested).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SCHED-01 | Dagster sensor triggers periodic re-crawl based on `crawl_schedule`, with deterministic `run_key` + cursor watermark to avoid duplicate runs / tick storms. | Sensor→op→job wiring verified in-process against dagster 1.13.11 (see Code Examples). Deterministic `run_key` + `update_cursor()` confirmed. Cron due-check via Dagster's vendored `get_next_cron_tick`/`get_latest_completed_cron_tick`. Per-source concurrency requires a `dagster.yaml` run-coordinator change (Pitfall 5). |
| SCHED-02 | Change comparison over **normalized silver-stage text** (not raw bytes); max-staleness forced refresh. | `remove_boilerplate()` (`clean.py:82`) is the exact normalizer; `clean()` (`clean.py:233`) hashes `cleaned_text.encode("utf-8")` with `hashlib.sha256(...).hexdigest()` — the signature the gate mirrors. Seed markdown is available from `adapter.fetch_page(url).markdown` (`protocols.py:CrawlPageResult`) before any `put_raw`. |
</phase_requirements>

## Summary

This phase is **integration-heavy, not algorithmically hard**. Every hard part already exists in the codebase: the normalizer (`remove_boilerplate`), the SHA256-over-normalized-text pattern (`clean()`), the full crawl vertical (`crawl_source`), the SSRF guard (`validate_public_url`), the additive-migration convention (`0006`–`0008`), and the session-safe repo helpers. The work is (1) three nullable columns via Alembic `0009`, (2) a change gate that reuses the silver normalizer on the seed page **before** `put_raw`, and (3) a first-ever Dagster `@sensor` + op-based `recrawl_source_job` wired into the existing `Definitions`.

The single most important **correction to a CONTEXT assumption**: **`croniter` is NOT importable as an ordinary Dagster transitive dependency** (D-04 assumed it was). Dagster 1.13.11 **vendors** it privately at `dagster._vendored.croniter` and does not expose it on `sys.path`. However, Dagster ships a clean, stable set of cron helpers in `dagster._utils.schedules` — `get_next_cron_tick(cron_string, current_time, timezone)`, `get_latest_completed_cron_tick(...)`, and `is_valid_cron_string(...)` — all verified working. **Recommendation: use these Dagster helpers and add NO new dependency.** They use the exact same croniter engine, match Dagster's own daemon tick semantics, and (because `dagster==1.13.11` is exact-pinned in `pyproject.toml`) carry negligible upgrade risk. Adding `croniter` directly is a viable fallback but the legitimacy seam flags its latest release as `SUS` (too-new patch, PyPI hides download counts), so it would require a human-verify checkpoint.

The second landmark is infrastructure: `infra/dagster/dagster.yaml` currently uses `DefaultRunCoordinator`, under which **tag-based per-source concurrency limits (D-16) do nothing**. Per-unique-value concurrency requires `QueuedRunCoordinator` with `tag_concurrency_limits: [{key: klake/source, value: {applyLimitPerUniqueValue: true}, limit: 1}]`. The plan must edit `dagster.yaml`, or accept that the deterministic `run_key` + the existing `_find_or_create_job` job-reuse already bound overlap.

**Primary recommendation:** Reuse `remove_boilerplate()` + `hashlib.sha256` for the gate; add a thin `recrawl_source()` (or `recrawl=True` branch) that seed-probes → normalizes → compares before touching `put_raw`; drive it from an op-based `recrawl_source_job`; schedule with a `@sensor` using Dagster's vendored `get_latest_completed_cron_tick` for both the due-check and the deterministic `run_key`; switch `dagster.yaml` to `QueuedRunCoordinator` for D-16.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Deciding *when* a source is due | Dagster daemon (sensor) | — | Sensor evaluates cron due-ness each tick; side-effect-free except cursor (D-15/D-17). |
| Deduplicating fires / preventing tick storms | Dagster run storage (`run_key`) | Sensor cursor | Dagster dedups `RunRequest`s by `run_key`; cursor bounds which fires were emitted (D-14/D-15). |
| Per-source serialization (concurrency=1) | Dagster run coordinator (`QueuedRunCoordinator` + `tag_concurrency_limits`) | `_find_or_create_job` job-reuse | Only the queued coordinator enforces per-unique-value limits (D-16, Pitfall 5). |
| Deciding *whether* content changed | `pipeline` (change gate) | `registry` (`last_content_hash`) | Normalized-text hash compare — reuses silver normalizer (D-06/D-07). |
| Actually crawling | `pipeline.crawl.crawl_source()` | crawl4ai adapter, `PerHostLimiter` | Unchanged from Phase 8; the op wraps it wholesale (D-13). |
| Persisting crawl watermarks | `registry` (`touch_source_crawl`) | crawl **op** | Writes happen in the op after `crawl_source()` returns (D-17), never in the sensor. |
| Storing/reading the schedule | `registry` (`Source.crawl_schedule` column) + `Source.config.crawl_config` | CLI / `domain-init` | Cron string is a first-class column; `max_staleness_days` override rides `crawl_config` JSON (D-10). |

## Standard Stack

### Core (all already installed — verified in `.venv`)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| dagster | **1.13.11** | `@sensor`, `@op`/`@job`, `RunRequest`, `RunConfig`, cursor, cron helpers | Project orchestration constraint (Dagster from day 1). Verified installed. |
| SQLAlchemy | 2.0.51 | `Mapped[...]` column additions on `Source` | Existing ORM. |
| Alembic | 1.18.5 | Additive `0009` migration | Existing migration tooling; head is `0008`. |
| psycopg (binary) | 3.3.4 | Postgres driver | Existing. |
| hashlib (stdlib) | — | `sha256` change signature | Same primitive `clean()` uses (`clean.py:233`). |
| structlog | 26.x | Sensor/op logging | Existing convention. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `dagster._utils.schedules` (internal) | ships with 1.13.11 | `get_next_cron_tick`, `get_latest_completed_cron_tick`, `is_valid_cron_string` | **Recommended** cron primitives — zero new dep (see Cron section). |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Dagster vendored cron helpers | `croniter==6.x` as a **direct** dep | Public, documented API and D-04's literal wording — but flagged `SUS` by the legitimacy seam (must gate behind a human-verify checkpoint) and adds a dependency Dagster already vendors. |
| Cron string schedule (D-03, locked) | Plain interval-seconds | Locked to cron; not revisited. |
| `QueuedRunCoordinator` (per-source limit) | Op-level concurrency `pool` | Pools give only a single **global** limit for a named pool, **not** per-`source_id` limits. `applyLimitPerUniqueValue` needs the queued coordinator (Pitfall 5). |

**Installation:** No new packages required if the Dagster vendored cron helper is used (recommended). If `croniter` is added as a direct dep instead:
```bash
uv add 'croniter>=2,<7'   # gate behind checkpoint:human-verify — flagged SUS (see audit)
```

**Version verification (performed this session):**
- `dagster.__version__` → `1.13.11` (matches `pyproject.toml` exact pin) [VERIFIED: .venv import]
- `import croniter` → `ModuleNotFoundError` [VERIFIED: .venv import] — **not** an ordinary transitive dep.
- `dagster._vendored.croniter.croniter` exists (vendored) [VERIFIED: `inspect.getfile`].
- croniter latest on PyPI = `6.2.3`, uploaded 2026-07-02, repo `github.com/pallets-eco/croniter` [VERIFIED: PyPI JSON API].

## Package Legitimacy Audit

> Only relevant if the planner chooses to add `croniter` as a direct dependency. The **recommended** path adds no packages.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| croniter | PyPI | latest patch 6.2.3 (2026-07-02); project ~10 yrs | PyPI hides count (`null`) | github.com/pallets-eco/croniter (Pallets ecosystem) | **SUS** (`too-new`, `unknown-downloads`) | **Flagged** — if added, planner must insert a `checkpoint:human-verify` before install. Prefer pinning an older mature minor (e.g. `>=2,<7`) rather than the bleeding-edge patch. |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** `croniter` — but the **recommended design avoids it entirely** by using Dagster's vendored engine via `dagster._utils.schedules`. The `SUS` flag is a false-positive artifact of PyPI not exposing download stats and the recency of the latest patch; the project is long-established and now maintained under `pallets-eco`. [ASSUMED: project maturity — from training knowledge, not a session-verified download metric]

## Cron Due-Check (D-03 / D-04) — verified

**Finding:** `croniter` is NOT importable in this env; Dagster vendors it and exposes helpers. All three below were executed successfully this session:

```python
# Source: dagster._utils.schedules (dagster 1.13.11), verified in-process
from datetime import datetime, timezone
from dagster._utils.schedules import (
    get_next_cron_tick,            # (cron_string, current_time: datetime, timezone: str|None) -> datetime
    get_latest_completed_cron_tick,
    is_valid_cron_string,          # rejects non-5-field / malformed strings
)

now = datetime(2026, 7, 10, 4, 0, 0, tzinfo=timezone.utc)
get_next_cron_tick("0 3 * * *", now, "UTC")            # -> 2026-07-11 03:00:00+00:00  (tz-aware)
get_latest_completed_cron_tick("0 3 * * *", now, "UTC")# -> 2026-07-10 03:00:00+00:00
is_valid_cron_string("0 3 * * *")   # True
is_valid_cron_string("*/5 * * * *") # True
is_valid_cron_string("not a cron")  # False
```

**Due-check (mirrors D-04 exactly, no new dep):**
```python
base = source.last_crawled_at or source.created_at   # both are DateTime(timezone=True) -> tz-aware UTC
next_fire = get_next_cron_tick(source.crawl_schedule, base, "UTC")
is_due = now >= next_fire
```

**Deterministic fire timestamp for the run_key (D-14):**
```python
# the most-recent scheduled fire at/just-before now — deterministic across overlapping ticks & restarts
fire = get_latest_completed_cron_tick(source.crawl_schedule, now, "UTC")
run_key = f"{source.id}:{fire.isoformat()}"
```
When a source is due, `get_latest_completed_cron_tick(now)` equals the `next_fire` that has just passed — the two helpers are internally consistent (same vendored engine). Returned datetimes are **tz-aware UTC**; compare only against tz-aware `now = datetime.now(timezone.utc)` (mixing naive/aware raises `TypeError` — Pitfall 4).

**Schedule validation:** call `is_valid_cron_string(schedule)` in the CLI set-schedule verb and at `domain-init` persistence so a malformed cron is rejected at write time, not silently at sensor-tick time. It enforces exactly 5 fields (rejects seconds-resolution `6`-field strings).

**Confidence:** HIGH [VERIFIED: .venv — functions imported and executed].

## Architecture Patterns

### System Architecture Diagram

```
                          ┌─────────────────────────── dagster-daemon (docker-compose) ───────────────────────────┐
                          │                                                                                        │
  registry (Postgres)     │   recrawl_sensor  (@sensor, minimum_interval_seconds≈60, DefaultSensorStatus.RUNNING)  │
  sources.crawl_schedule ─┼─► list_scheduled_sources()  ─► for each source:                                        │
  sources.last_crawled_at │        base = last_crawled_at or created_at                                            │
  sources.last_content_hash        get_next_cron_tick(schedule, base, "UTC") ── now >= next_fire? ──┐              │
                          │        │                                                    (not due)   └─ skip source │
                          │        │ (due)                                                                         │
                          │        ▼   fire = get_latest_completed_cron_tick(schedule, now,"UTC")                  │
                          │     RunRequest(run_key=f"{sid}:{fire.iso}",                                            │
                          │                run_config={ops:{recrawl_op:{source_id}}},                              │
                          │                tags={"klake/source": sid})   ── Dagster dedups by run_key ──┐          │
                          │     context.update_cursor(now.iso)   (only side-effect in the sensor)       │          │
                          └────────────────────────────────────────────────────────────────────────────┼──────────┘
                                                                                                         ▼
                                            QueuedRunCoordinator (tag_concurrency_limits: klake/source ≤ 1 per value)
                                                                                                         ▼
                                              recrawl_source_job  (@job → @op recrawl_op, reads RecrawlConfig.source_id)
                                                                                                         ▼
                       ┌──────────────────── CHANGE GATE (pipeline, BEFORE any put_raw) ───────────────────────────┐
   seed/canonical URL  │  validate_public_url(url)  ─► adapter.fetch_page(url).markdown                            │
                       │  sig = sha256(remove_boilerplate(markdown).encode()).hexdigest()   # SAME as clean()      │
                       │  stale = (now - last_crawled_at) > max_staleness_days                                     │
                       │  if sig == last_content_hash and not stale and last_content_hash is not None:             │
                       │        touch_source_crawl(last_crawled_at=now)          ── SKIP: no put_raw, no LLM ──►    │
                       │  else:                                                                                    │
                       │        crawl_source(url)  ──► put_raw/put_bronze ──► (async assets pick up ingest chain)  │
                       │        touch_source_crawl(last_crawled_at=now, last_content_hash=sig)                     │
                       └───────────────────────────────────────────────────────────────────────────────────────────┘
```
File-to-implementation mapping is in Component Responsibilities below, not in the diagram.

### Recommended Project Structure
```
src/knowledge_lake/
├── dagster_defs/
│   ├── sensors.py          # NEW: recrawl_sensor (@sensor) + recrawl_source_job (@job/@op) + RecrawlConfig(Config)
│   └── definitions.py      # EDIT: register sensors=[recrawl_sensor], jobs+=[recrawl_source_job]
├── pipeline/
│   └── crawl.py            # EDIT: add recrawl_source() (thin gate wrapper) OR recrawl=True branch in crawl_source()
├── registry/
│   ├── models.py           # EDIT: 3 new Mapped[...] columns on Source
│   ├── repo.py             # EDIT: touch_source_crawl(), list_scheduled_sources()
│   └── alembic/versions/
│       └── 0009_crawl_scheduling.py   # NEW: additive columns, down_revision="0008"
├── domains/models.py       # EDIT: SourceEntry.crawl_schedule: Optional[str] = None
├── cli/app.py              # EDIT: cmd_init persists crawl_schedule; NEW set-schedule verb
└── config/settings.py      # EDIT: CrawlSettings.max_staleness_days: int = 30
infra/dagster/dagster.yaml  # EDIT: DefaultRunCoordinator -> QueuedRunCoordinator + tag_concurrency_limits (D-16)
```

### Pattern 1: Op-based job reading `source_id` from run config (verified)
```python
# Source: dagster 1.13.11 — executed in-process this session (job.success == True)
import dagster as dg

class RecrawlConfig(dg.Config):          # Pydantic-backed, mirrors assets.py:IngestConfig
    source_id: str

@dg.op(retry_policy=dg.RetryPolicy(max_retries=2, delay=1, backoff=dg.Backoff.EXPONENTIAL))
def recrawl_op(context: dg.OpExecutionContext, config: RecrawlConfig) -> dict:
    # D-13: reuse the existing crawl vertical wholesale, behind the change gate (D-07)
    from knowledge_lake.pipeline.crawl import recrawl_source   # new thin wrapper
    import asyncio
    result = asyncio.run(recrawl_source(config.source_id))     # gate → skip-or-crawl → touch_source_crawl
    context.log.info("recrawl.op.done", extra=result)          # D-17: DB writes happen INSIDE recrawl_source
    return result

@dg.job(tags={"klake/kind": "recrawl"})
def recrawl_source_job():
    recrawl_op()
```
RunConfig plumbing (both forms verified): `dg.RunConfig(ops={"recrawl_op": RecrawlConfig(source_id=sid)})` **or** the dict form `{"ops": {"recrawl_op": {"config": {"source_id": sid}}}}`.

### Pattern 2: The sensor (verified end-to-end)
```python
# Source: dagster 1.13.11 — build_sensor_context + emission + cursor verified this session
import dagster as dg
from datetime import datetime, timezone
from dagster._utils.schedules import get_next_cron_tick, get_latest_completed_cron_tick

@dg.sensor(job=recrawl_source_job, minimum_interval_seconds=60,
           default_status=dg.DefaultSensorStatus.RUNNING)   # so it runs without manual UI toggle
def recrawl_sensor(context: dg.SensorEvaluationContext):
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry import repo
    now = datetime.now(timezone.utc)
    with get_session() as session:
        scheduled = repo.list_scheduled_sources(session)   # returns MATERIALIZED rows (Pattern 3)
    requests = []
    for src in scheduled:                                  # side-effect-free loop
        base = src.last_crawled_at or src.created_at
        if now >= get_next_cron_tick(src.crawl_schedule, base, "UTC"):
            fire = get_latest_completed_cron_tick(src.crawl_schedule, now, "UTC")
            requests.append(dg.RunRequest(
                run_key=f"{src.id}:{fire.isoformat()}",                     # D-14 deterministic
                run_config=dg.RunConfig(ops={"recrawl_op": RecrawlConfig(source_id=src.id)}),
                tags={"klake/source": src.id},                             # D-16 concurrency key
            ))
    context.update_cursor(now.isoformat())                 # D-15 watermark (only side-effect)
    return dg.SensorResult(run_requests=requests) if requests else dg.SkipReason("no sources due")
```

### Pattern 3: DetachedInstanceError-safe materialization (repo helper)
```python
# Source: mirrors pipeline/crawl.py:57 list_sources_for_crawl_all wrapper pattern
from collections import namedtuple
from sqlalchemy import select

_ScheduledSource = namedtuple(
    "_ScheduledSource", ["id", "url", "crawl_schedule", "last_crawled_at", "last_content_hash", "created_at", "config"]
)

def list_scheduled_sources(session) -> list:
    """Sources with a non-NULL crawl_schedule, materialized to survive session close (D-02)."""
    rows = session.execute(
        select(Source).where(Source.crawl_schedule.is_not(None))
    ).scalars()
    return [_ScheduledSource(
        id=s.id, url=s.url, crawl_schedule=s.crawl_schedule,
        last_crawled_at=s.last_crawled_at, last_content_hash=s.last_content_hash,
        created_at=s.created_at, config=(s.config or {}),
    ) for s in rows]
```

### Anti-Patterns to Avoid
- **DB writes in the sensor.** The sensor must be idempotent and cheap; a slow/failing write blocks the tick and can partially apply on re-evaluation. Writes belong in the op (D-17).
- **`run_key = now`.** Non-deterministic run keys defeat Dagster dedup → duplicate runs / tick storms. Use the cron fire timestamp (D-14).
- **Hashing raw bytes.** REQUIREMENTS Out-of-Scope explicitly bans raw-bytes change detection. Hash `remove_boilerplate(markdown)` only (D-06).
- **A second normalizer.** Reuse `remove_boilerplate()` directly; a divergent normalizer makes "changed" mean different things at the gate vs the silver zone.
- **`put_raw` before the gate.** The probe must precede any raw/bronze write, or WORM thrash returns (D-07/D-08).
- **Tag concurrency under `DefaultRunCoordinator`.** No-op; needs `QueuedRunCoordinator` (Pitfall 5).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cron parsing / next-tick | A regex cron parser | `dagster._utils.schedules.get_next_cron_tick` (or `croniter`) | DST, ranges, `*/n`, month/day edge cases; Dagster's engine is battle-tested and matches daemon ticks. |
| Text normalization for the signature | New whitespace/boilerplate stripper | `remove_boilerplate()` (`clean.py:82`) | Must equal silver-zone "changed"; already tuned (T-03-07). |
| Change signature | Custom fingerprint | `hashlib.sha256(text.encode("utf-8")).hexdigest()` | Exactly what `clean()` does (`clean.py:233`); 64-char hex fits `String(64)`. |
| Run dedup / idempotency | A "have I run this?" table | Dagster `RunRequest.run_key` | Dagster dedups by run_key in run storage — verified. |
| Per-source serialization | A DB lock / advisory lock | `QueuedRunCoordinator` `tag_concurrency_limits` + `_find_or_create_job` | Coordinator enforces `applyLimitPerUniqueValue`; crawl already reuses an in-flight job. |
| The whole crawl | A recrawl-specific crawler | `crawl_source()` (`crawl.py:90`) | Full vertical: SSRF, robots, rate-limit, two-artifact write, resume (D-13). |
| SSRF check on the probe | A new allow-list | `validate_public_url()` (`ingest.py:99`) | Same guard the crawl already trusts. |

**Key insight:** every "hard" primitive this phase needs already ships — in Dagster (cron + run dedup) or in the codebase (normalizer, hash, crawl, SSRF). Net-new code is glue, three columns, and one sensor.

## Runtime State Inventory

> This is an **additive schema change on live data**, so a state inventory applies.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `sources` table (Postgres registry) gains 3 nullable columns. Existing rows get NULL → all sources are "unscheduled" until an operator sets a schedule (D-02). No backfill. | Code edit (migration + ORM). No data migration. |
| Live service config | `infra/dagster/dagster.yaml` uses `DefaultRunCoordinator` — per-source concurrency (D-16) is inert under it. This file is mounted read-only into both dagster-webserver and dagster-daemon (`docker-compose.yml:165,191`). | Config edit: switch to `QueuedRunCoordinator` + `tag_concurrency_limits`; daemon restart to pick it up. |
| OS-registered state | The Dagster **daemon** must be running for a sensor to fire (compose service `dagster-daemon`, `command: dagster-daemon run`). Sensor default status is `STOPPED` unless `default_status=RUNNING` is set or it is toggled in the UI. | Set `default_status=DefaultSensorStatus.RUNNING`; ensure daemon is up. |
| Secrets / env vars | New `KLAKE_CRAWL__MAX_STALENESS_DAYS` (optional; defaults to 30 in code). No secret. Dagster resources already read `KLAKE_*` EnvVars. | None required (has a default). |
| Build artifacts / installed packages | No new installed package if the Dagster vendored cron helper is used. `sources.yaml` schedules only affect **newly** `domain-init`-ed sources unless a re-init/CLI verb is run. | None (recommended path). If `croniter` added: `uv lock` + rebuild image. |

**Nothing found for:** compiled binaries, egg-info, Redis/Chroma keys, Task Scheduler — none apply here.

## Common Pitfalls

### Pitfall 1: `croniter` assumed importable (it is not)
**What goes wrong:** Code does `import croniter` (per D-04's assumption) and fails at runtime with `ModuleNotFoundError` inside the daemon.
**Why:** Dagster vendors croniter privately (`dagster._vendored.croniter`); it is not on the import path, and it is not a declared project dependency.
**How to avoid:** Use `from dagster._utils.schedules import get_next_cron_tick, get_latest_completed_cron_tick, is_valid_cron_string` (no new dep), **or** add `croniter` as an explicit dep (behind a human-verify checkpoint — flagged `SUS`).
**Warning signs:** A green unit test that mocks cron but a red daemon at first tick.

### Pitfall 2: Per-source concurrency silently inert
**What goes wrong:** `tags={"klake/source": sid}` is set but two crawls for the same source still overlap.
**Why:** `dagster.yaml` uses `DefaultRunCoordinator`; `tag_concurrency_limits` only exist under `QueuedRunCoordinator`.
**How to avoid:** Switch the coordinator (see Code Examples). Note the deterministic `run_key` + `_find_or_create_job` (which reuses a `running`/`pending` job for the same `source_id`+crawler via a partial unique index, `crawl.py:228`) already bound the damage — but D-16 wants a real limit.
**Warning signs:** Overlapping runs in the Dagster UI for one `klake/source` tag value.

### Pitfall 3: Gate placed after `put_raw`
**What goes wrong:** Unchanged dynamic pages still write a new immutable raw object every tick — the exact WORM/spend thrash SCHED-02 forbids.
**Why:** The probe/compare must occur before any storage write; `crawl_source()` writes raw+bronze inside `_crawl_loop` (`crawl.py:440`).
**How to avoid:** Do the seed probe (`fetch_page(url).markdown` → normalize → hash → compare) in the wrapper **before** calling `crawl_source()`. Only on a change (or NULL hash, or staleness) call the full path.
**Warning signs:** New `raw_document` artifacts appearing for sources whose content did not change.

### Pitfall 4: Naive/aware datetime mix
**What goes wrong:** `TypeError: can't compare offset-naive and offset-aware datetimes` in the due-check or staleness math.
**Why:** `Source.last_crawled_at`/`created_at` are `DateTime(timezone=True)` (tz-aware); the cron helpers return tz-aware UTC. A `datetime.utcnow()` (naive) mixed in breaks it.
**How to avoid:** Always `datetime.now(timezone.utc)`. Staleness: `(now - last_crawled_at) > timedelta(days=max_staleness_days)`.
**Warning signs:** Sensor tick errors in the daemon log; the sensor shows an evaluation failure in the UI.

### Pitfall 5: Cursor / daemon-restart replay
**What goes wrong:** After a daemon restart the sensor re-emits historical fires or, conversely, skips a due fire.
**Why:** Misusing the cursor as the source of truth. The **deterministic `run_key` is the real idempotency guarantee**; the cursor is an optimization/watermark (D-15).
**How to avoid:** Keep the cursor as "last evaluation ISO time" and rely on `run_key = f"{sid}:{fire_iso}"` for dedup (Dagster will not launch a second run for a run_key already in run storage). Do not gate emission on the cursor in a way that can permanently skip a fire.
**Warning signs:** Duplicate crawls right after a `dagster-daemon` restart, or a source that never fires again after a restart.

### Pitfall 6: `SkipReason` vs empty yield
**What goes wrong:** Returning nothing when no source is due looks like an error / no-op in the UI.
**How to avoid:** Return `dg.SkipReason("no sources due")` (or a `SensorResult` with an empty list) so the tick is recorded cleanly. Verified that both `yield`ing RunRequests and returning `SensorResult(run_requests=[...])` work.

## Code Examples

### Alembic `0009` — additive columns (mirrors 0008 exactly)
```python
# Source: registry/alembic/versions/0009_crawl_scheduling.py — style from 0008_dataset_examples.py
from __future__ import annotations
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("sources", sa.Column("crawl_schedule", sa.String(255), nullable=True))
    op.add_column("sources", sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("last_content_hash", sa.String(64), nullable=True))

def downgrade() -> None:
    op.drop_column("sources", "last_content_hash")
    op.drop_column("sources", "last_crawled_at")
    op.drop_column("sources", "crawl_schedule")
```
Symmetry: upgrade adds three, downgrade drops in reverse order. No backfill, no NOT NULL, no server default — matches D-01.

### `Source` ORM additions (`registry/models.py`, after `config` / before `created_at`)
```python
crawl_schedule: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
"""5-field UTC cron string (SCHED-01, D-03). NULL ⇒ source is not auto-recrawled (D-02)."""

last_crawled_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
"""UTC timestamp of the last re-crawl ATTEMPT (updated on skip and crawl alike, D-11)."""

last_content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
"""SHA256 over normalized silver-stage seed-page text (D-06). NULL ⇒ always crawl (D-07)."""
```

### Change gate — reusing the silver normalizer (thin wrapper form)
```python
# Source: pipeline/crawl.py — new recrawl_source(); reuses remove_boilerplate + sha256 like clean.py:233
import asyncio, hashlib
from datetime import datetime, timezone, timedelta
from knowledge_lake.pipeline.clean import remove_boilerplate      # D-06 exact normalizer
from knowledge_lake.pipeline.ingest import validate_public_url
from knowledge_lake.plugins.resolver import get_crawler
from knowledge_lake.registry.db import get_session
from knowledge_lake.registry import repo

def _signature(markdown: str) -> str:
    return hashlib.sha256(remove_boilerplate(markdown).encode("utf-8")).hexdigest()

async def recrawl_source(source_id: str, *, settings=None) -> dict:
    s = settings or get_settings()
    now = datetime.now(timezone.utc)
    with get_session() as session:
        src = repo.get_source(session, source_id)
        url, last_hash, last_at = src.url, src.last_content_hash, src.last_crawled_at
        cc = repo.get_source_crawl_config(session, source_id)
    max_days = cc.get("max_staleness_days", s.crawl.max_staleness_days)   # D-10 per-source override
    stale = last_at is not None and (now - last_at) > timedelta(days=max_days)

    validate_public_url(url)                                    # D-07 SSRF before any HTTP
    adapter = get_crawler(type("_S", (), {"crawler": s.crawler})())
    probe = await adapter.fetch_page(url)                       # one GET, no put_raw
    sig = _signature(probe.markdown or "")

    if last_hash is not None and sig == last_hash and not stale:
        repo.touch_source_crawl(source_id, last_crawled_at=now)          # D-07 skip: bump timestamp only
        return {"source_id": source_id, "status": "skipped_unchanged"}

    result = await crawl_source(url, settings=s)                          # full path (D-13)
    repo.touch_source_crawl(source_id, last_crawled_at=now, last_content_hash=sig)  # D-17
    return {"source_id": source_id, "status": "recrawled", **result}
```

### `touch_source_crawl` repo helper (`registry/repo.py`, next to `get_domain_for_source`)
```python
def touch_source_crawl(source_id: str, *, last_crawled_at, last_content_hash: Optional[str] = None) -> None:
    """Update crawl watermarks after a re-crawl attempt (D-11/D-17). Its own session so the
    Dagster op can call it without holding one. last_content_hash omitted ⇒ leave unchanged (skip path)."""
    with get_session() as session:
        src = session.get(Source, source_id)
        if src is None:
            return
        src.last_crawled_at = last_crawled_at
        if last_content_hash is not None:
            src.last_content_hash = last_content_hash
```

### `dagster.yaml` — per-source concurrency (D-16)
```yaml
# infra/dagster/dagster.yaml — REPLACE the DefaultRunCoordinator block
run_coordinator:
  module: dagster.core.run_coordinator
  class: QueuedRunCoordinator
  config:
    tag_concurrency_limits:
      - key: "klake/source"
        value:
          applyLimitPerUniqueValue: true
        limit: 1
```

### Settings (`config/settings.py`, in `CrawlSettings`)
```python
max_staleness_days: int = 30
"""Force a full re-ingest when now - last_crawled_at exceeds this, even if the signature
is unchanged (SCHED-02, D-10). Env: KLAKE_CRAWL__MAX_STALENESS_DAYS. Per-source override
lives at Source.config['crawl_config']['max_staleness_days']."""
```
(The nested env prefix `KLAKE_CRAWL__` is already wired via `crawl: CrawlSettings` at `settings.py:401`; no new plumbing.)

### Schedule persistence (`domains/models.py` + `cli/app.py:1104`)
```python
# domains/models.py — SourceEntry gains:
crawl_schedule: Optional[str] = None   # optional 5-field cron in sources.yaml (D-05a)

# cli/app.py cmd_init create_source(...) — add to the config dict is WRONG (schedule is a column):
registry_repo.create_source(
    session, name=entry.name, source_type=entry.source_type, url=entry.url,
    normalized_url=norm_url, license_type=entry.license,
    crawl_schedule=entry.crawl_schedule,        # NEW column kwarg (validate with is_valid_cron_string)
    config={"domain": domain, "tags": entry.tags, "crawl_config": entry.crawl_config,
            "ingest_type": entry.ingest_type},
)
```
Note: `create_source()` in `repo.py` must accept a `crawl_schedule` kwarg — check its signature and extend it. The CLI set/clear verb (D-05b) validates the cron via `is_valid_cron_string` then updates the column (a sibling of `touch_source_crawl`).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `croniter` as an ordinary dep | Dagster vendors it; use `dagster._utils.schedules` helpers | Dagster ≥ ~1.5 vendored cron | No new dep; matches daemon tick semantics. |
| `@sensor` returns bare `RunRequest`/`SkipReason` | `SensorResult(run_requests=..., cursor=...)` also supported | Dagster ≥ 1.4 | Either works on 1.13.11 (both verified); `SensorResult` is cleaner for cursor+requests together. |
| Op concurrency via `tag:` in job config | Global concurrency **pools** (`@op(pool=...)`) | Dagster ≥ 1.10 | Pools give a single global limit; per-`source_id` still needs `QueuedRunCoordinator` `applyLimitPerUniqueValue`. |

**Deprecated/outdated:** none blocking. `Config`-class run config (`assets.py:IngestConfig`) is the current idiomatic form and is what this phase should follow (not raw `config_schema` dicts).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | croniter's `SUS` legitimacy verdict is a false-positive (long-established project under `pallets-eco`; PyPI hides download counts). | Package Legitimacy Audit | Low — recommended design avoids adding croniter; if added, a human-verify checkpoint catches any real issue. |
| A2 | `create_source()` in `repo.py` can be extended with a `crawl_schedule` kwarg (signature not read this session). | Code Examples (persistence) | Low — planner verifies the signature; if it already takes `**kwargs`/a config, adjust the call site. |
| A3 | The seed/canonical URL for the change probe is `Source.url` (the registered seed). | Change gate | Low — matches how `crawl_source` seeds; per-page (depth>0) is explicitly deferred (D-09). |
| A4 | `adapter.fetch_page(url).markdown` is populated for the seed on a normal 200 (crawl4ai produces markdown). | Change gate | Medium — if a source returns near-empty markdown, the signature could be unstable; the max-staleness floor (D-10) backstops false "unchanged". Planner may fall back to a direct GET per the D-07 discretion note. |

## Open Questions (RESOLVED)

1. **Sensor cursor semantics beyond the watermark.**
   - What we know: deterministic `run_key` is the real idempotency guarantee (D-14); cursor is a watermark (D-15).
   - What's unclear: whether the cursor should also carry per-source last-fire state to shrink the scan, or stay a single global ISO timestamp.
   - **RESOLVED:** keep it a single global ISO timestamp for v2.0 (simplest, correct given run_key dedup); revisit only if source counts grow large. → reflected in plan 11-05.

2. **Probe fetch: adapter vs direct GET (D-07 discretion).**
   - What we know: both must pass `validate_public_url`; the adapter yields markdown directly.
   - What's unclear: whether a lighter `httpx` GET + a markdown conversion would drift from crawl4ai's markdown (making signatures incomparable to what a full crawl would store).
   - **RESOLVED:** **reuse the configured crawler adapter** for the probe so the probe markdown and the crawl markdown come from the same producer — avoids signature drift. → reflected in plan 11-03.

3. **Does `create_source()` accept `crawl_schedule` today?** **RESOLVED:** signature verified at plan time; schedule persistence handled in plan 11-02 Task 2 (A2).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| dagster | Sensor, op/job, cron helpers | ✓ | 1.13.11 | — |
| dagster-daemon (compose) | Sensor must fire | ✓ (service defined) | 1.13.11 | Must be running; sensor `default_status=RUNNING`. |
| croniter (standalone) | Cron (only if not using Dagster helper) | ✗ | — | Use `dagster._utils.schedules` (recommended) |
| Postgres (registry) | New columns / repo helpers | ✓ | 16 (compose) | — |
| crawl4ai adapter | Seed-page probe markdown | ✓ | 0.9.0 | Direct SSRF-checked GET (D-07 discretion) |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** standalone `croniter` — fully covered by the Dagster vendored engine.

## Validation Architecture

> nyquist_validation = true (config.json) — section required.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (+ pytest-asyncio, `asyncio_mode = "auto"` in `pyproject.toml`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]`, `testpaths = ["tests"]` |
| Layout | `tests/unit/`, `tests/integration/`, `tests/e2e/` |
| Quick run command | `./.venv/bin/pytest tests/unit/test_recrawl_gate.py tests/unit/test_recrawl_sensor.py -x -q` |
| Full suite command | `./.venv/bin/pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SCHED-01 | Sensor emits exactly one `RunRequest` per due source with deterministic `run_key` | unit | `pytest tests/unit/test_recrawl_sensor.py::test_emits_deterministic_run_key -x` | ❌ Wave 0 |
| SCHED-01 | Not-due source emits `SkipReason`, no RunRequest | unit | `pytest tests/unit/test_recrawl_sensor.py::test_skips_not_due -x` | ❌ Wave 0 |
| SCHED-01 | Same fire window ⇒ identical run_key (idempotent across re-eval) | unit | `pytest tests/unit/test_recrawl_sensor.py::test_run_key_stable_within_window -x` | ❌ Wave 0 |
| SCHED-01 | `is_valid_cron_string` rejects malformed schedule at set time | unit | `pytest tests/unit/test_set_schedule_cli.py::test_rejects_bad_cron -x` | ❌ Wave 0 |
| SCHED-02 | Unchanged normalized signature + within staleness ⇒ skip, no `put_raw`, `last_crawled_at` bumped | unit | `pytest tests/unit/test_recrawl_gate.py::test_unchanged_skips_no_raw -x` | ❌ Wave 0 |
| SCHED-02 | Changed signature ⇒ full `crawl_source` path + hash updated | unit | `pytest tests/unit/test_recrawl_gate.py::test_changed_recrawls -x` | ❌ Wave 0 |
| SCHED-02 | Signature reuses `remove_boilerplate` (dynamic nonce/timestamp does NOT flip hash) | unit | `pytest tests/unit/test_recrawl_gate.py::test_nonce_noise_unchanged -x` | ❌ Wave 0 |
| SCHED-02 | `last_content_hash IS NULL` ⇒ always crawls | unit | `pytest tests/unit/test_recrawl_gate.py::test_null_hash_forces_crawl -x` | ❌ Wave 0 |
| SCHED-02 | Staleness exceeded ⇒ re-ingest even when hash matches | unit | `pytest tests/unit/test_recrawl_gate.py::test_staleness_forces_refresh -x` | ❌ Wave 0 |
| Criterion 1 | `0009` upgrade adds 3 nullable columns; downgrade drops them; head chains 0008→0009 | integration | `pytest tests/integration/test_migrations.py -x` (extend existing) | ⚠️ extend |

### Sampling Rate
- **Per task commit:** the quick run command above.
- **Per wave merge:** `./.venv/bin/pytest tests/unit -q`.
- **Phase gate:** full suite green before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/unit/test_recrawl_gate.py` — SCHED-02 gate (skip/crawl/null/staleness/nonce). Use a fake adapter returning controlled markdown; patch `StorageBackend`/`put_raw` to assert it is NOT called on skip.
- [ ] `tests/unit/test_recrawl_sensor.py` — SCHED-01 via `dg.build_sensor_context(cursor=...)`; assert run_key, tags, cursor advance, SkipReason.
- [ ] `tests/unit/test_set_schedule_cli.py` — CLI set/clear + `is_valid_cron_string` rejection.
- [ ] Extend `tests/integration/test_migrations.py` and/or `tests/integration/test_crawl_schema.py` for the `0009` columns + head chain.
- [ ] Fixtures: reuse `tests/conftest.py` in-memory SQLite pattern; a `DummySource` namedtuple for the materialized-row helper.

## Security Domain

> security_enforcement = true (config.json) — section required.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Internal daemon/sensor; no new auth surface. |
| V3 Session Management | no | — |
| V4 Access Control | no | No new external endpoint (REST exposure is optional/deferred). |
| V5 Input Validation | **yes** | `crawl_schedule` validated with `is_valid_cron_string` before persist (CLI + `domain-init`); `source_id` in run config is a registry PK, not user free-text. |
| V6 Cryptography | n/a (integrity, not secrecy) | SHA256 via `hashlib` — a content fingerprint, not a security control; never hand-rolled. |
| V10/V12 SSRF & Outbound | **yes** | The seed probe MUST call `validate_public_url()` before any HTTP (D-07); `crawl_source` re-validates every URL (`crawl.py:129,360`). |

### Known Threat Patterns for {Dagster sensor + outbound crawl}
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SSRF via a source URL pointed at an internal address | Information Disclosure | `validate_public_url()` on the probe AND inside `crawl_source` (defense in depth). |
| Malformed/hostile cron string (ReDoS / seconds-resolution abuse) | Denial of Service | `is_valid_cron_string` (rejects non-5-field); vendored croniter engine, not a custom regex. |
| Tick storm / duplicate-run flood | Denial of Service | Deterministic `run_key` dedup + `minimum_interval_seconds` + `QueuedRunCoordinator` per-source limit. |
| Unbounded re-ingest thrash on dynamic HTML | Denial of Service / cost | Normalized change gate (D-06/D-07) + max-staleness cap (D-10). |
| Sensor doing partial DB writes on re-eval | Tampering / integrity | Sensor side-effect-free; writes only in the op via `touch_source_crawl` (D-17). |

## Sources

### Primary (HIGH confidence — verified this session)
- `.venv` dagster 1.13.11: `@sensor`/`RunRequest`/`RunConfig`/`build_sensor_context`/`validate_run_config`/`execute_in_process` — full sensor→op→job wiring executed successfully.
- `dagster._utils.schedules`: `get_next_cron_tick`, `get_latest_completed_cron_tick`, `is_valid_cron_string`, `cron_string_iterator` — imported and executed.
- `dagster._vendored.croniter.croniter` — confirmed vendored (via `inspect.getfile`); `import croniter` raises `ModuleNotFoundError`.
- Repo source read directly: `pipeline/clean.py` (normalizer + sha256), `pipeline/crawl.py` (crawl_source, put_raw seam, SSRF), `registry/models.py` (Source), `registry/repo.py` (helpers), `registry/alembic/versions/0008_*.py` (head), `dagster_defs/definitions.py` + `assets.py` (Config/job patterns), `infra/dagster/dagster.yaml` (run coordinator), `config/settings.py` (CrawlSettings), `cli/app.py` (cmd_init), `domains/models.py` (SourceEntry), `plugins/protocols.py` (CrawlPageResult).

### Secondary (MEDIUM confidence)
- PyPI JSON API for `croniter` latest version/date and repo URL.
- `gsd-tools query package-legitimacy check --ecosystem pypi croniter` → `SUS` (too-new, unknown-downloads).

### Tertiary (LOW confidence)
- croniter project maturity/reputation (`pallets-eco`) — training knowledge, not a session-verified metric (see A1).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every library verified installed at its pinned version.
- Cron approach: HIGH — helpers executed; the "croniter not importable" correction is directly verified.
- Sensor/op/job mechanics: HIGH — end-to-end wiring executed in-process (job.success == True, run_key/cursor confirmed).
- Change gate: HIGH — normalizer + sha256 pattern read from source; seam location confirmed.
- Concurrency (D-16): MEDIUM-HIGH — `DefaultRunCoordinator` limitation is verified from `dagster.yaml`; the `QueuedRunCoordinator` config is the documented standard but not executed against a live daemon this session.
- Migration `0009`: HIGH — mirrors the verified `0008` head and additive convention.

**Research date:** 2026-07-10
**Valid until:** 2026-08-09 (stable — all deps exact-pinned; re-verify only if `dagster` is bumped off 1.13.11, which would affect the `dagster._utils.schedules` import path).
