"""Wave 0 RED scaffold: tool handler pipeline-binding assertions (D-03, MCP-01).

Asserts that each ToolDef.handler is a callable from a ``pipeline/*.py`` module,
not an api.app symbol. This prevents the MCP layer from coupling to the REST API
layer (D-03 thin-caller constraint).

Task 3 additions: build_server correctness tests (Plan 12-05):
  - build_server returns a low-level MCP Server
  - list_tools emits inputSchema from input_model.model_json_schema()
  - call_tool dispatches correctly (async handlers awaited, ValueError → isError)
  - server.py contains no asyncio.run, contains iscoroutinefunction

All tests marked xfail until agent/registry.py + agent/server.py exist.
"""

from __future__ import annotations

import inspect

import pytest

try:
    from knowledge_lake.agent.registry import TOOLS
    _IMPORT_OK = True
except ImportError:
    TOOLS = None  # type: ignore[assignment]
    _IMPORT_OK = False

try:
    from knowledge_lake.agent.server import build_server
    from mcp.server.lowlevel import Server as _McpServer
    _SERVER_IMPORT_OK = True
except ImportError:
    build_server = None  # type: ignore[assignment]
    _McpServer = None  # type: ignore[assignment]
    _SERVER_IMPORT_OK = False


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — agent.registry not yet implemented", strict=False)
def test_each_tool_has_handler() -> None:
    """Every ToolDef must expose a callable 'handler' attribute."""
    assert TOOLS is not None
    for tool in TOOLS:
        assert hasattr(tool, "handler"), f"Tool {tool.name!r} missing 'handler'"
        assert callable(tool.handler), f"Tool {tool.name!r}.handler is not callable"


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — agent.registry not yet implemented", strict=False)
def test_handlers_are_pipeline_callables_not_api() -> None:
    """Handler modules must be under pipeline/, not api/app.py (D-03)."""
    assert TOOLS is not None
    for tool in TOOLS:
        handler = tool.handler
        module = getattr(handler, "__module__", "") or ""
        # Must come from pipeline.* or agent.* (the thin shim), NOT api.app
        assert "api.app" not in module, (
            f"Tool {tool.name!r} handler {handler!r} is bound to api.app — "
            "MCP handlers must call pipeline/* directly (D-03)"
        )
        # Must be from knowledge_lake package
        assert module.startswith("knowledge_lake."), (
            f"Tool {tool.name!r} handler module {module!r} is outside knowledge_lake package"
        )


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — agent.registry not yet implemented", strict=False)
def test_each_tool_has_input_model() -> None:
    """Each ToolDef must expose a Pydantic input_model (D-02 schema contract)."""
    assert TOOLS is not None
    for tool in TOOLS:
        assert hasattr(tool, "input_model"), f"Tool {tool.name!r} missing 'input_model'"
        # Must have model_json_schema() — marks it as a Pydantic model
        assert hasattr(tool.input_model, "model_json_schema"), (
            f"Tool {tool.name!r}.input_model is not a Pydantic model "
            f"(type: {type(tool.input_model)})"
        )


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — agent.registry not yet implemented", strict=False)
def test_each_tool_has_description() -> None:
    """Each ToolDef must have a non-empty string description."""
    assert TOOLS is not None
    for tool in TOOLS:
        assert hasattr(tool, "description"), f"Tool {tool.name!r} missing 'description'"
        assert isinstance(tool.description, str), (
            f"Tool {tool.name!r}.description is not a string"
        )
        assert tool.description.strip(), f"Tool {tool.name!r}.description is empty"


# ── build_server tests (Task 3 — Plan 12-05) ─────────────────────────────────


@pytest.mark.xfail(not _SERVER_IMPORT_OK, reason="agent.server not yet implemented", strict=False)
def test_build_server_returns_server_instance() -> None:
    """build_server(TOOLS) must return a low-level mcp.server.lowlevel.Server."""
    assert build_server is not None
    assert _McpServer is not None
    assert TOOLS is not None
    server = build_server(TOOLS)
    assert isinstance(server, _McpServer), (
        f"Expected mcp.server.lowlevel.Server, got {type(server)}"
    )


@pytest.mark.xfail(not _SERVER_IMPORT_OK, reason="agent.server not yet implemented", strict=False)
def test_build_server_name() -> None:
    """Server must be named 'knowledge-lake'."""
    assert build_server is not None
    assert TOOLS is not None
    server = build_server(TOOLS)
    assert server.name == "knowledge-lake"


@pytest.mark.xfail(not _SERVER_IMPORT_OK, reason="agent.server not yet implemented", strict=False)
def test_server_no_asyncio_run() -> None:
    """server.py must not contain asyncio.run (D-12 prohibition)."""
    import importlib.util, pathlib

    spec = importlib.util.find_spec("knowledge_lake.agent.server")
    assert spec is not None
    src = pathlib.Path(spec.origin).read_text()
    assert "asyncio.run" not in src, (
        "asyncio.run found in server.py — use 'await' for async handlers (D-12)"
    )


