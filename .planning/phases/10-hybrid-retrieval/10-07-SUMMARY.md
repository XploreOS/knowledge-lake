---
phase: 10-hybrid-retrieval
plan: "07"
subsystem: pipeline/index + pipeline/search
tags: [hybrid-retrieval, sparse-vectors, reindex-migration, search-mode, bm25]
dependency_graph:
  requires:
    - 10-02 (RED test scaffold: test_search_mode.py, test_search_filters.py)
    - 10-05 (sparse_embedder.py: embed_sparse_doc, embed_sparse_query)
    - 10-06 (qdrant_store.py: reembed_all_points, assert_server_supports_hybrid, reindex)
  provides:
    - index() sparse attachment: every new VectorPoint carries dense+sparse named vectors (RETR-01, D-05)
    - reindex_collection(hybrid=True): operator-triggered live re-embedding migration (RETR-01, D-05, D-07)
    - pipeline.search(mode=...): mode threading + query-side BM25 (RETR-03, D-03, D-09, D-14)
  affects:
    - 10-08 (CLI/API surfaces that call pipeline.search — mode kwarg now accepted)
tech_stack:
  added: []
  patterns:
    - embed_sparse_doc(chunk.get("text","")) on every VectorPoint at index time
    - mode-or-settings-default resolution (effective_mode = mode or s.search.mode)
    - embed_sparse_query only for hybrid/sparse modes; None for dense (D-03)
    - MagicMock(unsafe=True) required when method names start with "assert"
key_files:
  created:
    - tests/unit/test_index_sparse.py
  modified:
    - src/knowledge_lake/pipeline/index.py
    - src/knowledge_lake/pipeline/search.py
decisions:
  - "embed_sparse_doc imported directly at module level in index.py (not lazy) — sparse encoding is always needed for new chunks in the named-vector schema"
  - "reindex_collection hybrid=True calls assert_server_supports_hybrid BEFORE vstore.reindex (D-07 — abort before touching data)"
  - "re_embed_fn reads payload['text'] from Qdrant scroll via vstore.reembed_all_points — no get_session block for chunk text (research simplification)"
  - "pipeline.search uses effective_mode = mode or s.search.mode so per-request override works without settings mutation"
  - "MagicMock(unsafe=True) used in test_index_sparse.py for vstore fixture whose assert_server_supports_hybrid name triggers MagicMock's safety check"
  - "xfail(strict=False) markers on test_search_mode.py + test_search_filters.py left in place (they now pass as XPASS, not failures)"
metrics:
  duration: "~38m"
  completed_date: "2026-07-10"
  tasks_completed: 3
  files_modified: 3
status: complete
---

# Phase 10 Plan 07: Pipeline Sparse Wire-Up Summary

Wire sparse encoder into the pipeline: index() attaches embed_sparse_doc sparse vectors to every VectorPoint, reindex_collection gains hybrid=True re-embedding migration with D-07 server preflight, and pipeline.search() threads mode + query-side embed_sparse_query — turning Plan 10-02's RED tests green.

## What Was Built

### Task 1 + 2: index.py — sparse attachment + hybrid migration
- Imported `embed_sparse_doc` from `plugins.builtin.sparse_embedder` at module level
- Added `sparse=embed_sparse_doc(chunk.get("text", ""))` to every `VectorPoint` in the upsert loop — new chunks index with both dense and sparse named vectors (RETR-01, D-05)
- Added `hybrid: bool = False` keyword-only parameter to `reindex_collection()`
  - `hybrid=True`: calls `vstore.assert_server_supports_hybrid()` BEFORE creating the new collection (D-07 preflight), then passes `_re_embed_fn` (which calls `vstore.reembed_all_points(collection, new_physical, embed_sparse_doc)`) as the `upsert_fn` to `vstore.reindex()`
  - `hybrid=False`: unchanged `_copy_fn` → `vstore.copy_all_points` path (back-compat)
  - Parity gate + alias swap remain in `vstore.reindex` (Plan 10-06) — not duplicated

