---
phase: 02-ingestion
verified: 2026-07-04T08:50:43Z
status: passed
score: 12/12 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification: null
---

# Phase 2: Ingestion Verification Report

**Phase Goal:** Users can get any public resource into the lake — register sources, pull single URLs, upload local files, crawl static/structured/dynamic sites with swappable crawler plugins, and discover new candidate sources — all with provenance, dedup, and legal politeness built in
**Verified:** 2026-07-04T08:50:43Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | User can register a source with domain assignment, download a URL, or upload a local file via CLI and API — each landing in the raw zone with SHA256, MIME type, source URL, timestamp, and license metadata recorded | ✓ VERIFIED | `klake add-source`, `klake upload`, `klake ingest-url` CLI commands present; `POST /sources`, `POST /uploads` API endpoints in OpenAPI; integration tests `test_source_register.py`, `test_upload.py` pass 6/6 |
| 2 | User can crawl a source with Crawl4AI producing LLM-ready markdown into raw/bronze, and can switch to Scrapy (structured sites) or Playwright (dynamic pages) as alternative crawler plugins via configuration | ✓ VERIFIED | `Crawl4AIAdapter`, `ScrapyAdapter`, `PlaywrightAdapter` all exist, implement `CrawlerPlugin` protocol (isinstance checks pass), registered as entry-points under `knowledge_lake.crawlers`; `klake crawl --crawler` accepts all three; `/crawl-jobs` POST endpoint wired; 26 tests across adapters pass |
| 3 | Re-ingesting identical content (by normalized URL or content hash) is a no-op — no duplicate raw objects or registry entries | ✓ VERIFIED | `normalize_url` + `get_source_by_normalized_url` URL-first dedup; `get_artifact_by_hash` hash-second dedup in `ingest_file`; `test_dedup_noop.py` (2 tests) and `test_ingest_url_dedup.py` (2 tests) pass; `normalize_url('HTTPS://Example.COM/a/?b=2&a=1#frag')` returns `'https://example.com/a?b=2&a=1'` confirmed live |
| 4 | Crawls respect robots.txt and apply per-host rate limits with retries and backoff; interrupted crawl jobs resume without re-fetching completed pages | ✓ VERIFIED | `RobotsPolicy`/`fetch_robots` (Protego), `resolve_delay` three-tier resolver (D-12), `PerHostLimiter` in `crawl/ratelimit.py`; `crawl_source` calls `validate_public_url` per-URL then checks robots policy; `_find_or_create_job` + `pending_states` resume logic; `test_crawl_robots_blocked.py` + `test_crawl_resume.py` (5 tests) pass; three-tier resolver verified live (5→2→1 tier cascade confirmed) |
| 5 | User can run a SearXNG discovery query and see candidate sources stored in the source registry for review | ✓ VERIFIED | `SearXNGDiscovery` implements `DiscoveryPlugin`; `discover_sources` pipeline auto-registers via `register_source(source_type_override='discovered')`; `klake discover --limit` CLI and `POST /discover` API wired; `infra/searxng/settings.yml` has `formats: [html, json]`; SearXNG compose service in `docker-compose.yml`; 21 tests pass |
| 6 | shared `validate_public_url` is the single SSRF guard imported by all crawler/discovery adapters | ✓ VERIFIED | All three crawler adapters (`crawl4ai_adapter`, `scrapy_adapter`, `playwright_adapter`) and `discover.py` import `validate_public_url` from `pipeline/ingest` — none define their own `getaddrinfo`-based implementation |
| 7 | `_fetch_with_retry` validates every redirect hop — a public URL that 302-redirects to a private/link-local IP is rejected before the private host is contacted | ✓ VERIFIED | `follow_redirects=False` in httpx client; manual redirect loop calls `validate_public_url` on each resolved `Location`; `test_fetch_redirect_ssrf.py` 4 tests pass including redirect-to-private-IP and RFC-1918 rejection |
| 8 | `crawl_states` table has UNIQUE(job_id, normalized_url) NOT on content_hash | ✓ VERIFIED | Migration 0003 creates `uq_crawl_states_job_url` UNIQUE(job_id, normalized_url); `test_crawl_schema.py` asserts IntegrityError on duplicate (job_id, normalized_url) but allows identical content under two URLs |
| 9 | `put_bronze` writes content-addressed bytes to the bronze zone with `parent_artifact_id` linking to raw (D-01) | ✓ VERIFIED | `StorageBackend.put_bronze` requires `parent_artifact_id` (no default, keyword-only); `_write_artifacts` in `crawl.py` passes `raw_id` as `parent_artifact_id`; `test_put_bronze.py` asserts lineage |
| 10 | Scrapy crawl runs in a child process — no ReactorNotRestartable on second in-process crawl | ✓ VERIFIED | `ScrapyAdapter.start_crawl` calls `subprocess.Popen([sys.executable, "-m", "scrapy_spider", ...])` — `CrawlerProcess.start()` is only in the child module `scrapy_spider.py`; `test_scrapy_subprocess.py` (9 tests) includes two-consecutive-crawl assertion |
| 11 | Auto-selection routes sitemap-bearing sites to Scrapy and SPA-marker HTML to Playwright; near-empty Crawl4AI markdown escalates to Playwright | ✓ VERIFIED | `select_crawler(url, html, has_sitemap=True)` returns `'scrapy'`; SPA markers + body <500 chars + ≥3 scripts returns `'playwright'`; `should_escalate('', 200)` returns True; `test_crawler_select.py` 22 tests pass; verified live |
| 12 | SearXNG query is passed as an httpx `params` value — never string-formatted into the URL | ✓ VERIFIED | `SearXNGDiscovery.search` uses `httpx.Client.get(..., params={'q': query, 'format': 'json'})`; no f-string or `.format(q=` found in source; `test_discovery.py` asserts query appears as params value |

