"""
Typed pydantic-settings configuration source for Knowledge Lake (FOUND-02).

Single source of truth for all environment/config. No other module in this
codebase should call os.getenv() or read environment variables directly.

Usage:
    from knowledge_lake.config.settings import get_settings
    s = get_settings()
    print(s.database_url)

Environment variable pattern:
    Prefix:            KLAKE_
    Nested delimiter:  __
    Example:           KLAKE_STORAGE__ENDPOINT_URL → settings.storage.endpoint_url
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageSettings(BaseSettings):
    """S3-compatible object storage configuration.

    Maps from KLAKE_STORAGE__* environment variables via env_nested_delimiter.
    Set endpoint_url to a MinIO address for dev; leave None for AWS S3 prod.
    """

    model_config = SettingsConfigDict(
        env_prefix="KLAKE_STORAGE__",
        extra="ignore",
    )

    endpoint_url: str | None = None
    """S3-compatible endpoint. None = use AWS S3; set to MinIO URL for dev."""

    bucket: str = "klake-data"
    """Target bucket name."""

    region: str = "us-east-1"
    """AWS region (used for presigned URLs and AWS S3 path-style requests)."""

    access_key_id: str | None = None
    """AWS access key ID or MinIO root user. None = use instance/env credentials."""

    secret_access_key: str | None = None
    """AWS secret access key or MinIO root password. None = use instance credentials."""


class Settings(BaseSettings):
    """Top-level application settings.

    All configuration is loaded from:
      1. Environment variables (highest precedence)
      2. .env file (if present)
      3. Defaults defined here

    Configuration keys use the KLAKE_ prefix. Nested models (storage) use
    the __ delimiter: KLAKE_STORAGE__ENDPOINT_URL maps to settings.storage.endpoint_url.
    """

    model_config = SettingsConfigDict(
        env_prefix="KLAKE_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Core service URLs ─────────────────────────────────────────────────────
    database_url: str = "postgresql+psycopg://klake:klake@localhost:5432/klake"
    """PostgreSQL connection string (SQLAlchemy async driver)."""

    qdrant_url: str = "http://localhost:6333"
    """Qdrant vector-store URL."""

    litellm_url: str = "http://localhost:4000"
    """LiteLLM proxy URL for all model calls."""

    # ── Plugin swap keys ──────────────────────────────────────────────────────
    embedder: str = "local"
    """Embedder plugin name. 'local' = sentence-transformers; 'litellm' = gateway."""

    parser: str = "docling"
    """Parser plugin name. 'docling' = Docling PDF/document parser."""

    vectorstore: str = "qdrant"
    """Vector-store plugin name. 'qdrant' = Qdrant client."""

    # ── Nested settings ───────────────────────────────────────────────────────
    storage: StorageSettings = Field(default_factory=StorageSettings)
    """S3-compatible object storage configuration."""

    def __init__(self, **data: Any) -> None:
        # If _env_file is explicitly passed as None (e.g. in tests), suppress .env loading.
        # pydantic-settings accepts _env_file as an init-time override.
        super().__init__(**data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached, validated Settings instance.

    Call this from anywhere in the application. Do not instantiate Settings
    directly — use this accessor so the app always reads from one validated source.
    """
    return Settings()
