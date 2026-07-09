"""
S3-compatible storage abstraction for Knowledge Lake (FOUND-03, FOUND-04).

Single boto3 S3 client that works against both MinIO (dev, endpoint_url set)
and AWS S3 (prod, endpoint_url=None) via an endpoint_url toggle.  No second
client, no raw HTTP, no local filesystem.

Classes:
    StorageBackend — wraps a single boto3 S3 client; provides put_object,
                     get_object, exists, object_uri, and put_raw.

Immutability contract (FOUND-04):
    - Raw-zone keys are SHA256 content-addressed: raw/{source_id}/{sha256}.{ext}
    - put_raw checks the registry by hash BEFORE any S3 write (registry no-op)
    - head_object guard refuses overwrite of any existing raw key
    - No S3 If-None-Match:'*' conditional-write wildcard (MinIO gap — FOUND-04)
"""

from __future__ import annotations

import hashlib
import logging
import urllib.parse
from typing import TYPE_CHECKING, Optional

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from sqlalchemy.exc import IntegrityError

from knowledge_lake.config.settings import StorageSettings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from knowledge_lake.registry.models import Artifact

log = logging.getLogger(__name__)


def _format_tags(tags: dict[str, str]) -> str:
    """Encode a tag dict to the URL-encoded string S3's Tagging= parameter expects.

    S3 tag value limit is 256 characters. Values are truncated defensively.
    The resulting format is ``key=val&key2=val2`` as required by the S3 API.
    """
    safe = {k: v[:256] for k, v in tags.items()}
    return urllib.parse.urlencode(safe)


