# Phase 2: Ingestion - Research

**Researched:** 2026-07-03
**Domain:** Multi-crawler web ingestion, source discovery, dedup, robots/rate-limit politeness, crawl job state & resume
**Confidence:** HIGH (stack + APIs verified against PyPI and current official docs; auto-selection heuristics MEDIUM)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Crawler plugin design**
- **D-01:** Crawlers produce **two artifacts per page**: raw HTML/bytes into the raw zone (immutability preserved) AND LLM-ready markdown as a bronze-zone artifact. Full lineage chain links bronze markdown back to its raw source.
- **D-02:** CrawlerPlugin protocol uses a **multi-method interface**: `start_crawl(source_url, config) → CrawlJob`, `poll_status(job_id)`, `get_results(job_id)`. Supports long-running crawls and external process models (Scrapy reactor, Playwright browser lifecycle).
- **D-03:** Crawl job state tracked in a **dedicated `crawl_states` table**: job_id, url, status (pending/complete/failed/robots_blocked), fetched_at. Resume queries for pending URLs. More structured than a JSON blob in the Job table.
- **D-04:** Three crawlers operate as a **unified system with auto-selection**: one CrawlerPlugin protocol, three adapters. Auto-select based on URL/site analysis (static HTML → Crawl4AI, sitemap present → Scrapy, SPA indicators → Playwright). Config override available.

