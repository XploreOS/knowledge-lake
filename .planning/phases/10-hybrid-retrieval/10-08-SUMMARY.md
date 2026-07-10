---
phase: 10-hybrid-retrieval
plan: "08"
subsystem: cli/app + api/app + api/schemas
tags: [hybrid-retrieval, search-mode, cli, api, retr-03, retr-01, t-10-02, d-07, d-09]
dependency_graph:
  requires:
    - 10-02 (RED scaffold: test_cli_search_mode.py, test_api_search_mode.py)
    - 10-07 (pipeline.search mode kwarg + reindex_collection hybrid kwarg)
  provides:
    - klake search --mode flag threading mode into pipeline.search (RETR-03, D-09)
    - klake reindex --hybrid flag triggering live re-embedding migration (RETR-01, D-04, D-07)
    - RuntimeError handling for D-07 preflight / D-06 parity gate abort (T-10-04)
    - GET /search?mode= query param with fail-closed 422 validation (RETR-03, T-10-02)
    - SearchParams.mode bounded field mirroring ExportRequest.kind precedent (ASVS V5)
  affects: []
tech_stack:
  added: []
  patterns:
    - typer.Option for Optional[str] mode flag on cmd_search; None passes through to pipeline default
    - typer.Option for bool hybrid flag on cmd_reindex; hybrid=False keeps back-compat
    - (ValueError, LookupError, RuntimeError) except tuple for clean CLI error surfacing
    - Query(pattern=r'^(hybrid|dense|sparse)$') on FastAPI endpoint — automatic 422 on mismatch
    - Field(pattern=r'^(hybrid|dense|sparse)$') on SearchParams.mode — same constraint in schema
key_files:
  created: []
  modified:
    - src/knowledge_lake/cli/app.py
    - src/knowledge_lake/api/app.py
    - src/knowledge_lake/api/schemas.py
decisions:
  - "mode=None passes through to pipeline.search; pipeline resolves effective_mode = mode or s.search.mode (hybrid default) — no settings mutation at the CLI/API layer"
  - "hybrid=False default on cmd_reindex preserves back-compat; existing klake reindex callers get the copy path unchanged"
  - "RuntimeError added to except tuple alongside ValueError+LookupError — all three abort the reindex cleanly with typer.Exit(code=1) and no traceback"
  - "Query(pattern=...) on the FastAPI endpoint rejects invalid mode before the handler body runs — no manual mode check added inside the handler (T-10-02 satisfied at boundary)"
  - "SearchParams.mode field mirrors ExportRequest.kind bounded-pattern precedent (schemas.py:168-172)"
metrics:
  duration: "~7m"
  completed_date: "2026-07-10"
  tasks_completed: 2
  files_modified: 3
status: complete
---

# Phase 10 Plan 08: CLI/API Mode Surface Summary

CLI + API thin surface wiring over pipeline.search mode and reindex_collection hybrid — `klake search --mode`, `klake reindex --hybrid`, and `GET /search?mode=` with fail-closed T-10-02 validation, turning Plan 10-02's RED tests green and completing RETR-03 plus the operator-facing half of RETR-01.

## What Was Built

### Task 1: cli/app.py — search --mode + reindex --hybrid

**File:** `src/knowledge_lake/cli/app.py`

- Added `mode: Optional[str] = typer.Option(None, "--mode", ...)` parameter to `cmd_search`, appended after the existing filter Options (678-699). Passes `mode=mode` into `pipeline.search` call.
- Omitting `--mode` passes `None` — `pipeline.search` resolves `effective_mode = mode or s.search.mode`, defaulting to `"hybrid"` (D-09).
- Added `hybrid: bool = typer.Option(False, "--hybrid", ...)` parameter to `cmd_reindex`. Passes `hybrid=hybrid` into `reindex_collection()`.
- Extended `except` tuple from `(ValueError, LookupError)` to `(ValueError, LookupError, RuntimeError)` — the D-07 `assert_server_supports_hybrid` preflight and D-06 parity gate both raise `RuntimeError` on abort; they now surface as `Error: ...` + `typer.Exit(code=1)` with no traceback (T-10-04).
- Updated `cmd_reindex` docstring to document the `--hybrid` RETR-01 live migration trigger and the rollback guarantee (alias keeps the old collection on preflight/parity abort).

### Task 2: api/app.py + api/schemas.py — search ?mode= with fail-closed validation

**Files:** `src/knowledge_lake/api/app.py`, `src/knowledge_lake/api/schemas.py`

- Added `SearchParams.mode: Optional[str]` field with `pattern=r"^(hybrid|dense|sparse)$"` mirroring the `ExportRequest.kind` bounded-pattern precedent (schemas.py:168-172). This is the canonical schema-layer validation boundary (T-10-02, ASVS V5).
- Added `mode: Optional[str] = Query(default=None, pattern=r"^(hybrid|dense|sparse)$", ...)` to `search_endpoint` parameters, mirroring the existing filter `Query` declarations (167-197). FastAPI's automatic 422 rejects any unrecognised mode before the handler body runs.
- Passes `mode=mode` into the `pipeline.search` delegation. `None` → settings default (hybrid).
- Added `mode=mode` to the structlog `logger.info("api.search", ...)` call for observability.
- Updated `search_endpoint` docstring to document `?mode=` and the fail-loud behavior (a hybrid/sparse request against a sparse-less collection returns the store's clear error, D-10).

## Verification Results

```
uv run pytest tests/unit/test_cli_search_mode.py tests/unit/test_api_search_mode.py -q
→ 8 xpassed, 1 warning

uv run pytest tests/unit/ -q
→ 407 passed, 2 xfailed, 38 xpassed, 19 warnings — ZERO FAILURES
```

Plan 10-02's RED tests (`test_cli_search_mode.py` 3 tests, `test_api_search_mode.py` 5 tests) are now XPASSED — implementation satisfies all acceptance criteria.

## Commits

| Hash | Message |
|------|---------|
| 86373b0 | feat(10-08): cli search --mode + reindex --hybrid with RuntimeError handling (RETR-01, RETR-03, D-04, D-07, D-09) |
| f3368b0 | feat(10-08): api search ?mode= with fail-closed validation + SearchParams.mode (RETR-03, T-10-02, D-09) |

## Deviations from Plan

None — plan executed exactly as written.

## Threat Mitigations Applied

| Threat ID | Mitigation |
|-----------|-----------|
| T-10-02 | `mode` Query param and `SearchParams.mode` field both carry `pattern=r"^(hybrid\|dense\|sparse)$"` — FastAPI rejects unknown modes with 422 before handler runs (ASVS V5, fail-closed) |
| T-10-04 | `RuntimeError` added to except tuple in `cmd_reindex` — D-07 preflight (`assert_server_supports_hybrid`) and D-06 parity gate aborts surface as clean `Error:` + `typer.Exit(code=1)`; alias keeps old collection (rollback) |

## Known Stubs

None — all behavior is fully wired.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries introduced. This plan is surface wiring only.

## Self-Check: PASSED

- `/root/healthlake/src/knowledge_lake/cli/app.py` — FOUND (modified)
- `/root/healthlake/src/knowledge_lake/api/app.py` — FOUND (modified)
- `/root/healthlake/src/knowledge_lake/api/schemas.py` — FOUND (modified)
- Commits 86373b0, f3368b0 — verified via git log