### Task 3: search.py — mode threading + sparse_query build  
- Added `mode: Optional[str] = None` keyword-only parameter
- Added `from typing import Any` and imported `embed_sparse_query` from sparse_embedder
- Resolves `effective_mode = mode or s.search.mode` (defaults to `"hybrid"` via `SearchSettings`, D-08/D-09)
- Builds `sparse_query = embed_sparse_query(query)` only when `mode in ("hybrid", "sparse")`; `None` for dense (D-03)
- Phase-7 filter builder (lines 104–122) reused verbatim across all modes (D-14)
- Threads `mode=effective_mode, sparse_query=sparse_query` into `vstore.search()` as keyword-only args
- Store's fail-loud error propagates unchanged — no dense fallback (D-10, T-10-03)

### New test file: test_index_sparse.py
- 6 unit tests: VectorPoint sparse attachment, embed_sparse_doc call count/args, empty chunk text, reindex_collection preflight ordering, reembed vs copy routing, hybrid=False back-compat
- Uses SQLite StaticPool + MagicMock(unsafe=True) — no DB/Qdrant/live-model contact

## Verification Results

```
uv run pytest tests/unit/test_index_sparse.py tests/unit/test_search_mode.py tests/unit/test_search_filters.py -q
→ 18 passed, 5 xpassed in 2.30s

uv run pytest tests/unit/ -q
→ 407 passed, 9 xfailed, 31 xpassed, 19 warnings in 29.94s
```

Plan 10-02's RED tests (test_search_mode.py, TestFilterPrefetchParity) are now XPASS — implementation matches the acceptance criteria.

## Commits

| Hash | Message |
|------|---------|
| a67f9e8 | test(10-07): add RED unit scaffold for index sparse attach + hybrid reindex wiring (RETR-01) |
| 080e3c7 | feat(10-07): index() sparse attach + reindex_collection hybrid migration (RETR-01, D-05, D-07) |
| 0c67561 | feat(10-07): thread mode + sparse_query through pipeline.search() (RETR-03, D-03, D-09, D-14) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] MagicMock(unsafe=True) required for assert_server_supports_hybrid**
- **Found during:** Task 1/2 GREEN phase (test_index_sparse.py runs)
- **Issue:** Python's `unittest.mock.MagicMock` blocks attribute access on names starting with `"assert"` (safety check to prevent mistyped assertion methods). `assert_server_supports_hybrid` begins with `"assert"`, causing `AttributeError` in the test fixture.
- **Fix:** Changed `MagicMock()` to `MagicMock(unsafe=True)` in the `fake_vstore_reindex` fixture; also removed the `monkeypatch.setattr(index_module, "get_session", MagicMock())` call that was unnecessary (reindex_collection still calls `get_session()` internally after `vstore.reindex()`, which the existing test engine handles).
- **Files modified:** `tests/unit/test_index_sparse.py`
- **Commit:** 080e3c7

## Threat Mitigations Applied

| Threat ID | Mitigation |
|-----------|-----------|
| T-10-04 | D-07 preflight (`assert_server_supports_hybrid`) called in `reindex_collection(hybrid=True)` before `vstore.reindex()` — server too old aborts before touching data |
| T-10-03 | Store's fail-loud ValueError propagates unchanged from `pipeline.search()` — no silent dense fallback (D-10) |

## Known Stubs

None — all behavior is fully wired.

## Self-Check: PASSED

- `/root/healthlake/tests/unit/test_index_sparse.py` — FOUND
- `/root/healthlake/src/knowledge_lake/pipeline/index.py` — FOUND (modified)
- `/root/healthlake/src/knowledge_lake/pipeline/search.py` — FOUND (modified)
- Commits a67f9e8, 080e3c7, 0c67561 — verified via git log
