# Phase 2: Ingestion - Context

**Gathered:** 2026-07-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 2 delivers the full ingestion breadth — users can get any public resource into the lake via source registration, single-URL downloads, local file uploads, multi-site crawling with three swappable crawler plugins (Crawl4AI, Scrapy, Playwright), and SearXNG-based source discovery. All ingestion paths enforce provenance recording, content deduplication, and legal politeness (robots.txt, rate limits). Interrupted crawls resume without re-fetching completed pages.

Requirements: INGEST-01 through INGEST-09.

</domain>

<decisions>
## Implementation Decisions

### Crawler plugin design
- **D-01:** Crawlers produce **two artifacts per page**: raw HTML/bytes into the raw zone (immutability preserved) AND LLM-ready markdown as a bronze-zone artifact. Full lineage chain links bronze markdown back to its raw source.
- **D-02:** CrawlerPlugin protocol uses a **multi-method interface**: `start_crawl(source_url, config) → CrawlJob`, `poll_status(job_id)`, `get_results(job_id)`. This supports long-running crawls and external process models (Scrapy's reactor, Playwright's browser lifecycle).
- **D-03:** Crawl job state is tracked in a **dedicated `crawl_states` table** with columns: job_id, url, status (pending/complete/failed/robots_blocked), fetched_at. Resume queries for pending URLs. More structured and queryable than a JSON blob in the Job table.
- **D-04:** The three crawlers operate as a **unified system with auto-selection**: one CrawlerPlugin protocol, three adapter implementations. The system auto-selects based on URL/site analysis (static HTML → Crawl4AI, sitemap present → Scrapy, SPA indicators → Playwright). No manual user choice required, though config override is available.

