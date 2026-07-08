---
phase: "02"
phase_name: "ingestion"
status: "partial"
iteration: 3
findings_in_scope: 13
fixed: 12
skipped: 1
---

# Code Review Fix Report: Phase 02 — ingestion

## Summary

12 of 13 in-scope findings (6 Critical, 7 Warning) were applied and committed. CR-002 was skipped because the migration it describes already exists on disk under the filename `0005_unique_sources_normalized_url.py` and already includes the required partial unique index on jobs — the finding was a false alarm caused by a filename mismatch.

## Fixes Applied

### CR-001 · Fixed — `get_event_loop()` raises DeprecationWarning/RuntimeError in Python 3.10+/3.12+

**Files:** `src/knowledge_lake/pipeline/crawl.py`, `src/knowledge_lake/plugins/builtin/playwright_adapter.py`
**Fix:** Replaced `asyncio.get_event_loop().run_in_executor(...)` with `asyncio.get_running_loop().run_in_executor(...)` in both files. `get_running_loop()` is the correct API inside an async coroutine; it raises `RuntimeError` immediately rather than silently returning a stale loop.
**Commit:** `fix(02): CR-001 replace get_event_loop() with get_running_loop() in async coroutines`

---

### CR-003 · Fixed — Post-rollback stale-session re-query in `put_raw`/`put_bronze`

**File:** `src/knowledge_lake/storage/s3.py`
**Fix:** Added `session.expire_all()` immediately after `session.rollback()` in both the `put_raw` and `put_bronze` `IntegrityError` handlers. This clears the ORM identity map so the subsequent `get_artifact_by_hash` SELECT issues a fresh database query rather than potentially returning a cached stale result.
**Commit:** `fix(02): CR-003 call session.expire_all() after rollback to clear identity map`

---

### CR-004 · Fixed — `_UPLOAD_ROOT` is hardcoded; `KLAKE_UPLOAD_ROOT` env var is never read

**Files:** `src/knowledge_lake/config/settings.py`, `src/knowledge_lake/api/app.py`
**Fix:** Added `upload_root: str = "/data/uploads"` to `Settings` (overridable via `KLAKE_UPLOAD_ROOT` env var). Removed the hardcoded `_UPLOAD_ROOT = Path("/data/uploads")` module-level constant from `app.py`. Updated `_safe_upload_path` to call `Path(get_settings().upload_root).resolve()` at request time so the guard always tracks the current deployment configuration.
**Commit:** `fix(02): CR-004 read upload_root from settings instead of hardcoded constant`

---

### CR-005 · Fixed — Scrapy spider leaves redirects enabled with no per-hop SSRF validation

**File:** `src/knowledge_lake/plugins/builtin/scrapy_spider.py`
**Fix:** Changed `"REDIRECT_ENABLED": True` to `"REDIRECT_ENABLED": False` in the spider settings dict. Added a comment explaining that Scrapy's `RedirectMiddleware` runs at priority 600 (after `SSRFGuardMiddleware` at 100), meaning redirect targets are never SSRF-validated when automatic redirect following is enabled.
**Commit:** `fix(02): CR-005 disable Scrapy redirects to prevent SSRF bypass on redirect targets`

---

### CR-006 · Fixed — `KlakeSpider.closed()` calls `_out_file.flush()` without None-check

**File:** `src/knowledge_lake/plugins/builtin/scrapy_spider.py`
**Fix:** Replaced the unconditional `_out_file.flush()` / `_out_file.close()` calls in `KlakeSpider.closed()` with a guarded block: `if _out_file is not None and not _out_file.closed:`. This prevents `AttributeError: 'NoneType' object has no attribute 'flush'` when Scrapy fires the closed signal before `_out_file` has been assigned (e.g., during abnormal setup failure).
**Commit:** `fix(02): CR-006 add None-check in KlakeSpider.closed() before flushing _out_file`

---

### WR-001 · Fixed — `asyncio.run()` inside a `def` endpoint creates a new event loop per request

**File:** `src/knowledge_lake/api/app.py`
**Fix:** Changed `create_crawl_job_endpoint` from `def` to `async def`. Replaced `asyncio.run(crawl_source(...))` with `await crawl_source(...)`. FastAPI now awaits the handler directly in the running event loop, eliminating per-request event-loop creation/destruction overhead and the future `RuntimeError` risk if the function were ever called from an already-running loop.
**Commit:** `fix(02): WR-001 convert create_crawl_job_endpoint to async def, await crawl_source directly`

---

### WR-002 · Fixed — Module-level `_limiter` accumulates dead `asyncio.Lock` objects across event loops

