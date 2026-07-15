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
  quality_score  — precedence: sibling curated_document's real column, falling back
                   to the sibling enriched_document's real column, falling back to
                   None (KL-04/05/06, 2026-07-15). Curate's DataTrove-style composite
                   (parse*0.30 + enrich*0.40 + filters*0.30) is the deterministic,
                   free quality gate — it now reaches search. The enriched
                   quality_score (LLM-judged, Bedrock-gated, costs money) remains the
                   fallback when curation hasn't run for a document. document_type/
                   keywords/title still come from enrichment metadata only — curation
                   does not carry those fields.
These four fields degrade gracefully to null/empty when neither enrichment nor
curation has run yet for the document — neither is a hard blocker to indexing (D-01).
Dagster-orchestrated runs now schedule enrich_document -> curate_document_asset ->
chunk_document via non-data deps= edges (KL-06, dagster_defs/assets.py) so the
scheduling race that produced a 21% swing in the same document's composite score
is closed for that execution path; this quality_score precedence resolution here
is what makes the *result* deterministic regardless of orchestration order.

Plus the source-metadata fields (PAYLOAD-01, D-01..D-04):
  source_id      — Artifact.source_id (foreign key to the source registry row)
  source_name    — Source.name (human-readable source name)
  source_url     — Source.url, or None if not set
  format         — Source.source_type (short format label: 'html', 'pdf', 'csv')
  tags           — Source.config['tags'] (list[str]), degrades to []
  title          — enriched_document metadata_['title'], or None
  organization   — Source.config['organization'], or None
All 7 fields degrade gracefully to None/[] when source row is absent or config
is empty (D-03). Only populated on chunks indexed after Phase 7 (D-13).

``collection`` remains the alias name applications pass unchanged; only the
resolution layer underneath changed to an alias-backed physical collection via
ensure_aliased_collection()/reindex() (D-06, INDEX-02).

