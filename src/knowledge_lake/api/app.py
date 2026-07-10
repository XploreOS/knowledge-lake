"""
Knowledge Lake FastAPI application.

Entry point: uvicorn knowledge_lake.api.app:app

Endpoints:
  GET /health                    → {"status": "ok"}
  GET /search?q=...&top_k=...   → list[SearchHit] — calls pipeline.search() (D-02),
                                    filterable by domain/document_type/min_quality_score (INDEX-03)
  POST /reindex?collection=...   → ReindexResponse — zero-downtime alias reindex (INDEX-02)
  GET /lineage/{artifact_id}     → list[LineageNode] — calls lineage.resolve_ancestry() (D-02)

Security (T-01-14):
    Query parameters are validated by pydantic schemas (ASVS V5).
    artifact_id is validated as a non-empty path segment.
    Unknown artifacts return 404 with a clear error body.

D-02 compliance:
    Both endpoints call the same pipeline.search() and lineage.resolve_ancestry()
    functions that the CLI uses — no behavior re-implementation.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import structlog
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from knowledge_lake.api.schemas import (
    ArtifactOut,
    ChunkRequest,
    ChunkResponse,
    CleanRequest,
    CleanResponse,
    CrawlAllOut,
    CrawlAllSourceResult,
    CrawlJobCreate,
    CrawlJobOut,
    CrawlStateOut,
    CurateRequest,
    CurateResponse,
    DedupeResponse,
    CuratedDocumentOut,
    DatasetOut,
    DiscoverOut,
    DiscoverRequest,
    DiscoverResultItem,
    DomainLoadRequest,
    DomainLoadResponse,
    EnrichRequest,
    EnrichResponse,
    ExportRequest,
    ExportResponse,
    GenerateDatasetRequest,
    GenerateDatasetResponse,
    LineageGraph,
    LineageNode,
    ParseRequest,
    ParseResponse,
    ReindexResponse,
    SearchHit,
    SearchParams,
    SourceCreate,
    SourceListItem,
    SourceOut,
    UploadOut,
)
from knowledge_lake.config.settings import get_settings

logger = structlog.get_logger(__name__)

def _safe_upload_path(raw: str) -> Path:
    """Resolve ``raw`` and assert it is inside the configured upload root.

    The upload root is read from ``settings.upload_root`` (default ``/data/uploads``,
    overridable via ``KLAKE_UPLOAD_ROOT`` env var) so the guard tracks the
    deployment configuration rather than a hardcoded constant (CR-004).

    Prevents arbitrary file-read: callers cannot supply /etc/passwd or
    any path outside the designated upload directory.

    Raises:
        HTTPException 400: When the resolved path escapes the upload root.
    """
    upload_root = Path(get_settings().upload_root).resolve()
    p = Path(raw).resolve()
    try:
        p.relative_to(upload_root)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Path is outside the allowed upload directory.",
        )
    return p


# Collection names must be alphanumeric with underscores/hyphens, max 64 chars (WR-04).
# Rejects arbitrary strings that could enumerate Qdrant collections or cause confusion.
_COLLECTION_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# Domain names: letter-first, alphanumeric + hyphen/underscore, 1-64 chars.
# Applied to /domains/load body.name (T-06-08) and /domains/{name}/sources path param (T-06-09).
_DOMAIN_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler — replaces deprecated @on_event("startup") (WR-005).

    Logs the resolved service configuration on startup.  FastAPI 0.93+ deprecated
    @app.on_event in favour of this lifespan context-manager pattern.
    """
    settings = get_settings()
    logger.info(
        "api.startup",
        database_url=settings.database_url.split("@")[-1],  # Never log credentials
        qdrant_url=settings.qdrant_url,
        litellm_url=settings.litellm_url,
        embedder=settings.embedder,
    )
    yield


