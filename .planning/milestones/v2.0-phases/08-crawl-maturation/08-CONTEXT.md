# Phase 8: Crawl Maturation - Context

**Gathered:** 2026-07-08
**Status:** Ready for planning
**Mode:** `--auto` (gray areas auto-selected, recommended defaults chosen without prompts — every decision below is auditable and revisable before planning)

<domain>
## Phase Boundary

Deliver **crawl reliability and completeness**: per-source config wiring, adaptive polite rate limiting, linked-document ingestion, batch crawl command, and partial-JSON enrichment recovery.

Five requirements in scope:

- **CRAWL-01** — `crawl_source` reads per-source `crawl_config` (depth, `rate_limit_seconds`) from the source's stored registry config / `sources.yaml` instead of hard-coded `source_config = None`; reconciles the `rate_limit_rps` vs `rate_limit_seconds` key mismatch so both keys are accepted.
- **CRAWL-02** — `klake crawl-all` batch command loops over all registered sources (optionally filtered by `--domain`), honoring each source's `crawl_config`.
- **CRAWL-03** — The crawler backs off exponentially on HTTP 429/403, enforces a per-host cooldown, and the effective delay is `max(robots crawl-delay, backoff, configured delay)`.
- **ENRICH-07** — Truncated LLM enrichment is detected via `finish_reason == "length"` (not a parse error), a longest-valid-prefix is extracted, partial results are flagged, and an incomplete result is never cached under the normal content-hash key.
- **INGEST-10** — A crawl of an HTML page follows links to `.pdf`/`.docx` assets and ingests them through the existing `ingest_url` path, with an SSRF guard on every followed link, a bounded link frontier, and dedup between an HTML page and its linked document.

**Out of scope:** storage key changes (Phase 9), sparse/hybrid vectors (Phase 10), Dagster re-crawl sensor (Phase 11), MCP/agent surfaces (Phase 12).
</domain>

<decisions>
## Implementation Decisions

### CRAWL-01 — Per-source config wiring

- **D-01:** Add a `get_source_crawl_config(source_id)` helper to `repo.py` that returns the `Source.config` dict (or `{}` if absent), mirroring the `get_domain_for_source` pattern at line 820. Keep the same None-guard and session-handling style.
- **D-02:** In `crawl_source` (`crawl.py:296`), replace the hard-coded `source_config = None` with a real lookup: call `get_source_crawl_config(source_id)` after `source_id` is resolved (line ~105). Pass the returned dict to `resolve_delay()` as `source_config`.
- **D-03:** `resolve_delay()` in `ratelimit.py` already reads `source_config["rate_limit_seconds"]` (Tier 1). Extend it to also accept `rate_limit_rps`: if `"rate_limit_rps"` is present and `"rate_limit_seconds"` is absent, convert via `1 / rate_limit_rps`. Both keys map to the same Tier 1 behavior — `rate_limit_seconds` wins if both are present. Backward-compatible: callers passing `None` unchanged.
- **D-04:** Per-source `depth` is read from `source_config.get("crawl_config", {}).get("depth")` (matching the `sources.yaml` nesting used in `domains/*/sources.yaml`). If present, it overrides `effective_max_pages` in `crawl_source`. If absent, existing `settings.crawl.max_pages` wins.
- **D-05:** `crawl_config` in `sources.yaml` uses the sub-key shape `crawl_config: {depth: N, rate_limit_rps: X}` already registered by `domain-init` (`app.py:1044`). The lookup must traverse this nesting: `source_config.get("crawl_config", {})`. Do not flatten the structure.

### CRAWL-02 — `klake crawl-all` batch command

