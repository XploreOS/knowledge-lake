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
  - src/knowledge_lake/plugins/builtin/searxng_discovery.py
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
  - src/knowledge_lake/plugins/builtin/scrapy_spider.py
  - src/knowledge_lake/crawl/select.py
  - src/knowledge_lake/api/app.py
  - src/knowledge_lake/pipeline/crawl.py
findings:
  critical: 5
  warning: 5
  info: 3
  total: 13
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-07-04T00:00:00Z
**Depth:** standard
**Files Reviewed:** 46
**Status:** issues_found

## Summary

The phase 02 ingestion implementation is architecturally sound. SSRF guards, robots.txt compliance,
dedup at URL and hash level, three-tier rate limiting, and lineage tracking are all present and
correctly integrated in most paths. However five blockers were found that cause crashes or constitute
exploitable security vulnerabilities, plus five warnings that degrade correctness or robustness.

Key blocker summary:

1. **Arbitrary file read** — The `/uploads` API endpoint accepts an arbitrary server-side filesystem
   path with no validation or allow-list, enabling any caller to read files outside the upload root.
2. **Scrapy SSRF guard is dead code** — `SSRFGuardMiddleware` is a locally-scoped class inside
   `_run_scrapy()`; Scrapy loads middleware by module attribute lookup and cannot find it, silently
   omitting SSRF protection for all Scrapy-crawled URLs.
3. **Runtime crash on every POST /crawl-jobs** — `crawl_source` calls `asyncio.run()` which raises
   `RuntimeError` when already inside a running event loop (every uvicorn async handler).
4. **SSRF bypass in `probe_site`** — `probe_site` validates the seed URL before fetching but then
   uses `follow_redirects=True` on all three probes without re-validating redirect targets, allowing
   a 302 to an RFC-1918 address to bypass the guard.
5. **Hardcoded SearXNG secret** — A known-value `secret_key` is committed in the repository and
   used unless explicitly overridden.

---

## Critical Issues

### CR-01: `/uploads` endpoint accepts arbitrary server-side filesystem paths — arbitrary file read

**File:** `src/knowledge_lake/api/app.py:194`

**Issue:** The `POST /uploads` handler accepts `file_path: str = Query(...)` described as "Absolute
path to the file on the server filesystem." No path-prefix restriction, allow-list, or authentication
guard is applied. The raw value is passed directly to `ingest_file`:

```python
result = ingest_file(Path(file_path), source_url=body.source_url, ...)
```

Any caller — including unauthenticated callers if no auth middleware is deployed — can supply
`/etc/passwd`, `/etc/shadow`, `~/.ssh/id_rsa`, or any other path readable by the server process.
The file contents are uploaded to S3 and registered in the artifact registry, exfiltrating them.

**Fix:** Constrain accepted paths to a configured upload root and reject anything outside it:

```python
from pathlib import Path

UPLOAD_ROOT = settings.upload_root   # e.g. Path("/data/uploads") from config

def _safe_upload_path(raw: str) -> Path:
    p = Path(raw).resolve()
    if not str(p).startswith(str(UPLOAD_ROOT.resolve())):
        raise HTTPException(
            status_code=400,
            detail=f"Path is outside the allowed upload directory.",
        )
    return p

# In the handler:
safe_path = _safe_upload_path(file_path)
result = ingest_file(safe_path, ...)
```

Alternatively, replace the filesystem-path parameter with a standard multipart file upload so the
server never touches arbitrary caller-supplied paths.

---

### CR-02: `asyncio.run()` inside `crawl_source` crashes every `POST /crawl-jobs` at runtime

**File:** `src/knowledge_lake/pipeline/crawl.py:105`
**Also:** `src/knowledge_lake/api/app.py:307`

**Issue:** `crawl_source` is a synchronous function that calls `asyncio.run(_crawl_loop(...))`.
The FastAPI handler `create_crawl_job_endpoint` (api/app.py line 289) is declared `async def` and
calls `crawl_source(...)` directly with no `await` and no thread hand-off. Under uvicorn/anyio,
every `async def` handler runs inside a running event loop. Python 3.10+ raises:

```
RuntimeError: asyncio.run() cannot be called when another event loop is running
```

Every `POST /crawl-jobs` request returns HTTP 500. The CLI path works because it has no running
loop when `crawl_source` is called.

**Fix — Option A (recommended):** Declare `crawl_source` as `async def` and `await` the loop:

