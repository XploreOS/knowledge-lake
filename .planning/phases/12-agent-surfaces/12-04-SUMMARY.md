---
phase: 12-agent-surfaces
plan: "04"
subsystem: agent/stdio
status: complete
tags: [mcp, stdio, lockdown, fd-level, first-task-gate]
dependency_graph:
  requires: [12-01]
  provides: [agent/stdio.py run_stdio, stdio lockdown first-task gate]
  affects: [all subsequent MCP plans depend on this lockdown being green]
tech_stack:
  added: []
  patterns:
    - "fd-level dup/dup2 ordering: os.dup(1) before os.dup2(2,1)"
    - "structlog PrintLoggerFactory reconfigured to file=sys.stderr"
    - "stdio_server(stdout=preserved) — explicit preserved handle"
key_files:
  created:
    - src/knowledge_lake/agent/__init__.py
    - src/knowledge_lake/agent/stdio.py
    - tests/integration/test_stdio_lockdown.py
  modified: []
decisions:
  - "InitializationOptions imported from mcp.server.models, not mcp.types (corrected during impl)"
  - "Log probe emitted inside call_tool handler so it fires AFTER lockdown is applied"
  - "cache_logger_on_first_use=False in stdio reconfigure to force re-bind to the new factory"
metrics:
  duration: "~15 min"
  completed: 2026-07-11
  tasks_completed: 2
  files_changed: 3
---

# Phase 12 Plan 04: fd-level stdout lockdown Summary

**One-liner:** fd-level dup/dup2 stdout lockdown shim (`run_stdio`) with deterministic subprocess self-test proving only JSON-RPC bytes reach stdout in stdio MCP mode.

## Objective

FIRST-TASK GATE (D-07/D-08): land the fd-level stdout-lockdown shim and its self-test in stdio mode ONLY, before any MCP tool logic exists.

Purpose: structlog's `PrintLoggerFactory()` (`__init__.py:42`, no `file=`) writes to stdout — the exact channel the MCP stdio JSON-RPC framing owns. Any stray log/print/C-extension byte corrupts the stream and kills the session. An fd-level `dup2` redirect (not merely reconfiguring the Python logger) is the robust fix; the self-test proves it deterministically.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | fd-level stdout-lockdown shim (agent/stdio.py) | `100520a` | `src/knowledge_lake/agent/__init__.py`, `src/knowledge_lake/agent/stdio.py` |
| 2 | stdio lockdown self-test (only JSON-RPC on stdout) | `baf2f3f` | `tests/integration/test_stdio_lockdown.py` |

## Implementation Details

### Task 1: run_stdio — fd-level lockdown in correct order

`src/knowledge_lake/agent/stdio.py` implements `run_stdio(server, init_opts)` with the mandatory 4-step ordering:

1. `real_fd = os.dup(1)` — preserve the real JSON-RPC fd BEFORE any redirect
2. `os.dup2(2, 1)` + `sys.stdout = sys.stderr` — redirect process fd 1 to stderr
3. Reconfigure structlog with `PrintLoggerFactory(file=sys.stderr)`, `logging.basicConfig(force=True)`, `logging.captureWarnings(True)`
4. Build `preserved = anyio.wrap_file(TextIOWrapper(os.fdopen(real_fd, "wb", buffering=0), encoding="utf-8"))` and call `async with stdio_server(stdout=preserved)`

This is stdio-only — HTTP mode never calls `run_stdio` (D-08 compliance).

### Task 2: Subprocess self-test

`tests/integration/test_stdio_lockdown.py` contains two tests:

- `test_run_stdio_is_importable` — confirms clean import of `run_stdio`
- `test_stdio_stdout_is_only_json_rpc` — spawns a subprocess with a trivial echo tool, drives a real JSON-RPC exchange (initialize + notifications/initialized + tools/call), and asserts:
  - All non-empty stdout lines parse as valid JSON-RPC (have `jsonrpc`/`id`/`result` keys)
  - The `lockdown-probe` structlog line emitted inside `call_tool` appears on stderr, not stdout

Both tests pass: `2 passed in 1.51s`

## Verification

```
$ uv run pytest tests/integration/test_stdio_lockdown.py -x -v
2 passed in 1.51s

$ uv run python -c "from knowledge_lake.agent.stdio import run_stdio; print('ok')"
ok

$ # Ordering guard
src.index('os.dup(1)') < src.index('os.dup2(2, 1)')  # PASSES
grep -c 'PrintLoggerFactory(file=' stdio.py  => 1
grep -c 'stdio_server(stdout='    stdio.py  => 4 (docstring + comment + actual call)
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `InitializationOptions` not in `mcp.types`**
- **Found during:** Task 1 import verification
- **Issue:** Plan said `from mcp.types import InitializationOptions` but the installed `mcp==1.28.1` exposes it at `mcp.server.models.InitializationOptions`
- **Fix:** Changed import to `from mcp.server.models import InitializationOptions`
- **Files modified:** `src/knowledge_lake/agent/stdio.py`
- **Commit:** `100520a`

**2. [Rule 2 - Correctness] Probe emitted inside call_tool not before run_stdio**
- **Found during:** Task 2 design — initial test attempt emitted log BEFORE calling `run_stdio`; the probe appeared on stdout (lockdown not yet applied)
- **Fix:** Test child script emits the `lockdown-probe` log line INSIDE the `call_tool` handler, which fires only after `run_stdio` has applied the lockdown
- **Commit:** `baf2f3f`

## Known Stubs

None — both created files are complete, functional implementations.

## Threat Surface Scan

No new network endpoints or auth paths introduced. This plan eliminates a threat surface (T-12-05): the fd-level lockdown closes the log-to-JSON-RPC-channel injection vector.

## Self-Check: PASSED

- [x] `src/knowledge_lake/agent/__init__.py` exists
- [x] `src/knowledge_lake/agent/stdio.py` exists with `run_stdio`
- [x] `tests/integration/test_stdio_lockdown.py` exists
- [x] Commit `100520a` exists (feat Task 1)
- [x] Commit `baf2f3f` exists (test Task 2)
- [x] `uv run pytest tests/integration/test_stdio_lockdown.py -x` — 2 passed
