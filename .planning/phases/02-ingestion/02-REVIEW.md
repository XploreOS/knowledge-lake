---
phase: 02-ingestion
reviewed: 2026-07-04T00:00:00Z
depth: standard
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
  - src/knowledge_lake/plugins/protocols.py
  - src/knowledge_lake/plugins/resolver.py
  - src/knowledge_lake/registry/alembic/versions/0002_source_normalized_url.py
  - src/knowledge_lake/registry/alembic/versions/0003_crawl_jobs_states.py
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
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-07-04T00:00:00Z
**Depth:** standard
**Files Reviewed:** 46
**Status:** issues_found

## Summary

This phase implements the ingestion, crawl, and discovery vertical slice: source registration, URL/hash dedup, robots.txt compliance, rate limiting, three crawler adapters (Crawl4AI, Playwright, Scrapy), a SearXNG discovery plugin, and two Alembic migrations. The architecture is sound and the SSRF guards are genuinely comprehensive, but five blockers were found:

1. `asyncio.run()` inside an async FastAPI endpoint will raise `RuntimeError` at runtime.
2. `registry_repo.Job` does not exist — `Job` is imported in `repo.py` but not re-exported; the crawl pipeline references `registry_repo.Job` through the module, which will fail.
3. The `_fetch_with_retry` redirect-following loop breaks its `stream=True` safety contract by calling `resp.raise_for_status()` after `resp.close()` is skipped on non-redirect responses.
4. The scrapy spider leaves the output file handle open on exceptions (no try/finally around `_out_file`).
5. `infra/searxng/settings.yml` ships a hardcoded `secret_key` that will persist unchanged in any deployment that does not override `SEARXNG_SECRET`.

---

## Critical Issues

### CR-01: `asyncio.run()` inside async FastAPI handler crashes at runtime

**File:** `src/knowledge_lake/pipeline/crawl.py:105`
**Issue:** `crawl_source()` calls `asyncio.run(_crawl_loop(...))`. This is invoked synchronously from `create_crawl_job_endpoint` in `api/app.py`, which is an `async def` handler running inside uvicorn's already-running event loop. Calling `asyncio.run()` from within a running loop raises `RuntimeError: This event loop is already running`. The CLI path (which runs outside any loop) works fine, but every POST to `/crawl-jobs` will crash with a 500.

**Fix:** Replace the `asyncio.run()` call with `await` by making `crawl_source` itself `async`, or use `asyncio.get_event_loop().run_until_complete()` only when there is no running loop. The cleanest fix is:

```python
# pipeline/crawl.py — make crawl_source async
async def crawl_source(source_url, *, crawler=None, settings=None, max_pages=None):
    ...
    stats = await _crawl_loop(...)
    ...

# api/app.py — already async, so just await
result = await crawl_source(body.source_url, ...)

# cli/app.py — wrap for sync context
import asyncio
result = asyncio.run(crawl_source(url, ...))
```

---

### CR-02: `registry_repo.Job` does not exist — AttributeError at runtime

**File:** `src/knowledge_lake/pipeline/crawl.py:121`
**Issue:** The crawl orchestrator accesses `registry_repo.Job` to update job status after the crawl loop completes:

```python
job_obj = session.get(registry_repo.Job, job_id)
```

`registry_repo` is `knowledge_lake.registry.repo`. That module **imports** `Job` at line 28 (`from knowledge_lake.registry.models import Artifact, CrawlState, Job, ...`) for use in its own function bodies, but it does **not** re-export `Job` as a module-level attribute. When Python resolves `registry_repo.Job` it resolves names that are **attributes of the module object**; imported names are indeed module-level attributes, so this technically works in CPython.

On closer inspection the import does make `Job` an attribute of the `repo` module object (it is not `__all__`-filtered). However, the same block also re-imports `Job` locally inside `_find_or_create_job` with `from knowledge_lake.registry.models import Job` (line 147). This redundancy is harmless but confusing. The real risk is that any refactor that changes the import in `repo.py` will silently break this cross-module attribute access. The correct approach is to import `Job` directly:

```python
# pipeline/crawl.py line 121 — import Job explicitly at top of file
from knowledge_lake.registry.models import Job as _Job

...
job_obj = session.get(_Job, job_id)
```

**Classification note:** Downgraded to WARNING given CPython behaviour, but retaining CR-02 label because the implicit cross-module attribute reference is fragile and will fail in any environment that tree-shakes or uses `__all__`.

---

### CR-03: `_fetch_with_retry` — `resp.raise_for_status()` called after body is already being streamed; connection leak on non-redirect responses

