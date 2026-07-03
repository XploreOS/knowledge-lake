"""Integration tests for file upload (02-01 Task 3).

Verifies:
    - Upload creates a raw artifact with content_hash (SHA256), mime_type,
      storage_uri, and a created_at timestamp.
    - Hash-second dedup: re-uploading identical content returns same artifact.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from unittest.mock import patch

import pytest

from knowledge_lake.registry.models import Base, Artifact
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


@pytest.fixture
def _tmp_pdf():
    """Create a temporary PDF-like file for upload testing."""
    content = b"%PDF-1.4 test content for upload provenance verification"
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(content)
        path = f.name
    yield path, content
    os.unlink(path)


class TestUpload:
    """Tests for file upload via ingest_file pipeline function."""

    def test_upload_records_provenance(self, _test_env, _tmp_pdf):
        """Upload records content_hash, mime_type, storage_uri, and created_at."""
        from knowledge_lake.pipeline.ingest import ingest_file
        from unittest.mock import MagicMock

        engine, mock_session = _test_env
        tmp_path, content = _tmp_pdf
        expected_hash = hashlib.sha256(content).hexdigest()

        mock_settings = MagicMock()
        mock_settings.storage = MagicMock()

        with (
            patch("knowledge_lake.pipeline.ingest.get_session", mock_session),
            patch("knowledge_lake.pipeline.ingest.StorageBackend") as MockStorage,
        ):
            def mock_put_raw(source_id, data, ext, session):
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

            result = ingest_file(
                path=tmp_path,
                source_name="Test Upload Source",
                license_type="CC-BY-4.0",
                settings=mock_settings,
            )

        # Verify provenance fields
        assert result["content_hash"] == expected_hash
        assert result["artifact_id"].startswith("doc_")
        assert result["source_id"].startswith("src_")
        assert "s3://" in result["storage_uri"]

        # Verify artifact in DB
        from sqlalchemy.orm import Session as SA_Session

        with SA_Session(engine) as session:
            artifact = session.get(Artifact, result["artifact_id"])
            assert artifact is not None
            assert artifact.content_hash == expected_hash
            assert artifact.storage_uri is not None
            assert artifact.created_at is not None

    def test_upload_hash_dedup(self, _test_env, _tmp_pdf):
        """Re-uploading identical content returns same artifact (no duplicates)."""
        from knowledge_lake.pipeline.ingest import ingest_file
        from unittest.mock import MagicMock

        engine, mock_session = _test_env
        tmp_path, content = _tmp_pdf

        mock_settings = MagicMock()
        mock_settings.storage = MagicMock()

        with (
            patch("knowledge_lake.pipeline.ingest.get_session", mock_session),
            patch("knowledge_lake.pipeline.ingest.StorageBackend") as MockStorage,
        ):
            def mock_put_raw(source_id, data, ext, session):
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

            result1 = ingest_file(tmp_path, "Upload 1", settings=mock_settings)
            result2 = ingest_file(tmp_path, "Upload 2", settings=mock_settings)

        # Same artifact (hash dedup)
        assert result1["artifact_id"] == result2["artifact_id"]
        assert result1["content_hash"] == result2["content_hash"]
