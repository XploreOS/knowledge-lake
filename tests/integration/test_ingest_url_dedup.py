"""Integration tests for URL ingest with dedup (02-01 Task 3).

Verifies:
    - Ingesting an https URL records SHA256, MIME type, URL, timestamp, and license.
    - Re-ingesting same URL returns identical IDs (URL-first dedup).
"""

from __future__ import annotations

import hashlib
from unittest.mock import patch, MagicMock

import pytest

from knowledge_lake.registry.models import Base, Source, Artifact
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


class TestIngestUrlDedup:
    """Tests for URL ingest with provenance and dedup."""

    def test_ingest_url_records_provenance(self, _test_env):
        """ingest_url records SHA256, MIME, URL, timestamp, and license."""
        from knowledge_lake.pipeline.ingest import ingest_url

        engine, mock_session = _test_env

        fake_body = b"<html><body>Test health document content</body></html>"
        fake_hash = hashlib.sha256(fake_body).hexdigest()

        def fake_getaddrinfo(host, port, *args, **kwargs):
            return [(2, 1, 6, "", ("93.184.216.34", 443))]

        def mock_fetch(url):
            return fake_body, "text/html"

        mock_settings = MagicMock()
        mock_settings.storage = MagicMock()

        with (
            patch("socket.getaddrinfo", side_effect=fake_getaddrinfo),
            patch("knowledge_lake.pipeline.ingest._fetch_with_retry", side_effect=mock_fetch),
            patch("knowledge_lake.pipeline.ingest.get_session", mock_session),
            patch("knowledge_lake.pipeline.ingest.StorageBackend") as MockStorage,
        ):
            def mock_put_raw(source_id, data, ext, session, mime_type=None):
                content_hash = hashlib.sha256(data).hexdigest()
                existing = registry_repo.get_artifact_by_hash(
                    session, content_hash, "raw_document"
                )
                if existing:
                    return existing
                return registry_repo.create_raw_artifact(
                    session,
                    source_id=source_id,
                    content_hash=content_hash,
                    storage_uri=f"s3://klake-test/raw/{source_id}/{content_hash}.html",
                    mime_type="text/html",
                )

            MockStorage.return_value.put_raw.side_effect = mock_put_raw

            result = ingest_url(
                "https://www.example.com/health-doc.html",
                "Health Document",
                license_type="CC-BY-4.0",
                settings=mock_settings,
            )

        # Verify provenance
        assert result["content_hash"] == fake_hash
        assert result["mime_type"] == "text/html"
        assert result["source_id"].startswith("src_")
        assert result["artifact_id"].startswith("doc_")
        assert "s3://" in result["storage_uri"]

        # Verify source row has URL and license
        from sqlalchemy.orm import Session as SA_Session

        with SA_Session(engine) as session:
            source = session.get(Source, result["source_id"])
            assert source is not None
            assert source.url == "https://www.example.com/health-doc.html"
            assert source.normalized_url == "https://www.example.com/health-doc.html"
            assert source.license_type == "CC-BY-4.0"
            assert source.created_at is not None

    def test_ingest_url_dedup_skips_fetch(self, _test_env):
        """Re-ingesting same URL skips fetch and returns existing IDs."""
        from knowledge_lake.pipeline.ingest import ingest_url

        engine, mock_session = _test_env

        fake_body = b"document bytes"
        fetch_count = [0]

        def fake_getaddrinfo(host, port, *args, **kwargs):
            return [(2, 1, 6, "", ("93.184.216.34", 443))]

        def mock_fetch(url):
            fetch_count[0] += 1
            return fake_body, "application/pdf"

        mock_settings = MagicMock()
        mock_settings.storage = MagicMock()

        with (
            patch("socket.getaddrinfo", side_effect=fake_getaddrinfo),
            patch("knowledge_lake.pipeline.ingest._fetch_with_retry", side_effect=mock_fetch),
            patch("knowledge_lake.pipeline.ingest.get_session", mock_session),
            patch("knowledge_lake.pipeline.ingest.StorageBackend") as MockStorage,
        ):
            def mock_put_raw(source_id, data, ext, session, mime_type=None):
                content_hash = hashlib.sha256(data).hexdigest()
                existing = registry_repo.get_artifact_by_hash(
                    session, content_hash, "raw_document"
                )
                if existing:
                    return existing
                return registry_repo.create_raw_artifact(
                    session,
                    source_id=source_id,
                    content_hash=content_hash,
                    storage_uri=f"s3://klake-test/raw/{source_id}/{content_hash}.pdf",
                    mime_type="application/pdf",
                )

            MockStorage.return_value.put_raw.side_effect = mock_put_raw

            result1 = ingest_url(
                "https://example.com/guidelines.pdf",
                "Guidelines",
                settings=mock_settings,
            )
            result2 = ingest_url(
                "https://example.com/guidelines.pdf",
                "Guidelines Again",
                settings=mock_settings,
            )

        # Same IDs
        assert result1["source_id"] == result2["source_id"]
        assert result1["artifact_id"] == result2["artifact_id"]

        # Fetch only called once (second was a dedup hit)
        assert fetch_count[0] == 1
