---
phase: 12-agent-surfaces
fixed_at: 2026-07-12T00:00:00Z
review_path: .planning/phases/12-agent-surfaces/12-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 12: Code Review Fix Report

**Fixed at:** 2026-07-12T00:00:00Z
**Source review:** .planning/phases/12-agent-surfaces/12-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (CR-01, WR-01, WR-03, WR-04, WR-05)
- Fixed: 5
- Skipped: 0
- IN-01 applied as part of CR-01 (test hardening). IN-02 left as-is (WR-03 kept
  the resilient bare `except` + logging rather than narrowing the catch, per the
  reviewer's primary recommendation, so the docstring split was not introduced).

**Verification:** `uv run pytest tests/unit/test_tool_handlers.py tests/unit/test_readonly.py
tests/unit/test_surface_parity.py tests/unit/test_tool_registry.py
tests/integration/test_mcp_http.py tests/integration/test_stdio_lockdown.py
tests/unit/test_pipeline_extractions.py -q` → **60 passed, 1 warning**.

## Fixed Issues

### CR-01: MCP expected-error path crashes on stdlib logger, masking every readable tool error

**Files modified:** `src/knowledge_lake/agent/server.py`, `tests/unit/test_tool_handlers.py`
**Commit:** 654f54f
**Applied fix:** Switched both `log.warning(...)` calls (lines 109 and 132) from
structlog-style keyword arguments (`tool=name, error=str(exc)`) to stdlib-compatible
`%`-style formatting (`"... tool=%s error=%s", name, str(exc)`). This stops the
`TypeError: Logger._log() got an unexpected keyword argument 'tool'` from firing inside
the `except` handler and replacing the readable domain message with an internal logging
string. Per IN-01, hardened `test_call_tool_value_error_returns_is_error` to assert
`call_result.content[0].text == "test error from handler"` (not merely `isError is True`),
and added a symmetric `test_call_tool_contamination_error_returns_readable_message` that
exercises the contamination branch (server.py:132) and asserts its message surfaces
verbatim.

### WR-01: `build_http_app` never auto-resolves `token` from settings — fail-open for factory/direct callers

**Files modified:** `src/knowledge_lake/agent/http.py`
**Commit:** 16e1448
**Applied fix:** Introduced a module-level `_UNSET` sentinel and changed the `token`
parameter default from `None` to `_UNSET`. The settings-resolution block now also fires
when `token is _UNSET` and sets `token = settings.mcp.token`, so an omitted token honours
`KLAKE_MCP__TOKEN`. An explicit `None`/empty still means "no auth" (tests pass
`token=None`/`token="s3cret-token"` explicitly and are unaffected). Docstring updated to
describe the new contract.

### WR-03: `process_crawled` swallows every per-doc exception with a bare `except` and no logging

**Files modified:** `src/knowledge_lake/pipeline/process.py`
**Commit:** 8f5a9f2
**Applied fix:** Added module-level `import logging` + `log = logging.getLogger(__name__)`
and a `log.warning("process_crawled: doc %s failed", raw_id, exc_info=True)` inside the
per-doc `except` before incrementing `failed`. The batch stays resilient but failures are
now observable with artifact id, exception type, and traceback. Kept the resilient bare
`except` (reviewer's primary recommendation) rather than narrowing it, so IN-02's docstring
split was intentionally not introduced.

### WR-04: Default `readonly=False` + `token=None` exposes all destructive write tools unauthenticated over HTTP

**Files modified:** `src/knowledge_lake/cli/app.py`
**Commit:** 5343d88
**Applied fix:** Added a fail-closed guard in `cmd_mcp`'s `--sse` path: when
`not settings.mcp.token and not settings.mcp.readonly`, raise `typer.BadParameter`
refusing to serve write tools over HTTP without `KLAKE_MCP__TOKEN`. The
`McpSettings.readonly`/`token` defaults were left unchanged so stdio (`klake mcp`) keeps
working, and an explicitly-tokened or explicitly-readonly HTTP server is unaffected. No
existing test invokes `klake mcp --sse` via the CLI (the HTTP integration tests call
`build_http_app` directly, and `test_stdio_lockdown` spawns stdio mode), so the guard
required no test changes.

### WR-05: CLI `mcp --port` hardcodes 3001 and ignores `settings.mcp.port` — `KLAKE_MCP__PORT` is dead config

**Files modified:** `src/knowledge_lake/cli/app.py`
**Commit:** f871fab
**Applied fix:** Changed the `--port` option default from the literal `3001` to
`Optional[int] = None` and resolve `bind_port = port if port is not None else
settings.mcp.port` in the `--sse` branch, using `bind_port` for both `build_http_app(...)`
and `uvicorn.run(...)`. `KLAKE_MCP__PORT` now takes effect while an explicit `--port` still
overrides. `Optional` was already imported.

---

_Fixed: 2026-07-12T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
