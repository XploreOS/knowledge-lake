"""
Repository layer for the Knowledge Lake registry (FOUND-05, FOUND-06).

All registry writes and reads go through these functions.  No raw SQL strings
are used — every query is expressed via the SQLAlchemy ORM to satisfy
threat T-01-03 (injection prevention).

Functions:
    create_source                   — register a new source
    create_raw_artifact             — persist a raw document node
    create_parsed_artifact          — persist a parsed document node
    create_cleaned_artifact         — persist a cleaned document node (CLEAN-01..03)
    create_chunk_artifact           — persist a chunk node
    get_artifact_by_hash            — dedup lookup used by storage.put_raw (FOUND-04)
    get_artifact                    — fetch by primary key
    list_children                   — list direct children of an artifact
    list_cleaned_artifacts          — list all cleaned_document artifacts (near-dup scan)
    create_enriched_artifact        — persist an enriched document node (ENRICH-01..05)
    get_llm_spend                   — read accumulated LLM spend for a scope (ENRICH-05)
    record_llm_spend                — accumulate LLM spend for a scope (ENRICH-05)
    get_enriched_artifact_for_parsed — resolve parsed -> cleaned -> enriched (D-01)
    get_domain_for_source           — read domain from Source.config JSON
    register_vector_collection      — register/flip current physical collection for an alias (INDEX-02)
    get_current_vector_collection   — read the current physical collection for an alias (INDEX-02)
"""

from __future__ import annotations

import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from knowledge_lake.ids import new_id
from knowledge_lake.version import pipeline_version
from knowledge_lake.registry.models import (
    Artifact,
    CrawlState,
    Job,
    LineageEvent,
    LlmSpend,
    Source,
    VectorCollection,
)


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


# ── Cleaned document ──────────────────────────────────────────────────────────


