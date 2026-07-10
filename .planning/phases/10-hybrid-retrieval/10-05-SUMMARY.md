---
phase: 10-hybrid-retrieval
plan: "05"
subsystem: sparse-embedding-wrapper
status: complete
tags: [sparse-embedder, bm25, fastembed, qdrant, pitfall-6, retr-01]
dependency_graph:
  requires: [10-03-fastembed-cpu-installed]
  provides: [sparse_embedder-module, embed_sparse_doc, embed_sparse_query]
  affects: [10-07-reembedding-and-index]
tech_stack:
  added: []
  patterns: [lazy-module-singleton, doc-vs-query-split, empty-text-guard]
key_files:
  created:
    - src/knowledge_lake/plugins/builtin/sparse_embedder.py
    - tests/unit/test_sparse_embedder.py
  modified: []
decisions:
  - "Lazy module-level singleton _bm25_model in sparse_embedder.py mirrors qdrant_store.py deferred-import convention; avoids fastembed import cost when sparse path is unused"
  - "embed_sparse_doc uses .embed([text]) (document side); embed_sparse_query uses .query_embed(text) (query side) — strictly distinct per Pitfall 6 / D-03"
  - "Empty or whitespace-only text returns SparseVector(indices=[], values=[]) without raising; guards callers from edge cases in migration upsert_fn"
  - "Unit tests monkeypatch the _bm25_model module global directly; autouse reset_singleton fixture ensures test isolation without needing SparseTextEmbedding import"
metrics:
  duration: "~3m"
  completed_date: "2026-07-10"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
requirements_satisfied: [RETR-01]
---

# Phase 10 Plan 05: BM25 Sparse Encoder Wrapper Summary

## One-liner

BM25 sparse encoder wrapper (fastembed Qdrant/bm25, lazy singleton) with distinct doc/query methods and 14 mocked unit tests proving the Pitfall-6 separation.

## What Was Built

### Task 1: sparse_embedder.py

`src/knowledge_lake/plugins/builtin/sparse_embedder.py` — new module inside the `plugins/builtin/` seam (D-01 plugin ethos):

- **`_get_model()`**: module-level lazy singleton accessor that imports `SparseTextEmbedding` from fastembed on first call and caches `SparseTextEmbedding(model_name="Qdrant/bm25")` in `_bm25_model`. Logs `sparse_embedder.load_model` via structlog on first load, mirroring qdrant_store.py style.
- **`embed_sparse_doc(text: str) -> SparseVector`**: document-side embedding using `.embed([text])`, returns `SparseVector(indices=e.indices.tolist(), values=e.values.tolist())`. Used at index time (D-05) and by the re-embedding migration in Plan 10-07.
- **`embed_sparse_query(text: str) -> SparseVector`**: query-side embedding using `.query_embed(text)` — the distinct query method per Pitfall 6 / D-03. Used by pipeline.search in Plan 10-07.
- **Empty/whitespace guard**: both functions check `text` before calling the model; empty or whitespace-only input returns `SparseVector(indices=[], values=[])` without raising.
- No collection creation, no server calls, no qdrant_store import — this module only produces `SparseVector` objects.

### Task 2: test_sparse_embedder.py

`tests/unit/test_sparse_embedder.py` — 14 tests, all green, no live model download:

- Monkeypatches `_bm25_model` module global with a MagicMock configured to return distinct fake `SparseEmbedding` objects for `.embed()` (indices=[1,2,3]) and `.query_embed()` (indices=[4,5]), so each test can assert which method was called.
- `autouse` `reset_singleton` fixture ensures `_bm25_model` is reset to `None` before and after every test — proper isolation.
- Test classes: `TestEmbedSparseDoc`, `TestEmbedSparseQuery`, `TestSingleton`.
- Key assertions: doc method calls `.embed()` and NOT `.query_embed()`; query method calls `.query_embed()` and NOT `.embed()`; empty/whitespace returns empty SparseVector without calling the model.

## Verification

```
uv run pytest tests/unit/test_sparse_embedder.py -q
14 passed in 1.89s

uv run pytest tests/unit -q
401 passed, 19 xfailed, 21 xpassed, 20 warnings in 28.70s
```

## Tasks

| Task | Name | Status | Commit |
|------|------|--------|--------|
| 1 | sparse_embedder.py — fastembed Qdrant/bm25 wrapper | DONE | 4e7f999 |
| 2 | test_sparse_embedder.py — mocked-fastembed unit coverage | DONE | 4e7f999 |

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced. The sparse_embedder.py module performs local ONNX inference only (no external calls). The supply-chain threat T-10-05 (Qdrant/bm25 model) is mitigated by the fastembed pin verified in Plan 10-03.

## Self-Check: PASSED

- `src/knowledge_lake/plugins/builtin/sparse_embedder.py`: FOUND
- `tests/unit/test_sparse_embedder.py`: FOUND
- Commit `4e7f999`: FOUND (git log confirmed)
- 14 unit tests: PASSED
- Full unit suite (401 tests): PASSED
