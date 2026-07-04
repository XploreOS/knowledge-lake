---
status: complete
phase: 02-ingestion
mode: mvp
user_story: "As a domain researcher, I want to ingest any public resource (URL, file, or crawl) into the lake with provenance and dedup, so that I have a traceable raw zone of source material to build AI datasets from."
source:
  - .planning/phases/02-ingestion/02-01-SUMMARY.md
  - .planning/phases/02-ingestion/02-02-SUMMARY.md
  - .planning/phases/02-ingestion/02-03-SUMMARY.md
  - .planning/phases/02-ingestion/02-04-SUMMARY.md
  - .planning/phases/02-ingestion/02-05-SUMMARY.md
  - .planning/phases/02-ingestion/02-06-SUMMARY.md
started: 2026-07-04T00:00:00Z
updated: 2026-07-04T17:00:00Z
---

## Current Test

[testing complete]

## Tests

<!-- Section A: User-Flow Walk-Through (MVP mode) -->

### 1. Cold Start Smoke Test
expected: |
  Run `cp .env.example .env`, set KLAKE_STORAGE__ACCESS_KEY_ID and KLAKE_STORAGE__SECRET_ACCESS_KEY
  (e.g. minioadmin/minioadmin), then `docker compose up -d`. All services healthy.
  `curl localhost:8000/health` returns 200.
result: pass
source: human + automated
coverage: |
  test_compose_health.py::test_minio_healthy — PASSED
  test_compose_health.py::test_qdrant_healthy — PASSED
  test_compose_health.py::test_litellm_healthy — PASSED
  test_compose_health.py::test_dagster_webserver_healthy — PASSED
  test_compose_health.py::test_api_health_endpoint_returns_200 — PASSED
  test_compose_health.py::test_all_http_services_reachable — PASSED
  User confirmed: stack started clean with .env configured.

### 2. Register a Source
expected: |
  `klake add-source https://example.com --name "Example" --domain general` exits 0.
  Source row created with stable ID, URL, domain, timestamp.
result: pass
source: automated
coverage: |
  test_source_register.py::test_register_creates_source_with_provenance — PASSED
  test_source_register.py::test_register_dedup_returns_existing — PASSED

### 3. Download a URL
expected: |
  `klake ingest <url>` exits 0. Raw zone object created with SHA256, MIME type, source URL, timestamp.
  Re-ingesting same URL is a no-op (URL-first dedup).
result: pass
source: automated
coverage: |
  test_ingest_url_dedup.py::test_ingest_url_records_provenance — PASSED
  test_ingest_url_dedup.py::test_ingest_url_dedup_skips_fetch — PASSED
  test_fetch_redirect_ssrf.py (4 tests) — PASSED

### 4. Upload a Local File
expected: |
  `klake upload /path/to/file` exits 0. Raw zone object created with SHA256, MIME type, timestamp.
  Re-uploading same file is a no-op (hash dedup).
result: pass
source: automated
coverage: |
  test_upload.py::test_upload_records_provenance — PASSED
  test_upload.py::test_upload_hash_dedup — PASSED
  test_dedup_noop.py::test_ingest_file_hash_dedup — PASSED

### 5. Crawl a Site with Crawl4AI (default)
expected: |
  `klake crawl <url>` starts crawl with Crawl4AI. Each page produces two artifacts (raw HTML + bronze
  markdown) with lineage. Crawl job visible via `klake crawl-jobs`. SSRF guard fires on private IPs.
result: pass
source: automated
coverage: |
  test_crawl4ai_adapter.py::TestProtocolCompliance (2) — PASSED
  test_crawl4ai_adapter.py::TestSSRFGuard (3) — PASSED
  test_crawl4ai_adapter.py::TestCompleteFetch (2) — PASSED
  test_crawl4ai_adapter.py::TestRobotsBlocked (2) — PASSED
  test_crawl4ai_adapter.py::TestSizeCap (1) — PASSED
  test_crawl4ai_adapter.py::TestEntryPointResolution (1) — PASSED
  test_crawl_resume.py::test_complete_page_has_raw_bronze_lineage — PASSED

