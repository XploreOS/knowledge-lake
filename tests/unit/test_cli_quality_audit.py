"""Unit tests for `klake quality-audit` CLI command (MEAS-01, Phase 17 Plan 04).

Follows tests/unit/test_cli_search_mode.py's CliRunner + try/except-ImportError-
guard pattern. cmd_quality_audit uses a function-local import of
run_quality_audit (`from knowledge_lake.pipeline.quality_audit import
run_quality_audit`), so tests patch it at its SOURCE module
(knowledge_lake.pipeline.quality_audit.run_quality_audit) — each CLI
invocation re-resolves the name from that module's current attribute.
"""

from __future__ import annotations

import json
import re
from unittest.mock import patch

try:
    from typer.testing import CliRunner

    from knowledge_lake.cli.app import app
    _IMPORT_OK = True
except ImportError:
    CliRunner = None  # type: ignore[assignment, misc]
    app = None  # type: ignore[assignment]
    _IMPORT_OK = False


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return re.sub(r'\x1b\[[^m]*m', '', text)


runner = CliRunner() if CliRunner is not None else None


_TWO_ROWS = [
    {
        "source_id": "src_a",
        "source_name": "Source A",
        "sections_considered": 4,
        "sections_kept": 3,
        "sections_rejected": 1,
        "rejection_reasons": {"empty_after_boilerplate_removal": 1},
        "documents_errored": 0,
        "garbage_rate": 0.25,
    },
    {
        "source_id": "src_b",
        "source_name": "Source B",
        "sections_considered": 0,
        "sections_kept": 0,
        "sections_rejected": 0,
        "rejection_reasons": {},
        "documents_errored": 0,
        "garbage_rate": None,
    },
]


class TestCliQualityAuditTable:
    def test_table_output_contains_source_names_and_percentage(self) -> None:
        """`quality-audit --domain healthcare` prints a table with both source_names and % garbage_rate."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        with patch(
            "knowledge_lake.pipeline.quality_audit.run_quality_audit",
            return_value=_TWO_ROWS,
        ):
            result = runner.invoke(app, ["quality-audit", "--domain", "healthcare"])

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. Output: {result.output!r}"
        )
        output = _strip_ansi(result.output)
        assert "Source A" in output
        assert "Source B" in output
        assert "25.0%" in output

    def test_none_garbage_rate_prints_na(self) -> None:
        """A row with garbage_rate=None prints 'N/A', not '0.0%' or a blank cell."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        with patch(
            "knowledge_lake.pipeline.quality_audit.run_quality_audit",
            return_value=_TWO_ROWS,
        ):
            result = runner.invoke(app, ["quality-audit", "--domain", "healthcare"])

        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "N/A" in output
        assert "0.0%" not in output


class TestCliQualityAuditJson:
    def test_json_output_preserves_unrounded_garbage_rate(self) -> None:
        """`--json` prints output that json.loads()-parses into the mocked rows list, floats unrounded."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        with patch(
            "knowledge_lake.pipeline.quality_audit.run_quality_audit",
            return_value=_TWO_ROWS,
        ):
            result = runner.invoke(
                app, ["quality-audit", "--domain", "healthcare", "--json"]
            )

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. Output: {result.output!r}"
        )
        parsed = json.loads(result.output)
        assert parsed == _TWO_ROWS
        assert parsed[0]["garbage_rate"] == 0.25
        assert parsed[1]["garbage_rate"] is None


class TestCliQualityAuditEmptyDomain:
    def test_empty_result_prints_explicit_message_and_exits_zero(self) -> None:
        """`--domain nonexistent` with zero rows prints 'No sources found ...' and exits 0."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        with patch(
            "knowledge_lake.pipeline.quality_audit.run_quality_audit",
            return_value=[],
        ):
            result = runner.invoke(app, ["quality-audit", "--domain", "nonexistent"])

        assert result.exit_code == 0, (
            f"Expected exit 0 for an empty (not error) result, got {result.exit_code}. "
            f"Output: {result.output!r}"
        )
        output = _strip_ansi(result.output)
        assert "No sources found" in output
        assert "nonexistent" in output


