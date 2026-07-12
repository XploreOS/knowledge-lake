---
phase: 08-crawl-maturation
plan: "06"
subsystem: crawl
tags: [crawl, api, cli, batch-crawl, schemas, CRAWL-02]
dependency_graph:
  requires:
    - 08-03 (crawl_all_sources() function in pipeline/crawl.py)
  provides:
    - src/knowledge_lake/api/schemas.py (CrawlAllRequest, CrawlAllSourceResult, CrawlAllOut)
    - src/knowledge_lake/api/app.py (POST /crawl-all endpoint)
    - src/knowledge_lake/cli/app.py (klake crawl-all command)
  affects: []
tech_stack:
  added: []
  patterns:
    - Thin shim pattern — CLI and API delegate directly to crawl_all_sources() with no business logic
    - Per-source result conversion from raw dict to CrawlAllSourceResult in endpoint handler
    - asyncio.run() in CLI mirrors cmd_crawl pattern exactly (D-07)
    - Optional domain query param via FastAPI Query() with description
key_files:
  created: []
  modified:
    - src/knowledge_lake/api/schemas.py
    - src/knowledge_lake/api/app.py
    - src/knowledge_lake/cli/app.py
decisions:
  - CrawlAllRequest domain field is Optional[str]=None consistent with D-08 query param pattern
  - crawl_all_endpoint is async def to mirror the create_crawl_job_endpoint async pattern (WR-001)
  - CrawlAllSourceResult pages_complete is Optional[int] to handle cases where crawl fails before page counting
  - Unexpected exceptions in crawl_all_endpoint raise HTTP 500 — crawl_all_sources handles per-source errors internally so this catch is a last-resort safety net
metrics:
  duration: "8m"
  completed_date: "2026-07-08"
  tasks_completed: 3
  files_changed: 3
status: complete
requirements:
  - CRAWL-02
---

# Phase 08 Plan 06: CRAWL-02 Surface Layer Summary

CRAWL-02 surface layer: CrawlAllRequest/CrawlAllOut/CrawlAllSourceResult schemas, POST /crawl-all endpoint, and klake crawl-all CLI command — thin shims over crawl_all_sources() from Plan 3.

## What Was Built

### Task 1: Add CrawlAllRequest, CrawlAllSourceResult, CrawlAllOut schemas (CRAWL-02 D-08/D-09)

**Added three Pydantic v2 models to `schemas.py`** immediately after `CrawlJobOut`:

- `CrawlAllRequest`: `domain: Optional[str] = None` — optional filter for batch crawl
- `CrawlAllSourceResult`: `source_id: str`, `status: str`, `error: Optional[str]`, `pages_complete: Optional[int]` — per-source result in the results list
- `CrawlAllOut`: `total: int`, `succeeded: int`, `failed: int`, `results: list[CrawlAllSourceResult]` — aggregate batch summary

**Verification:**
- `grep -c "CrawlAllRequest|CrawlAllOut|CrawlAllSourceResult" schemas.py` returns 5 (class definitions + imports from caller)
- Import test passes: `from knowledge_lake.api.schemas import CrawlAllRequest, CrawlAllOut, CrawlAllSourceResult`

### Task 2: Add POST /crawl-all API endpoint (CRAWL-02 D-08/D-09)

**Added `crawl_all_endpoint` to `api/app.py`** after `get_crawl_job_endpoint`:

- `@app.post("/crawl-all", response_model=CrawlAllOut, tags=["crawl"])` — consistent with POST /crawl-jobs naming (D-08)
- `async def crawl_all_endpoint(domain: Optional[str] = Query(None, ...))` — optional domain filter
- Lazy import of `crawl_all_sources` from `knowledge_lake.pipeline.crawl`
- Converts raw dict results to `CrawlAllSourceResult` objects
- Catches unexpected exceptions and raises `HTTPException(status_code=500)`
- Logs `api.crawl_all.start` with domain filter

**Verification:**
- Route assertion: `/crawl-all` in `[r.path for r in app.routes]` — PASSES
- `grep -c "crawl-all|crawl_all_endpoint" api/app.py` returns 2

### Task 3: Add klake crawl-all CLI command (CRAWL-02 D-07)

**Added `cmd_crawl_all` to `cli/app.py`** immediately after `cmd_crawl`:

- `@app.command(name="crawl-all")`
- `--domain`/`-d` option (Optional[str], default None) — mirrors `cmd_crawl` style
- Body: `asyncio.run(crawl_all_sources(domain=domain))` — exact same pattern as `cmd_crawl` (D-07)
- Prints summary: `Crawl-all complete:`, then `total:`, `succeeded:`, `failed:`
- Prints per-source rows with `source_id: status` and error if present
- `ValueError` caught and re-raised as `typer.Exit(code=1)`

**Verification:**
- `--help` includes "crawl-all" and "--domain"
- `grep -c "cmd_crawl_all|crawl-all" cli/app.py` returns 2

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | 43de414 | feat(08-06): add CrawlAllRequest, CrawlAllSourceResult, CrawlAllOut schemas (CRAWL-02 D-08/D-09) |
| Task 2 | 38245cd | feat(08-06): add POST /crawl-all API endpoint (CRAWL-02 D-08/D-09) |
| Task 3 | f6cce3f | feat(08-06): add klake crawl-all CLI command (CRAWL-02 D-07/D-09) |

## Verification Results

```
python -c "from knowledge_lake.api.app import app; routes = [r.path for r in app.routes]; assert '/crawl-all' in routes" → OK
python -m knowledge_lake.cli.app crawl-all --help → exits 0, shows --domain
grep -c "CrawlAllOut|CrawlAllRequest" src/knowledge_lake/api/schemas.py → 3
pytest tests/unit/ --ignore=tests/unit/test_crawl_all.py → 348 passed, 1 xfailed, 29 xpassed
```

The excluded `test_crawl_all.py` file contains the known-hanging test (`test_crawl_all_sources_returns_summary`) which attempts to crawl all 178 live sources without mocking — tracked as a deferred issue since Plan 3.

## Deviations from Plan

None — plan executed exactly as written. All three tasks implemented per specification with no auto-fixes required.

## Threat Surface Scan

**T-08-06-01 (DoS — sequential batch crawl):** Mitigated by sequential loop (D-06) with per-host adaptive backoff from Plan 2. No concurrency amplification.

**T-08-06-02 (Tampering — domain param):** Accepted. domain is a Python-side string equality filter in `list_sources_for_crawl_all`; no SQL injection via SQLAlchemy ORM.

**T-08-06-03 (Info Disclosure — error details):** Accepted. Error messages are internal pipeline exceptions consistent with existing `/crawl-jobs` error exposure.

## Known Stubs

None. All production paths fully wired.

## Self-Check: PASSED

- [x] `src/knowledge_lake/api/schemas.py` modified — CrawlAllRequest, CrawlAllSourceResult, CrawlAllOut added
- [x] `src/knowledge_lake/api/app.py` modified — POST /crawl-all endpoint added
- [x] `src/knowledge_lake/cli/app.py` modified — klake crawl-all command added
- [x] Commit 43de414 exists (Task 1)
- [x] Commit 38245cd exists (Task 2)
- [x] Commit f6cce3f exists (Task 3)
- [x] Route assertion passes: `/crawl-all` in app.routes
- [x] `--help` shows --domain option
- [x] 348 unit tests pass (excluding known-hanging crawl_all live-DB test)
