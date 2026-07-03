"""
Integration tests for the StorageBackend boto3 abstraction (FOUND-03).

Tests run against the compose/local MinIO instance.

Requirements tested:
- StorageBackend wraps a single boto3 S3 client
- put_object / get_object round-trips identical bytes against MinIO
- exists() returns True after a put and False for an absent key
- AWS-mode client construction when endpoint_url is None
- Raw bucket creation with versioning + object lock + delete-deny policy

Run with:
    uv run pytest tests/integration/test_storage.py -x -q
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest
import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from knowledge_lake.config.settings import Settings, StorageSettings
from knowledge_lake.storage.s3 import StorageBackend
from knowledge_lake.storage.bootstrap import ensure_buckets


# ── Fixtures ──────────────────────────────────────────────────────────────────

MINIO_ENDPOINT = os.environ.get("KLAKE_STORAGE__ENDPOINT_URL", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("KLAKE_STORAGE__ACCESS_KEY_ID", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("KLAKE_STORAGE__SECRET_ACCESS_KEY", "minioadmin")
TEST_BUCKET = "klake-test-storage"


@pytest.fixture(scope="module")
def storage_settings() -> StorageSettings:
    """StorageSettings pointed at the local MinIO instance."""
    return StorageSettings(
        endpoint_url=MINIO_ENDPOINT,
        bucket=TEST_BUCKET,
        region="us-east-1",
        access_key_id=MINIO_ACCESS_KEY,
        secret_access_key=MINIO_SECRET_KEY,
    )


@pytest.fixture(scope="module")
def backend(storage_settings: StorageSettings) -> StorageBackend:
    """StorageBackend connected to the test bucket on MinIO."""
    # Create the test bucket first (not the raw WORM bucket — that's bootstrap)
    direct_client = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
        config=BotoConfig(signature_version="s3v4"),
    )
    try:
        direct_client.create_bucket(Bucket=TEST_BUCKET)
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            raise
    return StorageBackend(storage_settings)


@pytest.fixture(scope="module")
def raw_settings() -> StorageSettings:
    """StorageSettings for the raw WORM bucket bootstrap test."""
    return StorageSettings(
        endpoint_url=MINIO_ENDPOINT,
        bucket="klake-test-raw-bootstrap",
        region="us-east-1",
        access_key_id=MINIO_ACCESS_KEY,
        secret_access_key=MINIO_SECRET_KEY,
    )


# ── Single-client guard ───────────────────────────────────────────────────────


class TestSingleBoto3Client:
    """StorageBackend must wrap exactly one boto3 S3 client (FOUND-03)."""

    def test_backend_has_single_client(self, backend: StorageBackend) -> None:
        """StorageBackend exposes a single internal boto3 client."""
        # The backend should have one client attribute (named _client or similar)
        assert hasattr(backend, "_client"), (
            "StorageBackend must expose _client as the single boto3 S3 client"
        )

    def test_client_is_boto3_s3_client(self, backend: StorageBackend) -> None:
        """The _client attribute must be a botocore S3 client."""
        client = backend._client
        # botocore clients expose _endpoint which has .host
        assert hasattr(client, "put_object"), "Client must be a boto3 S3 client"
        assert hasattr(client, "get_object"), "Client must be a boto3 S3 client"
        assert hasattr(client, "head_object"), "Client must be a boto3 S3 client"

    def test_minio_client_has_endpoint_url(self, backend: StorageBackend) -> None:
        """When endpoint_url is set (MinIO mode), client endpoint must match."""
        # botocore stores endpoint on _endpoint.host
        meta = backend._client.meta
        endpoint = meta.endpoint_url
        assert endpoint == MINIO_ENDPOINT, (
            f"Expected client endpoint {MINIO_ENDPOINT}, got {endpoint}"
        )


# ── put_object / get_object round-trip ────────────────────────────────────────


class TestRoundTrip:
    """StorageBackend puts and gets identical bytes (FOUND-03)."""

    def test_put_and_get_bytes_round_trip(self, backend: StorageBackend) -> None:
        """Bytes written with put_object are returned unchanged by get_object."""
        key = "test/roundtrip/hello.bin"
        data = b"Hello, Knowledge Lake!"
        backend.put_object(key, data)
        result = backend.get_object(key)
        assert result == data, f"Expected {data!r}, got {result!r}"

    def test_round_trip_preserves_binary_payload(self, backend: StorageBackend) -> None:
        """Binary payloads with NUL bytes round-trip faithfully."""
        key = "test/roundtrip/binary.bin"
        data = bytes(range(256))  # all byte values including NUL
        backend.put_object(key, data)
        result = backend.get_object(key)
        assert result == data

    def test_round_trip_utf8_json(self, backend: StorageBackend) -> None:
        """UTF-8 encoded JSON round-trips faithfully."""
        key = "test/roundtrip/meta.json"
        payload = {"source": "hhs.gov", "page": 42, "text": "administrative safeguards"}
        data = json.dumps(payload).encode("utf-8")
        backend.put_object(key, data)
        result = backend.get_object(key)
        assert json.loads(result) == payload


# ── exists() semantics ────────────────────────────────────────────────────────


class TestExists:
    """exists() returns True after a put and False for an absent key."""

    def test_exists_returns_false_for_absent_key(self, backend: StorageBackend) -> None:
        """exists() must return False for a key that has never been stored."""
        absent_key = "test/exists/totally_absent_key_xyz12345.bin"
        assert backend.exists(absent_key) is False

    def test_exists_returns_true_after_put(self, backend: StorageBackend) -> None:
        """exists() must return True after a successful put_object."""
        key = "test/exists/present.bin"
        backend.put_object(key, b"I exist!")
        assert backend.exists(key) is True

    def test_exists_via_head_object(self, backend: StorageBackend) -> None:
        """StorageBackend.exists() must use head_object (not list_objects)."""
        # This is verified by inspecting the implementation; here we test behavior
        key = "test/exists/head_check.bin"
        assert backend.exists(key) is False
        backend.put_object(key, b"checking")
        assert backend.exists(key) is True


# ── object_uri ────────────────────────────────────────────────────────────────


class TestObjectUri:
    """object_uri returns a well-formed S3 URI string."""

    def test_object_uri_format(self, backend: StorageBackend) -> None:
        """object_uri must return s3://<bucket>/<key>."""
        key = "raw/src_123/abcdef.pdf"
        uri = backend.object_uri(key)
        assert uri == f"s3://{TEST_BUCKET}/{key}", (
            f"Expected s3://{TEST_BUCKET}/{key}, got {uri}"
        )


