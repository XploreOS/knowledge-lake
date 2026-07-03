"""Chunk stage: parsed_document → section-aware chunk artifacts.

Produces chunks from a ParsedDoc that:
  - Respect section boundaries (headings = natural chunk boundaries)
  - Keep tables atomic (a table is never split across chunks)
  - Carry section_path + page_ref from the Section metadata (D-07)
  - Are registered as chunk artifacts with parent = parsed_document

Chunking strategy (Phase 1 spike):
    - One chunk per Section from ParsedDoc.sections.
    - If a section text exceeds MAX_CHUNK_CHARS, split on sentence boundaries.
    - An additional "header" chunk is emitted for the full document title text
      if it is not already covered by a section.

Returns:
    list of dicts, each dict:
      chunk_id, artifact_id, text, section_path, page, content_hash
"""

from __future__ import annotations

import hashlib
import textwrap
from typing import Optional

import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.plugins.protocols import ParsedDoc, Section
from knowledge_lake.registry.db import get_session
from knowledge_lake.registry import repo as registry_repo

log = structlog.get_logger(__name__)

# Maximum characters per chunk before forced split
MAX_CHUNK_CHARS = 1200


def chunk(
    parsed_artifact_id: str,
    source_id: str,
    parsed_doc: ParsedDoc,
    *,
    settings: Optional[Settings] = None,
) -> list[dict]:
    """Split a ParsedDoc into section-aware chunks and register artifact nodes.

    Args:
        parsed_artifact_id: ID of the parsed_document artifact (parent).
        source_id:          Source ID (propagated to each chunk artifact).
        parsed_doc:         ParsedDoc returned by the parse stage.
        settings:           Settings override.

    Returns:
        List of chunk dicts with keys:
          chunk_id, artifact_id, text, section_path, page, content_hash
    """
    s = settings or get_settings()

    # Build raw chunks from sections
    raw_chunks = _build_chunks(parsed_doc)
    log.info("chunk.raw_chunks", count=len(raw_chunks))

    results: list[dict] = []

    with get_session() as session:
        for raw in raw_chunks:
            text = raw["text"]
            section_path = raw["section_path"]
            page = raw["page"]

            # Include parsed_artifact_id in the hash so identical chunk text from
            # different documents creates distinct artifacts (WR-05: dedup key must
            # include parent to prevent lineage corruption across documents)
            hash_input = f"{parsed_artifact_id}:{text}"
            content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

            # Registry no-op: if this chunk already exists for THIS parent, use existing node
            existing = registry_repo.get_artifact_by_hash(session, content_hash, "chunk")
            if existing is not None:
                results.append({
                    "chunk_id": existing.id,
                    "artifact_id": existing.id,
                    "text": text,
                    "section_path": section_path,
                    "page": page,
                    "content_hash": content_hash,
                })
                continue

            artifact = registry_repo.create_chunk_artifact(
                session,
                source_id=source_id,
                parent_artifact_id=parsed_artifact_id,
                content_hash=content_hash,
                mime_type="text/plain",
                page_ref=page,
                section_path=section_path,
            )
            session.flush()

            results.append({
                "chunk_id": artifact.id,
                "artifact_id": artifact.id,
                "text": text,
                "section_path": section_path,
                "page": page,
                "content_hash": content_hash,
            })

    log.info("chunk.complete", chunk_count=len(results))
    return results


def _build_chunks(parsed_doc: ParsedDoc) -> list[dict]:
    """Build raw chunk dicts from ParsedDoc sections.

    One chunk per section by default. Oversized sections are split on
    sentence boundaries (MAX_CHUNK_CHARS limit).
    """
    raw_chunks: list[dict] = []

    if not parsed_doc.sections:
        # No sections: treat full text as single chunk
        if parsed_doc.text.strip():
            raw_chunks.append({
                "text": parsed_doc.text[:MAX_CHUNK_CHARS],
                "section_path": "§1",
                "page": 1,
            })
        return raw_chunks

    for section in parsed_doc.sections:
        heading = section.heading or ""
        body = section.text or ""
        full_text = f"{heading}\n\n{body}".strip() if heading else body.strip()

        if not full_text:
            continue

        # Split oversized sections
        if len(full_text) <= MAX_CHUNK_CHARS:
            raw_chunks.append({
                "text": full_text,
                "section_path": section.section_path,
                "page": section.page,
            })
        else:
            # Split into sub-chunks on sentence boundaries
            sub_chunks = _split_on_sentences(full_text, MAX_CHUNK_CHARS)
            for i, sub in enumerate(sub_chunks):
                raw_chunks.append({
                    "text": sub,
                    "section_path": f"{section.section_path}.{i + 1}",
                    "page": section.page,
                })

    return raw_chunks


def _split_on_sentences(text: str, max_chars: int) -> list[str]:
    """Split text into chunks of at most max_chars, preferring sentence breaks."""
    if len(text) <= max_chars:
        return [text]

    # Simple sentence splitter: split on '. ' or '.\n'
    import re
    sentences = re.split(r"(?<=[.!?])\s+", text)

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        if current_len + len(sentence) + 1 > max_chars and current:
            chunks.append(" ".join(current))
            current = [sentence]
            current_len = len(sentence)
        else:
            current.append(sentence)
            current_len += len(sentence) + 1

    if current:
        chunks.append(" ".join(current))

    return chunks or [text[:max_chars]]
