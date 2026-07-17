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
    get_curated_artifact_for_parsed — resolve parsed -> cleaned -> curated (KL-04/05/06)
    get_domain_for_source           — read domain from Source.config JSON
    get_source_crawl_config         — read crawl_config sub-dict from Source.config (CRAWL-01, D-01, D-05)
    list_sources_for_crawl_all      — list all sources, optionally filtered by domain (CRAWL-02)
    register_vector_collection      — register/flip current physical collection for an alias (INDEX-02)
    get_current_vector_collection   — read the current physical collection for an alias (INDEX-02)
    claim_dedup_ledger_entry        — atomically claim (collection, text_sha256) or return existing (DEDUP-01/02)
    get_dedup_ledger_entry          — pure lookup of a dedup ledger row (DEDUP-01)
    append_dedup_contributor        — append a contributor to a ledger row's contributors list (DEDUP-03)
"""

from __future__ import annotations

import datetime
from collections import namedtuple
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from knowledge_lake.ids import new_id
from knowledge_lake.registry.models import (
    Artifact,
    ChunkDedupLedger,
    CrawlState,
    Dataset,
    DatasetExample,
    Job,
    LlmSpend,
    Source,
    VectorCollection,
)
from knowledge_lake.version import pipeline_version

# ── Source ────────────────────────────────────────────────────────────────────


def create_source(
    session: Session,
    *,
    name: str,
    source_type: str,
    url: str | None = None,
    normalized_url: str | None = None,
    license_type: str | None = None,
    license_url: str | None = None,
    robots_checked: bool = False,
    config: Any | None = None,
    crawl_schedule: str | None = None,
    domain: str | None = None,
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
        Arbitrary JSON-serialisable configuration dict. Callers that also pass
        ``domain=`` are expected to keep ``config["domain"]`` in sync themselves
        during the KL-15 dual-write deprecation window — this function does not
        derive one from the other.
    crawl_schedule:
        5-field UTC cron string (SCHED-01). None means not auto-recrawled.
    domain:
        First-class domain classification (KL-15), written to the indexed
        ``sources.domain`` column. Callers should also set
        ``config["domain"]`` to the same value during the dual-write window
        (see ``registry/models.py``'s ``Source.domain`` docstring).

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
        crawl_schedule=crawl_schedule,
        domain=domain,
        created_at=datetime.datetime.now(datetime.UTC),
    )
    session.add(source)
    return source


# ── Artifact helpers ──────────────────────────────────────────────────────────


def _make_artifact(
    kind: str,
    source_id: str,
    artifact_type: str,
    content_hash: str,
    storage_uri: str | None,
    parent_artifact_id: str | None = None,
    mime_type: str | None = None,
    page_ref: int | None = None,
    section_path: str | None = None,
    metadata: Any | None = None,
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
        created_at=datetime.datetime.now(datetime.UTC),
    )


# ── Raw document ──────────────────────────────────────────────────────────────


def create_raw_artifact(
    session: Session,
    *,
    source_id: str,
    content_hash: str,
    storage_uri: str | None = None,
    mime_type: str | None = None,
    metadata: Any | None = None,
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
    storage_uri: str | None = None,
    mime_type: str | None = None,
    metadata: Any | None = None,
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
    storage_uri: str | None = None,
    mime_type: str | None = None,
    metadata: Any | None = None,
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
    storage_uri: str | None = None,
    mime_type: str | None = None,
    page_ref: int | None = None,
    section_path: str | None = None,
    metadata: Any | None = None,
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


# ── Tree index ────────────────────────────────────────────────────────────────


def create_tree_index_artifact(
    session: Session,
    *,
    source_id: str,
    parent_artifact_id: str,
    content_hash: str,
    storage_uri: str | None = None,
    mime_type: str | None = "application/json",
    metadata: Any | None = None,
) -> Artifact:
    """Persist a tree_index artifact node with full lineage.

    ``parent_artifact_id`` must be the parsed_document artifact ID (D-07
    lineage).  Zero Alembic migration required — artifact_type is a free-form
    String.

    Stamps ``pipeline_version`` and generates an ``idx_``-prefixed UUIDv7 ID
    (requires ``ids._PREFIX["tree_index"] = "idx"`` — added in Plan 13-02).
    """
    art = _make_artifact(
        kind="tree_index",
        source_id=source_id,
        artifact_type="tree_index",
        content_hash=content_hash,
        storage_uri=storage_uri,
        parent_artifact_id=parent_artifact_id,
        mime_type=mime_type,
        metadata=metadata,
    )
    session.add(art)
    return art


# ── Lookups ───────────────────────────────────────────────────────────────────


def get_artifact_by_hash(
    session: Session,
    content_hash: str,
    artifact_type: str,
) -> Artifact | None:
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


def get_artifact(session: Session, artifact_id: str) -> Artifact | None:
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
) -> Source | None:
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
    storage_uri: str | None = None,
    parent_artifact_id: str,
    mime_type: str | None = None,
    metadata: Any | None = None,
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
    source_id: str | None = None,
    crawler: str | None = None,
    config: Any | None = None,
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
        created_at=datetime.datetime.now(datetime.UTC),
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
    raw_artifact_id: str | None = None,
    bronze_artifact_id: str | None = None,
    fetched_at: datetime.datetime | None = None,
    error_msg: str | None = None,
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
        created_at=datetime.datetime.now(datetime.UTC),
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
) -> Artifact | None:
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
    metadata: Any | None = None,
    quality_score: float | None = None,
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


# ── Curated document (CURATE-01..03) ─────────────────────────────────────────


def create_curated_artifact(
    session: Session,
    *,
    source_id: str,
    parent_artifact_id: str,
    content_hash: str,
    metadata: Any | None = None,
    quality_score: float | None = None,
) -> Artifact:
    """Persist a curated document artifact node (CURATE-01..03).

    ``parent_artifact_id`` MUST point to the cleaned_document artifact (D-01),
    never parsed_document — curation always parents off the cleaned text,
    mirroring enriched_document's own parent convention exactly.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    source_id:
        FK to the source this document belongs to.
    parent_artifact_id:
        ID of the cleaned_document artifact this was curated from (required).
    content_hash:
        Synthetic SHA256 keyed on cleaned_content_hash + filter_config_version
        (mirrors _curation_cache_key's output — drives idempotent re-runs via
        the UNIQUE(content_hash, artifact_type) constraint).
    metadata:
        JSON dict carrying filter_results, composite_quality_score,
        parse_quality_score, enrich_quality_score, and dedup_status keys.
    quality_score:
        Composite quality score stored as the real Artifact.quality_score column
        for filterable API queries (mirrors enriched_document's usage).

    Returns
    -------
    Artifact
        The newly created (unsaved) Artifact instance.
    """
    art = _make_artifact(
        kind="curated_document",
        source_id=source_id,
        artifact_type="curated_document",
        content_hash=content_hash,
        storage_uri=None,
        parent_artifact_id=parent_artifact_id,
        metadata=metadata,
    )
    art.quality_score = quality_score
    session.add(art)
    return art


def get_child_artifact_by_type(
    session: Session,
    parent_artifact_id: str,
    artifact_type: str,
) -> Artifact | None:
    """Return the first direct child of ``parent_artifact_id`` matching ``artifact_type``,
    or None if no such child exists.

    Generic one-hop child lookup used for:
      - Finding the curated_document child of a cleaned_document parent.
      - Finding the enriched_document sibling for composite-score lookup (Pitfall 4:
        enriched_document and curated_document are cousins sharing a cleaned_document
        parent — this lookup finds them via the shared parent, not an ancestor walk).

    No raw SQL — ORM select (T-01-03).
    """
    stmt = (
        select(Artifact)
        .where(Artifact.parent_artifact_id == parent_artifact_id)
        .where(Artifact.artifact_type == artifact_type)
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


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
        updated_at=datetime.datetime.now(datetime.UTC),
    )
    session.add(spend)
    return spend


def get_enriched_artifact_for_parsed(
    session: Session,
    parsed_artifact_id: str,
) -> Artifact | None:
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


def get_curated_artifact_for_parsed(
    session: Session,
    parsed_artifact_id: str,
) -> Artifact | None:
    """Resolve the curated_document artifact two hops below a parsed_document.

    Walks parsed_document -> cleaned_document -> curated_document, mirroring
    get_enriched_artifact_for_parsed (KL-04/05/06): curate parents off
    cleaned_document per D-01, same as enrich. Returns None if no
    cleaned_document child exists yet, or if the cleaned_document has no
    curated_document child yet.
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

    curated = next(
        (
            child
            for child in list_children(session, cleaned.id)
            if child.artifact_type == "curated_document"
        ),
        None,
    )
    return curated


def get_domain_for_source(session: Session, source_id: str) -> str | None:
    """Return the domain classification for a source, or None.

    KL-15: domain is now a first-class indexed column (``Source.domain``,
    migration 0010) and is read from there first. Falls back to the legacy
    ``Source.config["domain"]`` JSON blob only as a defensive belt for rows
    the backfill migration somehow missed, or rows written by code that has
    not yet picked up the ``domain=`` column write (dual-write window).
    Returns None if the source is missing or has neither.
    """
    source = session.get(Source, source_id)
    if source is None:
        return None
    if source.domain:
        return source.domain
    if source.config:
        return source.config.get("domain")
    return None


def get_source(session: Session, source_id: str) -> Source | None:
    """Fetch a Source by its primary key.

    Returns None if not found (does not raise).
    """
    return session.get(Source, source_id)


def get_source_crawl_config(session: Session, source_id: str) -> dict:
    """Return the crawl_config sub-dict from Source.config, or {} if absent.

    Mirrors the get_domain_for_source pattern (D-01): same None-guard and
    session-handling style.

    D-05: returns the inner crawl_config sub-dict (not the outer Source.config),
    so callers receive keys like 'rate_limit_rps' and 'depth' directly, without
    needing to traverse the nesting themselves.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    source_id:
        Primary key of the Source row to look up.

    Returns
    -------
    dict
        The value of Source.config['crawl_config'], or {} if the source is
        missing, Source.config is None, or the 'crawl_config' key is absent.
    """
    source = session.get(Source, source_id)
    if source is None or not source.config:
        return {}
    return source.config.get("crawl_config", {})


def list_sources_for_crawl_all(
    session: Session,
    domain: str | None = None,
) -> list[Source]:
    """Return all sources ordered by created_at asc, optionally filtered by domain.

    Domain is stored in Source.config['domain'] (same JSON column used by
    get_domain_for_source and the GET /sources endpoint at api/app.py:1146).
    Filtering is done Python-side to avoid JSONB-specific SQL and remain
    database-agnostic (mirrors the api/app.py:1176 pattern confirmed in RESEARCH.md
    Pattern 6).

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    domain:
        If provided, only sources where Source.config.get('domain') == domain
        are returned.  None returns all sources.

    Returns
    -------
    list[Source]
        All matching Source rows, ordered by created_at ascending.
    """
    all_sources = list(
        session.execute(select(Source).order_by(Source.created_at.asc())).scalars()
    )
    if domain is None:
        return all_sources
    return [s for s in all_sources if (s.config or {}).get("domain") == domain]


# ── Crawl scheduling helpers (SCHED-01, SCHED-02) ────────────────────────────


_ScheduledSource = namedtuple(
    "_ScheduledSource",
    ["id", "url", "crawl_schedule", "last_crawled_at", "last_content_hash", "created_at", "config"],
)


def list_scheduled_sources(session: Session) -> list:
    """Return sources with a non-NULL crawl_schedule as namedtuples.

    Materializes every field inside the session to avoid DetachedInstanceError
    when the sensor iterates rows after session close.

    Returns
    -------
    list[_ScheduledSource]
        Namedtuples with id, url, crawl_schedule, last_crawled_at,
        last_content_hash, created_at, config.
    """
    rows = session.execute(
        select(Source).where(Source.crawl_schedule.is_not(None))
    ).scalars()
    return [
        _ScheduledSource(
            id=s.id,
            url=s.url,
            crawl_schedule=s.crawl_schedule,
            last_crawled_at=s.last_crawled_at,
            last_content_hash=s.last_content_hash,
            created_at=s.created_at,
            config=(s.config or {}),
        )
        for s in rows
    ]


def set_source_schedule(
    session: Session,
    source_id: str,
    crawl_schedule: str | None,
) -> bool:
    """Update or clear the crawl_schedule column for a source.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    source_id:
        Primary key of the Source to update.
    crawl_schedule:
        New cron string, or None to clear (disable scheduling).

    Returns
    -------
    bool
        True if the source existed and was updated; False if source not found.
    """
    source = session.get(Source, source_id)
    if source is None:
        return False
    source.crawl_schedule = crawl_schedule
    return True


def touch_source_crawl(
    source_id: str,
    *,
    last_crawled_at: datetime.datetime,
    last_content_hash: str | None = None,
) -> None:
    """Update crawl watermarks after a re-crawl attempt (D-11/D-17).

    Opens its own session so the Dagster op can call it without holding one.
    When last_content_hash is None (skip path), leaves the existing hash
    unchanged.

    Parameters
    ----------
    source_id:
        Primary key of the Source to update.
    last_crawled_at:
        UTC timestamp of the crawl attempt.
    last_content_hash:
        New content hash, or None to leave the existing value.
    """
    from knowledge_lake.registry.db import get_session

    with get_session() as session:
        src = session.get(Source, source_id)
        if src is None:
            return
        src.last_crawled_at = last_crawled_at
        if last_content_hash is not None:
            src.last_content_hash = last_content_hash


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
        created_at=datetime.datetime.now(datetime.UTC),
    )
    session.add(collection)
    return collection


