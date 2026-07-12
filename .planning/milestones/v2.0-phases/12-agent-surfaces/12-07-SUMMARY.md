---
phase: 12-agent-surfaces
plan: 07
subsystem: agent-surfaces
status: complete
tags: [mcp, cli, openapi, openai-tools, deterministic-export, skill]
requires:
  - agent/registry.py (TOOLS, registered_tools)
  - agent/server.py (build_server)
  - agent/stdio.py (run_stdio)
  - agent/http.py (build_http_app)
  - config/settings.py (McpSettings)
  - api/app.py (FastAPI app.openapi())
provides:
  - agent/openai_defs.py:openai_tool_defs
  - agent/openai_defs.py:render_openai_tools_json / write_openai_tools_json
  - cli/app.py:cmd_mcp (klake mcp / --sse)
  - cli/app.py:cmd_openapi (klake openapi)
  - docs/openapi.json (committed, deterministic)
  - docs/openai_tools.json (committed, deterministic)
affects:
  - Plan 12-08 (surface-parity test normalizes the same model_json_schema() source)
tech-stack:
  added: []
  patterns:
    - "OpenAI parameters and MCP inputSchema both derive from input_model.model_json_schema() — one schema source, two surfaces (D-15)"
    - "Deterministic committed artifact: json.dumps(obj, indent=2, sort_keys=True) + newline so re-runs are no-op diffs (Pitfall 3)"
    - "--sse flag NAME backs Streamable HTTP (build_http_app under uvicorn), never the deprecated HTTP+SSE transport"
    - "Single Server built from registered_tools(settings.mcp.readonly) drives BOTH transports so stdio == http"
key-files:
  created:
    - src/knowledge_lake/agent/openai_defs.py
    - docs/openapi.json
    - docs/openai_tools.json
  modified:
    - src/knowledge_lake/cli/app.py
    - tests/unit/test_openapi_export.py
decisions:
  - "openai_defs exposes render_/write_ helpers (not just openai_tool_defs) so the committed dump is generated from one deterministic renderer — avoids a second hand-written sort_keys call drifting from the CLI"
  - "klake openapi resolves docs/ via Path(__file__).resolve().parents[3] (repo root) so it writes the committed artifact regardless of cwd"
  - "cmd_mcp builds the Server once and passes it into build_http_app (--sse) or run_stdio (stdio); host/port/token come from settings.mcp, port overridable via --port"
metrics:
  duration: ~3m
  completed: 2026-07-11
  tasks: 2
  files: 5
---

# Phase 12 Plan 07: Agent Surface CLI + Static Exports Summary

Expose the MCP surfaces to users and commit the static agent-facing exports: `klake mcp` (stdio / `--sse` Streamable HTTP), `klake openapi` → committed deterministic `docs/openapi.json`, and OpenAI tool-defs generated from the registry → committed `docs/openai_tools.json`. Satisfies MCP-02 (the two CLI entrypoints), SKILL-02 (committed OpenAPI export), and the SKILL-03 generator (OpenAI defs from the same Pydantic source).

## What Was Built

**`agent/openai_defs.py`** — OpenAI function-tool defs generated from the registry:

- **`openai_tool_defs(tools) -> list[dict]`** emits one `{"type":"function","function":{name, description, parameters}}` per `ToolDef`. `parameters` is `t.input_model.model_json_schema()` — the identical call `agent/server.py` uses for the MCP `inputSchema`, so the OpenAI and MCP surfaces expose byte-identical argument schemas (D-15, one schema source).
- **`render_openai_tools_json` / `write_openai_tools_json`** produce the deterministic committed dump `json.dumps(..., indent=2, sort_keys=True) + "\n"` (Pitfall 3 — re-gen is a no-op diff).

**`cli/app.py`** — two new Typer verbs:

- **`cmd_mcp` (`klake mcp`)** with `--sse` (bool, default False) and `--port` (int, default 3001). Builds one `Server = build_server(registered_tools(settings.mcp.readonly))`; if `--sse`, serves MCP **Streamable HTTP** via `uvicorn.run(build_http_app(server, host=settings.mcp.host, port=port, token=settings.mcp.token), ...)` (no stdout lockdown, D-08); else runs stdio via `anyio.run(run_stdio, server, server.create_initialization_options())` (fd-level lockdown applies).
- **`cmd_openapi` (`klake openapi`)** imports the FastAPI `app` and writes `docs/openapi.json` as `json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"` (Pitfall 3), resolving `docs/` from the repo root so cwd does not matter.

**`docs/openapi.json`** and **`docs/openai_tools.json`** — committed deterministic exports (11 tools in openai_tools.json).

**`tests/unit/test_openapi_export.py`** — replaced the Wave-0 xfail scaffold with 3 real assertions: file exists, valid JSON with OpenAPI 3.x version field, and byte-identical to a fresh deterministic dump (re-export is a no-op diff).