- **D-06:** Add a `crawl_all_sources()` function to `crawl.py` (or `pipeline/crawl.py`) that fetches all registered sources from the registry (optionally filtered by `domain`) and calls `crawl_source()` for each. Simple sequential loop for v2.0 — no parallelism (avoids amplified rate limiting and complexity).
- **D-07:** CLI command `klake crawl-all` added to `cli/app.py` with `--domain` option (Optional[str], default None). Mirrors `klake crawl` style: emits a summary row per source. Calls `asyncio.run(crawl_all_sources(...))`.
- **D-08:** REST API: add a `POST /crawl-all` endpoint (consistent with existing `POST /crawl`) with optional `domain` query param. Delegates to `crawl_all_sources()`. Returns a list of per-source result dicts.
- **D-09:** Each source's crawl is independent — a failure on one source is logged and counted but does not abort the batch. Return a summary dict with `total`, `succeeded`, `failed`, and a list of per-source results.

### CRAWL-03 — Adaptive rate limiting (backoff on 429/403)

- **D-10:** Adaptive backoff is implemented centrally in the page-fetch loop in `crawl.py` (not in individual adapters, which stay thin). A `AdaptiveRateLimiter` class (or extended `PerHostLimiter`) tracks consecutive 429/403 responses per host and computes the effective delay as `max(robots_delay, backoff_delay, config_delay)`.
- **D-11:** Backoff strategy: exponential with base 2, starting at `config_delay`, capped at `MAX_BACKOFF_SECONDS` (default 60). Reset on any non-4xx response from that host. Per-host, not global.
- **D-12:** `resolve_delay()` signature is extended with an `backoff_extra` parameter (float, default 0.0) so the backoff contribution can be passed in transparently. The three-tier resolution remains the logical priority; backoff is a fourth additive layer that raises the floor when active: `max(tier1/2/3 result, tier_result + backoff_extra)`.
- **D-13:** Per-host cooldown: after a 429, wait at least `COOLDOWN_SECONDS` (default 30) before re-querying that host, regardless of backoff tier. This is a floor, not a replacement for exponential backoff.

### ENRICH-07 — Partial-JSON recovery from truncated LLM output

- **D-14:** Detect truncation via `choices[0].finish_reason == "length"` on the LiteLLM response (not by catching `ValidationError`). This is the authoritative signal — do not infer truncation from parse errors alone.
- **D-15:** Longest-valid-prefix extraction: walk backward from the end of the stripped content to find the last `}` that closes the outermost object (balanced-brace scan). Attempt `model_validate_json()` on that prefix. If it validates to a partial `EnrichmentResult` (missing fields degrade to their defaults), accept it with `is_partial=True`.
- **D-16:** Cache key for partial results: use a `"partial:{content_hash}"` cache key (or a `partial_enrichment` cache table / separate `EnrichmentCacheEntry.is_partial` column) so partial results are never returned to callers expecting a complete enrichment. Complete enrichments continue using the plain content-hash key. A cached partial result must be re-attempted on the next call (treat as a cache miss for complete results).
- **D-17:** Add `is_partial: bool = False` to `EnrichmentResult` (or a wrapper return type). Callers receive this flag and log a warning; they do NOT block indexing on partial enrichment (consistent with the Phase 4 "graceful degradation" contract from D-01/D-03 in Phase 7 CONTEXT).
- **D-18:** No re-try loop inside `enrich_document()` for truncation — a retry is cheap but risks burning double the budget. Log `enrich.partial_result` with `finish_reason` and `content_hash`; let the caller decide whether to retry in a separate budget window.

### INGEST-10 — Linked-document ingestion from crawled HTML

- **D-19:** Link extraction runs after page content is written as a bronze artifact, not before. Only `.pdf` and `.docx` links are followed (configurable via `LINKED_DOC_EXTENSIONS`, default `{".pdf", ".docx"}`).
- **D-20:** Frontier is bounded at `MAX_LINKED_DOCS_PER_PAGE` (default 10) per HTML page. Links are deduplicated against the current crawl job's already-seen URLs (using the existing `_seen_urls` set in the crawl loop). If a linked URL is already in the registry (content-hash match), skip silently.
- **D-21:** SSRF guard is applied to every followed link via the existing `validate_public_url()` from `ingest.py`. No exception: every link, every time, before any HTTP is issued.
- **D-22:** Each followed link is ingested via the existing `ingest_url()` function. The resulting artifact is linked to the same `source_id` and `job_id` as the parent HTML page. No new ingest path — reuse the existing single-URL ingest path exactly.
- **D-23:** Dedup between an HTML page and its linked document: `ingest_url()` already performs content-hash dedup (`get_artifact_by_hash` no-op) — no additional dedup logic needed. If the same PDF is linked from multiple HTML pages in the same crawl, only one artifact is created.
- **D-24:** Failed link follows (SSRF-rejected, HTTP error, size cap exceeded) are logged per link and counted in the crawl job summary as `linked_docs_failed`. They do not abort the parent HTML page's crawl.

