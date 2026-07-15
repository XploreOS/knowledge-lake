---
plan: 15-02
phase: 15-query-router
status: complete
wave: 2
completed: 2026-07-14
commits:
  - f447689 feat(15-02): wire route param through REST, CLI, and MCP surfaces (ROUTE-04)
  - 5b4fa39 feat(15-02): regenerate docs/openapi.json with route query param (Pitfall 3)
requirements_delivered: [ROUTE-01, ROUTE-04]
---

# Plan 15-02 Summary: Route Surface Wiring

## What Was Built

Wired the `route` parameter through all four surfaces: REST endpoint (`api/app.py`),
CLI command (`cli/app.py`), MCP agent handler (`agent/registry.py`), and OpenAPI
spec (`docs/openapi.json`). Removed xfail decorators from the Wave 0 surface tests —
all now pass as GREEN.

## Key Files Modified

| File | Action | What |
|------|--------|------|
| `src/knowledge_lake/api/app.py` | Modified | Added `route` Query(pattern=...) param, switched to `routed_search()` |
| `src/knowledge_lake/cli/app.py` | Modified | Added `--route` Option + `VALID_ROUTES` guard + `routed_search()` call |
| `src/knowledge_lake/agent/registry.py` | Modified | Added `route` kwarg to `_search_handler`, switched to `routed_search()` |
| `docs/openapi.json` | Regenerated | Route param now in GET /search schema |
| `tests/unit/test_api_route.py` | Modified | Removed xfail decorators (feature shipped) |
| `tests/unit/test_cli_route.py` | Modified | Removed xfail decorators (feature shipped) |

## Behaviors Delivered

- `GET /search?route=tree` → `routed_search(route='tree')`, returns tree results
- `GET /search?route=bogus` → HTTP 422 (pattern validation, ASVS V5)
- `GET /search` (no route) → `routed_search(route=None)` → falls through to settings default
- `klake search "q" --route tree` → `routed_search(route='tree')`
- `klake search "q" --route bogus` → exit 1, error message (VALID_ROUTES guard)
- MCP `_search_handler(route=...)` → `routed_search(route=...)`
- `docs/openapi.json` has route param, byte-identical test passes

## Test Results

```
tests/unit/test_api_route.py: 3 passed
tests/unit/test_cli_route.py: 3 passed
tests/unit/test_openapi_export.py: passed
tests/unit/test_tool_registry.py: passed
Full unit suite: 608 passed, 5 xfailed, 35 xpassed
```

## Self-Check: PASSED

All must_haves verified:
- [x] REST ?route=tree dispatches to routed_search(route='tree')
- [x] REST ?route=bogus returns 422 without reaching handler (ASVS V5, T-15-01)
- [x] CLI --route tree dispatches correctly
- [x] CLI --route bogus prints error and exits 1
- [x] MCP _search_handler accepts route and forwards to routed_search
- [x] docs/openapi.json regenerated with route param, byte-identical test passes
- [x] Omitting route on all surfaces passes None → settings.router.default_route

## Deviations

None. All four surfaces wired exactly as specified in PATTERNS.md.
