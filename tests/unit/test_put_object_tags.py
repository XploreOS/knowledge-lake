"""
Tests for StorageBackend.put_object tags support (STORE-02, D-07, D-08, D-10).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
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
        mock_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )
        backend = StorageBackend(storage_settings)
        yield backend, mock_client


class TestPutObjectTagging:
    """put_object passes Tagging= kwarg when tags dict provided (STORE-02, D-07, D-08)."""

    def test_tags_passed_as_tagging_kwarg(self, mock_storage):
        """put_object with tags= passes URL-encoded Tagging= to boto3 put_object."""
        backend, mock_client = mock_storage
        backend.put_object(
            "raw/_unclassified/src1/hash.pdf",
            b"data",
            tags={"domain": "healthcare", "format": "pdf"},
        )
        assert mock_client.put_object.called
        call_kwargs = mock_client.put_object.call_args[1]
        assert "Tagging" in call_kwargs, (
            f"Expected 'Tagging' in put_object kwargs, got: {list(call_kwargs.keys())}"
        )
        tagging = call_kwargs["Tagging"]
        assert "domain=healthcare" in tagging, (
            f"Expected 'domain=healthcare' in Tagging string, got: {tagging!r}"
        )


class TestTaggingBestEffortFallback:
    """put_object retries without tags on ClientError (STORE-02, D-10)."""

    def test_clienterror_retries_without_tags(self, mock_storage):
        """ClientError on first put_object (with Tagging) triggers a tagless retry."""
        backend, mock_client = mock_storage

        # First call (with Tagging) raises ClientError; second call (without) succeeds
        call_count = {"n": 0}

        def side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ClientError({"Error": {"Code": "AccessDenied"}}, "PutObject")

        mock_client.put_object.side_effect = side_effect

        # Should not raise — best-effort fallback kicks in
        backend.put_object("some/key", b"data", tags={"domain": "x"})

        assert mock_client.put_object.call_count == 2, (
            f"Expected 2 put_object calls (with tags, then without), "
            f"got: {mock_client.put_object.call_count}"
        )