class TestCliQualityAuditHelp:
    def test_help_lists_domain_and_json_options(self) -> None:
        """`quality-audit --help` exits 0 and lists both --domain/-d and --json."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        result = runner.invoke(app, ["quality-audit", "--help"])
        assert result.exit_code == 0, (
            f"'quality-audit --help' exited with {result.exit_code}: {result.output!r}"
        )
        output = _strip_ansi(result.output)
        assert "--domain" in output
        assert "-d" in output
        assert "--json" in output

    def test_help_lists_full_flag(self) -> None:
        """`quality-audit --help` also lists the new --full flag (Phase 22 Plan 02)."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        result = runner.invoke(app, ["quality-audit", "--help"])
        assert result.exit_code == 0, (
            f"'quality-audit --help' exited with {result.exit_code}: {result.output!r}"
        )
        output = _strip_ansi(result.output)
        assert "--full" in output


_FULL_RESULT = {
    "rows": [
        {
            "source_id": "src_a",
            "source_name": "Source A",
            "sections_considered": 4,
            "sections_kept": 3,
            "sections_rejected": 1,
            "rejection_reasons": {"empty_after_boilerplate_removal": 1},
            "documents_errored": 0,
            "garbage_rate": 0.25,
            "chunks_considered": 4,
            "chunks_kept": 3,
            "chunks_rejected": 1,
            "chunk_rejection_reasons": {"low_substance": 1},
            "chunk_garbage_rate": 0.25,
        },
    ],
    "summary": {
        "domain": "healthcare",
        "sources_count": 1,
        "documents_errored": 0,
        "sections_considered": 4,
        "sections_kept": 3,
        "sections_rejected": 1,
        "sections_garbage_rate": 0.25,
        "chunks_considered": 4,
        "chunks_kept": 3,
        "chunks_rejected": 1,
        "chunk_rejection_reasons": {"low_substance": 1},
        "chunk_garbage_rate": 0.25,
        "export_kept": 3,
        "export_junk": 0,
        "export_junk_rate": 0.0,
        "baseline_chunk_garbage_rate": 0.28,
        "baseline_export_junk_rate": 0.33,
    },
}

_FULL_RESULT_EMPTY = {
    "rows": [],
    "summary": {
        "domain": "healthcare",
        "sources_count": 0,
        "documents_errored": 0,
        "sections_considered": 0,
        "sections_kept": 0,
        "sections_rejected": 0,
        "sections_garbage_rate": None,
        "chunks_considered": 0,
        "chunks_kept": 0,
        "chunks_rejected": 0,
        "chunk_rejection_reasons": {},
        "chunk_garbage_rate": None,
        "export_kept": 0,
        "export_junk": 0,
        "export_junk_rate": None,
        "baseline_chunk_garbage_rate": 0.28,
        "baseline_export_junk_rate": 0.33,
    },
}


class TestCliQualityAuditFullFlag:
    def test_full_table_output_contains_chunk_columns_and_baseline(self) -> None:
        """`--full` prints chunk-level columns plus a summary block with both baselines."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        with patch(
            "knowledge_lake.pipeline.quality_audit.run_full_pipeline_audit",
            return_value=_FULL_RESULT,
        ):
            result = runner.invoke(
                app, ["quality-audit", "--domain", "healthcare", "--full"]
            )

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. Output: {result.output!r}"
        )
        output = _strip_ansi(result.output)
        assert "Source A" in output
        assert "25.0%" in output
        assert "28" in output
        assert "33" in output

    def test_full_json_round_trips_rows_and_summary(self) -> None:
        """`--full --json` round-trips the exact mocked {"rows":..., "summary":...} dict."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        with patch(
            "knowledge_lake.pipeline.quality_audit.run_full_pipeline_audit",
            return_value=_FULL_RESULT,
        ):
            result = runner.invoke(
                app, ["quality-audit", "--domain", "healthcare", "--full", "--json"]
            )

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. Output: {result.output!r}"
        )
        parsed = json.loads(result.output)
        assert parsed == _FULL_RESULT
        assert "rows" in parsed
        assert "summary" in parsed

    def test_full_empty_rows_prints_no_sources_message(self) -> None:
        """`--full` with zero rows prints the same 'No sources found ...' message."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        with patch(
            "knowledge_lake.pipeline.quality_audit.run_full_pipeline_audit",
            return_value=_FULL_RESULT_EMPTY,
        ):
            result = runner.invoke(
                app, ["quality-audit", "--domain", "nonexistent", "--full"]
            )

        assert result.exit_code == 0, (
            f"Expected exit 0 for an empty (not error) result, got {result.exit_code}. "
            f"Output: {result.output!r}"
        )
        output = _strip_ansi(result.output)
        assert "No sources found" in output
        assert "nonexistent" in output
