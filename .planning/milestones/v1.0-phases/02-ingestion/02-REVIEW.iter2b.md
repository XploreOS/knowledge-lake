---
phase: "02"
phase_name: "ingestion"
status: "findings"
depth: "standard"
files_reviewed: 46
files_reviewed_list:
  - infra/searxng/settings.yml
  - src/knowledge_lake/api/app.py
  - src/knowledge_lake/api/schemas.py
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/config/settings.py
  - src/knowledge_lake/crawl/__init__.py
  - src/knowledge_lake/crawl/ratelimit.py
  - src/knowledge_lake/crawl/robots.py
  - src/knowledge_lake/crawl/select.py
  - src/knowledge_lake/ids.py
  - src/knowledge_lake/pipeline/crawl.py
  - src/knowledge_lake/pipeline/discover.py
  - src/knowledge_lake/pipeline/ingest.py
  - src/knowledge_lake/plugins/builtin/crawl4ai_adapter.py
  - src/knowledge_lake/plugins/builtin/playwright_adapter.py
  - src/knowledge_lake/plugins/builtin/scrapy_adapter.py
  - src/knowledge_lake/plugins/builtin/scrapy_spider.py
  - src/knowledge_lake/plugins/builtin/searxng_discovery.py
  - src/knowledge_lake/plugins/protocols.py
  - src/knowledge_lake/plugins/resolver.py
  - src/knowledge_lake/registry/alembic/versions/0002_source_normalized_url.py
  - src/knowledge_lake/registry/alembic/versions/0003_crawl_jobs_states.py
  - src/knowledge_lake/registry/alembic/versions/0004_crawl_state_error_msg.py
  - src/knowledge_lake/registry/models.py
  - src/knowledge_lake/registry/repo.py
  - src/knowledge_lake/storage/s3.py
  - tests/integration/test_crawl4ai_adapter.py
  - tests/integration/test_crawl_resume.py
  - tests/integration/test_crawl_robots_blocked.py
  - tests/integration/test_crawl_schema.py
  - tests/integration/test_dedup_noop.py
  - tests/integration/test_discovery_register.py
  - tests/integration/test_ingest_url_dedup.py
  - tests/integration/test_playwright_adapter.py
  - tests/integration/test_scrapy_subprocess.py
  - tests/integration/test_source_register.py
  - tests/integration/test_upload.py
  - tests/unit/test_crawler_select.py
  - tests/unit/test_discovery.py
  - tests/unit/test_fetch_redirect_ssrf.py
  - tests/unit/test_put_bronze.py
  - tests/unit/test_robots_ratelimit.py
  - tests/unit/test_url_normalize.py
findings:
  critical: 5
  warning: 7
  info: 4
  total: 16
---

# Code Review: Phase 02 — ingestion

## Summary

The phase delivers a substantial and largely well-structured ingestion stack: SSRF-guarded URL fetching, robots.txt enforcement, three-tier rate limiting, multi-adapter crawl pipeline, source discovery, and a REST/CLI surface. Security fundamentals (parameterized queries, redirect-hop SSRF re-validation, no hardcoded secrets in production paths) are applied consistently. However, five critical bugs are present: integration tests for crawl resume call the `async def crawl_source` without awaiting it, `probe_site` unit tests mock `httpx` at the wrong layer (making live network calls), a TOCTOU race in `put_raw`/`put_bronze` can corrupt the raw zone under concurrent writes, `_find_or_create_job` uses two separate sessions with no transaction isolation allowing duplicate job creation, and the scrapy subprocess integration test reads the wrong argv index with a misleading comment. Several warnings cover a blocking synchronous robots fetch inside async coroutines, a `max_pages=0` falsy-check bug, a cross-domain skip inflating `pages_total`, and a missing UNIQUE constraint on `sources.normalized_url` that allows duplicate source rows under concurrent ingest.

---

## Critical Issues

### CR-001 · Critical — `crawl_source` called without `await` in integration tests

