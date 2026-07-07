---
phase: 01-foundation-end-to-end-spike
reviewed: 2026-07-03T00:00:00Z
depth: standard
files_reviewed: 32
files_reviewed_list:
  - src/knowledge_lake/__init__.py
  - src/knowledge_lake/config/settings.py
  - src/knowledge_lake/ids.py
  - src/knowledge_lake/version.py
  - src/knowledge_lake/lineage.py
  - src/knowledge_lake/pipeline/ingest.py
  - src/knowledge_lake/pipeline/parse.py
  - src/knowledge_lake/pipeline/chunk.py
  - src/knowledge_lake/pipeline/embed.py
  - src/knowledge_lake/pipeline/index.py
  - src/knowledge_lake/pipeline/search.py
  - src/knowledge_lake/pipeline/run.py
  - src/knowledge_lake/plugins/protocols.py
  - src/knowledge_lake/plugins/resolver.py
  - src/knowledge_lake/plugins/builtin/docling_parser.py
  - src/knowledge_lake/plugins/builtin/st_embedder.py
  - src/knowledge_lake/plugins/builtin/qdrant_store.py
  - src/knowledge_lake/registry/models.py
  - src/knowledge_lake/registry/repo.py
  - src/knowledge_lake/registry/db.py
  - src/knowledge_lake/registry/alembic/env.py
  - src/knowledge_lake/registry/alembic/versions/0001_core_schema.py
  - src/knowledge_lake/storage/s3.py
  - src/knowledge_lake/storage/bootstrap.py
  - src/knowledge_lake/api/app.py
  - src/knowledge_lake/api/schemas.py
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/dagster_defs/assets.py
  - src/knowledge_lake/dagster_defs/definitions.py
  - src/knowledge_lake/dagster_defs/resources.py
  - tests/conftest.py
  - docker-compose.yml
  - pyproject.toml
findings:
  critical: 2
  warning: 5
  info: 3
  total: 10
status: issues_found
---

# Phase 01: Code Review Report (Iteration 2)

**Reviewed:** 2026-07-03
**Depth:** standard
**Files Reviewed:** 32
**Status:** issues_found

## Summary

This is the second-pass review after the iteration 1 fixes were applied. Every targeted
fix from iteration 1 was inspected. Fifteen of the sixteen targeted items closed cleanly.
One iteration-1 fix (CR-01 SSRF) was applied but remains incomplete — it uses
`socket.gethostbyname()` which only checks a single IPv4 address and does not handle
IPv6 or DNS rebinding. One new data-integrity gap was found in the Dagster ingest path
(CR-02). Five warnings and three info items remain or are newly identified.

**Iteration 1 fix verification:**

| ID | Description | Status |
|----|-------------|--------|
| CR-01 | SSRF private-IP blocking | Partial — see new CR-01 below |
| CR-02 | Session race consolidated | Closed |
| CR-03 | Plugin URL injection via constructor | Closed |
| CR-04 | Dagster `deps=` removed | Closed |
| CR-05 | Lazy engine init | Closed |
| CR-06 | LIKE wildcard escaping | Closed |
| CR-07 | `robots_checked=False` | Closed |
| CR-08 | `TemporaryDirectory` context manager | Closed |
| CR-09 | `dim` validation in LiteLLMEmbedder | Closed |
| WR-01 | JSON renderer for non-tty | Closed |
| WR-02 | `StorageSettings` to `BaseModel` | Closed |
| WR-03 | LRU cache cleared in conftest | Closed |
| WR-05 | `parent_artifact_id` in chunk dedup hash | Closed |
| WR-07 | `PointStruct` import removed from `search()` | Closed |
| WR-08 | MIME detection from `Content-Type` | Closed |
| WR-09 | No `minioadmin` defaults in compose | Closed |

---

## Critical Issues

### CR-01: SSRF Guard Incomplete — Single IPv4 Address Check, No IPv6 / Rebinding Protection

