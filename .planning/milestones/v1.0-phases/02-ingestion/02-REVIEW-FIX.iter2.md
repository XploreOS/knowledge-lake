---
phase: "02"
phase_name: "ingestion"
status: "all_fixed"
iteration: 2
findings_in_scope: 12
fixed: 12
skipped: 0
---

# Code Review Fix Report: Phase 02 — ingestion

## Summary

All 5 critical and 7 warning findings from the iteration 2 review were fixed. The fixes address non-functional integration tests (unawaited coroutines, wrong mock layer), concurrent-write safety (IntegrityError handling in storage and registry), a new Alembic migration for UNIQUE constraints on sources and jobs, event-loop blocking remediation, and miscellaneous code correctness issues.

## Fixes Applied

### CR-001 · Fixed — `crawl_source` called without `await` in integration tests

**Files:** `tests/integration/test_crawl_resume.py`, `tests/integration/test_crawl_robots_blocked.py`
**Fix:** Wrapped all three `crawl_source(...)` calls in `test_crawl_resume.py` with `asyncio.run(...)` (lines 186, 303, 399). Added `import asyncio` to `test_crawl_robots_blocked.py` and wrapped both `crawl_source(...)` calls there with `asyncio.run(...)`. All test bodies now actually execute the crawl logic instead of returning an unawaited coroutine object.
**Commit:** `fix(02): CR-001 add asyncio.run() wrappers around crawl_source calls in integration tests`

---

### CR-002 · Fixed — `probe_site` tests mock `httpx` at the wrong layer: live network calls

**File:** `tests/unit/test_crawler_select.py`
**Fix:** Replaced `@patch("knowledge_lake.crawl.select.httpx")` with `@patch("knowledge_lake.crawl.select.httpx.Client")` on all four probe_site tests. Added a `_make_mock_client()` helper that builds a proper context-manager mock (with `__enter__`/`__exit__`) and sets `client.get.side_effect` to the response sequence. Updated each test to set `mock_client_cls.return_value = _make_mock_client([...])`. The `test_raises_on_private_ip` test had its unused `mock_httpx` parameter removed since SSRF validation fires before any `httpx.Client` is constructed.
**Commit:** `fix(02): CR-002 patch httpx.Client constructor instead of httpx module-level in probe_site tests`

---

### CR-003 · Fixed — TOCTOU race in `put_raw`/`put_bronze`: concurrent writes can corrupt the raw zone

**File:** `src/knowledge_lake/storage/s3.py`
**Fix:** Added `from sqlalchemy.exc import IntegrityError` import. Wrapped the `repo.create_raw_artifact(...)` call in `put_raw` in a `try/except IntegrityError` block — on conflict, rolls back the session and calls `get_artifact_by_hash` to return the winning writer's artifact. Applied the identical pattern to `put_bronze` using `create_bronze_artifact` / `get_artifact_by_hash(..., "bronze_document")`. Both methods now handle concurrent writes safely using the existing `uq_artifacts_hash_type` constraint.
**Commit:** `fix(02): CR-003 catch IntegrityError in put_raw/put_bronze to handle concurrent writes safely`

---

### CR-004 · Fixed — `_find_or_create_job` uses two separate sessions: duplicate job creation race

**Files:** `src/knowledge_lake/pipeline/crawl.py`, `src/knowledge_lake/registry/alembic/versions/0005_unique_sources_normalized_url.py`
**Fix:** Collapsed the two-session lookup+insert in `_find_or_create_job` into a single `with get_session()` block. The insert now catches `IntegrityError` and re-queries the session for the winning concurrent job. Created migration `0005` which (1) drops the plain `ix_sources_normalized_url` index and promotes it to a `UNIQUE` constraint (`uq_sources_normalized_url`) fixing WR-005 as well, and (2) adds a partial UNIQUE index `uq_jobs_source_crawler_active` on `(source_id, crawler) WHERE status IN ('running', 'pending')` — this makes the duplicate-job insert an IntegrityError rather than a silent duplicate row.
**Commit:** `fix(02): CR-004 consolidate _find_or_create_job into single session and add partial UNIQUE index migration`

---

### CR-005 · Fixed — Scrapy subprocess integration test reads wrong argv index with misleading comment

**File:** `tests/integration/test_scrapy_subprocess.py`
**Fix:** Added named index constants at the top of `test_two_scrapy_crawls_no_reactor_error`: `_PYTHON_IDX, _DASH_M_IDX, _MODULE_IDX, _URL_IDX, _JSONL_IDX, _CONFIG_IDX = range(6)`. Replaced the magic `cmd[4]` in `fake_popen` with `cmd[_JSONL_IDX]` and updated the inline comment to show the correct cmd layout. Also fixed the same bare `cmd[4]` in `test_two_crawls_parsed_result_count` with a local `_JSONL_IDX = 4` constant and a descriptive comment.
**Commit:** `fix(02): CR-005 replace magic cmd indices with named constants and fix misleading argv comment`

---