## Task Commits

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | OpenAI tool-defs generator + committed docs/openai_tools.json | `820a8ee` | src/knowledge_lake/agent/openai_defs.py, docs/openai_tools.json |
| 2 | klake mcp (stdio + --sse) and klake openapi verbs + export test | `4d8551b` | src/knowledge_lake/cli/app.py, docs/openapi.json, tests/unit/test_openapi_export.py |

## Verification

- `uv run python -c "...openai_tool_defs(TOOLS)..."` → 11 defs, every `function.parameters == t.input_model.model_json_schema()`, all `type=="function"` — **ok**.
- `docs/openai_tools.json` re-generation is byte-identical (**DETERMINISTIC-OK**); `docs/openapi.json` re-export byte-identical (**OPENAPI-DETERMINISTIC-OK**).
- `uv run pytest tests/unit/test_openapi_export.py -x` → **3 passed**.
- `uv run klake --help` lists `mcp` and `openapi`; `uv run klake mcp --help` shows `--sse` and `--port`.
- `grep -c 'sort_keys=True' src/knowledge_lake/cli/app.py` → 2 (deterministic openapi dump present).
- `uv run python -c "from knowledge_lake.agent.openai_defs import openai_tool_defs"` imports cleanly.
- `uv run ruff check` on all new/modified code ranges → clean (no new errors introduced; pre-existing file-wide lint debt untouched per scope boundary).

## Must-Haves Satisfied

| Truth | Evidence |
| ----- | -------- |
| `klake mcp` runs stdio (fd-locked) and `klake mcp --sse --port 3001` runs Streamable-HTTP, both from registered_tools(settings.mcp.readonly) via build_server() | `cmd_mcp` builds one Server, branches stdio/Streamable-HTTP; `--sse`/`--port` shown in help |
| `klake openapi` writes docs/openapi.json as deterministic sort_keys=True dump (re-runs no-op) | `cmd_openapi`; OPENAPI-DETERMINISTIC-OK; export test passes |
| openai_tool_defs(TOOLS) emits one function-tool per tool from the SAME schema source as MCP inputSchema | `openai_tool_defs`; verify asserts `parameters == input_model.model_json_schema()` |
| docs/openai_tools.json is a committed deterministic dump | committed; re-gen byte-identical |
| --sse flag backs Streamable HTTP (build_http_app), not HTTP+SSE | `cmd_mcp` calls `build_http_app`; `grep sse_app` absent (Plan 06) |
| Bind only to McpSettings.host (127.0.0.1 default) | `uvicorn.run(..., host=settings.mcp.host, port=port)`; never 0.0.0.0 |
| No stdio lockdown in --sse mode (D-08) | `run_stdio` only on the stdio branch |

## Deviations from Plan

**1. [Rule 2 - Missing critical functionality] Deterministic render helpers in openai_defs.py**
- **Found during:** Task 1
- **Issue:** The plan mentions writing `docs/openai_tools.json` "inline in the Task-2 CLI verb", but there is no `klake` verb dedicated to it and duplicating the `json.dumps(..., sort_keys=True)` call risks the committed dump drifting from the generator.
- **Fix:** Added `render_openai_tools_json` / `write_openai_tools_json` to `openai_defs.py` so the committed artifact is produced from one deterministic renderer alongside `openai_tool_defs`. The file was generated via `render_openai_tools_json(TOOLS)`.
- **Files modified:** src/knowledge_lake/agent/openai_defs.py
- **Commit:** `820a8ee`

**2. [Rule 1 - Bug] B904 exception chaining in cmd_openapi**
- **Found during:** Task 2 (ruff check)
- **Issue:** `raise typer.Exit(code=1)` inside `except ImportError as exc` triggered ruff B904 (raise-without-from).
- **Fix:** `raise typer.Exit(code=1) from exc`.
- **Files modified:** src/knowledge_lake/cli/app.py
- **Commit:** `4d8551b`

## Threat Surface

No new surface beyond the plan's `<threat_model>`. T-12-02 (Streamable-HTTP bind) is mitigated — `cmd_mcp` passes `settings.mcp.host` (127.0.0.1 default) and `settings.mcp.token` to `build_http_app`, never binds 0.0.0.0, and the read-only posture flows via `registered_tools`. T-12-05 (stdio) is mitigated — the stdio branch runs `run_stdio` (fd lockdown) and the `--sse` branch intentionally skips it (D-08). T-12-INFO (committed json) is accepted — exports carry only public schema shapes and are deterministic. No stubs introduced.

## Self-Check: PASSED

- FOUND: src/knowledge_lake/agent/openai_defs.py
- FOUND: docs/openapi.json
- FOUND: docs/openai_tools.json
- FOUND: tests/unit/test_openapi_export.py
- FOUND commit: 820a8ee
- FOUND commit: 4d8551b
