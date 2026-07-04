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
import structlog
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from knowledge_lake.api.schemas import (
    DiscoverOut,
    DiscoverRequest,
    DiscoverResultItem,
    LineageGraph,
    LineageNode,
    SearchHit,
    SearchParams,
    SourceCreate,
    SourceOut,
    UploadOut,
)
from knowledge_lake.config.settings import get_settings

logger = structlog.get_logger(__name__)

# Collection names must be alphanumeric with underscores/hyphens, max 64 chars (WR-04).
# Rejects arbitrary strings that could enumerate Qdrant collections or cause confusion.
_COLLECTION_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

app = FastAPI(
    title="Knowledge Lake API",
    description=(
        "Domain-agnostic framework API — serves AI-ready assets with full lineage traceability."
    ),
    version="0.1.0",
)


@app.on_event("startup")
async def on_startup() -> None:
    """Log startup with resolved service configuration."""
    settings = get_settings()
    logger.info(
        "api.startup",
        database_url=settings.database_url.split("@")[-1],  # Never log credentials
        qdrant_url=settings.qdrant_url,
        litellm_url=settings.litellm_url,
        embedder=settings.embedder,
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
async def search_endpoint(
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
async def create_source_endpoint(body: SourceCreate) -> SourceOut:
    """Register a source URL with URL-first dedup (INGEST-01).

    If the normalized URL already exists, returns the existing source (HTTP 201
    regardless — D-07 silent success, same shape).

    Security (T-02-04 / ASVS V5):
        - URL is validated by pydantic (min_length=8).
        - Name/domain lengths are bounded.
    """
    from knowledge_lake.pipeline.ingest import register_source

    logger.info("api.sources.create", url=body.url, name=body.name)

    effective_name = body.name or body.url.split("/")[2] if "/" in body.url else body.url
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
async def upload_endpoint(
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

    Security (T-02-04):
        - file_path is validated by the pipeline (must exist on disk).
    """
    from knowledge_lake.pipeline.ingest import ingest_file

    logger.info("api.uploads.create", file_path=file_path, source_name=source_name)

    try:
        result = ingest_file(
            path=file_path,
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
async def discover_endpoint(body: DiscoverRequest) -> DiscoverOut:
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


@app.get(
    "/lineage/{artifact_id}",
    response_model=list[LineageNode],
    tags=["lineage"],
    summary="Resolve the full ancestry of an artifact",
    responses={
        404: {"description": "Artifact not found in the registry"},
    },
)
async def lineage_endpoint(artifact_id: str) -> list[LineageNode]:
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
