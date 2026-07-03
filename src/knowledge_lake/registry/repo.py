"""
Repository layer for the Knowledge Lake registry (FOUND-05, FOUND-06).

All registry writes and reads go through these functions.  No raw SQL strings
are used — every query is expressed via the SQLAlchemy ORM to satisfy
threat T-01-03 (injection prevention).

Functions:
    create_source             — register a new source
    create_raw_artifact       — persist a raw document node
    create_parsed_artifact    — persist a parsed document node
    create_chunk_artifact     — persist a chunk node
    get_artifact_by_hash      — dedup lookup used by storage.put_raw (FOUND-04)
    get_artifact              — fetch by primary key
    list_children             — list direct children of an artifact
"""

from __future__ import annotations

import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from knowledge_lake.ids import new_id
from knowledge_lake.version import pipeline_version
from knowledge_lake.registry.models import Artifact, LineageEvent, Source


# ── Source ────────────────────────────────────────────────────────────────────


def create_source(
    session: Session,
    *,
    name: str,
    source_type: str,
    url: Optional[str] = None,
    normalized_url: Optional[str] = None,
    license_type: Optional[str] = None,
    license_url: Optional[str] = None,
    robots_checked: bool = False,
    config: Optional[Any] = None,
) -> Source:
    """Register a new source and add it to the session.

    The caller is responsible for committing or flushing the session.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    name:
        Human-readable name for this source.
    source_type:
        Kind of source (e.g. 'web', 'upload', 'api').
    url:
        Canonical URL of the source, if applicable.
    normalized_url:
        D-06 normalized URL for URL-first dedup lookup.
    license_type:
        SPDX identifier or 'public_domain'.
    license_url:
        URL to the full license text.
    robots_checked:
        Whether robots.txt was checked before crawling.
    config:
        Arbitrary JSON-serialisable configuration dict.

    Returns
    -------
    Source
        The newly created (unsaved) Source instance.
    """
    source = Source(
        id=new_id("source"),
        name=name,
        source_type=source_type,
        url=url,
        normalized_url=normalized_url,
        license_type=license_type,
        license_url=license_url,
        robots_checked=robots_checked,
        config=config,
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )
    session.add(source)
    return source


# ── Artifact helpers ──────────────────────────────────────────────────────────


def _make_artifact(
    kind: str,
    source_id: str,
    artifact_type: str,
    content_hash: str,
    storage_uri: Optional[str],
    parent_artifact_id: Optional[str] = None,
    mime_type: Optional[str] = None,
    page_ref: Optional[int] = None,
    section_path: Optional[str] = None,
    metadata: Optional[Any] = None,
) -> Artifact:
    """Internal: construct an Artifact with all FOUND-06 fields stamped."""
    return Artifact(
        id=new_id(kind),
        source_id=source_id,
        parent_artifact_id=parent_artifact_id,
        artifact_type=artifact_type,
        content_hash=content_hash,
        pipeline_version=pipeline_version(),
        storage_uri=storage_uri,
        mime_type=mime_type,
        page_ref=page_ref,
        section_path=section_path,
        metadata_=metadata or {},
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )


# ── Raw document ──────────────────────────────────────────────────────────────


def create_raw_artifact(
    session: Session,
    *,
    source_id: str,
    content_hash: str,
    storage_uri: Optional[str] = None,
    mime_type: Optional[str] = None,
    metadata: Optional[Any] = None,
) -> Artifact:
    """Persist a raw document artifact node (FOUND-06).

    ``parent_artifact_id`` is NULL for raw nodes — they are the root of the
    lineage tree.

    Stamps ``pipeline_version`` and generates a ``doc_``-prefixed UUIDv7 ID.
    """
    art = _make_artifact(
        kind="raw_document",
        source_id=source_id,
        artifact_type="raw_document",
        content_hash=content_hash,
        storage_uri=storage_uri,
        parent_artifact_id=None,   # raw documents have no parent
        mime_type=mime_type,
        metadata=metadata,
    )
    session.add(art)
    return art


# ── Parsed document ───────────────────────────────────────────────────────────


