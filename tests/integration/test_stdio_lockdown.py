"""Wave 0 RED scaffold: stdio stdout lockdown integration test (MCP-02, first-task gate).

FIRST-TASK GATE: When Plan 04 implements the fd-level stdout lockdown shim in
``agent/stdio.py``, this test verifies that every non-empty stdout line produced
by ``klake mcp`` (stdio mode) is a well-formed JSON-RPC message — no banner text,
no log output, no structlog lines may appear on stdout.

Architecture note (RESEARCH.md Pattern 2 / Pitfall 1):
  structlog defaults to PrintLoggerFactory() which writes to stdout. When stdio
  MCP transport is active, stdout IS the JSON-RPC channel. Any non-JSON bytes on
  stdout corrupt the MCP transport. The lockdown shim must:
    1. os.dup(1) to preserve the real stdout fd before os.dup2(2, 1) redirects it.
    2. Reconfigure structlog to write to stderr.
    3. Pass the preserved fd to mcp.server.stdio.stdio_server(stdout=...).

Test strategy (mirrors tests/integration/test_scrapy_subprocess.py):
  Spawn ``klake mcp`` as a subprocess, send a trivial JSON-RPC initialize request
  over stdin, read stdout for up to 5 seconds, and assert every non-empty line is
  valid JSON (JSON-RPC envelope).

This test is xfail (strict=False) until Plan 04 lands the lockdown.
"""

from __future__ import annotations

import json

import pytest

try:
    from knowledge_lake.agent.stdio import run_stdio
    _IMPORT_OK = True
except ImportError:
    run_stdio = None  # type: ignore[assignment]
    _IMPORT_OK = False


@pytest.mark.integration
@pytest.mark.xfail(
    reason="Wave 0 scaffold — agent.stdio stdout lockdown not yet implemented (Plan 04)",
    strict=False,
)
def test_stdio_stdout_is_only_json_rpc() -> None:
    """Every non-empty stdout line from klake mcp (stdio) must be valid JSON-RPC.

    Assertion intent (MCP-02 FIRST-TASK GATE):
      - Spawn ``klake mcp`` as a subprocess (no --sse flag → stdio transport).
      - Write a JSON-RPC 2.0 initialize request to stdin.
      - Read stdout lines for up to 5 seconds.
      - Assert every non-empty line parses as JSON.
      - Assert no plain text / log / banner bytes appear on stdout.

    If any non-JSON line is found, the lockdown shim is broken and MCP clients
    will see corrupted transport (RESEARCH.md Pitfall 1).
    """
    import subprocess
    import sys
    import time

    init_request = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.0.1"},
        },
    }) + "\n"

    proc = subprocess.Popen(
        [sys.executable, "-m", "knowledge_lake.cli.app", "mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout_lines: list[str] = []
    parse_errors: list[str] = []

    try:
        assert proc.stdin is not None
        proc.stdin.write(init_request)
        proc.stdin.flush()

        deadline = time.monotonic() + 5.0
        assert proc.stdout is not None
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            stripped = line.strip()
            if not stripped:
                continue
            stdout_lines.append(stripped)
            try:
                json.loads(stripped)
            except json.JSONDecodeError:
                parse_errors.append(stripped)
            # Stop after receiving one response
            if len(stdout_lines) >= 1:
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    assert stdout_lines, "No output received from klake mcp — process may have failed to start"
    assert not parse_errors, (
        f"Non-JSON lines found on stdout (violates MCP-02 lockdown):\n"
        + "\n".join(f"  {line!r}" for line in parse_errors)
    )


@pytest.mark.integration
@pytest.mark.xfail(
    reason="Wave 0 scaffold — agent.stdio not yet implemented (Plan 04)",
    strict=False,
)
def test_stdio_run_stdio_is_importable() -> None:
    """run_stdio must be importable from knowledge_lake.agent.stdio (Plan 04)."""
    assert _IMPORT_OK, (
        "knowledge_lake.agent.stdio.run_stdio is not importable — "
        "Plan 04 must create agent/stdio.py"
    )
    assert callable(run_stdio), "run_stdio must be a callable"