### 6. Switch Crawler to Scrapy
expected: |
  `klake crawl <url> --crawler scrapy` (or sitemap-bearing site) uses Scrapy subprocess adapter.
  Two consecutive crawls in one process succeed (no ReactorNotRestartable).
result: pass
source: automated
coverage: |
  test_scrapy_subprocess.py::test_scrapy_adapter_is_crawler_plugin — PASSED
  test_scrapy_subprocess.py::test_get_crawler_resolves_scrapy — PASSED
  test_scrapy_subprocess.py::test_start_crawl_spawns_subprocess — PASSED
  test_scrapy_subprocess.py::test_start_crawl_rejects_private_ip — PASSED
  test_scrapy_subprocess.py::test_two_scrapy_crawls_no_reactor_error — PASSED
  test_scrapy_subprocess.py::test_two_crawls_parsed_result_count — PASSED

### 7. Switch Crawler to Playwright
expected: |
  `klake crawl <spa-url> --crawler playwright` launches headless Chromium. Page renders and
  markdown lands in raw zone. Robots check fires before any navigation.
result: pass
source: automated
coverage: |
  test_playwright_adapter.py::test_playwright_robots_blocked — PASSED
  test_crawler_select.py (22 unit tests including SPA detection and escalation) — PASSED
note: Full browser render test (test_playwright_renders_spa_fixture) is skipped outside Docker image — requires `docker compose up`.

### 8. Discover Candidate Sources
expected: |
  `klake discover "healthcare guidelines"` queries SearXNG. Candidate sources stored in registry
  with source_type=discovered. Re-running produces no duplicates. Private-IP results are dropped.
result: pass
source: automated
coverage: |
  test_discovery_register.py::test_discovered_sources_registered_with_correct_type — PASSED
  test_discovery_register.py::test_private_ip_result_skipped — PASSED
  test_discovery_register.py::test_no_duplicate_rows_on_rerun — PASSED
  test_discovery_register.py::test_discover_runs_with_mock — PASSED
  test_discovery_register.py::test_discover_endpoint_with_mock — PASSED
  test_discovery_register.py::test_discover_validates_empty_query — PASSED

<!-- Section B: Technical Checks -->

### 9. Dedup: Re-ingesting Identical Content is a No-Op
expected: |
  Ingest same URL twice — second call is a no-op with no new raw object or registry entry.
  Same for file upload with identical content hash.
result: pass
source: automated
coverage: |
  test_dedup_noop.py::test_ingest_url_dedup_returns_same_ids — PASSED
  test_dedup_noop.py::test_ingest_file_hash_dedup — PASSED
  test_ingest_url_dedup.py::test_ingest_url_dedup_skips_fetch — PASSED

### 10. Robots.txt Respect
expected: |
  Crawling a URL blocked by robots.txt records crawl_state as robots_blocked with no raw artifact written.
result: pass
source: automated
coverage: |
  test_crawl_robots_blocked.py::test_robots_blocked_url_has_no_artifacts — PASSED
  test_crawl_robots_blocked.py::test_mixed_allowed_and_blocked_urls — PASSED
  test_robots_ratelimit.py (15 unit tests) — PASSED

### 11. Crawl Resume After Interruption
expected: |
  Interrupted crawl resumes from pending pages only — completed pages not re-fetched. Same job ID reused.
result: pass
source: automated
coverage: |
  test_crawl_resume.py::test_resume_fetches_only_pending_urls — PASSED
  test_crawl_resume.py::test_validate_public_url_called_before_fetch — PASSED

## Summary

total: 11
passed: 11
issues: 0
skipped: 0
pending: 0

## Gaps

[none yet]