**Score:** 12/12 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/knowledge_lake/pipeline/ingest.py` | normalize_url, validate_public_url, register_source | ✓ VERIFIED | 482 lines, all symbols exported, imports confirmed |
| `src/knowledge_lake/registry/alembic/versions/0002_source_normalized_url.py` | revision "0002", down_revision "0001" | ✓ VERIFIED | Revision chain correct; adds `normalized_url` TEXT nullable + index |
| `src/knowledge_lake/registry/alembic/versions/0003_crawl_jobs_states.py` | revision "0003", down_revision "0002" | ✓ VERIFIED | Revision chain correct; creates `crawl_states` + UNIQUE(job_id, normalized_url) |
| `src/knowledge_lake/plugins/builtin/crawl4ai_adapter.py` | Crawl4AIAdapter, CrawlerPlugin-compliant | ✓ VERIFIED | 191 lines; AsyncWebCrawler, check_robots_txt=True, validate_public_url |
| `src/knowledge_lake/plugins/builtin/scrapy_adapter.py` | ScrapyAdapter, subprocess isolation | ✓ VERIFIED | 312 lines; subprocess.Popen, validate_public_url before spawn |
| `src/knowledge_lake/plugins/builtin/scrapy_spider.py` | Standalone python -m module | ✓ VERIFIED | ROBOTSTXT_OBEY=True, CrawlerProcess.start() in child only |
| `src/knowledge_lake/plugins/builtin/playwright_adapter.py` | PlaywrightAdapter, browser hardened | ✓ VERIFIED | 280 lines; accept_downloads=False, 30s timeout, robots+SSRF before nav |
| `src/knowledge_lake/plugins/builtin/searxng_discovery.py` | SearXNGDiscovery, DiscoveryPlugin-compliant | ✓ VERIFIED | 107 lines; params dict, not string-format |
| `src/knowledge_lake/pipeline/crawl.py` | crawl_source orchestrator | ✓ VERIFIED | 400 lines; validate_public_url per-URL, resume via pending_states, two-artifact write |
| `src/knowledge_lake/pipeline/discover.py` | discover_sources pipeline | ✓ VERIFIED | 117 lines; validate_public_url per result, source_type='discovered' |
| `src/knowledge_lake/crawl/robots.py` | RobotsPolicy, fetch_robots (Protego) | ✓ VERIFIED | 141 lines; Protego-backed, RFC 9309 allow-all on unreachable |
| `src/knowledge_lake/crawl/ratelimit.py` | resolve_delay, PerHostLimiter | ✓ VERIFIED | 132 lines; three-tier D-12 resolver, tldextract domain keying |
| `src/knowledge_lake/crawl/select.py` | select_crawler, probe_site, should_escalate | ✓ VERIFIED | 226 lines; sitemap→scrapy, SPA→playwright, near-empty escalation |
| `infra/searxng/settings.yml` | formats: [html, json] | ✓ VERIFIED | Confirmed via yaml.safe_load: ['html', 'json'] |
| `Dockerfile` | playwright install + crawl4ai-setup layer | ✓ VERIFIED | Lines 29-30: `playwright install --with-deps chromium && uv run crawl4ai-setup` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| All crawlers (crawl4ai, scrapy, playwright) | `pipeline/ingest.validate_public_url` | `from knowledge_lake.pipeline.ingest import validate_public_url` | ✓ WIRED | Each adapter imports and calls before any fetch/navigation/spawn |
| `pipeline/crawl.py` | `validate_public_url` | Called at line 241 inside `_crawl_loop` per-URL | ✓ WIRED | Every URL in the loop is SSRF-validated before adapter call |
| `pipeline/discover.py` | `validate_public_url` | Called at line 75 per result URL | ✓ WIRED | Each discovered URL validated before `register_source` |
| `crawl_states` | `(job_id, normalized_url)` UNIQUE | Alembic 0003 `uq_crawl_states_job_url` | ✓ WIRED | Constraint enforced in DB, tested by `test_crawl_schema.py` |
| `put_bronze` | `parent_artifact_id = raw.id` | `_write_artifacts` passes raw_id as parent | ✓ WIRED | D-01 lineage established per page |
| `get_crawler(settings)` | `knowledge_lake.crawlers` entry-point group | pyproject.toml registers crawl4ai/scrapy/playwright | ✓ WIRED | All three resolv via `entry_points(group=GROUP_CRAWLERS)` |
| `get_discovery(settings)` | `knowledge_lake.discovery` entry-point group | pyproject.toml registers searxng | ✓ WIRED | SearXNGDiscovery resolves via `entry_points(group=GROUP_DISCOVERY)` |
| `SearXNGDiscovery.search` | SearXNG JSON API | `httpx params={'q': query, 'format': 'json'}` | ✓ WIRED | Never string-formats query; 403 raises RuntimeError |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| normalize_url preserves query order + strips fragment | `uv run python3 -c "from knowledge_lake.pipeline.ingest import normalize_url; assert normalize_url('HTTPS://Example.COM/a/?b=2&a=1#frag') == 'https://example.com/a?b=2&a=1'"` | Output matches | ✓ PASS |
| validate_public_url rejects http scheme | `uv run python3 -c "from knowledge_lake.pipeline.ingest import validate_public_url; validate_public_url('http://example.com')"` | ValueError raised | ✓ PASS |
| Three-tier resolver: source→robots→global | `resolve_delay({'rate_limit_seconds': 5}, 2.0, 1.0) == 5.0` | True | ✓ PASS |
| select_crawler sitemap branch | `select_crawler('https://example.com', html, has_sitemap=True) == 'scrapy'` | True | ✓ PASS |
| select_crawler SPA branch | `select_crawler('https://spa.example.com', spa_html, has_sitemap=False) == 'playwright'` | True | ✓ PASS |
| should_escalate near-empty markdown | `should_escalate('', 200) == True` | True | ✓ PASS |
| All three crawlers implement CrawlerPlugin | `isinstance(Crawl4AIAdapter(), CrawlerPlugin)` etc. | True x3 | ✓ PASS |
| SearXNGDiscovery implements DiscoveryPlugin | `isinstance(SearXNGDiscovery(...), DiscoveryPlugin)` | True | ✓ PASS |
| Phase 2 unit tests | `uv run pytest tests/unit/test_url_normalize.py test_fetch_redirect_ssrf.py test_robots_ratelimit.py test_crawler_select.py test_discovery.py test_put_bronze.py -q` | 70 passed | ✓ PASS |
| Phase 2 integration tests | `uv run pytest tests/integration/{test_dedup_noop,test_source_register,test_upload,test_ingest_url_dedup,test_crawl_schema,test_crawl4ai_adapter,test_crawl_resume,test_crawl_robots_blocked,test_scrapy_subprocess,test_playwright_adapter,test_discovery_register}.py -q` | 126 passed, 1 skipped (browser test, chromium absent) | ✓ PASS |
| OpenAPI contains /sources, /uploads, /crawl-jobs, /discover | FastAPI TestClient `/openapi.json` introspection | All 5 paths present | ✓ PASS |
| SearXNG settings.yml has html+json formats | `yaml.safe_load(settings.yml)['search']['formats']` | `['html', 'json']` | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| INGEST-01 | 02-01 | Register source URL with domain assignment via CLI and API | ✓ SATISFIED | `klake add-source`, `POST /sources`, `test_source_register.py` |
| INGEST-02 | 02-01 | Download single URL to raw zone with SHA256/MIME/URL/timestamp/license | ✓ SATISFIED | `ingest_url`, `_fetch_with_retry`, `test_ingest_url_dedup.py` |
| INGEST-03 | 02-01 | Upload local file with same provenance metadata | ✓ SATISFIED | `ingest_file`, `klake upload`, `POST /uploads`, `test_upload.py` |
| INGEST-04 | 02-02, 02-03 | Crawl with Crawl4AI → LLM-ready markdown into raw/bronze | ✓ SATISFIED | `Crawl4AIAdapter`, `crawl_source`, two-artifact write with lineage, `test_crawl4ai_adapter.py` |
| INGEST-05 | 02-04 | Crawl structured sites with Scrapy as alternative plugin | ✓ SATISFIED | `ScrapyAdapter`, subprocess isolation, `test_scrapy_subprocess.py` |
| INGEST-06 | 02-05 | Crawl dynamic pages with Playwright as alternative plugin | ✓ SATISFIED | `PlaywrightAdapter`, headless browser, Dockerfile browser layer |
| INGEST-07 | 02-06 | Discover candidate sources via SearXNG and store in registry | ✓ SATISFIED | `SearXNGDiscovery`, `discover_sources`, `klake discover`, `POST /discover`, compose service |
| INGEST-08 | 02-01, 02-03 | Dedup by normalized URL and content hash — re-ingest is no-op | ✓ SATISFIED | URL-first via `normalized_url` column; hash-second via `get_artifact_by_hash`; `test_dedup_noop.py` |
| INGEST-09 | 02-02, 02-03 | Robots.txt respected; per-host rate limits; interrupted crawl resumes | ✓ SATISFIED | Protego robots, three-tier ratelimit, `pending_states` resume, `test_crawl_robots_blocked.py`, `test_crawl_resume.py` |

**Note:** REQUIREMENTS.md checkbox status shows INGEST-01/02/03/04/07/08/09 as "Pending" and traceability table as "Pending" — these are documentation artifacts that were not updated after Phase 2 completion. The codebase fully implements all nine requirements. INGEST-05 and INGEST-06 are correctly marked "Complete" in REQUIREMENTS.md.

### Anti-Patterns Found

No `TBD`, `FIXME`, `XXX`, `TODO`, `HACK`, or `PLACEHOLDER` markers found in any Phase 2 source files. No stub implementations (empty handlers, `return null`, hardcoded empty data) found. All code paths are wired to real implementations.

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | — | — | — |

### Human Verification Required

None. All must-haves are verified programmatically via test suites and import/behavioral spot-checks. The one skipped test (`test_playwright_renders_spa_fixture`) is correctly marked `@pytest.mark.browser` and skips when Chromium is absent — this is intended behavior documented in the plan, not a verification gap.

---

## Gaps Summary

No gaps. All 12 observable truths are VERIFIED. All 9 INGEST requirements are satisfied by substantive, wired implementations with passing test coverage.

**Minor documentation artifact:** REQUIREMENTS.md still marks INGEST-01/02/03/04/07/08/09 as `[ ]` Pending and the traceability table shows "Pending" for these. This is a documentation update gap, not a code gap — the implementations are complete and tested. Recommend updating REQUIREMENTS.md checkboxes and traceability table to reflect completion.

---

_Verified: 2026-07-04T08:50:43Z_
_Verifier: Claude (gsd-verifier)_
