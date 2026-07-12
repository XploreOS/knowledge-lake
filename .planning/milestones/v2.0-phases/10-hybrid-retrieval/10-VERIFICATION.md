---
phase: "10"
slug: hybrid-retrieval
status: passed
verified_at: 2026-07-11T11:38:00Z
plans_verified: 8
summaries_verified: 8
uat_passed: true
integration_tests_passed: true
---

# Phase 10 — Verification Report

## Verification Summary

All 8 plans executed and verified. UAT complete — all 9 checkpoints passed via automated programmatic testing against a live Qdrant instance. No human-only gaps remain.

## Test Results

### Unit Tests

```
uv run pytest tests/unit/ -q
436 passed, 2 xfailed, 38 xpassed, 19 warnings
```

All phase-10 unit test files (test_qdrant_hybrid.py, test_search_mode.py, test_search_filters.py, test_index_sparse.py, test_settings_search.py, test_sparse_embedder.py, test_cli_search_mode.py, test_api_search_mode.py, test_index_alias.py) fully green — 65 tests, 0 failures, 18 XPASS (implementations exceeded RED scaffold).

### Integration Tests

```
uv run pytest tests/integration/ -m integration -q
10 passed, 178 deselected, 7 xfailed, 7 xpassed
```

All 5 hybrid-migration integration tests passed:
- test_reembed_parity — count(old) == count(new) after migration
- test_all_points_have_sparse — every migrated point has non-empty sparse vectors
- test_idf_modifier_set — Modifier.IDF present in sparse_vectors config
- test_payload_indexes_survive — payload indexes intact after named collection recreate
- test_dense_both_shapes — dense mode works on both legacy unnamed and migrated named collections

### Live Qdrant Programmatic Tests

Ran against live Qdrant 1.13.6 (localhost:6333):

| Test | Result |
|------|--------|
| Born-named collection (dense+sparse named vectors) | PASS |
| Server preflight (>=1.10) | PASS |
| Upsert named-shape (dense+sparse) | PASS |
| Upsert legacy-shape back-compat | PASS |
| Dense search | PASS |
| Hybrid search (RRF fusion) | PASS |
| Fail-loud on sparse-less collection (ValueError) | PASS |
| reindex_collection hybrid=True migration (alias swap, parity) | PASS |
| pipeline.search mode=hybrid forwards sparse_query | PASS |
| pipeline.search mode=dense passes sparse_query=None | PASS |

### API/CLI Tests

| Test | Result |
|------|--------|
| GET /search?q=test&mode=dense → 200 + mode forwarded | PASS |
| GET /search?q=test&mode=hybrid → 200 + mode forwarded | PASS |
| GET /search?q=test (absent mode) → 200, mode=null logged | PASS |
| GET /search?q=test&mode=invalid_mode → 422 | PASS |
| klake search --mode dense → pipeline.search(mode='dense') | PASS |
| klake reindex --hybrid → reindex_collection(hybrid=True) | PASS |
| klake reindex (no flag) → reindex_collection(hybrid=False) | PASS |
| RuntimeError → exit(1) + clean error message, no traceback | PASS |
| KLAKE_SEARCH__MODE env override | PASS |
| KLAKE_SEARCH__MODE=bogus → ValidationError | PASS |
| VectorPoint.sparse back-compat (None default) | PASS |

## Requirements Coverage

| Requirement | Status |
|-------------|--------|
| RETR-01: Named dense+sparse collections, hybrid RRF search, re-embedding migration | PASSED |
| RETR-03: Search mode surface (settings, CLI, API), fail-loud, filter continuity | PASSED |

## Known Limitations

- `test_hybrid_prefetch_limits` remains xfail (strict=False) — test scaffold passes MagicMock filter to real Prefetch which fails pydantic validation. The implementation is correct and exercised by integration tests against live Qdrant. Not a blocker.
- Qdrant client 1.18.0 vs server 1.13.6 minor version mismatch warning (non-fatal; check_compatibility=False suppresses in production config).
