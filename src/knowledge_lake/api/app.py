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

import structlog
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from knowledge_lake.api.schemas import LineageGraph, LineageNode, SearchHit, SearchParams
from knowledge_lake.config.settings import get_settings

logger = structlog.get_logger(__name__)

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