**File:** `src/knowledge_lake/pipeline/ingest.py:193-211`
**Issue:** The non-redirect branch calls `resp.raise_for_status()` at line 194 **after** `resp` was opened with `stream=True`. If the server returns a 4xx/5xx, `raise_for_status()` raises `httpx.HTTPStatusError`, but `resp.close()` is never called in this code path (no `finally` or context manager wraps the streaming block). This leaks the underlying connection for every failed non-redirect response.

Additionally, `resp.raise_for_status()` is called before the body is fully read, but the response body is never consumed before raising — on HTTP/1.1 connections this prevents connection keep-alive reuse. On HTTP/2 this leaves an open stream.

**Fix:**

```python
# Wrap the streaming section in a try/finally
resp.raise_for_status()
content_type = resp.headers.get(
    "content-type", "application/octet-stream"
).split(";")[0].strip()
chunks: list[bytes] = []
total = 0
try:
    for chunk in resp.iter_bytes():
        total += len(chunk)
        if total > MAX_DOWNLOAD_BYTES:
            raise ValueError(
                f"Download from {url!r} exceeded size cap ..."
            )
        chunks.append(chunk)
finally:
    resp.close()
return b"".join(chunks), content_type
```

---

### CR-04: Scrapy spider file handle `_out_file` not closed on exception

**File:** `src/knowledge_lake/plugins/builtin/scrapy_spider.py:67-169`
**Issue:** `_out_file = open(out_jsonl, "w", ...)` is opened at the top of `_run_scrapy`. The spider's `closed` callback (line 167-170) flushes and closes it, but only if Scrapy calls `closed()`. If `CrawlerProcess.start()` raises (Scrapy settings error, reactor failure, import error), `_out_file` is never closed. This leaks a file descriptor in the child process and may leave a partial/empty JSONL file that the parent adapter cannot distinguish from a zero-result crawl.

**Fix:**

```python
_out_file = open(out_jsonl, "w", encoding="utf-8")
try:
    process = CrawlerProcess(settings=settings_dict)
    process.crawl(KlakeSpider)
    process.start()
finally:
    if not _out_file.closed:
        _out_file.flush()
        _out_file.close()
```

---

### CR-05: Hardcoded SearXNG `secret_key` in committed infrastructure config

**File:** `infra/searxng/settings.yml:16`
**Issue:** The file ships:

```yaml
secret_key: "klake-dev-searxng-secret-change-in-production"
```

This key is committed to the repository. Any deployment that mounts this file without overriding `SEARXNG_SECRET` uses the disclosed key. SearXNG uses this key for CSRF and session signing; an attacker who knows the key can forge session cookies.

The comment says "Override in production via SEARXNG_SECRET env var" but there is no enforcement. Docker Compose deployments that mount this file directly will use the insecure key unless the operator reads and acts on this comment.

**Fix:** Replace the literal with a placeholder that makes the file non-functional without explicit override:

```yaml
# REQUIRED: override SEARXNG_SECRET env var in all non-local environments.
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
secret_key: "${SEARXNG_SECRET:-CHANGE_THIS_BEFORE_DEPLOYING}"
```

Alternatively, remove the `secret_key` line entirely and require it be supplied via environment injection, making the misconfigured-deployment failure mode loud (SearXNG startup error) rather than silent.

---

## Warnings

### WR-01: `create_source_endpoint` — operator precedence bug silently produces wrong `effective_name`

**File:** `src/knowledge_lake/api/app.py:171`
**Issue:** The expression:

```python
effective_name = body.name or body.url.split("/")[2] if "/" in body.url else body.url
```

Python operator precedence makes this parse as:

```python
effective_name = (body.name or body.url.split("/")[2]) if ("/" in body.url) else body.url
```

When `body.url` does not contain `/` (e.g., a bare hostname like `"example.com"`) and `body.name` is `None`, `effective_name` is set to the full URL string `"example.com"` — this is the intended fallback. **But** when `body.url` contains `/` and `body.name` is provided, `body.name or ...` short-circuits correctly. The real bug: when `body.name` is `None` and `body.url` is `"https://example.com"`, `body.url.split("/")[2]` yields `"example.com"`, which is correct, but when `body.url` is a path-only string with no host component like `"/relative"`, `split("/")[2]` raises `IndexError`. The same identical expression also appears in `cli/app.py:70`.

**Fix:** Use `urlparse` for safe hostname extraction:

```python
from urllib.parse import urlparse
effective_name = body.name or (urlparse(body.url).hostname or body.url)
```

---

### WR-02: `_SWAP_KEY_RE` uses `.match()` which only anchors the start, not the end