app = FastAPI(
    title="Knowledge Lake API",
    description=(
        "Domain-agnostic framework API — serves AI-ready assets with full lineage traceability."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["ops"], summary="Service health check")
async def health() -> dict[str, str]:
    """Return the service health status.

    Returns:
        {"status": "ok"} when the service is ready to accept requests.
    """
    return {"status": "ok"}


@app.get(
    "/search",
    response_model=list[SearchHit],
    tags=["search"],
    summary="Semantic search over indexed chunks",
)
def search_endpoint(
    q: str = Query(..., description="Natural-language search query."),
    top_k: int = Query(
        default=5,
        ge=1,
        le=100,
        description="Maximum number of results to return. Must be 1–100.",
    ),
    collection: str = Query(
        default="klake_chunks",
        description="Qdrant collection to search.",
    ),
    domain: Optional[str] = Query(
        default=None,
        description="Filter results to this domain.",
    ),
    document_type: Optional[str] = Query(
        default=None,
        description="Filter results to this document_type.",
    ),
    min_quality_score: Optional[float] = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description="Filter results to quality_score >= this value.",
    ),
    source_name: Optional[str] = Query(
        default=None,
        description="Filter results to this source name.",
    ),
    format: Optional[str] = Query(
        default=None,
        description="Filter results to this source format (e.g. 'html', 'pdf').",
    ),
    source_id: Optional[str] = Query(
        default=None,
        description="Filter results to this source ID.",
    ),
    tags: Optional[list[str]] = Query(
        default=None,
        description="Filter results where payload tags contain any of these values (OR logic). Each tag max 64 chars, max 64 tags.",
        max_length=64,  # per-element character limit (list length is checked separately in handler)
    ),
    mode: Optional[str] = Query(
        default=None,
        pattern=r"^(hybrid|dense|sparse)$",
        description=(
            "Search mode: hybrid|dense|sparse. "
            "Defaults to KLAKE_SEARCH__MODE setting (hybrid). "
            "An unrecognised value is rejected with 422 (T-10-02, ASVS V5, fail-closed). "
            "A hybrid or sparse request against a sparse-less collection returns the "
            "store's clear error (fail-loud, D-10)."
        ),
    ),
) -> list[SearchHit]:
    """Embed a query and return the top-k nearest chunk hits with citation fields.

    Calls ``pipeline.search.search()`` — the same function the CLI uses (D-02).

    Security (T-01-14 / ASVS V5):
        - ``top_k`` is bounded [1, 100] by the ``ge``/``le`` constraints.
        - ``min_quality_score`` is bounded [0.0, 1.0] by the ``ge``/``le`` constraints.
        - ``tags`` list max_length=64 bounds number of tags; each element is also
          validated to max 64 characters (T-07-04-01).
        - ``mode`` is bounded to the Literal set {hybrid, dense, sparse} via the
          Query pattern — any other value is automatically rejected with 422 before
          the handler body runs (T-10-02, ASVS V5).
        - Empty/whitespace queries return an empty list (not an error).

    Args:
        q:                 Natural-language search query.
        top_k:             Maximum number of results (1–100, default 5).
        collection:        Qdrant collection to search (default: klake_chunks).
        domain:            Optional filter — payload['domain'] must match exactly.
        document_type:     Optional filter — payload['document_type'] must match exactly.
        min_quality_score: Optional filter — payload['quality_score'] must be >= this value.
        source_name:       Optional filter — payload['source_name'] must match exactly.
        format:            Optional filter — payload['format'] must match exactly.
        source_id:         Optional filter — payload['source_id'] must match exactly.
        tags:              Optional OR filter — payload['tags'] must contain any of these values.
        mode:              Optional search mode override (hybrid|dense|sparse). None → settings default.

    D-13 backward-compat note:
        source_name, format, tags, source_id filters are only effective on points indexed
        after Phase 7 (or after a full reindex from source chunks). Pre-Phase-7 points
        will not match.

    Returns:
        A list of SearchHit objects ordered by score descending.
        Returns an empty list when the query is empty/whitespace.
    """
    from knowledge_lake.pipeline.search import search

    # Validate collection name format before passing to Qdrant (WR-04, T-01-14).
    # Prevents collection enumeration attacks and rejects malformed names early.
    if not _COLLECTION_NAME_RE.fullmatch(collection):
        raise HTTPException(status_code=422, detail="Invalid collection name format.")

    # Guard against an unbounded number of tags (WR-02).
    # FastAPI's Query(max_length=64) on a list[str] constrains each element's
    # character length, NOT the number of elements — a caller could send thousands
    # of &tags= repetitions causing unbounded CPU in the MatchAny clause.
    if tags and len(tags) > 64:
        raise HTTPException(status_code=422, detail="At most 64 tags may be specified.")

    # Validate per-element tag string length (WR-05, T-07-04-01).
    # FastAPI's Query(max_length=64) on a list bounds the number of elements,
    # not the length of each element string.  Enforce element length manually.
    if tags and any(len(t) > 64 for t in tags):
        raise HTTPException(status_code=422, detail="Tag values must not exceed 64 characters.")

    # Delegate entirely to the existing plain function (D-02)
    logger.info(
        "api.search",
        q=q[:80],
        top_k=top_k,
        collection=collection,
        domain=domain,
        document_type=document_type,
        min_quality_score=min_quality_score,
        source_name=source_name,
        format=format,
        source_id=source_id,
        tags=tags,
        mode=mode,
    )
    hits = search(
        q,
        collection=collection,
        top_k=top_k,
        domain=domain,
        document_type=document_type,
        min_quality_score=min_quality_score,
        source_name=source_name,
        format=format,
        source_id=source_id,
        tags=tags,
        mode=mode,
    )

    # Map Hit → SearchHit, extracting citation + enrichment fields from payload
    result: list[SearchHit] = []
    for hit in hits:
        payload = hit.payload or {}
        result.append(
            SearchHit(
                id=hit.id,
                score=hit.score,
                document=payload.get("document", ""),
                section_path=payload.get("section_path", ""),
                page=int(payload.get("page") or 1),
                chunk_id=payload.get("chunk_id", hit.id),
                text=payload.get("text", ""),
                domain=payload.get("domain"),
                document_type=payload.get("document_type"),
                keywords=payload.get("keywords", []),
                quality_score=payload.get("quality_score"),
                source_id=payload.get("source_id"),
                source_name=payload.get("source_name"),
                source_url=payload.get("source_url"),
                format=payload.get("format"),
                tags=payload.get("tags", []),
                title=payload.get("title"),
                organization=payload.get("organization"),
            )
        )

    logger.info("api.search.complete", results=len(result))
    return result


