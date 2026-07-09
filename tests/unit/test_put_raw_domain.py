"""
RED-state tests for StorageBackend.put_raw domain-scoped key construction and
dedup ordering (STORE-01). Tests are xfail(strict=False) until Plan 09-03 adds
the domain kwarg to put_raw.
"""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

SAMPLE_DATA = b"test raw content for domain key testing"
SAMPLE_EXT = "pdf"
SAMPLE_HASH = hashlib.sha256(SAMPLE_DATA).hexdigest()


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
        mock_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )
        backend = StorageBackend(storage_settings)
        yield backend, mock_client


@pytest.fixture()
def source(session):
    """Create a source for raw domain key testing."""
    from knowledge_lake.registry import repo as registry_repo

    src = registry_repo.create_source(session, name="test-domain-source", source_type="upload")
    session.flush()
    return src


class TestPutRawDomainKey:
    """put_raw with domain kwarg produces domain-scoped S3 keys (STORE-01)."""

    @pytest.mark.xfail(strict=False, reason="STORE-01: put_raw domain kwarg pending Plan 09-03")
    def test_domain_segment_in_raw_key(self, mock_storage, source, session):
        """put_raw(domain='healthcare') produces key starting with 'raw/healthcare/'."""
        backend, mock_client = mock_storage
        backend.put_raw(source.id, SAMPLE_DATA, SAMPLE_EXT, session, domain="healthcare")
        assert mock_client.put_object.called
        call_kwargs = mock_client.put_object.call_args[1]
        key = call_kwargs["Key"]
        assert key.startswith("raw/healthcare/"), (
            f"Expected key to start with 'raw/healthcare/', got: {key!r}"
        )
        assert key.endswith(f"{SAMPLE_HASH}.{SAMPLE_EXT}"), (
            f"Expected key to end with '{SAMPLE_HASH}.{SAMPLE_EXT}', got: {key!r}"
        )

    @pytest.mark.xfail(strict=False, reason="STORE-01: put_raw domain kwarg pending Plan 09-03")
    def test_none_domain_uses_unclassified_segment(self, mock_storage, source, session):
        """put_raw(domain=None) produces key starting with 'raw/_unclassified/'."""
        backend, mock_client = mock_storage
        backend.put_raw(source.id, SAMPLE_DATA, SAMPLE_EXT, session, domain=None)
        assert mock_client.put_object.called
        call_kwargs = mock_client.put_object.call_args[1]
        key = call_kwargs["Key"]
        assert key.startswith("raw/_unclassified/"), (
            f"Expected key to start with 'raw/_unclassified/', got: {key!r}"
        )
        assert key.endswith(f"{SAMPLE_HASH}.{SAMPLE_EXT}"), (
            f"Expected key to end with '{SAMPLE_HASH}.{SAMPLE_EXT}', got: {key!r}"
        )


class TestDeduplicationOrderPreserved:
    """Registry no-op fires before key construction — domain kwarg does not affect dedup (STORE-01)."""

    @pytest.mark.xfail(strict=False, reason="STORE-01: put_raw domain kwarg pending Plan 09-03")
    def test_no_put_object_when_artifact_already_in_registry(
        self, mock_storage, source, session
    ):
        """Seeded artifact causes put_raw to return early; S3 put_object is never called."""
        from knowledge_lake.registry.repo import create_raw_artifact

        storage_uri = (
            f"s3://test-bucket/raw/_unclassified/{source.id}/{SAMPLE_HASH}.{SAMPLE_EXT}"
        )
        create_raw_artifact(
            session,
            source_id=source.id,
            content_hash=SAMPLE_HASH,
            storage_uri=storage_uri,
        )
        session.flush()

        backend, mock_client = mock_storage
        mock_client.put_object.reset_mock()

        backend.put_raw(source.id, SAMPLE_DATA, SAMPLE_EXT, session, domain="healthcare")
        mock_client.put_object.assert_not_called()
