"""
SQLAlchemy 2.0 declarative ORM models for the Knowledge Lake registry.

This module defines the core schema:
- Source            — origin of a document (URL, upload, crawler run)
- Artifact          — unified self-referencing lineage node (raw/parsed/chunk/enriched)
- LineageEvent      — explicit edge log for lineage tracing (FOUND-07)
- Job               — pipeline job placeholder (created empty in migration #1)
- CrawlState        — per-URL crawl state tracking (INGEST-04)
- LlmSpend          — accumulated LLM call cost per scope (ENRICH-05)
- VectorCollection  — alias-to-physical-collection registry (INDEX-02)
- Dataset           — curated dataset placeholder (created empty in migration #1)

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
    Float,
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

    crawl_schedule: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    """5-field UTC cron string (SCHED-01, D-02/D-03). NULL means source is not
    auto-recrawled."""

    last_crawled_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """UTC timestamp of the last re-crawl ATTEMPT (updated on skip and crawl
    alike, D-11)."""

    last_content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    """SHA256 over normalized silver-stage seed-page text (D-06/D-07). NULL means
    always crawl."""

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

    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    """LLM-judged quality score for enriched_document rows (Phase 4, ENRICH-05).

    Distinct per artifact_type — this is NOT the same value as Phase 3's
    heuristic parse-quality score, which remains stored in metadata_ JSON for
    parsed_document rows. The column itself was added physically to the
    artifacts table by migration 0006; this Phase 4 change only maps it as a
    real ORM attribute so enriched_document rows can be filtered/queried on it
    directly.
    """

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

    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    """Human-readable error message for failed/robots_blocked states (WR-03).

    Populated by the crawl orchestrator when SSRF guard, adapter error, or
    other failure occurs.  NULL for successful ('complete') states.
    """

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


class LlmSpend(Base):
    """Accumulated LLM call cost per scope, in USD (ENRICH-05).

    Gives the enrichment pipeline's budget cap (D-05) a concrete accounting
    mechanism. A single "global" scope row is acceptable for Phase 4 MVP per
    CONTEXT.md discretion; per-source/per-job scopes can be added later
    without a schema change since scope is just a string key.
    """

    __tablename__ = "llm_spend"
    __table_args__ = (
        UniqueConstraint("scope", name="uq_llm_spend_scope"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    """Prefixed UUIDv7 — always ``art_<uuidv7>`` (generic, not a lineage node)."""

    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    """Budget scope key, e.g. "global" — a single global budget scope is
    acceptable for Phase 4 MVP per CONTEXT.md discretion (ENRICH-05)."""

    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    """Cumulative LLM call cost in USD for this scope."""

    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    """UTC timestamp of the last spend update."""


class VectorCollection(Base):
    """Registry-queryable mapping of a stable alias to its current physical
    Qdrant collection (INDEX-02, D-06).

    Tracks which physical collection each alias currently resolves to,
    independent of Qdrant's own alias listing, so reindex/rollback logic can
    be audited and driven from the registry.
    """

    __tablename__ = "vector_collections"
    __table_args__ = (
        UniqueConstraint("physical_collection", name="uq_vector_collections_physical"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    """Prefixed UUIDv7 — always ``art_<uuidv7>`` (generic, not a lineage node)."""

    alias_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    """The stable alias every app call site uses, e.g. "klake_chunks" (D-06)."""

    physical_collection: Mapped[str] = mapped_column(String(128), nullable=False)
    """The versioned collection this alias currently points at, e.g.
    "klake_chunks_v1"."""

    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    """Embedding vector dimensionality of the physical collection."""

    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """Only one row per alias_name should have is_current=True at a time —
    reindex flips the old row to False and inserts a new True row."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    """UTC timestamp of registration."""


class Dataset(Base):
    """Curated dataset record — extended in Phase 5 with real columns (DATA-01..03).

    Originally a placeholder created in migration #1 (FOUND-05). Migration 0008
    adds dataset_type, format, example_count, storage_uri, and a UNIQUE
    constraint on name so get_or_create_dataset() is race-safe.
    """

    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("name", name="uq_datasets_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dataset_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    """Kind of dataset: 'rag_eval', 'instruction_tuning', 'pretraining', etc."""
    format: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    """Export format: 'jsonl', 'parquet', 'csv', etc. None until exported."""
    example_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    """Running count of examples in this dataset; updated on export."""
    storage_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    """S3 URI of the exported dataset file (gold zone). None until exported."""
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    examples: Mapped[list[DatasetExample]] = relationship(
        "DatasetExample",
        back_populates="dataset",
        foreign_keys="[DatasetExample.dataset_id]",
    )


class DatasetExample(Base):
    """Per-example lineage record for dataset generation (DATA-03, D-08).

    NOT a lineage-tree Artifact node — lives in its own join table so
    per-example provenance is queryable without exploding the artifacts table
    at QA-pair granularity (D-08: per-example Artifact granularity explicitly
    rejected). The nullable FK to artifacts.id (ondelete=SET NULL) means
    examples survive artifact deletion while the lineage reference becomes NULL.
    """

    __tablename__ = "dataset_examples"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    """Prefixed UUIDv7 — always ``dex_<uuidv7>``."""

    dataset_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """FK to the parent Dataset; CASCADE deletes all examples when dataset is deleted."""

    source_artifact_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("artifacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """FK to the source chunk (DATA-01) or enriched_document (DATA-02) artifact.
    Nullable (ondelete=SET NULL) so examples survive artifact deletion."""

    example_index: Mapped[int] = mapped_column(Integer, nullable=False)
    """Zero-based position of this example within its dataset."""

    payload: Mapped[Optional[Any]] = mapped_column(_JSON, nullable=True)
    """Validated LLM-generated example payload (QAPairResult or InstructionPairResult
    fields + _cache_key). For QA: question, answer, citation_chunk_id, _cache_key.
    For instruction: instruction, input, output, _cache_key."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    dataset: Mapped[Dataset] = relationship(
        "Dataset",
        back_populates="examples",
        foreign_keys=[dataset_id],
    )