# ── AWS-mode client construction ──────────────────────────────────────────────


class TestAWSModeClient:
    """When endpoint_url is None, client is constructed for AWS S3 (not MinIO)."""

    def test_aws_mode_client_has_no_endpoint_url(self) -> None:
        """StorageBackend with endpoint_url=None must produce an AWS-mode client."""
        aws_settings = StorageSettings(
            endpoint_url=None,  # AWS mode
            bucket="some-bucket",
            region="us-west-2",
            access_key_id="AKIAIOSFODNN7EXAMPLE",
            secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        b = StorageBackend(aws_settings)
        meta = b._client.meta
        # In AWS mode, the endpoint URL is the standard AWS S3 endpoint, not a custom one
        endpoint = meta.endpoint_url
        # boto3 uses a regional AWS endpoint, NOT a custom URL
        # endpoint_url in meta should be None or the default AWS endpoint
        # (botocore meta.endpoint_url is None when no custom endpoint was set)
        assert endpoint is None, (
            f"AWS-mode client must have no custom endpoint_url, got {endpoint!r}"
        )

    def test_aws_mode_uses_correct_region(self) -> None:
        """AWS-mode client must use the region from settings."""
        aws_settings = StorageSettings(
            endpoint_url=None,
            bucket="some-bucket",
            region="eu-west-1",
            access_key_id="AKIAIOSFODNN7EXAMPLE",
            secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        b = StorageBackend(aws_settings)
        # Region is visible via the client's meta region_name
        assert b._client.meta.region_name == "eu-west-1"


# ── Raw bucket bootstrap (versioning + object lock + delete-deny policy) ──────


class TestRawBucketBootstrap:
    """ensure_buckets creates raw bucket with WORM protections (FOUND-04)."""

    def test_ensure_buckets_creates_raw_bucket(self, raw_settings: StorageSettings) -> None:
        """ensure_buckets must create the configured bucket."""
        # Remove existing bucket if present
        direct_client = boto3.client(
            "s3",
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            region_name="us-east-1",
            config=BotoConfig(signature_version="s3v4"),
        )
        try:
            direct_client.delete_bucket(Bucket=raw_settings.bucket)
        except ClientError:
            pass  # May not exist yet

        ensure_buckets(raw_settings)

        # Bucket must now exist
        resp = direct_client.list_buckets()
        bucket_names = [b["Name"] for b in resp["Buckets"]]
        assert raw_settings.bucket in bucket_names, (
            f"Bucket {raw_settings.bucket!r} not created by ensure_buckets"
        )

    def test_raw_bucket_has_versioning_enabled(self, raw_settings: StorageSettings) -> None:
        """Raw bucket must have versioning enabled."""
        direct_client = boto3.client(
            "s3",
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            region_name="us-east-1",
            config=BotoConfig(signature_version="s3v4"),
        )
        resp = direct_client.get_bucket_versioning(Bucket=raw_settings.bucket)
        assert resp.get("Status") == "Enabled", (
            f"Versioning must be Enabled for raw bucket; got {resp.get('Status')!r}"
        )

    def test_raw_bucket_has_object_lock_configured(self, raw_settings: StorageSettings) -> None:
        """Raw bucket must have object lock configured (GOVERNANCE/COMPLIANCE)."""
        direct_client = boto3.client(
            "s3",
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            region_name="us-east-1",
            config=BotoConfig(signature_version="s3v4"),
        )
        # get_object_lock_configuration raises if object lock was not enabled at creation
        resp = direct_client.get_object_lock_configuration(Bucket=raw_settings.bucket)
        lock_config = resp.get("ObjectLockConfiguration", {})
        assert lock_config.get("ObjectLockEnabled") == "Enabled", (
            f"Object lock must be Enabled; got {lock_config}"
        )

    def test_raw_bucket_has_delete_deny_policy(self, raw_settings: StorageSettings) -> None:
        """Raw bucket must have a bucket policy denying s3:DeleteObject."""
        direct_client = boto3.client(
            "s3",
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            region_name="us-east-1",
            config=BotoConfig(signature_version="s3v4"),
        )
        resp = direct_client.get_bucket_policy(Bucket=raw_settings.bucket)
        policy = json.loads(resp["Policy"])
        # The policy must include a Deny effect on s3:DeleteObject
        statements = policy.get("Statement", [])
        deny_deletes = [
            s for s in statements
            if s.get("Effect") == "Deny"
            and "s3:DeleteObject" in (
                [s["Action"]] if isinstance(s["Action"], str) else s["Action"]
            )
        ]
        assert deny_deletes, (
            f"Bucket policy must include Deny s3:DeleteObject; statements: {statements}"
        )

    def test_ensure_buckets_is_idempotent(self, raw_settings: StorageSettings) -> None:
        """Calling ensure_buckets again on existing bucket must not raise."""
        ensure_buckets(raw_settings)  # second call; bucket already exists