### Claude's Discretion

- Exact naming of `get_source_crawl_config` vs `get_source_config` (use whichever is clearest in `repo.py` context).
- Whether `AdaptiveRateLimiter` is a new class or an extension of `PerHostLimiter` — implementation detail, as long as D-10/D-11/D-13 hold.
- Whether `crawl_all_sources()` lives in `crawl.py` or a new `pipeline/batch.py` — follow the existing file-size and module-cohesion conventions.
- Exact `EnrichmentResult` field name for the partial flag (`is_partial` vs `partial`) — planner discretion.
- Whether `MAX_LINKED_DOCS_PER_PAGE`, `MAX_BACKOFF_SECONDS`, `COOLDOWN_SECONDS` are in `Settings` or module-level constants — planner discretion, but they must be visible and tunable.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 8: Crawl Maturation" — goal + 5 success criteria (config wiring, crawl-all, adaptive backoff, linked-doc ingest, partial-JSON recovery).
- `.planning/REQUIREMENTS.md` — CRAWL-01, CRAWL-02, CRAWL-03, ENRICH-07, INGEST-10 (full acceptance text with explicit anti-patterns).

### Prior phase context (load-bearing decisions)
- `.planning/phases/07-metadata-foundation/07-CONTEXT.md` — D-01/D-03 graceful-degradation contract (new enrichment failures must not block indexing); D-05 `Source.config` JSON pattern for non-columnar source metadata.

### Code touch points
- `src/knowledge_lake/pipeline/crawl.py` — `crawl_source()` (lines 42+); `source_config = None` bug at line 296; robots/rate-limit plumbing to extend.
- `src/knowledge_lake/crawl/ratelimit.py` — `resolve_delay()` (Tier 1/2/3 logic to extend with `rate_limit_rps` + backoff); `PerHostLimiter` class.
- `src/knowledge_lake/registry/repo.py` — `get_domain_for_source` (line 820) — exact pattern for new `get_source_crawl_config` helper.
- `src/knowledge_lake/pipeline/enrich.py` — `enrich_document()` (lines ~190+); `_strip_json_fences()` (line 113); `EnrichmentResult` model; LiteLLM call site where `finish_reason` is available.
- `src/knowledge_lake/pipeline/ingest.py` — `ingest_url()` (line 337), `validate_public_url()` (line ~102); SSRF guard implementation; content-hash dedup path.
- `src/knowledge_lake/cli/app.py` — `cmd_crawl` (line 456) — pattern for new `crawl-all` command; `domain-init` at line ~971 shows `crawl_config` nesting in `sources.yaml`.
- `src/knowledge_lake/plugins/builtin/playwright_adapter.py` — lines 78–181 for existing per-host rate-limit usage in an adapter (reference, not change target).

