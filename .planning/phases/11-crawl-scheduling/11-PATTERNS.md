# Phase 11: Crawl Scheduling - Pattern Map

**Mapped:** 2026-07-10
**Files analyzed:** 10 (2 new, 8 modified)
**Analogs found:** 10 / 10

> Every "hard" primitive already ships. This phase is glue: 3 nullable columns, one change gate, one first-ever Dagster `@sensor` + op-based job. Prefer the RESEARCH.md § "Code Examples" verified snippets — they were executed in-process against dagster 1.13.11. This file points the planner/executor at the exact reference implementations.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `registry/alembic/versions/0009_crawl_scheduling.py` (NEW) | migration | batch/DDL | `registry/alembic/versions/0008_dataset_examples.py` | exact |
| `registry/models.py` (MODIFY `Source`) | model | — | existing `Source` columns (`normalized_url`, `robots_checked`, `config`) | exact |
| `registry/repo.py` (MODIFY: `touch_source_crawl`, `list_scheduled_sources`) | repository | CRUD | `get_domain_for_source` (:822), `get_source_crawl_config` (:843), `create_source` (:55) | exact |
| `pipeline/crawl.py` (MODIFY: `recrawl_source` gate) | service | request-response / transform | `crawl_source` (:90), `list_sources_for_crawl_all` (:57), `clean()` hash (`clean.py:229-233`) | role+flow match |
| `dagster_defs/sensors.py` (NEW: `recrawl_sensor` + `recrawl_source_job` + `RecrawlConfig`) | sensor/job | event-driven | `assets.py` `IngestConfig` (:71), `_PIPELINE_RETRY` (:60), `healthcare_e2e_job` (:868) | role-match (first sensor) |
| `dagster_defs/definitions.py` (MODIFY: register sensor+job) | config | — | `Definitions(...)` (:67) | exact |
| `config/settings.py` (MODIFY: `CrawlSettings.max_staleness_days`) | config | — | `CrawlSettings` (:53) | exact |
| `cli/app.py` (MODIFY: persist schedule + set/clear verb) | CLI | request-response | `cmd_init` `create_source` call (:1104) | exact |
| `domains/models.py` (MODIFY: `SourceEntry.crawl_schedule`) | model | — | `SourceEntry` (:17), `crawl_config` field (:40) | exact |
| `infra/dagster/dagster.yaml` (MODIFY: `QueuedRunCoordinator`) | config | — | existing `DefaultRunCoordinator` block | role-match |

## Pattern Assignments

### `registry/alembic/versions/0009_crawl_scheduling.py` (NEW, migration)

**Analog:** `registry/alembic/versions/0008_dataset_examples.py` (read in full)

**Header + revision identifiers** (0008 lines 22-33) — copy verbatim, change ids:
```python
from __future__ import annotations
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
```

**Additive-column op style** (0008 lines 38-41) — the exact `op.add_column(...)` shape to mirror:
```python
op.add_column("datasets", sa.Column("dataset_type", sa.String(64), nullable=True))
```

**0009 body** (per RESEARCH § "Alembic 0009", D-01) — three nullable columns, downgrade drops in reverse (mirrors 0008 lines 83-94):
```python
def upgrade() -> None:
    op.add_column("sources", sa.Column("crawl_schedule", sa.String(255), nullable=True))
    op.add_column("sources", sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("last_content_hash", sa.String(64), nullable=True))

def downgrade() -> None:
    op.drop_column("sources", "last_content_hash")
    op.drop_column("sources", "last_crawled_at")
    op.drop_column("sources", "crawl_schedule")
```
No backfill, no NOT NULL, no server default — 0008 uses `server_default=sa.text("NOW()")` only on a NOT NULL `created_at`; the 0009 columns must NOT copy that (they are nullable, D-01).

---

### `registry/models.py` — `Source` (MODIFY, model)

**Analog:** existing `Source` columns, `models.py:58-101` (read in full). Place new columns after `config` (:93), before `created_at` (:96).

