---
phase: 10-hybrid-retrieval
reviewed: 2026-07-10T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - src/knowledge_lake/api/app.py
  - src/knowledge_lake/api/schemas.py
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/config/settings.py
  - src/knowledge_lake/pipeline/index.py
  - src/knowledge_lake/pipeline/search.py
  - src/knowledge_lake/plugins/builtin/qdrant_store.py
  - src/knowledge_lake/plugins/builtin/sparse_embedder.py
  - src/knowledge_lake/plugins/protocols.py
findings:
  critical: 2
  warning: 6
  info: 3
  total: 11
status: issues_found
---

# Phase 10: Code Review Report

**Reviewed:** 2026-07-10  
**Depth:** standard  
**Files Reviewed:** 9  
**Status:** issues_found

## Summary

Phase 10 adds hybrid retrieval (dense + sparse BM25 via fastembed) to the Qdrant vector store.
The overall design is sound: named-vector branching in `upsert`/`search`, RRF fusion via
`query_points`, fail-loud mode enforcement (D-10), and a doc/query-side BM25 split (Pitfall 6)
are all correctly implemented. Two blockers were found:

1. A missing `session.commit()` in `reindex_collection()` means the registry never durably
   records the new physical collection after a reindex — every other call site in the same
   file uses `session.commit()` explicitly.
2. `QdrantVectorStore._named_cache` is never invalidated after a hybrid migration, so if the
   store instance is reused across requests (e.g. resolver uses `lru_cache`), new upserts
   post-migration silently use the legacy bare-vector path, stripping all sparse vectors from
   newly indexed chunks and breaking hybrid/sparse search for them.

---

## Critical Issues

### CR-01: `reindex_collection()` calls `session.flush()` instead of `session.commit()`

**File:** `src/knowledge_lake/pipeline/index.py:258`

**Issue:** After the alias-swap succeeds, `register_vector_collection` is called inside a
`get_session()` block that ends with `session.flush()`. SQLAlchemy 2.0 requires an explicit
`commit()` to durably persist changes; `flush()` only sends SQL to the in-flight transaction.
When the context manager exits, the transaction is closed without a commit, silently rolling
back the registry row. The alias-to-physical mapping is lost, so subsequent calls to
`ensure_aliased_collection` see no existing mapping and attempt to create `_v2` when `_v1`
already exists (or vice versa), causing confusion or duplicate physical collections.

The bug is confirmed by contrast: every other site that registers a collection in `index.py`
(including the `if created:` block at line 104 in `index()`) calls `session.commit()`
explicitly, and the comment at line 99-103 even explains why an immediate commit is required.

**Fix:**
```python
# pipeline/index.py — reindex_collection(), around line 258
with get_session() as session:
    registry_repo.register_vector_collection(
        session,
        alias_name=collection,
        physical_collection=result["new_physical"],
        dim=dim,
    )
    session.commit()   # ← was session.flush(); must commit to persist the row
```

---

### CR-02: `_named_cache` never invalidated after hybrid migration

**File:** `src/knowledge_lake/plugins/builtin/qdrant_store.py:392-402`

**Issue:** `QdrantVectorStore._is_named(collection)` caches the named-vector result
(True/False) per collection/alias name and never evicts it. After a hybrid migration:

1. Before migration: `_is_named("klake_chunks")` → `False` (alias targets a legacy
   unnamed-vector collection); result is cached.
2. `reindex(hybrid=True)` runs successfully — alias now targets a new named-vector collection
   (`klake_chunks_v2`).
3. First `index()` call post-migration: `_is_named("klake_chunks")` → `False` (stale cache).
4. `upsert()` takes the `else` branch and builds
   `PointStruct(id=..., vector=list[float], ...)` — a bare dense-only vector.
5. Qdrant receives a bare-list upsert against a named-vector collection; depending on
   server version, this either silently stores a malformed point or raises an error.

If it silently accepts, every chunk indexed post-migration lacks a sparse vector, making it
invisible to all subsequent hybrid/sparse searches — the primary deliverable of Phase 10.

This only manifests when the `QdrantVectorStore` instance is reused across the reindex and
subsequent index calls (e.g. if `get_vectorstore()` in the resolver uses `lru_cache`).

**Fix:** Invalidate the cache entry for the alias after a successful reindex, and also after
`ensure_aliased_collection` creates a new named collection:

