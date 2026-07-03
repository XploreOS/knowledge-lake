---
phase: 01-foundation-end-to-end-spike
reviewed: 2026-07-03T12:00:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - src/knowledge_lake/__init__.py
  - src/knowledge_lake/config/settings.py
  - src/knowledge_lake/pipeline/ingest.py
  - src/knowledge_lake/pipeline/parse.py
  - src/knowledge_lake/pipeline/chunk.py
  - src/knowledge_lake/plugins/builtin/st_embedder.py
  - src/knowledge_lake/plugins/builtin/qdrant_store.py
  - src/knowledge_lake/plugins/resolver.py
  - src/knowledge_lake/dagster_defs/assets.py
  - src/knowledge_lake/registry/db.py
  - src/knowledge_lake/lineage.py
  - src/knowledge_lake/plugins/builtin/docling_parser.py
  - src/knowledge_lake/api/app.py
  - src/knowledge_lake/api/schemas.py
  - tests/conftest.py
  - docker-compose.yml
findings:
  critical: 0
  warning: 0
  info: 3
  total: 3
status: clean
---

# Phase 01: Code Review Report (Iteration 3 — Final)

**Reviewed:** 2026-07-03T12:00:00Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** clean

## Summary

This is the iteration 3 re-review, verifying that all seven targeted fixes from iteration 2
were applied correctly. All seven are confirmed closed. No new Critical or Warning findings
were identified. Three pre-existing Info items carry forward from prior iterations; none of
these require blocking action before the phase is considered complete.

**Iteration 2 fix verification:**

| ID | Description | Status |
|----|-------------|--------|
| CR-01 | SSRF: `getaddrinfo` + IPv4-mapped IPv6 unwrap | Closed — `ingest.py:85` uses `socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)` and `ingest.py:97-98` unwraps `addr.ipv4_mapped`; `_PRIVATE_NETS` covers `::1/128` and `fc00::/7`. |
| CR-02 | `robots_checked` field in `IngestConfig` | Closed — `assets.py:75` declares `robots_checked: bool = False`; `assets.py:147` forwards it to `ingest_url`. |
| WR-01 | `threading.Lock` around lazy engine init | Closed — `db.py:48` declares `_engine_lock = threading.Lock()`; `db.py:65-66` implements double-checked locking. |
| WR-02 | `retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException))` | Closed — `ingest.py:110` uses this exact predicate; `ValueError` (size-cap) is no longer retried. `httpx.HTTPStatusError` is a subclass of `httpx.HTTPError` so non-2xx responses are still retried correctly. |
| WR-03 | `qdrant_client` models imported once in `__init__` | Closed — `qdrant_store.py:42-47` imports `Distance`, `PointStruct`, `VectorParams` in `__init__` and stashes them as `self._Distance`, `self._PointStruct`, `self._VectorParams`; no further per-call imports in `ensure_collection` or `upsert`. |
| WR-04 | `_COLLECTION_NAME_RE` regex validates `collection` param in `/search` | Closed — `app.py:35` compiles `^[a-zA-Z0-9_-]{1,64}$`; `app.py:109-110` applies `fullmatch` and raises HTTP 422 on failure. |
| WR-05 | `settings` fixture `yield` scope | Closed — `conftest.py:96-101` wraps `patch.dict` and `yield s` inside the same `with` block, keeping the env override active for the full test body. |

---

## Narrative Findings (AI reviewer)

No Critical or Warning findings remain.

## Info

### IN-01: `app.on_event("startup")` Is Deprecated in FastAPI 0.93+

**File:** `src/knowledge_lake/api/app.py:46`
**Issue:** `@app.on_event("startup")` is deprecated since FastAPI 0.93.0. The project pins
FastAPI 0.139.0 where the decorator still functions but emits a `DeprecationWarning` on
startup, polluting structured production logs.
**Fix:** Migrate to a `lifespan` context manager:
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("api.startup", ...)
    yield

app = FastAPI(..., lifespan=lifespan)
```

---

### IN-02: `raw_document` and `parsed_document` Share the `doc_` ID Prefix

**File:** `src/knowledge_lake/ids.py` (not in this review scope, tracked from prior iteration)
**Issue:** Both artifact types map to the `doc_` prefix, making IDs ambiguous in logs and
in the prefix-expansion path in `lineage.py`. An unambiguous prefix like `doc_019f` could
match either type.
**Fix:** Assign distinct prefixes (`raw_` / `prs_` or similar). This is a breaking schema
change and should be applied before any production data is written.

---

### IN-03: `version.py` — `git rev-parse` Subprocess Spawned Per Artifact, No Memoization

**File:** `src/knowledge_lake/version.py` (not in this review scope, tracked from prior iteration)
**Issue:** `pipeline_version()` forks a subprocess on every artifact write. A document
producing 50 chunks spawns 52 subprocesses. The result is constant within a process lifetime.
**Fix:** Decorate with `@functools.cache` (Python 3.9+).

---

_Reviewed: 2026-07-03T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Iteration: 3 (final re-review — all targeted fixes confirmed closed)_
