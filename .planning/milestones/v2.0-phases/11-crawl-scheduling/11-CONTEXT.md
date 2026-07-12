# Phase 11: Crawl Scheduling - Context

**Gathered:** 2026-07-10
**Status:** Ready for planning
**Mode:** `--auto` (gray areas auto-selected, recommended defaults chosen without prompts — every decision below is auditable and revisable before planning)

<domain>
## Phase Boundary

Deliver **scheduled, change-aware re-crawling**: the lake re-crawls registered sources on a per-source schedule and only re-ingests content that has *genuinely* changed, so the corpus stays fresh without thrashing the immutable WORM raw zone or burning LLM spend on dynamic-HTML noise (timestamps/nonces).

Two requirements in scope:

- **SCHED-01** — A Dagster `@sensor` triggers periodic re-crawl of a source based on its `crawl_schedule`, using a deterministic `run_key` and a cursor watermark (plus per-source concurrency) to avoid duplicate runs and tick storms.
- **SCHED-02** — On re-crawl, a content-change comparison over the **normalized silver-stage text** (not raw bytes) decides whether to re-ingest; a max-staleness threshold forces an occasional refresh to catch change-detection false negatives.

Enabled by an additive, forward-only Alembic `0009` migration adding `crawl_schedule`, `last_crawled_at`, and `last_content_hash` columns to the `sources` registry.

**Out of scope:** new crawl capabilities (per-source config, adaptive backoff, linked-doc ingest — all shipped in Phase 8); hybrid/sparse retrieval (Phase 10); MCP/agent surfaces (Phase 12); auto-discovery scheduling (DISCOVER-01, deferred v2.1); sitemap-first crawl (SITEMAP-01, deferred v2.1); per-page granular change tracking on deep crawls (deferred — see Deferred Ideas).
</domain>

<decisions>
## Implementation Decisions

### Schema migration (0009) — enabling columns

- **D-01:** Additive Alembic migration `0009` (`revision="0009"`, `down_revision="0008"`) adds three **nullable** columns to `sources`, mirroring the additive style of `0006`/`0007`: `crawl_schedule` `String(255)` nullable; `last_crawled_at` `DateTime(timezone=True)` nullable; `last_content_hash` `String(64)` nullable. Forward-only — no backfill, no NOT NULL, no server default. Existing rows get NULL. Add matching `Mapped[...]` attributes with docstrings to the `Source` ORM model (`registry/models.py:58`).
- **D-02:** `crawl_schedule IS NULL` means the source is **not** auto-recrawled — the sensor skips it. Scheduling is strictly opt-in; no existing source changes behavior until a schedule is set. This satisfies the "sensor can be disabled independently of the schema change" rollback note.

### Schedule format & due-check (SCHED-01)

- **D-03:** `crawl_schedule` stores a **5-field cron expression string** interpreted in **UTC** (e.g. `"0 3 * * *"` = daily 03:00 UTC). Cron is Dagster-native, matches the daemon tick model, and gives operators wall-clock cadence control. Chosen over plain interval-seconds because it composes directly with a cron library for "is this source due?" checks.
- **D-04:** The sensor computes due-ness as: `base = last_crawled_at or source.created_at`; `next_fire = croniter(crawl_schedule, base).get_next(datetime)`; the source is **due** when `now >= next_fire`. NULL `last_crawled_at` falls back to `created_at` so a newly-scheduled source fires on its first matching tick. Use a maintained cron library (`croniter`, already a Dagster transitive dep — confirm at plan/research time); do **not** hand-roll cron parsing.
- **D-05:** A schedule is set on a source two ways: (a) a `crawl_schedule:` key in `domains/*/sources.yaml`, persisted to the new column at `domain-init` registration; (b) a small CLI verb to set/clear a schedule on an existing source. Persisting from `sources.yaml` is the primary path; the CLI is the operational override. REST exposure is optional (planner discretion).

### Change-detection gate (SCHED-02) — normalized silver-text, WORM-safe