```python
# pipeline/crawl.py
async def crawl_source(source_url, *, crawler=None, settings=None, max_pages=None):
    ...
    stats = await _crawl_loop(...)
    return stats

# api/app.py — already async, just await
result = await crawl_source(body.source_url, ...)

# cli/app.py — wrap for sync context
import asyncio
result = asyncio.run(crawl_source(url, ...))
```

**Fix — Option B:** Keep `crawl_source` synchronous and dispatch it to a threadpool from the async
handler so `asyncio.run()` has no running loop in the worker thread:

```python
# api/app.py
import asyncio
result = await asyncio.get_running_loop().run_in_executor(
    None, lambda: crawl_source(body.source_url, ...)
)
```

---

### CR-03: Scrapy `SSRFGuardMiddleware` is a locally-scoped class — Scrapy cannot load it; SSRF protection is absent in all Scrapy crawls

**File:** `src/knowledge_lake/plugins/builtin/scrapy_spider.py:74–202`

**Issue:** `SSRFGuardMiddleware` is defined inside the `_run_scrapy()` function body (line 74), making
it a local variable, not a module-level attribute. It is registered in Scrapy's settings as:

```python
"DOWNLOADER_MIDDLEWARES": {
    "knowledge_lake.plugins.builtin.scrapy_spider.SSRFGuardMiddleware": 100,
},
```

Scrapy resolves middleware strings by doing:

```python
module = importlib.import_module("knowledge_lake.plugins.builtin.scrapy_spider")
cls = getattr(module, "SSRFGuardMiddleware")   # AttributeError — not a module attribute
```

The assignment `SSRFGuardMiddleware.__module__ = __name__` (line 202) only updates the class's
`__module__` metadata attribute (used for `repr` and `pickle`) and does **not** inject the class
into the module's namespace. Scrapy raises `AttributeError`, typically causing it to skip or
disable the middleware silently, leaving every URL crawled by Scrapy without SSRF validation.

No test detects this because `test_scrapy_subprocess.py` mocks `subprocess.Popen` and never
executes real Scrapy middleware loading.

**Fix:** Move `SSRFGuardMiddleware` to module level (outside any function):

```python
# TOP-LEVEL — not inside _run_scrapy()
class SSRFGuardMiddleware:
    """Block requests to private/internal addresses (T-02-15)."""

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_request(self, request, spider):
        from knowledge_lake.pipeline.ingest import validate_public_url
        try:
            validate_public_url(request.url)
        except ValueError as exc:
            from scrapy.exceptions import IgnoreRequest
            raise IgnoreRequest(str(exc)) from exc
```

Remove the `SSRFGuardMiddleware.__module__ = __name__` line; it is no longer needed.

---

### CR-04: `probe_site` follows redirects without re-validating target IPs — SSRF bypass

**File:** `src/knowledge_lake/crawl/select.py:183–222`

**Issue:** `probe_site` calls `validate_public_url(url)` on the seed URL (line 183) and then
makes all three probes with `follow_redirects=True`:

```python
entry_resp = httpx.get(url, timeout=_PROBE_TIMEOUT, follow_redirects=True)      # line 190
robots_resp = httpx.get(robots_url, timeout=_PROBE_TIMEOUT, follow_redirects=True)   # line 201
sitemap_resp = httpx.get(sitemap_url, timeout=_PROBE_TIMEOUT, follow_redirects=True)  # line 218
```

If any of these URLs responds with a 301/302 to `http://169.254.169.254/latest/meta-data/` or any
RFC-1918 address, `httpx` follows the redirect without re-validating the resolved Location header.
The initial `validate_public_url` guard is bypassed.

This is the exact scenario that `_fetch_with_retry` in `pipeline/ingest.py` was hardened against by
manually following each hop and re-calling `validate_public_url` on each Location header. `probe_site`
does not apply the same discipline.

**Fix:** Replace `follow_redirects=True` with manual hop-by-hop redirect following, re-validating
each Location header:

```python
def _safe_get(url: str, timeout: float) -> httpx.Response:
    """GET url, re-validating SSRF guard on each redirect hop."""
    from knowledge_lake.pipeline.ingest import validate_public_url
    with httpx.Client(follow_redirects=False) as client:
        for _ in range(10):   # max redirects
            resp = client.get(url, timeout=timeout)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location", "")
                validate_public_url(location)   # raises on private IP
                url = location
                continue
            return resp
    raise ValueError("Too many redirects")
```

Use `_safe_get` in place of all three `httpx.get(..., follow_redirects=True)` calls.

---

### CR-05: Hardcoded SearXNG `secret_key` committed in the repository

