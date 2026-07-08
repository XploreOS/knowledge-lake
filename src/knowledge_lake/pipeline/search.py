"""Search stage: embed query, ANN search → Hits with score + citation payload.

The embedder and vector store are resolved from settings.
The query is embedded with the same embedder used during indexing — the
collection dimension must match (both default to 'local' → 384-dim).

Optional domain/document_type/min_quality_score keyword arguments build a
Qdrant Filter that narrows ANN results to chunks whose payload matches
(INDEX-03). Calling search() with none of these kwargs behaves identically to
the pre-Phase-4 signature — additive and backward compatible.

NOTE: importing qdrant_client.models here couples this file to the Qdrant
backend's filter shape — an acknowledged, accepted simplification since only
one VectorStorePlugin implementation (QdrantVectorStore) exists today
(RESEARCH.md's own verified Code Example).

Returns: list[Hit], each Hit has .id, .score, .payload with citation fields.
"""

from __future__ import annotations

from typing import Optional

import structlog
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue, Range

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.plugins.protocols import Hit
from knowledge_lake.plugins.resolver import get_embedder, get_vectorstore

log = structlog.get_logger(__name__)


def search(
    query: str,
    *,
    collection: str = "klake_chunks",
    top_k: int = 5,
    domain: Optional[str] = None,
    document_type: Optional[str] = None,
    min_quality_score: Optional[float] = None,
    source_name: Optional[str] = None,
    format: Optional[str] = None,  # noqa: A002
    tags: Optional[list[str]] = None,
    source_id: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> list[Hit]:
    """Embed a query and return the top-k nearest chunk hits.

    Args:
        query:             Natural-language query string.
        collection:        Qdrant collection to search (must exist and be populated).
        top_k:             Maximum number of results to return.
        domain:            Optional filter — payload['domain'] must match exactly.
        document_type:     Optional filter — payload['document_type'] must match exactly.
        min_quality_score: Optional filter — payload['quality_score'] must be >= this value.
        source_name:       Optional filter — payload['source_name'] must match exactly.
        format:            Optional filter — payload['format'] must match exactly (e.g. 'pdf', 'html').
        tags:              Optional filter — payload['tags'] must contain the given tag(s).
                           Single tag uses MatchValue; multiple tags uses MatchAny (D-11).
        source_id:         Optional filter — payload['source_id'] must match exactly.
        settings:          Settings override.

    NOTE: The source_name, format, tags, and source_id filters are only effective on
    points indexed after Phase 7 (or after a full reindex). Pre-Phase-7 points will
    not match — see CONTEXT.md D-13.

    Returns:
        List of Hit objects ordered by score descending, each carrying:
          .id             — chunk artifact ID (also in .payload['chunk_id'])
          .score          — cosine similarity score in [0, 1]
          .payload        — dict with document, section_path, page, chunk_id, text,
                            domain, document_type, keywords, quality_score,
                            source_id, source_name, source_url, format, tags,
                            title, organization
    """
    if not query.strip():
        log.warning("search.empty_query")
        return []

    s = settings or get_settings()
    embedder = get_embedder(s)
    vstore = get_vectorstore(s)

    log.info(
        "search.start",
        query=query[:80],
        collection=collection,
        top_k=top_k,
        domain=domain,
        document_type=document_type,
        min_quality_score=min_quality_score,
        source_name=source_name,
        format=format,
        source_id=source_id,
        tags=tags,
    )

    # Embed the query
    query_vectors = embedder.embed([query])
    query_vector = query_vectors[0]

    # Build an optional Qdrant Filter from the given filter kwargs (INDEX-03).
    must: list = []
    if domain:
        must.append(FieldCondition(key="domain", match=MatchValue(value=domain)))
    if document_type:
        must.append(FieldCondition(key="document_type", match=MatchValue(value=document_type)))
    if min_quality_score is not None:
        must.append(FieldCondition(key="quality_score", range=Range(gte=min_quality_score)))
    if source_name:
        must.append(FieldCondition(key="source_name", match=MatchValue(value=source_name)))
    if format:
        must.append(FieldCondition(key="format", match=MatchValue(value=format)))
    if source_id:
        must.append(FieldCondition(key="source_id", match=MatchValue(value=source_id)))
    if tags:
        if len(tags) == 1:
            must.append(FieldCondition(key="tags", match=MatchValue(value=tags[0])))
        else:
            must.append(FieldCondition(key="tags", match=MatchAny(any=tags)))
    query_filter = Filter(must=must) if must else None

    # ANN search
    hits: list[Hit] = vstore.search(
        collection, query_vector, top_k=top_k, query_filter=query_filter
    )

    log.info("search.complete", hits=len(hits))
    return hits