**File:** `tests/integration/test_crawl_resume.py` · **Lines:** 186, 302, 399  
**Issue:** `crawl_source` is an `async def` (pipeline/crawl.py line 38). The integration tests call it as a bare synchronous call:
```python
result = crawl_source("https://example.com", settings=...)
```
This returns a coroutine object and never executes the body. All downstream assertions like `result["pages_complete"]` raise `TypeError: 'coroutine' object is not subscriptable` at runtime. The same pattern appears in `test_crawl_robots_blocked.py` at lines 138 and 261. Because mock objects are flexible, assertions may appear to pass without the crawl body ever running.  
**Impact:** The crawl resume and robots-blocked integration tests do not actually exercise any crawl logic. They either silently produce wrong results or crash with a TypeError depending on Python version and pytest configuration. Entire test classes are effectively non-functional.  
**Fix:** Add `asyncio.run()` wrappers or mark tests `@pytest.mark.asyncio` and use `await`:
```python
# Option A — synchronous test:
result = asyncio.run(crawl_source("https://example.com", settings=...))

# Option B — async test:
@pytest.mark.asyncio
async def test_resume_fetches_only_pending_urls(self, engine, mock_adapter):
    result = await crawl_source("https://example.com", settings=...)
```

---

### CR-002 · Critical — `probe_site` tests mock `httpx` at the wrong layer: live network calls

**File:** `tests/unit/test_crawler_select.py` · **Lines:** 148, 165, 182, 196  
**Issue:** All four probe_site tests use `@patch("knowledge_lake.crawl.select.httpx")` to suppress network calls. But `probe_site` calls `_safe_get(url, timeout)`, which itself calls `httpx.Client(follow_redirects=False)` — a constructor call, not a module-level function call. Patching the `httpx` name at the module level does not intercept the `httpx.Client(...)` constructor. As a result, `_safe_get` creates a real `httpx.Client` and makes live outbound connections.

On a network-isolated CI runner the tests fail with connection errors. On a live machine they make actual HTTP requests to `example.com` on every test run.  
**Impact:** Unit tests are not hermetic; they depend on external network availability and make outbound connections, violating the test contract.  
**Fix:** Patch `httpx.Client` at the point of use:
```python
@patch("knowledge_lake.crawl.select.httpx.Client")
def test_has_sitemap_from_sitemap_xml_200(self, mock_client_cls):
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.side_effect = [entry_resp, robots_resp, sitemap_resp]
    mock_client_cls.return_value = mock_client
    html, has_sitemap = probe_site("https://example.com")
```

---

### CR-003 · Critical — TOCTOU race in `put_raw`/`put_bronze`: concurrent writes can corrupt the raw zone

**File:** `src/knowledge_lake/storage/s3.py` · **Lines:** 203–242 (`put_raw`), 294–336 (`put_bronze`)  
**Issue:** Both `put_raw` and `put_bronze` follow a check-then-act sequence across three separate non-atomic steps:
1. `get_artifact_by_hash(session, hash, ...)` — registry read (returns None)
2. `self.exists(key)` — S3 head_object (returns False)
3. `self.put_object(key, data)` — S3 write
4. `create_raw_artifact(session, ...)` — registry write

Under concurrent ingest of identical content, two workers can both pass steps 1 and 2, then both attempt step 3. The second `put_object` overwrites the S3 object (even though it has the same content, this is a write to an object declared immutable). Then both attempt step 4, and one gets a DB `IntegrityError` on `uq_artifacts_hash_type` (crashing the request) while the other succeeds.  
**Impact:** Raw zone "immutability" is violated under concurrent writes. One of two concurrent ingest requests will raise an unhandled `IntegrityError` surfaced as a 500. The documented "defense-in-depth" immutability guarantee does not hold under concurrency.  
**Fix:** Catch `IntegrityError` from the `create_raw_artifact` call and recover:
```python
from sqlalchemy.exc import IntegrityError
try:
    artifact = repo.create_raw_artifact(session, ...)
    session.flush()
except IntegrityError:
    session.rollback()
    artifact = repo.get_artifact_by_hash(session, content_hash, "raw_document")
    if artifact is None:
        raise  # unexpected — re-raise
return artifact
```
The existing `uq_artifacts_hash_type` constraint makes this safe: the first writer wins, the second detects the conflict and returns the winner's artifact.

---

### CR-004 · Critical — `_find_or_create_job` uses two separate sessions: duplicate job creation race

