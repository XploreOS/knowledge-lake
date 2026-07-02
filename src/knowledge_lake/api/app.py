"""
Knowledge Lake FastAPI application.

Entry point: uvicorn knowledge_lake.api.app:app

This is the thin start of the full REST surface. Search and lineage endpoints
are added in plan 01-06. This plan delivers only:
  GET /health  → {"status":"ok"}
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI

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
