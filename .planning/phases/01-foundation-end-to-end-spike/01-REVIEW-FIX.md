---
phase: 01-foundation-end-to-end-spike
fixed_at: 2026-07-03T00:00:00Z
review_path: .planning/phases/01-foundation-end-to-end-spike/01-REVIEW.md
iteration: 2
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-07-03
**Source review:** .planning/phases/01-foundation-end-to-end-spike/01-REVIEW.md
**Iteration:** 2

**Summary:**
- Findings in scope: 7 (2 Critical, 5 Warning)
- Fixed: 7
- Skipped: 0

## Fixed Issues

### CR-01: SSRF Guard Incomplete — Single IPv4 Address Check, No IPv6 / Rebinding Protection

**Files modified:** `src/knowledge_lake/pipeline/ingest.py`
**Commit:** `3474512`
**Applied fix:** Replaced `socket.gethostbyname()` with `socket.getaddrinfo(AF_UNSPEC, SOCK_STREAM)` to resolve all IPv4 and IPv6 addresses. Now iterates every returned `(family, type, proto, canonname, sockaddr)` entry, unwraps IPv4-mapped IPv6 addresses (`::ffff:10.x.x.x` to `10.x.x.x`) before the private-range check, and raises `ValueError` if any resolved address falls in a private/reserved range. Exception type narrowed from bare `except Exception` to `except socket.gaierror`. Also changed `retry=` predicate (WR-02) in the same commit since both changes are in ingest.py.

---

### CR-02: Dagster `ingest_raw_document` Asset Cannot Pass `robots_checked=True` — Field Missing from Config

**Files modified:** `src/knowledge_lake/dagster_defs/assets.py`
**Commit:** `15da121`
**Applied fix:** Added `robots_checked: bool = False` field with descriptive docstring to `IngestConfig`. In the URL branch of `ingest_raw_document`, added `robots_checked=config.robots_checked` to the `ingest_url()` call so operators who have verified `robots.txt` can set the flag and have it accurately recorded in the source registry.

---

### WR-01: `get_engine()` Not Thread-Safe — Double-Initialisation Window Under Concurrent Access

**Files modified:** `src/knowledge_lake/registry/db.py`
**Commit:** `086879c`
**Applied fix:** Added `import threading` and a module-level `_engine_lock = threading.Lock()`. Implemented double-checked locking in `get_engine()`: fast outer `if _engine is None` check (no lock), then `with _engine_lock:` followed by an inner `if _engine is None` check before calling `_build_engine()`. Prevents multiple uvicorn worker threads or parallel Dagster assets from creating duplicate engine instances and exhausting the PostgreSQL connection pool.

---

### WR-02: `_fetch_with_retry` Retries on `ValueError` from Size Cap — Wastes Bandwidth

**Files modified:** `src/knowledge_lake/pipeline/ingest.py`
**Commit:** `3474512` (combined with CR-01 fix)
**Applied fix:** Added `retry_if_exception_type` to the tenacity import and applied `retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException))` to the `@retry` decorator. Retries are now restricted to transient network errors; the permanent size-cap `ValueError` is surfaced immediately without re-downloading up to 50 MB per retry attempt.

---

### WR-03: `qdrant_store.py` — `PointStruct` and `VectorParams`/`Distance` Re-Imported on Every Call

**Files modified:** `src/knowledge_lake/plugins/builtin/qdrant_store.py`
**Commit:** `141a7d4`
**Applied fix:** Moved `from qdrant_client.models import Distance, PointStruct, VectorParams` into `__init__`. Stored them as `self._Distance`, `self._PointStruct`, `self._VectorParams`. Updated `ensure_collection()` to use `self._Distance` and `self._VectorParams`, and `upsert()` to use `self._PointStruct`. Removed both local per-call imports. Pattern is now consistent with the `QdrantClient` import already in `__init__`.

---

### WR-04: `collection` Parameter in `/search` API Endpoint Has No Format Validation

**Files modified:** `src/knowledge_lake/api/app.py`
**Commit:** `e1b9029`
**Applied fix:** Added `import re` and a module-level `_COLLECTION_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")`. Inside `search_endpoint`, added a `_COLLECTION_NAME_RE.fullmatch(collection)` check before delegating to `search()`. Returns HTTP 422 with `"Invalid collection name format."` for names that fail the check. Closes the collection enumeration vector and aligns with ASVS V5 / T-01-14.

---

### WR-05: `conftest.py` `settings` Fixture Exits `patch.dict` Before Yielding

**Files modified:** `tests/conftest.py`
**Commit:** `9a7d2ff`
**Applied fix:** Converted the `settings` fixture from a plain `return` function to a `yield` generator fixture. The `patch.dict(os.environ, test_env, clear=False)` context manager now wraps the `yield s` so `os.environ` retains the test overrides for the complete test body. Added `_db._engine = None` reset before yielding and in teardown. Teardown runs `get_settings.cache_clear()` and `_db._engine = None` after the `with` block exits so the patched settings do not leak into subsequent tests.

---

_Fixed: 2026-07-03_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