**File:** `src/knowledge_lake/pipeline/crawl.py` · **Lines:** 136–173  
**Issue:** The function opens one session to check for an existing job (lines 148–162), closes it, then opens a second session to create a new job (lines 164–173). Between closing the first and opening the second, another concurrent worker for the same `(source_id, crawler)` can observe the same "no existing job" result and create its own job. Both inserts succeed because there is no `UNIQUE` constraint on `(source_id, crawler)` in the `jobs` table — two running jobs for the same source are now live simultaneously.  
**Impact:** Duplicate crawl jobs. The same source gets crawled twice in parallel, producing duplicate artifacts, duplicate crawl_state rows (under two different job_ids), and double the S3 writes. The resume logic will not detect the duplicate because it filters by `job_id`.  
**Fix:** Combine the lookup and conditional insert into a single session with a select-for-update or use a database-level unique partial index:
```sql
-- Alembic migration:
CREATE UNIQUE INDEX uq_jobs_source_crawler_active
  ON jobs (source_id, crawler)
  WHERE status IN ('running', 'pending');
```
Then catch `IntegrityError` on insert as the "already exists" signal and return the existing job's ID.

---

### CR-005 · Critical — Scrapy subprocess integration test reads wrong argv index with misleading comment

**File:** `tests/integration/test_scrapy_subprocess.py` · **Line:** 251  
**Issue:** Inside `fake_popen`, the JSONL output path is read as:
```python
out_jsonl_path = Path(cmd[4])  # argv[2] = out_jsonl
```
The comment `argv[2]` refers to `sys.argv[2]` inside the child process. In the parent's Popen call vector the actual argument positions are:
```
cmd[0] = sys.executable
cmd[1] = "-m"
cmd[2] = "knowledge_lake.plugins.builtin.scrapy_spider"
cmd[3] = source_url
cmd[4] = out_jsonl    <-- correct index, wrong comment
cmd[5] = config_json
```
Index `cmd[4]` is coincidentally correct for the current module path (`scrapy_spider` as a single component after the package path). However, `test_start_crawl_spawns_subprocess` on line 144 asserts `call_args[3] == _SAMPLE_URL` using 0-based indexing of the Popen list, but `call_args` there is `mock_popen.call_args[0][0]` (the positional arg list to Popen), making `call_args[3]` = `source_url`. These two different indexing schemes (child argv vs parent cmd list) coexist with contradicting comments. If the module path is ever changed (e.g., renamed or moved), `cmd[4]` would silently point to `source_url` instead of `out_jsonl` and `_FakeProc` would write JSONL to a path matching the source URL, failing silently.  
**Impact:** Silent test failure if module path changes; confusing maintenance burden from contradicting comments.  
**Fix:** Replace magic indices with named extraction and fix the comment:
```python
# cmd layout: [python, "-m", "<module>", source_url, out_jsonl, config_json]
_PYTHON_IDX, _DASH_M_IDX, _MODULE_IDX, _URL_IDX, _JSONL_IDX, _CONFIG_IDX = range(6)
out_jsonl_path = Path(cmd[_JSONL_IDX])
assert cmd[_URL_IDX] == url  # verify source_url at expected position
```

---

## Warnings

### WR-001 · Warning — `max_pages=0` silently ignored due to falsy `or` check

**File:** `src/knowledge_lake/pipeline/crawl.py` · **Line:** 70  
**Issue:**
```python
effective_max_pages = max_pages or s.crawl.max_pages
```
Python's `or` treats `0` as falsy. If `max_pages=0` is passed (e.g., a test stub or dry-run), it falls through to `s.crawl.max_pages` (default 50). The caller cannot request zero pages.  
**Impact:** `max_pages=0` is silently overridden with the global default (50 pages). A user expecting a dry-run or a test expecting zero crawl operations gets 50 pages crawled instead.  
**Fix:**
```python
effective_max_pages = max_pages if max_pages is not None else s.crawl.max_pages
```

---

### WR-002 · Warning — Cross-domain skip inflates `pages_total` making stats inconsistent

**File:** `src/knowledge_lake/pipeline/crawl.py` · **Lines:** 235–254  
**Issue:** `pages_total` is incremented at line 238 (before the same-domain check at line 250). Cross-domain URLs increment `pages_total` but do not increment `pages_complete`, `pages_robots_blocked`, or `pages_failed`. The returned stats dict will have `pages_total > pages_complete + pages_robots_blocked + pages_failed` whenever cross-domain URLs are encountered.  
**Impact:** Misleading stats. Callers cannot reconcile the total against outcome counts. Monitoring systems built on these stats will show unexplained discrepancies.  
**Fix:** Decrement `pages_total` on the cross-domain skip path:
```python
if url_domain != seed_domain:
    log.info("crawl.cross_domain_skip", url=url, domain=url_domain)
    pages_total -= 1  # undo the increment for skipped URL
    continue
```
Or alternatively track a separate `pages_skipped_cross_domain` counter and include it in the returned dict.

