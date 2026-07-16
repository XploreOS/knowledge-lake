"""Pipeline service function: process_crawled (D-05, MCP-01).

Extracted from ``cli/app.py:cmd_process_crawled`` so the CLI, API, and MCP tool
can all call one implementation (one function, many callers — D-03).

Rows are materialized to tuples inside the ``get_session()`` block
(DetachedInstanceError guard, PAYLOAD-01).

CLEAN-02: runs a ``clean()`` stage between ``parse()`` and ``chunk()`` so this
CLI/API/MCP-shared path produces chunks from cleaned text, matching the
Dagster ``clean_document -> chunk_document`` path (no shortcut/bypass).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def process_crawled(
    *,
    source_id: str | None = None,
    limit: int = 100,
    collection: str = "klake_chunks",
) -> dict:
    """Process crawled raw_document artifacts through parse→clean→chunk→embed→index.

    Finds all ``raw_document`` artifacts that have no corresponding
    ``parsed_document`` child and runs the full pipeline on each.  Useful
    after bulk crawling to convert raw HTML into searchable vector chunks.

    Args:
        source_id: When set, restrict processing to raw docs from this source.
        limit:     Maximum number of raw documents to process (default 100).
        collection: Qdrant collection to index chunks into (default
                    ``klake_chunks``).

    Returns:
        A dict with integer counts::

            {
                "processed":      <int>,   # successfully processed docs
                "chunks_indexed": <int>,   # total chunks upserted into Qdrant
                "failed":         <int>,   # docs that raised an exception
            }

    Raises:
        Any exception from the parse/chunk/embed/index pipeline propagates as-is
        for unexpected errors; expected per-doc failures are caught, counted, and
        included in ``"failed"``.
    """
    from sqlalchemy import and_, select
    from sqlalchemy.orm import aliased

    from knowledge_lake.pipeline.chunk import chunk
    from knowledge_lake.pipeline.clean import clean
    from knowledge_lake.pipeline.embed import embed
    from knowledge_lake.pipeline.index import index
    from knowledge_lake.pipeline.ingest import _detect_mime_from_uri
    from knowledge_lake.pipeline.parse import parse
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.models import Artifact

    with get_session() as session:
        # Find raw_documents that have no parsed_document child.
        # A parsed child has parent_artifact_id pointing to the raw doc.
        ParsedChild = aliased(Artifact)
        has_parsed_child = (
            select(ParsedChild.id)
            .where(
                and_(
                    ParsedChild.parent_artifact_id == Artifact.id,
                    ParsedChild.artifact_type == "parsed_document",
                )
            )
            .correlate(Artifact)
            .exists()
        )

        stmt = (
            select(Artifact)
            .where(Artifact.artifact_type == "raw_document")
            .where(~has_parsed_child)
        )
        if source_id:
            stmt = stmt.where(Artifact.source_id == source_id)
        stmt = stmt.order_by(Artifact.created_at.desc()).limit(limit)

        unprocessed = session.execute(stmt).scalars().all()
        # Materialize to tuples inside the session — DetachedInstanceError guard (PAYLOAD-01).
        raw_docs = [(a.id, a.source_id, a.storage_uri, a.mime_type) for a in unprocessed]

    if not raw_docs:
        return {"processed": 0, "chunks_indexed": 0, "failed": 0}

    processed = 0
    failed = 0
    total_chunks = 0

    for raw_id, src_id, storage_uri, stored_mime in raw_docs:
        # Detect mime from storage URI if not set
        mime = stored_mime
        if not mime or mime == "application/octet-stream":
            mime = _detect_mime_from_uri(storage_uri or "")

        try:
            parse_result, parsed_doc = parse(raw_id, src_id, mime_type=mime)
            parsed_id = parse_result["artifact_id"]

            clean_result = clean(parsed_id, src_id, parsed_doc=parsed_doc)
            cleaned_doc = clean_result["cleaned_doc"]

            chunks_list = chunk(parsed_id, src_id, cleaned_doc)
            if not chunks_list:
                processed += 1
                continue

            vectors, dim = embed(chunks_list)
            index(chunks_list, vectors, dim, parsed_id, collection=collection)

            processed += 1
            total_chunks += len(chunks_list)
        except Exception:
            # Keep the batch resilient but observable: record the artifact id,
            # exception type, and traceback so a systemic outage (Qdrant down,
            # OOM in embed) is diagnosable rather than a bare ``failed`` count.
            failed += 1
            log.warning("process_crawled: doc %s failed", raw_id, exc_info=True)

    return {"processed": processed, "chunks_indexed": total_chunks, "failed": failed}
