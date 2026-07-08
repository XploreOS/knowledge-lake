---
phase: 02-ingestion
plan: "04"
subsystem: crawl
tags: [scrapy, crawler, subprocess, auto-selection, sitemap, INGEST-05, D-04]
requires: [02-03]
provides: [ScrapyAdapter, scrapy_spider, probe_site, select_crawler-sitemap-branch]
affects: [pipeline/crawl.py, cli/app.py, api/app.py, plugins/resolver.py]
tech_stack:
  added: [scrapy==2.16.0]
  patterns: [subprocess-isolation, TDD-red-green, entry-point-registration, SSRF-guard, JSONL-IPC]
key_files:
  created:
    - src/knowledge_lake/plugins/builtin/scrapy_spider.py
    - src/knowledge_lake/plugins/builtin/scrapy_adapter.py
    - tests/unit/test_crawler_select.py
    - tests/integration/test_scrapy_subprocess.py
  modified:
    - src/knowledge_lake/crawl/select.py
    - pyproject.toml
decisions:
  - "Subprocess isolation for Scrapy: each crawl job spawns `python -m scrapy_spider` child process; Twisted reactor lives and dies with the child — no ReactorNotRestartable"
  - "JSONL IPC: child writes one JSON object per page with base64-encoded HTML; parent parses after child exits"
  - "TDD red-green for auto-selection: test file committed before implementation"
  - "SPA detection heuristic: SPA markers + body text <500 chars + ≥3 script tags (all three required)"
  - "sitemap branch short-circuits over all other signals: has_sitemap=True always returns scrapy"
metrics:
  duration: "6m"
  completed: "2026-07-04"
  tasks: 3
  files_changed: 6
status: complete
---

# Phase 02 Plan 04: Scrapy Crawler Adapter + Auto-Selection Summary

Scrapy adapter running each crawl in a subprocess (no ReactorNotRestartable), auto-selection probe routing sitemap-bearing sites to Scrapy, and integration tests proving two consecutive crawls in one process both succeed.

## Objective

Add Scrapy as a config-swappable crawler plugin via subprocess isolation, fill in the sitemap branch of D-04 auto-selection, and wire `--crawler scrapy` through CLI and API.

## Artifacts Produced

### ScrapyAdapter (`src/knowledge_lake/plugins/builtin/scrapy_adapter.py`)
- Implements `CrawlerPlugin` protocol (`start_crawl`, `poll_status`, `get_results`)
- `start_crawl`: validates URL with SSRF guard, writes config.json to temp dir, spawns `subprocess.Popen([sys.executable, "-m", "scrapy_spider", url, out.jsonl, config.json])`
- `poll_status`: maps `proc.poll()` — None→running, 0→complete, else→failed
- `get_results`: parses completed JSONL lines (base64-decoded HTML) into `CrawlPageResult`
- Never calls `CrawlerProcess.start()` in-process (T-02-14 compliance)
- Registered as `[knowledge_lake.crawlers] scrapy = ScrapyAdapter` entry-point

### scrapy_spider child module (`src/knowledge_lake/plugins/builtin/scrapy_spider.py`)
- Standalone `python -m` entry (reads argv: source_url, out_jsonl, config_json)
- Calls `validate_public_url` on source_url before starting reactor (T-02-15)
- `SSRFGuardMiddleware` Scrapy downloader middleware re-validates every followed URL
- Settings: `ROBOTSTXT_OBEY=True` (T-02-16), `DOWNLOAD_MAXSIZE=50MB` (T-02-17), `AUTOTHROTTLE_ENABLED=True`, same-domain link scoping
- Writes one JSONL object per page (url, status, html_b64, markdown, error)
- Reactor lives and dies with this child process

### Auto-selection probe (`src/knowledge_lake/crawl/select.py`)
- `select_crawler(url, html, has_sitemap)`: three-tier priority routing
  1. `has_sitemap=True` → "scrapy" (sitemap wins, structured enumerable site)
  2. SPA markers (\_\_NEXT_DATA\_\_, \_\_NUXT\_\_, ng-version, data-reactroot, id=root/app) + body <500 chars + ≥3 scripts → "playwright" (02-05 reserved)
  3. default → "crawl4ai"
- `probe_site(url)`: SSRF-guarded httpx probe; fetches entry URL + /robots.txt (Sitemap: directive check) + /sitemap.xml (200 check); returns (html, has_sitemap)

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | Scrapy subprocess spider + adapter | 712fe55 | scrapy_adapter.py, scrapy_spider.py, pyproject.toml |
| 2 (RED) | Failing tests for select_crawler + probe_site | 29948a8 | tests/unit/test_crawler_select.py |
| 2 (GREEN) | Auto-selection sitemap branch + probe_site | 46ae224 | crawl/select.py |
| 3 | Integration test: subprocess isolation + CLI/API wiring | a0b5374 | tests/integration/test_scrapy_subprocess.py |

## Test Coverage

- `tests/unit/test_crawler_select.py`: 12 tests — table-driven select_crawler routing + mocked probe_site
- `tests/integration/test_scrapy_subprocess.py`: 9 tests — subprocess lifecycle, two-run isolation, JSONL parsing, protocol compliance, SSRF guard

## Security Posture (Threat Register)

| Threat | Mitigation | Status |
|--------|-----------|--------|
| T-02-14 DoS/crash ReactorNotRestartable | subprocess.Popen — reactor dies with child | Mitigated |
| T-02-15 SSRF via followed link | validate_public_url in adapter + SSRFGuardMiddleware in spider | Mitigated |
| T-02-16 robots bypass | ROBOTSTXT_OBEY=True + robots_blocked recorded in results | Mitigated |
| T-02-17 DoS (oversized response) | DOWNLOAD_MAXSIZE=50MB + AUTOTHROTTLE + per-host delay | Mitigated |

## Deviations from Plan

None — plan executed exactly as written. The JSONL IPC uses base64 for HTML (binary-safe transport over text JSONL), which is consistent with the plan's architecture note ("html_path/md").

## TDD Gate Compliance

Task 2 followed RED/GREEN/REFACTOR:
- RED commit: 29948a8 (test file with 12 failing tests — probe_site missing, select_crawler lacks branches)
- GREEN commit: 46ae224 (implementation; all 12 tests pass)
- REFACTOR: not needed (implementation was clean)

## Self-Check: PASSED

Files created/modified verified present:
- src/knowledge_lake/plugins/builtin/scrapy_adapter.py ✓
- src/knowledge_lake/plugins/builtin/scrapy_spider.py ✓
- src/knowledge_lake/crawl/select.py ✓
- tests/unit/test_crawler_select.py ✓
- tests/integration/test_scrapy_subprocess.py ✓

Commits verified: 712fe55, 29948a8, 46ae224, a0b5374 all present in git log.
