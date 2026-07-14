"""Unit tests for CLI search --route flag threading (ROUTE-04, ASVS V5).

Pattern mirrors tests/unit/test_cli_search_mode.py: CliRunner + try/except
ImportError guard. Patch at knowledge_lake.pipeline.route.routed_search (the
symbol that cmd_search imports from pipeline.route).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

try:
    from typer.testing import CliRunner
    from knowledge_lake.cli.app import app
    _IMPORT_OK = True
except ImportError:
    CliRunner = None  # type: ignore[assignment, misc]
    app = None  # type: ignore[assignment]
    _IMPORT_OK = False

runner = CliRunner() if CliRunner is not None else None


class TestCliRouteForwarding:
    """CLI --route flag threads route into routed_search (ROUTE-04)."""

    def test_route_flag_forwarded(self) -> None:
        """klake search 'test' --route tree calls routed_search with route='tree'."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        captured_kwargs: dict = {}

        def routed_search_stub(query: str, **kwargs) -> list:
            captured_kwargs.update({"query": query, **kwargs})
            return []

        with patch(
            "knowledge_lake.pipeline.route.routed_search",
            side_effect=routed_search_stub,
        ):
            result = runner.invoke(app, ["search", "test query", "--route", "tree"])

        assert result.exit_code == 0, (
            f"Expected exit 0 for 'search <q> --route tree', got {result.exit_code}. "
            f"Output: {result.output!r}"
        )
        assert captured_kwargs.get("route") == "tree", (
            f"Expected route='tree' forwarded to routed_search, "
            f"got: {captured_kwargs.get('route')!r}. Full kwargs: {captured_kwargs}"
        )

    def test_route_invalid_exit1(self) -> None:
        """klake search 'test' --route bogus exits with code 1 and prints error to stderr."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        result = runner.invoke(app, ["search", "test query", "--route", "bogus"])
        assert result.exit_code == 1, (
            f"Expected exit 1 for --route bogus (invalid route), got {result.exit_code}. "
            f"Output: {result.output!r}"
        )
        combined_output = result.output + (result.stderr if hasattr(result, "stderr") and result.stderr else "")
        assert "bogus" in combined_output or "route" in combined_output.lower(), (
            f"Expected error message mentioning 'bogus' or 'route', got: {combined_output!r}"
        )

    def test_route_omitted_forwards_none(self) -> None:
        """klake search 'test' (no --route) calls routed_search with route=None."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        captured_kwargs: dict = {}

        def routed_search_stub(query: str, **kwargs) -> list:
            captured_kwargs.update({"query": query, **kwargs})
            return []

        with patch(
            "knowledge_lake.pipeline.route.routed_search",
            side_effect=routed_search_stub,
        ):
            result = runner.invoke(app, ["search", "test query"])

        assert result.exit_code == 0, (
            f"Expected exit 0 for 'search <q>' (no route), got {result.exit_code}. "
            f"Output: {result.output!r}"
        )
        assert captured_kwargs.get("route") is None, (
            f"Expected route=None when not specified, "
            f"got: {captured_kwargs.get('route')!r}. Full kwargs: {captured_kwargs}"
        )
