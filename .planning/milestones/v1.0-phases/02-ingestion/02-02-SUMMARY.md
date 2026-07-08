---
phase: 02-ingestion
plan: 02
subsystem: crawl-substrate
tags: [crawler, protocol, schema, bronze, robots, ratelimit]
dependency_graph:
  requires: [02-01]
  provides: [CrawlerPlugin, CrawlState, put_bronze, robots, ratelimit, crawl_settings]
  affects: [02-03, 02-04]
tech_stack:
  added: [protego, tldextract]
  patterns: [three-tier-resolver, content-addressed-bronze, per-host-limiter]
key_files:
  created:
    - src/knowledge_lake/crawl/__init__.py
    - src/knowledge_lake/crawl/robots.py
    - src/knowledge_lake/crawl/ratelimit.py
    - src/knowledge_lake/registry/alembic/versions/0003_crawl_jobs_states.py
    - tests/unit/test_robots_ratelimit.py
    - tests/unit/test_put_bronze.py
    - tests/integration/test_crawl_schema.py
  modified:
    - src/knowledge_lake/plugins/protocols.py
    - src/knowledge_lake/plugins/resolver.py
    - src/knowledge_lake/ids.py
    - src/knowledge_lake/config/settings.py
    - src/knowledge_lake/storage/s3.py
    - src/knowledge_lake/registry/models.py
    - src/knowledge_lake/registry/repo.py
    - pyproject.toml
decisions:
  - "UNIQUE(job_id, normalized_url) NOT content_hash for crawl_states (Pitfall 4, T-02-05)"
  - "Protego for robots parsing instead of hand-rolling (T-02-06)"
  - "tldextract for registrable-domain keying in per-host limiter (T-02-07)"
  - "ASVS V5 regex validator on all swap keys (T-02-08)"
  - "RFC 9309 Section 2.3: unreachable robots.txt treated as allow-all"
metrics:
  duration: "5m"
  completed: "2026-07-04T00:00:00Z"
  tasks_completed: 3
  tasks_total: 3
  tests_added: 29
status: complete
---

# Phase 02 Plan 02: Crawler Substrate Summary

Durable substrate for the crawler subsystem: CrawlerPlugin protocol, crawl-job/crawl_states schema, content-addressed bronze-zone writer with raw-to-bronze lineage, crawler resolver seam, and two politeness primitives (Protego-backed robots parsing + three-tier rate-limit resolver with per-host async limiter).

## Artifacts Produced

### Protocols & Dataclasses (src/knowledge_lake/plugins/protocols.py)
- `CrawlJob` — dataclass (job_id, source_url, crawler, status, config)
- `CrawlPageResult` — dataclass (url, status, html, markdown, error, fetched_at)
- `CrawlerPlugin` — runtime_checkable Protocol (name, start_crawl, poll_status, get_results)

### Resolver (src/knowledge_lake/plugins/resolver.py)
- `GROUP_CRAWLERS = "knowledge_lake.crawlers"` — entry-point group constant
- `get_crawler(settings)` — resolves settings.crawler via entry-point group

### ID Prefixes (src/knowledge_lake/ids.py)
- `crawl_job` -> `job` prefix
- `crawl_state` -> `cst` prefix
- `bronze_document` -> `doc` prefix

### Settings (src/knowledge_lake/config/settings.py)
- `CrawlSettings` — BaseModel (max_pages=50, max_depth=2, rate_limit_seconds=1.0, same_domain_only=True)
- `crawler` swap key (default "crawl4ai") on Settings
- `crawl` field (CrawlSettings) on Settings
- ASVS V5 regex validator on all swap keys (_SWAP_KEY_RE)

### Storage (src/knowledge_lake/storage/s3.py)
- `StorageBackend.put_bronze(source_id, data, ext, session, *, parent_artifact_id)` — content-addressed bronze zone writer with hash-second no-op and required parent linkage

### Models (src/knowledge_lake/registry/models.py)
- `Job` extended: source_id (FK), job_type (default "crawl"), crawler, config (_JSON), stats (_JSON), updated_at
- `CrawlState` — new model: id, job_id (FK RESTRICT), url, normalized_url, status, raw_artifact_id, bronze_artifact_id, fetched_at, created_at; UNIQUE(job_id, normalized_url)

### Repo (src/knowledge_lake/registry/repo.py)
- `create_bronze_artifact(session, *, source_id, content_hash, storage_uri, parent_artifact_id)` — bronze node with required parent
- `create_crawl_job(session, *, source_id, crawler, config, status)` — job record
- `upsert_crawl_state(session, *, job_id, url, normalized_url, status, ...)` — insert-or-update
- `pending_states(session, job_id)` — fetch pending crawl states for resume

### Migration (src/knowledge_lake/registry/alembic/versions/0003_crawl_jobs_states.py)
- Revision "0003", down_revision "0002"
- Extends jobs table (source_id, job_type, crawler, config, stats, updated_at)
- Creates crawl_states table with UNIQUE(job_id, normalized_url) + ix_crawl_states_job_status

### Crawl Package
- `src/knowledge_lake/crawl/__init__.py` — package init
- `src/knowledge_lake/crawl/robots.py` — RobotsPolicy (Protego), fetch_robots (tenacity retry, RFC 9309)
- `src/knowledge_lake/crawl/ratelimit.py` — resolve_delay (D-12 three-tier), _domain_key (tldextract), PerHostLimiter (async)

### Dependencies (pyproject.toml)
- `protego>=0.3.1` — Scrapy team's robots.txt parser
- `tldextract>=5.1.0` — registrable domain extraction

## Decisions Made

1. **UNIQUE on (job_id, normalized_url) not content_hash** — Pitfall 4 requires this so identical content under different URLs can exist as separate crawl state rows pointing at no-op'd artifacts.
2. **Protego over hand-rolled parser** — handles wildcards, $-terminated patterns, Crawl-delay, and agent precedence correctly (T-02-06).
3. **tldextract for domain keying** — ensures www.example.com and api.example.com share a single rate limiter (T-02-07).
4. **ASVS V5 regex on all swap keys** — prevents path traversal and injection via malicious entry-point names (T-02-08).
5. **RFC 9309 unreachable-robots policy** — if robots.txt is unreachable, treat as allow-all per the standard.

## Deviations from Plan

None - plan executed exactly as written.

## TDD Gate Compliance

Task 3 followed RED/GREEN/REFACTOR:
- RED: `362712e` — test(02-02): add failing tests for robots parsing and rate-limit resolver
- GREEN: `7da4db1` — feat(02-02): implement robots parsing and three-tier rate-limit resolver
- REFACTOR: not needed (code was already clean and minimal)

## Verification Results

- `uv run pytest tests/unit/test_robots_ratelimit.py tests/unit/test_put_bronze.py tests/integration/test_crawl_schema.py -q` — 29 passed
- `uv run pytest tests/unit/ tests/integration/test_crawl_schema.py -q` — 168 passed
- `uv run klake --help` — CLI operational, all existing commands listed
- Pre-existing test_lineage.py errors are unrelated (Dagster asset dependencies not available in test context)

## Known Stubs

None. All code paths are wired to real implementations or clear no-op guards.

## Threat Flags

None. All new surfaces are covered by the plan's threat model (T-02-05 through T-02-08).

## Self-Check: PASSED

All created files exist, all modified files exist, all commits verified, SUMMARY.md present.
