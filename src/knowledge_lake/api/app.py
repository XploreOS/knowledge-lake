"""
Knowledge Lake FastAPI application.

Entry point: uvicorn knowledge_lake.api.app:app

Endpoints:
  GET /health                    → {"status": "ok"}
  GET /search?q=...&top_k=...   → list[SearchHit] — calls pipeline.search() (D-02)
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
from urllib.parse import urlparse

import structlog
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from knowledge_lake.api.schemas import (
    ChunkRequest,
    ChunkResponse,
    CleanRequest,
    CleanResponse,
    CrawlJobCreate,
    CrawlJobOut,
    CrawlStateOut,
    DiscoverOut,
    DiscoverRequest,
    DiscoverResultItem,
    EnrichRequest,
    EnrichResponse,
    LineageGraph,
    LineageNode,
    ParseRequest,
    ParseResponse,
    SearchHit,
    SearchParams,
    SourceCreate,
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
) -> list[SearchHit]:
    """Embed a query and return the top-k nearest chunk hits with citation fields.

    Calls ``pipeline.search.search()`` — the same function the CLI uses (D-02).

    Security (T-01-14 / ASVS V5):
        - ``top_k`` is bounded [1, 100] by the ``ge``/``le`` constraints.
        - Empty/whitespace queries return an empty list (not an error).

    Args:
        q:          Natural-language search query.
        top_k:      Maximum number of results (1–100, default 5).
        collection: Qdrant collection to search (default: klake_chunks).

    Returns:
        A list of SearchHit objects ordered by score descending.
        Returns an empty list when the query is empty/whitespace.
    """
    from knowledge_lake.pipeline.search import search

    # Validate collection name format before passing to Qdrant (WR-04, T-01-14).
    # Prevents collection enumeration attacks and rejects malformed names early.
    if not _COLLECTION_NAME_RE.fullmatch(collection):
        raise HTTPException(status_code=422, detail="Invalid collection name format.")

    # Delegate entirely to the existing plain function (D-02)
    logger.info("api.search", q=q[:80], top_k=top_k, collection=collection)
    hits = search(q, collection=collection, top_k=top_k)

    # Map Hit → SearchHit, extracting citation fields from payload
    result: list[SearchHit] = []
    for hit in hits:
        payload = hit.payload or {}
        result.append(
            SearchHit(
                id=hit.id,
                score=hit.score,
                document=payload.get("document", ""),
                section_path=payload.get("section_path", ""),
                page=int(payload.get("page", 1)),
                chunk_id=payload.get("chunk_id", hit.id),
                text=payload.get("text", ""),
            )
        )

    logger.info("api.search.complete", results=len(result))
    return result


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

    logger.info("api.enrich", cleaned_artifact_id=body.cleaned_artifact_id)

    try:
        result = enrich_document(body.cleaned_artifact_id, body.source_id)
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