**Dedup & idempotency**
- **D-05:** Duplicate detection **URL-first, hash-second**: normalize URL and check the sources table first. If URL exists, skip fetch entirely. If URL new but content hash matches after fetch, link to existing artifact.
- **D-06:** URL normalization is **conservative**: lowercase scheme+host, strip fragment (#), strip trailing slash. No query param reordering or tracking param removal.
- **D-07:** Duplicate detected → **silent success with existing IDs** — same return shape as fresh ingest. Log at INFO. True idempotency.

**SearXNG discovery flow**
- **D-08:** Discovery results **auto-register as sources** with `source_type='discovered'`. No staging queue. User can list/delete. Crawling still requires explicit trigger.
- **D-09:** Metadata per discovered source is **minimal: URL + title only**.
- **D-10:** SearXNG built as a **DiscoveryPlugin protocol** (like ParserPlugin). SearXNG is the first implementation; swappable later.

**Robots.txt & rate limits**
- **D-11:** Robots.txt checking **built into each CrawlerPlugin implementation**, not centralized middleware. Crawl4AI native, Scrapy own middleware, Playwright adapter implements it.
- **D-12:** Per-host rate limits use **three-tier priority**: (1) per-source `Source.config` override (highest), (2) robots.txt Crawl-delay if present, (3) global Settings default (e.g., 1 req/sec/host). Operator can always override.
- **D-13:** Disallowed paths recorded as **`status='robots_blocked'`** in crawl_states. Visible in crawl job reports.

### Claude's Discretion
CrawlJob data-structure internals (fields beyond the protocol contract), exact auto-selection heuristics, URL normalization implementation details, SearXNG API query construction, crawl_states migration schema specifics, retry/backoff parameters, CLI command naming (`klake crawl`, `klake discover`), API endpoint design for ingestion operations.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INGEST-01 | Register a source URL with domain assignment via CLI and API | `create_source()` already exists; add `normalized_url` column + URL-first dedup lookup (§Dedup). New `klake add-source` + `POST /sources`. |
| INGEST-02 | Download a single URL into raw zone with SHA256/MIME/URL/timestamp/license | `ingest_url()` exists; wrap with URL-first dedup (D-05) and real robots check. |
| INGEST-03 | Upload a local file into raw zone with same provenance | `ingest_file()` exists; wrap with hash-dedup return-existing-IDs shape (D-07). New `klake upload` + `POST /uploads`. |
| INGEST-04 | Crawl a source with Crawl4AI → LLM-ready markdown into raw/bronze | Crawl4AIAdapter (§Crawl4AI); `AsyncWebCrawler.arun(check_robots_txt=True)` → `result.html` + `result.markdown`. Two artifacts (D-01). |
| INGEST-05 | Crawl structured sites with Scrapy | ScrapyAdapter (§Scrapy) via **subprocess** (ReactorNotRestartable — §Pitfall 1). |
| INGEST-06 | Crawl dynamic pages with Playwright | PlaywrightAdapter (§Playwright); manual robots via Protego + rate limiter. |
| INGEST-07 | Discover candidate sources via SearXNG → store in registry | SearXNGDiscovery plugin (§Discovery); `GET /search?q=&format=json`; auto-register `source_type='discovered'` (D-08/09). |
| INGEST-08 | Deduplicate by normalized URL and content hash — re-ingest is a no-op | URL-first (sources.normalized_url) + hash-second (existing `get_artifact_by_hash`) (§Dedup). |
| INGEST-09 | Respect robots.txt + per-host rate limits with retries/backoff | Per-crawler robots (D-11), three-tier delay resolver (D-12), tenacity retries (§Robots & Rate Limiting). |
</phase_requirements>

## Summary

Phase 2 broadens the Phase 1 single-URL spike into the full ingestion surface. The existing code is a clean foundation: `ingest_url()`/`ingest_file()` already implement the SSRF guard, size cap, tenacity retry, streaming download, and registry-first write pattern; `StorageBackend.put_raw()` already does content-addressed WORM writes with hash-based no-op dedup; the plugin resolver + `@runtime_checkable` Protocol pattern is proven for parsers/embedders/vectorstores. Phase 2 extends these seams rather than rewriting them.

The work splits into five vertical slices: (1) **source registration + single-URL/file ingest with dedup** — small extensions to existing functions plus a `normalized_url` column and URL-first lookup; (2) **the crawler subsystem** — a new `CrawlerPlugin` protocol with three adapters (Crawl4AI async in-process, Scrapy in a **subprocess** to dodge the Twisted `ReactorNotRestartable` limitation, Playwright with a manually-implemented robots+rate-limit layer) plus an auto-selection probe; (3) **crawl job state + resume** — extend the placeholder `jobs` table into a crawl-job header and add a `crawl_states` per-URL table so resume is a `WHERE status='pending'` query; (4) **SearXNG discovery** — a `DiscoveryPlugin` hitting the SearXNG JSON API and auto-registering minimal sources; (5) **politeness** — per-crawler robots compliance and a three-tier rate-limit resolver.

The single most important technical fact: **Scrapy cannot be started twice in one Python process** (Twisted reactor is not restartable). A long-lived API/CLI/Dagster process that triggers multiple crawls MUST run each Scrapy crawl in a child process. This aligns perfectly with D-02's multi-method `start_crawl → poll_status → get_results` contract, which already assumes an external-process lifecycle. The second most important fact: **the existing SSRF guard protects `ingest_url` but NOT the crawlers** — every followed link and every SearXNG-discovered URL is attacker-influenceable and must be re-validated before fetch (§Security Domain).

**Primary recommendation:** Model the `CrawlerPlugin` as `start_crawl/poll_status/get_results` over a job persisted in `jobs` + `crawl_states`. Implement Crawl4AI as the in-process async default, Scrapy via `subprocess` (JSON-lines output), Playwright via async browser + Protego robots + a shared per-host async rate limiter. Add a lightweight pre-crawl HTTP probe for auto-selection (sitemap → Scrapy, SPA markers → Playwright, else Crawl4AI) with a Crawl4AI→Playwright escalation fallback when returned markdown is near-empty. Verify robots and dedup with property/behavioural tests.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Source registration (INGEST-01) | Registry (Postgres) | CLI/API | Pure metadata write; `create_source()` already owns it. URL-first dedup lives at the registry query layer. |
| Single-URL / file ingest (INGEST-02/03) | Pipeline (`pipeline/ingest.py`) | Storage (S3) + Registry | Already the home of ingest logic; dedup wraps it. |
| Crawling (INGEST-04/05/06) | Crawler plugin adapters (external process / browser) | Pipeline (orchestration) + Storage | Fetching is an external-tool concern behind the protocol seam (FOUND-08); adapters own robots + rate limiting (D-11). |
| Crawl job state / resume (INGEST-09) | Registry (`jobs` + `crawl_states`) | Pipeline | Resume is a DB query; state must be durable across process death. |
| Bronze markdown production (D-01) | Crawler adapter (produces markdown) | Storage (bronze zone) | Markdown is a crawler output; storage just persists it content-addressed. |
| Discovery (INGEST-07) | Discovery plugin (SearXNG HTTP) | Registry | SearXNG is an external service; plugin normalizes results → source rows. |
| Robots.txt compliance (INGEST-09) | Crawler adapter (per D-11) | — | Each crawler is responsible for its own compliance; no shared middleware. |
| Rate limiting (INGEST-09) | Crawler adapter | Settings/`Source.config` (policy source) | Enforcement is per-adapter; the three-tier policy is resolved from config. |
| Long-running crawl orchestration | Dagster op/job (optional wrapper) | Pipeline plain functions | Follows Phase 1 D-01/D-02: Dagster wraps the same plain functions the CLI/API call. |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| crawl4ai | 0.9.0 | Primary crawler adapter — async HTML fetch + LLM-ready markdown, native robots.txt | `[VERIFIED: PyPI]` project's designated primary crawler (CLAUDE.md); `AsyncWebCrawler` + `arun(config=CrawlerRunConfig(check_robots_txt=True))` produces `result.html` and `result.markdown` in one call `[CITED: docs.crawl4ai.com/core/browser-crawler-config]` |
| scrapy | 2.16.0 | Structured/bulk crawler adapter | `[VERIFIED: PyPI]` project's secondary crawler (CLAUDE.md); mature middleware (RobotsTxtMiddleware, RetryMiddleware, AutoThrottle) |
| playwright | 1.61.0 | Dynamic/SPA crawler adapter | `[VERIFIED: PyPI]` headless-browser rendering for JS-heavy pages; async API integrates with the async pipeline |
| protego | 0.6.2 | robots.txt parsing for the Playwright adapter (and any manual robots check) | `[VERIFIED: PyPI]` maintained by the Scrapy team; pure-Python, supports wildcards **and `Crawl-delay`** (stdlib `urllib.robotparser` does not parse Crawl-delay reliably or support `*`/`$` wildcards) |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| httpx | 0.28.1 (already pinned) | SearXNG JSON API calls + the auto-selection pre-crawl probe | Already a dependency; no new client needed for discovery |
| tenacity | 9.1.4 (already pinned) | Retry/backoff for the Playwright adapter and discovery calls | Already used by `ingest_url`; reuse for crawler retries (INGEST-09) |
| tldextract | 5.3.1 | Reliable registrable-domain / host extraction for per-host rate-limit keys and same-site link scoping | Optional but recommended for correct per-host bucketing (handles multi-label TLDs like `.co.uk`) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| protego (Playwright robots) | stdlib `urllib.robotparser` | stdlib is zero-dep but ignores `Crawl-delay` in older Pythons and lacks `*`/`$` wildcard support — breaks D-12 tier 2. Protego is what Scrapy itself uses. |
| protego | reppy (0.4.14) | reppy is stale (last release years old) and has a C-extension build dependency; protego is pure-Python and actively maintained. Avoid reppy. |
| hand-rolled URL normalizer | w3lib `canonicalize_url` / `courlan` / `url-normalize` | These libraries **do more than D-06 wants** — `canonicalize_url` sorts query params (D-06 explicitly forbids reordering). D-06's normalization (lowercase scheme+host, strip fragment, strip trailing slash) is ~6 lines of stdlib `urllib.parse` and is the correct choice here. See §Don't Hand-Roll for the nuance. |
| Scrapy subprocess | Scrapy `CrawlerRunner` in a persistent reactor thread | Running one shared reactor in a background thread avoids per-crawl process spawn but couples all crawls to one reactor lifecycle and complicates cancellation/resume. Subprocess isolation is simpler, crash-safe, and matches D-02. Revisit only if process-spawn overhead becomes a measured bottleneck. |

**Installation:**
```bash
# Add to pyproject.toml [project.dependencies] with exact pins:
uv add "crawl4ai==0.9.0" "scrapy==2.16.0" "playwright==1.61.0" "protego==0.6.2" "tldextract==5.3.1"
# Playwright browser binaries (NOT pip-installed — separate download, ~150 MB):
uv run playwright install chromium
# Crawl4AI also uses Playwright under the hood; its post-install helper:
uv run crawl4ai-setup   # runs `playwright install` + diagnostics
```

**Version verification (performed 2026-07-03 via `pip index versions`):**
- crawl4ai 0.9.0 `[VERIFIED: PyPI]` (matches CLAUDE.md pin)
- scrapy 2.16.0 `[VERIFIED: PyPI]` (matches CLAUDE.md pin)
- playwright 1.61.0 `[VERIFIED: PyPI]` (CLAUDE.md does not pin Playwright — recommend pinning 1.61.0)
- protego 0.6.2 `[VERIFIED: PyPI]`
- tldextract 5.3.1 `[VERIFIED: PyPI]`

## Package Legitimacy Audit

> All packages are established, high-download OSS with public source repos. No SLOP/SUS verdicts.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| crawl4ai | PyPI | ~2 yrs | high (top-trending crawler) | github.com/unclecode/crawl4ai | OK | Approved (project-designated) |
| scrapy | PyPI | 10+ yrs | very high | github.com/scrapy/scrapy | OK | Approved |
| playwright | PyPI | 5+ yrs | very high | github.com/microsoft/playwright-python | OK | Approved (Microsoft) |
| protego | PyPI | 6+ yrs | high | github.com/scrapy/protego | OK | Approved |
| tldextract | PyPI | 10+ yrs | very high | github.com/john-kurkowski/tldextract | OK | Approved |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

> Note: `reppy`, `courlan`, `url-normalize`, `w3lib` were evaluated and **rejected** (see Alternatives Considered) — not for legitimacy reasons but because they do more/less than the locked decisions require.

## Architecture Patterns

### System Architecture Diagram

```
                 ┌─────────────────────────────────────────────────────────┐
   CLI (klake)   │  add-source | upload | ingest-url | crawl | discover      │
   API (FastAPI) │  POST /sources /uploads /crawl-jobs  GET /crawl-jobs/{id}  │
                 └───────────────┬───────────────────────────┬──────────────┘
                                 │                            │
                    ┌────────────▼───────────┐   ┌────────────▼────────────┐
                    │ pipeline/ingest.py     │   │ pipeline/discover.py    │
                    │  (dedup-aware wrapper)  │   │  DiscoveryPlugin seam    │
                    └───┬───────────────┬────┘   └───────────┬─────────────┘
   URL-first dedup ─────┘               │                     │  SearXNG JSON API
   (sources.normalized_url)             │                     ▼   (Docker service)
                                        │            ┌────────────────────┐
                    ┌───────────────────▼──────┐     │ auto-register       │
                    │ pipeline/crawl.py         │     │ source_type=        │
                    │  auto-select probe (httpx)│     │ 'discovered'        │
                    │  → resolve CrawlerPlugin   │     └────────────────────┘
                    └───┬─────────┬─────────┬───┘
        static │        │ sitemap │         │ SPA markers
               ▼        ▼         ▼         ▼
        ┌──────────┐ ┌──────────────┐ ┌──────────────┐
        │Crawl4AI  │ │Scrapy adapter│ │Playwright     │
        │(async,   │ │(SUBPROCESS,  │ │adapter        │
        │in-proc)  │ │JSONL out)    │ │(async browser)│
        │robots:   │ │robots:       │ │robots: Protego│
        │native    │ │ROBOTSTXT_OBEY│ │+ rate limiter │
        └────┬─────┘ └──────┬───────┘ └──────┬────────┘
             │ per page: (raw HTML, markdown) │
             └──────────────┬─────────────────┘
                            ▼
        ┌───────────────────────────────────────────────┐
        │ per page write:                                 │
        │  put_raw(raw HTML)  → raw zone   (doc_ artifact) │
        │  put_bronze(md)     → bronze zone(bronze artifact│
        │                        parent = raw doc)  [D-01] │
        │  crawl_states row: status, fetched_at, artifacts │
        └───────┬───────────────────────┬─────────────────┘
                ▼                        ▼
        S3/MinIO (raw + bronze)   Postgres (jobs, crawl_states,
                                   sources, artifacts, lineage)
                            ▲
                            │ resume: SELECT ... WHERE job_id=? AND status='pending'
```

### Recommended Project Structure

```
src/knowledge_lake/
├── plugins/
│   ├── protocols.py            # ADD: CrawlerPlugin, DiscoveryPlugin, CrawlJob, CrawlPageResult, DiscoveryResult
│   ├── resolver.py             # ADD: GROUP_CRAWLERS, GROUP_DISCOVERY, get_crawler(), get_discovery()
│   └── builtin/
│       ├── crawl4ai_adapter.py     # Crawl4AIAdapter (async, in-process)
│       ├── scrapy_adapter.py       # ScrapyAdapter (subprocess launcher)
│       ├── scrapy_spider.py        # module run as `python -m ... <url> <out.jsonl>` child process
│       └── playwright_adapter.py   # PlaywrightAdapter (async browser + Protego robots + rate limiter)
├── crawl/
│   ├── select.py               # auto-selection probe + escalation fallback (D-04)
│   ├── robots.py               # Protego-backed robots fetch/cache + Crawl-delay parse (D-11/13)
│   └── ratelimit.py            # three-tier per-host async rate limiter (D-12)
├── pipeline/
│   ├── ingest.py               # EXTEND: dedup-aware ingest_url/ingest_file (D-05/06/07)
│   ├── crawl.py                # NEW: orchestrates start_crawl/poll/get_results, writes raw+bronze
│   └── discover.py             # NEW: run discovery plugin → auto-register sources (D-08/09/10)
├── registry/
│   ├── models.py               # EXTEND Job; ADD CrawlState; add normalized_url to Source
│   ├── repo.py                 # ADD: create_crawl_job, upsert_crawl_state, pending_states,
│   │                           #      get_source_by_normalized_url, create_bronze_artifact
│   └── alembic/versions/
│       └── 0002_ingestion.py   # migration: sources.normalized_url, jobs columns, crawl_states
├── storage/
│   └── s3.py                   # ADD: put_bronze() (bronze zone, content-addressed, D-01)
├── config/settings.py          # ADD: searxng_url, crawler, discovery, crawl_* defaults
├── cli/app.py                  # ADD: add-source, upload, crawl, discover commands
└── api/
    ├── app.py                  # ADD: /sources, /uploads, /crawl-jobs, /discover
    └── schemas.py              # ADD: request/response models for the above
```

### Pattern 1: CrawlerPlugin protocol (D-02 multi-method)
**What:** A `@runtime_checkable` Protocol mirroring the existing plugin style, with an external-process lifecycle.
**When to use:** All three crawler adapters implement it; resolved by `settings.crawler` (or auto-selection).
**Example:**
```python
# Source: pattern extends src/knowledge_lake/plugins/protocols.py (existing style)
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

@dataclass
class CrawlJob:
    job_id: str                 # 'job_<uuidv7>'
    source_url: str
    crawler: str                # 'crawl4ai' | 'scrapy' | 'playwright'
    status: str = "pending"     # pending|running|complete|failed
    config: dict[str, Any] = field(default_factory=dict)

@dataclass
class CrawlPageResult:
    url: str
    status: str                 # complete|failed|robots_blocked  (D-13)
    html: bytes | None = None   # raw bytes → raw zone (D-01)
    markdown: str | None = None # LLM-ready → bronze zone (D-01)
    error: str | None = None
    fetched_at: str | None = None

@runtime_checkable
class CrawlerPlugin(Protocol):
    name: str
    def start_crawl(self, source_url: str, config: dict[str, Any]) -> CrawlJob: ...
    def poll_status(self, job_id: str) -> str: ...                 # returns status
    def get_results(self, job_id: str) -> list[CrawlPageResult]: ... # incremental or final
```
> `CrawlJob` internals beyond the three-method contract are Claude's discretion (D-04). The persisted source of truth is the `jobs` + `crawl_states` rows; the dataclass is the in-memory handle.

### Pattern 2: Scrapy via subprocess (ReactorNotRestartable-safe)
**What:** `ScrapyAdapter.start_crawl` spawns `python -m knowledge_lake.plugins.builtin.scrapy_spider <url> <out.jsonl> <config.json>` as a child process; `poll_status` checks the process + tails the JSONL; `get_results` parses completed lines.
**When to use:** Any time Scrapy runs inside the long-lived API/CLI/Dagster process (which is always, in this app).
**Why:** Twisted's reactor cannot be restarted in-process; a second `CrawlerProcess.start()` raises `ReactorNotRestartable`. One Scrapy run per child process side-steps this entirely and gives crash isolation + clean cancellation.
```python
# Source: https://docs.scrapy.org/en/latest/topics/practices.html + issue scrapy/scrapy#2941
import subprocess, sys
proc = subprocess.Popen(
    [sys.executable, "-m", "knowledge_lake.plugins.builtin.scrapy_spider",
     source_url, out_path, config_path],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
)
# poll_status: proc.poll() is None → running; ==0 → complete; else failed
# child writes one JSON object per page (url, status, html_path/md) to out.jsonl
```

### Pattern 3: Auto-selection probe (D-04)
**What:** Before committing a crawler, do ONE cheap `httpx.get` of the entry URL (+ a HEAD/GET of `/robots.txt` and `/sitemap.xml`) and classify.
**When to use:** `klake crawl <url>` with no explicit `--crawler` override.
```python
# Source: heuristics synthesized from SPA-detection guidance (see Sources)
def select_crawler(url: str, html: str, has_sitemap: bool) -> str:
    if has_sitemap:                       # robots.txt Sitemap: or /sitemap.xml 200
        return "scrapy"                   # structured, enumerable site
    if _looks_like_spa(html):             # SPA markers below
        return "playwright"
    return "crawl4ai"                     # default: static/server-rendered HTML

def _looks_like_spa(html: str) -> bool:
    markers = ('__NEXT_DATA__', 'window.__NUXT__', 'ng-version=',
               'data-reactroot', 'id="root"', 'id="app"')
    has_marker = any(m in html for m in markers)
    # near-empty body + heavy scripts is the strongest signal
    text_len = len(_strip_tags(html))
    script_count = html.count('<script')
    return has_marker and text_len < 500 and script_count >= 3
```
**Escalation fallback (recommended):** if the chosen static crawler (Crawl4AI) returns markdown below a threshold (e.g., < 200 chars) for a page that returned HTTP 200, re-fetch that page with Playwright. This catches SPAs the probe misclassified without a browser-for-everything cost. `[ASSUMED — thresholds need tuning against real sites]`

### Pattern 4: Two-artifact write per page (D-01)
```python
# Source: extends src/knowledge_lake/storage/s3.py put_raw pattern
with get_session() as session:
    raw_art = storage.put_raw(source_id, page.html, "html", session)      # raw zone
    bronze_art = storage.put_bronze(                                       # bronze zone
        source_id, page.markdown.encode(), "md", session,
        parent_artifact_id=raw_art.id,        # lineage: bronze → raw (D-01)
    )
    repo.upsert_crawl_state(session, job_id=job.id, url=page.url,
        status=page.status, raw_artifact_id=raw_art.id,
        bronze_artifact_id=bronze_art.id, fetched_at=page.fetched_at)
```

### Anti-Patterns to Avoid
- **Calling `CrawlerProcess.start()` twice in one process:** raises `ReactorNotRestartable`. Always subprocess Scrapy.
- **Trusting crawler-followed URLs:** the existing SSRF guard only runs in `ingest_url`. A crawler that follows a link to `http://169.254.169.254/` or an internal host bypasses it. Re-validate EVERY fetched/discovered URL (§Security).
- **Using `w3lib.canonicalize_url` for D-06:** it sorts query params — violates "no query reordering." Use the conservative stdlib normalizer.
- **Blocking a Dagster op for a multi-hour crawl:** don't hold one op open polling for hours. Use the persisted `crawl_states` so any process (op, CLI, API) can drive/resume the crawl; keep the op thin or use a sensor.
- **One Source row per crawled page:** a crawl = ONE site Source; pages are `raw_document`/`bronze` artifacts under it, tracked per-URL in `crawl_states`. URL-first source dedup (D-05) applies to single-URL ingest and source registration, not to each page.
- **Playwright with `--no-sandbox` on untrusted pages without resource limits:** run with a per-page timeout, JS/network caps, and blocked downloads.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| robots.txt parsing + Crawl-delay + wildcards | Custom regex robots parser | `protego` (Playwright adapter) / native `ROBOTSTXT_OBEY` (Scrapy) / `check_robots_txt=True` (Crawl4AI) | Wildcards, `$` anchors, `Crawl-delay`, multi-agent precedence are subtle; protego is the reference impl. |
| HTML→markdown for LLMs | Custom BeautifulSoup→md | Crawl4AI `DefaultMarkdownGenerator` (`result.markdown`) | Reading-order, boilerplate stripping, link handling already solved. |
| Headless-browser page rendering | Custom Selenium wiring | Playwright | Auto-waits, network idle, robust selectors, maintained by Microsoft. |
| Retry/backoff | Custom loop | `tenacity` (already pinned) | Already used by `ingest_url`; consistent policy. |
| Meta-search across engines | Direct Google/Bing scraping | SearXNG (Docker, JSON API) | Aggregates engines, no API keys, privacy-respecting (project decision). |
| **URL normalization (D-06)** | ⚠ *This is the exception* — DO implement a ~6-line stdlib helper | stdlib `urllib.parse.urlsplit` | Every library (`w3lib`, `courlan`, `url-normalize`) normalizes **more** than D-06 permits (query sorting, tracking-param removal). D-06 is deliberately conservative; a tiny hand-rolled function is *correct* here, not reinvention. |

**Key insight:** In this domain the danger is *under*-using mature tools for robots/rendering/markdown (subtle correctness + legal risk) while *over*-using them for URL normalization (they'd break D-06's low-false-positive contract). Match the tool to the decision, not the reverse.

## Runtime State Inventory

> Phase 2 is additive/greenfield within an existing schema (new tables + columns + plugins). No rename/refactor. This inventory covers the schema-migration surface only.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Existing `sources`, `artifacts` rows from Phase 1 spike (demo runs). New `sources.normalized_url` column will be NULL on existing rows. | Migration adds column nullable; optional backfill of existing rows' normalized_url (low volume — spike data only). |
| Live service config | New Docker service **SearXNG** must be added to `docker-compose.yml` with `settings.yml` enabling `formats: [html, json]` (JSON is 403 by default). Playwright/Crawl4AI need browser binaries baked into the `Dockerfile` image. | Compose + Dockerfile edits; `infra/searxng/settings.yml`; `playwright install chromium` + `crawl4ai-setup` in image build. |
| OS-registered state | None — no OS-level task/service registration in this app. | None (verified: app runs entirely in Docker Compose; no host cron/systemd). |
| Secrets/env vars | New settings keys: `KLAKE_SEARXNG_URL`, `KLAKE_CRAWLER`, `KLAKE_DISCOVERY`, crawl defaults (`KLAKE_CRAWL__*`). No new secrets (SearXNG needs no API key). | Add to `settings.py`, `.env.example`, compose `x-common-env`. |
| Build artifacts / installed packages | Playwright/Crawl4AI browser binaries are downloaded at build time, NOT via pip. `uv.lock` regenerates on `uv add`. | Add `playwright install chromium` + `crawl4ai-setup` to Dockerfile; regenerate lockfile; ensure browser cache path persists in image. |

## Common Pitfalls

### Pitfall 1: Twisted ReactorNotRestartable (Scrapy)
**What goes wrong:** Second in-process Scrapy crawl raises `twisted.internet.error.ReactorNotRestartable`; the whole API/daemon process becomes unable to crawl again until restart.
**Why it happens:** Twisted's global reactor cannot be started, stopped, then restarted. `CrawlerProcess.start()` starts+stops it.
**How to avoid:** Run each Scrapy crawl in a fresh child process (`subprocess`). The child's reactor lives and dies with the process. Matches D-02's external-process model.
**Warning signs:** First crawl works, all subsequent Scrapy crawls fail; error only appears in long-lived processes (not one-shot scripts/tests). `[VERIFIED: scrapy/scrapy#2941, docs.scrapy.org practices]`

### Pitfall 2: SSRF via crawler-followed / discovered URLs
**What goes wrong:** Crawler follows a link (or SearXNG returns a result) pointing at `169.254.169.254` (cloud IMDS) or an RFC-1918 host → server-side request forgery, credential theft.
**Why it happens:** `_validate_url_scheme()` guards `ingest_url` only; Crawl4AI/Scrapy/Playwright fetch arbitrary discovered URLs without it.
**How to avoid:** Extract the SSRF validator into a reusable function and call it (a) before every crawler fetch/link-follow, and (b) on every SearXNG result before auto-registering/crawling. Constrain crawls to the seed registrable domain by default.
**Warning signs:** Crawl logs show requests to private IPs or metadata endpoints; unexpected 200s from internal hosts. `[VERIFIED: existing ingest.py guard scope]`

### Pitfall 3: SearXNG JSON returns 403
**What goes wrong:** `GET /search?q=...&format=json` returns `403 Forbidden`.
**Why it happens:** JSON output is disabled by default; must be enabled in `settings.yml` under `search: formats:`.
**How to avoid:** Ship `infra/searxng/settings.yml` with `formats: [html, json]` and mount it into the container. Add an integration test asserting JSON is enabled.
**Warning signs:** Discovery returns 403 while the SearXNG web UI works fine. `[CITED: docs.searxng.org/dev/search_api]`

### Pitfall 4: Bronze/raw dedup interaction with UNIQUE(content_hash, artifact_type)
**What goes wrong:** Two pages with identical HTML across crawls — `put_raw` no-ops correctly (returns existing artifact), but if you also try to insert a second `crawl_states` row or a second bronze artifact with the same `(hash, artifact_type)`, you hit the unique constraint or double-count.
**Why it happens:** Existing `uq_artifacts_hash_type` makes raw/bronze artifacts globally unique per content; crawl_states must tolerate the same content appearing under multiple URLs/jobs.
**How to avoid:** Let `put_raw`/`put_bronze` return existing artifacts (no-op, D-07 semantics). Key `crawl_states` uniqueness on `(job_id, normalized_url)`, NOT on content hash — the same content under a new URL is a new state row pointing at the existing artifact.
**Warning signs:** IntegrityError on re-crawl; resume double-processing. `[VERIFIED: models.py uq_artifacts_hash_type]`

### Pitfall 5: Playwright/Crawl4AI browser binaries missing in container
**What goes wrong:** `playwright._impl._errors.Error: Executable doesn't exist` at first crawl in the Docker image.
**Why it happens:** `pip install playwright` installs the Python package but NOT the browser binaries; those need `playwright install`.
**How to avoid:** Add `RUN playwright install --with-deps chromium` (and `crawl4ai-setup`) to the Dockerfile; verify the browser cache path is in the final image layer.
**Warning signs:** Works locally (dev ran `playwright install`) but fails in compose. `[CITED: playwright-python docs]`

### Pitfall 6: Rate-limit tier precedence inverted
**What goes wrong:** Global default overrides a stricter robots `Crawl-delay`, or robots overrides an operator's explicit per-source override → either impoliteness (legal risk) or unwanted slowness.
**Why it happens:** Tier resolution order implemented backwards.
**How to avoid:** Resolve strictly per D-12: `Source.config['rate_limit']` if set → else robots `Crawl-delay` if present → else `Settings` global default. Unit-test all four permutations (§Validation).
**Warning signs:** Crawl faster than robots asks, or operator override ignored. `[CITED: D-12]`

## Code Examples

### Conservative URL normalization (D-06)
```python
# Source: stdlib urllib.parse — deliberately minimal per D-06
from urllib.parse import urlsplit, urlunsplit

def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    netloc = host
    if parts.port:                       # preserve explicit non-default port
        netloc = f"{host}:{parts.port}"
    path = parts.path.rstrip("/") or "/"  # strip trailing slash (keep root "/")
    # D-06: keep query AS-IS (no reorder), DROP fragment
    return urlunsplit((scheme, netloc, path, parts.query, ""))
```
> Property to test (hypothesis): `normalize_url(normalize_url(u)) == normalize_url(u)` (idempotent) and normalization never changes query-param order.

### Crawl4AI adapter core (INGEST-04, D-11 native robots)
```python
# Source: https://docs.crawl4ai.com/core/browser-crawler-config/
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode

async def crawl_page(url: str) -> CrawlPageResult:
    cfg = CrawlerRunConfig(check_robots_txt=True, cache_mode=CacheMode.BYPASS)
    async with AsyncWebCrawler() as crawler:
        res = await crawler.arun(url=url, config=cfg)
    if not res.success and res.status_code == 403:   # robots-blocked signal
        return CrawlPageResult(url=url, status="robots_blocked")
    return CrawlPageResult(
        url=url, status="complete",
        html=(res.html or "").encode(),
        markdown=str(res.markdown),   # DefaultMarkdownGenerator output
    )
```

### SearXNG discovery (INGEST-07, D-08/09/10)
```python
# Source: https://docs.searxng.org/dev/search_api.html
import httpx
def searxng_search(searxng_url: str, query: str, limit: int = 20) -> list[DiscoveryResult]:
    r = httpx.get(f"{searxng_url}/search",
                  params={"q": query, "format": "json"}, timeout=15.0)
    r.raise_for_status()                       # 403 => JSON not enabled (Pitfall 3)
    out = []
    for item in r.json().get("results", [])[:limit]:
        out.append(DiscoveryResult(url=item["url"], title=item.get("title", "")))
    return out
# each result → repo.create_source(name=title, source_type="discovered", url=url)
#   AFTER SSRF-validating item["url"] (Pitfall 2), with URL-first dedup (D-05)
```

### Three-tier rate-limit resolver (D-12)
```python
def resolve_delay(source_config: dict | None, robots_crawl_delay: float | None,
                  global_default: float) -> float:
    if source_config and "rate_limit_seconds" in source_config:   # tier 1
        return float(source_config["rate_limit_seconds"])
    if robots_crawl_delay is not None:                            # tier 2
        return float(robots_crawl_delay)
    return float(global_default)                                  # tier 3
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `requests` + BeautifulSoup + manual markdown | Crawl4AI `AsyncWebCrawler` → `result.markdown` | crawl4ai 0.3+ | One call yields LLM-ready markdown + robots handling |
| Manual robots.txt regex / stdlib robotparser | `check_robots_txt=True` (Crawl4AI), `ROBOTSTXT_OBEY` (Scrapy), Protego (Playwright) | current | Correct wildcard + Crawl-delay handling for free |
| Selenium | Playwright async | 2021+ | Auto-wait, network-idle, less flake |
| Scrapy in-process multi-run | Scrapy per-crawl subprocess | long-standing Twisted constraint | Only crash-safe way to run repeated crawls in a long-lived service |
| SearXNG scraping HTML | SearXNG `format=json` API | current | Structured results; but must enable JSON in settings.yml |

**Deprecated/outdated:**
- `reppy` for robots.txt: stale, C-extension build burden → use Protego.
- `w3lib.canonicalize_url` for this phase: over-normalizes (sorts query) → violates D-06.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | SPA-detection thresholds (text < 500 chars, ≥3 `<script>`, marker strings) reliably separate SPA from static | Pattern 3 | Misclassification → wrong crawler chosen; mitigated by escalation fallback (A2) and config override (D-04). |
| A2 | Crawl4AI→Playwright escalation on near-empty markdown (< 200 chars) is a good safety net | Pattern 3 | Wrong threshold → either missed SPAs or unnecessary browser launches; tune against real healthcare sites. |
| A3 | Crawl4AI signals robots-block via `success=False` + `status_code==403` | Code Examples | If the signal differs, robots_blocked status won't record; verify against installed 0.9.0 API at plan time. |
| A4 | Playwright 1.61.0 is compatible with the Crawl4AI 0.9.0 bundled Playwright requirement | Standard Stack | Version conflict → install failure; verify `uv` resolves both before pinning. |
| A5 | Extending the existing `jobs` table (vs a new `crawl_jobs` table) is the cleanest fit for D-03 | §Crawl Job State | If `jobs` is later needed generically for non-crawl jobs, a `job_type` discriminator column covers it; low risk. |
| A6 | Bronze markdown should be content-addressed and WORM like raw (new `bronze_document` artifact_type) | D-01 patterns | If bronze is meant to be mutable/re-derivable, the immutability layer is over-strict; but immutability + lineage is the CLAUDE.md default. |
| A7 | Per-crawl = one Source (site); pages are artifacts under it | Anti-Patterns | If product wants each page as its own Source, source-table dedup semantics change; confirm with planner. |

## Open Questions

1. **Extend `jobs` vs. add `crawl_jobs` table (D-03 ambiguity)?**
   - What we know: D-03 mandates a separate `crawl_states` (per-URL) table; the code_context says "link to the existing Job table (Phase 1 placeholder) or replace it — research should determine the cleanest approach."
   - What's unclear: whether the crawl-job *header* lives in the existing `jobs` table (extended) or a new table.
   - Recommendation: **Extend `jobs`** with `source_id`, `job_type='crawl'`, `crawler`, `config`, `stats`, `updated_at`; add `crawl_states` as the per-URL child. Minimal new surface, reuses `job_` prefix. (A5)

2. **Crawl scope / link-following depth defaults?**
   - What we know: Crawl4AI supports BFS/DFS/Best-First deep crawling; Scrapy has depth limits. Success criteria say "crawl a source" (a site), not "one page."
   - What's unclear: default max depth / max pages / same-domain-only for the MVP.
   - Recommendation: default to same-registrable-domain, a conservative `max_pages` (e.g., 50) and `max_depth` (e.g., 2), both overridable via `Source.config`. Confirm with planner/discuss.

3. **Dagster wrapping for long crawls — op-that-polls vs sensor?**
   - What we know: Phase 1 kept Dagster thin (D-01/D-02: assets wrap the same plain functions). Crawls can run minutes-to-hours.
   - What's unclear: whether Phase 2 must expose crawl as a Dagster asset now (IFACE-03 is Phase 6) or defer.
   - Recommendation: implement crawl as plain functions + `crawl_states` durability first (resume works from any driver); add a thin `crawl_source` Dagster asset that drives to completion for observability, but do not block phase completion on a sophisticated sensor. `[ASSUMED]`

4. **Domain assignment for INGEST-01 (`with domain assignment`)?**
   - What we know: requirement says "register a source URL **with domain assignment**"; domain packs are Phase 6.
   - What's unclear: whether "domain" here means a healthcare/domain-pack tag or the URL host.
   - Recommendation: store an optional `domain` value in `Source.config` (or a nullable `domain` column) now; full domain-pack wiring is Phase 6. Confirm interpretation.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| crawl4ai | INGEST-04 | ✗ (not yet installed) | 0.9.0 on PyPI | none — must add |
| scrapy | INGEST-05 | ✗ | 2.16.0 on PyPI | none — must add |
| playwright (pkg) | INGEST-06 | ✗ | 1.61.0 on PyPI | none — must add |
| playwright chromium binary | INGEST-06 + crawl4ai | ✗ | via `playwright install` | none — must add to Dockerfile |
| protego | INGEST-09 (Playwright robots) | ✗ | 0.6.2 on PyPI | stdlib robotparser (loses Crawl-delay) |
| SearXNG (Docker service) | INGEST-07 | ✗ (not in compose) | `searxng/searxng` image | none — must add service + settings.yml |
| Postgres / MinIO / Qdrant | all | ✓ (compose) | Phase 1 | — |
| httpx / tenacity | probe, discovery, retries | ✓ (pinned) | 0.28.1 / 9.1.4 | — |

**Missing dependencies with no fallback:** crawl4ai, scrapy, playwright + chromium binary, SearXNG service — all are core to phase requirements and must be installed/wired. The planner must include install + compose/Dockerfile tasks before crawl tasks.
**Missing dependencies with fallback:** protego (stdlib fallback exists but degrades D-12 tier 2 — recommend installing protego).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio (auto mode) `[VERIFIED: pyproject.toml]` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`asyncio_mode = "auto"`, `testpaths=["tests"]`) |
| Quick run command | `uv run pytest tests/unit -x -q` |
| Full suite command | `uv run pytest -q` |
| Property testing | `hypothesis` — NOT installed; recommend adding to dev group for URL-normalization laws (Wave 0) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INGEST-01 | Register source via CLI+API; provenance recorded | integration | `uv run pytest tests/integration/test_source_register.py -x` | ❌ Wave 0 |
| INGEST-02 | Single-URL download records SHA256/MIME/URL/ts/license | integration | `pytest tests/integration/test_ingest_url_dedup.py -x` | ❌ Wave 0 |
| INGEST-03 | File upload records same provenance | unit+integration | `pytest tests/integration/test_upload.py -x` | ❌ Wave 0 |
| INGEST-04 | Crawl4AI yields raw+bronze artifacts with lineage | integration (mock/vcr HTML) | `pytest tests/integration/test_crawl4ai_adapter.py -x` | ❌ Wave 0 |
| INGEST-05 | Scrapy subprocess crawl produces results, no ReactorNotRestartable on 2nd run | integration | `pytest tests/integration/test_scrapy_subprocess.py -x` | ❌ Wave 0 |
| INGEST-06 | Playwright renders SPA fixture → markdown | integration | `pytest tests/integration/test_playwright_adapter.py -x` | ❌ Wave 0 |
| INGEST-07 | SearXNG discovery parses JSON → auto-registered sources | unit (mock httpx) + integration | `pytest tests/unit/test_discovery.py -x` | ❌ Wave 0 |
| INGEST-08 | Re-ingest identical URL/content → same IDs, no dup rows | unit+integration | `pytest tests/integration/test_dedup_noop.py -x` | ❌ Wave 0 |
| INGEST-09 | robots Disallow → robots_blocked; 3-tier delay resolves; retries fire | unit | `pytest tests/unit/test_robots_ratelimit.py -x` | ❌ Wave 0 |
| D-04 | Auto-selection picks correct adapter for HTML signals | unit (property/table) | `pytest tests/unit/test_crawler_select.py -x` | ❌ Wave 0 |
| D-06 | URL normalization is idempotent + preserves query order | property (hypothesis) | `pytest tests/unit/test_url_normalize.py -x` | ❌ Wave 0 |
| D-03 | Interrupted crawl resumes without re-fetching completed pages | integration | `pytest tests/integration/test_crawl_resume.py -x` | ❌ Wave 0 |

### Observable Truths (what "true" looks like)
- **Dedup no-op:** two `ingest_url(same_url)` calls → identical `source_id` + `artifact_id`; `SELECT count(*) FROM sources WHERE normalized_url=?` == 1.
- **Resume:** kill a crawl after N pages → `crawl_states` has N `complete` + M `pending`; re-run fetches only the M pending (assert completed URLs not re-requested — spy on the fetch layer).
- **robots_blocked:** crawl a fixture whose robots.txt disallows `/private/` → that URL's `crawl_states.status == 'robots_blocked'`; no raw/bronze artifact written for it.
- **Rate-limit precedence:** table test across all 4 tier permutations → resolver returns the expected delay.
- **Lineage (D-01):** bronze artifact's `parent_artifact_id` == its raw artifact's id; `klake lineage <bronze_id>` walks bronze → raw → source.
- **SSRF:** discovery/crawl of a private-IP URL is rejected before any fetch (assert `ValueError` / skipped state).

### Sampling Rate
- **Per task commit:** `uv run pytest tests/unit -x -q` (URL normalize, robots/ratelimit, select, discovery — all fast, no network).
- **Per wave merge:** `uv run pytest -q` (adds integration; crawler adapters use local HTML fixtures / mocked httpx, not live network).
- **Phase gate:** full suite green + a manual live smoke (`klake discover`, `klake crawl <small public site>`) before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/unit/test_url_normalize.py` — property tests (D-06). Requires `hypothesis` in dev deps.
- [ ] `tests/unit/test_robots_ratelimit.py` — 3-tier resolver + Protego robots parse (INGEST-09).
- [ ] `tests/unit/test_crawler_select.py` — auto-selection table tests (D-04).
- [ ] `tests/unit/test_discovery.py` — SearXNG JSON parsing with mocked httpx (INGEST-07).
- [ ] `tests/fixtures/` — add: a static HTML page, an SPA-shell HTML page, a `robots.txt` with Disallow + Crawl-delay, a sample SearXNG JSON response, a small sitemap.xml.
- [ ] `tests/integration/conftest.py` — fixtures to spawn/mocks for Scrapy subprocess + Playwright (or mark `@pytest.mark.browser` and skip when chromium absent).
- [ ] Dev-dep install: `uv add --dev hypothesis` (if property tests adopted).

## Security Domain

> `security_enforcement: true`, ASVS Level 1. This phase fetches attacker-influenceable URLs (crawled links + SearXNG results) and runs a headless browser — the highest-risk phase so far.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Single-user framework; SearXNG is an internal service, no auth surface added. |
| V3 Session Management | no | No sessions. |
| V4 Access Control | no | No multi-tenant/RBAC (out of scope per REQUIREMENTS). |
| V5 Input Validation | **yes** | Pydantic-validate all CLI/API inputs (URLs, query, collection); validate SearXNG JSON shape; regex-validate crawler/discovery swap keys. Reuse existing `_COLLECTION_NAME_RE` pattern. |
| V6 Cryptography | no (reuse) | SHA256 content hashing already via `hashlib`; no new crypto. |
| V7 Error Handling & Logging | yes | Never log credentials; log robots_blocked + SSRF rejections at INFO/WARN with URL (already the pattern). |
| V12 Files & Resources | **yes** | Size caps on downloads (exists: 50 MB), page timeouts for Playwright, cap max_pages/max_depth to bound resource use. |
| V13 API / SSRF | **yes (critical)** | Apply the SSRF validator to EVERY crawled/followed/discovered URL, not just `ingest_url`. |

### Known Threat Patterns for {crawler + discovery stack}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SSRF via crawled link / SearXNG result to IMDS or RFC-1918 | Information Disclosure / EoP | Refactor `_validate_url_scheme` into a shared `validate_public_url()`; call before every fetch + before auto-registering discovered sources; default same-domain scope. |
| robots.txt bypass (legal/compliance) | Repudiation / legal | Per-crawler robots enforcement (D-11); record `robots_blocked`; block crawl if robots.txt unreachable-and-policy-strict. |
| Decompression / oversized-response DoS | DoS | Existing 50 MB cap on downloads; enforce equivalent cap in crawler adapters; Playwright per-page timeout + block huge resources. |
| Headless browser exploitation on hostile page | EoP | Playwright: disable downloads, cap navigation timeout, no arbitrary JS eval from page content, run chromium sandboxed where possible, resource limits on the container. |
| SearXNG query injection / SSRF to internal SearXNG | Tampering | Treat `searxng_url` as trusted internal config only; pass `q` as a params value (httpx encodes it) — never string-format into the URL. |
| Redirect to private IP after public DNS (DNS rebinding) | Info Disclosure | Validate the resolved IP (getaddrinfo, as existing guard does) and re-validate on redirects (`follow_redirects` currently on in `_fetch_with_retry` — validate each hop or disable auto-redirect for crawled URLs). |
| Path/collection/param injection into Qdrant/S3 keys | Tampering | Reuse regex validation; content-addressed keys already prevent path traversal in storage. |

## Sources

### Primary (HIGH confidence)
- PyPI (`pip index versions`, 2026-07-03) — crawl4ai 0.9.0, scrapy 2.16.0, playwright 1.61.0, protego 0.6.2, tldextract 5.3.1 — version verification
- Existing codebase (read this session) — `pipeline/ingest.py`, `storage/s3.py`, `plugins/protocols.py`, `plugins/resolver.py`, `registry/models.py`, `registry/repo.py`, `dagster_defs/assets.py`, `docker-compose.yml`, `conftest.py`, `pyproject.toml` — integration points + reuse patterns
- https://docs.scrapy.org/en/latest/topics/practices.html + github.com/scrapy/scrapy#2941 — ReactorNotRestartable / subprocess pattern
- https://docs.searxng.org/dev/search_api.html — JSON API, `format=json`, 403-when-disabled

### Secondary (MEDIUM confidence)
- https://docs.crawl4ai.com/core/browser-crawler-config/ — `CrawlerRunConfig(check_robots_txt=True)`, `result.markdown`
- https://docs.crawl4ai.com/core/deep-crawling/ — BFS/DFS/Best-First deep crawl
- SPA-vs-static detection guidance (weweb.io, prerender.io, nuxtseo.com SPA-SEO guides) — auto-selection heuristics (synthesized, marked A1/A2)

### Tertiary (LOW confidence)
- SPA-detection threshold specifics (text length, script count, escalation cutoffs) — ASSUMED, must tune against real sites (A1/A2)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions verified on PyPI; all packages established with public repos.
- Architecture (protocol shape, subprocess Scrapy, two-artifact write, crawl_states/resume): HIGH — grounded in existing patterns + verified Twisted/SearXNG constraints.
- Auto-selection heuristics: MEDIUM/LOW — directionally sound, thresholds need real-site tuning (mitigated by escalation fallback + config override).
- Pitfalls: HIGH — ReactorNotRestartable, SSRF-scope gap, SearXNG-403, browser-binary, dedup-constraint all verified against source or docs.

**Research date:** 2026-07-03
**Valid until:** 2026-08-02 (30 days — crawl4ai iterates fast; re-verify its API and Playwright compat at plan time)
</content>
</invoke>