### Key constraint from REQUIREMENTS.md (out-of-scope anti-patterns)
- `REQUIREMENTS.md` Out of Scope: no raw-bytes hashing for change detection (WORM thrash risk) — not in scope here but adjacent; do not introduce content-hash comparisons on re-crawl in this phase.
- `REQUIREMENTS.md` Out of Scope: no GPU-based sparse encoders in CRAWL-03 — not relevant but noted.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`get_domain_for_source` (repo.py:820):** exact pattern to copy for `get_source_crawl_config` — same None-guard, same session handling, same `Source.config` JSON access.
- **`resolve_delay()` (ratelimit.py):** already does three-tier selection cleanly — extend it in-place with `rate_limit_rps` conversion and `backoff_extra` parameter.
- **`PerHostLimiter` (ratelimit.py):** tracks last-fetch time per host — can carry the consecutive-error count for backoff state.
- **`ingest_url()` (ingest.py:337):** already has SSRF guard, size cap, content-hash dedup, and lineage writes — linked-doc ingestion should call it as-is with no changes.
- **`validate_public_url()` (ingest.py:~102):** the shared SSRF seam — always call this before any HTTP; INGEST-10 must use it for every followed link.
- **`_seen_urls` set in crawl loop:** already tracks seen URLs for the crawl job — extend it to cover linked-doc URLs for dedup.
- **`crawl.py` page-fetch loop:** the right place to add adaptive backoff (D-10) — adapters stay thin, backoff is orchestration-level.

### Established Patterns
- **`source_config = None` bug (crawl.py:296):** line is isolated and mechanical to fix — add the registry lookup just above this line; no architectural change required.
- **`Source.config` JSON for non-columnar metadata (Phase 7 D-06):** `crawl_config` nesting (`source_config.get("crawl_config", {})`) is already persisted by `domain-init` (app.py:1044) — lookup must traverse the same nesting.
- **Additive, backward-compatible signatures:** all new kwargs default to None/0 so existing callers work unchanged.
- **Graceful degradation over hard failures:** partial enrichment results, failed link follows, and per-source crawl errors must all degrade gracefully (log + continue), never abort the parent operation.
- **`asyncio.run()` in CLI commands:** `cmd_crawl` calls `asyncio.run(crawl_source(...))` — `crawl-all` follows the same pattern.

### Integration Points
- `crawl_source()` ← `get_source_crawl_config(source_id)` result replaces `source_config = None`.
- `resolve_delay()` ← extended with `rate_limit_rps` conversion + `backoff_extra`.
- `PerHostLimiter` or new `AdaptiveRateLimiter` ← tracks backoff state per host; used in crawl page-fetch loop.
- `enrich_document()` ← `finish_reason` check + prefix-trim + `is_partial` flag on return.
- Crawl page-fetch loop ← after bronze write, extract + SSRF-guard + ingest linked `.pdf`/`.docx` links via `ingest_url()`.
- `cli/app.py` ← new `crawl-all` command + `crawl_all_sources()` pipeline function.
- `api/` ← new `POST /crawl-all` endpoint delegating to `crawl_all_sources()`.
</code_context>

<specifics>
## Specific Ideas

- `rate_limit_rps` and `rate_limit_seconds` are both used across the codebase — accept both in `resolve_delay()` at Tier 1, converting `rps → seconds` via `1/rps`. This avoids requiring any `sources.yaml` migration.
- The `source_config = None` line (crawl.py:296) is a one-line mechanical bug fix — registry lookup added immediately above it.
- Linked-doc following is post-bronze (not pre-write) so the parent HTML page's artifact is always committed before any link is followed.
- Partial enrichment is never served as a complete result — cache key discipline (`partial:` prefix) is the enforcement mechanism.
- The `crawl-all` batch is sequential (no parallelism) for v2.0 to avoid rate-limit amplification and keep the implementation simple.
</specifics>

<deferred>
## Deferred Ideas

- **Parallel `crawl-all` execution** — concurrent source crawls would reduce wall-clock time but require careful rate-limit isolation per host; defer to a later optimization pass.
- **Sitemap-first crawl strategy (SITEMAP-01)** — detect and use sitemaps for URL discovery; deferred to v2.1 per REQUIREMENTS.md.
- **Re-crawl change detection (SCHED-02)** — normalized silver-text hash comparison; that belongs in Phase 11 (Crawl Scheduling).
- **Quality-score propagation to search (QUALITY-01)** — deferred to v2.1.
- **Retry loop inside `enrich_document()` for truncation** — deliberately deferred to caller; D-18 explains why (budget risk).

None of the above were requested as scope — captured so they aren't lost.
</deferred>

---

*Phase: 8-crawl-maturation*
*Context gathered: 2026-07-08*