**File:** `infra/searxng/settings.yml:16`

**Issue:**

```yaml
secret_key: "klake-dev-searxng-secret-change-in-production"
```

This key is committed to source control and becomes the default for any deployment that mounts
this file without explicitly setting `SEARXNG_SECRET`. SearXNG uses it to sign CSRF tokens and
session cookies. An attacker who can read this repository can forge any SearXNG session or CSRF
token against any deployment using the default key.

**Fix:** Replace the literal with a template that forces an explicit override:

```yaml
# REQUIRED before any non-local deployment.
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
# Then set the SEARXNG_SECRET environment variable.
secret_key: "${SEARXNG_SECRET:?SEARXNG_SECRET environment variable must be set}"
```

Alternatively remove the `secret_key` line entirely; SearXNG will refuse to start without it,
making misconfigured deployments loud rather than silently insecure.

---

## Warnings

### WR-01: Operator precedence bug in `effective_name` — IndexError on path-only URLs

**File:** `src/knowledge_lake/api/app.py:171`
**Also:** `src/knowledge_lake/cli/app.py:70`

**Issue:** Both files contain:

```python
effective_name = body.name or body.url.split("/")[2] if "/" in body.url else body.url
```

Python parses the ternary operator with lower precedence than `or`, yielding:

```python
effective_name = (body.name or body.url.split("/")[2]) if ("/" in body.url) else body.url
```

Two problems with this expression:

1. When `body.url` is a path-only string like `"/some/path"` (contains `/` but no host component),
   `split("/")[2]` yields the first path segment (`"some"`), not the hostname. This silently records
   wrong metadata.
2. If `body.url` is `"/"` (one slash), `split("/")` produces `["", ""]` — `[2]` raises `IndexError`,
   crashing the endpoint.

**Fix:** Use `urlparse` for safe hostname extraction at both call sites:

```python
from urllib.parse import urlparse
effective_name = body.name or (urlparse(body.url).hostname or body.url)
```

---

### WR-02: All async FastAPI handlers call blocking synchronous pipeline functions — event loop starvation

**File:** `src/knowledge_lake/api/app.py:119–147, 173–184, 221–231, 258–262, 305–311`

**Issue:** Every `async def` handler directly calls synchronous blocking functions:

- `search(...)` — database + vector store I/O
- `register_source(...)` — database + network I/O
- `ingest_file(...)` — filesystem + HTTP + database I/O
- `discover_sources(...)` — HTTP + database I/O
- `resolve_ancestry(...)` — recursive database I/O

Blocking synchronous calls inside `async def` handlers block uvicorn's event loop for the duration
of each call. Under concurrent load, all other requests queue behind each slow handler.

**Fix:** Dispatch blocking work to the default thread pool executor:

```python
import asyncio

# In each async handler:
result = await asyncio.get_running_loop().run_in_executor(
    None, lambda: register_source(body.url, name=effective_name)
)
```

FastAPI also supports declaring handlers as plain `def` (non-async); FastAPI automatically
dispatches them to a thread pool, making this the simplest fix for handler bodies that are
entirely synchronous:

```python
@app.post("/sources", ...)
def create_source_endpoint(body: SourceCreate) -> dict:   # sync, not async
    ...
```

---

### WR-03: `_record_state` accepts `error` parameter but never forwards it to `upsert_crawl_state` — failures are undiagnosable

**File:** `src/knowledge_lake/pipeline/crawl.py:361–388`
**Also:** `src/knowledge_lake/registry/models.py`, `src/knowledge_lake/registry/repo.py`

**Issue:** `_record_state` has signature `(job_id, url, state, *, error=None)`. It is called with
error messages at lines 244, 280, and 289 when SSRF guard, adapter error, or other failures occur.
The function body never passes `error` to `upsert_crawl_state`, and `CrawlState` has no `error_msg`
column. All failure reasons are silently discarded from the database.

**Impact:** Operators debugging a failed crawl cannot see which URLs failed or why without
re-running the crawl or scanning logs. This makes production triage of large-scale crawl failures
effectively impossible from the registry alone.

**Fix:** Add `error_msg` to `CrawlState`, extend `upsert_crawl_state` to accept and persist it,
and wire through in `_record_state`:

```python
# registry/models.py — add column
error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

# registry/repo.py — extend upsert signature
def upsert_crawl_state(..., error_msg: Optional[str] = None) -> CrawlState:
    ...
    obj.error_msg = error_msg

# pipeline/crawl.py — forward in _record_state
registry_repo.upsert_crawl_state(session, ..., error_msg=error)
```

