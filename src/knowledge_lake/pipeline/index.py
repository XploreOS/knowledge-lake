"""Index stage: upsert chunk vectors with citation payload into Qdrant.

The vector store plugin is resolved from settings (KLAKE_VECTORSTORE, default 'qdrant').
Each chunk's VectorPoint payload carries the citation fields (D-07, D-14):
  document     — parsed_document artifact ID (so callers can fetch parsed text)
  section_path — section path string (e.g. '§1 Administrative Safeguards')
  page         — 1-indexed page number
  chunk_id     — chunk artifact ID (matches the point ID)
  text         — the chunk text (for snippet rendering without a second lookup)

Plus the enrichment-derived filterable fields (D-07, INDEX-01):
  domain         — Source.config['domain'] (never a Source.domain/Artifact column, RESEARCH.md Pitfall 4)
  document_type  — from the sibling enriched_document artifact's metadata_, or None
  keywords       — from the sibling enriched_document artifact's metadata_, or []
  quality_score  — from the sibling enriched_document artifact's real column, or None
These four fields degrade gracefully to null/empty when no enrichment has run
yet for the document — enrichment is never a hard blocker to indexing (D-01).

``collection`` remains the alias name applications pass unchanged; only the
resolution layer underneath changed to an alias-backed physical collection via
ensure_aliased_collection()/reindex() (D-06, INDEX-02).

Returns: list of chunk_ids indexed (same order as input chunks).
"""

from __future__ import annotations

from typing import Optional

import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.plugins.protocols import VectorPoint
from knowledge_lake.plugins.resolver import get_vectorstore
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session

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
    """Upsert chunk vectors into the vector store with citation + enrichment payload.

    Bootstraps the alias-backed collection idempotently before upserting, and
    joins in domain/document_type/keywords/quality_score from the sibling
    enrichment (when one exists) before building each chunk's payload.

    Args:
        chunks:              List of chunk dicts from the chunk stage.
        vectors:             Embedding vectors (one per chunk, same order).
        dim:                 Embedding dimension (for collection setup).
        parsed_artifact_id:  ID of the parsed_document artifact (for 'document' payload).
        collection:          Qdrant alias name (default: 'klake_chunks').
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

    log.info("index.ensure_aliased_collection", collection=collection, dim=dim)
    physical, created = vstore.ensure_aliased_collection(collection, dim=dim)
    if created:
        with get_session() as session:
            registry_repo.register_vector_collection(
                session, alias_name=collection, physical_collection=physical, dim=dim
            )
            session.flush()

    # Resolve domain (Source.config['domain']) and the sibling enrichment
    # (parsed_document -> cleaned_document -> enriched_document) once per
    # index() call, not once per chunk (INDEX-01, D-07).
    with get_session() as session:
        parsed_artifact = registry_repo.get_artifact(session, parsed_artifact_id)
        domain = (
            registry_repo.get_domain_for_source(session, parsed_artifact.source_id)
            if parsed_artifact is not None
            else None
        )

        enriched = registry_repo.get_enriched_artifact_for_parsed(session, parsed_artifact_id)
        if enriched is not None:
            enrichment_metadata = enriched.metadata_ or {}
            quality_score = enriched.quality_score
        else:
            enrichment_metadata = {}
            quality_score = None

    # Build VectorPoints with citation + enrichment payload.
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
            "domain": domain,
            "document_type": enrichment_metadata.get("document_type"),
            "keywords": enrichment_metadata.get("keywords", []),
            "quality_score": quality_score,
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


def reindex_collection(
    collection: str = "klake_chunks",
    *,
    settings: Optional[Settings] = None,
) -> dict:
    """Zero-downtime reindex of an alias-backed collection (INDEX-02, D-06).

    Creates the next versioned physical collection, copies every existing
    point into it via copy_all_points(), atomically repoints the alias, and
    registers the new alias->physical mapping in the registry. The prior
    physical collection is retained — never auto-dropped.

    Args:
        collection: Qdrant alias name to reindex (default: 'klake_chunks').
        settings:   Settings override.

    Returns:
        {"collection": ..., "new_physical": ..., "old_physical": ...}
    """
    s = settings or get_settings()
    vstore = get_vectorstore(s)

    dim = vstore.get_collection_dim(collection)

    def _copy_fn(new_physical: str) -> None:
        vstore.copy_all_points(collection, new_physical)

    log.info("index.reindex.start", collection=collection, dim=dim)
    result = vstore.reindex(collection, dim=dim, upsert_fn=_copy_fn)

    with get_session() as session:
        registry_repo.register_vector_collection(
            session,
            alias_name=collection,
            physical_collection=result["new_physical"],
            dim=dim,
        )
        session.flush()

    log.info(
        "index.reindex.complete",
        collection=collection,
        new_physical=result["new_physical"],
        old_physical=result["old_physical"],
    )
    return {
        "collection": collection,
        "new_physical": result["new_physical"],
        "old_physical": result["old_physical"],
    }


def _strip_prefix(prefixed_id: str) -> str:
    """Strip the type prefix from a registry ID to produce a bare UUID.

    Qdrant requires point IDs to be unsigned integers or bare UUIDs.
    Registry IDs look like 'chk_019f2610-...'; stripping the prefix and
    underscore gives '019f2610-...' which is a valid UUID string.
    """
    if "_" in prefixed_id:
        return prefixed_id.split("_", 1)[1]
    return prefixed_id