- **D-06:** The change signature is `SHA256` over the **normalized** page text, where "normalized" reuses the **exact same** transform the silver `clean()` stage applies — `remove_boilerplate()` → `_normalize_whitespace()` (`pipeline/clean.py:82` / `:67`). Reuse that function directly; do **not** author a second normalizer, so "changed" means the same thing at the re-crawl gate and in the silver zone. This is the "normalized silver-stage text, not raw bytes" mandate made concrete.
- **D-07:** The gate runs at **crawl time, on the seed/canonical page, BEFORE any raw write.** A scheduled re-crawl fetches the source's canonical URL (one GET, no `put_raw`), applies the shared normalizer to the fetched markdown, computes the signature, and compares to `Source.last_content_hash`:
  - **Unchanged** (signature equal) **and within max-staleness** → skip the entire re-crawl: no raw/bronze write, no parse/enrich/embed/index. Update only `last_crawled_at`.
  - **Changed** (signature differs) **or `last_content_hash IS NULL`** → run the full existing `crawl_source()` path; on success, set `last_content_hash` to the new signature and `last_crawled_at` to now.
- **D-08:** The gate is WORM-safe by construction: unchanged content never reaches `put_raw`, so no new immutable raw object is created and no LLM enrichment spend is incurred. It **complements** (does not replace) the existing artifact-layer raw content-hash dedup no-op — the normalized gate specifically catches the dynamic-HTML nonce/timestamp churn that byte-level dedup misses.
- **D-09:** For v2.0 the signature is **source-level, keyed on the seed page**, matching the single `last_content_hash` column the schema provides. Per-page granular change tracking across deep (`depth>0`) crawls is deferred (would require per-page hash state, e.g. on the existing `crawl_states` rows).

### Max-staleness forced refresh (SCHED-02)

- **D-10:** A max-staleness threshold forces a full re-ingest even when the normalized signature is unchanged, to catch change-gate false negatives (e.g. the normalizer over-strips a real edit). Config: global `KLAKE_CRAWL__MAX_STALENESS_DAYS` (default `30`), with an optional per-source override via `crawl_config.max_staleness_days` (same `Source.config` nesting Phase 8 established). When `now - last_crawled_at > max_staleness`, bypass the change gate and re-ingest regardless of hash match.
- **D-11:** Staleness is measured against `last_crawled_at`, which is updated on **every** re-crawl attempt (changed or skipped). So an unchanged source still gets one forced deep refresh per staleness window — not on every skipped tick.

### Sensor mechanics (SCHED-01)

- **D-12:** Add a Dagster `@sensor` in a new `dagster_defs/sensors.py`, registered via `Definitions(sensors=[...])` in `dagster_defs/definitions.py`. Set a modest `minimum_interval_seconds` (e.g. `60`; planner discretion). Each evaluation iterates registered sources with a non-NULL `crawl_schedule`, computes due-ness (D-04), and emits one `RunRequest` per due source.
- **D-13:** The re-crawl target is a **new op-based Dagster job** `recrawl_source_job` — crawl is not a pipeline asset (the asset graph starts at `ingest_raw_document`). The job's single op reads `source_id` from run config and calls the existing crawl path (`crawl_source()` via `asyncio.run`) behind the change gate (D-07). Reuse the crawl pipeline wholesale — the sensor/op re-implement **no** crawling logic (mirrors the D-01/D-02 "assets call the same plain pipeline functions" architecture).
- **D-14:** Deterministic `run_key = f"{source_id}:{scheduled_fire_iso}"`, where `scheduled_fire_iso` is the **cron fire timestamp the RunRequest satisfies** (not `now`). Dagster deduplicates RunRequests by `run_key`, so overlapping sensor evaluations or a daemon restart within the same due-window never launch duplicate crawls.
- **D-15:** The sensor persists a **cursor watermark** (`context.update_cursor()`) = ISO timestamp of the last evaluation, advanced each tick. With the deterministic `run_key` this bounds "which fires have I already emitted" and prevents re-emitting historical fires after a daemon restart.
- **D-16:** Per-source concurrency = 1: tag runs (e.g. `{"klake/source": source_id}`) and apply a Dagster concurrency limit / pool so a slow crawl never overlaps its own next tick for the same source. Global crawl concurrency stays modest; per-host politeness continues to come from the Phase 8 `PerHostLimiter` inside `crawl_source()`.
- **D-17:** `last_crawled_at` / `last_content_hash` writes happen inside the crawl **op** after `crawl_source()` returns (success path), never in the sensor. The sensor stays side-effect-free apart from its cursor — keeping the watermark and the DB registry state cleanly separated.

