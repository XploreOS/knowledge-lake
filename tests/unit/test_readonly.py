"""Wave 0 RED scaffold: readonly filter assertions (MCP-01).

Asserts that ``registered_tools(readonly=True)`` returns exactly the 4
read-only tools and excludes all write tools.

Also asserts McpSettings defaults and environment-variable resolution
(Plan 12-05 Task 1 — settings.py McpSettings nested model).

All tests marked xfail until agent/registry.py and McpSettings are implemented.
"""

from __future__ import annotations

import pytest

try:
    from knowledge_lake.agent.registry import registered_tools
    _IMPORT_OK = True
except ImportError:
    registered_tools = None  # type: ignore[assignment]
    _IMPORT_OK = False

try:
    from knowledge_lake.config.settings import McpSettings, Settings
    _MCP_SETTINGS_OK = True
except ImportError:
    McpSettings = None  # type: ignore[assignment,misc]
    Settings = None  # type: ignore[assignment]
    _MCP_SETTINGS_OK = False


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


# ── McpSettings tests (Task 1 — Plan 12-05) ──────────────────────────────────


@pytest.mark.xfail(not _MCP_SETTINGS_OK, reason="McpSettings not yet implemented in settings.py", strict=False)
def test_mcp_settings_default_host() -> None:
    """McpSettings.host defaults to '127.0.0.1' (localhost-safe)."""
    assert McpSettings is not None
    s = McpSettings()
    assert s.host == "127.0.0.1", f"Expected '127.0.0.1', got {s.host!r}"


@pytest.mark.xfail(not _MCP_SETTINGS_OK, reason="McpSettings not yet implemented in settings.py", strict=False)
def test_mcp_settings_default_readonly_false() -> None:
    """McpSettings.readonly defaults to False."""
    assert McpSettings is not None
    s = McpSettings()
    assert s.readonly is False, f"Expected False, got {s.readonly!r}"


@pytest.mark.xfail(not _MCP_SETTINGS_OK, reason="McpSettings not yet implemented in settings.py", strict=False)
def test_mcp_settings_default_port() -> None:
    """McpSettings.port defaults to 3001."""
    assert McpSettings is not None
    s = McpSettings()
    assert s.port == 3001, f"Expected 3001, got {s.port!r}"


@pytest.mark.xfail(not _MCP_SETTINGS_OK, reason="McpSettings not yet implemented in settings.py", strict=False)
def test_mcp_settings_default_token_none() -> None:
    """McpSettings.token defaults to None (no baked-in secret)."""
    assert McpSettings is not None
    s = McpSettings()
    assert s.token is None, f"Expected None, got {s.token!r}"


@pytest.mark.xfail(not _MCP_SETTINGS_OK, reason="McpSettings not yet implemented in settings.py", strict=False)
def test_settings_has_mcp_mount() -> None:
    """Settings must expose a .mcp attribute of type McpSettings."""
    assert Settings is not None
    assert McpSettings is not None
    s = Settings()
    assert hasattr(s, "mcp"), "Settings missing 'mcp' attribute"
    assert isinstance(s.mcp, McpSettings), (
        f"settings.mcp should be McpSettings, got {type(s.mcp)}"
    )
