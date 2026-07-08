---
phase: "02"
phase_name: "ingestion"
status: "all_fixed"
iteration: 1
findings_in_scope: 10
fixed: 10
skipped: 0
---

# Code Review Fix Report: Phase 02 — ingestion

## Summary

All five critical security vulnerabilities and five warnings were fixed. The fixes address arbitrary file read via the upload endpoint, an asyncio.run() crash in API handlers, dead SSRF middleware in Scrapy, an SSRF bypass via unchecked redirects, a hardcoded secret key, an operator-precedence bug causing IndexError, event-loop starvation from blocking sync calls, silently discarded crawl failure reasons, a file-descriptor leak on Scrapy errors, and an HTTP connection leak on 4xx/5xx retries.

## Fixes Applied

### CR-01 · Fixed — Constrain /uploads to configured upload root

**File:** `src/knowledge_lake/api/app.py`
**Fix:** Added `_safe_upload_path()` helper that resolves the caller-supplied path and asserts it falls under `_UPLOAD_ROOT` (`/data/uploads` by default) using `Path.relative_to()`. The upload handler now calls `_safe_upload_path(file_path)` before passing the path to `ingest_file`, returning HTTP 400 if the path escapes the root.
**Commit:** `fix(02): CR-01 constrain /uploads endpoint to configured upload root`

---

### CR-02 · Fixed — Make crawl_source async to fix asyncio.run() crash

**Files:** `src/knowledge_lake/pipeline/crawl.py`, `src/knowledge_lake/api/app.py`, `src/knowledge_lake/cli/app.py`
**Fix:** Changed `crawl_source` from `def` to `async def` and replaced `asyncio.run(_crawl_loop(...))` with a direct `await _crawl_loop(...)`. The API handler already `async def` now simply `await`s `crawl_source`. The CLI wraps the call in `asyncio.run(crawl_source(...))` since it runs outside a live event loop.
**Commit:** `fix(02): CR-02 make crawl_source async to fix asyncio.run crash in API handlers`

---

### CR-03 · Fixed — Move SSRFGuardMiddleware to module level for Scrapy discovery

**File:** `src/knowledge_lake/plugins/builtin/scrapy_spider.py`
**Fix:** Moved the `SSRFGuardMiddleware` class from inside `_run_scrapy()` to module level so Scrapy can resolve it via `importlib.import_module(...) + getattr(module, "SSRFGuardMiddleware")`. Removed the defunct `SSRFGuardMiddleware.__module__ = __name__` line and the now-unused local `validate_public_url` import inside `_run_scrapy`. The middleware imports `validate_public_url` lazily in `process_request` to avoid circular import.
**Commit:** `fix(02): CR-03 move SSRFGuardMiddleware to module level so Scrapy can load it`

---

### CR-04 · Fixed — Re-validate SSRF guard on each redirect hop in probe_site

**File:** `src/knowledge_lake/crawl/select.py`
**Fix:** Added `_safe_get(url, timeout)` helper that manually follows redirects (up to 10 hops) without `follow_redirects=True`, calling `validate_public_url()` on each resolved `Location` header before following. Replaced all three `httpx.get(..., follow_redirects=True)` calls in `probe_site` with `_safe_get(...)` to close the redirect-based SSRF bypass.
**Commit:** `fix(02): CR-04 re-validate SSRF guard on each redirect hop in probe_site`

---

### CR-05 · Fixed — Replace hardcoded SearXNG secret_key with env-var template

**File:** `infra/searxng/settings.yml`
**Fix:** Replaced the literal string `"klake-dev-searxng-secret-change-in-production"` with `"${SEARXNG_SECRET:?SEARXNG_SECRET environment variable must be set}"`. SearXNG expands this template at startup: if `SEARXNG_SECRET` is unset, the process refuses to start with a clear error message rather than silently using the committed known-value key. Added a generation command comment.
**Commit:** `fix(02): CR-05 replace hardcoded SearXNG secret_key with required env-var template`

---

### WR-01 · Fixed — Use urlparse.hostname for effective_name to fix IndexError

**Files:** `src/knowledge_lake/api/app.py`, `src/knowledge_lake/cli/app.py`
**Fix:** Replaced `body.name or body.url.split("/")[2] if "/" in body.url else body.url` (operator-precedence trap; IndexError on `"/"`) with `body.name or (urlparse(body.url).hostname or body.url)` in both files. `urlparse` safely extracts the hostname regardless of URL shape. Added `from urllib.parse import urlparse` to `cli/app.py` (already present in `api/app.py` after CR-01 fix).
**Commit:** `fix(02): WR-01 use urlparse.hostname for effective_name to fix IndexError on path-only URLs`

---

### WR-02 · Fixed — Convert blocking sync handlers to plain def for thread-pool dispatch

**File:** `src/knowledge_lake/api/app.py`
**Fix:** Changed four handlers that call synchronous blocking functions (`search_endpoint`, `create_source_endpoint`, `upload_endpoint`, `discover_endpoint`, `lineage_endpoint`) from `async def` to plain `def`. FastAPI automatically dispatches plain `def` handlers to the default thread pool, unblocking the event loop. The `create_crawl_job_endpoint` remains `async def` because it now `await`s `crawl_source` (CR-02 fix).
**Commit:** `fix(02): WR-02 convert blocking sync handlers from async def to def for thread-pool dispatch`

---

### WR-03 · Fixed — Persist error_msg in crawl_states for failure diagnostics

**Files:** `src/knowledge_lake/registry/models.py`, `src/knowledge_lake/registry/repo.py`, `src/knowledge_lake/pipeline/crawl.py`, `src/knowledge_lake/registry/alembic/versions/0004_crawl_state_error_msg.py`
**Fix:** Added `error_msg: Mapped[Optional[str]]` (Text, nullable) to `CrawlState`. Extended `upsert_crawl_state` with an `error_msg: Optional[str] = None` parameter and wires it to the model (always updated so a retry success clears the prior error). Updated `_record_state` in `crawl.py` to forward the `error` kwarg as `error_msg=error`. Created migration `0004_crawl_state_error_msg.py` (revises 0003) to add the column.
**Commit:** `fix(02): WR-03 persist error_msg in crawl_states so failures are diagnosable`

---

### WR-04 · Fixed — Close output file on Scrapy CrawlerProcess exception

**File:** `src/knowledge_lake/plugins/builtin/scrapy_spider.py`
**Fix:** Wrapped the `CrawlerProcess(...) / process.crawl(...) / process.start()` block in `try/finally`. The `finally` block calls `_out_file.flush()` and `_out_file.close()` only if the file is not already closed (the normal path closes it via `KlakeSpider.closed()`). This prevents the file-descriptor leak when `CrawlerProcess` raises before the spider's `closed` signal fires.
**Commit:** `fix(02): WR-04 wrap CrawlerProcess in try/finally to close output file on exception`

---

### WR-05 · Fixed — Close streaming response in finally block on 4xx/5xx

**File:** `src/knowledge_lake/pipeline/ingest.py`
**Fix:** Wrapped the body-read section of `_fetch_with_retry` in `try/finally`: `resp.raise_for_status()` and `resp.iter_bytes()` are inside the `try`; `resp.close()` is in the `finally`. This ensures the streaming response is always closed even when `raise_for_status()` throws on 4xx/5xx, preventing HTTP connection leaks across tenacity retry attempts.
**Commit:** `fix(02): WR-05 close streaming response in finally block to prevent HTTP connection leak`

---

## Remaining Issues

None — all issues resolved.

---

_Fixed: 2026-07-04T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