A new Alembic migration is required to add the column.

---

### WR-04: `_run_scrapy` opens `_out_file` without `try/finally` — file handle leaked on exception

**File:** `src/knowledge_lake/plugins/builtin/scrapy_spider.py:67`

**Issue:**

```python
_out_file = open(out_jsonl, "w", encoding="utf-8")   # no context manager, no try/finally
```

The file is closed inside `KlakeSpider.closed()` (Scrapy's spider-done signal callback). If
`CrawlerProcess(settings=settings_dict)` raises before the spider's `closed` signal fires — for
example because the `SSRFGuardMiddleware` class is unresolvable (see CR-03) — `_out_file` is
never closed. The file descriptor leaks in the subprocess and the empty/partial output file is
indistinguishable from a zero-result crawl, masking the underlying error.

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

### WR-05: `_fetch_with_retry` does not close streaming response on 4xx/5xx — HTTP connection leak

**File:** `src/knowledge_lake/pipeline/ingest.py:193–211`

**Issue:** When a non-redirect response arrives, the code calls `resp.raise_for_status()` and then
reads the body with `resp.iter_bytes()`. If `raise_for_status()` raises (4xx or 5xx), the streaming
response object `resp` is never closed: there is no `finally` block and no context manager wrapping
the streaming section. On HTTP/1.1, the unread response body prevents connection keep-alive reuse;
on HTTP/2 it leaves a stream open until timeout.

This does not affect the correctness of the SSRF guard (redirect validation is sound), but under
retried requests (`@retry`) each failed attempt may leak a connection. The tenacity retry decorator
will retry the same request up to `stop_after_attempt(3)` times, potentially leaking three
connections per invocation.

**Fix:** Wrap the streaming body read in `try/finally`:

```python
resp.raise_for_status()
content_type = resp.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
chunks: list[bytes] = []
total = 0
try:
    for chunk in resp.iter_bytes():
        total += len(chunk)
        if total > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"Download exceeded size cap {MAX_DOWNLOAD_BYTES}")
        chunks.append(chunk)
finally:
    resp.close()
return b"".join(chunks), content_type
```

---

## Info

### IN-01: `raw_document`, `parsed_document`, and `bronze_document` share the `"doc_"` ID prefix — ambiguous in logs

**File:** `src/knowledge_lake/ids.py:32–40`

**Issue:** Three distinct artifact kinds all map to the `"doc"` prefix, so any `doc_XXXX` ID in a
log line or API response is ambiguous without a registry lookup. Operators cannot tell from the ID
alone whether a given artifact is a raw HTML download, a Docling-parsed document, or a bronze
markdown artifact.

**Fix:** Use distinct per-kind prefixes (`raw_`, `par_`, `bro_`) or add a comment explicitly
documenting why sharing a prefix is intentional (e.g., "all are documents in the lineage chain,
type is always co-stored with the ID").

---

### IN-02: `@app.on_event("startup")` is deprecated since FastAPI 0.93

**File:** `src/knowledge_lake/api/app.py:60`

**Issue:** `@app.on_event("startup")` emits a `DeprecationWarning` in the pinned FastAPI 0.139.x.
The preferred pattern is the `lifespan` context manager.

**Fix:**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_logging()
    log.info("api.startup", version=APP_VERSION)
    yield

app = FastAPI(title="Knowledge Lake API", lifespan=lifespan)
```

---

### IN-03: `scrapy_spider._registrable_domain` uses `urlparse.hostname` instead of `tldextract`

**File:** `src/knowledge_lake/plugins/builtin/scrapy_spider.py:41`

**Issue:**

```python
def _registrable_domain(url: str) -> str:
    return urlparse(url).hostname or ""
```

The rest of the codebase (e.g., `ratelimit.py`) uses `tldextract` to extract the registrable
domain (e.g., `example.co.uk` → `example.co.uk` not just `co.uk`). Using raw `hostname` returns
the full hostname including subdomains (`www.example.com`), causing per-subdomain domain-key
partitioning in the Scrapy rate-limiter bucket instead of per-registrable-domain partitioning.
This inconsistency could allow a site to effectively avoid per-domain rate limits by rotating
subdomains.

**Fix:** Use `tldextract` consistently:

```python
import tldextract

def _registrable_domain(url: str) -> str:
    ext = tldextract.extract(url)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}"
    return urlparse(url).hostname or ""
```

---

_Reviewed: 2026-07-04T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
