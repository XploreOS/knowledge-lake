"""Unit tests for `klake tree-index` CLI command (KL-09).

`klake tree-search` shipped with no producer on the CLI path — the only way
to build a tree index was previously the Dagster `tree_index_document` asset,
and the registry held zero tree_index artifacts as a result. This adds the
missing `klake tree-index` command.

Pattern mirrors tests/unit/test_tree_search.py: in-memory SQLite engine via
StaticPool with registry.db.get_engine monkeypatched, StorageBackend and the
parser-fallback chain mocked — no real S3, LLM, or Docling in this suite.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.registry.db as registry_db

try:
    from typer.testing import CliRunner

    from knowledge_lake.cli.app import app
    _IMPORT_OK = True
except ImportError:
    CliRunner = None  # type: ignore[assignment, misc]
    app = None  # type: ignore[assignment]
    _IMPORT_OK = False

runner = CliRunner() if CliRunner is not None else None


# ── Fixtures (mirrors test_tree_search.py) ───────────────────────────────────


@pytest.fixture()
def engine():
    from knowledge_lake.registry.models import Base

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _patch_engine(monkeypatch, engine):
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)


@pytest.fixture()
def session(engine):
    with Session(engine) as sess:
        yield sess


@pytest.fixture()
def seeded(session):
    """Seed a Source -> raw -> parsed artifact chain, mirroring the parent
    relationship cmd_tree_index resolves (parsed_document.parent_artifact_id
    -> raw_document)."""
    from knowledge_lake.registry import repo as registry_repo

    source = registry_repo.create_source(session, name="Test Source", source_type="web")
    raw = registry_repo.create_raw_artifact(
        session,
        source_id=source.id,
        content_hash="raw_h",
        storage_uri="s3://b/raw/raw_h.pdf",
    )
    parsed = registry_repo.create_parsed_artifact(
        session,
        source_id=source.id,
        parent_artifact_id=raw.id,
        content_hash="abc123",
        storage_uri="s3://b/silver/abc123.md",
    )
    session.commit()
    return {
        "source_id": source.id,
        "raw_artifact_id": raw.id,
        "parsed_artifact_id": parsed.id,
    }


class TestCliTreeIndex:
    """`klake tree-index <parsed_artifact_id> <source_id>` (KL-09)."""

    def test_help_lists_arguments(self) -> None:
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        result = runner.invoke(app, ["tree-index", "--help"])
        assert result.exit_code == 0, result.output
        assert "PARSED_ARTIFACT_ID" in result.output
        assert "SOURCE_ID" in result.output

    def test_unknown_parsed_artifact_exits_1(self, session) -> None:
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        result = runner.invoke(app, ["tree-index", "doc_unknown", "src_unknown"])
        assert result.exit_code == 1, result.output
        assert "not found in registry" in result.output

    def test_reparse_recovers_sections_and_calls_tree_index(self, session, seeded) -> None:
        """klake tree-index falls back to re-parsing the raw parent via the
        parser-fallback chain when the parsed artifact has no sections sidecar
        (Task 8: the `seeded` fixture creates a parsed_document with no
        metadata_["sections_uri"], simulating an artifact parsed before that
        feature existed). Hands tree_index() a ParsedDoc WITH sections — the
        cmd_chunk shortcut (section-less ParsedDoc) does not transfer here
        because _build_deterministic_tree() builds the tree FROM sections.

        Patches pipeline.parse.StorageBackend / .parse_with_fallback (not the
        defining modules) because reparse_from_raw() binds both names at
        pipeline.parse's own module-import time (KL-19 lesson: patch the seam
        actually consulted, not the seam that merely defines the symbol)."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        from knowledge_lake.plugins.protocols import ParsedDoc, Section

        fake_parsed_doc = ParsedDoc(
            text="full re-parsed text",
            sections=[
                Section(heading="Intro", section_path="§1", page=1),
                Section(heading="Details", section_path="§1.1", page=2),
            ],
        )

        mock_storage = MagicMock()
        mock_storage.get_object.return_value = b"%PDF-1.4 fake raw bytes"

        captured: dict = {}

        def tree_index_stub(parsed_artifact_id, source_id, parsed_doc, **kwargs):
            captured["parsed_artifact_id"] = parsed_artifact_id
            captured["source_id"] = source_id
            captured["parsed_doc"] = parsed_doc
            return {"artifact_id": "idx_fake", "cached": False, "status": "tree_indexed"}

        with (
            patch("knowledge_lake.pipeline.parse.StorageBackend", return_value=mock_storage),
            patch(
                "knowledge_lake.pipeline.parse.parse_with_fallback",
                return_value=(fake_parsed_doc, "docling", 0.9),
            ) as mock_parse,
            patch(
                "knowledge_lake.pipeline.tree_index.tree_index",
                side_effect=tree_index_stub,
            ) as mock_tree_index,
        ):
            result = runner.invoke(
                app,
                ["tree-index", seeded["parsed_artifact_id"], seeded["source_id"]],
            )

        assert result.exit_code == 0, result.output
        assert mock_parse.call_count == 1, (
            "Must re-parse the raw parent via the same parser-fallback chain "
            "klake parse uses (KL-09) when no sections sidecar exists"
        )
        assert mock_tree_index.call_count == 1
        assert captured["parsed_artifact_id"] == seeded["parsed_artifact_id"]
        assert captured["source_id"] == seeded["source_id"]
        assert captured["parsed_doc"].sections, (
            "tree_index() must receive a ParsedDoc WITH sections — a "
            "section-less ParsedDoc (cmd_chunk's old shortcut) would yield a "
            "single degenerate root node instead of a real tree (KL-09)"
        )
        assert "tree_indexed" in result.output
        assert "idx_fake" in result.output

    def test_sidecar_hit_skips_reparse(self, session, seeded) -> None:
        """When the parsed artifact HAS a sections sidecar (Task 8), tree-index
        rehydrates it instead of re-parsing the raw document."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        from knowledge_lake.registry import repo as registry_repo

        # Give the seeded parsed artifact a sections_uri, simulating a parse()
        # call made after Task 8.
        artifact = registry_repo.get_artifact(session, seeded["parsed_artifact_id"])
        artifact.metadata_ = {
            "quality_score": 0.9,
            "parser_used": "docling",
            "title": "Test",
            "sections_uri": "s3://b/silver/abc123.sections.json",
        }
        session.commit()

        import orjson

        sidecar_bytes = orjson.dumps({
            "text": "sidecar text",
            "sections": [
                {"heading": "Intro", "section_path": "§1", "page": 1, "text": "", "is_table": False},
            ],
            "metadata": {},
        })
        mock_storage = MagicMock()
        mock_storage.get_object.return_value = sidecar_bytes

        captured: dict = {}

        def tree_index_stub(parsed_artifact_id, source_id, parsed_doc, **kwargs):
            captured["parsed_doc"] = parsed_doc
            return {"artifact_id": "idx_fake", "cached": False, "status": "tree_indexed"}

        with (
            patch("knowledge_lake.pipeline.parse.StorageBackend", return_value=mock_storage),
            patch(
                "knowledge_lake.pipeline.parse.parse_with_fallback",
            ) as mock_parse,
            patch(
                "knowledge_lake.pipeline.tree_index.tree_index",
                side_effect=tree_index_stub,
            ) as mock_tree_index,
        ):
            result = runner.invoke(
                app,
                ["tree-index", seeded["parsed_artifact_id"], seeded["source_id"]],
            )

        assert result.exit_code == 0, result.output
        assert mock_parse.call_count == 0, "Must NOT re-parse when a sidecar exists"
        assert mock_tree_index.call_count == 1
        assert captured["parsed_doc"].sections
        assert "no re-parse needed" in result.output


class TestCliTreeSearchEmptyResultDiagnosis:
    """klake tree-search distinguishes "no tree index" from "no matches" (KL-09)."""

    def test_no_tree_index_message_when_shortlisted_but_uncovered(self) -> None:
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        with (
            patch("knowledge_lake.pipeline.tree_search.tree_search", return_value=[]),
            patch(
                "knowledge_lake.pipeline.tree_search.tree_index_coverage",
                return_value={"shortlisted": 2, "has_any_index": False},
            ),
        ):
            result = runner.invoke(app, ["tree-search", "some query"])

        assert result.exit_code == 0, result.output
        assert "No tree index has been built yet" in result.output
        assert "klake tree-index" in result.output
        assert "No results for query" not in result.output

    def test_plain_no_results_when_index_exists_but_no_matches(self) -> None:
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        with (
            patch("knowledge_lake.pipeline.tree_search.tree_search", return_value=[]),
            patch(
                "knowledge_lake.pipeline.tree_search.tree_index_coverage",
                return_value={"shortlisted": 1, "has_any_index": True},
            ),
        ):
            result = runner.invoke(app, ["tree-search", "some query"])

        assert result.exit_code == 0, result.output
        assert "No results for query" in result.output
        assert "No tree index has been built yet" not in result.output

    def test_plain_no_results_when_nothing_shortlisted(self) -> None:
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        with (
            patch("knowledge_lake.pipeline.tree_search.tree_search", return_value=[]),
            patch(
                "knowledge_lake.pipeline.tree_search.tree_index_coverage",
                return_value={"shortlisted": 0, "has_any_index": False},
            ),
        ):
            result = runner.invoke(app, ["tree-search", "some query"])

        assert result.exit_code == 0, result.output
        assert "No results for query" in result.output
        assert "No tree index has been built yet" not in result.output
