---
phase: 15-query-router
iteration: 1
fix_scope: critical_warning
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
fixed_on: 2026-07-14
commits:
  - 083869c fix(15): CR-01 use dataclasses.asdict() in MCP _search_handler for Hit serialisation
  - c9f8499 fix(15): CR-02 separate mode/tree_mode to resolve dual-semantics conflict in routed_search
  - 07d306a fix(15): WR-01 remove unused search import from agent/registry.py
  - b41d541 fix(15): WR-03 add DomainSourceEntry typed response schema for GET /domains/{name}/sources
  - 4df5d48 fix(15): WR-04 update MCP search tool description to document route and tree_mode params
  - 44f1cc1 fix(15): regenerate openapi.json after tree_mode param added (Pitfall 3)
---

# Phase 15: Code Review Fix Report

**Phase:** 15-query-router
**Fix Scope:** critical_warning (Critical + Warning; Info excluded)
**Findings In Scope:** 6
**Fixed:** 6
**Skipped:** 0
**Status:** all_fixed

## Fixed Findings

### CR-01 — MCP _search_handler crashes on non-empty results
**File:** `src/knowledge_lake/agent/registry.py`
**Fix:** Added `import dataclasses` at module level and replaced `[h._asdict() if hasattr(h, "_asdict") else dict(h) for h in hits]` with `[dataclasses.asdict(h) for h in hits]`.
**Rationale:** `Hit` is a `@dataclass`, not a `NamedTuple`. `hasattr(h, "_asdict")` is always `False`, so the fallback `dict(h)` raised `TypeError` on every non-empty result. `dataclasses.asdict()` handles nested dataclasses recursively and is the correct serialization method.
**Commit:** 083869c

### CR-02 — `mode` parameter dual semantics (chunk vs tree paths)
**Files:** `pipeline/route.py`, `api/schemas.py`, `api/app.py`, `cli/app.py`, `agent/registry.py`, `tests/unit/test_route.py`
**Fix:** Introduced a distinct `tree_mode: str | None` parameter throughout the call stack. `mode` now exclusively carries chunk-path values (`hybrid|dense|sparse`); `tree_mode` carries tree-path values (`heuristic|llm`). Each callee receives only its valid set of values. `routed_search()`, `search_endpoint()`, `cmd_search()`, and `_search_handler()` all accept both params; `tree_search()` receives `tree_mode` (as its `mode` kwarg) while `search()` receives `mode`.
**Rationale:** A request like `?mode=hybrid&route=tree` previously passed API validation then hit `tree_search()` with `mode="hybrid"` — an invalid value for that function. Splitting the parameters eliminates the ambiguity.
**Commit:** c9f8499

### WR-01 — Unused `search` import in `agent/registry.py`
**File:** `src/knowledge_lake/agent/registry.py`
**Fix:** Removed `from knowledge_lake.pipeline.search import search` (dead import after CR-02 switched `_search_handler` to `routed_search`).
**Commit:** 07d306a

### WR-02 — Silent fallthrough for unrecognized route values
**File:** `src/knowledge_lake/pipeline/route.py`
**Fix:** Added `log.warning("route.unknown_route", route=effective_route)` before the final `search()` fallthrough branch, giving operators visibility when an unrecognised route value reaches Python callers that bypass API/CLI validation.
**Commit:** c9f8499 (incorporated into CR-02 commit)

### WR-03 — Untyped `list[dict]` response for `/domains/{name}/sources`
**Files:** `api/schemas.py`, `api/app.py`
**Fix:** Defined `DomainSourceEntry` Pydantic model mirroring `domains.models.SourceEntry` fields and updated `GET /domains/{name}/sources` `response_model` from `list[dict]` to `list[DomainSourceEntry]`. FastAPI now validates and documents the response schema.
**Commit:** b41d541

### WR-04 — MCP `search` tool description omits `route` and `tree_mode` fields
**File:** `src/knowledge_lake/agent/registry.py`
**Fix:** Rewrote the MCP `search` tool description to document all four `route` values (`chunk|tree|two_stage|auto`) and the new `tree_mode` parameter (`heuristic|llm`), making routing capabilities visible to LLM agents consuming the tool spec.
**Commit:** 4df5d48

## Post-Fix Verification

- Full unit suite: **610 passed, 5 xfailed, 35 xpassed** (zero regressions)
- `docs/openapi.json` regenerated with `tree_mode` param (44f1cc1)
- `test_openapi_json_matches_deterministic_dump`: PASSED

## Remaining (Info — excluded from fix scope)

- **IN-01** — `DatasetKind`/`ExportKind` dead code in `cli/app.py`
- **IN-02** — `SearchParams.q` required + `min_length=0` contradictory contract
- **IN-03** — `.+` in `comparison_multihop` regex (quadratic backtracking note)
