"""Integration tests for source discovery → auto-register pipeline.

Tests:
  - Discovered sources register with source_type='discovered' and URL + title only
  - A private-IP result is SSRF-skipped (not registered)
  - Re-running the same query does not create duplicate source rows (URL-first dedup)
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return re.sub(r'\x1b\[[^m]*m', '', text)

from knowledge_lake.plugins.protocols import DiscoveryResult


# ── Fixtures ────────────────────────────────────────────────────────────────


MOCK_DISCOVERY_RESULTS = [
    DiscoveryResult(url="https://www.hhs.gov/hipaa/security/index.html", title="HIPAA Security"),
    DiscoveryResult(url="https://www.cms.gov/hipaa", title="CMS HIPAA"),
    # Private IP — should be skipped by SSRF validation
    DiscoveryResult(url="https://192.168.1.1/internal", title="Internal Resource"),
]


@pytest.fixture()
def mock_discovery_plugin():
    """Return a mock DiscoveryPlugin that returns MOCK_DISCOVERY_RESULTS."""
    plugin = MagicMock()
    plugin.name = "searxng"
    plugin.search.return_value = MOCK_DISCOVERY_RESULTS
    return plugin


@pytest.fixture()
def db_session(tmp_path):
    """Provide a SQLite-backed registry session for integration testing."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from knowledge_lake.registry.models import Base

    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


class TestDiscoveryRegister:
    """Integration tests for discover_sources pipeline."""

    def test_discovered_sources_registered_with_correct_type(
        self, mock_discovery_plugin, db_session, tmp_path
    ):
        """Discovered sources are registered with source_type='discovered'."""
        from knowledge_lake.pipeline.discover import discover_sources
        from knowledge_lake.registry import repo as registry_repo

        # Mock the resolver to return our plugin
        with (
            patch(
                "knowledge_lake.pipeline.discover.get_discovery",
                return_value=mock_discovery_plugin,
            ),
            patch(
                "knowledge_lake.pipeline.ingest.get_session",
            ) as mock_get_session,
        ):
            mock_get_session.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

            results = discover_sources(query="HIPAA security", limit=10)

        # Should have 3 results total
        assert len(results) == 3

        # Two public URLs should be registered
        registered = [r for r in results if r["status"] == "registered"]
        assert len(registered) == 2

        # Verify they have source_type='discovered' in the DB
        sources = registry_repo.list_sources_by_type(db_session, "discovered")
        assert len(sources) == 2
        for source in sources:
            assert source.source_type == "discovered"

    def test_private_ip_result_skipped(
        self, mock_discovery_plugin, db_session
    ):
        """A result URL resolving to a private IP is skipped (not registered)."""
        from knowledge_lake.pipeline.discover import discover_sources

        with (
            patch(
                "knowledge_lake.pipeline.discover.get_discovery",
                return_value=mock_discovery_plugin,
            ),
            patch(
                "knowledge_lake.pipeline.ingest.get_session",
            ) as mock_get_session,
        ):
            mock_get_session.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

            results = discover_sources(query="test", limit=10)

        skipped = [r for r in results if r["status"] == "skipped_ssrf"]
        assert len(skipped) == 1
        assert "192.168.1.1" in skipped[0]["url"]
        assert skipped[0]["source_id"] is None

    def test_no_duplicate_rows_on_rerun(
        self, mock_discovery_plugin, db_session
    ):
        """Re-running the same query does not create duplicate source rows (URL-first dedup)."""
        from knowledge_lake.pipeline.discover import discover_sources
        from knowledge_lake.registry import repo as registry_repo

        with (
            patch(
                "knowledge_lake.pipeline.discover.get_discovery",
                return_value=mock_discovery_plugin,
            ),
            patch(
                "knowledge_lake.pipeline.ingest.get_session",
            ) as mock_get_session,
        ):
            mock_get_session.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

            # First run
            results_1 = discover_sources(query="HIPAA security", limit=10)
            # Second run — same query
            results_2 = discover_sources(query="HIPAA security", limit=10)

        # First run: 2 registered
        registered_1 = [r for r in results_1 if r["status"] == "registered"]
        assert len(registered_1) == 2

        # Second run: 0 registered, 2 existing (dedup hit)
        registered_2 = [r for r in results_2 if r["status"] == "registered"]
        existing_2 = [r for r in results_2 if r["status"] == "existing"]
        assert len(registered_2) == 0
        assert len(existing_2) == 2

        # Total sources in DB: still just 2
        sources = registry_repo.list_sources_by_type(db_session, "discovered")
        assert len(sources) == 2


class TestDiscoverCLI:
    """Test the klake discover CLI command."""

    def test_help_exits_zero(self):
        """klake discover --help exits 0."""
        from typer.testing import CliRunner

        from knowledge_lake.cli.app import app

        runner = CliRunner()
        result = runner.invoke(app, ["discover", "--help"])
        assert result.exit_code == 0
        assert "--limit" in _strip_ansi(result.output)

    def test_discover_runs_with_mock(self, mock_discovery_plugin, db_session):
        """klake discover with mocked pipeline produces output."""
        from typer.testing import CliRunner

        from knowledge_lake.cli.app import app

        runner = CliRunner()

        with (
            patch(
                "knowledge_lake.pipeline.discover.get_discovery",
                return_value=mock_discovery_plugin,
            ),
            patch(
                "knowledge_lake.pipeline.ingest.get_session",
            ) as mock_get_session,
        ):
            mock_get_session.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

            result = runner.invoke(app, ["discover", "HIPAA"])

        assert result.exit_code == 0
        assert "Discovery:" in result.output


class TestDiscoverAPI:
    """Test the POST /discover API endpoint."""

    def test_discover_in_openapi(self):
        """POST /discover appears in the OpenAPI spec."""
        from fastapi.testclient import TestClient

        from knowledge_lake.api.app import app

        client = TestClient(app)
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()
        assert "/discover" in spec["paths"]
        assert "post" in spec["paths"]["/discover"]

    def test_discover_endpoint_with_mock(self, mock_discovery_plugin, db_session):
        """POST /discover returns results with correct schema."""
        from fastapi.testclient import TestClient

        from knowledge_lake.api.app import app

        client = TestClient(app)

        with (
            patch(
                "knowledge_lake.pipeline.discover.get_discovery",
                return_value=mock_discovery_plugin,
            ),
            patch(
                "knowledge_lake.pipeline.ingest.get_session",
            ) as mock_get_session,
        ):
            mock_get_session.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

            resp = client.post("/discover", json={"query": "HIPAA", "limit": 10})

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "HIPAA"
        assert data["total"] == 3
        assert len(data["results"]) == 3

    def test_discover_validates_empty_query(self):
        """POST /discover rejects empty query."""
        from fastapi.testclient import TestClient

        from knowledge_lake.api.app import app

        client = TestClient(app)
        resp = client.post("/discover", json={"query": "", "limit": 10})
        assert resp.status_code == 422