**File:** `src/knowledge_lake/pipeline/ingest.py:78`
**Issue:** The fix from iteration 1 calls `socket.gethostbyname(hostname)` which resolves
only one IPv4 address. This leaves three real attack vectors open:

1. **DNS rebinding**: A hostname that initially resolves to a public IP passes the check;
   the subsequent `httpx.stream()` call (which re-resolves DNS independently) may get a
   private IP if the attacker's DNS TTL expired between the two lookups.
2. **IPv6 only hostnames**: `gethostbyname` raises an exception for hostnames that have
   only AAAA records. The exception is caught and converted to `ValueError("Cannot resolve
   hostname")` — safe but silent on IPv6-only targets rather than a specific SSRF message.
3. **IPv4-mapped IPv6 addresses**: A hostname that resolves via `getaddrinfo` to
   `::ffff:10.0.0.1` (an IPv4-mapped IPv6 address) is not detected by the current check
   because `gethostbyname` returns `10.0.0.1` (which *is* in `_PRIVATE_NETS`) on most
   systems — but `gethostbyname` behaviour is OS-dependent and not guaranteed on all
   Linux distributions, particularly when `nsswitch.conf` prefers IPv6.

The robust fix is `socket.getaddrinfo()` which returns all addresses (IPv4 + IPv6) and
is immune to the single-address limitation.

**Fix:**
```python
def _validate_url_scheme(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(
            f"ingest_url rejected URL with scheme {parsed.scheme!r}. "
            "Only https:// URLs are allowed (SSRF prevention, T-01-11)."
        )
    hostname = parsed.hostname or ""
    try:
        # getaddrinfo returns ALL resolved addresses (IPv4 + IPv6)
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(
            f"Cannot resolve hostname {hostname!r}: {exc}"
        ) from exc
    if not infos:
        raise ValueError(f"No addresses resolved for hostname {hostname!r}")
    for (_family, _type, _proto, _canonname, sockaddr) in infos:
        raw_addr = sockaddr[0]
        addr = ipaddress.ip_address(raw_addr)
        # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:10.0.0.1 -> 10.0.0.1)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        for net in _PRIVATE_NETS:
            if addr in net:
                raise ValueError(
                    f"URL {url!r} resolves to private/link-local address {addr} — "
                    "SSRF prevention blocks requests to private networks (T-01-11)."
                )
```

---

### CR-02: Dagster `ingest_raw_document` Asset Cannot Pass `robots_checked=True` — Field Missing from Config

**File:** `src/knowledge_lake/dagster_defs/assets.py:139-143`
**Issue:** The `IngestConfig` Dagster `Config` class has no `robots_checked` field. When
`ingest_url` is called from the Dagster asset path, `robots_checked` is not forwarded — it
defaults to `False` inside `ingest_url`. This is the safe default and technically correct,
but it creates an operational gap: operators who have manually verified `robots.txt`
**cannot** mark Dagster-ingested sources as `robots_checked=True`. Every source registered
via Dagster will permanently have `robots_checked=False` in the registry, making the
compliance field misleading and preventing accurate tracking. The CLI path and the
`ingest_url` function signature both support the parameter — only the Dagster config is missing it.

**Fix:** Add `robots_checked: bool = False` to `IngestConfig` and thread it through:
```python
class IngestConfig(Config):
    fixture_path: Optional[str] = None
    url: Optional[str] = None
    source_name: Optional[str] = None
    collection: str = DEFAULT_COLLECTION
    mime_type: str = "application/pdf"
    robots_checked: bool = False
    """Set True only after verifying the target URL's robots.txt (Phase 2)."""

# In ingest_raw_document asset, URL branch:
result = ingest_url(
    config.url,
    config.source_name or config.url,
    mime_type=config.mime_type,
    robots_checked=config.robots_checked,  # forward the field
    settings=settings,
)
```

---

## Warnings

### WR-01: `get_engine()` Not Thread-Safe — Double-Initialisation Window Under Concurrent Access