**File:** `src/knowledge_lake/plugins/builtin/playwright_adapter.py`
**Fix:** Removed the module-level `_limiter = PerHostLimiter()` singleton. Added `self._limiter = PerHostLimiter()` to `PlaywrightAdapter.__init__`. Updated the `fetch_page` call site from `await _limiter.wait(...)` to `await self._limiter.wait(...)`. Each adapter instance now owns its own limiter, so `asyncio.Lock` objects are always created in — and used in — the same event loop.
**Commit:** `fix(02): WR-002 move PerHostLimiter to instance variable to avoid stale event-loop locks`

---

### WR-003 · Fixed — `ScrapyAdapter.wait_for_completion` can deadlock when child process writes to a full pipe

**File:** `src/knowledge_lake/plugins/builtin/scrapy_adapter.py`
**Fix:** Replaced `proc.wait(timeout=timeout)` with `proc.communicate(timeout=timeout)`. `communicate()` reads stdout and stderr concurrently while waiting for the process to exit, preventing the classic deadlock where the child fills the pipe buffer and blocks while the parent is blocked in `wait()`. On `TimeoutExpired`, `proc.kill()` is called followed by `proc.communicate()` to drain pipes after the kill.
**Commit:** `fix(02): WR-003 use proc.communicate() instead of proc.wait() to prevent pipe-buffer deadlock`

---

### WR-004 · Fixed — `ingest_file` creates a new `Source` row without URL-first dedup

**File:** `src/knowledge_lake/pipeline/ingest.py`
**Fix:** Added URL-first dedup before `create_source`. When `source_url` is provided, `normalize_url` is called to compute `norm_url`, then `get_source_by_normalized_url` is checked. If an existing source is found, it is reused instead of attempting a new insert (which would raise `IntegrityError` from the `uq_sources_normalized_url` constraint added in migration 0005).
**Commit:** `fix(02): WR-004 add URL-first dedup in ingest_file to prevent duplicate source rows`

---

### WR-005 · Fixed — `@app.on_event("startup")` is deprecated in FastAPI 0.93+

**File:** `src/knowledge_lake/api/app.py`
**Fix:** Replaced `@app.on_event("startup")` with an `@asynccontextmanager` `lifespan` function. The `lifespan` async generator logs startup configuration before `yield` and is passed to `FastAPI(lifespan=lifespan)`. Added `from contextlib import asynccontextmanager` import. Removed the old `on_startup` function entirely.
**Commit:** `fix(02): WR-005 replace deprecated @app.on_event('startup') with lifespan context manager`

---

### WR-006 · Fixed — `_find_or_create_job` re-queries rolled-back session that may not see concurrent winner

**File:** `src/knowledge_lake/pipeline/crawl.py`
**Fix:** After `session.rollback()` in the `IntegrityError` handler, opened a fresh `get_session()` context to re-execute the SELECT for the concurrent winner's job. The rolled-back session is still bound to the same database connection and may not see committed rows under higher isolation levels; a fresh session opens a new connection and always sees the winner's committed row.
**Commit:** `fix(02): WR-006 use fresh session for post-rollback re-query in _find_or_create_job`

---

### WR-007 · Fixed — `probe_site` does not validate `robots_url` and `sitemap_url` independently

**File:** `src/knowledge_lake/crawl/select.py`
**Fix:** Added `validate_public_url(robots_url)` immediately before the `robots.txt` fetch and `validate_public_url(sitemap_url)` immediately before the `sitemap.xml` fetch. These calls are defense-in-depth: both URLs are derived from the already-validated base, but crafted `netloc` components using IPv6 bracket notation or user-info prefixes could encode a different host after `urlparse` round-tripping.
**Commit:** `fix(02): WR-007 add validate_public_url on derived robots_url and sitemap_url in probe_site`

---

## Skipped Issues

### CR-002 · Skipped — Migration `0005_jobs_unique_source_crawler.py` listed as missing but already exists

**File:** `src/knowledge_lake/registry/alembic/versions/0005_jobs_unique_source_crawler.py`
**Reason:** The file referenced by the reviewer does not exist by that exact name, but the migration it describes is already implemented. `0005_unique_sources_normalized_url.py` (revision `0005`, `down_revision = "0004"`) already includes the partial unique index `uq_jobs_source_crawler_active ON jobs (source_id, crawler) WHERE status IN ('running', 'pending')`. The finding was caused by a filename mismatch between what the reviewer expected and the actual filename on disk. No action required — the migration and constraint are already present.

---

## Remaining Issues

None — all 12 actionable findings resolved. CR-002 is confirmed already fixed under a different filename.

---

_Fixed: 2026-07-04T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 3_