### WR-001 · Fixed — `max_pages=0` silently ignored due to falsy `or` check

**File:** `src/knowledge_lake/pipeline/crawl.py`
**Fix:** Changed `effective_max_pages = max_pages or s.crawl.max_pages` to `effective_max_pages = max_pages if max_pages is not None else s.crawl.max_pages`. `0` is now a valid caller-supplied value that is respected instead of falling through to the global default.
**Commit:** `fix(02): WR-001 use 'is not None' check for max_pages to allow max_pages=0`

---

### WR-002 · Fixed — Cross-domain skip inflates `pages_total` making stats inconsistent

**File:** `src/knowledge_lake/pipeline/crawl.py`
**Fix:** Added `pages_total -= 1` immediately before `continue` on the cross-domain skip path in `_crawl_loop`. This undoes the pre-loop increment so `pages_total` accounts only for URLs that were actually processed, keeping `pages_total == pages_complete + pages_robots_blocked + pages_failed`.
**Commit:** `fix(02): WR-002 decrement pages_total on cross-domain skip to keep stats consistent`

---

### WR-003 · Fixed — `_fetch_with_retry` may raise secondary exception masking original on mid-stream timeout

**File:** `src/knowledge_lake/pipeline/ingest.py`
**Fix:** Wrapped the `resp.close()` call in the existing `finally` block in a bare `try/except Exception: pass`. A `RuntimeError` or `RemoteProtocolError` raised while closing a partially-read streaming response can no longer replace the original `TimeoutException` in the exception chain, ensuring tenacity's retry filter fires correctly on mid-stream timeouts.
**Commit:** `fix(02): WR-003 wrap resp.close() in try/except to prevent secondary exception masking original`

---

### WR-004 · Fixed — `fetch_robots` is synchronous but called from async coroutines

**Files:** `src/knowledge_lake/pipeline/crawl.py`, `src/knowledge_lake/plugins/builtin/playwright_adapter.py`
**Fix:** In `crawl_source`, replaced `robots_policy = fetch_robots(base_url)` with `robots_policy = await asyncio.get_event_loop().run_in_executor(None, fetch_robots, base_url)`. Applied the same pattern in `PlaywrightAdapter.fetch_page`. The blocking `httpx.Client` HTTP call is now offloaded to the default thread pool executor so the event loop is not stalled for up to 30 seconds during robots.txt fetches.
**Commit:** `fix(02): WR-004 offload blocking fetch_robots to thread executor in async crawl coroutines`

---

### WR-005 · Fixed — Missing UNIQUE constraint on `sources.normalized_url` allows duplicate sources under concurrency

**Files:** `src/knowledge_lake/pipeline/ingest.py`, `src/knowledge_lake/registry/alembic/versions/0005_unique_sources_normalized_url.py`
**Fix:** The UNIQUE constraint is added in migration 0005 (committed under CR-004 above — both fixes share the same migration file). In `ingest.py`, added `from sqlalchemy.exc import IntegrityError`. Wrapped the `registry_repo.create_source(...)` call in `register_source` in a `try/except IntegrityError` block that rolls back and returns the concurrent winner's row. Applied the same pattern to the `create_source` call inside `ingest_url`.
**Commit:** `fix(02): WR-005 catch IntegrityError in register_source and ingest_url for concurrent dedup safety`

---

### WR-006 · Fixed — `scrapy_spider.py` `_out_file` not closed if exception occurs before `try` block

**File:** `src/knowledge_lake/plugins/builtin/scrapy_spider.py`
**Fix:** Set `_out_file = None` before the `try` block and moved `_out_file = open(out_jsonl, "w", encoding="utf-8")` to be the first statement inside the `try` block. Updated the `finally` guard from `if not _out_file.closed` to `if _out_file and not _out_file.closed`. Any exception during class-body definitions or CrawlerProcess setup now correctly enters the `finally` and skips the close (since `_out_file` is still `None`); the file is only opened once the `try` block is entered.
**Commit:** `fix(02): WR-006 move _out_file open() inside try block to prevent FD leak on exception`

---

### WR-007 · Fixed — Async API handlers call blocking SQLAlchemy sessions directly

**File:** `src/knowledge_lake/api/app.py`
**Fix:** Converted `create_crawl_job_endpoint` from `async def` to `def`. Since `crawl_source` is `async def`, added `import asyncio as _asyncio` locally and called it via `_asyncio.run(crawl_source(...))` inside the sync handler (FastAPI runs sync `def` handlers in a thread pool via anyio, so `asyncio.run` is safe there). Converted `get_crawl_job_endpoint` from `async def` to plain `def` — it only performs synchronous SQLAlchemy session operations. Both handlers are now dispatched to the thread pool by FastAPI, consistent with `search_endpoint` and `create_source_endpoint`.
**Commit:** `fix(02): WR-007 convert async crawl job API handlers to sync def to avoid blocking event loop`

---

## Remaining Issues

None — all issues resolved.

---

_Fixed: 2026-07-04T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
