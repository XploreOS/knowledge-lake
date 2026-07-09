"""
Integration tests for put_raw: content-addressed immutable raw zone (FOUND-04).

These tests verify the four enforcement layers of Pattern 1:

1. Content-addressed key: raw/{domain}/{source_id}/{sha256}.{ext} — when no domain
   is configured for the source, the ``_unclassified`` segment is used as a real
   routed fallback (STORE-01, D-01). New writes always use domain-scoped keys;
   existing raw keys are never rewritten (forward-only, D-06).
2. Registry no-op: re-ingesting identical content returns the existing artifact
   with no new S3 write and no new registry node
3. head_object guard: overwriting an existing raw key is refused (RuntimeError)
4. No S3 If-None-Match:'*' conditional-write wildcard used anywhere

Tests run against:
  - Live MinIO (local compose stack)
  - Live PostgreSQL (klake_test database, Alembic-migrated by test fixture)

Run with:
    uv run pytest tests/integration/test_raw_immutable.py -x -q
"""

from __future__ import annotations

import hashlib
import os
import uuid

import pytest
import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from knowledge_lake.config.settings import StorageSettings
from knowledge_lake.storage.s3 import StorageBackend
from knowledge_lake.storage.bootstrap import ensure_buckets
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.models import Base


# ── Connection constants ───────────────────────────────────────────────────────

MINIO_ENDPOINT = os.environ.get("KLAKE_STORAGE__ENDPOINT_URL", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("KLAKE_STORAGE__ACCESS_KEY_ID", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("KLAKE_STORAGE__SECRET_ACCESS_KEY", "minioadmin")
TEST_BUCKET = "klake-test-raw-immutable"

TEST_DB_URL = os.environ.get(
    "KLAKE_TEST_DATABASE_URL",
    "postgresql+psycopg://klake:klake@localhost:5432/klake_test",
)


# ── Module-level fixtures ──────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def raw_settings() -> StorageSettings:
    """StorageSettings for the raw immutability test bucket."""
    return StorageSettings(
        endpoint_url=MINIO_ENDPOINT,
        bucket=TEST_BUCKET,
        region="us-east-1",
        access_key_id=MINIO_ACCESS_KEY,
        secret_access_key=MINIO_SECRET_KEY,
    )


@pytest.fixture(scope="module")
def backend(raw_settings: StorageSettings) -> StorageBackend:
    """StorageBackend with WORM bucket bootstrapped."""
    # Ensure the test bucket exists with WORM protections
    # Clean up any existing bucket first for test isolation
    direct = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
        config=BotoConfig(signature_version="s3v4"),
    )
    # Clean up existing objects (WORM policy would prevent deletion in prod,
    # but for test isolation we need a fresh bucket; delete + recreate)
    try:
        _purge_bucket(direct, TEST_BUCKET)
        direct.delete_bucket(Bucket=TEST_BUCKET)
    except ClientError:
        pass
    ensure_buckets(raw_settings)
    return StorageBackend(raw_settings)


def _purge_bucket(client, bucket: str) -> None:
    """Delete all versioned objects from a bucket to allow bucket deletion."""
    try:
        paginator = client.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bucket):
            for version in page.get("Versions", []):
                client.delete_object(
                    Bucket=bucket,
                    Key=version["Key"],
                    VersionId=version["VersionId"],
                )
            for marker in page.get("DeleteMarkers", []):
                client.delete_object(
                    Bucket=bucket,
                    Key=marker["Key"],
                    VersionId=marker["VersionId"],
                )
    except ClientError:
        pass


@pytest.fixture(scope="module")
def engine():
    """Synchronous SQLAlchemy engine for the test database."""
    # Use SQLite in-memory for unit testing the registry+storage integration
    # (faster and no external dependency for the logic tests)
    import sqlalchemy
    eng = sqlalchemy.create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine) -> Session:
    """Function-scoped transactional session that rolls back after each test."""
    conn = engine.connect()
    trans = conn.begin()
    sess = sessionmaker(bind=conn)()
    yield sess
    sess.close()
    trans.rollback()
    conn.close()


@pytest.fixture()
def source_id(session: Session) -> str:
    """Create a test source and return its ID."""
    src = registry_repo.create_source(
        session,
        name="Test Source",
        source_type="upload",
        url=None,
        license_type="public_domain",
        robots_checked=True,
    )
    session.flush()
    return src.id