### Dedup & idempotency
- **D-05:** Duplicate detection uses **URL-first, hash-second**: normalize URL (lowercase scheme+host, strip fragment, strip trailing slash) and check the sources table first. If URL exists, skip fetch entirely. If URL is new but content hash matches after fetch, link to existing artifact.
- **D-06:** URL normalization is **conservative**: lowercase scheme+host, strip fragment (#), strip trailing slash. No query param reordering or tracking param removal. Low false-positive risk.
- **D-07:** When a duplicate is detected, the operation returns **silent success with existing IDs** — same return shape as a fresh ingest, with the existing source_id and artifact_id. Log at INFO level. True idempotency — callers don't need to distinguish new vs existing.

### SearXNG discovery flow
- **D-08:** Discovery results **auto-register as sources** in the registry with `source_type='discovered'`. No staging queue or manual approval step before registration. User can list/delete discovered sources. Crawling still requires explicit trigger.
- **D-09:** Metadata captured per discovered source is **minimal: URL + title only**. Domain assignment and further enrichment happen later when the user reviews or triggers ingestion.
- **D-10:** SearXNG integration is built as a **DiscoveryPlugin protocol** (like ParserPlugin, EmbedderPlugin, etc.). SearXNG is the first implementation. This allows swapping to other discovery engines later (Google Custom Search, Tavily, etc.) without changing core logic.

### Robots.txt & rate limits
- **D-11:** Robots.txt checking is **built into each CrawlerPlugin implementation** rather than a centralized middleware. Crawl4AI handles it natively, Scrapy has its own middleware, Playwright adapter implements it. Each crawler is responsible for its own compliance.
- **D-12:** Per-host rate limits use a **three-tier priority**: (1) per-source config override in the Source.config JSON column (highest), (2) Crawl-delay directive from robots.txt if present, (3) global default from Settings (e.g., 1 req/sec per host). Operator can always override.
- **D-13:** Disallowed paths (robots.txt Disallow) are **recorded as `status='robots_blocked'` in the crawl_states table**. Visible in crawl job reports. User can see exactly what was skipped and why.

### Claude's Discretion
- CrawlJob data structure internals (fields beyond the protocol contract), exact auto-selection heuristics for choosing between crawlers, URL normalization implementation details, SearXNG API query construction, crawl_states migration schema specifics, retry/backoff parameters, CLI command naming (e.g., `klake crawl`, `klake discover`), API endpoint design for ingestion operations.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project planning docs
- `.planning/PROJECT.md` — Constraints table (LLM-only gateway, S3 storage, immutability, lineage, legal/robots.txt), Key Decisions (plugin architecture validated Phase 1)
- `.planning/REQUIREMENTS.md` — INGEST-01..09 definitions this phase must satisfy
- `.planning/ROADMAP.md` — Phase 2 goal and 5 success criteria (the scope anchor)

### Phase 1 context (decisions that carry forward)
- `.planning/phases/01-foundation-end-to-end-spike/01-CONTEXT.md` — D-06 (minimal URL download path), D-11 (built-in plugins register via entry-points), D-15 (UUIDv7 with type prefixes)

### Existing implementation (extend, don't rewrite)
- `src/knowledge_lake/plugins/protocols.py` — ParserPlugin, EmbedderPlugin, VectorStorePlugin patterns to follow for CrawlerPlugin and DiscoveryPlugin
- `src/knowledge_lake/plugins/resolver.py` — Entry-point group resolution pattern; add `knowledge_lake.crawlers` and `knowledge_lake.discovery` groups
- `src/knowledge_lake/pipeline/ingest.py` — Existing `ingest_url()` and `ingest_file()` to extend/refactor (SSRF guard, retry logic, registry writes)
- `src/knowledge_lake/registry/models.py` — Source and Artifact ORM models; Source.config JSON column for per-source rate limit overrides
- `src/knowledge_lake/config/settings.py` — Settings pattern for adding `searxng_url`, `crawler` swap key, `discovery` swap key
- `src/knowledge_lake/storage/s3.py` — StorageBackend.put_raw for raw zone writes; bronze zone writes follow same pattern

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ingest_url()` — SSRF validation, httpx streaming download, retry with tenacity, registry write pattern. Phase 2 crawlers can reuse the SSRF guard and retry logic.
- `StorageBackend.put_raw()` — Content-addressed writes to raw zone. Crawlers use this for raw HTML, plus a new `put_bronze()` or zone-parameterized write for markdown.
- `registry_repo.create_source()` — Source creation pattern. Discovery and crawl operations use this same function.
- Plugin resolver pattern — Entry-point groups + `resolve(group, name)`. Extend with `GROUP_CRAWLERS` and `GROUP_DISCOVERY`.
- Source.config JSON column — Already exists for arbitrary source config. Rate limit overrides go here.

### Established Patterns
- Plugin Protocol + entry-point resolution: every external tool behind a `@runtime_checkable` Protocol, registered via pyproject.toml entry points, resolved by a settings key.
- Content-addressed raw zone: SHA256 key, never modified after write. Bronze zone follows same immutability.
- Registry-first writes: every operation creates registry records (Source, Artifact, LineageEvent) within the same session.
- UUIDv7 with type prefixes (`src_`, `doc_`, `chk_`, `art_`). Crawl jobs and crawl states need their own prefixes (e.g., `job_`, `cst_`).
- pydantic-settings with `KLAKE_` prefix and `__` nesting for sub-models.

### Integration Points
- New Alembic migration(s) for `crawl_states` table
- Docker Compose additions: SearXNG service, possibly Playwright browser service
- pyproject.toml entry-point additions for crawler and discovery plugin groups
- CLI expansion: `klake add-source`, `klake upload`, `klake crawl`, `klake discover` commands
- API expansion: source CRUD, crawl trigger, discovery endpoints
- Dagster: crawl jobs as software-defined assets (or ops) — long-running, needs job/sensor pattern

</code_context>

<specifics>
## Specific Ideas

- The existing `ingest_url()` is the thin Phase 1 spike. Phase 2 wraps it with dedup-aware logic (check URL first, check hash after fetch) and the `robots_checked` boolean becomes a real check via the crawler.
- CrawlJob model should link to the existing Job table (Phase 1 placeholder) or replace it — research should determine the cleanest approach.
- Auto-selection heuristics for crawler choice: researcher should investigate what signals reliably distinguish static-site vs SPA vs structured-site before planner commits to specific rules.
- SearXNG runs as a Docker service already supported in the stack docs — add to docker-compose.yml with appropriate config.

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope.

</deferred>

---

*Phase: 2-Ingestion*
*Context gathered: 2026-07-03*
