"""Unit tests for the `klake upload` CLI command's --source-url option (24-01 Task 2).

Follows tests/unit/test_cli_quality_audit.py's CliRunner + try/except-ImportError
guard pattern. cmd_upload uses a function-local import of ingest_file (`from
knowledge_lake.pipeline.ingest import ingest_file`), so tests patch it at its
SOURCE module (knowledge_lake.pipeline.ingest.ingest_file) — each CLI
invocation re-resolves the name from that module's current attribute.
"""

from __future__ import annotations

import os
import tempfile
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

_FAKE_RESULT = {
    "source_id": "src_fake",
    "artifact_id": "art_fake",
    "storage_uri": "s3://bucket/fake",
    "content_hash": "deadbeef",
}


def _tmp_file() -> str:
    """Create a small temporary file to pass as the upload path."""
    fd, path = tempfile.mkstemp(suffix=".pdf")
    with os.fdopen(fd, "wb") as f:
        f.write(b"%PDF-1.4 fake content")
    return path


class TestCliUploadSourceUrl:
    def test_upload_with_source_url(self) -> None:
        """--source-url is threaded to ingest_file(source_url=...) as a kwarg."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        tmp_path = _tmp_file()
        try:
            with patch(
                "knowledge_lake.pipeline.ingest.ingest_file",
                return_value=_FAKE_RESULT,
            ) as mock_ingest:
                result = runner.invoke(
                    app,
                    [
                        "upload",
                        tmp_path,
                        "--source",
                        "NIST AI 600-1",
                        "--license",
                        "public-domain",
                        "--source-url",
                        "https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf",
                    ],
                )

            assert result.exit_code == 0, (
                f"Expected exit 0, got {result.exit_code}. Output: {result.output!r}"
            )
            mock_ingest.assert_called_once()
            _, kwargs = mock_ingest.call_args
            assert (
                kwargs["source_url"]
                == "https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf"
            )
        finally:
            os.unlink(tmp_path)

    def test_upload_without_source_url_defaults_to_none(self) -> None:
        """Omitting --source-url calls ingest_file with source_url=None (no regression)."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        tmp_path = _tmp_file()
        try:
            with patch(
                "knowledge_lake.pipeline.ingest.ingest_file",
                return_value=_FAKE_RESULT,
            ) as mock_ingest:
                result = runner.invoke(
                    app,
                    [
                        "upload",
                        tmp_path,
                        "--source",
                        "X",
                        "--license",
                        "public-domain",
                    ],
                )

            assert result.exit_code == 0, (
                f"Expected exit 0, got {result.exit_code}. Output: {result.output!r}"
            )
            mock_ingest.assert_called_once()
            _, kwargs = mock_ingest.call_args
            assert kwargs["source_url"] is None
        finally:
            os.unlink(tmp_path)


class TestCliUploadHelp:
    def test_help_lists_source_url_option(self) -> None:
        """`klake upload --help` output contains the literal string --source-url."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        result = runner.invoke(app, ["upload", "--help"])
        assert result.exit_code == 0, (
            f"'upload --help' exited with {result.exit_code}: {result.output!r}"
        )
        assert "--source-url" in result.output
