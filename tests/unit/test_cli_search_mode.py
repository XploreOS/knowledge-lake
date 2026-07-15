"""Unit tests for CLI search --mode flag threading (RETR-03, Plan 10-08).

RED test scaffold: asserts that invoking `klake search <query> --mode hybrid`
forwards mode='hybrid' into pipeline.search. The --mode flag does not yet exist
on cmd_search — Plan 10-08 added it. All three tests now pass; the two
forwarding tests previously patched the wrong target (see KL-19 in
E2E-GAP-ANALYSIS.md) — fixed to patch knowledge_lake.pipeline.route.search,
which is what routed_search() actually calls.

Pattern: monkeypatch knowledge_lake.pipeline.route.search (what routed_search()
actually calls), capture forwarded kwargs via a stub, then invoke the CLI runner.
Mirrors tests/unit/test_cli_init_index.py: CliRunner + try/except ImportError guard.
"""

from __future__ import annotations

from unittest.mock import patch

try:
    from typer.testing import CliRunner

    from knowledge_lake.cli.app import app
    _IMPORT_OK = True
except ImportError:
    CliRunner = None  # type: ignore[assignment, misc]
    app = None  # type: ignore[assignment]
    _IMPORT_OK = False

runner = CliRunner() if CliRunner is not None else None


class TestCliModeForwarding:
    """CLI --mode flag threads mode into pipeline.search (RETR-03, T-10-02)."""

    def test_cli_mode_forwarded_hybrid(self) -> None:
        """Invoking `search <q> --mode hybrid` forwards mode='hybrid' into pipeline.search.

        Encodes: must_have truth §4 (RETR-03 — CLI --mode threading).
        """
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        # Capture what pipeline.search.search was called with
        captured_kwargs: dict = {}

        def search_stub(query: str, **kwargs) -> list:  # type: ignore[return]
            captured_kwargs.update({"query": query, **kwargs})
            return []

        # cmd_search delegates to routed_search(), which calls its own
        # module-level `search` binding (route.py: `from
        # knowledge_lake.pipeline.search import search`) — not
        # pipeline.search.search directly (KL-19). Patch the real target.
        with patch("knowledge_lake.pipeline.route.search", side_effect=search_stub):
            result = runner.invoke(app, ["search", "test query", "--mode", "hybrid"])

        assert result.exit_code == 0, (
            f"Expected exit 0 for 'search <q> --mode hybrid', got {result.exit_code}. "
            f"Output: {result.output!r}"
        )
        assert captured_kwargs.get("mode") == "hybrid", (
            f"Expected mode='hybrid' forwarded to pipeline.search, "
            f"got: {captured_kwargs.get('mode')!r}. Full kwargs: {captured_kwargs}"
        )

    def test_cli_mode_forwarded_dense(self) -> None:
        """Invoking `search <q> --mode dense` forwards mode='dense' into pipeline.search."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        captured_kwargs: dict = {}

        def search_stub(query: str, **kwargs) -> list:  # type: ignore[return]
            captured_kwargs.update({"query": query, **kwargs})
            return []

        with patch("knowledge_lake.pipeline.route.search", side_effect=search_stub):
            result = runner.invoke(app, ["search", "test query", "--mode", "dense"])

        assert result.exit_code == 0, (
            f"Expected exit 0 for 'search <q> --mode dense', got {result.exit_code}. "
            f"Output: {result.output!r}"
        )
        assert captured_kwargs.get("mode") == "dense", (
            f"Expected mode='dense' forwarded to pipeline.search, "
            f"got: {captured_kwargs.get('mode')!r}"
        )

    def test_cli_search_mode_help_shows_mode_option(self) -> None:
        """klake search --help must list --mode as an accepted option (Plan 10-08)."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0, (
            f"'search --help' exited with {result.exit_code}: {result.output!r}"
        )
        assert "--mode" in result.output, (
            f"'--mode' option not found in 'search --help' output: {result.output!r}"
        )