---

### WR-003 · Warning — `_fetch_with_retry` may raise secondary exception masking the original on mid-stream timeout

**File:** `src/knowledge_lake/pipeline/ingest.py` · **Lines:** 196–215  
**Issue:** The `try`/`finally` block reads the response body in `try` and calls `resp.close()` in `finally`. If `httpx.TimeoutException` is raised during `resp.iter_bytes()` (mid-stream), `resp.close()` is called in `finally` on a partially-read streaming response. Depending on the httpx version and transport, closing a streaming response mid-read may itself raise a `RuntimeError` or `httpx.RemoteProtocolError`, which replaces the original `TimeoutException` in the exception chain before `tenacity` sees it. Since `TimeoutException` is in the retry filter but `RuntimeError` is not, the retry logic never fires.  
**Impact:** A mid-stream timeout may surface as an unretried `RuntimeError` instead of a retried `TimeoutException`. The downstream caller sees an unexpected error type.  
**Fix:** Wrap the `resp.close()` call in the `finally` to suppress secondary exceptions:
```python
finally:
    try:
        resp.close()
    except Exception:
        pass  # never mask the original exception
```

---

### WR-004 · Warning — `fetch_robots` is synchronous but called from async coroutines

**File:** `src/knowledge_lake/crawl/robots.py` · **Lines:** 98–141`; callers: `src/knowledge_lake/pipeline/crawl.py:96`, `src/knowledge_lake/plugins/builtin/playwright_adapter.py:165`  
**Issue:** `fetch_robots` uses a blocking `httpx.Client` (synchronous). It is called from inside `crawl_source` (an `async def`) and `PlaywrightAdapter.fetch_page` (an `async def`). A blocking HTTP call inside an async coroutine holds the event loop for the full robots.txt fetch duration — up to 10 seconds per attempt × 3 retries = 30 seconds in the worst case. This prevents all other coroutines from making progress during that window.  
**Impact:** Under concurrent crawl operations, a single slow robots.txt server stalls the entire event loop. All other in-flight requests queue behind the blocking call.  
**Fix:** Convert to async using `httpx.AsyncClient`. As an immediate interim fix, offload the blocking call to a thread:
```python
# In crawl_source:
import asyncio
robots_policy = await asyncio.get_event_loop().run_in_executor(
    None, fetch_robots, base_url
)
```

---

### WR-005 · Warning — Missing UNIQUE constraint on `sources.normalized_url` allows duplicate sources under concurrency

**File:** `src/knowledge_lake/registry/alembic/versions/0002_source_normalized_url.py` · **Lines:** 33–42  
**Issue:** Migration 0002 adds an index (`ix_sources_normalized_url`) on `sources.normalized_url` but NOT a UNIQUE constraint. The URL-first dedup in `register_source` and `ingest_url` relies on a check-then-insert pattern across two separate sessions. Without a database-enforced uniqueness guarantee, concurrent callers for the same URL will both find "no existing source" and both insert new rows, producing duplicate source entries.  
**Impact:** Duplicate source rows for the same normalized URL. `get_source_by_normalized_url` uses `.limit(1)` and returns an arbitrary row, so two concurrent callers may get different `source_id` values for the same URL, causing lineage splits and breaking dedup guarantees.  
**Fix:** Add a unique constraint in a new migration:
```python
def upgrade() -> None:
    op.create_unique_constraint(
        "uq_sources_normalized_url",
        "sources",
        ["normalized_url"],
    )
```
Then update `register_source` and `ingest_url` to catch `IntegrityError` on insert as the dedup signal:
```python
from sqlalchemy.exc import IntegrityError
try:
    source = registry_repo.create_source(session, ...)
    session.flush()
except IntegrityError:
    session.rollback()
    source = registry_repo.get_source_by_normalized_url(session, norm_url)
```

---

### WR-006 · Warning — `scrapy_spider.py` `_out_file` not closed if exception occurs before `try` block

**File:** `src/knowledge_lake/plugins/builtin/scrapy_spider.py` · **Lines:** 90, 99–100, 216–223  
**Issue:** `_out_file` is opened at line 90 (before the `try` block at line 216). If any exception occurs between line 90 and the `try` statement at line 216 — for example, during the class body definitions of `MaxPagesExtension` or `KlakeSpider` — the `try`/`finally` is never entered and `_out_file` is never closed. The comment at lines 97–100 acknowledges this but the fix is incomplete: the file open itself should be inside the `try`.  
**Impact:** File descriptor leak on exceptions during spider class setup. In a subprocess context the FD is released on process exit, but unflushed data may be lost.  
**Fix:** Move the `open()` call inside the `try` block:
```python
_out_file = None
try:
    _out_file = open(out_jsonl, "w", encoding="utf-8")
    # ... class definitions and process.start() ...
