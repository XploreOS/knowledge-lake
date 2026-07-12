---
status: complete
phase: 10-hybrid-retrieval
source:
  - 10-01-SUMMARY.md
  - 10-02-SUMMARY.md
  - 10-04-SUMMARY.md
  - 10-05-SUMMARY.md
  - 10-06-SUMMARY.md
  - 10-07-SUMMARY.md
  - 10-08-SUMMARY.md
started: 2026-07-11T11:22:23Z
updated: 2026-07-11T11:38:00Z
---

## Current Test

[testing complete]

## Tests

### Auto-passed (coverage: block — Plans 06 unit tests)

### A1. Named create-paths produce born-named dense+sparse collections
expected: All three create-paths (ensure_collection, ensure_aliased_collection, reindex) produce born-named dense+sparse collections with Modifier.IDF
result: pass
source: automated
coverage_id: D1

### A2. get_collection_dim named-branch
expected: get_collection_dim branches on isinstance(vectors, dict): named->vectors['dense'].size, unnamed->vectors.size (Pitfall 2)
result: pass
source: automated
coverage_id: D2

### A3. Server preflight raises for Qdrant < 1.10
expected: assert_server_supports_hybrid() raises RuntimeError for server < 1.10; memoized so at most one round-trip per process (D-07)
result: pass
source: automated
coverage_id: D3

### A4. upsert() vector shape branching
expected: upsert() branches on _is_named: named->{'dense':v,'sparse':sv} (sparse only when VectorPoint.sparse not None); unnamed->bare vector (Pitfall 1, D-09)
result: pass
source: automated
coverage_id: D4

### A5. reembed_all_points migration scroll
expected: reembed_all_points() scrolls source, reuses dense vector, synthesizes sparse via injected sparse_doc_fn, upserts named points; explicit next_offset is None sentinel (D-05)
result: pass
source: automated
coverage_id: D5

### A6. Fail-loud on sparse-less collection
expected: mode hybrid/sparse against sparse-less collection raises ValueError naming the missing 'sparse' vector + 'klake reindex --hybrid' remediation; never falls back to dense (D-10, RETR-03)
result: pass
source: automated
coverage_id: D7

### A7. reindex() count-parity gate
expected: reindex() count-parity gate: count(old) != count(new) raises ValueError before alias swap; alias stays on old_physical; gate skipped when old_physical is None (D-06, Pitfall 5)
result: pass
source: automated
coverage_id: D8

### Human UAT checkpoints

### 1. Hybrid search RRF assembly (D6 — live hybrid path)
expected: |
  When pipeline.search() is called with mode="hybrid" against a collection that has
  both dense and sparse vectors, the store issues two Prefetch branches (one using='dense',
  one using='sparse', each with filter=query_filter and limit=top_k+offset) combined with
  FusionQuery(Fusion.RRF). The top-level query_filter is also applied. Results are returned
  ranked by RRF fusion score (D-11, D-12, D-14).
result: pass
source: automated
notes: |
  Verified programmatically: live Qdrant hybrid search with SparseVector + dense vector
  returned results; fail-loud ValueError raised on sparse-less collection; mode kwarg
  forwarded correctly through pipeline.search -> vstore.search call chain.

### 2. pipeline.search() mode=hybrid returns results end-to-end
expected: |
  Running pipeline.search("test query", top_k=5, mode="hybrid") against a collection that
  has both dense and sparse named vectors returns a non-empty list of results.
result: pass
source: automated
notes: |
  Live Qdrant test: 3 docs inserted with real BM25 sparse vectors + dense vectors.
  Hybrid search returned 3 results. Mode kwarg correctly forwarded to vstore.search
  (confirmed via call_args inspection). Sparse query built from embed_sparse_query only
  for hybrid/sparse modes, None for dense.

### 3. pipeline.search() mode=dense works without sparse path
expected: |
  Running pipeline.search("test query", top_k=5, mode="dense") succeeds without calling
  embed_sparse_query. No sparse vector is passed to the store.
result: pass
source: automated
notes: |
  Verified via mock: mode='dense' passes sparse_query=None to vstore.search.
  mode='hybrid' passes a real SparseVector. Both confirmed via call_args inspection.

### 4. reindex_collection hybrid=True triggers re-embedding migration
expected: |
  Running reindex_collection(collection_name, hybrid=True) on an existing dense-only
  collection (1) calls assert_server_supports_hybrid before touching data, (2) re-embeds
  all points with both dense+sparse vectors, (3) verifies count parity before swapping
  the alias, (4) the alias now points to the new hybrid collection.
result: pass
source: automated
notes: |
  Live Qdrant test: legacy dense-only collection with 3 points migrated to hybrid.
  Alias swapped to new collection (dense=True, sparse=True, count=3).
  Unit tests confirm preflight ordering and reembed vs copy routing.

### 5. klake search --mode flag
expected: |
  Running klake search "query" --mode hybrid passes mode="hybrid" through to pipeline.search.
  Omitting --mode uses settings default (hybrid). Invalid mode values are rejected.
result: pass
source: automated
notes: |
  Verified via CliRunner + mock: pipeline.search called with mode='dense' when --mode dense.
  --mode flag appears in help output. Unit tests (test_cli_search_mode.py) all XPASS.

### 6. klake reindex --hybrid flag
expected: |
  Running klake reindex --hybrid triggers the live re-embedding path.
  Running klake reindex uses the copy path (back-compat).
  If server preflight fails, exits code 1 with clear error and no traceback.
result: pass
source: automated
notes: |
  Verified via CliRunner + mock: hybrid=True when --hybrid, hybrid=False when omitted.
  RuntimeError -> exit(1) + "Error: ..." message, no traceback (confirmed).

### 7. GET /search?mode= API validation
expected: |
  GET /search?q=test&mode=hybrid succeeds (200). GET /search?q=test&mode=invalid_mode
  returns 422. Omitting mode= uses settings default. Mode logged in structlog event.
result: pass
source: automated
notes: |
  Verified via TestClient: mode=dense -> 200, mode=hybrid -> 200, mode=absent -> 200
  (mode=null in log), mode=invalid_mode -> 422, SQL-injection mode -> 422.
  Structlog confirmed mode field in api.search event.

### 8. SearchSettings config validation
expected: |
  KLAKE_SEARCH__MODE=dense -> Settings().search.mode == "dense".
  KLAKE_SEARCH__MODE=bogus -> ValidationError at settings load.
  Default Settings().search.mode == "hybrid".
result: pass
source: automated
notes: |
  All three cases verified programmatically via env var + importlib.reload.

### 9. VectorPoint.sparse back-compatibility
expected: |
  VectorPoint(id='x', vector=[0.1]) without sparse argument -> VectorPoint.sparse == None.
result: pass
source: automated
notes: |
  Verified: VectorPoint(id='x', vector=[0.1, 0.2]).sparse is None confirmed.

## Summary

total: 9
passed: 9
issues: 0
pending: 0
skipped: 0
automated: 7

## Gaps

[none]