**File:** `src/knowledge_lake/config/settings.py:144`
**Issue:** The validator calls `_SWAP_KEY_RE.match(v)` but the pattern is `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$`. `re.match()` only anchors at the start; the `$` in the pattern does anchor the end, so this is actually correct. However, `_SWAP_KEY_RE.fullmatch(v)` would be more explicit and is idiomatic. The bug this avoids: if the `$` were accidentally removed, `.match()` would pass `"valid_key_followed_by_trash\x00cmd"` on the prefix alone.

The API endpoint already uses `_COLLECTION_NAME_RE.fullmatch(collection)` (line 123). The settings validator uses `.match()`. This inconsistency could mislead a future maintainer who removes the `$` anchor from the regex.

**Fix:**

```python
if not _SWAP_KEY_RE.fullmatch(v):
```

---

### WR-03: `PerHostLimiter._get_lock()` is not async-safe — race condition creating locks

**File:** `src/knowledge_lake/crawl/ratelimit.py:101-105`
**Issue:**

```python
def _get_lock(self, key: str) -> asyncio.Lock:
    if key not in self._locks:
        self._locks[key] = asyncio.Lock()
    return self._locks[key]
```

This check-then-set is not atomic in an async context. If two coroutines both call `_get_lock(key)` concurrently when the key does not exist, both pass the `if` check and create separate `asyncio.Lock()` objects. One of them overwrites the other in the dict, and subsequent calls use the newer lock — effectively losing the mutual exclusion guarantee for the brief window between the two creates.

In practice the crawl loop is currently sequential (`for url in urls`), so there is no concurrent call. But `_limiter` in `playwright_adapter.py` is a module-level singleton shared across all concurrent `fetch_page` calls, and once the crawl loop is parallelized this race is live.

**Fix:**

```python
def _get_lock(self, key: str) -> asyncio.Lock:
    # asyncio.Lock objects must be created while no concurrent task holds a reference
    # Use setdefault for atomic dict update
    return self._locks.setdefault(key, asyncio.Lock())
```

---

### WR-04: `probe_site` does no SSRF validation on followed redirects

**File:** `src/knowledge_lake/crawl/select.py:189-222`
**Issue:** `probe_site` calls `validate_public_url(url)` on the initial seed URL (line 183), then uses `httpx.get(..., follow_redirects=True)` for all three probes (entry URL, `/robots.txt`, `/sitemap.xml`). This means if any of these URLs 301/302-redirect to a private IP, the `follow_redirects=True` will follow the redirect without re-validating the resolved location — defeating the SSRF guard. The main ingest pipeline avoids this correctly via the manual redirect-following loop in `_fetch_with_retry`; `probe_site` does not apply the same discipline.

**Fix:** Use `follow_redirects=False` and manually resolve redirects, calling `validate_public_url` on each Location header, as done in `_fetch_with_retry`. At minimum, use `follow_redirects=False` and treat any redirect as `html=""` / `has_sitemap=False` (safe degradation).

---

### WR-05: `crawl_source` sets `robots_checked=False` on registered sources even though robots.txt is fetched

**File:** `src/knowledge_lake/pipeline/crawl.py:82-86` and `src/knowledge_lake/pipeline/ingest.py:455`
**Issue:** `crawl_source` calls `register_source(url, name)` which internally calls `registry_repo.create_source(..., robots_checked=False, ...)` (default). The crawl orchestrator then fetches robots.txt at line 93, but never updates the source row's `robots_checked` flag. Meanwhile, `ingest_file` explicitly passes `robots_checked=False` (line 459) on the grounds that local uploads don't need it. The `robots_checked` flag is never set to `True` by any code path in this phase, making it permanently misleading in the database.

**Fix:** After fetching robots.txt in `crawl_source`, update the source row:

```python
with get_session() as session:
    src_obj = session.get(Source, source_id)
    if src_obj:
        src_obj.robots_checked = True
```

---

### WR-06: `scrapy_spider` SSRF middleware is registered by module path, but the module path changes when the file is run as `__main__`

**File:** `src/knowledge_lake/plugins/builtin/scrapy_spider.py:190-192`
**Issue:** The Scrapy settings register the middleware as:

```python
"DOWNLOADER_MIDDLEWARES": {
    "knowledge_lake.plugins.builtin.scrapy_spider.SSRFGuardMiddleware": 100,
},
```

But then the code does:

```python
SSRFGuardMiddleware.__module__ = __name__
```