def get_current_vector_collection(
    session: Session,
    alias_name: str,
) -> VectorCollection | None:
    """Return the current physical collection row for the given alias, or None."""
    stmt = (
        select(VectorCollection)
        .where(VectorCollection.alias_name == alias_name)
        .where(VectorCollection.is_current == True)  # noqa: E712
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


# ── Chunk dedup ledger (DEDUP-01..03) ──────────────────────────────────────────


def claim_dedup_ledger_entry(
    session: Session,
    *,
    collection: str,
    text_sha256: str,
    point_id: str,
    chunk_id: str,
    parsed_artifact_id: str,
    source_id: str | None,
    created_at: datetime.datetime,
) -> tuple[ChunkDedupLedger, bool]:
    """Atomically claim ``(collection, text_sha256)`` as a NEW primary, or
    return the row that already won the race (D-14).

    Uses ``INSERT ... ON CONFLICT (collection, text_sha256) DO NOTHING
    ... RETURNING`` -- the only correct way to detect first-writer status on
    this project's exact psycopg3 + SQLAlchemy 2.0.51 pin.
    ``CursorResult``'s rowcount attribute returns -1 for this statement shape
    regardless of outcome (empirically verified against live Postgres 16);
    never branch on it.

    Returns ``(row, True)`` if this call created the row (new primary), or
    ``(row, False)`` if another caller already claimed this key first -- in
    which case ``row`` is the pre-existing (winning) row, untouched by this
    call. The losing caller does NOT become a contributor here; contributor
    appending is a separate, later concern (see ``append_dedup_contributor``).
    """
    primary_contributor = {
        "chunk_id": chunk_id,
        "document": parsed_artifact_id,
        "source_id": source_id,
        "created_at": created_at.isoformat(),
    }

    stmt = (
        pg_insert(ChunkDedupLedger)
        .values(
            id=new_id("artifact"),
            collection=collection,
            text_sha256=text_sha256,
            point_id=point_id,
            primary_chunk_id=chunk_id,
            primary_parsed_artifact_id=parsed_artifact_id,
            primary_source_id=source_id,
            primary_created_at=created_at,
            contributors=[primary_contributor],
            contributor_count=1,
        )
        .on_conflict_do_nothing(index_elements=["collection", "text_sha256"])
        .returning(ChunkDedupLedger.id)
    )
    won = session.execute(stmt).fetchall()

    if won:
        row = session.get(ChunkDedupLedger, won[0][0])
        return row, True

    # Lost the race -- re-select the existing (winning) row. Do NOT mutate it
    # here; the losing caller only routes the chunk.
    existing = session.execute(
        select(ChunkDedupLedger)
        .where(ChunkDedupLedger.collection == collection)
        .where(ChunkDedupLedger.text_sha256 == text_sha256)
    ).scalar_one()
    return existing, False


def get_dedup_ledger_entry(
    session: Session,
    *,
    collection: str,
    point_id: str | None = None,
    text_sha256: str | None = None,
) -> ChunkDedupLedger | None:
    """Pure lookup of a dedup ledger row -- no insert, never raises for a miss
    (mirrors ``get_artifact_by_hash``'s ``scalar_one_or_none()`` shape).

    Exactly one of ``point_id``/``text_sha256`` must be given; raises
    ``ValueError`` if both or neither are provided.
    """
    if (point_id is None) == (text_sha256 is None):
        raise ValueError(
            "get_dedup_ledger_entry requires exactly one of point_id or text_sha256"
        )

    stmt = select(ChunkDedupLedger).where(ChunkDedupLedger.collection == collection)
    if text_sha256 is not None:
        stmt = stmt.where(ChunkDedupLedger.text_sha256 == text_sha256)
    else:
        stmt = stmt.where(ChunkDedupLedger.point_id == point_id)

    return session.execute(stmt).scalar_one_or_none()


def append_dedup_contributor(
    session: Session,
    ledger_row: ChunkDedupLedger,
    *,
    chunk_id: str,
    document: str,
    source_id: str | None,
    created_at: datetime.datetime,
) -> ChunkDedupLedger:
    """Append one contributor to the ledger's UNBOUNDED ``contributors`` list
    (D-13 -- the ledger never caps; only the Qdrant mirror caps, and that
    capping is the caller's job).

    ``contributor_count`` is derived from the new list's length -- never an
    independent increment, so it cannot drift. The caller is responsible for
    committing the session; this function only mutates the tracked ORM object.
    """
    new_contributors = list(ledger_row.contributors or [])
    new_contributors.append(
        {
            "chunk_id": chunk_id,
            "document": document,
            "source_id": source_id,
            "created_at": created_at.isoformat(),
        }
    )
    ledger_row.contributors = new_contributors
    ledger_row.contributor_count = len(new_contributors)
    return ledger_row


# ── Dataset registry (DATA-01..03) ────────────────────────────────────────────


def create_dataset(
    session: Session,
    *,
    name: str,
    dataset_type: str,
    format: str | None = None,
    storage_uri: str | None = None,
    example_count: int | None = None,
    id: str | None = None,
) -> Dataset:
    """Create a new Dataset row and add it to the session.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    name:
        Human-readable, unique name for this dataset (unique constraint from 0008).
    dataset_type:
        Kind of dataset: 'rag_eval', 'instruction_tuning', 'pretraining', etc.
    format:
        Export format: 'jsonl', 'parquet', etc. None until exported.
    storage_uri:
        S3 URI of the exported dataset file. None until exported.
    example_count:
        Running example count. None until populated by export.
    id:
        Row ID to use, e.g. when the caller already minted a ``dst_`` ID for a
        storage key (filename) and wants the row to carry the SAME ID rather
        than a second, unrelated one (KL-14). Defaults to a freshly minted
        ``new_id("dataset")`` when not supplied — the pre-existing behavior.

    Returns
    -------
    Dataset
        The newly created (unsaved) Dataset instance.
    """
    dataset = Dataset(
        id=id or new_id("dataset"),
        name=name,
        dataset_type=dataset_type,
        format=format,
        storage_uri=storage_uri,
        example_count=example_count,
        created_at=datetime.datetime.now(datetime.UTC),
    )
    session.add(dataset)
    return dataset


def get_dataset_by_name(session: Session, name: str) -> Dataset | None:
    """Return the Dataset matching ``name``, or None.

    Uses the uq_datasets_name unique index for O(1) lookup.
    No raw SQL — ORM select (T-01-03).
    """
    stmt = select(Dataset).where(Dataset.name == name).limit(1)
    return session.execute(stmt).scalar_one_or_none()


def get_or_create_dataset(
    session: Session,
    *,
    name: str,
    dataset_type: str,
    format: str | None = None,
) -> Dataset:
    """Get an existing Dataset by name, or create it if it doesn't exist.

    Uses the same get-or-create discipline as ``record_llm_spend`` — checks
    for an existing row first so repeated per-chunk/per-document generation
    calls accumulate into ONE logical dataset rather than creating a new
    Dataset row per example.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    name:
        Dataset name to look up or create.
    dataset_type:
        Dataset type used on creation only (ignored on get).
    format:
        Export format used on creation only.

    Returns
    -------
    Dataset
        Existing or newly created Dataset instance.
    """
    existing = get_dataset_by_name(session, name)
    if existing is not None:
        return existing
    return create_dataset(session, name=name, dataset_type=dataset_type, format=format)


def create_dataset_example(
    session: Session,
    *,
    dataset_id: str,
    source_artifact_id: str | None,
    example_index: int,
    payload: Any | None = None,
) -> DatasetExample:
    """Create a new DatasetExample row and add it to the session (DATA-03).

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    dataset_id:
        FK to the parent Dataset.
    source_artifact_id:
        FK to the source chunk (DATA-01) or enriched_document (DATA-02) artifact.
        Nullable — ondelete=SET NULL keeps examples if the artifact is deleted.
    example_index:
        Zero-based position of this example within its dataset.
    payload:
        Dict carrying the validated LLM-generated content (plus _cache_key).

    Returns
    -------
    DatasetExample
        The newly created (unsaved) DatasetExample instance.
    """
    example = DatasetExample(
        id=new_id("dataset_example"),
        dataset_id=dataset_id,
        source_artifact_id=source_artifact_id,
        example_index=example_index,
        payload=payload or {},
        created_at=datetime.datetime.now(datetime.UTC),
    )
    session.add(example)
    return example


def list_dataset_examples(
    session: Session,
    dataset_id: str,
) -> list[DatasetExample]:
    """Return all DatasetExample rows for a dataset, ordered by example_index.

    Used to compute the next example_index and to list examples for export.
    No raw SQL — ORM select (T-01-03).
    """
    stmt = (
        select(DatasetExample)
        .where(DatasetExample.dataset_id == dataset_id)
        .order_by(DatasetExample.example_index)
    )
    return list(session.execute(stmt).scalars())


def list_artifacts_by_type(
    session: Session,
    artifact_type: str,
) -> list[Artifact]:
    """Return all artifacts of the given type, ordered by created_at.

    Generic version of list_cleaned_artifacts() — parameterized by artifact_type.
    Used by export functions to enumerate ALL chunk artifacts (EXPORT-01) and ALL
    curated_document artifacts (EXPORT-02).

    No raw SQL — ORM select (T-01-03).
    """
    stmt = (
        select(Artifact)
        .where(Artifact.artifact_type == artifact_type)
        .order_by(Artifact.created_at)
    )
    return list(session.execute(stmt).scalars())


def update_dataset_export(
    session: Session,
    dataset_id: str,
    *,
    format: str,
    storage_uri: str,
    example_count: int,
) -> Dataset:
    """Update a Dataset row's export materialization fields.

    Fetches the Dataset row by ID and updates its format, storage_uri, and
    example_count fields in place — materializing an existing logical dataset
    to a file, not creating a new dataset row.

    Used by export_finetune_dataset() after successfully writing the gold-zone
    JSONL file. Raises ValueError if the dataset_id does not resolve to a
    live row.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    dataset_id:
        Primary key of the Dataset row to update.
    format:
        Export format written ('jsonl', 'parquet', etc.).
    storage_uri:
        S3 URI of the exported file in the gold zone.
    example_count:
        Number of examples written to the file.

    Returns
    -------
    Dataset
        The updated Dataset instance.

    Raises
    ------
    ValueError
        If no Dataset row exists for the given dataset_id.
    """
    row = session.get(Dataset, dataset_id)
    if row is None:
        raise ValueError(f"Dataset not found: {dataset_id!r}")
    row.format = format
    row.storage_uri = storage_uri
    row.example_count = example_count
    return row


def list_all_dataset_examples(session: Session) -> list[DatasetExample]:
    """Return all DatasetExample rows across every dataset.

    Used by check_train_eval_contamination() — the contamination check is a
    full-corpus check per 05-AI-SPEC Section 6/7, not scoped to one dataset.

    No raw SQL — ORM select (T-01-03).
    """
    stmt = select(DatasetExample)
    return list(session.execute(stmt).scalars())


def list_curated_documents_by_dedup_status(
    session: Session,
    status: str,
) -> list[Artifact]:
    """Return curated_document artifacts whose metadata_['dedup_status'] matches status.

    Filters in Python (not via a DB-specific JSON operator) so the same code
    works identically against the in-memory SQLite test fixture and real Postgres
    (Python-side JSON field access is DB-agnostic).

    Used by check_train_eval_contamination() to build the set of near-dup
    flagged documents for the near-dup cross-check.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    status:
        dedup_status string to filter by (e.g. 'near_dup', 'unique', 'not_yet_computed').

    Returns
    -------
    list[Artifact]
        Curated_document artifacts whose metadata_['dedup_status'] == status.
    """
    all_curated = list_artifacts_by_type(session, "curated_document")
    return [
        a for a in all_curated
        if (a.metadata_ or {}).get("dedup_status") == status
    ]


def list_dataset_examples_by_cache_key(
    session: Session,
    cache_key: str,
) -> list[DatasetExample]:
    """Return DatasetExample rows whose payload._cache_key matches ``cache_key``.

    Used by generate_qa_example/generate_instruction_example to detect idempotent
    re-runs: the synthetic cache key (source_content_hash + prompt_version) is
    stored inside payload["_cache_key"] so we can find prior generations without
    needing a dedicated content-hash column on dataset_examples (D-08: examples
    are NOT Artifact nodes with a UNIQUE(content_hash, artifact_type) constraint).

    Returns an empty list if no matches are found.
    No raw SQL — Python-side JSON filter for DB-agnostic behaviour (T-01-03).
    """
    # Use Python-side filtering to avoid SQLAlchemy JSON path operator
    # differences between PostgreSQL (-> returns quoted JSON fragment) and
    # SQLite (JSON_EXTRACT returns unquoted value).  Matches the pattern used
    # by list_curated_documents_by_dedup_status (line 1148).
    all_examples = list(session.execute(select(DatasetExample)).scalars())
    return [e for e in all_examples if (e.payload or {}).get("_cache_key") == cache_key][:1]
