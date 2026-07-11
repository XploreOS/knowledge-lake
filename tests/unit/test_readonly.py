"""Wave 0 RED scaffold: readonly filter assertions (MCP-01).

Asserts that ``registered_tools(readonly=True)`` returns exactly the 4
read-only tools and excludes all write tools.

All tests are xfail until Plan 02 implements ``agent/registry.py``.
"""

from __future__ import annotations

import pytest

try:
    from knowledge_lake.agent.registry import registered_tools
    _IMPORT_OK = True
except ImportError:
    registered_tools = None  # type: ignore[assignment]
    _IMPORT_OK = False


_EXPECTED_READ_TOOLS = {"search", "list_sources", "lineage", "stats"}
_EXPECTED_WRITE_TOOLS = {
    "ingest_url",
    "crawl",
    "crawl_all",
    "process_crawled",
    "add_source",
    "export",
    "init_domain",
}


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — agent.registry not yet implemented", strict=False)
def test_readonly_returns_four_tools() -> None:
    """registered_tools(readonly=True) returns exactly 4 tools."""
    assert registered_tools is not None
    tools = registered_tools(readonly=True)
    assert len(tools) == 4, f"Expected 4 read-only tools, got {len(tools)}: {[t.name for t in tools]}"


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — agent.registry not yet implemented", strict=False)
def test_readonly_tool_names() -> None:
    """Read-only tools must be exactly: search, list_sources, lineage, stats."""
    assert registered_tools is not None
    tools = registered_tools(readonly=True)
    names = {t.name for t in tools}
    assert names == _EXPECTED_READ_TOOLS, (
        f"Readonly tool mismatch — expected {_EXPECTED_READ_TOOLS}, got {names}"
    )


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — agent.registry not yet implemented", strict=False)
def test_readonly_excludes_write_tools() -> None:
    """Read-only tool list must not contain any write tools."""
    assert registered_tools is not None
    tools = registered_tools(readonly=True)
    names = {t.name for t in tools}
    leaked = names & _EXPECTED_WRITE_TOOLS
    assert not leaked, f"Write tools leaked into readonly list: {leaked}"


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — agent.registry not yet implemented", strict=False)
def test_readonly_false_returns_all_tools() -> None:
    """registered_tools(readonly=False) returns all 11 tools."""
    assert registered_tools is not None
    all_tools = registered_tools(readonly=False)
    all_names = {t.name for t in all_tools}
    expected_all = _EXPECTED_READ_TOOLS | _EXPECTED_WRITE_TOOLS
    assert all_names == expected_all, (
        f"All-tools mismatch — expected {expected_all}, got {all_names}"
    )