finally:
    if _out_file and not _out_file.closed:
        _out_file.flush()
        _out_file.close()
```

---

### WR-007 · Warning — Async API handlers call blocking SQLAlchemy sessions directly

**File:** `src/knowledge_lake/api/app.py` · **Lines:** 319, 374, 391–405  
**Issue:** `create_crawl_job_endpoint` and `get_crawl_job_endpoint` are `async def` handlers. Both call `get_session()` which returns a synchronous SQLAlchemy `Session`. `get_crawl_job_endpoint` executes `session.get(Job, job_id)` and `session.execute(stmt).all()` (lines 392–405) directly from the async handler body. These are blocking I/O operations that hold the event loop during DB round-trips. The sync handlers (`search_endpoint`, `create_source_endpoint`) are correctly declared as `def` so FastAPI runs them in a thread pool, but the async handlers bypass that safety valve.  
**Impact:** Any DB query in an `async` handler blocks the event loop. Under load, this serializes all concurrent requests behind each DB call, causing cascading timeouts.  
**Fix:** Convert `create_crawl_job_endpoint` and `get_crawl_job_endpoint` to sync `def` (FastAPI will run them in a thread pool, consistent with the other handlers) until proper async session support is added:
```python
def get_crawl_job_endpoint(job_id: str) -> CrawlJobOut:
    ...
```

---

## Info

### IN-001 · Info — `raw_document`, `parsed_document`, and `bronze_document` all share the `doc_` ID prefix

**File:** `src/knowledge_lake/ids.py` · **Lines:** 31–40  
**Issue:** Three distinct artifact types (`raw_document`, `parsed_document`, `bronze_document`) all generate IDs with the `"doc_"` prefix. A bare `doc_<uuid>` in logs cannot identify whether the artifact is a raw, parsed, or bronze document without a registry lookup, defeating the stated self-describing ID goal.  
**Impact:** Reduced debuggability and log readability. Lineage traces in logs show `doc_` IDs without type context.  
**Fix:** Assign distinct prefixes: e.g., `raw_` for raw documents, `pdoc_` for parsed, `bron_` for bronze. This is a breaking schema change requiring a data migration for existing rows.

---

### IN-002 · Info — `_domain_key` produces a key with a trailing dot for hostnames without a TLD

**File:** `src/knowledge_lake/crawl/ratelimit.py` · **Lines:** 85–86  
**Issue:** `tldextract.extract("https://localhost/page")` returns `ExtractResult(subdomain='', domain='localhost', suffix='')`, so `f"{extracted.domain}.{extracted.suffix}"` produces `"localhost."` (trailing dot). In practice `localhost` URLs are blocked by `validate_public_url` before reaching `_domain_key`, so this is unreachable in production — but defensive code should handle the edge case.  
**Impact:** Non-canonical rate-limiter key with trailing dot in edge cases. No functional impact in current usage.  
**Fix:**
```python
key = f"{extracted.domain}.{extracted.suffix}".rstrip(".")
return key or url
```

---

### IN-003 · Info — `cmd_demo` in `cli/app.py` catches bare `Exception` on live URL fallback

**File:** `src/knowledge_lake/cli/app.py` · **Lines:** 371–373  
**Issue:** The demo command catches all exceptions including programming errors (`AttributeError`, `TypeError`) and silently retries with the cached fixture. A programming error in the live ingest path appears as `"Live URL failed (AttributeError: ...)."` rather than a traceback, making bugs hard to diagnose.  
**Impact:** Programming errors are masked during live demo execution.  
**Fix:** Narrow to expected network/validation errors:
```python
import httpx
except (ValueError, httpx.HTTPError, OSError, TimeoutError) as exc:
    typer.echo(f"Live URL failed ({exc}). Falling back to cached fixture.", err=True)
    use_live = False
