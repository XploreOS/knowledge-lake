"""Pipeline orchestrator: runs ingest→parse→chunk→embed→index in-process.

This is the thin coordinator that chains the plain-function stages for Plan 05.
No Dagster definitions here — that is Plan 06 (D-01, Pitfall 1: prove flow first).

The CLI (klake ingest-url, klake demo) calls run_document() to process a document
end-to-end.  Dagster's software-defined assets in Plan 06 will wrap these same calls.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.pipeline.ingest import ingest_file, ingest_url
from knowledge_lake.pipeline.parse import parse
from knowledge_lake.pipeline.chunk import chunk
from knowledge_lake.pipeline.embed import embed
from knowledge_lake.pipeline.index import index

log = structlog.get_logger(__name__)

# Default Qdrant collection for the spike
DEFAULT_COLLECTION = "klake_chunks"


def run_document(
    *,
    url: Optional[str] = None,
    fixture_path: Optional[Path] = None,
    source_name: Optional[str] = None,
    collection: str = DEFAULT_COLLECTION,
    mime_type: str = "application/pdf",
    settings: Optional[Settings] = None,
) -> dict:
    """Orchestrate the full pipeline for a single document.

    Exactly one of url or fixture_path must be provided.

    Stages:
      1. ingest: download URL or load file → raw_document artifact
      2. parse:  bytes → ParsedDoc + parsed_document artifact
      3. chunk:  ParsedDoc → section-aware chunk artifacts
      4. embed:  chunk texts → dense vectors
      5. index:  upsert vectors with citation payload into Qdrant

    Args:
        url:          https:// URL to ingest (SSRF-checked; only https allowed).
        fixture_path: Local file path for hermetic fixture testing.
        source_name:  Human-readable name for the source (auto-inferred if None).
        collection:   Qdrant collection to index into.
        mime_type:    MIME type of the document.
        settings:     Settings override.

    Returns:
        dict with:
          source_id, raw_artifact_id, parsed_artifact_id,
          chunk_artifact_ids (list), collection, chunk_count

    Raises:
        ValueError: If neither url nor fixture_path is given, or if both are given.
    """
    if url is None and fixture_path is None:
        raise ValueError("run_document: exactly one of url or fixture_path must be provided")
    if url is not None and fixture_path is not None:
        raise ValueError("run_document: provide either url or fixture_path, not both")

    s = settings or get_settings()

    # ── Stage 1: Ingest ────────────────────────────────────────────────────────
    if url is not None:
        effective_name = source_name or _name_from_url(url)
        log.info("run_document.ingest_url", url=url)
        ingest_result = ingest_url(url, effective_name, mime_type=mime_type, settings=s)
    else:
        effective_name = source_name or (fixture_path.stem if fixture_path else "fixture")
        log.info("run_document.ingest_file", path=str(fixture_path))
        ingest_result = ingest_file(
            fixture_path,  # type: ignore[arg-type]
            effective_name,
            mime_type=mime_type,
            settings=s,
        )

    source_id = ingest_result["source_id"]
    raw_artifact_id = ingest_result["artifact_id"]
    log.info("run_document.ingest_done", source_id=source_id, raw_artifact_id=raw_artifact_id)

    # ── Stage 2: Parse ────────────────────────────────────────────────────────
    parse_result, parsed_doc = parse(
        raw_artifact_id,
        source_id,
        mime_type=mime_type,
        settings=s,
    )
    parsed_artifact_id = parse_result["artifact_id"]
    log.info(
        "run_document.parse_done",
        parsed_artifact_id=parsed_artifact_id,
        sections=len(parsed_doc.sections),
    )

    # ── Stage 3: Chunk ────────────────────────────────────────────────────────
    chunks = chunk(parsed_artifact_id, source_id, parsed_doc, settings=s)
    log.info("run_document.chunk_done", chunk_count=len(chunks))

    # ── Stage 4: Embed ────────────────────────────────────────────────────────
    vectors, dim = embed(chunks, settings=s)
    log.info("run_document.embed_done", dim=dim)

    # ── Stage 5: Index ────────────────────────────────────────────────────────
    indexed_ids = index(
        chunks,
        vectors,
        dim,
        parsed_artifact_id,
        collection=collection,
        settings=s,
    )
    log.info("run_document.index_done", indexed=len(indexed_ids), collection=collection)

    result = {
        "source_id": source_id,
        "raw_artifact_id": raw_artifact_id,
        "parsed_artifact_id": parsed_artifact_id,
        "chunk_artifact_ids": indexed_ids,
        "collection": collection,
        "chunk_count": len(indexed_ids),
    }

    log.info("run_document.complete", **{k: v for k, v in result.items() if k != "chunk_artifact_ids"})
    return result


def _name_from_url(url: str) -> str:
    """Derive a human-readable source name from a URL."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    name = path.split("/")[-1] if path else parsed.netloc
    return name.replace("-", " ").replace("_", " ").replace(".", " ").title() or "Web Source"