class StorageBackend:
    """Single boto3 S3 client for MinIO (dev) and AWS S3 (prod).

    Construction:
        Use ``StorageBackend(settings.storage)`` where ``settings`` is the
        application ``Settings`` instance.  The endpoint_url toggle selects
        the target:

        - ``endpoint_url`` set  → MinIO (or any S3-compatible endpoint)
        - ``endpoint_url=None`` → AWS S3 (standard regional endpoint)

    One client, one code path (FOUND-03).  No second S3 client is ever
    created by this class.
    """

    def __init__(self, storage: StorageSettings) -> None:
        """Build the single boto3 S3 client from StorageSettings.

        Parameters
        ----------
        storage:
            ``StorageSettings`` instance (from ``Settings.storage``).
        """
        self._bucket = storage.bucket
        client_kwargs: dict = {
            "service_name": "s3",
            "region_name": storage.region,
            "config": BotoConfig(signature_version="s3v4"),
        }
        if storage.endpoint_url is not None:
            # MinIO / S3-compatible dev mode
            client_kwargs["endpoint_url"] = storage.endpoint_url
        if storage.access_key_id is not None:
            client_kwargs["aws_access_key_id"] = storage.access_key_id
        if storage.secret_access_key is not None:
            client_kwargs["aws_secret_access_key"] = storage.secret_access_key

        self._client = boto3.client(**client_kwargs)

    # ── Core operations ───────────────────────────────────────────────────────

    def put_object(
        self,
        key: str,
        data: bytes,
        tags: Optional[dict[str, str]] = None,
    ) -> None:
        """Write bytes to an arbitrary key in the configured bucket.

        Does NOT enforce immutability — use ``put_raw`` for the raw zone.

        Parameters
        ----------
        key:
            S3 object key (path within the bucket).
        data:
            Raw bytes to store.
        tags:
            Optional dict of tag key-value pairs. When provided, encoded as a
            URL-encoded string and passed to the S3 ``Tagging=`` parameter (D-07,
            D-08). Tagging is best-effort: if the S3 call fails due to a
            ``ClientError``, a tagless retry is attempted so the object is always
            written (D-10). Registry remains the source of truth (D-07).
        """
        kwargs: dict = {"Bucket": self._bucket, "Key": key, "Body": data}
        if tags:
            kwargs["Tagging"] = _format_tags(tags)
        try:
            self._client.put_object(**kwargs)
        except ClientError:
            if tags:
                # Best-effort: retry without tags so the object is always written (D-10)
                log.warning(
                    "put_object: tagging failed, retrying without tags (key=%s)", key
                )
                self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
            else:
                raise
        log.debug("stored", bucket=self._bucket, key=key, size=len(data))

    def get_object(self, key: str) -> bytes:
        """Read and return the full contents of an object.

        Parameters
        ----------
        key:
            S3 object key.

        Returns
        -------
        bytes
            The raw bytes of the stored object.

        Raises
        ------
        ClientError
            If the key does not exist (NoSuchKey).
        """
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    def exists(self, key: str) -> bool:
        """Return True if the key exists in the bucket, False otherwise.

        Uses ``head_object`` for an O(1) existence check without fetching
        the body.

        Parameters
        ----------
        key:
            S3 object key to check.
        """
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    def object_uri(self, key: str) -> str:
        """Return the S3 URI for an object.

        Parameters
        ----------
        key:
            S3 object key.

        Returns
        -------
        str
            ``s3://<bucket>/<key>``
        """
        return f"s3://{self._bucket}/{key}"

    # ── Content-addressed immutable raw zone (FOUND-04) ───────────────────────

    def put_raw(
        self,
        source_id: str,
        data: bytes,
        ext: str,
        session: "Session",
        mime_type: Optional[str] = None,
    ) -> "Artifact":
        """Write bytes to the content-addressed immutable raw zone.

        Enforcement layers (Pattern 1 — all four applied):

        1. **Registry no-op:** SHA256 lookup before any S3 write.  If an
           artifact with this hash already exists, return it immediately —
           no S3 write, no new registry node (FOUND-04 verbatim).
        2. **Content-addressed key:** ``raw/{source_id}/{sha256}.{ext}`` —
           identity == content, so an overwrite is structurally impossible.
        3. **head_object guard:** if the hash is new but the key somehow
           already exists (should not happen for SHA256), raise rather than
           overwriting.
        4. **Bucket-level WORM:** versioning + object lock + delete-deny
           bucket policy applied by ``bootstrap.ensure_buckets``.

        NOT used: S3 ``If-None-Match:'*'`` conditional-write wildcard.
        MinIO does not support it (minio/minio#20346); enforcement is
        backend-portable via the layers above.

        Parameters
        ----------
        source_id:
            Registry source ID (used as the key prefix).
        data:
            Raw bytes to store.
        ext:
            File extension without the leading dot (e.g. ``"pdf"``).
        session:
            Active SQLAlchemy session for the registry lookup and write.

        Returns
        -------
        Artifact
            Either the existing artifact (no-op path) or the newly created
            artifact (new write path).

        Raises
        ------
        RuntimeError
            If the content-addressed key already exists in S3 but no
            registry artifact exists for this hash (defense-in-depth guard).
        """
        from knowledge_lake.registry import repo

        # Layer 1: compute content hash
        content_hash = hashlib.sha256(data).hexdigest()

        # Layer 2: registry no-op — return existing artifact without any S3 write
        existing = repo.get_artifact_by_hash(session, content_hash, "raw_document")
        if existing is not None:
            log.debug(
                "put_raw no-op: artifact already in registry",
                content_hash=content_hash,
                artifact_id=existing.id,
            )
            return existing

        # Layer 3: build content-addressed key
        key = f"raw/{source_id}/{content_hash}.{ext}"

        # Layer 4: head_object guard — refuse overwrite if key already exists
        if self.exists(key):
            raise RuntimeError(
                f"Raw key already exists, refusing overwrite: {key!r}. "
                "This should not happen for SHA256 content-addressed keys. "
                "Possible corruption — do not overwrite the raw zone."
            )

        # Layer 5: write bytes to S3 (NO If-None-Match:'*')
        self.put_object(key, data)
        log.info("put_raw stored new raw artifact", key=key, size=len(data))

        # Layer 6: create registry artifact node
        # Catch IntegrityError from concurrent writes of identical content:
        # both workers pass layers 1-2 (registry check), then both write to S3
        # (idempotent for SHA256 content-addressed keys), then both attempt the
        # registry insert. The second writer gets IntegrityError on
        # uq_artifacts_hash_type; we roll back and return the first writer's row.
        try:
            artifact = repo.create_raw_artifact(
                session,
                source_id=source_id,
                content_hash=content_hash,
                storage_uri=self.object_uri(key),
                mime_type=mime_type,
            )
            session.flush()
        except IntegrityError:
            session.rollback()
            session.expire_all()  # clear identity map after rollback (CR-003)
            artifact = repo.get_artifact_by_hash(session, content_hash, "raw_document")
            if artifact is None:
                raise  # unexpected — constraint violation on a different column
        log.info(
            "put_raw created registry node",
            artifact_id=artifact.id,
            storage_uri=artifact.storage_uri,
        )
        return artifact

    # ── Content-addressed bronze zone (D-01, INGEST-04) ──────────────────────

    def put_bronze(
        self,
        source_id: str,
        data: bytes,
        ext: str,
        session: "Session",
        *,
        parent_artifact_id: str,
    ) -> "Artifact":
        """Write bytes to the content-addressed bronze zone with lineage.

        Mirrors the put_raw pattern exactly (six enforcement layers) but:
          - Zone prefix: ``bronze/`` (not ``raw/``)
          - Artifact type: ``bronze_document`` (not ``raw_document``)
          - parent_artifact_id: REQUIRED (links bronze -> raw, D-01 two-artifact lineage)

        The hash-second no-op reuses get_artifact_by_hash("bronze_document") so
        re-processing identical content is a registry-level no-op.

        Parameters
        ----------
        source_id:
            Registry source ID (used as the key prefix).
        data:
            Processed bytes to store (e.g. markdown, cleaned HTML).
        ext:
            File extension without the leading dot (e.g. ``"md"``).
        session:
            Active SQLAlchemy session for the registry lookup and write.
        parent_artifact_id:
            ID of the raw artifact this bronze artifact derives from (D-01 lineage).

        Returns
        -------
        Artifact
            Either the existing artifact (no-op path) or the newly created
            bronze artifact.

        Raises
        ------
        RuntimeError
            If the content-addressed key already exists in S3 but no
            registry artifact exists for this hash (defense-in-depth guard).
        """
        from knowledge_lake.registry import repo

        # Layer 1: compute content hash
        content_hash = hashlib.sha256(data).hexdigest()

        # Layer 2: registry no-op — return existing artifact without any S3 write
        existing = repo.get_artifact_by_hash(session, content_hash, "bronze_document")
        if existing is not None:
            log.debug(
                "put_bronze no-op: artifact already in registry",
                content_hash=content_hash,
                artifact_id=existing.id,
            )
            return existing

        # Layer 3: build content-addressed key
        key = f"bronze/{source_id}/{content_hash}.{ext}"

        # Layer 4: head_object guard — refuse overwrite if key already exists
        if self.exists(key):
            raise RuntimeError(
                f"Bronze key already exists, refusing overwrite: {key!r}. "
                "This should not happen for SHA256 content-addressed keys. "
                "Possible corruption — do not overwrite the bronze zone."
            )

        # Layer 5: write bytes to S3
        self.put_object(key, data)
        log.info("put_bronze stored new bronze artifact", key=key, size=len(data))

        # Layer 6: create registry artifact node with parent linkage
        # Same concurrent-write race protection as put_raw: catch IntegrityError
        # and return the winning writer's artifact row.
        try:
            artifact = repo.create_bronze_artifact(
                session,
                source_id=source_id,
                content_hash=content_hash,
                storage_uri=self.object_uri(key),
                parent_artifact_id=parent_artifact_id,
            )
            session.flush()
        except IntegrityError:
            session.rollback()
            session.expire_all()  # clear identity map after rollback (CR-003)
            artifact = repo.get_artifact_by_hash(session, content_hash, "bronze_document")
            if artifact is None:
                raise  # unexpected — constraint violation on a different column
        log.info(
            "put_bronze created registry node",
            artifact_id=artifact.id,
            parent_artifact_id=parent_artifact_id,
            storage_uri=artifact.storage_uri,
        )
        return artifact