Returns: list of chunk_ids indexed (same order as input chunks).
"""

from __future__ import annotations

import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.plugins.builtin.sparse_embedder import embed_sparse_doc
from knowledge_lake.plugins.protocols import VectorPoint
from knowledge_lake.plugins.resolver import get_vectorstore
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session

log = structlog.get_logger(__name__)


def _resolve_document_payload_fields(session, parsed_artifact_id: str) -> dict:
    """Resolve the per-document payload fields shared by every chunk of a document.

    Joins domain (Source.config['domain']), the Source row's 7 metadata fields
    (PAYLOAD-01), and the curated/enriched siblings once per document — not once
    per chunk (INDEX-01, D-01, PAYLOAD-01) — so index() and the reindex payload
    refresh (KL-06) share one join implementation instead of two.

    quality_score precedence (KL-04/05/06): curated_document's real column,
    falling back to enriched_document's real column, falling back to None.
    document_type/keywords/title still come only from enrichment metadata —
    curation carries no document_type/keywords/title.

    Must be called with an open Session; all attribute access happens inside
    this function to avoid DetachedInstanceError in callers.
    """
    parsed_artifact = registry_repo.get_artifact(session, parsed_artifact_id)
    source_id_val = parsed_artifact.source_id if parsed_artifact is not None else None
    domain = (
        registry_repo.get_domain_for_source(session, source_id_val)
        if source_id_val is not None
        else None
    )

    # Fetch the Source row for the 7 new source-metadata payload fields (PAYLOAD-01, D-02).
    source = (
        registry_repo.get_source(session, source_id_val)
        if source_id_val is not None
        else None
    )
    _sc = (source.config or {}) if source is not None else {}
    source_name = source.name if source is not None else None
    source_url = source.url if source is not None else None
    fmt = source.source_type if source is not None else None  # D-04: source_type IS the format label
    tags = _sc.get("tags", [])
    organization = _sc.get("organization")

    enriched = registry_repo.get_enriched_artifact_for_parsed(session, parsed_artifact_id)
    if enriched is not None:
        enrichment_metadata = enriched.metadata_ or {}
        enriched_quality_score = enriched.quality_score
    else:
        enrichment_metadata = {}
        enriched_quality_score = None

    curated = registry_repo.get_curated_artifact_for_parsed(session, parsed_artifact_id)
    curated_quality_score = curated.quality_score if curated is not None else None

    # KL-04/05/06 precedence: curated composite wins; enriched is the fallback.
    quality_score = (
        curated_quality_score if curated_quality_score is not None else enriched_quality_score
    )

    return {
        "domain": domain,
        "document_type": enrichment_metadata.get("document_type"),
        "keywords": enrichment_metadata.get("keywords", []),
        "quality_score": quality_score,
        "source_id": source_id_val,
        "source_name": source_name,
        "source_url": source_url,
        "format": fmt,
        "tags": tags,
        "title": enrichment_metadata.get("title"),
        "organization": organization,
    }


def index(
    chunks: list[dict],
    vectors: list[list[float]],
    dim: int,
    parsed_artifact_id: str,
    *,
    collection: str = "klake_chunks",
    settings: Settings | None = None,
) -> list[str]:
    """Upsert chunk vectors into the vector store with citation + enrichment payload.

    Bootstraps the alias-backed collection idempotently before upserting, and
    joins in domain/document_type/keywords/quality_score from the sibling
    curated/enriched artifacts (when they exist) before building each chunk's
    payload — quality_score prefers the curated composite over the enriched
    LLM score (KL-04/05/06); see module docstring for the full precedence.

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

    if len(chunks) != len(vectors):
        raise ValueError(
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
            # ORDERING INVARIANT: commit the alias registration row HERE, before
            # vstore.upsert runs in the separate session block below.  This guarantees
            # that even if the Qdrant upsert raises (e.g. server timeout), the alias
            # row is already durable in Postgres.  A future refactor must NOT move
            # vstore.upsert inside this session block — doing so would roll back the
            # alias registration on any Qdrant failure and cause ensure_aliased_collection
            # to create "v2" on the next call instead of reusing "v1".
            session.commit()

    # Resolve domain, source metadata, and curated/enriched quality_score
    # precedence once per index() call — not once per chunk (INDEX-01, D-01,
    # PAYLOAD-01) — via the shared helper (KL-04/05/06).
    with get_session() as session:
        fields = _resolve_document_payload_fields(session, parsed_artifact_id)

    domain = fields["domain"]
    source_id_val = fields["source_id"]
    source_name = fields["source_name"]
    source_url = fields["source_url"]
    fmt = fields["format"]
    tags = fields["tags"]
    organization = fields["organization"]
    document_type = fields["document_type"]
    keywords = fields["keywords"]
    quality_score = fields["quality_score"]
    title = fields["title"]

    # Build VectorPoints with citation + enrichment payload.
    # Qdrant requires point IDs to be unsigned integers or bare UUIDs —
    # our chunk IDs are prefixed (e.g. "chk_0196a2c1-...").  We strip the
    # prefix for the Qdrant point ID and preserve the full prefixed ID in the
    # payload as chunk_id so the CLI/lineage can resolve it back to the registry.
    points: list[VectorPoint] = []
    for chunk, vector in zip(chunks, vectors, strict=True):
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
            "document_type": document_type,
            "keywords": keywords,
            "quality_score": quality_score,
            # PAYLOAD-01: 7 new source-metadata fields (D-01..D-04, D-13).
            # Populated only on chunks indexed after Phase 7; degrade to None/[].
            "source_id": source_id_val,
            "source_name": source_name,
            "source_url": source_url,
            "format": fmt,
            "tags": tags,
            "title": title,
            "organization": organization,
        }
        points.append(
            VectorPoint(
                id=qdrant_point_id,
                vector=vector,
                payload=payload,
                sparse=embed_sparse_doc(chunk.get("text", "")),
            )
        )

    log.info("index.upsert", collection=collection, count=len(points))
    vstore.upsert(collection, points)

    indexed_ids = [c["chunk_id"] for c in chunks]
    log.info("index.complete", collection=collection, indexed=len(indexed_ids))
    return indexed_ids


def _build_payload_refresh_fn(settings: Settings | None = None):
    """Build a ``payload_resolve_fn`` for refresh_all_points_payload (KL-06 repair path).

    Re-derives domain/document_type/keywords/quality_score/source-metadata
    fields per point from the registry via the point's existing
    payload['document'] (the parsed_artifact_id), leaving citation fields
    (document, section_path, page, chunk_id, qdrant_id, text) untouched.

    Caches per-document field resolution across points — a reindex commonly
    touches many chunks that share the same document, so this avoids an
    N-queries-per-chunk join (mirrors index()'s once-per-document join,
    INDEX-01).

    Note: ``settings`` is accepted for interface symmetry with the other
    reindex upsert_fn builders but is currently unused — get_session() reads
    the process-global registry connection, same as index()/reindex_collection.
    """
    cache: dict[str, dict] = {}

    def _resolve(old_payload: dict) -> dict:
        parsed_artifact_id = old_payload.get("document")
        if not parsed_artifact_id:
            # No document reference on this point — cannot re-resolve;
            # preserve it unchanged rather than dropping fields.
            return old_payload
        if parsed_artifact_id not in cache:
            with get_session() as session:
                cache[parsed_artifact_id] = _resolve_document_payload_fields(
                    session, parsed_artifact_id
                )
        new_payload = dict(old_payload)
        new_payload.update(cache[parsed_artifact_id])
        return new_payload

    return _resolve