**Existing column style to mirror** (:79-82, `normalized_url`):
```python
normalized_url: Mapped[Optional[str]] = mapped_column(
    Text, nullable=True, index=True
)
"""D-06 normalized URL for URL-first dedup (...)."""
```

**New columns** (per RESEARCH § "Source ORM additions", D-01/D-02/D-06/D-11). Note `Optional`, `Mapped`, `mapped_column`, `String`, `DateTime` are already imported (:26-44); `datetime` module already imported (:25):
```python
crawl_schedule: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
"""5-field UTC cron string (SCHED-01, D-03). NULL ⇒ source is not auto-recrawled (D-02)."""

last_crawled_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
"""UTC timestamp of the last re-crawl ATTEMPT (updated on skip and crawl alike, D-11)."""

last_content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
"""SHA256 over normalized silver-stage seed-page text (D-06). NULL ⇒ always crawl (D-07)."""
```

---

### `registry/repo.py` — `touch_source_crawl` + `list_scheduled_sources` (MODIFY, CRUD)

**Analogs:** `get_domain_for_source` (:822-832), `get_source` (:835-840), `get_source_crawl_config` (:843-869), `create_source` (:55-66).

**None-guard + `session.get(Source, ...)` pattern** (`get_source_crawl_config` :866-869) — the template both new helpers follow:
```python
source = session.get(Source, source_id)
if source is None or not source.config:
    return {}
return source.config.get("crawl_config", {})
```

**`touch_source_crawl` (own-session variant, D-11/D-17)** — RESEARCH § "touch_source_crawl". Unlike the analogs (which take a `session` param), the op calls this without holding a session, so it opens its own via `get_session()`:
```python
def touch_source_crawl(source_id: str, *, last_crawled_at, last_content_hash: Optional[str] = None) -> None:
    """Update crawl watermarks after a re-crawl attempt (D-11/D-17). Own session so the
    Dagster op can call it without holding one. last_content_hash omitted ⇒ leave unchanged (skip path)."""
    with get_session() as session:
        src = session.get(Source, source_id)
        if src is None:
            return
        src.last_crawled_at = last_crawled_at
        if last_content_hash is not None:
            src.last_content_hash = last_content_hash
```
Confirm `get_session` is importable in `repo.py` (other helpers take an injected `session`; verify the module-level import or add one — see A2/session-handling note).

**`list_scheduled_sources` (materialized rows, avoid `DetachedInstanceError`)** — mirror `crawl.py:57` `list_sources_for_crawl_all` namedtuple materialization (lines 81-87). RESEARCH § "Pattern 3":
```python
_ScheduledSource = namedtuple(
    "_ScheduledSource",
    ["id", "url", "crawl_schedule", "last_crawled_at", "last_content_hash", "created_at", "config"],
)

def list_scheduled_sources(session) -> list:
    rows = session.execute(
        select(Source).where(Source.crawl_schedule.is_not(None))
    ).scalars()
    return [_ScheduledSource(
        id=s.id, url=s.url, crawl_schedule=s.crawl_schedule,
        last_crawled_at=s.last_crawled_at, last_content_hash=s.last_content_hash,
        created_at=s.created_at, config=(s.config or {}),
    ) for s in rows]
```

**`create_source` signature extension** — `create_source` (:55-66) currently takes `name, source_type, url, normalized_url, license_type, license_url, robots_checked, config`. Add a `crawl_schedule: Optional[str] = None` kwarg and set it on the `Source(...)` construction (D-05a, A2/A3). A sibling `set_source_schedule(session, source_id, schedule)` helper for the CLI clear/set verb (validate with `is_valid_cron_string` at the call site).

---

### `pipeline/crawl.py` — `recrawl_source` change gate (MODIFY, transform → request-response)

**Analogs:** `crawl_source` (:90, wrapped wholesale — do NOT re-implement), `clean.py:229-233` (the exact normalize+sha256 shape), `clean.py:82` `remove_boilerplate`.

**The signature shape to mirror** (`clean.py:229-233`, step 3+4) — normalize THEN sha256 of utf-8 bytes:
```python
cleaned_text = remove_boilerplate(parsed_text)
cleaned_bytes = cleaned_text.encode("utf-8")
content_hash = hashlib.sha256(cleaned_bytes).hexdigest()
```