### Claude's Discretion
- Cron library choice (`croniter` vs alternative) and whether to pin it as a direct dependency — confirm what Dagster already ships at research time.
- Exact sensor `minimum_interval_seconds` and whether concurrency uses Dagster concurrency pools vs run-tag limits.
- Whether the change-gate probe lives as a `recrawl=True` branch inside `crawl_source()` or a thin `recrawl_source()` wrapper that calls it — as long as D-06/D-07/D-08 hold and no crawl logic is duplicated.
- Exact CLI verb/signature for setting or clearing a schedule; whether a REST endpoint is added.
- Whether the seed-page probe fetch reuses the configured crawler adapter or a lighter direct GET (must still pass the Phase 8 SSRF `validate_public_url` guard).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 11: Crawl Scheduling" — goal + 4 success criteria + the LIVE-DATA-MIGRATION note (additive columns, forward-only, sensor disable-able independently).
- `.planning/REQUIREMENTS.md` — SCHED-01, SCHED-02 (full acceptance text) and the Out-of-Scope row: **"Raw-bytes hashing for re-crawl change detection is an anti-feature"** (WORM/spend thrash) — SCHED-02 gates on a normalized signature.

### Prior phase context (load-bearing decisions)
- `.planning/phases/08-crawl-maturation/08-CONTEXT.md` — the crawl foundation this phase schedules: `crawl_source()` per-source config wiring (D-01..D-05), the `PerHostLimiter`/`resolve_delay` politeness layer (D-10..D-13), and the `Source.config` `crawl_config` nesting reused here for `max_staleness_days`. Phase 8 explicitly deferred SCHED-02 to Phase 11.
- `.planning/phases/07-metadata-foundation/07-CONTEXT.md` — the `Source.config` JSON pattern for non-columnar per-source metadata (reused for the per-source `max_staleness_days` override).

### Code touch points
- `src/knowledge_lake/registry/models.py:58` — `Source` model; add `crawl_schedule` / `last_crawled_at` / `last_content_hash` `Mapped[...]` columns.
- `src/knowledge_lake/registry/alembic/versions/0008_dataset_examples.py` — the current migration head (`revision="0008"`); new `0009` sets `down_revision="0008"`. Mirror the additive-column op style.
- `src/knowledge_lake/pipeline/clean.py:67` (`_normalize_whitespace`) and `:82` (`remove_boilerplate`) — the shared normalizer the change gate MUST reuse; `clean.py:171` `clean()` shows the existing SHA256-over-normalized-text pattern (step 4) to model the signature on.
- `src/knowledge_lake/pipeline/crawl.py:90` — `crawl_source()` entry point the re-crawl op wraps; the SSRF `validate_public_url` guard (line ~129) the seed probe must reuse.
- `src/knowledge_lake/registry/repo.py` — add a `touch_source_crawl(source_id, *, last_crawled_at, last_content_hash)` update helper next to `get_domain_for_source` (line 822) and `list_sources_for_crawl_all` (used by the sensor to enumerate scheduled sources).
- `src/knowledge_lake/dagster_defs/definitions.py:67` — `Definitions(...)`; add `sensors=[...]` and the new `recrawl_source_job` to `jobs=[...]`.
- `src/knowledge_lake/dagster_defs/assets.py:42` (`define_asset_job`, `RetryPolicy`, `Config`) and `:868` (`healthcare_e2e_job`) — patterns for defining the op-based `recrawl_source_job` and run config.
- `src/knowledge_lake/cli/app.py` — `domain-init` source registration (persist `crawl_schedule` from `sources.yaml`) + a set-schedule CLI verb.

### Key constraint (out-of-scope anti-pattern to honor)
- `.planning/REQUIREMENTS.md` Out of Scope — **no raw-bytes hashing for change detection**. The gate hashes normalized silver-stage text only (D-06). Never compare raw bytes to decide re-ingest.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`remove_boilerplate()` / `_normalize_whitespace()` (clean.py:82 / :67):** the exact silver-stage normalizer — reuse verbatim for the change signature so the gate and the silver zone agree on "changed" (D-06).
- **`clean()` SHA256-over-normalized-text (clean.py:171, step 4):** existing precedent for hashing normalized text for dedup — the change signature follows the same shape.
- **`crawl_source()` (crawl.py:90):** the full crawl vertical the re-crawl op wraps as-is; already has SSRF, rate limiting, two-artifact writes, resume, and per-source `crawl_config` (Phase 8). No crawl logic is re-implemented.
- **`validate_public_url()` (crawl.py imports from ingest.py):** SSRF seam — the cheap seed-page probe fetch must pass through it before any HTTP.
- **`PerHostLimiter` / `resolve_delay()` (crawl/ratelimit.py):** Phase 8 politeness layer — re-crawls inherit it automatically via `crawl_source()`; per-source Dagster concurrency (D-16) sits on top, it does not replace host politeness.
- **`list_sources_for_crawl_all()` (crawl.py:57 / repo.py):** session-safe source enumeration pattern — the sensor needs an analogous "list sources with a schedule" query returning materialized rows (avoid `DetachedInstanceError`).
- **`get_domain_for_source` (repo.py:822):** template for the new `touch_source_crawl` update helper (same None-guard + session handling).
- **`Definitions(...)` (definitions.py:67):** EnvVar-configured resources + assets + `healthcare_e2e_job`; extend with `sensors=[...]` and `jobs+=[recrawl_source_job]`.

