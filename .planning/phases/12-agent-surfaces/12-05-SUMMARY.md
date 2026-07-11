---
phase: 12-agent-surfaces
plan: "05"
subsystem: agent-mcp-core
tags: [mcp, tool-registry, server-core, settings, tdd]
status: complete
requires: [12-02, 12-03, 12-04]
provides: [McpSettings, ToolDef, TOOLS, registered_tools, build_server]
affects: [src/knowledge_lake/config/settings.py, src/knowledge_lake/agent/registry.py, src/knowledge_lake/agent/server.py]
key-files:
  created:
    - src/knowledge_lake/agent/registry.py
    - src/knowledge_lake/agent/server.py
  modified:
    - src/knowledge_lake/config/settings.py
    - tests/unit/test_readonly.py
    - tests/unit/test_tool_handlers.py
decisions:
  - "ToolDef is a @dataclass (not BaseModel) — lightweight, no serialization overhead needed for registry entries"
  - "Handler shims (_search_handler, _ingest_url_handler, etc.) in registry.py translate Pydantic field names to pipeline fn kwargs"
  - "TrainEvalContaminationError handled via lazy import + isinstance check to avoid hard dep at module level"
  - "Non-dict handler returns wrapped in {result: value} for SDK compatibility"
tech-stack:
  added:
    - "mcp.server.lowlevel.Server — low-level MCP protocol server (Pattern 1)"
    - "mcp.types.Tool, CallToolResult, TextContent — MCP protocol types"
    - "inspect.iscoroutinefunction — async/sync bridge for call_tool dispatch"
  patterns:
    - "ToolDef dataclass as single source of truth for tool schema + handler binding"
    - "registered_tools(readonly) filter pattern for read/write posture"
    - "Async bridge: iscoroutinefunction → await or call directly (D-12)"
    - "TDD: RED (xfail scaffold) → GREEN (implementation) per task"
metrics:
  duration: "12m"
  completed: "2026-07-11"
  tasks: 3
  files: 5
---

# Phase 12 Plan 05: MCP Tool Registry and Server Core Summary

Built the 11-tool MCP registry and low-level server core — `ToolDef/TOOLS/registered_tools` in `registry.py` and `build_server` in `server.py` — with `McpSettings` providing the read-only posture and environment-variable config.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | McpSettings nested model | 0a8cf48 | settings.py, test_readonly.py |
| 2 | Tool registry (ToolDef + TOOLS + filter) | 352322d | agent/registry.py |
| 3 | MCP server core (build_server) | ffa0a14 | agent/server.py, test_tool_handlers.py |

## What Was Built

### Task 1: McpSettings

`McpSettings(BaseModel)` added to `settings.py` with localhost-safe defaults:
- `token: Optional[str] = None` — no baked-in secret
- `readonly: bool = False` — all 11 tools available by default
- `host: str = "127.0.0.1"` — localhost-only
- `port: int = 3001`

Mounted on `Settings` as `mcp: McpSettings = Field(default_factory=McpSettings)`. The existing `env_prefix="KLAKE_"` + `env_nested_delimiter="__"` resolve `KLAKE_MCP__READONLY=true` / `KLAKE_MCP__TOKEN` / `KLAKE_MCP__HOST` / `KLAKE_MCP__PORT` automatically.

### Task 2: Tool Registry

`agent/registry.py` is the **single source of truth** for all 11 MCP tools.

`ToolDef` dataclass: `{name, description, input_model (Pydantic), handler (pipeline fn), access ('read'|'write')}`.

**11 tools registered in TOOLS:**

Read tools (4): `search`, `list_sources`, `lineage`, `stats`
Write tools (7): `ingest_url`, `add_source`, `crawl`, `crawl_all`, `process_crawled`, `export`, `init_domain`

Handler binding: all callables imported from `pipeline/*.py` or `lineage.resolve_ancestry` — no `api.app` import (D-03 compliance verified).

`registered_tools(readonly: bool = False)` filters by `access == "read"` when `readonly=True`.

Thin handler shims translate Pydantic model fields to pipeline function kwargs (e.g., `SearchParams.q` → `search(query=q, ...)`).

### Task 3: MCP Server Core

`agent/server.py` implements `build_server(tools: list[ToolDef]) -> Server`:

1. **list_tools** — emits one `types.Tool` per `ToolDef` with `inputSchema = input_model.model_json_schema()` (D-01 single schema source).

2. **call_tool** — validates args via `input_model(**arguments)` (Pydantic coercion + type safety, T-12-07 double validation), unpacks via `model_dump(exclude_none=True)`, invokes via async bridge:
   - `inspect.iscoroutinefunction(fn)` → `await fn(**kwargs)` for crawl/crawl_all
   - otherwise `fn(**kwargs)` for all sync handlers
   - No `asyncio.run` in server.py (D-12 prohibition enforced)

3. **Error contract** (D-13):
   - `ValueError` / `LookupError` / `TrainEvalContaminationError` → `CallToolResult(isError=True)` with readable message
   - Unexpected exceptions propagate → SDK converts via `_make_error_result`
   - Dict returns pass through → SDK auto-wraps as structuredContent + TextContent

## Verification Results

```
tests/unit/test_tool_registry.py  6 passed
tests/unit/test_tool_handlers.py 10 passed
tests/unit/test_readonly.py       9 passed
─────────────────────────────────────────
TOTAL                            25 passed
```

All plan acceptance criteria satisfied:
- `TOOLS` has exactly 11 entries with unique names
- `registered_tools(True)` returns exactly `{search, list_sources, lineage, stats}`
- No `api.app` import in registry.py (handler modules verified via `__module__`)
- `asyncio.run` absent from server.py; `iscoroutinefunction` present
- `build_server(TOOLS)` returns `mcp.server.lowlevel.Server`
- `ValueError` → `isError=True` in call_tool

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written.

### Extra Decisions

**[Deviation: McpSettings test coverage in test_readonly.py]**
The Wave 0 scaffold in `test_readonly.py` had no McpSettings tests. Added 5 McpSettings TDD tests to that file as part of Task 1 (matching the plan's `files` field). This is additive, not a behavioral deviation.

**[Deviation: TrainEvalContaminationError lazy import in server.py]**
Rather than importing `TrainEvalContaminationError` at module level (which would eagerly load pipeline.export and its heavy deps), used a lazy import inside the except handler. Functionally equivalent to the plan's "catch TrainEvalContaminationError" requirement but avoids startup overhead.

## Threat Surface Scan

No new network endpoints, auth paths, or file access patterns introduced. The `build_server` function:
- Never opens sockets or files itself
- Does not expose any endpoint; transport wrapping is done by stdio.py / http.py (Plans 12-01 / 12-06)
- SSRF guard remains inside `ingest_url/crawl` pipeline functions, unchanged (T-12-03 mitigated)
- Double validation (T-12-07): SDK inputSchema jsonschema validation + Pydantic `input_model(**arguments)` in call_tool

## Known Stubs

None — all implemented handlers reference real pipeline functions. No placeholder returns.

## Self-Check: PASSED

Files exist:
- FOUND: src/knowledge_lake/agent/registry.py
- FOUND: src/knowledge_lake/agent/server.py
- FOUND: src/knowledge_lake/config/settings.py (McpSettings added)

Commits exist:
- 0a8cf48: feat(12-05): add McpSettings nested model to settings.py
- 352322d: feat(12-05): create agent/registry.py with ToolDef, TOOLS, registered_tools
- ffa0a14: feat(12-05): create agent/server.py with build_server (list_tools + call_tool)
