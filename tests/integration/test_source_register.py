"""Integration tests for source registration (02-01 Task 3).

Verifies:
    - A source row is created with name, source_type, url, normalized_url,
      license_type, and created_at populated.
    - register_source with URL-first dedup returns existing source on repeat.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from knowledge_lake.registry.models import Base, Source
from knowledge_lake.registry import repo as registry_repo


@pytest.fixture
def _test_env():
    """Set up test environment with SQLite in-memory DB."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from contextlib import contextmanager

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    @contextmanager
    def mock_session():
        with Session(engine) as session:
            yield session
            session.commit()

    return engine, mock_session


class TestSourceRegister:
    """Tests for source registration via register_source pipeline function."""

    def test_register_creates_source_with_provenance(self, _test_env):
        """register_source creates a source row with all provenance columns populated."""
        from knowledge_lake.pipeline.ingest import register_source

        engine, mock_session = _test_env

        with patch("knowledge_lake.pipeline.ingest.get_session", mock_session):
            result = register_source(
                url="https://www.example.com/health-guidelines.pdf",
                name="Health Guidelines",
                domain="healthcare",
                license_type="CC-BY-4.0",
            )

        assert result["is_new"] is True
        assert result["source_id"].startswith("src_")
        assert result["name"] == "Health Guidelines"
        assert result["url"] == "https://www.example.com/health-guidelines.pdf"
        assert result["normalized_url"] == "https://www.example.com/health-guidelines.pdf"
        assert result["domain"] == "healthcare"

        # Verify the DB row
        from sqlalchemy.orm import Session as SA_Session

        with SA_Session(engine) as session:
            source = session.get(Source, result["source_id"])
            assert source is not None
            assert source.name == "Health Guidelines"
            assert source.source_type == "web"
            assert source.url == "https://www.example.com/health-guidelines.pdf"
            assert source.normalized_url == "https://www.example.com/health-guidelines.pdf"
            assert source.license_type == "CC-BY-4.0"
            assert source.created_at is not None
            assert source.config == {"domain": "healthcare"}

    def test_register_dedup_returns_existing(self, _test_env):
        """register_source on same normalized URL returns existing source."""
        from knowledge_lake.pipeline.ingest import register_source

        engine, mock_session = _test_env

        with patch("knowledge_lake.pipeline.ingest.get_session", mock_session):
            result1 = register_source(
                url="HTTPS://Example.COM/doc/",
                name="First Registration",
            )
            result2 = register_source(
                url="https://example.com/doc",
                name="Second Registration",
            )

        assert result1["source_id"] == result2["source_id"]
        assert result2["is_new"] is False
        # Original name preserved
        assert result2["name"] == "First Registration"
