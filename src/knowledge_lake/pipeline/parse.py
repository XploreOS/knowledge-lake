"""Parse stage: raw_document bytes → parsed_document artifact + ParsedDoc.

The parser plugin is resolved from settings (KLAKE_PARSER env var, default 'docling').
Parsed markdown/JSON is stored in the silver zone under silver/{source_id}/{hash}.{ext}.
A parsed_document artifact node is created with parent_artifact_id = raw_artifact.id.

Returns the parsed_document Artifact ORM object and the ParsedDoc struct.
"""

from __future__ import annotations

import hashlib

import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.pipeline.deterministic import extract_title
from knowledge_lake.pipeline.utils import uri_to_key as _uri_to_key
from knowledge_lake.plugins.protocols import ParsedDoc
from knowledge_lake.plugins.resolver import parse_with_fallback
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.storage.s3 import _UNCLASSIFIED_DOMAIN, StorageBackend

log = structlog.get_logger(__name__)

# Silver zone bucket name (could be a separate bucket in prod; uses same for Phase 1)
_SILVER_PREFIX = "silver"


def parse(
    raw_artifact_id: str,
    source_id: str,
    *,
    mime_type: str | None = None,
    settings: Settings | None = None,
) -> tuple[dict, ParsedDoc]:
    """Parse raw document bytes into a ParsedDoc and create a parsed_document artifact.

    Args:
        raw_artifact_id: ID of the raw_document artifact to parse.
        source_id:       Source ID (parent of the raw artifact).
        mime_type:       MIME type override. If None, the stored artifact mime_type is
                         used; falls back to 'application/pdf' if neither is set.
        settings:        Settings override.

    Returns:
        Tuple of:
          - dict with artifact_id, storage_uri, content_hash
          - ParsedDoc (text + sections with citation metadata)

    Raises:
        LookupError: If the parser plugin is not found.
        ValueError:  If the raw artifact does not exist or bytes cannot be retrieved.
    """
    s = settings or get_settings()
    storage = StorageBackend(s.storage)

    # Load raw bytes from storage
    with get_session() as session:
        raw_artifact = registry_repo.get_artifact(session, raw_artifact_id)
        if raw_artifact is None:
            raise ValueError(f"parse: raw_artifact {raw_artifact_id!r} not found in registry")
        storage_uri = raw_artifact.storage_uri
        if not storage_uri:
            raise ValueError(
                f"parse: raw_artifact {raw_artifact_id!r} has no storage_uri"
            )
        # Resolve effective mime_type: caller override > stored artifact > URI extension > fallback
        stored_mime = raw_artifact.mime_type
        if stored_mime in (None, "application/octet-stream"):
            from knowledge_lake.pipeline.ingest import _detect_mime_from_uri
            stored_mime = _detect_mime_from_uri(storage_uri)
        effective_mime = mime_type or stored_mime or "application/pdf"

    mime_type = effective_mime  # rebind for use below
    log.info("parse.start", raw_artifact_id=raw_artifact_id, mime_type=mime_type)

    # Retrieve raw bytes from storage (s3://bucket/key → key)
    key = _uri_to_key(storage_uri)
    raw_bytes = storage.get_object(key)
    log.info("parse.loaded_raw", size=len(raw_bytes))

    # Run the parser fallback chain (D-01, D-02)
    parsed_doc, parser_used, quality_score = parse_with_fallback(
        raw_bytes, mime_type, settings=s
    )
    log.info(
        "parse.parsed",
        sections=len(parsed_doc.sections),
        text_len=len(parsed_doc.text),
        parser_used=parser_used,
        quality_score=quality_score,
    )

    # Content-hash the parsed text for dedup and silver-zone key
    parsed_bytes = parsed_doc.text.encode("utf-8")
    content_hash = hashlib.sha256(parsed_bytes).hexdigest()

    # Deterministic title, computed once here and persisted into the
    # parsed_document artifact's metadata_ so callers that only have the
    # artifact ID (no in-memory ParsedDoc, e.g. CLI/API enrich entry points —
    # CR-01) can still recover a real title instead of "" (parsed_doc.metadata
    # never carries a "title" key from any parser plugin; sections are only
    # available in-memory and are never persisted separately).
    title = extract_title(parsed_doc.metadata, parsed_doc.sections)

    # Dedup check and artifact creation in a single session block to prevent race
    # conditions under concurrent execution (CR-02). Both the read and the write
    # happen within the same session, making the dedup + insert effectively atomic.
    with get_session() as session:
        source_obj = registry_repo.get_source(session, source_id)
        source_name = source_obj.name if source_obj else "unknown"
        domain = (source_obj.config or {}).get("domain") or _UNCLASSIFIED_DOMAIN if source_obj else _UNCLASSIFIED_DOMAIN
        silver_key = f"{_SILVER_PREFIX}/{domain}/{source_id}/{content_hash}.md"
        existing = registry_repo.get_artifact_by_hash(session, content_hash, "parsed_document")
        if existing is not None:
            log.info(
                "parse.no_op",
                content_hash=content_hash,
                existing_artifact_id=existing.id,
            )
            return {
                "artifact_id": existing.id,
                "storage_uri": existing.storage_uri,
                "content_hash": existing.content_hash,
            }, parsed_doc

        # Store parsed markdown in silver zone (outside DB transaction but within
        # the same logical block — S3 put_object is idempotent for the same key)
        storage.put_object(silver_key, parsed_bytes, tags={
            "domain": domain,
            "source_name": source_name,
            "format": "md",
            "artifact_type": "parsed_document",
        })
        silver_uri = storage.object_uri(silver_key)
        log.info("parse.stored_silver", silver_uri=silver_uri)

        artifact = registry_repo.create_parsed_artifact(
            session,
            source_id=source_id,
            parent_artifact_id=raw_artifact_id,
            content_hash=content_hash,
            storage_uri=silver_uri,
            mime_type="text/markdown",
            metadata={
                "quality_score": quality_score,
                "parser_used": parser_used,
                "title": title,
            },
        )
        session.flush()
        result = {
            "artifact_id": artifact.id,
            "storage_uri": artifact.storage_uri,
            "content_hash": artifact.content_hash,
            "quality_score": quality_score,
            "parser_used": parser_used,
        }

    log.info("parse.complete", artifact_id=result["artifact_id"])
    return result, parsed_doc


# _uri_to_key is re-exported from pipeline.utils as _uri_to_key (imported above)
