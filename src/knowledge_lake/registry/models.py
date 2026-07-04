"""
SQLAlchemy 2.0 declarative ORM models for the Knowledge Lake registry.

This module defines the core schema:
- Source          — origin of a document (URL, upload, crawler run)
- Artifact        — unified self-referencing lineage node (raw/parsed/chunk)
- LineageEvent    — explicit edge log for lineage tracing (FOUND-07)
- Job             — pipeline job placeholder (created empty in migration #1)
- Dataset         — curated dataset placeholder (created empty in migration #1)

Schema is managed EXCLUSIVELY by Alembic migrations.  This module defines the
Python-side model; ``Base.metadata.create_all()`` is NEVER called in production
code — only in tests running against ephemeral in-memory SQLite databases.

FOUND-06 fields on every artifact:
    source_id, parent_artifact_id, content_hash, pipeline_version,
    storage_uri, created_at
"""

from __future__ import annotations

import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

try:
    from sqlalchemy import JSON

    _JSON = JSON
except ImportError:
    from sqlalchemy import Text as _JSON  # type: ignore[assignment]


class Base(DeclarativeBase):
    """Shared declarative base; ``metadata`` is imported by Alembic env.py."""


class Source(Base):
    """Registry of document sources (FOUND-05).

    A source represents a logical origin: a website domain, an API endpoint,
    an S3 upload batch, etc.  All artifacts trace back to a source.
    """

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    """Prefixed UUIDv7 — always ``src_<uuidv7>``."""

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    """Human-readable name for the source."""

    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    """Kind of source: 'web', 'upload', 'api', 'crawler', etc."""

    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    """Canonical URL of the source (if applicable)."""

    normalized_url: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, index=True
    )
    """D-06 normalized URL for URL-first dedup (lowercase scheme+host, strip fragment/trailing slash)."""

    license_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    """SPDX license identifier or 'public_domain', 'proprietary', etc."""

    license_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    """URL to the license text."""

    robots_checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """Whether robots.txt was checked before crawling."""

    config: Mapped[Optional[Any]] = mapped_column(_JSON, nullable=True)
    """Arbitrary source configuration (crawl parameters, credentials refs, etc.)."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    """UTC timestamp of source registration."""

    # ── Relationships ─────────────────────────────────────────────────────────
    artifacts: Mapped[list[Artifact]] = relationship(
        "Artifact",
        back_populates="source",
        foreign_keys="[Artifact.source_id]",
    )


class Artifact(Base):
    """Unified self-referencing lineage node (FOUND-05, FOUND-06, FOUND-07).

    Every byte written to storage is paired with an Artifact node.  The
    ``artifact_type`` discriminates between raw_document, parsed_document,
    and chunk nodes.  The ``parent_artifact_id`` self-FK enables FOUND-07's
    recursive CTE ancestry walk.

    FOUND-06 fields (all non-null except parent_artifact_id for raw nodes):
        source_id, parent_artifact_id, content_hash, pipeline_version,
        storage_uri, created_at
    """

    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("content_hash", "artifact_type", name="uq_artifacts_hash_type"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    """Prefixed UUIDv7 — prefix encodes type (doc_, chk_, art_)."""

    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    """FK to the originating Source (FOUND-06)."""

    parent_artifact_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("artifacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """Self-FK to the parent node; NULL for raw documents (FOUND-06/07)."""

    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    """Discriminator: 'raw_document' | 'parsed_document' | 'chunk'."""

    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    """SHA256 of the content bytes (FOUND-06, content-addressable storage)."""

    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=False)
    """Package version + git SHA that produced this artifact (D-04, FOUND-06)."""

    storage_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    """S3-compatible URI: s3://bucket/zone/key (FOUND-06)."""

    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    """MIME type of the content (application/pdf, application/json, etc.)."""

    page_ref: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    """Source page number (for parsed/chunk nodes — citation, D-07)."""

    section_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    """Heading path within the document (citation, D-07/D-14)."""

    metadata_: Mapped[Optional[Any]] = mapped_column(
        "metadata",
        _JSON,
        nullable=True,
        default=dict,
    )
    """Arbitrary extra metadata."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    """UTC timestamp of artifact creation (FOUND-06)."""

    # ── Relationships ─────────────────────────────────────────────────────────
    source: Mapped[Source] = relationship(
        "Source",
        back_populates="artifacts",
        foreign_keys=[source_id],
    )

    parent: Mapped[Optional[Artifact]] = relationship(
        "Artifact",
        back_populates="children",
        foreign_keys=[parent_artifact_id],
        remote_side="Artifact.id",
    )

    children: Mapped[list[Artifact]] = relationship(
        "Artifact",
        back_populates="parent",
        foreign_keys=[parent_artifact_id],
    )

    lineage_events: Mapped[list[LineageEvent]] = relationship(
        "LineageEvent",
        back_populates="artifact",
        foreign_keys="[LineageEvent.artifact_id]",
    )


class LineageEvent(Base):
    """Explicit lineage edge log (FOUND-05, FOUND-07).

    Records every transformation relationship between artifact nodes.
    Complements the implicit tree from parent_artifact_id with explicit
    labelled edges for audit and replay.
    """

    __tablename__ = "lineage_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    """Prefixed UUIDv7."""

    artifact_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """FK to the output artifact (the one this event produced)."""

    parent_artifact_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("artifacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """FK to the input artifact (source of the transformation); NULL for ingest events."""

    edge_type: Mapped[str] = mapped_column(
        "relationship", String(64), nullable=False
    )
    """Named relationship: 'ingested_from', 'parsed_from', 'chunked_from', etc."""

    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=False)
    """Version of the pipeline that produced this edge."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    artifact: Mapped[Artifact] = relationship(
        "Artifact",
        back_populates="lineage_events",
        foreign_keys=[artifact_id],
    )