**`recrawl_source` gate** — RESEARCH § "Change gate" (verified snippet). Key ordering: `validate_public_url` → probe fetch (no `put_raw`) → normalize → sha256 → compare/staleness → skip-or-`crawl_source`:
```python
def _signature(markdown: str) -> str:
    return hashlib.sha256(remove_boilerplate(markdown).encode("utf-8")).hexdigest()

async def recrawl_source(source_id: str, *, settings=None) -> dict:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        src = repo.get_source(session, source_id)
        url, last_hash, last_at = src.url, src.last_content_hash, src.last_crawled_at
        cc = repo.get_source_crawl_config(session, source_id)
    max_days = cc.get("max_staleness_days", s.crawl.max_staleness_days)   # D-10 per-source override
    stale = last_at is not None and (now - last_at) > timedelta(days=max_days)

    validate_public_url(url)                            # D-07 SSRF BEFORE any HTTP (crawl.py:129 pattern)
    probe = await adapter.fetch_page(url)               # one GET, NO put_raw
    sig = _signature(probe.markdown or "")

    if last_hash is not None and sig == last_hash and not stale:
        repo.touch_source_crawl(source_id, last_crawled_at=now)          # skip: bump timestamp only
        return {"source_id": source_id, "status": "skipped_unchanged"}

    result = await crawl_source(url, settings=s)                          # full path (D-13)
    repo.touch_source_crawl(source_id, last_crawled_at=now, last_content_hash=sig)  # D-17
    return {"source_id": source_id, "status": "recrawled", **result}
```
`validate_public_url` is imported into crawl.py from `ingest.py:99` (used at crawl.py:129,360). Reuse the configured crawler adapter for the probe (RESEARCH Open Question 2 recommendation) so probe markdown matches what a full crawl would store — avoids signature drift.

---

### `dagster_defs/sensors.py` (NEW: `recrawl_sensor` + `recrawl_source_job` + `RecrawlConfig`)

**Analogs:** `assets.py` `IngestConfig` (:71, `Config` subclass), `_PIPELINE_RETRY` (:60, `RetryPolicy(max_retries=2, delay=1, backoff=Backoff.EXPONENTIAL)`), `healthcare_e2e_job` (:868, job definition style). No existing sensor — this is the first; lean on RESEARCH § "Pattern 1/2" (both executed in-process, `job.success == True`).

**`Config` subclass pattern** (`assets.py:71` `IngestConfig`) — mirror for `RecrawlConfig`:
```python
class RecrawlConfig(dg.Config):
    source_id: str
```

**Op + job** (RESEARCH § "Pattern 1", reuses the `_PIPELINE_RETRY` shape from `assets.py:60`, D-13/D-17):
```python
@dg.op(retry_policy=dg.RetryPolicy(max_retries=2, delay=1, backoff=dg.Backoff.EXPONENTIAL))
def recrawl_op(context: dg.OpExecutionContext, config: RecrawlConfig) -> dict:
    from knowledge_lake.pipeline.crawl import recrawl_source
    import asyncio
    result = asyncio.run(recrawl_source(config.source_id))   # gate → skip-or-crawl → touch_source_crawl
    context.log.info("recrawl.op.done", extra=result)
    return result

@dg.job(tags={"klake/kind": "recrawl"})
def recrawl_source_job():
    recrawl_op()
```

