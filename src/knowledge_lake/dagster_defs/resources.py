"""Dagster ConfigurableResources for the Knowledge Lake pipeline (D-01, Pitfall 14).

Each resource reads connection config via Dagster's EnvVar mechanism so that:
  - No URLs or credentials are hardcoded (Pitfall 14)
  - The same resource class works in dev (localhost) and prod (container DNS)
  - Config is visible and declarative in the Dagster UI

Resources defined here:
  PostgresResource  — SQLAlchemy database URL for the registry
  MinIOResource     — S3-compatible storage (endpoint + credentials)
  QdrantResource    — Qdrant vector-store URL
  LiteLLMResource   — LiteLLM proxy URL (model gateway)

Usage in definitions.py:
    from knowledge_lake.dagster_defs.resources import (
        PostgresResource, MinIOResource, QdrantResource, LiteLLMResource
    )
    defs = Definitions(
        assets=[...],
        resources={
            "postgres": PostgresResource(database_url=EnvVar("KLAKE_DATABASE_URL")),
            "minio": MinIOResource(
                endpoint_url=EnvVar("KLAKE_STORAGE__ENDPOINT_URL"),
                bucket=EnvVar("KLAKE_STORAGE__BUCKET"),
                access_key_id=EnvVar("KLAKE_STORAGE__ACCESS_KEY_ID"),
                secret_access_key=EnvVar("KLAKE_STORAGE__SECRET_ACCESS_KEY"),
            ),
            "qdrant": QdrantResource(qdrant_url=EnvVar("KLAKE_QDRANT_URL")),
            "litellm": LiteLLMResource(litellm_url=EnvVar("KLAKE_LITELLM_URL")),
        },
    )

Note: Assets call StorageBackend and registry functions explicitly — they do NOT
use these resources as IO managers for object bytes (Pitfall 7). Resources here
provide connection configuration only; they are passed as typed parameters to
asset functions which build the appropriate client objects from them.
"""

from __future__ import annotations

from dagster import ConfigurableResource
from pydantic import Field


class PostgresResource(ConfigurableResource):
    """PostgreSQL registry connection resource.

    Provides the database URL for the Knowledge Lake artifact/source registry.
    Assets use this to obtain a SQLAlchemy session via knowledge_lake.registry.db.

    Config var: KLAKE_DATABASE_URL
    Default:    postgresql+psycopg://klake:klake@localhost:5432/klake
    """

    database_url: str = Field(
        default="postgresql+psycopg://klake:klake@localhost:5432/klake",
        description=(
            "SQLAlchemy database URL for the Knowledge Lake registry. "
            "Set via KLAKE_DATABASE_URL env var."
        ),
    )


class MinIOResource(ConfigurableResource):
    """S3-compatible (MinIO / AWS S3) object-storage resource.

    Provides credentials and endpoint configuration for the boto3 client
    used by StorageBackend. In dev, ``endpoint_url`` points at MinIO.
    In prod (AWS S3), ``endpoint_url`` is None/empty and boto3 uses the default AWS endpoint.

    Config vars: KLAKE_STORAGE__ENDPOINT_URL, KLAKE_STORAGE__BUCKET,
                 KLAKE_STORAGE__ACCESS_KEY_ID, KLAKE_STORAGE__SECRET_ACCESS_KEY
    """

    endpoint_url: str | None = Field(
        default=None,
        description=(
            "S3-compatible endpoint URL. Set to MinIO address for dev, "
            "leave empty for AWS S3 prod."
        ),
    )
    bucket: str = Field(
        default="klake-data",
        description="Target S3 bucket name.",
    )
    access_key_id: str | None = Field(
        default=None,
        description="AWS/MinIO access key ID.",
    )
    secret_access_key: str | None = Field(
        default=None,
        description="AWS/MinIO secret access key.",
    )
    region: str = Field(
        default="us-east-1",
        description="AWS region for S3 requests.",
    )


class QdrantResource(ConfigurableResource):
    """Qdrant vector-store connection resource.

    Assets call the VectorStorePlugin (resolved via settings) directly;
    this resource provides the URL used to build the Qdrant settings override.

    Config var: KLAKE_QDRANT_URL
    Default:    http://localhost:6333
    """

    qdrant_url: str = Field(
        default="http://localhost:6333",
        description=(
            "Qdrant server URL. Set via KLAKE_QDRANT_URL env var."
        ),
    )


class LiteLLMResource(ConfigurableResource):
    """LiteLLM proxy gateway connection resource.

    All model calls in the pipeline go through LiteLLM (CLAUDE.md constraint).
    This resource captures the proxy URL so the Dagster execution path uses the
    same gateway configuration as the CLI/API path.

    Config var: KLAKE_LITELLM_URL
    Default:    http://localhost:4000
    """

    litellm_url: str = Field(
        default="http://localhost:4000",
        description=(
            "LiteLLM proxy URL. Set via KLAKE_LITELLM_URL env var."
        ),
    )
