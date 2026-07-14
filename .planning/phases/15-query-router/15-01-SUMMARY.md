---
plan: 15-01
phase: 15-query-router
status: complete
wave: 1
completed: 2026-07-14
commits:
  - 5d12b88 test(15-01): Wave 0 RED test scaffolds for query router (ROUTE-01..04)
  - 7e451fc feat(15-01): RouterSettings submodel + SearchParams.route field (D-07, D-08)
  - 3eceefb feat(15-01): pipeline/route.py — classify_route() + routed_search() (D-01..D-06)
requirements_delivered: [ROUTE-01, ROUTE-02, ROUTE-03]
---

# Plan 15-01 Summary: Query Router Core

## What Was Built

Created the query router core layer: deterministic heuristic classifier
(`classify_route()`), dispatch orchestrator (`routed_search()`), configuration
submodel (`RouterSettings`), and schema field (`SearchParams.route`). Three Wave 0
test files establish the RED→GREEN verification scaffold.

## Key Files Created / Modified

| File | Action | What |
|------|--------|------|
| `src/knowledge_lake/pipeline/route.py` | **Created** | Router dispatch module: `_TREE_TRIGGERS`, `classify_route()`, `routed_search()` |
| `src/knowledge_lake/config/settings.py` | Modified | `RouterSettings` class + `Settings.router` field |
| `src/knowledge_lake/api/schemas.py` | Modified | `SearchParams.route: str\|None` field with pattern validation |
| `tests/unit/test_route.py` | **Created** | 25 unit tests — all GREEN |
| `tests/unit/test_api_route.py` | **Created** | API route forwarding/422 scaffold (xfail) |
| `tests/unit/test_cli_route.py` | **Created** | CLI route forwarding/exit-1 scaffold (xfail) |

## Behaviors Delivered

- `classify_route("section 3 of the document")` → `("tree", "section_page_ref")`
- `classify_route("compare X vs Y")` → `("tree", "comparison_multihop")`
- `classify_route("outline of chapter 1")` → `("tree", "structural_breadth")`
- `classify_route("what is diabetes")` → `("chunk", "no_match")`
- `routed_search(q, route="tree")` and `route="two_stage"` dispatch identically (D-01 alias)
- `route=None` resolves to `settings.router.default_route` (D-07 per-call override)
- Auto-mode + tree empty → fallback to `search()` (D-05); explicit route → no fallback
- One `route.dispatch` structlog event per call with `route`, `trigger`, `fallback` keys (D-06)
- `RouterSettings.default_route` Literal rejects invalid values at load (ASVS V5)
- `SearchParams.route` defaults to `None`, validated by regex pattern (Pitfall 5)

## Test Results

```
tests/unit/test_route.py: 25 passed
Full unit suite: 602 passed, 5 xfailed, 41 xpassed
```

## Self-Check: PASSED

All must_haves verified:
- [x] `classify_route()` returns correct tuples for all D-04 categories
- [x] `routed_search()` dispatches correctly for all route values
- [x] tree/two_stage alias equivalence holds (D-01)
- [x] Auto-fallback on zero hits; explicit routes never fall back (D-05)
- [x] Structlog event emitted on every call (D-06)
- [x] RouterSettings Literal rejects invalid values at config load
- [x] SearchParams.route defaults to None, pattern-validated
- [x] No merge/both/combine result path (D-09 prohibition)
- [x] Additive only — search.py and tree_search.py unchanged (D-02)

## Deviations

None. Implementation followed PATTERNS.md and RESEARCH.md skeleton exactly.

## What Plan 15-02 Must Do

Wire `route` parameter through 4 surfaces: REST endpoint (`api/app.py`), CLI command
(`cli/app.py`), agent registry handler (`agent/registry.py`), and regenerate
`docs/openapi.json`. The test_api_route.py and test_cli_route.py xfail tests will
go GREEN when Plan 15-02 completes.