def create_cleaned_artifact(
    session: Session,
    *,
    source_id: str,
    parent_artifact_id: str,
    content_hash: str,
    storage_uri: Optional[str] = None,
    mime_type: Optional[str] = None,
    metadata: Optional[Any] = None,
) -> Artifact:
    """Persist a cleaned document artifact (CLEAN-01..03).

    Parent is the parsed_document artifact. ``metadata`` carries language,
    dedup_status, and minhash_num_perm keys.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    source_id:
        FK to the source this document belongs to.
    parent_artifact_id:
        ID of the parsed_document artifact this was cleaned from (required).
    content_hash:
        SHA256 of cleaned text bytes for exact-dedup lookup.
    storage_uri:
        S3 URI of the cleaned markdown in the silver zone.
    mime_type:
        MIME type of the stored artifact (typically 'text/markdown').
    metadata:
        JSON dict with language, dedup_status, minhash_num_perm keys.

    Returns
    -------
    Artifact
        The newly created (unsaved) Artifact instance.
    """
    art = _make_artifact(
        kind="cleaned_document",
        source_id=source_id,
        artifact_type="cleaned_document",
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


# ── Bronze document ─────────────────────────────────────────────────────────


def create_bronze_artifact(
    session: Session,
    *,
    source_id: str,
    content_hash: str,
    storage_uri: Optional[str] = None,
    parent_artifact_id: str,
    mime_type: Optional[str] = None,
    metadata: Optional[Any] = None,
) -> Artifact:
    """Persist a bronze document artifact node (D-01, INGEST-04).

    ``parent_artifact_id`` is REQUIRED for bronze nodes — they derive from
    a raw document (D-01 two-artifact lineage: raw -> bronze).

    Stamps ``pipeline_version`` and generates a ``doc_``-prefixed UUIDv7 ID.
    """
    art = _make_artifact(
        kind="bronze_document",
        source_id=source_id,
        artifact_type="bronze_document",
        content_hash=content_hash,
        storage_uri=storage_uri,
        parent_artifact_id=parent_artifact_id,
        mime_type=mime_type,
        metadata=metadata,
    )
    session.add(art)
    return art


# ── Crawl job / state ────────────────────────────────────────────────────────


def create_crawl_job(
    session: Session,
    *,
    source_id: Optional[str] = None,
    crawler: Optional[str] = None,
    config: Optional[Any] = None,
    status: str = "pending",
) -> Job:
    """Create a crawl job record.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    source_id:
        FK to the source being crawled.
    crawler:
        Name of the crawler adapter (e.g. 'crawl4ai').
    config:
        Job-specific configuration dict.
    status:
        Initial status (default 'pending').

    Returns
    -------
    Job
        The newly created Job instance.
    """
    job = Job(
        id=new_id("crawl_job"),
        source_id=source_id,
        job_type="crawl",
        crawler=crawler,
        config=config,
        status=status,
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )
    session.add(job)
    return job


def upsert_crawl_state(
    session: Session,
    *,
    job_id: str,
    url: str,
    normalized_url: str,
    status: str = "pending",
    raw_artifact_id: Optional[str] = None,
    bronze_artifact_id: Optional[str] = None,
    fetched_at: Optional[datetime.datetime] = None,
    error_msg: Optional[str] = None,
) -> CrawlState:
    """Insert or update a crawl state row (keyed on job_id + normalized_url).

    If a row with (job_id, normalized_url) already exists, updates its status,
    artifact IDs, fetched_at, and error_msg. Otherwise, creates a new row.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    job_id:
        FK to the parent crawl job.
    url:
        Original URL as discovered.
    normalized_url:
        Normalized URL for dedup within the job.
    status:
        Page-level status.
    raw_artifact_id:
        FK to the raw artifact (set after fetch).
    bronze_artifact_id:
        FK to the bronze artifact (set after processing).
    fetched_at:
        Timestamp of fetch completion.
    error_msg:
        Human-readable failure reason for 'failed'/'robots_blocked' states (WR-03).

    Returns
    -------
    CrawlState
        The created or updated CrawlState instance.
    """
    # Check if state already exists for this (job_id, normalized_url)
    stmt = (
        select(CrawlState)
        .where(CrawlState.job_id == job_id)
        .where(CrawlState.normalized_url == normalized_url)
        .limit(1)
    )
    existing = session.execute(stmt).scalar_one_or_none()

    if existing is not None:
        existing.status = status
        if raw_artifact_id is not None:
            existing.raw_artifact_id = raw_artifact_id
        if bronze_artifact_id is not None:
            existing.bronze_artifact_id = bronze_artifact_id
        if fetched_at is not None:
            existing.fetched_at = fetched_at
        existing.error_msg = error_msg  # always update (clears error on retry success)
        return existing

    state = CrawlState(
        id=new_id("crawl_state"),
        job_id=job_id,
        url=url,
        normalized_url=normalized_url,
        status=status,
        raw_artifact_id=raw_artifact_id,
        bronze_artifact_id=bronze_artifact_id,
        fetched_at=fetched_at,
        error_msg=error_msg,
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )
    session.add(state)
    return state


def pending_states(session: Session, job_id: str) -> list[CrawlState]:
    """Return all crawl states with status 'pending' for a given job.

    Used by the crawl orchestrator to resume interrupted crawls — fetches
    only URLs that haven't been processed yet.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    job_id:
        The crawl job ID to query.

    Returns
    -------
    list[CrawlState]
        CrawlState rows with status == 'pending', ordered by created_at.
    """
    stmt = (
        select(CrawlState)
        .where(CrawlState.job_id == job_id)
        .where(CrawlState.status == "pending")
        .order_by(CrawlState.created_at)
    )
    return list(session.execute(stmt).scalars())


def list_sources_by_type(
    session: Session,
    source_type: str,
) -> list[Source]:
    """Return all sources matching the given source_type.

    Used by discover_sources to list discovered candidates for review.
    ORM-only query (T-02-02: no raw SQL).

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    source_type:
        The source type to filter by (e.g. 'discovered', 'web', 'upload').

    Returns
    -------
    list[Source]
        Source rows matching the type, ordered by created_at descending.
    """
    stmt = (
        select(Source)
        .where(Source.source_type == source_type)
        .order_by(Source.created_at.desc())
    )
    return list(session.execute(stmt).scalars())


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


def list_cleaned_artifacts(session: Session) -> list[Artifact]:
    """Return all cleaned_document artifacts ordered by created_at.

    Used by clean() to build the transient MinHash LSH for near-duplicate
    detection (CLEAN-03). This is O(n) per clean() call — acceptable for
    Phase 3 MVP corpus sizes (< 10,000 documents).

    No raw SQL — ORM select (T-01-03).
    """
    stmt = (
        select(Artifact)
        .where(Artifact.artifact_type == "cleaned_document")
        .order_by(Artifact.created_at)
    )
    return list(session.execute(stmt).scalars())


# ── Enriched document (ENRICH-01..05) ────────────────────────────────────────


def create_enriched_artifact(
    session: Session,
    *,
    source_id: str,
    parent_artifact_id: str,
    content_hash: str,
    metadata: Optional[Any] = None,
    quality_score: Optional[float] = None,
) -> Artifact:
    """Persist an enriched document artifact node (ENRICH-01..05).

    ``parent_artifact_id`` MUST point to the cleaned_document artifact
    (D-01), never parsed_document — enrichment always parents off the
    cleaned text, not the raw parsed output.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    source_id:
        FK to the source this document belongs to.
    parent_artifact_id:
        ID of the cleaned_document artifact this was enriched from (required).
    content_hash:
        SHA256 of the enriched content/metadata bytes.
    metadata:
        JSON dict carrying the LLM-generated enrichment metadata.
    quality_score:
        LLM-judged quality score for this enriched document (Phase 4).

    Returns
    -------
    Artifact
        The newly created (unsaved) Artifact instance.
    """
    art = _make_artifact(
        kind="enriched_document",
        source_id=source_id,
        artifact_type="enriched_document",
        content_hash=content_hash,
        storage_uri=None,
        parent_artifact_id=parent_artifact_id,
        metadata=metadata,
    )
    art.quality_score = quality_score
    session.add(art)
    return art


# ── LLM spend accounting (ENRICH-05) ─────────────────────────────────────────


def get_llm_spend(session: Session, scope: str = "global") -> float:
    """Return accumulated LLM spend in USD for the given scope.

    Returns 0.0 if no spend has been recorded yet for this scope (ENRICH-05).
    """
    stmt = select(LlmSpend).where(LlmSpend.scope == scope).limit(1)
    row = session.execute(stmt).scalar_one_or_none()
    return row.total_cost_usd if row is not None else 0.0


def record_llm_spend(session: Session, scope: str, cost_usd: float) -> LlmSpend:
    """Accumulate LLM call cost in USD for the given scope (ENRICH-05).

    Get-or-create pattern mirroring ``upsert_crawl_state``: if a row for
    ``scope`` already exists, its ``total_cost_usd`` is incremented in place;
    otherwise a new row is created. The UNIQUE(scope) constraint on
    ``llm_spend`` prevents duplicate scope rows from ever being created.
    """
    stmt = select(LlmSpend).where(LlmSpend.scope == scope).limit(1)
    existing = session.execute(stmt).scalar_one_or_none()

    if existing is not None:
        existing.total_cost_usd += cost_usd
        return existing

    spend = LlmSpend(
        id=new_id("artifact"),
        scope=scope,
        total_cost_usd=cost_usd,
        updated_at=datetime.datetime.now(datetime.timezone.utc),
    )
    session.add(spend)
    return spend


def get_enriched_artifact_for_parsed(
    session: Session,
    parsed_artifact_id: str,
) -> Optional[Artifact]:
    """Resolve the enriched_document artifact two hops below a parsed_document.

    Walks parsed_document -> cleaned_document -> enriched_document, bridging
    parsed_artifact_id-keyed index() calls to enrichment, which parents off
    cleaned_document per D-01. Returns None if no cleaned_document child
    exists yet, or if the cleaned_document has no enriched_document child yet.
    """
    cleaned = next(
        (
            child
            for child in list_children(session, parsed_artifact_id)
            if child.artifact_type == "cleaned_document"
        ),
        None,
    )
    if cleaned is None:
        return None

    enriched = next(
        (
            child
            for child in list_children(session, cleaned.id)
            if child.artifact_type == "enriched_document"
        ),
        None,
    )
    return enriched


def get_domain_for_source(session: Session, source_id: str) -> Optional[str]:
    """Return the domain classification stored in Source.config, or None.

    RESEARCH.md Pitfall 4: domain is never a dedicated column, always stored
    under Source.config["domain"] (see pipeline/ingest.py's register_source).
    Returns None if the source is missing or has no config.
    """
    source = session.get(Source, source_id)
    if source is None or not source.config:
        return None
    return source.config.get("domain")


# ── Vector collection alias registry (INDEX-02, D-06) ───────────────────────


def register_vector_collection(
    session: Session,
    *,
    alias_name: str,
    physical_collection: str,
    dim: int,
) -> VectorCollection:
    """Register a physical collection as the new current target for an alias.

    Any existing rows for ``alias_name`` with ``is_current=True`` are flipped
    to ``is_current=False`` before the new row is inserted, so only one row
    per alias_name is ever current at a time (D-06 zero-downtime reindex).
    """
    stmt = (
        select(VectorCollection)
        .where(VectorCollection.alias_name == alias_name)
        .where(VectorCollection.is_current == True)  # noqa: E712
    )
    for existing in session.execute(stmt).scalars():
        existing.is_current = False

    collection = VectorCollection(
        id=new_id("artifact"),
        alias_name=alias_name,
        physical_collection=physical_collection,
        dim=dim,
        is_current=True,
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )
    session.add(collection)
    return collection


def get_current_vector_collection(
    session: Session,
    alias_name: str,
) -> Optional[VectorCollection]:
    """Return the current physical collection row for the given alias, or None."""
    stmt = (
        select(VectorCollection)
        .where(VectorCollection.alias_name == alias_name)
        .where(VectorCollection.is_current == True)  # noqa: E712
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()
