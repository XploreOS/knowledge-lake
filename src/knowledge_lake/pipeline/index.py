"""Index stage: upsert chunk vectors with citation payload into Qdrant.

The vector store plugin is resolved from settings (KLAKE_VECTORSTORE, default 'qdrant').
Each chunk's VectorPoint payload carries the citation fields (D-07, D-14):
  document     — parsed_document artifact ID (so callers can fetch parsed text)
  section_path — section path string (e.g. '§1 Administrative Safeguards')
  page         — 1-indexed page number
  chunk_id     — chunk artifact ID (matches the point ID)
  text         — the chunk text (for snippet rendering without a second lookup)

The collection is created (idempotently) with the correct dimension before upsert.

Returns: list of chunk_ids indexed (same order as input chunks).
"""

from __future__ import annotations

from typing import Optional

import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.plugins.protocols import VectorPoint
from knowledge_lake.plugins.resolver import get_vectorstore

log = structlog.get_logger(__name__)


def index(
    chunks: list[dict],
    vectors: list[list[float]],
    dim: int,
    parsed_artifact_id: str,
    *,
    collection: str = "klake_chunks",
    settings: Optional[Settings] = None,
) -> list[str]:
    """Upsert chunk vectors into the vector store with citation payload.

    Creates the collection idempotently before upserting.

    Args:
        chunks:              List of chunk dicts from the chunk stage.
        vectors:             Embedding vectors (one per chunk, same order).
        dim:                 Embedding dimension (for collection setup).
        parsed_artifact_id:  ID of the parsed_document artifact (for 'document' payload).
        collection:          Qdrant collection name (default: 'klake_chunks').
        settings:            Settings override.

    Returns:
        List of chunk_ids that were indexed (same order as input).
    """
    if not chunks:
        return []

    assert len(chunks) == len(vectors), (
        f"index: chunks ({len(chunks)}) and vectors ({len(vectors)}) length mismatch"
    )

    s = settings or get_settings()
    vstore = get_vectorstore(s)

    log.info("index.ensure_collection", collection=collection, dim=dim)
    vstore.ensure_collection(collection, dim=dim)

    # Build VectorPoints with citation payload.
    # Qdrant requires point IDs to be unsigned integers or bare UUIDs —
    # our chunk IDs are prefixed (e.g. "chk_0196a2c1-...").  We strip the
    # prefix for the Qdrant point ID and preserve the full prefixed ID in the
    # payload as chunk_id so the CLI/lineage can resolve it back to the registry.
    points: list[VectorPoint] = []
    for chunk, vector in zip(chunks, vectors):
        full_chunk_id = chunk["chunk_id"]
        qdrant_point_id = _strip_prefix(full_chunk_id)
        payload = {
            "document": parsed_artifact_id,
            "section_path": chunk.get("section_path", ""),
            "page": chunk.get("page", 1),
            "chunk_id": full_chunk_id,       # registry ID (with prefix)
            "qdrant_id": qdrant_point_id,    # bare UUID for Qdrant cross-ref
            "text": chunk.get("text", ""),
        }
        points.append(
            VectorPoint(
                id=qdrant_point_id,
                vector=vector,
                payload=payload,
            )
        )

    log.info("index.upsert", collection=collection, count=len(points))
    vstore.upsert(collection, points)

    indexed_ids = [c["chunk_id"] for c in chunks]
    log.info("index.complete", collection=collection, indexed=len(indexed_ids))
    return indexed_ids


def _strip_prefix(prefixed_id: str) -> str:
    """Strip the type prefix from a registry ID to produce a bare UUID.

    Qdrant requires point IDs to be unsigned integers or bare UUIDs.
    Registry IDs look like 'chk_019f2610-...'; stripping the prefix and
    underscore gives '019f2610-...' which is a valid UUID string.
    """
    if "_" in prefixed_id:
        return prefixed_id.split("_", 1)[1]
    return prefixed_id
