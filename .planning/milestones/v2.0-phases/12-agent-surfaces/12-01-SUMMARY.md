---
phase: 12-agent-surfaces
plan: "01"
subsystem: agent-surfaces
status: complete
tags: [mcp, tdd, wave-0, test-scaffold, dependency]
requires: []
provides: [mcp-dependency, wave-0-test-scaffolds, normalize-helper]
affects: [pyproject.toml, uv.lock, tests/unit, tests/integration]
tech_stack:
  added: [mcp==1.28.1, httpx-sse==0.4.3, pyjwt==2.13.0, python-multipart==0.0.32, sse-starlette==3.4.5]
  patterns: [import-guard-xfail, normalize-canonical-helper, wave-0-red-scaffold]
key_files:
  created:
    - tests/unit/test_tool_registry.py
    - tests/unit/test_tool_handlers.py
    - tests/unit/test_readonly.py
    - tests/unit/test_openapi_export.py
    - tests/unit/test_surface_parity.py
    - tests/unit/test_skills_present.py
    - tests/unit/test_pipeline_extractions.py
    - tests/unit/test_input_models.py
    - tests/integration/test_stdio_lockdown.py
    - tests/integration/test_mcp_http.py
  modified:
    - pyproject.toml
    - uv.lock
decisions:
  - "mcp==1.28.1 pinned bare (no extras) — conflicts with httpx/pydantic/starlette/uvicorn/pydantic-settings resolved by uv automatically"
  - "Wave 0 xfail tests use strict=False and import-guard pattern — collection never errors before implementation"
  - "normalize()/canonical() helpers implemented in test_surface_parity.py with no agent/ dependency — importable by other test files immediately"
  - "test_openapi_json_exists uses unconditional xfail (not guarded on _IMPORT_OK) since file absence is the RED condition"
  - "test_search_params_has_filter_fields uses unconditional xfail since SearchParams extension lands in Plan 02"
metrics:
  duration: "~5m"
  completed_date: "2026-07-11"
  tasks: 3
  files: 12
---

# Phase 12 Plan 01: Wave 0 Scaffold Summary

**One-liner:** `mcp==1.28.1` locked and importable; 9 RED/xfail test files with `normalize()`/`canonical()` parity helpers covering all phase-12 requirements.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Add mcp==1.28.1 dependency and lock | `8a7c16b` | pyproject.toml, uv.lock |
| 2 | Wave 0 unit-test scaffolds + normalize() | `8747f8a` | tests/unit/test_tool_registry.py, test_tool_handlers.py, test_readonly.py, test_openapi_export.py, test_surface_parity.py, test_skills_present.py, test_pipeline_extractions.py, test_input_models.py |
| 3 | Wave 0 integration-test scaffolds | `11319f4` | tests/integration/test_stdio_lockdown.py, test_mcp_http.py |

## Verification Results

- `uv run python -c "import mcp; from mcp.server.lowlevel import Server; from mcp.server.stdio import stdio_server; from mcp.server.streamable_http_manager import StreamableHTTPSessionManager; print('ok')"` → `ok`
- `grep -c 'mcp==1.28.1' pyproject.toml` → `1` (bare, no extras)
- `uv.lock` contains `mcp 1.28.1`
- All 9 test files collect with 0 errors: **6 passed** (normalize/canonical helpers), **46 xfailed** (RED scaffolds), **15 skipped**, 1 warning (httpx deprecation from starlette TestClient — upstream, not blocking)

## Requirements Covered

