"""Tests for CLI init/index commands (IFACE-01).

Import uses a try/except guard so pytest can collect the file before the commands exist.
"""

from __future__ import annotations

try:
    from typer.testing import CliRunner
    from knowledge_lake.cli.app import app
    _IMPORT_OK = True
except ImportError:
    CliRunner = None  # type: ignore[assignment, misc]
    app = None  # type: ignore[assignment]
    _IMPORT_OK = False

runner = CliRunner() if CliRunner is not None else None


def test_init_command_exists() -> None:
    """typer app ["init", "--domain", "healthcare"] must not produce 'No such command' error."""
    assert _IMPORT_OK, "CliRunner or app import failed"
    assert runner is not None
    result = runner.invoke(app, ["init", "--domain", "healthcare"])
    assert "No such command" not in (result.output or ""), (
        f"init command not registered. Output: {result.output!r}"
    )


def test_init_command_help() -> None:
    """app ['init', '--help'] must exit 0 and output must contain '--domain'."""
    assert _IMPORT_OK, "CliRunner or app import failed"
    assert runner is not None
    result = runner.invoke(app, ["init", "--help"])
    assert result.exit_code == 0, (
        f"Expected exit 0 for 'init --help', got {result.exit_code}. Output: {result.output!r}"
    )
    assert "--domain" in result.output, (
        f"'--domain' not found in 'init --help' output: {result.output!r}"
    )


def test_index_command_exists() -> None:
    """app ['index', '--help'] must exit 0 and output must contain '--collection'."""
    assert _IMPORT_OK, "CliRunner or app import failed"
    assert runner is not None
    result = runner.invoke(app, ["index", "--help"])
    assert result.exit_code == 0, (
        f"Expected exit 0 for 'index --help', got {result.exit_code}. Output: {result.output!r}"
    )
    assert "--collection" in result.output, (
        f"'--collection' not found in 'index --help' output: {result.output!r}"
    )
