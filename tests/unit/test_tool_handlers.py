"""Wave 0 RED scaffold: tool handler pipeline-binding assertions (D-03, MCP-01).

Asserts that each ToolDef.handler is a callable from a ``pipeline/*.py`` module,
not an api.app symbol. This prevents the MCP layer from coupling to the REST API
layer (D-03 thin-caller constraint).

All tests are xfail until Plan 02 implements ``agent/registry.py``.
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