| Req | Description | Test |
|-----|-------------|------|
| MCP-01 | MCP server tool registry (11 tools, read/write tags) | test_tool_registry.py, test_tool_handlers.py, test_readonly.py |
| MCP-02 | stdio + HTTP transport | test_stdio_lockdown.py (first-task gate), test_mcp_http.py |
| SKILL-01 | Claude Code skill files | test_skills_present.py |
| SKILL-02 | Static OpenAPI export determinism | test_openapi_export.py |
| SKILL-03 | OpenAI-format tool parity | test_surface_parity.py (+ normalize/canonical helpers) |
| D-02 | Input model schema contract | test_input_models.py |
| D-03 | Handlers from pipeline/* not api.app | test_tool_handlers.py |
| D-04 | Surface parity (stdio == openai == model_json_schema) | test_surface_parity.py |
| D-05 | Pipeline function extractions | test_pipeline_extractions.py |
| D-11 | 11 tools with access tags | test_tool_registry.py |

## normalize/canonical Helper (SKILL-03, Pitfall 2)

Implemented directly in `tests/unit/test_surface_parity.py` — no agent/ dependency.

```python
from tests.unit.test_surface_parity import normalize, canonical

canonical({"title": "X", "type": "object"}) == canonical({"type": "object"})  # True
canonical({"$ref": "#/$defs/MyModel"}) == canonical({"$ref": "#/definitions/MyModel"})  # True
```

Transformations: drops all `title` keys, canonicalizes `#/$defs/` and `#/definitions/` → `#/DEFS/`, `json.dumps(sort_keys=True)`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_openapi_json_exists was FAILED not xfailed**
- **Found during:** Task 2 verification
- **Issue:** Test used `@pytest.mark.xfail(not _IMPORT_OK, ...)` but `_IMPORT_OK=True` (FastAPI app imports fine), so the condition evaluated to `False` — the test ran and hard-failed on missing file
- **Fix:** Changed decorator to unconditional `@pytest.mark.xfail(reason="Wave 0 scaffold — klake openapi not yet implemented (Plan 05)", strict=False)` since the RED condition is the absent `docs/openapi.json` file
- **Files modified:** tests/unit/test_openapi_export.py
- **Commit:** included in 8747f8a

**2. [Rule 1 - Bug] test_search_params_has_filter_fields was FAILED not xfailed**
- **Found during:** Task 2 verification
- **Issue:** Test used `@pytest.mark.xfail(not _SEARCH_OK, ...)` but `SearchParams` imports fine; condition was False so the test ran and hard-failed on the missing filter fields
- **Fix:** Changed to unconditional `@pytest.mark.xfail(reason="Wave 0 scaffold — SearchParams filter fields added in Plan 02", strict=False)` since the RED condition is the missing fields
- **Files modified:** tests/unit/test_input_models.py
- **Commit:** included in 8747f8a

## Threat Surface Scan

Task 1 added `mcp==1.28.1` and transitive packages to the dependency graph. Per the plan's `<threat_model>`, T-12-SC disposition is **mitigate** — the RESEARCH Package Legitimacy Audit verified `mcp` as the official Anthropic/MCP SDK (verdict OK); exact version pin, no extras, `uv.lock` records the resolution. No new network endpoints, auth paths, or schema changes introduced in this plan (test-only aside from pyproject.toml).

## Self-Check: PASSED

Files created/present:

- [x] tests/unit/test_tool_registry.py — 8747f8a
- [x] tests/unit/test_tool_handlers.py — 8747f8a
- [x] tests/unit/test_readonly.py — 8747f8a
- [x] tests/unit/test_openapi_export.py — 8747f8a
- [x] tests/unit/test_surface_parity.py — 8747f8a
- [x] tests/unit/test_skills_present.py — 8747f8a
- [x] tests/unit/test_pipeline_extractions.py — 8747f8a
- [x] tests/unit/test_input_models.py — 8747f8a
- [x] tests/integration/test_stdio_lockdown.py — 11319f4
- [x] tests/integration/test_mcp_http.py — 11319f4
- [x] pyproject.toml (mcp==1.28.1 pin) — 8a7c16b
- [x] uv.lock (updated) — 8a7c16b

Commits present:

- [x] 8a7c16b — chore(12-01): add mcp==1.28.1 dependency and lock
- [x] 8747f8a — test(12-01): Wave 0 unit RED scaffolds + normalize/canonical parity helper
- [x] 11319f4 — test(12-01): Wave 0 integration RED scaffolds (stdio lockdown + MCP HTTP)
