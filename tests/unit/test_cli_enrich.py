"""Unit tests for `klake enrich` CLI command's exit-code behavior (24-05,
closing 24-VERIFICATION.md gap #8).

Follows tests/unit/test_cli_tree_index.py's engine/_patch_engine/session
fixture pattern (in-memory SQLite via registry_db.get_engine monkeypatch)
plus tests/unit/test_enrich.py's `seeded` Source -> raw -> parsed -> cleaned
artifact chain shape, so cmd_enrich's own internal get_session()/
registry_repo.get_artifact() lookups resolve against real seeded rows.

enrich_document is patched at its SOURCE module
(knowledge_lake.pipeline.enrich.enrich_document) because cmd_enrich imports
it via a function-local import — mirrors tests/unit/test_cli_quality_audit.py's
"patch the source module" convention.
"""

from __future__ import annotations

from unittest.mock import patch

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


# ── Fixtures (mirrors tests/unit/test_enrich.py's `seeded`) ──────────────────


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
    """Seed a Source -> raw -> parsed -> cleaned_document artifact chain."""
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
        content_hash="parsed_h",
        storage_uri="s3://b/silver/parsed_h.md",
    )
    cleaned = registry_repo.create_cleaned_artifact(
        session,
        source_id=source.id,
        parent_artifact_id=parsed.id,
        content_hash="cleaned_h",
        storage_uri="s3://b/silver/cleaned_h.md",
    )
    session.commit()
    return {"source_id": source.id, "cleaned_artifact_id": cleaned.id}


class TestCliEnrichExitCode:
    """`klake enrich <cleaned_artifact_id> <source_id>` exit-code behavior
    (24-VERIFICATION.md gap #8)."""

    def test_skipped_enrichment_failed_exits_1(self, session, seeded) -> None:
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        canned = {"status": "skipped_enrichment_failed", "artifact_id": None, "cached": False}
        with patch("knowledge_lake.pipeline.enrich.enrich_document", return_value=canned):
            result = runner.invoke(
                app, ["enrich", seeded["cleaned_artifact_id"], seeded["source_id"]]
            )

        assert result.exit_code == 1, result.output
        assert "skipped_enrichment_failed" in result.output

    def test_skipped_budget_exceeded_exits_1(self, session, seeded) -> None:
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        canned = {"status": "skipped_budget_exceeded", "artifact_id": None, "cached": False}
        with patch("knowledge_lake.pipeline.enrich.enrich_document", return_value=canned):
            result = runner.invoke(
                app, ["enrich", seeded["cleaned_artifact_id"], seeded["source_id"]]
            )

        assert result.exit_code == 1, result.output
        assert "skipped_budget_exceeded" in result.output

    def test_enriched_status_exits_0(self, session, seeded) -> None:
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        canned = {
            "status": "enriched",
            "artifact_id": "art_x",
            "quality_score": 0.9,
            "cached": False,
        }
        with patch("knowledge_lake.pipeline.enrich.enrich_document", return_value=canned):
            result = runner.invoke(
                app, ["enrich", seeded["cleaned_artifact_id"], seeded["source_id"]]
            )

        assert result.exit_code == 0, result.output
        assert "enriched" in result.output

    def test_cached_status_exits_0(self, session, seeded) -> None:
        """A cache hit is a success, not a failure — must still exit 0."""
        assert _IMPORT_OK, "CliRunner or app import failed"
        assert runner is not None

        canned = {
            "status": "cached",
            "artifact_id": "art_x",
            "quality_score": 0.9,
            "cached": True,
        }
        with patch("knowledge_lake.pipeline.enrich.enrich_document", return_value=canned):
            result = runner.invoke(
                app, ["enrich", seeded["cleaned_artifact_id"], seeded["source_id"]]
            )

        assert result.exit_code == 0, result.output
        assert "cached" in result.output