```python
# plugins/builtin/qdrant_store.py — reindex(), before the return statement
self._named_cache.pop(alias, None)   # invalidate stale cache after alias swap

# Additionally, in ensure_aliased_collection(), after creating the named collection:
self._named_cache.pop(alias, None)   # ensure first index() call queries fresh
```

---

## Warnings

### WR-01: CLI `--mode` accepts arbitrary strings — invalid values silently fall back to dense

**File:** `src/knowledge_lake/cli/app.py:700-703`

**Issue:** `klake search --mode foobar` passes `mode="foobar"` to `pipeline.search.search()`,
which computes `effective_mode = "foobar"` and calls `vstore.search(..., mode="foobar")`.
In `qdrant_store.search()`, the guard `if mode in ("hybrid", "sparse")` is False, so the
code falls through to the `else` (dense) branch silently. An unknown mode produces dense
results with no error, violating the D-10 fail-loud contract and making misconfigured CLI
invocations hard to diagnose.

The API layer correctly uses `pattern=r"^(hybrid|dense|sparse)$"` on the Query parameter,
but the CLI has no equivalent guard.

**Fix:**
```python
# cli/app.py — in cmd_search(), before the search() call
VALID_MODES = {"hybrid", "dense", "sparse"}
if mode is not None and mode not in VALID_MODES:
    typer.echo(f"Error: --mode must be one of {sorted(VALID_MODES)}, got {mode!r}", err=True)
    raise typer.Exit(code=1)
```

---

### WR-02: `tags` list length is unbounded in the `/search` endpoint

**File:** `src/knowledge_lake/api/app.py:193-197`

**Issue:** The `tags` query parameter is declared as `Optional[list[str]]` with
`Query(..., max_length=64)`. In FastAPI/Pydantic v2, `max_length` on a `list[str]` Query
field constrains each element's character length, NOT the number of elements in the list.
The manual per-element check at lines 256-257 confirms this: it catches strings longer than
64 characters but does nothing to cap the number of tags. A caller can supply thousands of
`&tags=...` repetitions, causing unbounded CPU in both the length-check loop and the Qdrant
`MatchAny` clause construction. The comment at line 195 also incorrectly describes this as
"bounds the number of tags in the list".

**Fix:**
```python
tags: Optional[list[str]] = Query(
    default=None,
    description="...",
    max_length=64,          # per-element character limit (keep)
),
# Add an explicit list-length guard in the handler body:
if tags and len(tags) > 64:
    raise HTTPException(status_code=422, detail="At most 64 tags may be specified.")
if tags and any(len(t) > 64 for t in tags):
    raise HTTPException(status_code=422, detail="Tag values must not exceed 64 characters.")
```

---

### WR-03: `int(payload.get("page") or 1)` raises `ValueError` on unexpected payload data

**File:** `src/knowledge_lake/api/app.py:298`

**Issue:**
```python
page=int(payload.get("page") or 1),
```
If `payload["page"]` is a non-numeric string (e.g. `"unknown"` or `"n/a"` from an old/corrupt
point), `int("unknown")` raises `ValueError`. This propagates as an unhandled 500 error from
the search endpoint rather than a graceful fallback. Points from legacy collections or from
external tools could carry non-integer page values.

**Fix:**
```python
_raw_page = payload.get("page")
try:
    page = int(_raw_page) if _raw_page is not None else 1
except (TypeError, ValueError):
    page = 1
```

---

### WR-04: `reembed_all_points` does not guard against a `None` dense vector

**File:** `src/knowledge_lake/plugins/builtin/qdrant_store.py:508-509`

**Issue:**
```python
else:
    dense = r.vector.get("dense")   # returns None if key absent
```
If a scrolled point has a named-vector dict that lacks the `"dense"` key, `dense` becomes
`None`. The subsequent `PointStruct(id=..., vector={"dense": None, "sparse": sparse}, ...)`
call sends a null vector to Qdrant, which will either reject it or store a corrupt point. The
count-parity gate in `reindex()` would still pass if Qdrant accepts the upsert, silently
leaving a broken point in the new physical collection.

**Fix:**
```python
dense = r.vector.get("dense") if isinstance(r.vector, dict) else r.vector
if dense is None:
    log.warning(
        "qdrant_store.reembed_all_points.missing_dense_vector",
        point_id=r.id,
    )
    continue   # skip points with no dense vector; log for operator review
```