**Sensor** (RESEARCH § "Pattern 2", D-04/D-14/D-15/D-16) — cron helpers from Dagster's vendored engine (NO `croniter` import — Pitfall 1), `datetime.now(timezone.utc)` only (Pitfall 4), deterministic `run_key` from the cron fire timestamp (Pitfall 5, not `now`), `SkipReason` when empty (Pitfall 6):
```python
from dagster._utils.schedules import get_next_cron_tick, get_latest_completed_cron_tick

@dg.sensor(job=recrawl_source_job, minimum_interval_seconds=60,
           default_status=dg.DefaultSensorStatus.RUNNING)
def recrawl_sensor(context: dg.SensorEvaluationContext):
    now = datetime.now(timezone.utc)
    with get_session() as session:
        scheduled = repo.list_scheduled_sources(session)
    requests = []
    for src in scheduled:
        base = src.last_crawled_at or src.created_at
        if now >= get_next_cron_tick(src.crawl_schedule, base, "UTC"):
            fire = get_latest_completed_cron_tick(src.crawl_schedule, now, "UTC")
            requests.append(dg.RunRequest(
                run_key=f"{src.id}:{fire.isoformat()}",                     # D-14 deterministic
                run_config=dg.RunConfig(ops={"recrawl_op": RecrawlConfig(source_id=src.id)}),
                tags={"klake/source": src.id},                             # D-16 concurrency key
            ))
    context.update_cursor(now.isoformat())                                 # D-15 watermark (only side-effect)
    return dg.SensorResult(run_requests=requests) if requests else dg.SkipReason("no sources due")
```

---

### `dagster_defs/definitions.py` (MODIFY, config)

**Analog:** `Definitions(...)` (:67-99, read in full). Import block at :37-51; `Definitions` + `EnvVar` at :35.

**Change** (D-12) — add sensor+job imports from `dagster_defs.sensors`, then extend the `Definitions(...)` call:
```python
# add to imports:
from knowledge_lake.dagster_defs.sensors import recrawl_sensor, recrawl_source_job

# in Definitions(...):
    jobs=[healthcare_e2e_job, recrawl_source_job],   # was jobs=[healthcare_e2e_job] (:82)
    sensors=[recrawl_sensor],                          # NEW kwarg
```

---

### `config/settings.py` — `CrawlSettings` (MODIFY, config)

**Analog:** `CrawlSettings` (:53). Nested env prefix `KLAKE_CRAWL__` already wired via `crawl: CrawlSettings` (settings.py:401) — no new plumbing.

**Add** (RESEARCH § "Settings", D-10):
```python
max_staleness_days: int = 30
"""Force a full re-ingest when now - last_crawled_at exceeds this, even if the signature
is unchanged (SCHED-02, D-10). Env: KLAKE_CRAWL__MAX_STALENESS_DAYS. Per-source override
lives at Source.config['crawl_config']['max_staleness_days']."""
```

---

### `cli/app.py` — persist schedule + set/clear verb (MODIFY, CLI)

**Analog:** `cmd_init` `create_source` call (:1104-1117, read in full).

**Persist `crawl_schedule` at `domain-init`** (D-05a) — `crawl_schedule` is a COLUMN, not a config key. Add the kwarg (RESEARCH § "Schedule persistence"), validate with `is_valid_cron_string` before the call:
```python
registry_repo.create_source(
    session,
    name=entry.name, source_type=entry.source_type, url=entry.url,
    normalized_url=norm_url, license_type=entry.license,
    crawl_schedule=entry.crawl_schedule,   # NEW column kwarg (validate is_valid_cron_string)
    config={"domain": domain, "tags": entry.tags,
            "crawl_config": entry.crawl_config, "ingest_type": entry.ingest_type},
)
```

**New set/clear verb** (D-05b) — a Typer command that validates the cron via `is_valid_cron_string` then calls the `set_source_schedule` repo sibling (clear = pass `None`). Follow the existing `typer.echo(...)` result-reporting style (:1123).

---

### `domains/models.py` — `SourceEntry` (MODIFY, model)

**Analog:** `SourceEntry` (:17), existing `crawl_config: dict = {}` (:40) — Pydantic `BaseModel` field style.

**Add** (D-05a):
```python
crawl_schedule: Optional[str] = None   # optional 5-field cron in sources.yaml (D-05a)
```

---

### `infra/dagster/dagster.yaml` (MODIFY, config)

**Analog:** existing `DefaultRunCoordinator` block (replace it). RESEARCH Pitfall 2/5 — tag concurrency is inert under `DefaultRunCoordinator`; per-unique-value limit requires `QueuedRunCoordinator`.

