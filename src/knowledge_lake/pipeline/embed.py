"""Embed stage: chunk texts → dense float vectors.

The embedder plugin is resolved from settings (KLAKE_EMBEDDER, default 'local').
Returns vectors in the same order as the input chunks.

No registry writes in this stage — embedding is a stateless transformation.
The resulting vectors flow directly to the index stage.

Returns: list[list[float]] (one vector per chunk, length == embedder.dim)
"""

from __future__ import annotations

import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.plugins.resolver import get_embedder

log = structlog.get_logger(__name__)


def embed(
    chunks: list[dict],
    *,
    settings: Settings | None = None,
) -> tuple[list[list[float]], int]:
    """Embed chunk texts using the configured embedder plugin.

    Args:
        chunks:   List of chunk dicts from the chunk stage (each has 'text').
        settings: Settings override (uses get_settings() if None).

    Returns:
        Tuple of:
          - list[list[float]]: One vector per chunk (length == embedder.dim)
          - int: The embedding dimension (needed by index stage for collection setup)
    """
    if not chunks:
        return [], 0

    s = settings or get_settings()
    embedder = get_embedder(s)

    texts = [c["text"] for c in chunks]
    log.info("embed.start", count=len(texts), embedder=embedder.name, dim=embedder.dim)

    vectors = embedder.embed(texts)

    log.info("embed.complete", vectors=len(vectors), dim=embedder.dim)
    return vectors, embedder.dim
