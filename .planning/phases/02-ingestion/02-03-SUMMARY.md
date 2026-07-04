---
phase: 02-ingestion
plan: 03
subsystem: crawl-vertical-slice
tags: [crawl4ai, crawler, pipeline, cli, api, resume, robots, lineage]
dependency_graph:
  requires: [02-02]
  provides: [Crawl4AIAdapter, crawl_source, select_crawler, crawl_cli, crawl_api]
  affects: [02-04, 02-05]
tech_stack:
  added: [crawl4ai]
  patterns: [two-artifact-per-page, resume-from-pending, find-or-create-job]
key_files:
  created:
    - src/knowledge_lake/plugins/builtin/crawl4ai_adapter.py
    - src/knowledge_lake/pipeline/crawl.py
    - src/knowledge_lake/crawl/select.py
    - tests/integration/test_crawl4ai_adapter.py
    - tests/integration/test_crawl_resume.py
    - tests/integration/test_crawl_robots_blocked.py
  modified:
    - src/knowledge_lake/cli/app.py
    - src/knowledge_lake/api/app.py
    - src/knowledge_lake/api/schemas.py
    - pyproject.toml
decisions:
  - "Crawl4AI adapter uses in-process async pattern with page-level fetch_page method"
  - "Resume via _find_or_create_job: reuse existing incomplete job for same source"
  - "Robots check dual-layer: local Protego policy + Crawl4AI native check_robots_txt=True"
  - "Dagster crawl-asset deferred to Phase 6 / IFACE-03 (recorded, not dropped)"
metrics:
  duration: "8m"
  completed: "2026-07-04T04:43:00Z"
  tasks_completed: 3
  tasks_total: 3
  tests_added: 16
status: complete
---

# Phase 02 Plan 03: Crawl Vertical Slice Summary

Crawl4AI adapter with SSRF guard and native robots, crawl orchestrator writing two-artifact-per-page lineage (raw HTML + bronze markdown), durable resume from pending crawl_states, per-host rate limiting, and klake crawl CLI + /crawl-jobs REST API.

## Artifacts Produced

### Crawl4AIAdapter (src/knowledge_lake/plugins/builtin/crawl4ai_adapter.py)
- `Crawl4AIAdapter` — CrawlerPlugin implementation (name="crawl4ai")
- `fetch_page(url)` — async page fetch with SSRF guard, robots detection, 50 MB cap
- `fetch_page_sync(url)` — sync wrapper for non-async contexts
- Protocol methods: start_crawl, poll_status, get_results (for protocol compliance)
- Entry-point registered: `[knowledge_lake.crawlers] crawl4ai`

### Crawl Orchestrator (src/knowledge_lake/pipeline/crawl.py)
- `crawl_source(source_url, *, crawler, settings, max_pages)` — main entry point
- `_find_or_create_job(source_id, crawler, max_pages, source_url)` — resume-aware job resolution
- `_get_urls_to_process(job_id, seed_url, max_pages)` — pending-state resume logic
- `_crawl_loop(...)` — async crawl with SSRF revalidation, rate limiting, robots check
- `_write_artifacts(source_id, url, html, markdown, storage)` — two-artifact write with lineage
- `_record_state(job_id, url, status, ...)` — crawl_states upsert

### Crawler Selector (src/knowledge_lake/crawl/select.py)
- `select_crawler(url, html, has_sitemap)` — default "crawl4ai" with escalation hook stub

### CLI (src/knowledge_lake/cli/app.py)
- `klake crawl <url> [--crawler] [--max-pages]` — starts crawl, prints job_id + page counts

### API (src/knowledge_lake/api/app.py)
- `POST /crawl-jobs` — CrawlJobCreate body, returns CrawlJobOut (201)
- `GET /crawl-jobs/{job_id}` — returns job status + state counts (404 for unknown)

### Schemas (src/knowledge_lake/api/schemas.py)
- `CrawlJobCreate` — source_url, optional crawler/max_pages with pydantic validation
- `CrawlJobOut` — job_id, source_id, crawler, status, states
- `CrawlStateOut` — complete/robots_blocked/failed/pending counts

### Dependencies (pyproject.toml)
- `crawl4ai==0.9.0` — primary web crawler
- Entry-point: `[knowledge_lake.crawlers] crawl4ai`

## Decisions Made

1. **In-process async fetch pattern** — Crawl4AIAdapter exposes `fetch_page(url)` for per-page orchestrator iteration rather than batch crawl. This gives the orchestrator full control over rate limiting, SSRF validation, and artifact writes per page.
2. **Resume via _find_or_create_job** — On re-run, the orchestrator looks for an existing incomplete job for the same source/crawler before creating a new one. pending_states query returns only URLs not yet processed.
3. **Dual-layer robots check** — The orchestrator checks the local Protego policy AND the adapter uses check_robots_txt=True. This ensures robots are respected even if the adapter's native check has edge cases.
4. **Dagster deferral** — Crawl is implemented as plain functions. A thin Dagster asset/sensor is deferred to Phase 6 / IFACE-03 per RESEARCH Open Question #3.

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

- `uv run pytest tests/integration/test_crawl4ai_adapter.py -q` — 11 passed
- `uv run pytest tests/integration/test_crawl_resume.py tests/integration/test_crawl_robots_blocked.py -q` — 5 passed
- `uv run klake crawl --help` — exits 0, lists --crawler and --max-pages
- OpenAPI contains `/crawl-jobs` (POST) and `/crawl-jobs/{job_id}` (GET)
- Full test suite: 184 passed (unit + integration)

## Known Stubs

None. All code paths are wired to real implementations. The `select_crawler` escalation hook is a documented future extension point (02-05), not a stub affecting current functionality.

## Threat Flags

None. All new surfaces are covered by the plan's threat model (T-02-09 through T-02-13).

## Self-Check: PASSED