**Replace** (RESEARCH § "dagster.yaml", D-16):
```yaml
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
File is mounted read-only into dagster-webserver and dagster-daemon (`docker-compose.yml:165,191`); daemon restart required to pick it up.

## Shared Patterns

### Change signature (normalize → sha256)
**Source:** `pipeline/clean.py:229-233` (also `remove_boilerplate` `clean.py:82`).
**Apply to:** `pipeline/crawl.py` `recrawl_source` gate. Reuse `remove_boilerplate()` VERBATIM then `hashlib.sha256(text.encode("utf-8")).hexdigest()`. Never author a second normalizer (D-06); never hash raw bytes (REQUIREMENTS out-of-scope anti-feature).

### DetachedInstanceError-safe materialization
**Source:** `pipeline/crawl.py:57-87` (`list_sources_for_crawl_all`, namedtuple materialized inside the session).
**Apply to:** `repo.list_scheduled_sources` — the sensor iterates rows AFTER session close, so materialize every field a namedtuple before returning.

### SSRF guard before any outbound HTTP
**Source:** `validate_public_url()` (imported into `crawl.py` from `ingest.py:99`; enforced at `crawl.py:129,360`).
**Apply to:** the `recrawl_source` seed probe — call `validate_public_url(url)` before `adapter.fetch_page(url)` (D-07, V10/V12 SSRF).

### `Config`-class run config + `_PIPELINE_RETRY`
**Source:** `assets.py:71` (`IngestConfig(Config)`), `assets.py:60` (`RetryPolicy(max_retries=2, delay=1, backoff=Backoff.EXPONENTIAL)`).
**Apply to:** `RecrawlConfig` and `recrawl_op` in `dagster_defs/sensors.py`. Use the `Config` subclass form (idiomatic), not raw `config_schema` dicts.

### None-guard registry helper
**Source:** `repo.get_source_crawl_config` (:866-869) / `get_domain_for_source` (:829-832).
**Apply to:** `touch_source_crawl` and `set_source_schedule` — `session.get(Source, id)`, early-return on `None`.

### Assets/ops call plain pipeline functions (never duplicate logic)
**Source:** `definitions.py:16-19` D-01/D-02 note; `assets.py:30-34`.
**Apply to:** `recrawl_op` calls `recrawl_source()` via `asyncio.run`; the sensor only decides whether/when. No crawling logic is re-implemented (D-13).

## No Analog Found

None. Every file has a concrete in-repo analog. The only net-new *concept* is a Dagster `@sensor` (no prior sensor exists) — but RESEARCH § "Pattern 2" supplies a verified, executed reference implementation and `assets.py` supplies the `Config`/`RetryPolicy`/job conventions.

## Cross-cutting corrections the planner must honor (from RESEARCH)

- **Do NOT `import croniter`** — not importable in this env (Pitfall 1). Use `from dagster._utils.schedules import get_next_cron_tick, get_latest_completed_cron_tick, is_valid_cron_string`. Zero new dependency.
- **`run_key` = cron fire timestamp, not `now`** (D-14, Pitfall 5).
- **Gate BEFORE `put_raw`** — probe/normalize/compare precedes any `crawl_source()` call (D-07/D-08, Pitfall 3).
- **`datetime.now(timezone.utc)` only** — `Source` timestamps are tz-aware; naive/aware mix raises `TypeError` (Pitfall 4).
- **DB writes only in the op** (via `touch_source_crawl`), never in the sensor (D-17).
- **Tag concurrency needs `QueuedRunCoordinator`** — inert under the current `DefaultRunCoordinator` (Pitfall 2).

## Metadata

**Analog search scope:** `registry/` (models, repo, alembic/versions), `pipeline/` (crawl, clean), `dagster_defs/` (assets, definitions), `config/settings.py`, `cli/app.py`, `domains/models.py`, `infra/dagster/dagster.yaml`.
**Files scanned:** 10 analog files read (targeted ranges; 0008 migration + Source model read in full).
**Pattern extraction date:** 2026-07-10
</content>
</invoke>
