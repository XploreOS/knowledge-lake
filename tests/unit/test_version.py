"""
Unit tests for knowledge_lake.version — pipeline_version helper (D-04, FOUND-06).

TDD: These tests define the expected behavior of pipeline_version().
"""

from __future__ import annotations

import re
from unittest.mock import patch


VERSION_WITH_SHA_PATTERN = re.compile(r"^\d+\.\d+\.\d+\+[0-9a-f]+$")
"""Pattern for 'N.N.N+shortsha' format."""

VERSION_WITHOUT_SHA_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
"""Pattern for bare 'N.N.N' format (no '+')."""


class TestPipelineVersionFormat:
    """pipeline_version() returns correctly formatted strings."""

    def test_returns_string(self) -> None:
        from knowledge_lake.version import pipeline_version

        result = pipeline_version()
        assert isinstance(result, str), f"Expected str, got {type(result)}"

    def test_never_raises(self) -> None:
        """pipeline_version must never raise regardless of environment."""
        from knowledge_lake.version import pipeline_version

        # Call multiple times; should never raise
        for _ in range(3):
            result = pipeline_version()
            assert result  # non-empty

    def test_format_with_git_sha(self) -> None:
        """When git is available and returns a SHA, format is 'version+sha'."""
        from knowledge_lake.version import pipeline_version

        # Mock subprocess to return a known SHA
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "abc1234\n"
            mock_run.return_value.returncode = 0
            result = pipeline_version()

        assert "+" in result, f"Expected '+' in result with git SHA: {result}"
        assert "abc1234" in result, f"Expected SHA 'abc1234' in result: {result}"

    def test_format_without_git_fallback(self) -> None:
        """When git is unavailable, returns bare package version (no '+')."""
        from knowledge_lake.version import pipeline_version

        with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            result = pipeline_version()

        assert "+" not in result, (
            f"Expected no '+' in fallback result: {result}"
        )
        assert VERSION_WITHOUT_SHA_PATTERN.match(result), (
            f"Expected 'N.N.N' format, got: {result}"
        )

    def test_empty_git_output_returns_pkg_only(self) -> None:
        """Empty git output (not in a git repo) returns bare package version."""
        from knowledge_lake.version import pipeline_version

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = ""
            mock_run.return_value.returncode = 128
            result = pipeline_version()

        # No '+' because SHA was empty
        assert "+" not in result


class TestPipelineVersionPackageVersion:
    """pipeline_version() uses package version as the base."""

    def test_contains_version_digits(self) -> None:
        """Result must contain at least N.N.N version digits."""
        from knowledge_lake.version import pipeline_version

        result = pipeline_version()
        # The result must start with a version number
        parts = result.split("+")
        base_version = parts[0]
        assert re.match(r"^\d+\.\d+\.\d+", base_version), (
            f"Result does not start with version digits: {result}"
        )

    def test_fallback_version_when_package_not_found(self) -> None:
        """When package metadata is unavailable, falls back to '0.0.0'."""
        from knowledge_lake.version import pipeline_version
        from importlib.metadata import PackageNotFoundError

        with patch("importlib.metadata.version", side_effect=PackageNotFoundError()):
            with patch("subprocess.run", side_effect=FileNotFoundError()):
                result = pipeline_version()

        assert result == "0.0.0", f"Expected '0.0.0' fallback, got: {result}"

    def test_git_exception_returns_pkg_only(self) -> None:
        """Any exception from git returns bare package version."""
        from knowledge_lake.version import pipeline_version

        with patch("subprocess.run", side_effect=Exception("unexpected error")):
            result = pipeline_version()

        # Must have a version number, no SHA appended
        assert "+" not in result
        assert re.match(r"^\d+\.\d+\.\d+", result)
