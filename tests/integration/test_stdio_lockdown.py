"""Stdio stdout-lockdown self-test (MCP-02, first-task gate, Plan 04).

Verifies that every non-empty stdout line produced by a subprocess running
``run_stdio`` is a well-formed JSON-RPC message — no banner text, no log
output, no structlog lines may appear on stdout.

Architecture (RESEARCH.md Pattern 2 / Pitfall 1 / D-07):
  structlog defaults to ``PrintLoggerFactory()`` (no ``file=``) which writes
  to stdout.  When stdio MCP transport is active, stdout IS the JSON-RPC
  channel.  The lockdown shim in ``agent/stdio.py`` must:
    1. ``os.dup(1)`` — preserve the real stdout fd BEFORE ``os.dup2(2, 1)``.
    2. ``os.dup2(2, 1)`` — redirect process fd 1 to stderr.
    3. Reconfigure structlog / stdlib logging / warnings to stderr.
    4. Pass the preserved handle as ``stdio_server(stdout=preserved)``.

Test strategy (mirrors tests/integration/test_scrapy_subprocess.py):
  Spawn a trivial MCP server subprocess (inline ``-c`` script) that:
    - builds a low-level ``Server`` with one ``echo`` tool,
    - calls a structlog ``logger.info(...)`` INSIDE ``call_tool`` so the log
      fires AFTER the lockdown is applied,
    - runs it under ``run_stdio``.

  The test drives the server with a real JSON-RPC exchange:
    initialize → notifications/initialized → tools/call (echo)

  Then it asserts:
    * every non-empty stdout line parses as JSON (has ``jsonrpc`` key), and
    * the structlog probe line that was emitted inside ``call_tool`` appears
      on stderr but not on stdout.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import threading
import time

import pytest

try:
    from knowledge_lake.agent.stdio import run_stdio  # noqa: F401
    _IMPORT_OK = True
except ImportError:
    _IMPORT_OK = False

# ── Subprocess child source ────────────────────────────────────────────────────

_CHILD_SCRIPT = textwrap.dedent("""\
    \"\"\"Trivial MCP stdio child for lockdown self-test.

    Builds a low-level Server with one echo tool, emits a structlog line
    INSIDE call_tool (after lockdown is applied), then runs under run_stdio.
    The log line must appear on stderr, never on stdout.
    \"\"\"
    import asyncio
    import structlog
    import mcp.types as types
    from mcp.server.lowlevel import Server
    from knowledge_lake.agent.stdio import run_stdio

    server = Server("test-lockdown-server")

    @server.list_tools()
    async def list_tools():
        return [
            types.Tool(
                name="echo",
                description="Echo input text",
                inputSchema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        # This log line fires AFTER run_stdio has applied the lockdown.
        # It must appear on stderr, never on stdout.
        structlog.get_logger("test-child").info(
            "lockdown-probe", tool=name
        )
        if name == "echo":
            return [types.TextContent(type="text", text=arguments.get("text", ""))]
        raise ValueError(f"Unknown tool: {name}")

    async def main():
        init_opts = server.create_initialization_options()
        await run_stdio(server, init_opts)

    asyncio.run(main())
""")

# ── JSON-RPC message helpers ───────────────────────────────────────────────────

_INIT_REQUEST = json.dumps({
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "0.0.1"},
    },
}) + "\n"

_INITIALIZED_NOTIF = json.dumps({
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
    "params": {},
}) + "\n"

_ECHO_CALL = json.dumps({
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {"name": "echo", "arguments": {"text": "hello-lockdown"}},
}) + "\n"

# Distinctive probe string that structlog will emit on stderr
_LOG_PROBE = "lockdown-probe"


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_run_stdio_is_importable() -> None:
    """run_stdio must be importable from knowledge_lake.agent.stdio (Plan 04)."""
    assert _IMPORT_OK, (
        "knowledge_lake.agent.stdio.run_stdio is not importable — "
        "Plan 04 must create agent/stdio.py"
    )
    from knowledge_lake.agent.stdio import run_stdio as _fn  # noqa: F401
    assert callable(_fn), "run_stdio must be a callable"


@pytest.mark.integration
def test_stdio_stdout_is_only_json_rpc() -> None:
    """Every non-empty stdout line from the stdio server must be valid JSON-RPC.

    The structlog probe line emitted inside ``call_tool`` must appear on stderr
    and must NOT appear on stdout.  Any non-JSON byte on stdout would corrupt
    the MCP transport (RESEARCH.md Pitfall 1, D-07/D-08).
    """
    assert _IMPORT_OK, "knowledge_lake.agent.stdio is not importable — skip"

    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD_SCRIPT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stripped = line.strip()
            if stripped:
                stderr_lines.append(stripped)

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    try:
        assert proc.stdin is not None
        assert proc.stdout is not None

        # Drive: initialize
        proc.stdin.write(_INIT_REQUEST)
        proc.stdin.flush()

        # Read initialize response
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline and len(stdout_lines) < 1:
            line = proc.stdout.readline()
            if not line:
                break
            stripped = line.strip()
            if stripped:
                stdout_lines.append(stripped)

        # Drive: notifications/initialized + tools/call
        proc.stdin.write(_INITIALIZED_NOTIF)
        proc.stdin.write(_ECHO_CALL)
        proc.stdin.flush()

        # Read tools/call response (second JSON-RPC message)
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline and len(stdout_lines) < 2:
            line = proc.stdout.readline()
            if not line:
                break
            stripped = line.strip()
            if stripped:
                stdout_lines.append(stripped)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    # Give stderr drain thread a moment to flush
    stderr_thread.join(timeout=2.0)

    # ── Assert: at least two JSON-RPC responses received ──────────────────────
    assert len(stdout_lines) >= 2, (
        f"Expected at least 2 JSON-RPC responses; got {len(stdout_lines)}: {stdout_lines}"
    )

    # ── Assert: every non-empty stdout line is valid JSON ─────────────────────
    parse_errors: list[str] = []
    for line in stdout_lines:
        try:
            parsed = json.loads(line)
            # Must have jsonrpc field — confirms it is a JSON-RPC envelope
            assert "jsonrpc" in parsed or "id" in parsed or "result" in parsed, (
                f"stdout line parsed as JSON but lacks JSON-RPC keys: {line!r}"
            )
        except json.JSONDecodeError:
            parse_errors.append(line)

    assert not parse_errors, (
        "Non-JSON lines found on stdout (violates MCP-02 stdout lockdown):\n"
        + "\n".join(f"  {line!r}" for line in parse_errors)
    )

    # ── Assert: structlog probe is on stderr, NOT on stdout ───────────────────
    stdout_joined = "\n".join(stdout_lines)
    assert _LOG_PROBE not in stdout_joined, (
        f"structlog probe {_LOG_PROBE!r} appeared on stdout — lockdown failed!\n"
        f"stdout lines: {stdout_lines}"
    )

    stderr_joined = "\n".join(stderr_lines)
    assert _LOG_PROBE in stderr_joined, (
        f"structlog probe {_LOG_PROBE!r} NOT found on stderr — "
        f"the log line may not have fired or stderr was not captured.\n"
        f"stderr lines: {stderr_lines}"
    )
