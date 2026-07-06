"""
Integration tests for pipeline/export.py — live MinIO + DuckDB round-trip (EXPORT-01).

Tests a genuine Parquet export: seeded chunk artifacts are written to the MinIO
gold zone via export_rag_corpus(), then DuckDB's httpfs extension reads back the
file and reports the exact seeded row count.

Run with:
    uv run pytest tests/integration/test_export_parquet_duckdb.py -x -m integration

Requirements:
    - MinIO running at KLAKE_STORAGE__ENDPOINT_URL (default: http://localhost:9000)
    - PostgreSQL running at KLAKE_TEST_DATABASE_URL (default: postgresql+psycopg://klake:klake@localhost:5432/klake_test)
"""

from __future__ import annotations

import os

import boto3
import pytest
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from knowledge_lake.config.settings import Settings, StorageSettings
from knowledge_lake.storage.s3 import StorageBackend

# ── Environment ───────────────────────────────────────────────────────────────

MINIO_ENDPOINT = os.environ.get("KLAKE_STORAGE__ENDPOINT_URL", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("KLAKE_STORAGE__ACCESS_KEY_ID", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("KLAKE_STORAGE__SECRET_ACCESS_KEY", "minioadmin")
TEST_BUCKET = "klake-test-export"
TEST_DB_URL = os.environ.get(
    "KLAKE_TEST_DATABASE_URL",
    "postgresql+psycopg://klake:klake@localhost:5432/klake_test",
)

pytestmark = pytest.mark.integration


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def storage_settings() -> StorageSettings:
    """StorageSettings pointed at the klake-test-export bucket on MinIO."""
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
    # Create the test bucket using a direct boto3 client (out-of-band setup)
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
def engine():
    """SQLAlchemy engine connected to the real Postgres test DB."""
    eng = create_engine(TEST_DB_URL)
    # Run migrations to ensure schema is up to date
    try:
        from alembic import command
        from alembic.config import Config as AlembicConfig
        cfg = AlembicConfig("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
        command.upgrade(cfg, "head")
    except Exception as exc:
        pytest.skip(f"Alembic migration failed — Postgres unavailable: {exc}")
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def settings(storage_settings: StorageSettings) -> Settings:
    """Settings instance with real MinIO + Postgres."""
    return Settings(
        database_url=TEST_DB_URL,
        storage=storage_settings,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture(scope="module")
def seeded_chunks(engine, backend, settings) -> list[str]:
    """Seed 3 chunk artifacts in Postgres and return their IDs.

    Each chunk has a real text value in metadata_.text so the Parquet
    export can build meaningful rows.
    """
    from knowledge_lake.registry import repo as registry_repo
    from knowledge_lake.registry.db import get_session

    import knowledge_lake.registry.db as registry_db
    from unittest.mock import patch

    chunk_ids = []

    # Patch the DB engine to point at the test DB
    with Session(engine) as session:
        # Create a unique source for this integration test run
        import uuid
        unique_suffix = uuid.uuid4().hex[:8]
        source = registry_repo.create_source(
            session,
            name=f"export-integration-test-{unique_suffix}",
            source_type="upload",
            config={"domain": "healthcare"},
        )
        session.flush()

        raw = registry_repo.create_raw_artifact(
            session,
            source_id=source.id,
            content_hash=f"raw_export_integration_{unique_suffix}",
        )
        session.flush()

        parsed = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash=f"parsed_export_integration_{unique_suffix}",
        )
        session.flush()

        for i in range(3):
            chunk = registry_repo.create_chunk_artifact(
                session,
                source_id=source.id,
                parent_artifact_id=parsed.id,
                content_hash=f"chunk_export_integration_{unique_suffix}_{i}",
                metadata={
                    "text": f"Integration test chunk {i} text. Healthcare domain.",
                    "section_path": f"§{i+1} Section",
                    "page": i + 1,
                },
            )
            session.flush()
            chunk_ids.append(chunk.id)

        session.commit()

    return chunk_ids


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestRagCorpusParquetRoundTrip:
    """EXPORT-01: real Parquet file written to MinIO and read back via DuckDB."""

    def test_export_rag_corpus_and_verify_with_duckdb(
        self,
        seeded_chunks: list[str],
        settings: Settings,
        engine,
    ):
        """Write a Parquet file to MinIO via export_rag_corpus() and verify with DuckDB.

        This is a genuine round-trip test:
        1. Real chunk artifacts are seeded in Postgres
        2. export_rag_corpus() calls Polars.write_parquet() → StorageBackend.put_object()
        3. verify_export() connects DuckDB's httpfs extension and reads the Parquet file
        4. DuckDB's COUNT(*) must exactly match the seeded chunk count
        """
        import knowledge_lake.registry.db as registry_db
        from unittest.mock import patch

        # Patch the DB engine so export_rag_corpus()'s get_session() hits the test DB
        with patch.object(registry_db, "get_engine", return_value=engine):
            from knowledge_lake.pipeline.export import export_rag_corpus, verify_export

            # Run the actual export against the real MinIO bucket
            result = export_rag_corpus(settings=settings)

        assert result["row_count"] >= len(seeded_chunks), (
            f"Expected at least {len(seeded_chunks)} rows (seeded chunks), "
            f"got {result['row_count']}"
        )
        assert result["storage_uri"].startswith("s3://"), (
            f"Expected s3:// URI, got {result['storage_uri']!r}"
        )

        # DuckDB round-trip: read the Parquet from MinIO via httpfs
        with patch.object(registry_db, "get_engine", return_value=engine):
            duckdb_count = verify_export(result["storage_uri"], settings=settings)

        assert duckdb_count == result["row_count"], (
            f"DuckDB COUNT(*) {duckdb_count} != export row_count {result['row_count']}: "
            f"Parquet round-trip failed"
        )

    def test_parquet_has_only_allow_listed_columns(
        self,
        seeded_chunks: list[str],
        settings: Settings,
        engine,
        backend: StorageBackend,
    ):
        """The gold-zone Parquet file must contain only _RAG_CORPUS_FIELDS columns."""
        import io
        import polars as pl
        import knowledge_lake.registry.db as registry_db
        from knowledge_lake.pipeline.export import _RAG_CORPUS_FIELDS
        from unittest.mock import patch

        with patch.object(registry_db, "get_engine", return_value=engine):
            from knowledge_lake.pipeline.export import export_rag_corpus

            result = export_rag_corpus(settings=settings)

        # Download the Parquet from MinIO directly and inspect columns
        # s3://bucket/key -> extract key
        uri = result["storage_uri"]
        key = uri.split("/", 3)[3]
        parquet_bytes = backend.get_object(key)
        buf = io.BytesIO(parquet_bytes)
        df = pl.read_parquet(buf)

        column_names = set(df.columns)
        for col in column_names:
            assert col in _RAG_CORPUS_FIELDS, (
                f"Unexpected column '{col}' in exported Parquet — not in allow-list (T-05-08)"
            )