**File:** `src/knowledge_lake/registry/db.py:56-59`
**Issue:** The lazy engine check-and-set uses no lock:
```python
if _engine is None:
    _engine = _build_engine()
```
Under concurrent request handling (multiple uvicorn worker threads in the same process,
or Dagster executing assets in parallel), two threads can simultaneously observe
`_engine is None` and both call `_build_engine()`. The second engine is immediately
discarded, but both have already opened connection-pool connections, wasting connections
against a limited PostgreSQL pool. This will not cause a crash but violates the
"single engine" invariant stated in the module docstring and can exhaust the pool under
burst load in production.

**Fix:**
```python
import threading
_engine: Engine | None = None
_engine_lock = threading.Lock()

def get_engine() -> Engine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:   # double-checked locking
                _engine = _build_engine()
    return _engine
```

---

### WR-02: `_fetch_with_retry` Retries on `ValueError` from Size Cap — Wastes Bandwidth

**File:** `src/knowledge_lake/pipeline/ingest.py:91-119`
**Issue:** The `@retry` decorator has no `retry=` predicate, so by default Tenacity
retries on **all** exceptions including `ValueError`. When a 200 MB document exceeds
`MAX_DOWNLOAD_BYTES`, `_fetch_with_retry` raises `ValueError("Download ... exceeded size
cap")`. Tenacity retries this up to 3 times total, re-downloading up to 50 MB per
attempt — 100 MB of wasted bandwidth per oversized URL. The size cap is a permanent
condition (not a transient network error), so retrying it is semantically wrong.

**Fix:**
```python
from tenacity import retry_if_exception_type
import httpx

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    reraise=True,
)
def _fetch_with_retry(url: str) -> tuple[bytes, str]:
    ...
```

---

### WR-03: `qdrant_store.py` — `PointStruct` and `VectorParams`/`Distance` Re-Imported on Every Call

**File:** `src/knowledge_lake/plugins/builtin/qdrant_store.py:60-61, 90`
**Issue:** After the WR-07 fix moved `PointStruct` inside `upsert()`, the pattern now
imports `Distance` and `VectorParams` inside `ensure_collection()` and `PointStruct`
inside `upsert()`. Python's module import system caches modules in `sys.modules`, so
these calls do not re-execute module code — but the attribute lookup on the module object
still occurs on every `upsert()` and `ensure_collection()` call. In high-throughput
indexing (thousands of upsert batches) this adds up. More importantly, the repeated local
import pattern is inconsistent with the `QdrantClient` import in `__init__` and will
confuse future maintainers.

**Fix:** Consolidate all `qdrant_client` imports into `__init__`:
```python
def __init__(self, qdrant_url: str = "http://localhost:6333") -> None:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams
    self._PointStruct = PointStruct
    self._Distance = Distance
    self._VectorParams = VectorParams
    self._client = QdrantClient(url=qdrant_url)
    log.debug("qdrant_store.connect", url=qdrant_url)
```

---

### WR-04: `collection` Parameter in `/search` API Endpoint Has No Format Validation

**File:** `src/knowledge_lake/api/app.py:78-82`
**Issue:** The `collection` query parameter is a free-form string passed directly to
`vstore.search(collection_name=collection, ...)`. There is no validation against a
permitted list or a format regex. An attacker can supply arbitrary collection names to
enumerate Qdrant collections. While this is a read-only operation and Qdrant does not
expose sensitive data by default, in a multi-tenant deployment it would allow cross-tenant
collection access. Even in the Phase 1 single-tenant deployment, the API should reject
obviously malformed collection names to provide a cleaner security boundary.

**Fix:** Add a format constraint:
```python
import re
_COLLECTION_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# In the handler, before calling search():
if not _COLLECTION_NAME_RE.fullmatch(collection):
    raise HTTPException(status_code=422, detail="Invalid collection name format.")
```

---

