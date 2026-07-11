"""Wave 0 RED scaffold: tool registry assertions (D-11, MCP-01).

Asserts that ``knowledge_lake.agent.registry.TOOLS`` yields exactly 11 tools
with unique names and explicit read/write access tags.

All tests are xfail until Plan 02 implements ``agent/registry.py``.
Uses the import-guard pattern from test_api_new_endpoints.py lines 12-19.
"""

from __future__ import annotations

import pytest

try:
    from knowledge_lake.agent.registry import TOOLS, registered_tools
    _IMPORT_OK = True
except ImportError:
    TOOLS = None  # type: ignore[assignment]
    registered_tools = None  # type: ignore[assignment]
    _IMPORT_OK = False


_EXPECTED_TOOL_NAMES = {
    "search",
    "ingest_url",
    "crawl",
    "crawl_all",
    "process_crawled",
    "add_source",
    "list_sources",
    "lineage",
    "export",
    "init_domain",
    "stats",
}


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — agent.registry not yet implemented", strict=False)
def test_tools_count_is_eleven() -> None:
    """TOOLS must contain exactly 11 entries (D-11 tool list)."""
    assert TOOLS is not None
    assert len(TOOLS) == 11, f"Expected 11 tools, got {len(TOOLS)}: {[t.name for t in TOOLS]}"


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — agent.registry not yet implemented", strict=False)
def test_tool_names_are_unique() -> None:
    """All tool names must be unique (no duplicates)."""
    assert TOOLS is not None
    names = [t.name for t in TOOLS]
    assert len(names) == len(set(names)), f"Duplicate tool names: {names}"


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — agent.registry not yet implemented", strict=False)
def test_tool_names_match_expected_set() -> None:
    """Tool names must match the 11 expected names from D-11."""
    assert TOOLS is not None
    names = {t.name for t in TOOLS}
    assert names == _EXPECTED_TOOL_NAMES, (
        f"Missing: {_EXPECTED_TOOL_NAMES - names}; Extra: {names - _EXPECTED_TOOL_NAMES}"
    )


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — agent.registry not yet implemented", strict=False)
def test_each_tool_has_access_tag() -> None:
    """Each ToolDef must have an 'access' attribute of 'read' or 'write'."""
    assert TOOLS is not None
    for tool in TOOLS:
        assert hasattr(tool, "access"), f"Tool {tool.name!r} missing 'access' attribute"
        assert tool.access in ("read", "write"), (
            f"Tool {tool.name!r} has invalid access {tool.access!r}; expected 'read' or 'write'"
        )


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — agent.registry not yet implemented", strict=False)
def test_read_only_tools_subset() -> None:
    """registered_tools(readonly=True) returns only the 4 read-access tools."""
    assert registered_tools is not None
    read_tools = registered_tools(readonly=True)
    assert len(read_tools) == 4, f"Expected 4 read tools, got {len(read_tools)}"
    for tool in read_tools:
        assert tool.access == "read", f"Tool {tool.name!r} is not read-access"


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — agent.registry not yet implemented", strict=False)
def test_registered_tools_all_returns_all() -> None:
    """registered_tools() with no args (or readonly=False) returns all 11 tools."""
    assert registered_tools is not None
    all_tools = registered_tools()
    assert len(all_tools) == 11, f"Expected 11 tools, got {len(all_tools)}"