### Established Patterns
- **Additive, forward-only migrations:** `0006`/`0007`/`0008` add nullable columns with no backfill — `0009` follows exactly (D-01).
- **`Source.config` JSON for non-columnar per-source metadata (Phase 7 D-06, reused Phase 8):** `max_staleness_days` lives under `crawl_config` in the same nesting (D-10).
- **Assets call plain pipeline functions, never duplicate logic (definitions.py D-01/D-02):** the re-crawl op calls `crawl_source()`; the sensor only decides *whether/when*, never *how* to crawl (D-13).
- **`asyncio.run(crawl_source(...))` from sync entry points (CLI `cmd_crawl`):** the Dagster op follows the same bridge from its sync body.
- **Graceful degradation:** a failed re-crawl for one source is logged and does not abort the sensor tick or other sources' RunRequests.

### Integration Points
- Alembic `0009` + `Source` model ← three new nullable columns.
- `Source.config.crawl_config` ← optional `max_staleness_days` override.
- `crawl_source()` ← wrapped by a change-gated `recrawl` path (seed probe → normalize → compare → skip-or-crawl).
- `repo.py` ← `touch_source_crawl()` update helper + `list_scheduled_sources()` enumeration.
- `dagster_defs/sensors.py` (new) ← `@sensor` emitting deterministic `RunRequest`s targeting `recrawl_source_job`.
- `dagster_defs/definitions.py` ← register the sensor + job.
- `cli/app.py` / `domain-init` ← persist `crawl_schedule` from `sources.yaml`; set/clear-schedule CLI verb.
</code_context>

<specifics>
## Specific Ideas

- "Normalized silver-stage text" is made concrete as: reuse `remove_boilerplate()`/`_normalize_whitespace()` from `clean.py`, `SHA256` the result, store on `Source.last_content_hash`. Same function, same definition of "changed" as the silver zone — no divergence.
- The change gate is a **pre-`put_raw`** seed-page probe: one cheap GET, normalize, compare. Unchanged → the crawl never touches the WORM raw zone or the LLM gateway. This is the direct fix for dynamic-HTML nonce/timestamp thrash.
- Deterministic `run_key = source_id:cron_fire_timestamp` (fire time, not wall-clock now) is what makes tick storms and daemon restarts idempotent — Dagster dedups on it.
- `last_crawled_at` updates on every attempt (even skips) so max-staleness measures true elapsed time since the last *probe*, and the forced refresh fires once per staleness window rather than every tick.
- Opt-in by design: NULL `crawl_schedule` = unscheduled; the whole feature is dormant until an operator sets a schedule, satisfying the independent-rollback requirement.

</specifics>

<deferred>
## Deferred Ideas

- **Per-page granular change detection on deep crawls** — v2.0 gates at the source/seed-page level (single `last_content_hash` column). Per-page normalized-hash state (e.g. on `crawl_states`) so unchanged child pages skip individually is a future refinement, not in SCHED-02's single-column scope.
- **Auto-discovery scheduling (DISCOVER-01)** — scheduled SearXNG re-discovery of *new* sources — deferred to v2.1 per REQUIREMENTS.md; this phase schedules re-crawls of *known* sources only.
- **Sitemap-first re-crawl (SITEMAP-01)** — using `<lastmod>` sitemap hints to pre-filter which pages changed before fetching — deferred to v2.1; would compose well with this phase's gate later.
- **Adaptive schedule tuning** — automatically lengthening/shortening `crawl_schedule` based on observed change frequency — not requested; noted so it isn't lost.

None of the above were requested as scope — captured so they aren't lost.

</deferred>

---

*Phase: 11-crawl-scheduling*
*Context gathered: 2026-07-10*