def create_parsed_artifact(
    session: Session,
    *,
    source_id: str,
    parent_artifact_id: str,
    content_hash: str,
    storage_uri: Optional[str] = None,
    mime_type: Optional[str] = None,
    metadata: Optional[Any] = None,
) -> Artifact:
    """Persist a parsed document artifact node.

    ``parent_artifact_id`` must point to the raw document from which this was
    parsed — it is required, not optional, for parsed nodes.
    """
    art = _make_artifact(
        kind="parsed_document",
        source_id=source_id,
        artifact_type="parsed_document",
        content_hash=content_hash,
        storage_uri=storage_uri,
        parent_artifact_id=parent_artifact_id,
        mime_type=mime_type,
        metadata=metadata,
    )
    session.add(art)
    return art


# ── Chunk ─────────────────────────────────────────────────────────────────────


def create_chunk_artifact(
    session: Session,
    *,
    source_id: str,
    parent_artifact_id: str,
    content_hash: str,
    storage_uri: Optional[str] = None,
    mime_type: Optional[str] = None,
    page_ref: Optional[int] = None,
    section_path: Optional[str] = None,
    metadata: Optional[Any] = None,
) -> Artifact:
    """Persist a chunk artifact node.

    ``parent_artifact_id`` must point to the parsed document from which this
    chunk was extracted.
    """
    art = _make_artifact(
        kind="chunk",
        source_id=source_id,
        artifact_type="chunk",
        content_hash=content_hash,
        storage_uri=storage_uri,
        parent_artifact_id=parent_artifact_id,
        mime_type=mime_type,
        page_ref=page_ref,
        section_path=section_path,
        metadata=metadata,
    )
    session.add(art)
    return art


# ── Lookups ───────────────────────────────────────────────────────────────────


def get_artifact_by_hash(
    session: Session,
    content_hash: str,
    artifact_type: str,
) -> Optional[Artifact]:
    """Return the artifact matching ``(content_hash, artifact_type)`` or None.

    This is the FOUND-04 dedup lookup: called by ``storage.put_raw`` before
    writing to S3 to make re-ingesting identical content a registry-level no-op.

    Uses the UNIQUE(content_hash, artifact_type) index for O(1) lookup.
    No raw SQL — ORM select with parameterized WHERE clause (T-01-03).
    """
    stmt = (
        select(Artifact)
        .where(Artifact.content_hash == content_hash)
        .where(Artifact.artifact_type == artifact_type)
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def get_artifact(session: Session, artifact_id: str) -> Optional[Artifact]:
    """Fetch an artifact by its primary key.

    Returns None if not found (does not raise).
    """
    return session.get(Artifact, artifact_id)


def list_children(session: Session, artifact_id: str) -> list[Artifact]:
    """Return direct children of the given artifact node.

    Children are artifacts whose ``parent_artifact_id`` equals ``artifact_id``.
    Used by the lineage tree renderer (D-14) to display the forward-direction
    of the DAG.
    """
    stmt = (
        select(Artifact)
        .where(Artifact.parent_artifact_id == artifact_id)
        .order_by(Artifact.created_at)
    )
    return list(session.execute(stmt).scalars())


# ── Dedup lookups (D-05, D-07, INGEST-08) ───────────────────────────────────


def get_source_by_normalized_url(
    session: Session,
    normalized_url: str,
) -> Optional[Source]:
    """Return the source matching a normalized URL, or None.

    This is the URL-first dedup lookup (D-05): called by register_source()
    before creating a new source row.  Uses the ix_sources_normalized_url
    index.  No raw SQL — ORM select (T-02-02).
    """
    stmt = (
        select(Source)
        .where(Source.normalized_url == normalized_url)
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def get_raw_artifact_for_source(
    session: Session,
    source_id: str,
) -> Optional[Artifact]:
    """Return the raw_document artifact owned by the given source, or None.

    Used by ingest_url when URL-first dedup hits: the existing source_id is known,
    so we fetch its raw artifact to return the same IDs (D-07 silent success).
    No raw SQL — ORM select (T-02-02).
    """
    stmt = (
        select(Artifact)
        .where(Artifact.source_id == source_id)
        .where(Artifact.artifact_type == "raw_document")
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()