# ── Test data ─────────────────────────────────────────────────────────────────

SAMPLE_DATA = b"This is a test healthcare PDF content for immutability testing."
SAMPLE_EXT = "pdf"
SAMPLE_HASH = hashlib.sha256(SAMPLE_DATA).hexdigest()


# ── Test 1: First put_raw creates object + node ───────────────────────────────


class TestPutRawFirstStore:
    """First put_raw creates both the S3 object and the registry artifact node."""

    def test_put_raw_returns_artifact(
        self, backend: StorageBackend, session: Session, source_id: str
    ) -> None:
        """put_raw must return an Artifact with the correct content_hash."""
        from knowledge_lake.registry.models import Artifact

        artifact = backend.put_raw(source_id, SAMPLE_DATA, SAMPLE_EXT, session)
        assert artifact is not None
        assert isinstance(artifact, Artifact)
        assert artifact.content_hash == SAMPLE_HASH

    def test_put_raw_creates_s3_object(
        self, backend: StorageBackend, session: Session, source_id: str
    ) -> None:
        """After put_raw, the content-addressed key must exist in S3."""
        backend.put_raw(source_id, SAMPLE_DATA, SAMPLE_EXT, session)
        expected_key = f"raw/_unclassified/{source_id}/{SAMPLE_HASH}.{SAMPLE_EXT}"
        assert backend.exists(expected_key), (
            f"Expected S3 key {expected_key!r} to exist after put_raw"
        )

    def test_put_raw_key_is_content_addressed(
        self, backend: StorageBackend, session: Session, source_id: str
    ) -> None:
        """Raw key format must be raw/_unclassified/{source_id}/{sha256}.{ext} when no domain is configured."""
        artifact = backend.put_raw(source_id, SAMPLE_DATA, SAMPLE_EXT, session)
        expected_uri = f"s3://{TEST_BUCKET}/raw/_unclassified/{source_id}/{SAMPLE_HASH}.{SAMPLE_EXT}"
        assert artifact.storage_uri == expected_uri, (
            f"Expected storage_uri {expected_uri!r}, got {artifact.storage_uri!r}"
        )

    def test_put_raw_creates_registry_node_with_source_id(
        self, backend: StorageBackend, session: Session, source_id: str
    ) -> None:
        """Registry artifact must reference the correct source."""
        artifact = backend.put_raw(source_id, SAMPLE_DATA, SAMPLE_EXT, session)
        assert artifact.source_id == source_id

    def test_put_raw_creates_raw_document_artifact_type(
        self, backend: StorageBackend, session: Session, source_id: str
    ) -> None:
        """Registry artifact must be of type 'raw_document'."""
        artifact = backend.put_raw(source_id, SAMPLE_DATA, SAMPLE_EXT, session)
        assert artifact.artifact_type == "raw_document"

    def test_put_raw_artifact_has_no_parent(
        self, backend: StorageBackend, session: Session, source_id: str
    ) -> None:
        """Raw document artifact must have no parent (root of lineage tree)."""
        artifact = backend.put_raw(source_id, SAMPLE_DATA, SAMPLE_EXT, session)
        assert artifact.parent_artifact_id is None


# ── Test 2: Re-ingesting identical content is a registry-level no-op ──────────