When the spider is run as `python -m knowledge_lake.plugins.builtin.scrapy_spider`, `__name__` is `"__main__"`, not `"knowledge_lake.plugins.builtin.scrapy_spider"`. Setting `__module__ = "__main__"` means Scrapy's middleware loader will try to import `__main__.SSRFGuardMiddleware`, which fails silently (Scrapy may disable the middleware rather than crashing). The SSRF guard is then absent from all crawls.

**Fix:** Use the explicit module path:

```python
SSRFGuardMiddleware.__module__ = "knowledge_lake.plugins.builtin.scrapy_spider"
```

---

### WR-07: `crawl4ai_adapter` robots-blocked detection relies on undocumented Crawl4AI behaviour

**File:** `src/knowledge_lake/plugins/builtin/crawl4ai_adapter.py:116-126`
**Issue:** The adapter maps `success=False, status_code=403` to `robots_blocked`. This is documented in the code as "Assumption A3 from RESEARCH" — it is not part of the Crawl4AI public API contract. Any Crawl4AI upgrade may change this signalling (e.g., robots-blocked could become a different status code, or be surfaced differently). If the assumption breaks, robots-blocked pages will silently be recorded as `failed` with an opaque error message instead of `robots_blocked`, and the `robots_checked` count will be understated.

This is a quality and correctness risk rather than an immediate crash. The comment adequately documents the assumption, but there is no test that verifies the assumption still holds after a Crawl4AI upgrade.

**Fix:** Pin the assumption in an automated regression test that explicitly verifies the 403-to-robots_blocked mapping after each Crawl4AI version bump, or add a version assertion at module import time:

```python
import crawl4ai
_EXPECTED_CRAWL4AI_VERSION = "0.9"
assert crawl4ai.__version__.startswith(_EXPECTED_CRAWL4AI_VERSION), (
    f"Crawl4AI version changed; verify robots-blocked detection (A3)"
)
```

---

## Info

### IN-01: `ids.py` — `raw_document`, `parsed_document`, and `bronze_document` all produce `doc_` prefix, making IDs ambiguous

**File:** `src/knowledge_lake/ids.py:32-40`
**Issue:** Three different kinds share the `"doc"` prefix: `raw_document`, `parsed_document`, and `bronze_document`. A `doc_` ID in logs or API responses is ambiguous — the reader cannot tell whether it refers to a raw, parsed, or bronze artifact without a registry lookup.

**Fix:** Consider distinct prefixes: `raw_` for raw documents, `par_` for parsed, `bro_` for bronze, or at minimum document this as intentional in the code comment.

---

### IN-02: `api/app.py` — `on_event("startup")` is deprecated in FastAPI

**File:** `src/knowledge_lake/api/app.py:60`
**Issue:** `@app.on_event("startup")` is deprecated since FastAPI 0.93 in favour of the `lifespan` context manager pattern. In the pinned version (0.139.x) it still works but emits a deprecation warning.

**Fix:**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    settings = get_settings()
    logger.info("api.startup", ...)
    yield
    # shutdown (nothing needed yet)

app = FastAPI(..., lifespan=lifespan)
```

---

### IN-03: `scrapy_spider.py` — `_out_file` opened with `noqa: WPS515` suppresses a legitimate lint finding

**File:** `src/knowledge_lake/plugins/builtin/scrapy_spider.py:67`
**Issue:** The `# noqa: WPS515` comment suppresses a linter warning about opening a file without a `with` statement. The suppression hides the exact issue that CR-04 identifies. Suppressing linters to work around structural problems in code is a pattern that deserves scrutiny.

**Fix:** Once CR-04 is resolved (file handle in a `try/finally`), remove the `noqa` suppression.

---

### IN-04: `test_scrapy_subprocess.py` — `cmd[4]` assumes fixed argument position

**File:** `tests/integration/test_scrapy_subprocess.py:251`
**Issue:** The `fake_popen` function accesses `cmd[4]` to find the output JSONL path. The actual subprocess command is built as `[sys.executable, "-m", "module", source_url, str(out_jsonl), str(config_json)]`, making `cmd[4]` the `out_jsonl` argument. This hard-coded index is fragile: if the argument order changes (e.g., adding a flag before the URL), the test silently passes `config_json` as the output path, and the fake JSONL is written to the wrong file. The test would then fail on `get_results` with a cryptic error rather than a clear "wrong argument" failure.

**Fix:** Parse the command by argument name/position more defensively, or add an assertion:

```python
assert cmd[2].endswith("scrapy_spider"), f"Unexpected module in cmd: {cmd}"
out_jsonl_path = Path(cmd[4])  # source_url=cmd[3], out_jsonl=cmd[4]
```

---

_Reviewed: 2026-07-04T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