@pytest.mark.xfail(not _SERVER_IMPORT_OK, reason="agent.server not yet implemented", strict=False)
def test_server_has_iscoroutinefunction() -> None:
    """server.py must use inspect.iscoroutinefunction for async/sync dispatch."""
    import importlib.util, pathlib

    spec = importlib.util.find_spec("knowledge_lake.agent.server")
    assert spec is not None
    src = pathlib.Path(spec.origin).read_text()
    assert "iscoroutinefunction" in src, (
        "iscoroutinefunction not found in server.py — async bridge missing (D-12)"
    )


@pytest.mark.xfail(not _SERVER_IMPORT_OK, reason="agent.server not yet implemented", strict=False)
@pytest.mark.anyio
async def test_list_tools_uses_input_model_schema() -> None:
    """list_tools must return inputSchema from input_model.model_json_schema()."""
    from mcp.types import ListToolsRequest

    assert build_server is not None
    assert TOOLS is not None

    server = build_server(TOOLS)
    # Invoke the registered list_tools handler via request_handlers
    handler = server.request_handlers[ListToolsRequest]
    req = ListToolsRequest(method="tools/list", params=None)
    server_result = await handler(req)
    mcp_tools = server_result.root.tools

    assert len(mcp_tools) == len(TOOLS)

    by_name = {t.name: t for t in TOOLS}
    for mcp_tool in mcp_tools:
        tdef = by_name[mcp_tool.name]
        expected_schema = tdef.input_model.model_json_schema()
        assert mcp_tool.inputSchema == expected_schema, (
            f"Tool {mcp_tool.name!r} inputSchema mismatch: "
            f"expected {expected_schema}, got {mcp_tool.inputSchema}"
        )


# ── _add_source_handler body tests (CR-01, WR-02) ────────────────────────────
# These exercise the handler BODY (not just the ToolDef wiring). No test
# covered this before, which is why the register_source(session, ...) call
# signature bug shipped silently. We patch register_source at the registry
# module boundary so no live Postgres/MinIO is required.


@pytest.mark.skipif(not _IMPORT_OK, reason="agent.registry not yet importable")
def test_add_source_handler_calls_register_source_without_session(monkeypatch) -> None:
    """Handler must call register_source(url, name, ...) — no session arg, url once (CR-01)."""
    from knowledge_lake.agent import registry as _registry

    captured: dict = {}

    def _stub_register_source(url, name, *, domain=None, license_type="unknown", **kwargs):
        captured["url"] = url
        captured["name"] = name
        captured["domain"] = domain
        captured["license_type"] = license_type
        captured["extra_kwargs"] = kwargs
        # Representative return shape from the real register_source (a dict).
        return {
            "source_id": "src-abc123",
            "name": name,
            "url": url,
            "normalized_url": url,
            "domain": domain,
            "is_new": True,
        }

    monkeypatch.setattr(_registry, "register_source", _stub_register_source)

    result = _registry._add_source_handler(
        url="https://example.com/docs",
        name="Example Docs",
        domain="healthcare",
        license_type="CC-BY-4.0",
    )

    # url passed exactly once (positionally); no session leaked into kwargs.
    assert captured["url"] == "https://example.com/docs"
    assert captured["name"] == "Example Docs"
    assert captured["domain"] == "healthcare"
    assert captured["license_type"] == "CC-BY-4.0"
    assert captured["extra_kwargs"] == {}

    # Response dict maps register_source's returned keys.
    assert result == {
        "source_id": "src-abc123",
        "name": "Example Docs",
        "url": "https://example.com/docs",
        "is_new": True,
    }


@pytest.mark.skipif(not _IMPORT_OK, reason="agent.registry not yet importable")
def test_add_source_handler_defaults_name_to_hostname(monkeypatch) -> None:
    """When name is omitted, default it to the URL hostname (WR-02, CLI parity)."""
    from knowledge_lake.agent import registry as _registry

    captured: dict = {}

    def _stub_register_source(url, name, *, domain=None, license_type="unknown", **kwargs):
        captured["name"] = name
        return {
            "source_id": "src-1",
            "name": name,
            "url": url,
            "normalized_url": url,
            "domain": domain,
            "is_new": True,
        }

    monkeypatch.setattr(_registry, "register_source", _stub_register_source)

    result = _registry._add_source_handler(url="https://health.example.org/a/b")

    assert captured["name"] == "health.example.org"
    assert result["name"] == "health.example.org"


@pytest.mark.xfail(not _SERVER_IMPORT_OK, reason="agent.server not yet implemented", strict=False)
@pytest.mark.anyio
async def test_call_tool_value_error_returns_is_error() -> None:
    """ValueError from a handler must return isError=True (D-13)."""
    from mcp.types import CallToolRequest, CallToolRequestParams

    assert build_server is not None

    # Build a test server with a minimal handler that raises ValueError
    from knowledge_lake.agent.registry import ToolDef
    from knowledge_lake.api.schemas import StatsInput

    def _raising_handler(**kwargs):  # type: ignore[return]
        raise ValueError("test error from handler")

    test_tools = [
        ToolDef(
            name="stats",
            description="test stats tool",
            input_model=StatsInput,
            handler=_raising_handler,
            access="read",
        )
    ]
    server = build_server(test_tools)
    handler = server.request_handlers[CallToolRequest]
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="stats", arguments={}),
    )
    server_result = await handler(req)
    call_result = server_result.root  # unwrap ServerResult → CallToolResult
    assert call_result.isError is True, (
        f"Expected isError=True for ValueError, got isError={call_result.isError}"
    )