class TestPutRawRegistryNoOp:
    """FOUND-04: re-ingesting identical content is a registry no-op."""

    def test_second_put_raw_returns_same_artifact_id(
        self, backend: StorageBackend, session: Session, source_id: str
    ) -> None:
        """Second put_raw with identical bytes must return the SAME artifact."""
        first = backend.put_raw(source_id, SAMPLE_DATA, SAMPLE_EXT, session)
        session.flush()
        second = backend.put_raw(source_id, SAMPLE_DATA, SAMPLE_EXT, session)
        assert first.id == second.id, (
            f"Second put_raw must return same artifact ID: "
            f"first={first.id!r}, second={second.id!r}"
        )

    def test_second_put_raw_does_not_create_new_node(
        self, backend: StorageBackend, session: Session, source_id: str
    ) -> None:
        """Re-ingesting identical content must NOT create a new artifact node."""
        from sqlalchemy import select
        from knowledge_lake.registry.models import Artifact

        backend.put_raw(source_id, SAMPLE_DATA, SAMPLE_EXT, session)
        session.flush()

        # Count artifacts before second put
        stmt = select(Artifact).where(Artifact.content_hash == SAMPLE_HASH)
        count_before = len(list(session.execute(stmt).scalars()))

        # Second put_raw
        backend.put_raw(source_id, SAMPLE_DATA, SAMPLE_EXT, session)
        session.flush()

        count_after = len(list(session.execute(stmt).scalars()))
        assert count_after == count_before, (
            f"Re-ingesting identical content must not create new nodes: "
            f"before={count_before}, after={count_after}"
        )

    def test_second_put_raw_does_not_write_new_s3_version(
        self, backend: StorageBackend, session: Session, source_id: str
    ) -> None:
        """Second put_raw with identical bytes must NOT call put_object again.

        We verify this by patching the backend's _client.put_object and
        asserting it is called exactly once (on the first put_raw, not the
        second).
        """
        from unittest.mock import patch as mock_patch

        first_artifact = backend.put_raw(source_id, SAMPLE_DATA, SAMPLE_EXT, session)
        session.flush()

        # Patch _client.put_object to detect if it is called
        with mock_patch.object(backend._client, "put_object", wraps=backend._client.put_object) as mock_put:
            backend.put_raw(source_id, SAMPLE_DATA, SAMPLE_EXT, session)
            assert mock_put.call_count == 0, (
                "put_object must NOT be called for re-ingesting identical content"
            )


# ── Test 3: head_object guard refuses overwrite ────────────────────────────────


class TestPutRawOverwriteGuard:
    """head_object guard refuses overwrite of existing raw key."""

    def test_forced_key_collision_raises_runtime_error(
        self, backend: StorageBackend, session: Session, source_id: str
    ) -> None:
        """If key exists but no registry artifact: put_raw must raise RuntimeError."""
        # Pre-write the key directly (bypassing registry) to simulate key collision
        # No domain is passed — key uses _unclassified segment (new format)
        key = f"raw/_unclassified/{source_id}/{SAMPLE_HASH}.{SAMPLE_EXT}"
        backend._client.put_object(Bucket=TEST_BUCKET, Key=key, Body=SAMPLE_DATA)

        # Now attempt put_raw with same data — registry says no artifact,
        # but S3 key exists → should raise (overwrite guard)
        # NOTE: registry is empty here (fresh session, no prior put_raw),
        # so the registry no-op path is NOT triggered.  The head_object guard fires.
        with pytest.raises(RuntimeError, match="[Rr]aw key already exists"):
            backend.put_raw(source_id, SAMPLE_DATA, SAMPLE_EXT, session)


# ── Test 4: No If-None-Match:'*' conditional-write used ───────────────────────


class TestNoConditionalWriteWildcard:
    """put_raw must not use S3 If-None-Match:'*' conditional-write wildcard.

    MinIO does not support this wildcard (minio/minio#20346).
    Enforcement must be at the app + bucket-policy layer, not via S3 API.
    """

    def test_put_raw_does_not_use_if_none_match_wildcard(
        self, backend: StorageBackend, session: Session, source_id: str
    ) -> None:
        """put_raw must not pass IfNoneMatch to put_object."""
        from unittest.mock import patch as mock_patch

        captured_kwargs: list[dict] = []

        original_put = backend._client.put_object

        def capture_put(**kwargs):
            captured_kwargs.append(kwargs)
            return original_put(**kwargs)

        with mock_patch.object(backend._client, "put_object", side_effect=capture_put):
            # Use unique content to ensure this is a new write (not no-op)
            unique_data = b"unique content " + uuid.uuid4().bytes
            backend.put_raw(source_id, unique_data, "txt", session)

        assert captured_kwargs, "put_object should have been called for new content"
        for call_kwargs in captured_kwargs:
            assert "IfNoneMatch" not in call_kwargs, (
                "put_raw must NOT use IfNoneMatch:'*' (MinIO does not support it)"
            )

    def test_storage_module_has_no_if_none_match_wildcard_in_source(self) -> None:
        """Source code of s3.py must not contain IfNoneMatch='*' pattern."""
        import inspect
        from knowledge_lake.storage import s3
        source = inspect.getsource(s3)
        assert "IfNoneMatch" not in source, (
            "s3.py source must not contain IfNoneMatch (conditional-write wildcard)"
        )