### WR-05: `conftest.py` `settings` Fixture Exits `patch.dict` Before Yielding — `get_settings()` Calls in Test Body See Unpatched Env

**File:** `tests/conftest.py:78-95`
**Issue:** The `settings` fixture enters `patch.dict(os.environ, test_env)` as a context
manager, clears the LRU cache, constructs `s = Settings(_env_file=None)`, then the `with`
block **exits** before returning `s`. After the `with` block exits, `os.environ` no longer
has the test overrides. Any code under test that subsequently calls `get_settings()` will
construct a fresh `Settings` from the **unpatched** environment (thanks to
`_clear_settings_cache` having cleared the LRU cache). The returned `s` value is correct
for tests that pass it as an argument, but the global `get_settings()` singleton and the
lazy engine will pick up the wrong URL for any module that calls `get_settings()` directly
(e.g., `storage/bootstrap.py`, `pipeline/run.py`).

**Fix:** Convert to a `yield` fixture so `patch.dict` spans the full test body:
```python
@pytest.fixture
def settings():
    from knowledge_lake.config.settings import Settings, get_settings
    test_env = {
        "KLAKE_DATABASE_URL": "postgresql+psycopg://klake:klake@localhost:5432/klake_test",
        ...
    }
    with patch.dict(os.environ, test_env, clear=False):
        get_settings.cache_clear()
        import knowledge_lake.registry.db as _db
        _db._engine = None
        s = Settings(_env_file=None)
        yield s
    get_settings.cache_clear()
```

---

## Info

### IN-01: `app.on_event("startup")` Is Deprecated in FastAPI 0.93+ — Will Warn in Production Logs

**File:** `src/knowledge_lake/api/app.py:41`
**Issue:** `@app.on_event("startup")` has been deprecated since FastAPI 0.93.0 in favour
of `lifespan` context managers. The project pins FastAPI 0.139.0, where `on_event` still
works but emits a `DeprecationWarning` on startup. This warning pollutes production
structured logs and may trigger false alerts in monitoring systems.

**Fix:**
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("api.startup", ...)
    yield

app = FastAPI(..., lifespan=lifespan)
# Remove the @app.on_event("startup") function entirely.
```

---

### IN-02: `ids.py` — `raw_document` and `parsed_document` Share the `doc_` Prefix — IDs Not Self-Describing

**File:** `src/knowledge_lake/ids.py:31-37`
**Issue:** Both `"raw_document"` and `"parsed_document"` map to the prefix `"doc"`. The
module docstring claims IDs are "self-describing" so "logs and CLI output are
self-describing," but a `doc_019f...` ID in a log line is ambiguous between two distinct
artifact types. The `_expand_prefix` logic in `lineage.py` searches by prefix regardless
of type, so an ambiguous prefix like `doc_019f` could match either type and confuse
lineage resolution.

**Fix:** Assign a distinct prefix to parsed documents:
```python
_PREFIX = {
    "source":           "src",
    "raw_document":     "raw",   # was "doc"
    "parsed_document":  "prs",   # was "doc"
    "chunk":            "chk",
    "artifact":         "art",
}
```
Note: this is a breaking schema change if any data already exists; apply via migration.

---

### IN-03: `version.py` — `subprocess` Spawned on Every Artifact Write, No Memoization

**File:** `src/knowledge_lake/version.py:31-63`
**Issue:** `pipeline_version()` is called by `_make_artifact()` in `repo.py` for every
artifact row created (raw, parsed, chunk). Each call forks a `git rev-parse` subprocess
bounded to 2 seconds. A document producing 50 chunks spawns 52 subprocesses per pipeline
run. The result is constant within a process lifetime; there is no reason to re-fork.

**Fix:**
```python
import functools

@functools.cache       # Python 3.9+ equivalent of lru_cache(maxsize=None)
def pipeline_version() -> str:
    ...
```

---

_Reviewed: 2026-07-03_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Iteration: 2 (post-fix re-review)_