```

---

### IN-004 · Info — `test_raises_on_private_ip` in probe_site tests may be environment-sensitive

**File:** `tests/unit/test_crawler_select.py` · **Lines:** 208–211  
**Issue:** `probe_site("https://192.168.1.1/")` is expected to raise `ValueError`. This works because `validate_public_url` checks the IP directly without DNS. However, the `probe_site` function also calls `validate_public_url` (which calls `socket.getaddrinfo`) and in some container environments with custom DNS resolvers, even numeric IPs may go through an override path. The test does not mock `socket.getaddrinfo` as the other SSRF tests do.  
**Impact:** Potentially fragile in non-standard DNS environments. Low severity.  
**Fix:** Add `socket.getaddrinfo` mock consistent with other SSRF tests:
```python
with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("192.168.1.1", 443))]):
    with pytest.raises(ValueError):
        probe_site("https://192.168.1.1/")
```

---

## Files Reviewed

| File | Status |
|------|--------|
| `infra/searxng/settings.yml` | Clean |
| `src/knowledge_lake/api/app.py` | 1 finding (WR-007) |
| `src/knowledge_lake/api/schemas.py` | Clean |
| `src/knowledge_lake/cli/app.py` | 1 finding (IN-003) |
| `src/knowledge_lake/config/settings.py` | Clean |
| `src/knowledge_lake/crawl/__init__.py` | Clean |
| `src/knowledge_lake/crawl/ratelimit.py` | 1 finding (IN-002) |
| `src/knowledge_lake/crawl/robots.py` | 1 finding (WR-004) |
| `src/knowledge_lake/crawl/select.py` | Clean |
| `src/knowledge_lake/ids.py` | 1 finding (IN-001) |
| `src/knowledge_lake/pipeline/crawl.py` | 3 findings (CR-004, WR-001, WR-002) |
| `src/knowledge_lake/pipeline/discover.py` | Clean |
| `src/knowledge_lake/pipeline/ingest.py` | 2 findings (WR-003, WR-005) |
| `src/knowledge_lake/plugins/builtin/crawl4ai_adapter.py` | Clean |
| `src/knowledge_lake/plugins/builtin/playwright_adapter.py` | 1 finding (WR-004 caller) |
| `src/knowledge_lake/plugins/builtin/scrapy_adapter.py` | Clean |
| `src/knowledge_lake/plugins/builtin/scrapy_spider.py` | 1 finding (WR-006) |
| `src/knowledge_lake/plugins/builtin/searxng_discovery.py` | Clean |
| `src/knowledge_lake/plugins/protocols.py` | Clean |
| `src/knowledge_lake/plugins/resolver.py` | Clean |
| `src/knowledge_lake/registry/alembic/versions/0002_source_normalized_url.py` | 1 finding (WR-005) |
| `src/knowledge_lake/registry/alembic/versions/0003_crawl_jobs_states.py` | Clean |
| `src/knowledge_lake/registry/alembic/versions/0004_crawl_state_error_msg.py` | Clean |
| `src/knowledge_lake/registry/models.py` | Clean |
| `src/knowledge_lake/registry/repo.py` | Clean |
| `src/knowledge_lake/storage/s3.py` | 1 finding (CR-003) |
| `tests/integration/test_crawl4ai_adapter.py` | Clean |
| `tests/integration/test_crawl_resume.py` | 1 finding (CR-001) |
| `tests/integration/test_crawl_robots_blocked.py` | 1 finding (CR-001 same pattern) |
| `tests/integration/test_crawl_schema.py` | Clean |
| `tests/integration/test_dedup_noop.py` | Clean |
| `tests/integration/test_discovery_register.py` | Clean |
| `tests/integration/test_ingest_url_dedup.py` | Clean |
| `tests/integration/test_playwright_adapter.py` | Clean |
| `tests/integration/test_scrapy_subprocess.py` | 1 finding (CR-005) |
| `tests/integration/test_source_register.py` | Clean |
| `tests/integration/test_upload.py` | Clean |
| `tests/unit/test_crawler_select.py` | 2 findings (CR-002, IN-004) |
| `tests/unit/test_discovery.py` | Clean |
| `tests/unit/test_fetch_redirect_ssrf.py` | Clean |
| `tests/unit/test_put_bronze.py` | Clean |
| `tests/unit/test_robots_ratelimit.py` | Clean |
| `tests/unit/test_url_normalize.py` | Clean |

---

_Reviewed: 2026-07-04T00:00:00Z_  
_Reviewer: Claude (gsd-code-reviewer)_  
_Depth: standard_