class Job(Base):
    """Pipeline job record (FOUND-05, INGEST-04).

    Extended in Phase 2 with source_id, job_type, crawler, config, stats,
    and updated_at to support crawl job tracking.
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    source_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    """FK to the source being crawled (nullable for legacy jobs)."""

    job_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="crawl"
    )
    """Job type discriminator (default 'crawl')."""

    crawler: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    """Name of the crawler adapter that owns this job."""

    config: Mapped[Optional[Any]] = mapped_column(_JSON, nullable=True)
    """Job-specific configuration (max_pages, max_depth, etc.)."""

    stats: Mapped[Optional[Any]] = mapped_column(_JSON, nullable=True)
    """Job statistics (pages_fetched, errors, duration, etc.)."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    """Timestamp of last status update."""


class CrawlState(Base):
    """Per-URL crawl state tracking (INGEST-04, T-02-05).

    Records the crawl status of each URL within a job. The UNIQUE constraint
    on (job_id, normalized_url) — NOT on content_hash — prevents duplicate
    processing of the same URL within a job while allowing identical content
    under different URLs to have separate state rows (Pitfall 4).
    """

    __tablename__ = "crawl_states"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "normalized_url", name="uq_crawl_states_job_url"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    """Prefixed UUIDv7 — always 'cst_<uuidv7>'."""

    job_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    """FK to the parent crawl job."""

    url: Mapped[str] = mapped_column(Text, nullable=False)
    """Original URL as discovered during the crawl."""

    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    """Normalized URL for dedup within the job (lowercase host, strip fragment)."""

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    """Page-level status: 'pending', 'complete', 'failed', 'robots_blocked'."""

    raw_artifact_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    """FK to the raw artifact created from this page (NULL until fetched)."""

    bronze_artifact_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    """FK to the bronze artifact (markdown/processed) from this page."""

    fetched_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    """UTC timestamp of when this URL was successfully fetched."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Dataset(Base):
    """Curated dataset record — created empty in migration #1 (FOUND-05).

    Exercised in Phase 5 when curated exports are registered.
    """

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