def reindex_collection(
    collection: str = "klake_chunks",
    *,
    hybrid: bool = False,
    refresh_payload: bool = False,
    settings: Settings | None = None,
) -> dict:
    """Zero-downtime reindex of an alias-backed collection (INDEX-02, D-06).

    Creates the next versioned physical collection, populates it, atomically
    repoints the alias, and registers the new alias->physical mapping in the
    registry. The prior physical collection is retained — never auto-dropped.

    When ``hybrid=False`` and ``refresh_payload=False`` (default):
        Copies every existing point via copy_all_points() — the existing
        behavior, unchanged for back-compatibility.

    When ``refresh_payload=True`` (opt-in repair path, KL-06, default OFF):
        Re-derives each point's payload from the registry (domain,
        document_type, keywords, quality_score with the curated/enriched
        precedence, and the 7 source-metadata fields) instead of copying it
        verbatim, via vstore.refresh_all_points_payload(). Vectors are reused
        unchanged — this is a payload repair, not a re-embedding. This is
        what lets a chunk indexed before enrichment/curation ran pick up the
        real quality_score without a full re-ingest.

    When ``hybrid=True`` (operator-triggered live re-embedding migration):
        1. Asserts the running Qdrant server is >= 1.10 (D-07 preflight) —
           aborts loudly before touching any data if the server is too old.
        2. Scrolls existing points and synthesizes sparse vectors from their
           payload['text'] via embed_sparse_doc, writing named {dense+sparse}
           points to the new physical collection via vstore.reembed_all_points.
        3. Delegates the count-parity gate and alias swap to vstore.reindex —
           no duplication here (Plan 10-06 owns the safety contract).
        No new get_session block is needed for chunk text — text is read
        directly from the Qdrant scroll payload['text'] (research simplification).
        ``refresh_payload`` is ignored when ``hybrid=True`` — the hybrid path
        does not currently also refresh the payload; reindex twice (hybrid
        first, refresh_payload second) if both are needed.

    Args:
        collection:      Qdrant alias name to reindex (default: 'klake_chunks').
        hybrid:          When True, perform the re-embedding migration with the
                         D-07 server preflight and reembed_all_points upsert_fn.
        refresh_payload: When True (and hybrid=False), re-derive each point's
                         payload from the registry instead of copying it
                         verbatim (KL-06). Default False preserves today's
                         copy behavior.
        settings:        Settings override.

    Returns:
        {"collection": ..., "new_physical": ..., "old_physical": ...}
    """
    s = settings or get_settings()
    vstore = get_vectorstore(s)

    dim = vstore.get_collection_dim(collection)

    if hybrid:
        # D-07: preflight — assert server >= 1.10 BEFORE creating any collection
        vstore.assert_server_supports_hybrid()

        def _re_embed_fn(new_physical: str) -> tuple[int, int]:
            # D-05: re-embed reads payload['text'] from the Qdrant scroll;
            # no registry join needed for chunk text.
            # Returns (total, skipped) so reindex()'s D-06 parity gate can
            # account for corrupt source points with no dense vector (WR-04).
            return vstore.reembed_all_points(collection, new_physical, embed_sparse_doc)

        upsert_fn = _re_embed_fn
    elif refresh_payload:
        resolve_fn = _build_payload_refresh_fn(s)

        def _refresh_fn(new_physical: str) -> int:
            return vstore.refresh_all_points_payload(collection, new_physical, resolve_fn)

        upsert_fn = _refresh_fn
    else:
        def _copy_fn(new_physical: str) -> None:
            vstore.copy_all_points(collection, new_physical)

        upsert_fn = _copy_fn

    log.info(
        "index.reindex.start",
        collection=collection,
        dim=dim,
        hybrid=hybrid,
        refresh_payload=refresh_payload,
    )
    result = vstore.reindex(collection, dim=dim, upsert_fn=upsert_fn)

    with get_session() as session:
        registry_repo.register_vector_collection(
            session,
            alias_name=collection,
            physical_collection=result["new_physical"],
            dim=dim,
        )
        session.commit()

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