@app.post(
    "/reindex",
    response_model=ReindexResponse,
    tags=["pipeline"],
    summary="Reindex a Qdrant alias with zero search downtime",
    status_code=200,
)
def reindex_endpoint(
    collection: str = Query(default="klake_chunks", description="Qdrant alias to reindex."),
) -> ReindexResponse:
    """Reindex a Qdrant alias with zero search downtime (INDEX-02).

    Creates the next versioned physical collection, copies all existing points
    into it via ``copy_all_points()``, then atomically repoints the alias.
    Calls ``pipeline.index.reindex_collection()`` — the same function the CLI
    uses (D-02). The prior physical collection is retained, never auto-dropped.

    Security (ASVS V5):
        - collection is validated against the same format guard as /search (WR-04).
    """
    from knowledge_lake.pipeline.index import reindex_collection

    if not _COLLECTION_NAME_RE.fullmatch(collection):
        raise HTTPException(status_code=422, detail="Invalid collection name format.")

    logger.info("api.reindex", collection=collection)

    try:
        result = reindex_collection(collection)
    except ValueError as exc:
        logger.warning("api.reindex.error", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info(
        "api.reindex.complete",
        collection=collection,
        new_physical=result["new_physical"],
        old_physical=result.get("old_physical"),
    )
    return ReindexResponse(**result)


@app.post(
    "/sources",
    response_model=SourceOut,
    tags=["ingestion"],
    summary="Register a source URL",
    status_code=201,
)
def create_source_endpoint(body: SourceCreate) -> SourceOut:
    """Register a source URL with URL-first dedup (INGEST-01).

    If the normalized URL already exists, returns the existing source (HTTP 201
    regardless — D-07 silent success, same shape).

    Security (T-02-04 / ASVS V5):
        - URL is validated by pydantic (min_length=8).
        - Name/domain lengths are bounded.
    """
    from knowledge_lake.pipeline.ingest import register_source

    logger.info("api.sources.create", url=body.url, name=body.name)

    effective_name = body.name or (urlparse(body.url).hostname or body.url)
    try:
        result = register_source(
            url=body.url,
            name=effective_name,
            domain=body.domain,
            license_type=body.license_type,
        )
    except ValueError as exc:
        logger.warning("api.sources.validation_error", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info("api.sources.complete", source_id=result["source_id"], is_new=result["is_new"])
    return SourceOut(**result)


@app.post(
    "/uploads",
    response_model=UploadOut,
    tags=["ingestion"],
    summary="Upload a local file into the raw zone",
    status_code=201,
)
def upload_endpoint(
    file_path: str = Query(
        ...,
        description="Absolute path to the file on the server filesystem.",
    ),
    source_name: str = Query(
        default="uploaded-file",
        description="Human-readable source name.",
    ),
    license_type: str = Query(
        default="unknown",
        description="SPDX license identifier.",
    ),
) -> UploadOut:
    """Upload a local file and ingest as a raw_document artifact (INGEST-03).

    For hermetic/integration testing: accepts a file path (not multipart).
    Hash-second dedup: identical content returns existing artifact IDs (D-07).

    Security (T-02-04, CR-01):
        - file_path is constrained to _UPLOAD_ROOT to prevent arbitrary file read.
    """
    from knowledge_lake.pipeline.ingest import ingest_file

    safe_path = _safe_upload_path(file_path)
    logger.info("api.uploads.create", file_path=str(safe_path), source_name=source_name)

    try:
        result = ingest_file(
            path=safe_path,
            source_name=source_name,
            license_type=license_type,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info("api.uploads.complete", artifact_id=result["artifact_id"])
    return UploadOut(**result)


@app.post(
    "/discover",
    response_model=DiscoverOut,
    tags=["discovery"],
    summary="Discover candidate sources via meta-search",
    status_code=200,
)
def discover_endpoint(body: DiscoverRequest) -> DiscoverOut:
    """Run a source discovery query and auto-register valid results (INGEST-07).

    Uses the configured DiscoveryPlugin (default: SearXNG) to search for
    candidate sources. Each result URL is SSRF-validated (T-02-22) and
    URL-deduped (D-08) before registration.

    Security (T-02-25 / ASVS V5):
        - query is bounded [1, 500] characters by pydantic.
        - limit is bounded [1, 100] by pydantic.
        - SSRF validation on every result URL before registration.
    """
    from knowledge_lake.pipeline.discover import discover_sources

    logger.info("api.discover", query=body.query[:80], limit=body.limit)

    try:
        results = discover_sources(query=body.query, limit=body.limit)
    except (RuntimeError, LookupError) as exc:
        logger.warning("api.discover.error", error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    items = [
        DiscoverResultItem(
            url=r["url"],
            title=r["title"],
            source_id=r["source_id"],
            status=r["status"],
        )
        for r in results
    ]

    logger.info("api.discover.complete", total=len(items))
    return DiscoverOut(
        query=body.query,
        total=len(items),
        results=items,
    )


@app.post(
    "/crawl-jobs",
    response_model=CrawlJobOut,
    tags=["crawl"],
    summary="Start a crawl job for a source URL",
    status_code=201,
)
async def create_crawl_job_endpoint(body: CrawlJobCreate) -> CrawlJobOut:
    """Start a crawl job for the given source URL (INGEST-04).

    Creates a crawl job and runs it asynchronously, writing raw+bronze artifacts
    for each successfully fetched page. Resume-safe: re-running for the same
    source URL picks up where a prior interrupted crawl left off.

    Declared as `async def` so FastAPI awaits it directly in the event loop.
    crawl_source is async and is awaited without the overhead of creating a
    new event loop per request (WR-001).

    Security (T-02-13 / ASVS V5):
        - source_url is validated by pydantic (min_length=8).
        - crawler override is validated against registered crawlers.
        - max_pages is bounded [1, 10000].
    """
    from knowledge_lake.pipeline.crawl import crawl_source

    logger.info("api.crawl_jobs.create", source_url=body.source_url, crawler=body.crawler)

    try:
        result = await crawl_source(
            body.source_url,
            crawler=body.crawler,
            max_pages=body.max_pages,
        )
    except ValueError as exc:
        logger.warning("api.crawl_jobs.validation_error", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        logger.warning("api.crawl_jobs.crawler_not_found", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    states = CrawlStateOut(
        complete=result.get("pages_complete", 0),
        robots_blocked=result.get("pages_robots_blocked", 0),
        failed=result.get("pages_failed", 0),
        pending=0,
    )

    logger.info("api.crawl_jobs.complete", job_id=result["job_id"])
    return CrawlJobOut(
        job_id=result["job_id"],
        source_id=result["source_id"],
        crawler=result["crawler"],
        status="complete",
        states=states,
    )


@app.get(
    "/crawl-jobs/{job_id}",
    response_model=CrawlJobOut,
    tags=["crawl"],
    summary="Get crawl job status and page counts",
    responses={
        404: {"description": "Crawl job not found"},
    },
)
def get_crawl_job_endpoint(job_id: str) -> CrawlJobOut:
    """Get the status and page counts of a crawl job (INGEST-04).

    Returns the job header + crawl_states summary (counts by status).
    Returns 404 for an unknown job_id.

    Security (T-01-14 / ASVS V5):
        - job_id is parameterized in SQL (no injection).
        - Unknown IDs return 404 with a clear JSON error body.
    """
    from sqlalchemy import select, func

    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.models import CrawlState, Job

    logger.info("api.crawl_jobs.get", job_id=job_id)

    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(
                status_code=404,
                detail=f"Crawl job {job_id!r} not found.",
            )

        # Count states by status
        stmt = (
            select(CrawlState.status, func.count(CrawlState.id))
            .where(CrawlState.job_id == job_id)
            .group_by(CrawlState.status)
        )
        counts = dict(session.execute(stmt).all())

    states = CrawlStateOut(
        complete=counts.get("complete", 0),
        robots_blocked=counts.get("robots_blocked", 0),
        failed=counts.get("failed", 0),
        pending=counts.get("pending", 0),
    )

    return CrawlJobOut(
        job_id=job.id,
        source_id=job.source_id or "",
        crawler=job.crawler or "",
        status=job.status or "unknown",
        states=states,
    )


@app.post(
    "/crawl-all",
    response_model=CrawlAllOut,
    tags=["crawl"],
    summary="Batch-crawl all registered sources",
    status_code=200,
)
async def crawl_all_endpoint(
    domain: Optional[str] = Query(None, description="Filter by domain (e.g. 'healthcare'). Crawls all sources if omitted."),
) -> CrawlAllOut:
    """Batch-crawl all registered sources into the lake (CRAWL-02 D-08/D-09).

    Loops over all sources (optionally filtered by domain), running per-source
    crawl in sequence.  Per-source failures are logged and counted but do not
    abort the batch — a summary is always returned (D-09).

    Security (T-08-06-02):
        domain is passed as a Python-side string filter to list_sources_for_crawl_all;
        no SQL injection risk (SQLAlchemy ORM, Python-side equality check).
    """
    from knowledge_lake.pipeline.crawl import crawl_all_sources

    logger.info("api.crawl_all.start", domain=domain)

    try:
        raw = await crawl_all_sources(domain=domain)
    except Exception as exc:
        logger.error("api.crawl_all.unexpected_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    results = [
        CrawlAllSourceResult(
            source_id=entry.get("source_id", ""),
            status=entry.get("status", "failed"),
            error=entry.get("error"),
            pages_complete=entry.get("pages_complete"),
        )
        for entry in raw.get("results", [])
    ]

    return CrawlAllOut(
        total=raw.get("total", 0),
        succeeded=raw.get("succeeded", 0),
        failed=raw.get("failed", 0),
        results=results,
    )


@app.post(
    "/parse",
    response_model=ParseResponse,
    tags=["pipeline"],
    summary="Parse a raw document artifact into a parsed document",
    status_code=200,
)
def parse_endpoint(body: ParseRequest) -> ParseResponse:
    """Run the parse pipeline stage on an already-ingested raw_document artifact.

    Uses the configured parser fallback chain (Docling → JSON/XML → Unstructured → Tika).
    Returns the parsed artifact ID, quality score, parser used, and content hash.

    Security (T-03-11 / ASVS V5):
        - artifact_id is validated by Pydantic (min_length=1).
        - Artifact lookup uses parameterised ORM query (no SQL injection).
        - Invalid IDs return 422 with a clear error body.
    """
    from knowledge_lake.pipeline.parse import parse

    logger.info("api.parse", raw_artifact_id=body.raw_artifact_id, mime_type=body.mime_type)

    try:
        result, _parsed_doc = parse(
            body.raw_artifact_id,
            body.source_id,
            mime_type=body.mime_type,
        )
    except (ValueError, LookupError) as exc:
        logger.warning("api.parse.error", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info("api.parse.complete", artifact_id=result["artifact_id"])
    return ParseResponse(
        artifact_id=result["artifact_id"],
        quality_score=result.get("quality_score", 0.0),
        parser_used=result.get("parser_used", "unknown"),
        content_hash=result.get("content_hash", ""),
    )


@app.post(
    "/clean",
    response_model=CleanResponse,
    tags=["pipeline"],
    summary="Clean a parsed document artifact",
    status_code=200,
)
def clean_endpoint(body: CleanRequest) -> CleanResponse:
    """Run the clean pipeline stage on a parsed_document artifact.

    Removes boilerplate, normalises whitespace, detects language, and flags
    near-duplicate documents.  Returns the cleaned artifact ID, language, and
    dedup status.

    Security (T-03-11 / ASVS V5):
        - artifact_id is validated by Pydantic (min_length=1).
        - Artifact lookup uses parameterised ORM query (no SQL injection).
        - Invalid IDs return 422 with a clear error body.
    """
    from knowledge_lake.pipeline.clean import clean

    logger.info("api.clean", parsed_artifact_id=body.parsed_artifact_id)

    try:
        result = clean(body.parsed_artifact_id, body.source_id)
    except ValueError as exc:
        logger.warning("api.clean.error", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info("api.clean.complete", artifact_id=result["artifact_id"])
    return CleanResponse(
        artifact_id=result["artifact_id"],
        language=result["language"],
        dedup_status=result["dedup_status"],
        content_hash=result["content_hash"],
    )


@app.post(
    "/chunk",
    response_model=ChunkResponse,
    tags=["pipeline"],
    summary="Chunk a parsed document artifact into token-aware chunks",
    status_code=200,
)
def chunk_endpoint(body: ChunkRequest) -> ChunkResponse:
    """Run the chunk pipeline stage on a parsed_document artifact.

    Fetches the parsed text from the silver zone, reconstructs a minimal ParsedDoc,
    and runs the token-aware chunker.  Returns the chunk count and all chunk artifact IDs.

    Note: In production usage the Dagster pipeline passes ParsedDoc in-memory between
    clean and chunk stages.  This endpoint reconstructs a ParsedDoc from the stored text
    (no section structure) — suitable for testing and ad-hoc chunking.

    Security (T-03-11 / ASVS V5):
        - artifact_id is validated by Pydantic (min_length=1).
        - Artifact lookup uses parameterised ORM query (no SQL injection).
        - Invalid IDs return 422 with a clear error body.
    """
    from knowledge_lake.config.settings import get_settings
    from knowledge_lake.pipeline.chunk import chunk
    from knowledge_lake.plugins.protocols import ParsedDoc
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry import repo as registry_repo
    from knowledge_lake.storage.s3 import StorageBackend

    logger.info("api.chunk", parsed_artifact_id=body.parsed_artifact_id)

    s = get_settings()
    storage = StorageBackend(s.storage)

    try:
        # Fetch parsed artifact metadata to get storage URI
        with get_session() as session:
            parsed_artifact = registry_repo.get_artifact(session, body.parsed_artifact_id)
            if parsed_artifact is None:
                raise ValueError(
                    f"Parsed artifact {body.parsed_artifact_id!r} not found in registry"
                )
            storage_uri = parsed_artifact.storage_uri
            if not storage_uri:
                raise ValueError(
                    f"Parsed artifact {body.parsed_artifact_id!r} has no storage_uri"
                )

        # Extract S3 key from s3://bucket/key URI — use shared helper to
        # raise a descriptive ValueError on malformed URIs instead of IndexError.
        from knowledge_lake.pipeline.utils import uri_to_key
        key = uri_to_key(storage_uri)
        raw_bytes = storage.get_object(key)
        parsed_text = raw_bytes.decode("utf-8")

        # Reconstruct minimal ParsedDoc with no section structure
        doc = ParsedDoc(text=parsed_text, sections=[])
        chunks = chunk(body.parsed_artifact_id, body.source_id, doc)

    except ValueError as exc:
        logger.warning("api.chunk.error", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    chunk_ids = [c["artifact_id"] for c in chunks]
    logger.info("api.chunk.complete", chunk_count=len(chunks))
    return ChunkResponse(chunk_count=len(chunks), chunk_ids=chunk_ids)


@app.post(
    "/enrich",
    response_model=EnrichResponse,
    tags=["pipeline"],
    summary="Enrich a cleaned document artifact with LLM-judged metadata",
    status_code=200,
)
def enrich_endpoint(body: EnrichRequest) -> EnrichResponse:
    """Run the enrich pipeline stage on a cleaned_document artifact.

    Runs deterministic (non-LLM) extraction first, then a single cached,
    budget-capped LiteLLM call. Returns 'enriched', 'cached',
    'skipped_budget_exceeded', or 'skipped_enrichment_failed' status.

    Security (ASVS V5):
        - cleaned_artifact_id/source_id are validated by Pydantic (min_length=1).
        - Artifact lookup uses parameterised ORM query (no SQL injection).
        - Invalid IDs return 422 with a clear error body.
    """
    from knowledge_lake.pipeline.enrich import enrich_document
    from knowledge_lake.plugins.protocols import ParsedDoc
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry import repo as registry_repo

    logger.info("api.enrich", cleaned_artifact_id=body.cleaned_artifact_id)

    try:
        # Reconstruct a minimal ParsedDoc from the cleaned artifact's parent
        # parsed_document artifact's stored metadata (which carries a "title"
        # key persisted by pipeline.parse.parse()) so the deterministic title
        # is not silently dropped to "" on this entry point (CR-01) — mirrors
        # the parent-artifact-fetch pattern already used by chunk_endpoint.
        with get_session() as session:
            cleaned_artifact = registry_repo.get_artifact(session, body.cleaned_artifact_id)
            if cleaned_artifact is None:
                raise ValueError(
                    f"Cleaned artifact {body.cleaned_artifact_id!r} not found in registry"
                )
            parsed_artifact = (
                registry_repo.get_artifact(session, cleaned_artifact.parent_artifact_id)
                if cleaned_artifact.parent_artifact_id
                else None
            )
            parsed_metadata = (parsed_artifact.metadata_ if parsed_artifact else None) or {}

        parsed_doc = ParsedDoc(text="", sections=[], metadata=parsed_metadata)
        domain_system_prompt: str | None = None
        _enrich_settings = get_settings()
        if _enrich_settings.domain.domain_name:
            from knowledge_lake.domains.loader import DomainLoader
            domain_system_prompt = DomainLoader.from_name(_enrich_settings.domain.domain_name).render_prompt("enrich.j2")
        result = enrich_document(
            body.cleaned_artifact_id, body.source_id, parsed_doc=parsed_doc,
            domain_system_prompt=domain_system_prompt,
        )
    except ValueError as exc:
        logger.warning("api.enrich.error", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info("api.enrich.complete", status=result["status"], artifact_id=result.get("artifact_id"))
    return EnrichResponse(
        artifact_id=result.get("artifact_id"),
        status=result["status"],
        cached=result.get("cached", False),
        quality_score=result.get("quality_score"),
    )


@app.post(
    "/curate",
    response_model=CurateResponse,
    tags=["pipeline"],
    summary="Run DataTrove-style quality filtering on a cleaned_document artifact",
    status_code=200,
)
def curate_endpoint(body: CurateRequest) -> CurateResponse:
    """Run the curate pipeline stage on a cleaned_document artifact (CURATE-01..03).

    Records per-heuristic DataTrove filter pass/fail, computes a composite quality
    score spanning parse + enrich + curation stages, and stores the result as a
    curated_document artifact. Returns 'curated' or 'cached' status.

    Security (ASVS V5, T-05-03):
        - cleaned_artifact_id/source_id are validated by Pydantic (min_length=1).
        - Artifact lookup uses parameterised ORM query (no SQL injection).
        - Invalid IDs return 422 with a clear error body.
    """
    from knowledge_lake.pipeline.curate import curate_document

    logger.info("api.curate", cleaned_artifact_id=body.cleaned_artifact_id)

    try:
        result = curate_document(body.cleaned_artifact_id, body.source_id)
    except (ValueError, LookupError) as exc:
        logger.warning("api.curate.error", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info(
        "api.curate.complete",
        status=result["status"],
        artifact_id=result.get("artifact_id"),
    )
    # dedup_status lives in the artifact's metadata_ — fetch from result metadata if present
    dedup_status = result.get("dedup_status")
    return CurateResponse(
        artifact_id=result.get("artifact_id"),
        status=result["status"],
        cached=result.get("cached", False),
        quality_score=result.get("quality_score"),
        dedup_status=dedup_status,
    )


@app.post(
    "/curate/dedupe",
    response_model=DedupeResponse,
    tags=["curation"],
    summary="Run corpus-wide MinHash batch deduplication over all cleaned_document artifacts (CURATE-02)",
    status_code=200,
)
def dedupe_endpoint() -> DedupeResponse:
    """Build one MinHash LSH index over ALL cleaned_document artifacts in a single pass.

    Corpus-wide deduplication (CURATE-02): classifies each artifact as 'unique' or
    'near_dup' and updates the dedup_status field on its curated_document child.
    Equivalent to `klake dedupe` in the CLI — calls pipeline.curate.batch_dedup_corpus()
    with no per-call options (runs over the full corpus).

    Security (ASVS V5): no user input; read-only artifact scan + targeted metadata update.
    """
    from knowledge_lake.pipeline.curate import batch_dedup_corpus

    logger.info("api.dedupe.start")
    try:
        result = batch_dedup_corpus()
    except Exception as exc:
        logger.error("api.dedupe.error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    logger.info(
        "api.dedupe.complete",
        total=result.get("total"),
        unique=result.get("unique"),
        near_dup=result.get("near_dup"),
    )
    return DedupeResponse(
        total=result.get("total", 0),
        unique=result.get("unique", 0),
        near_dup=result.get("near_dup", 0),
        skipped_no_curation=result.get("skipped_no_curation", 0),
    )


@app.post(
    "/datasets/examples",
    response_model=GenerateDatasetResponse,
    tags=["datasets"],
    summary="Generate a dataset example from a chunk (qa) or enriched document (instruction)",
    status_code=200,
)
def generate_dataset_endpoint(body: GenerateDatasetRequest) -> GenerateDatasetResponse:
    """Generate a dataset training/eval example and store it with full lineage (DATA-01/02/03).

    Routes to pipeline.datasets.generate_qa_example (kind='qa') or
    pipeline.datasets.generate_instruction_example (kind='instruction') —
    no logic duplicated (D-02).

    Security (ASVS V5, T-05-07):
        - kind is bounded to '^(qa|instruction)$' via Pydantic pattern validation.
        - source_artifact_id/dataset_name are validated by Pydantic (min_length=1).
        - Artifact lookups use parameterised ORM queries — no raw SQL.
        - Invalid artifact IDs or wrong artifact types return 422.
    """
    from knowledge_lake.pipeline.datasets import (
        generate_instruction_example,
        generate_qa_example,
    )

    logger.info(
        "api.generate_dataset",
        kind=body.kind,
        source_artifact_id=body.source_artifact_id,
        dataset_name=body.dataset_name,
    )

    try:
        if body.kind == "qa":
            result = generate_qa_example(body.source_artifact_id, body.dataset_name)
        else:
            result = generate_instruction_example(body.source_artifact_id, body.dataset_name)
    except ValueError as exc:
        logger.warning("api.generate_dataset.error", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info(
        "api.generate_dataset.complete",
        status=result["status"],
        example_id=result.get("example_id"),
    )
    return GenerateDatasetResponse(
        status=result["status"],
        example_id=result.get("example_id"),
        dataset_id=result.get("dataset_id"),
        cost_usd=result.get("cost_usd"),
    )


@app.get(
    "/curated-documents",
    response_model=list[CuratedDocumentOut],
    tags=["pipeline"],
    summary="List curated documents with optional quality-score filtering",
    status_code=200,
)
def list_curated_documents_endpoint(
    min_quality_score: Optional[float] = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum composite quality score to include (0.0–1.0, T-05-03).",
    ),
) -> list[CuratedDocumentOut]:
    """Return curated_document artifacts ordered by quality_score descending.

    Optional ``min_quality_score`` filter (Pydantic ge/le bounds reject out-of-range
    values before the query runs, satisfying T-05-03). Uses a parameterized ORM
    select() query — never raw SQL (T-01-03 injection prevention).

    CURATE-03: satisfies the "queryable via API" criterion.
    """
    from sqlalchemy import select
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.models import Artifact

    with get_session() as session:
        stmt = select(Artifact).where(Artifact.artifact_type == "curated_document")
        if min_quality_score is not None:
            stmt = stmt.where(Artifact.quality_score >= min_quality_score)
        stmt = stmt.order_by(Artifact.quality_score.desc())
        artifacts = list(session.execute(stmt).scalars())

    return [
        CuratedDocumentOut(
            artifact_id=a.id,
            quality_score=a.quality_score,
            dedup_status=(a.metadata_ or {}).get("dedup_status"),
            created_at=a.created_at.isoformat() if a.created_at else "",
        )
        for a in artifacts
    ]


@app.get(
    "/lineage/{artifact_id}",
    response_model=list[LineageNode],
    tags=["lineage"],
    summary="Resolve the full ancestry of an artifact",
    responses={
        404: {"description": "Artifact not found in the registry"},
    },
)
def lineage_endpoint(artifact_id: str) -> list[LineageNode]:
    """Resolve the full ancestry chain of an artifact (FOUND-07 API).

    Walks from the given artifact up to the raw source via the recursive CTE
    in ``lineage.resolve_ancestry()`` — the same function the CLI uses (D-02).

    Returns ordered nodes (leaf first, root last). Each node carries all six
    FOUND-06 fields: id, artifact_type, content_hash, created_at,
    pipeline_version, storage_uri.

    Security (T-01-14 / ASVS V5):
        - Artifact IDs are parameterized in SQL — no string interpolation
          (T-01-13, enforced by the underlying resolver).
        - Unknown artifact IDs return 404 with a clear JSON error body.

    Args:
        artifact_id: Full artifact ID (e.g. ``chk_019f...``) or unambiguous prefix.

    Returns:
        List of LineageNode objects ordered by depth (0 = queried artifact).

    Raises:
        HTTPException 404: When artifact_id is not found in the registry.
    """
    from knowledge_lake.lineage import resolve_ancestry

    logger.info("api.lineage", artifact_id=artifact_id)

    try:
        nodes = resolve_ancestry(artifact_id)
    except (LookupError, ValueError) as exc:
        logger.warning("api.lineage.not_found", artifact_id=artifact_id, error=str(exc))
        raise HTTPException(
            status_code=404,
            detail=f"Artifact {artifact_id!r} not found in the registry. {exc}",
        ) from exc

    # Map dicts → LineageNode pydantic models
    result: list[LineageNode] = []
    for node in nodes:
        result.append(
            LineageNode(
                id=node["id"],
                artifact_type=node["artifact_type"],
                content_hash=node["content_hash"],
                created_at=node["created_at"],
                pipeline_version=node["pipeline_version"],
                storage_uri=node.get("storage_uri"),
                source_id=node.get("source_id"),
                parent_artifact_id=node.get("parent_artifact_id"),
                depth=node.get("depth", 0),
                section_path=node.get("section_path"),
                page=node.get("page"),
                mime_type=node.get("mime_type"),
            )
        )

    logger.info("api.lineage.complete", artifact_id=artifact_id, nodes=len(result))
    return result


@app.post(
    "/exports",
    response_model=ExportResponse,
    tags=["export"],
    summary="Export the corpus or a dataset to the gold zone (EXPORT-01/02/03)",
    status_code=200,
)
def export_endpoint(body: ExportRequest) -> ExportResponse:
    """Export curated corpus or dataset examples to the gold zone (EXPORT-01/02/03).

    Routes to the appropriate pipeline.export function based on ``kind``:
    - ``rag-corpus`` → export_rag_corpus() → Parquet (EXPORT-01)
    - ``pretrain``   → export_pretrain_corpus() → JSONL (EXPORT-02)
    - ``finetune``   → export_finetune_dataset(dataset_name) → JSONL (EXPORT-03)

    All export functions fail closed with a 422 if any undocumented train/eval
    contamination exists (05-AI-SPEC Section 6/7 hard gate, T-05-11).

    Security (T-05-09 / ASVS V5):
        - ``kind`` is bounded to ``^(rag-corpus|pretrain|finetune)$`` via Pydantic pattern.
        - No free-form string reaches the gold-zone S3 key construction.
        - ``dataset_name`` is bounded to max_length=255.
        - ``ValueError`` (missing dataset, invalid kind) → 422.

    D-02 compliance:
        Calls the same pipeline.export functions as the CLI export command — no
        behavior re-implemented.
    """
    from knowledge_lake.pipeline.export import (
        TrainEvalContaminationError,
        export_finetune_dataset,
        export_pretrain_corpus,
        export_rag_corpus,
    )

    if body.kind == "finetune" and not body.dataset_name:
        raise HTTPException(
            status_code=422,
            detail="dataset_name is required for kind='finetune'.",
        )

    logger.info("api.export", kind=body.kind, dataset_name=body.dataset_name)

    try:
        if body.kind == "rag-corpus":
            result = export_rag_corpus()
        elif body.kind == "pretrain":
            result = export_pretrain_corpus()
        else:
            assert body.dataset_name is not None  # validated above
            result = export_finetune_dataset(body.dataset_name)
    except TrainEvalContaminationError as exc:
        logger.warning("api.export.contamination", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        logger.warning("api.export.error", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info(
        "api.export.complete",
        kind=body.kind,
        dataset_id=result.get("dataset_id"),
        row_count=result.get("row_count"),
    )
    return ExportResponse(
        dataset_id=result["dataset_id"],
        storage_uri=result["storage_uri"],
        row_count=result["row_count"],
        skipped_dangling_lineage=result.get("skipped_dangling_lineage"),
    )


# ── D-07 API gap audit: 8 additive endpoints ─────────────────────────────────
# Group 1: Sources (GET /sources, GET /sources/{source_id})
# Group 2: Documents (GET /documents, GET /documents/{artifact_id})
# Group 3: Datasets (GET /datasets, GET /datasets/{dataset_id})
# Group 4: Domains (POST /domains/load, GET /domains/{name}/sources)
# All queries use SQLAlchemy ORM select() — never raw SQL (T-06-11 injection prevention).
# Domain names validated against _DOMAIN_NAME_RE before any path construction (T-06-08/09).


@app.get(
    "/sources",
    response_model=list[SourceListItem],
    tags=["registry"],
    summary="List registered sources with optional domain filter",
    status_code=200,
)
def list_sources_endpoint(
    domain: Optional[str] = Query(
        default=None,
        description="Filter by domain classification (e.g. 'healthcare').",
        max_length=64,
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Maximum results (1–200)."),
    offset: int = Query(default=0, ge=0, description="Pagination offset."),
) -> list[SourceListItem]:
    """List all registered sources with pagination and optional domain filter (D-07 gap audit).

    When a domain filter is active, all matching rows are fetched first (Python-side
    filter for DB-agnosticism, same pattern as list_curated_documents_by_dedup_status)
    and then LIMIT/OFFSET are applied to the filtered set so pagination counts are
    correct.  Without a domain filter, LIMIT/OFFSET are pushed to the DB for
    efficiency.

    Security (T-06-11 / ASVS V5):
        - All queries use ORM select() — no raw SQL.
        - domain/limit/offset are validated by Pydantic before reaching the handler.
    """
    from sqlalchemy import select
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.models import Source

    with get_session() as session:
        if domain is not None:
            # Fetch all rows and filter in Python so LIMIT/OFFSET apply to the
            # filtered result set (avoids post-LIMIT domain filtering which breaks
            # pagination semantics — WR-01).
            all_sources = list(
                session.execute(select(Source).order_by(Source.created_at.desc())).scalars()
            )
            filtered = [
                s for s in all_sources
                if (s.config or {}).get("domain") == domain
            ]
            sources = filtered[offset : offset + limit]
        else:
            stmt = select(Source).order_by(Source.created_at.desc()).limit(limit).offset(offset)
            sources = list(session.execute(stmt).scalars())

    result: list[SourceListItem] = []
    for src in sources:
        src_domain = (src.config or {}).get("domain") if src.config else None
        result.append(
            SourceListItem(
                source_id=src.id,
                name=src.name,
                url=src.url,
                source_type=src.source_type,
                license_type=src.license_type,
                domain=src_domain,
                created_at=src.created_at.isoformat() if src.created_at else "",
            )
        )
    return result


@app.get(
    "/sources/{source_id}",
    response_model=SourceListItem,
    tags=["registry"],
    summary="Get a single source by ID",
    status_code=200,
    responses={404: {"description": "Source not found"}},
)
def get_source_endpoint(source_id: str) -> SourceListItem:
    """Return a single source registry entry by its ID or 404 (D-07 gap audit).

    Security (T-06-11 / ASVS V5):
        - session.get() uses parameterised primary-key lookup — no injection.
    """
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.models import Source

    with get_session() as session:
        src = session.get(Source, source_id)
        if src is None:
            raise HTTPException(
                status_code=404,
                detail=f"Source {source_id!r} not found.",
            )
        src_domain = (src.config or {}).get("domain") if src.config else None
        return SourceListItem(
            source_id=src.id,
            name=src.name,
            url=src.url,
            source_type=src.source_type,
            license_type=src.license_type,
            domain=src_domain,
            created_at=src.created_at.isoformat() if src.created_at else "",
        )


@app.get(
    "/documents",
    response_model=list[ArtifactOut],
    tags=["registry"],
    summary="List artifact documents with optional type and source filters",
    status_code=200,
)
def list_documents_endpoint(
    artifact_type: Optional[str] = Query(
        default=None,
        description="Filter by artifact type (e.g. 'raw_document', 'parsed_document').",
        max_length=64,
    ),
    source_id: Optional[str] = Query(
        default=None,
        description="Filter by source registry ID.",
        max_length=64,
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Maximum results (1–200)."),
    offset: int = Query(default=0, ge=0, description="Pagination offset."),
) -> list[ArtifactOut]:
    """List artifacts (documents) with pagination and optional type/source filters (D-07 gap audit).

    Security (T-06-11 / ASVS V5):
        - All filter parameters are bound via ORM — no string interpolation.
    """
    from sqlalchemy import select
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.models import Artifact

    with get_session() as session:
        stmt = select(Artifact).order_by(Artifact.created_at.desc())
        if artifact_type is not None:
            stmt = stmt.where(Artifact.artifact_type == artifact_type)
        if source_id is not None:
            stmt = stmt.where(Artifact.source_id == source_id)
        stmt = stmt.limit(limit).offset(offset)
        artifacts = list(session.execute(stmt).scalars())

    return [
        ArtifactOut(
            id=a.id,
            artifact_type=a.artifact_type,
            source_id=a.source_id,
            parent_artifact_id=a.parent_artifact_id,
            content_hash=a.content_hash,
            created_at=a.created_at.isoformat() if a.created_at else "",
            storage_uri=a.storage_uri,
            mime_type=a.mime_type,
        )
        for a in artifacts
    ]


@app.get(
    "/documents/{artifact_id}",
    response_model=ArtifactOut,
    tags=["registry"],
    summary="Get a single artifact document by ID",
    status_code=200,
    responses={404: {"description": "Artifact not found"}},
)
def get_document_endpoint(artifact_id: str) -> ArtifactOut:
    """Return a single artifact registry entry by its ID or 404 (D-07 gap audit).

    Security (T-06-11 / ASVS V5):
        - session.get() uses parameterised primary-key lookup — no injection.
    """
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.models import Artifact

    with get_session() as session:
        artifact = session.get(Artifact, artifact_id)
        if artifact is None:
            raise HTTPException(
                status_code=404,
                detail=f"Artifact {artifact_id!r} not found.",
            )
        return ArtifactOut(
            id=artifact.id,
            artifact_type=artifact.artifact_type,
            source_id=artifact.source_id,
            parent_artifact_id=artifact.parent_artifact_id,
            content_hash=artifact.content_hash,
            created_at=artifact.created_at.isoformat() if artifact.created_at else "",
            storage_uri=artifact.storage_uri,
            mime_type=artifact.mime_type,
        )


@app.get(
    "/datasets",
    response_model=list[DatasetOut],
    tags=["datasets"],
    summary="List curated datasets with pagination",
    status_code=200,
)
def list_datasets_endpoint(
    limit: int = Query(default=50, ge=1, le=200, description="Maximum results (1–200)."),
    offset: int = Query(default=0, ge=0, description="Pagination offset."),
) -> list[DatasetOut]:
    """List all registered datasets with pagination (D-07 gap audit).

    Security (T-06-11 / ASVS V5):
        - limit/offset validated by Pydantic ge/le bounds before reaching DB.
        - ORM select() — no raw SQL.
    """
    from sqlalchemy import select
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.models import Dataset

    with get_session() as session:
        stmt = (
            select(Dataset)
            .order_by(Dataset.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        datasets = list(session.execute(stmt).scalars())

    return [
        DatasetOut(
            dataset_id=ds.id,
            name=ds.name,
            created_at=ds.created_at.isoformat() if ds.created_at else "",
            row_count=ds.example_count or 0,
        )
        for ds in datasets
    ]


@app.get(
    "/datasets/{dataset_id}",
    response_model=DatasetOut,
    tags=["datasets"],
    summary="Get a single dataset by ID",
    status_code=200,
    responses={404: {"description": "Dataset not found"}},
)
def get_dataset_endpoint(dataset_id: str) -> DatasetOut:
    """Return a single dataset registry entry by its ID or 404 (D-07 gap audit).

    Security (T-06-11 / ASVS V5):
        - session.get() uses parameterised primary-key lookup — no injection.
    """
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.models import Dataset

    with get_session() as session:
        ds = session.get(Dataset, dataset_id)
        if ds is None:
            raise HTTPException(
                status_code=404,
                detail=f"Dataset {dataset_id!r} not found.",
            )
        return DatasetOut(
            dataset_id=ds.id,
            name=ds.name,
            created_at=ds.created_at.isoformat() if ds.created_at else "",
            row_count=ds.example_count or 0,
        )


def _register_domain_sources(name: str) -> dict:
    """Shared helper: load a domain pack and register its crawl-type sources.

    Returns a dict with loaded_count, skipped_count, upload_required_count keys.
    Used by both POST /domains/load and klake init --domain to avoid duplicating
    the registration logic (D-02: no behavior re-implementation).

    Raises FileNotFoundError if the domain pack does not exist.
    """
    from pathlib import Path

    from sqlalchemy.exc import IntegrityError

    from knowledge_lake.config.settings import get_settings
    from knowledge_lake.domains.loader import DomainLoader
    from knowledge_lake.pipeline.ingest import normalize_url
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry import repo as registry_repo
    from knowledge_lake.registry.repo import get_source_by_normalized_url

    settings = get_settings()
    _domains_path = Path(settings.domain.domains_root).resolve()
    root = _domains_path.parent if _domains_path.name == "domains" else _domains_path

    loader = DomainLoader.from_name(name, root=root)

    loaded_count = 0
    skipped_count = 0
    upload_required_count = 0

    for entry in loader.sources:
        if entry.ingest_type == "upload":
            upload_required_count += 1
            continue

        try:
            with get_session() as session:
                try:
                    norm_url = normalize_url(entry.url)
                except Exception:
                    norm_url = entry.url

                existing = get_source_by_normalized_url(session, norm_url)
                if existing is not None:
                    skipped_count += 1
                    continue

                registry_repo.create_source(
                    session,
                    name=entry.name,
                    source_type=entry.source_type,
                    url=entry.url,
                    normalized_url=norm_url,
                    license_type=entry.license,
                    config={
                        "domain": name,
                        "tags": entry.tags,
                        "crawl_config": entry.crawl_config,
                        "ingest_type": entry.ingest_type,
                    },
                )
                session.commit()
                loaded_count += 1
        except IntegrityError:
            skipped_count += 1

    return {
        "loaded_count": loaded_count,
        "skipped_count": skipped_count,
        "upload_required_count": upload_required_count,
    }


@app.post(
    "/domains/load",
    response_model=DomainLoadResponse,
    tags=["domains"],
    summary="Load a domain pack and register its seed sources",
    status_code=200,
)
def load_domain_endpoint(body: DomainLoadRequest) -> DomainLoadResponse:
    """Load a domain pack by name and bulk-register its crawl-type sources (DOMAIN-01).

    Upload-type sources are counted but not auto-registered. Existing sources
    are silently skipped (URL dedup). Returns counts for all categories.

    Security (T-06-08 / ASVS V5):
        - body.name validated against r'^[a-zA-Z][a-zA-Z0-9_-]{0,63}$' by Pydantic pattern
          in DomainLoadRequest BEFORE this handler runs — path traversal blocked at schema level.
        - Domain name is also validated against _DOMAIN_NAME_RE below for defence-in-depth.
        - DomainLoader validates the name again internally (T-06-01 in loader.py).
    """
    # Defence-in-depth: validate again even though Pydantic pattern already checked (T-06-08).
    if not _DOMAIN_NAME_RE.fullmatch(body.name):
        raise HTTPException(status_code=422, detail="Invalid domain name format.")

    logger.info("api.domains.load", name=body.name)

    try:
        result = _register_domain_sources(body.name)
    except FileNotFoundError as exc:
        logger.warning("api.domains.load.not_found", name=body.name, error=str(exc))
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    logger.info(
        "api.domains.load.complete",
        name=body.name,
        loaded_count=result["loaded_count"],
        skipped_count=result["skipped_count"],
        upload_required_count=result["upload_required_count"],
    )
    return DomainLoadResponse(
        name=body.name,
        loaded_count=result["loaded_count"],
        skipped_count=result["skipped_count"],
        upload_required_count=result["upload_required_count"],
    )


@app.get(
    "/domains/{name}/sources",
    response_model=list[dict],
    tags=["domains"],
    summary="List sources.yaml entries for a domain pack",
    status_code=200,
    responses={
        404: {"description": "Domain pack not found"},
        422: {"description": "Invalid domain name format"},
    },
)
def list_domain_sources_endpoint(name: str) -> list[dict]:
    """Return the list of SourceEntry dicts from sources.yaml for the named domain pack (DOMAIN-01).

    No DB access — reads the domain pack's sources.yaml directly via DomainLoader.
    Returns 404 if the domain pack does not exist.

    Security (T-06-09 / ASVS V5):
        - name validated against _DOMAIN_NAME_RE before calling DomainLoader.from_name().
        - DomainLoader.from_name() validates the name again internally (T-06-01).
        - Double validation provides defence-in-depth against path traversal.
    """
    from pathlib import Path

    from knowledge_lake.config.settings import get_settings
    from knowledge_lake.domains.loader import DomainLoader

    # Validate domain name before constructing any filesystem path (T-06-09).
    if not _DOMAIN_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail="Invalid domain name format.")

    logger.info("api.domains.sources", name=name)

    settings = get_settings()
    _domains_path = Path(settings.domain.domains_root).resolve()
    root = _domains_path.parent if _domains_path.name == "domains" else _domains_path

    try:
        loader = DomainLoader.from_name(name, root=root)
    except FileNotFoundError as exc:
        logger.warning("api.domains.sources.not_found", name=name, error=str(exc))
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return [s.model_dump() for s in loader.sources]
