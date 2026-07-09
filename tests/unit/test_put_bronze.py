"""
Unit tests for StorageBackend.put_bronze (D-01, INGEST-04).

Tests verify:
  - Bronze write creates an artifact with type 'bronze_document'
  - The bronze artifact has parent_artifact_id linking to the raw artifact
  - Repeated put_bronze of identical bytes is a registry no-op (returns same artifact)
  - Bronze key uses the bronze/ zone prefix

Uses an in-memory SQLite database with a mocked S3 client (no live MinIO needed).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture(scope="module")
def engine():
    """In-memory SQLite engine with all tables created via ORM."""
    from knowledge_lake.registry.models import Base

    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    """Fresh session per test; rolls back on teardown."""
    with Session(engine) as sess:
        yield sess
        sess.rollback()


@pytest.fixture()
def mock_storage():
    """StorageBackend with a mocked S3 client."""
    from knowledge_lake.config.settings import StorageSettings
    from knowledge_lake.storage.s3 import StorageBackend

    storage_settings = StorageSettings(
        endpoint_url="http://minio-test:9000",
        bucket="test-bucket",
        access_key_id="test",
        secret_access_key="test",
    )

    with patch("boto3.client") as mock_boto:
        mock_client = MagicMock()
        mock_boto.return_value = mock_client
        # head_object raises 404 by default (key doesn't exist)
        from botocore.exceptions import ClientError

        mock_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )
        backend = StorageBackend(storage_settings)
        yield backend, mock_client


@pytest.fixture()
def source_and_raw(session):
    """Create a source and a raw artifact for bronze lineage testing."""
    from knowledge_lake.registry.repo import create_raw_artifact, create_source

    source = create_source(session, name="Test Source", source_type="web")
    raw = create_raw_artifact(
        session,
        source_id=source.id,
        content_hash="raw_hash_abc123",
        storage_uri="s3://test-bucket/raw/src_x/raw_hash_abc123.pdf",
    )
    session.flush()
    return source, raw


class TestPutBronzeBasic:
    """put_bronze creates a bronze artifact with correct type and parent."""

    def test_bronze_artifact_type(self, session, mock_storage, source_and_raw):
        """Bronze artifact has artifact_type == 'bronze_document'."""
        backend, _ = mock_storage
        source, raw = source_and_raw

        data = b"# Hello World\n\nThis is markdown content."
        artifact = backend.put_bronze(
            source.id, data, "md", session, parent_artifact_id=raw.id
        )

        assert artifact.artifact_type == "bronze_document"

    def test_bronze_parent_is_raw(self, session, mock_storage, source_and_raw):
        """Bronze artifact has parent_artifact_id pointing to the raw artifact."""
        backend, _ = mock_storage
        source, raw = source_and_raw

        data = b"# Bronze content with lineage"
        artifact = backend.put_bronze(
            source.id, data, "md", session, parent_artifact_id=raw.id
        )

        assert artifact.parent_artifact_id == raw.id

    def test_bronze_id_prefixed(self, session, mock_storage, source_and_raw):
        """Bronze artifact ID starts with 'doc_' (bronze_document uses 'doc' prefix)."""
        backend, _ = mock_storage
        source, raw = source_and_raw

        data = b"# Bronze doc prefix test"
        artifact = backend.put_bronze(
            source.id, data, "md", session, parent_artifact_id=raw.id
        )

        assert artifact.id.startswith("doc_"), f"Expected doc_ prefix: {artifact.id}"

    def test_bronze_storage_uri(self, session, mock_storage, source_and_raw):
        """Bronze artifact storage_uri uses the bronze/ zone prefix."""
        backend, _ = mock_storage
        source, raw = source_and_raw

        data = b"# Storage URI test"
        artifact = backend.put_bronze(
            source.id, data, "md", session, parent_artifact_id=raw.id
        )

        assert artifact.storage_uri is not None
        assert "bronze/" in artifact.storage_uri


class TestPutBronzeNoop:
    """put_bronze no-ops on repeated identical content (hash-second dedup)."""

    def test_repeat_returns_same_artifact(self, session, mock_storage, source_and_raw):
        """Re-processing identical bytes returns the same artifact (no new S3 write)."""
        backend, mock_client = mock_storage
        source, raw = source_and_raw

        data = b"# Identical content for dedup test"

        # First write
        art1 = backend.put_bronze(
            source.id, data, "md", session, parent_artifact_id=raw.id
        )
        session.flush()

        # Second write of identical data — should hit the registry no-op
        art2 = backend.put_bronze(
            source.id, data, "md", session, parent_artifact_id=raw.id
        )

        assert art2.id == art1.id, "Repeat put_bronze should return the same artifact"

    def test_noop_skips_s3_write(self, session, mock_storage, source_and_raw):
        """No-op path does not issue a put_object call to S3."""
        backend, mock_client = mock_storage
        source, raw = source_and_raw

        data = b"# No-op S3 skip test"

        # First write
        backend.put_bronze(
            source.id, data, "md", session, parent_artifact_id=raw.id
        )
        session.flush()
        initial_put_count = mock_client.put_object.call_count

        # Second write — no-op
        backend.put_bronze(
            source.id, data, "md", session, parent_artifact_id=raw.id
        )

        assert mock_client.put_object.call_count == initial_put_count, (
            "No-op should not call put_object"
        )


class TestPutBronzeDomainKey:
    """put_bronze with domain kwarg produces domain-scoped S3 keys (STORE-01)."""

    def test_domain_segment_in_bronze_key(self, mock_storage, source_and_raw, session):
        """put_bronze(domain='healthcare') produces key starting with 'bronze/healthcare/'."""
        import hashlib

        backend, mock_client = mock_storage
        source, raw = source_and_raw
        bronze_data = b"bronze content data"
        expected_hash = hashlib.sha256(bronze_data).hexdigest()

        backend.put_bronze(
            source.id, bronze_data, "md", session,
            parent_artifact_id=raw.id,
            domain="healthcare",
        )
        assert mock_client.put_object.called
        call_kwargs = mock_client.put_object.call_args[1]
        key = call_kwargs["Key"]
        assert key.startswith("bronze/healthcare/"), (
            f"Expected key to start with 'bronze/healthcare/', got: {key!r}"
        )
        assert key.endswith(f"{expected_hash}.md"), (
            f"Expected key to end with '{expected_hash}.md', got: {key!r}"
        )

    def test_none_domain_uses_unclassified_segment(self, mock_storage, source_and_raw, session):
        """put_bronze(domain=None) produces key starting with 'bronze/_unclassified/'."""
        backend, mock_client = mock_storage
        source, raw = source_and_raw
        bronze_data = b"bronze content data unclassified"

        backend.put_bronze(
            source.id, bronze_data, "md", session,
            parent_artifact_id=raw.id,
            domain=None,
        )
        assert mock_client.put_object.called
        call_kwargs = mock_client.put_object.call_args[1]
        key = call_kwargs["Key"]
        assert key.startswith("bronze/_unclassified/"), (
            f"Expected key to start with 'bronze/_unclassified/', got: {key!r}"
        )