---

### WR-05: `VectorStorePlugin` protocol is missing `reembed_all_points` and `assert_server_supports_hybrid`

**File:** `src/knowledge_lake/plugins/protocols.py:207-367`

**Issue:** `pipeline/index.py` calls both `vstore.reembed_all_points(...)` (line 239) and
`vstore.assert_server_supports_hybrid()` (line 233) on the value returned by
`get_vectorstore(s)`, which is typed as a `VectorStorePlugin`. Neither method is declared in
the protocol. This means:

1. Static type checkers (mypy, pyright) will report attribute errors on the call sites.
2. Any alternative `VectorStorePlugin` implementation is not contractually required to provide
   these methods, so substituting a mock or a future implementation would silently break the
   hybrid reindex path at runtime.

**Fix:** Add the two methods to `VectorStorePlugin`:
```python
def assert_server_supports_hybrid(self) -> None:
    """Assert the vector store server supports hybrid/sparse retrieval."""
    ...

def reembed_all_points(
    self,
    source: str,
    dest: str,
    sparse_doc_fn: Callable[[str], Any],
    batch_size: int = 256,
) -> int:
    """Re-embed all points from source into dest with added sparse vectors."""
    ...
```

---

### WR-06: `SourceListItem.source_type` is non-optional but `Source.source_type` can be `None`

**File:** `src/knowledge_lake/api/app.py:1262`, `src/knowledge_lake/api/schemas.py:661`

**Issue:** `SourceListItem.source_type: str` has no `Optional` annotation and no default.
The `list_sources_endpoint` and `get_source_endpoint` handlers populate it directly with
`src.source_type`, which is a nullable column in the `Source` model. When a source was
registered without a `source_type` (e.g. by an earlier version or a manual DB insert),
Pydantic v2 will raise a `ValidationError` at serialization time, returning a 500 to the
caller instead of a clean 404 or fallback.

**Fix:**
```python
# schemas.py
source_type: str = Field(
    default="unknown",
    description="Kind of source: 'web', 'upload', 'crawler', etc.",
)

# OR make it Optional:
source_type: Optional[str] = Field(default=None, ...)
```

---

## Info

### IN-01: `SearchParams` schema is defined but never used by the search endpoint

**File:** `src/knowledge_lake/api/schemas.py:30-60`

**Issue:** `SearchParams` models the query parameters for `GET /search` but the actual
`search_endpoint` in `app.py` declares all its parameters inline as individual `Query(...)`
arguments. `SearchParams` is imported into `app.py` (line 67) but never referenced in the
handler signature. It is dead code.

**Fix:** Either wire `SearchParams` as the endpoint's query model, or remove it and the
import to avoid confusion about whether it is authoritative.

---

### IN-02: `DatasetKind` and `ExportKind` stub classes are dead code in the CLI

**File:** `src/knowledge_lake/cli/app.py:395-399`, `950-959`

**Issue:** Both classes inherit from `str` and define string constants but are never used as
type annotations for the Typer command parameters they were presumably intended for. Both
commands (`generate-dataset` and `export`) manually validate the `kind` argument with
`if kind not in (...)` comparisons instead. The classes add noise without providing any
compile-time or runtime enforcement.

**Fix:** Remove `DatasetKind` and `ExportKind` entirely, or use them as Typer enum types
to get built-in validation:
```python
class DatasetKind(str, Enum):
    QA = "qa"
    INSTRUCTION = "instruction"

kind: DatasetKind = typer.Argument(...)
```

---

### IN-03: Misleading comment on `tags` `max_length` constraint

**File:** `src/knowledge_lake/api/app.py:195`

**Issue:**
```python
max_length=64,  # bounds the number of tags in the list
```
The comment is factually wrong. `max_length=64` on a `list[str]` Query constrains each
element's character length, not the list size. The immediately following manual check at
lines 256-257 is also checking per-element length (not list length), compounding the
confusion. See WR-02 for the actual missing bound.

**Fix:** Update the comment:
```python
max_length=64,  # per-element character limit (list length is unbounded — add a list-length guard)
```

---

_Reviewed: 2026-07-10_  
_Reviewer: Claude (gsd-code-reviewer)_  
_Depth: standard_
