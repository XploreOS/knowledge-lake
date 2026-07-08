"""Integration tests for URL-first and hash-second dedup (02-01 Task 2).

Verifies:
    - Two ingest_url(same_url) calls return identical source_id AND artifact_id;
      sources table has exactly one row for that normalized_url.
    - Two ingest_file(identical bytes) calls return the identical raw artifact_id
      with no second raw_document artifact created (hash-second, D-07).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from knowledge_lake.registry.models import Base, Source, Artifact
from knowledge_lake.registry import repo as registry_repo


@pytest.fixture
def _test_env():
    """Set up test environment with SQLite in-memory DB."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    # Patch get_session to use our test DB
    from contextlib import contextmanager

    @contextmanager
    def mock_session():
        with Session(engine) as session:
            yield session
            session.commit()

    return engine, mock_session


class TestUrlFirstDedup:
    """URL-first dedup: two ingest_url(same_url) → identical IDs, one source row."""

    def test_ingest_url_dedup_returns_same_ids(self, _test_env):
        """Two ingest_url(same URL) calls return identical source_id + artifact_id."""
        from knowledge_lake.pipeline.ingest import ingest_url

        engine, mock_session = _test_env

        # Mock dependencies
        fake_body = b"test document content for dedup"

        def fake_getaddrinfo(host, port, *args, **kwargs):
            return [(2, 1, 6, "", ("93.184.216.34", 443))]

        mock_settings = MagicMock()
        mock_settings.storage = MagicMock()

        def mock_fetch(url):
            return fake_body, "application/pdf"

        with (
            patch("socket.getaddrinfo", side_effect=fake_getaddrinfo),
            patch("knowledge_lake.pipeline.ingest._fetch_with_retry", side_effect=mock_fetch),
            patch("knowledge_lake.pipeline.ingest.get_session", mock_session),
            patch("knowledge_lake.pipeline.ingest.StorageBackend") as MockStorage,
        ):
            # Mock storage.put_raw to create artifact in our test DB
            def mock_put_raw(source_id, data, ext, session, mime_type=None):
                content_hash = hashlib.sha256(data).hexdigest()
                # Check existing first (like real put_raw)
                existing = registry_repo.get_artifact_by_hash(
                    session, content_hash, "raw_document"
                )
                if existing:
                    return existing
                return registry_repo.create_raw_artifact(
                    session,
                    source_id=source_id,
                    content_hash=content_hash,
                    storage_uri=f"s3://test/{source_id}/{content_hash}.pdf",
                    mime_type="application/pdf",
                )

            mock_storage_instance = MockStorage.return_value
            mock_storage_instance.put_raw.side_effect = mock_put_raw

            result1 = ingest_url(
                "https://example.com/doc.pdf",
                "Test Source",
                settings=mock_settings,
            )
            result2 = ingest_url(
                "https://example.com/doc.pdf",
                "Test Source",
                settings=mock_settings,
            )

        # Same source_id and artifact_id
        assert result1["source_id"] == result2["source_id"]
        assert result1["artifact_id"] == result2["artifact_id"]

        # Only one source row for this normalized_url
        from sqlalchemy.orm import Session as SA_Session
        from sqlalchemy import select, func

        with SA_Session(engine) as session:
            from knowledge_lake.pipeline.ingest import normalize_url

            norm_url = normalize_url("https://example.com/doc.pdf")
            count = session.execute(
                select(func.count())
                .select_from(Source)
                .where(Source.normalized_url == norm_url)
            ).scalar()
            assert count == 1

    def test_ingest_file_hash_dedup(self, _test_env):
        """Two ingest_file(same bytes) calls return same artifact_id — hash-second dedup."""
        from knowledge_lake.pipeline.ingest import ingest_file

        engine, mock_session = _test_env

        # Create a temp file with known content
        content = b"identical content for hash dedup test"
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(content)
            tmp_path = f.name

        mock_settings = MagicMock()
        mock_settings.storage = MagicMock()

        try:
            with (
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
                        storage_uri=f"s3://test/{source_id}/{content_hash}.pdf",
                        mime_type="application/pdf",
                    )

                mock_storage_instance = MockStorage.return_value
                mock_storage_instance.put_raw.side_effect = mock_put_raw

                result1 = ingest_file(
                    tmp_path, "Upload Source 1", settings=mock_settings
                )
                result2 = ingest_file(
                    tmp_path, "Upload Source 2", settings=mock_settings
                )

            # Same artifact_id (hash-based dedup)
            assert result1["artifact_id"] == result2["artifact_id"]

            # Verify only one raw_document artifact
            from sqlalchemy.orm import Session as SA_Session
            from sqlalchemy import select, func

            content_hash = hashlib.sha256(content).hexdigest()
            with SA_Session(engine) as session:
                count = session.execute(
                    select(func.count())
                    .select_from(Artifact)
                    .where(Artifact.content_hash == content_hash)
                    .where(Artifact.artifact_type == "raw_document")
                ).scalar()
                assert count == 1
        finally:
            os.unlink(tmp_path)
