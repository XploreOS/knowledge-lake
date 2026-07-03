"""Search stage: embed query, ANN search → Hits with score + citation payload.

The embedder and vector store are resolved from settings.
The query is embedded with the same embedder used during indexing — the
collection dimension must match (both default to 'local' → 384-dim).

Returns: list[Hit], each Hit has .id, .score, .payload with citation fields.
"""

from __future__ import annotations

from typing import Optional

import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.plugins.protocols import Hit
from knowledge_lake.plugins.resolver import get_embedder, get_vectorstore

log = structlog.get_logger(__name__)


def search(
    query: str,
    *,
    collection: str = "klake_chunks",
    top_k: int = 5,
    settings: Optional[Settings] = None,
) -> list[Hit]:
    """Embed a query and return the top-k nearest chunk hits.

    Args:
        query:      Natural-language query string.
        collection: Qdrant collection to search (must exist and be populated).
        top_k:      Maximum number of results to return.
        settings:   Settings override.

    Returns:
        List of Hit objects ordered by score descending, each carrying:
          .id             — chunk artifact ID (also in .payload['chunk_id'])
          .score          — cosine similarity score in [0, 1]
          .payload        — dict with document, section_path, page, chunk_id, text
    """
    if not query.strip():
        log.warning("search.empty_query")
        return []

    s = settings or get_settings()
    embedder = get_embedder(s)
    vstore = get_vectorstore(s)

    log.info("search.start", query=query[:80], collection=collection, top_k=top_k)

    # Embed the query
    query_vectors = embedder.embed([query])
    query_vector = query_vectors[0]

    # ANN search
    hits: list[Hit] = vstore.search(collection, query_vector, top_k=top_k)

    log.info("search.complete", hits=len(hits))
    return hits
