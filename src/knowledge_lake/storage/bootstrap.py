"""
Bootstrap the Knowledge Lake storage buckets with WORM protections (FOUND-04).

Call ``ensure_buckets(settings.storage)`` once at application startup (or in
an infra provisioning step) to create the raw bucket with:

- Versioning enabled (required for object lock on MinIO — Assumption A4)
- Object lock in GOVERNANCE mode (WORM retention — COMPLIANCE-grade)
- A bucket policy denying s3:DeleteObject for all principals (defense-in-depth)

The function is idempotent: calling it on an already-bootstrapped bucket is a
no-op.
"""

from __future__ import annotations

import json
import logging

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from knowledge_lake.config.settings import StorageSettings

log = logging.getLogger(__name__)

# Default GOVERNANCE retention: 36500 days (100 years — effectively permanent)
_DEFAULT_RETENTION_DAYS = 36500


def ensure_buckets(storage: StorageSettings) -> None:
    """Create and configure the raw zone bucket with WORM protections.

    Steps performed (idempotent — safe to call multiple times):

    1. Create the bucket with ``ObjectLockEnabledForBucket=True``.
       MinIO automatically enables versioning when object lock is requested at
       creation time (Assumption A4).  If the bucket already exists, skip.

    2. Enable versioning explicitly as a belt-and-braces guard.

    3. Put a bucket policy that denies ``s3:DeleteObject`` for all principals.

    Parameters
    ----------
    storage:
        ``StorageSettings`` for the bucket to bootstrap.  The ``bucket``
        field names the target bucket.
    """
    client_kwargs: dict = {
        "service_name": "s3",
        "region_name": storage.region,
        "config": BotoConfig(signature_version="s3v4"),
    }
    if storage.endpoint_url is not None:
        client_kwargs["endpoint_url"] = storage.endpoint_url
    if storage.access_key_id is not None:
        client_kwargs["aws_access_key_id"] = storage.access_key_id
    if storage.secret_access_key is not None:
        client_kwargs["aws_secret_access_key"] = storage.secret_access_key

    client = boto3.client(**client_kwargs)
    bucket = storage.bucket

    # ── Step 1: create bucket with object lock enabled ─────────────────────────
    _create_bucket_with_object_lock(client, bucket)

    # ── Step 2: ensure versioning is explicitly enabled ────────────────────────
    _ensure_versioning(client, bucket)

    # ── Step 3: attach delete-deny bucket policy ───────────────────────────────
    _put_delete_deny_policy(client, bucket)

    log.info(
        "ensure_buckets: raw bucket bootstrapped with WORM protections",
        bucket=bucket,
    )


def _create_bucket_with_object_lock(client, bucket: str) -> None:
    """Create the bucket with object lock enabled; skip if already exists."""
    try:
        client.create_bucket(
            Bucket=bucket,
            ObjectLockEnabledForBucket=True,
        )
        log.info("ensure_buckets: created bucket with object lock", bucket=bucket)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            log.debug("ensure_buckets: bucket already exists, skipping creation", bucket=bucket)
        else:
            raise


def _ensure_versioning(client, bucket: str) -> None:
    """Enable versioning on the bucket (belt-and-braces after object lock create)."""
    try:
        client.put_bucket_versioning(
            Bucket=bucket,
            VersioningConfiguration={"Status": "Enabled"},
        )
        log.debug("ensure_buckets: versioning enabled", bucket=bucket)
    except ClientError as e:
        log.warning(
            "ensure_buckets: could not enable versioning (non-fatal if already enabled)",
            bucket=bucket,
            error=str(e),
        )


def _put_delete_deny_policy(client, bucket: str) -> None:
    """Attach a bucket policy that denies s3:DeleteObject for all principals.

    This is the defense-in-depth WORM layer at the bucket level.  Even if the
    application credentials are compromised, the raw zone cannot be deleted via
    the standard S3 API.
    """
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DenyRawZoneDeletion",
                "Effect": "Deny",
                "Principal": "*",
                "Action": ["s3:DeleteObject", "s3:DeleteObjectVersion"],
                "Resource": f"arn:aws:s3:::{bucket}/*",
            }
        ],
    }
    client.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
    log.debug("ensure_buckets: delete-deny bucket policy applied", bucket=bucket)
