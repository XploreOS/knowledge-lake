"""Parse stage: raw_document bytes → parsed_document artifact + ParsedDoc.

The parser plugin is resolved from settings (KLAKE_PARSER env var, default 'docling').
Parsed markdown/JSON is stored in the silver zone under silver/{source_id}/{hash}.{ext}.
A parsed_document artifact node is created with parent_artifact_id = raw_artifact.id.

Returns the parsed_document Artifact ORM object and the ParsedDoc struct.

Section persistence (Task 8, KL-09 follow-up):
    parse() ALSO serializes the full ParsedDoc (text + sections + metadata) to a
    JSON sidecar next to the markdown file in the silver zone
    (``{hash}.sections.json``), and records its URI in the parsed_document
    artifact's ``metadata_["sections_uri"]``. Without this, sections existed only
    in-memory for the duration of a single pipeline run — CLI entry points
    (klake chunk, klake tree-index) had no way to recover them short of
    re-parsing the raw document from scratch (~40s of Docling on a 19-page PDF).

    load_parsed_doc() rehydrates a ParsedDoc from the sidecar. reparse_from_raw()
    is the fallback for artifacts parsed BEFORE this change (no sidecar exists) —
    it re-parses the raw parent through the same parser-fallback chain parse()
    uses. Both are used by cli/app.py's cmd_chunk and cmd_tree_index.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict

import orjson
import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.pipeline.deterministic import extract_title
from knowledge_lake.pipeline.utils import uri_to_key as _uri_to_key
from knowledge_lake.plugins.protocols import ParsedDoc, Section
from knowledge_lake.plugins.resolver import parse_with_fallback
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.storage.s3 import _UNCLASSIFIED_DOMAIN, StorageBackend

log = structlog.get_logger(__name__)

# Silver zone bucket name (could be a separate bucket in prod; uses same for Phase 1)
_SILVER_PREFIX = "silver"

# Suffix for the sections sidecar written alongside the parsed markdown (Task 8).
# {content_hash}.md -> {content_hash}.sections.json, same silver-zone key prefix.
_SECTIONS_SIDECAR_SUFFIX = "sections.json"


# ── ParsedDoc <-> JSON sidecar (Task 8) ────────────────────────────────────────


def _serialize_parsed_doc(parsed_doc: ParsedDoc) -> bytes:
    """Serialize a ParsedDoc (text + sections + metadata) to sidecar JSON bytes."""
    return orjson.dumps({
        "text": parsed_doc.text,
        "sections": [asdict(section) for section in parsed_doc.sections],
        "metadata": parsed_doc.metadata,
    })


def _deserialize_parsed_doc(data: bytes) -> ParsedDoc:
    """Reconstruct a ParsedDoc from sidecar JSON bytes written by _serialize_parsed_doc."""
    obj = orjson.loads(data)
    sections = [Section(**s) for s in obj.get("sections", [])]
    return ParsedDoc(
        text=obj.get("text", ""),
        sections=sections,
        metadata=obj.get("metadata") or {},
    )


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
        sections_key = f"{_SILVER_PREFIX}/{domain}/{source_id}/{content_hash}.{_SECTIONS_SIDECAR_SUFFIX}"
        existing = registry_repo.get_artifact_by_hash(session, content_hash, "parsed_document")
        if existing is not None:
            log.info(
                "parse.no_op",
                content_hash=content_hash,
                existing_artifact_id=existing.id,
            )
            # Task 8 healing: the registry no-op means content is unchanged, but if
            # this existing artifact predates the sections sidecar (parsed before
            # Task 8), we already re-ran the full parser-fallback chain above and
            # have parsed_doc in memory — write the sidecar now instead of leaving
            # this artifact permanently stuck on the expensive reparse_from_raw
            # fallback every time a caller needs its sections. Best-effort: never
            # let a healing failure turn a successful no-op into an error.
            existing_metadata = existing.metadata_ or {}
            if not existing_metadata.get("sections_uri"):
                try:
                    sections_bytes = _serialize_parsed_doc(parsed_doc)
                    storage.put_object(sections_key, sections_bytes, tags={
                        "domain": domain,
                        "source_name": source_name,
                        "format": "json",
                        "artifact_type": "parsed_document_sections",
                    })
                    sections_uri = storage.object_uri(sections_key)
                    existing_metadata = {**existing_metadata, "sections_uri": sections_uri}
                    existing.metadata_ = existing_metadata
                    session.add(existing)
                    session.flush()
                    log.info(
                        "parse.healed_sections_sidecar",
                        existing_artifact_id=existing.id,
                        sections_uri=sections_uri,
                    )
                except Exception:
                    log.warning(
                        "parse.heal_sections_sidecar_failed",
                        existing_artifact_id=existing.id,
                        exc_info=True,
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

        # Sections sidecar (Task 8): full ParsedDoc (text + sections + metadata) as
        # JSON, alongside the markdown. Sections carry the whole document body via
        # Section.text (docling_parser.py populates it) — silver zone, not
        # metadata_/Postgres, so documents are never duplicated into the registry.
        sections_bytes = _serialize_parsed_doc(parsed_doc)
        storage.put_object(sections_key, sections_bytes, tags={
            "domain": domain,
            "source_name": source_name,
            "format": "json",
            "artifact_type": "parsed_document_sections",
        })
        sections_uri = storage.object_uri(sections_key)
        log.info(
            "parse.stored_sections_sidecar",
            sections_uri=sections_uri,
            sections=len(parsed_doc.sections),
        )

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
                "sections_uri": sections_uri,
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


# ── Section rehydration + re-parse fallback (Task 8, KL-09 follow-up) ─────────


def load_parsed_doc(
    parsed_artifact_id: str,
    *,
    settings: Settings | None = None,
) -> ParsedDoc | None:
    """Rehydrate a ParsedDoc from a parsed_document artifact's sections sidecar.

    Reads ``metadata_["sections_uri"]`` off the artifact and loads the JSON
    sidecar parse() writes to the silver zone. Returns None — never raises —
    when the artifact has no sidecar (parsed before Task 8) or the sidecar
    cannot be read; callers MUST fall back to reparse_from_raw() in that case.

    Args:
        parsed_artifact_id: ID of the parsed_document artifact to rehydrate.
        settings:           Settings override.

    Returns:
        The rehydrated ParsedDoc, or None if no usable sidecar exists.
    """
    s = settings or get_settings()
    storage = StorageBackend(s.storage)

    with get_session() as session:
        artifact = registry_repo.get_artifact(session, parsed_artifact_id)
        if artifact is None:
            log.warning(
                "parse.load_parsed_doc.artifact_missing",
                parsed_artifact_id=parsed_artifact_id,
            )
            return None
        sections_uri = (artifact.metadata_ or {}).get("sections_uri")

    if not sections_uri:
        log.info(
            "parse.load_parsed_doc.no_sidecar",
            parsed_artifact_id=parsed_artifact_id,
        )
        return None

    try:
        key = _uri_to_key(sections_uri)
        data = storage.get_object(key)
        parsed_doc = _deserialize_parsed_doc(data)
    except Exception:
        log.warning(
            "parse.load_parsed_doc.sidecar_read_failed",
            parsed_artifact_id=parsed_artifact_id,
            sections_uri=sections_uri,
            exc_info=True,
        )
        return None

    log.info(
        "parse.load_parsed_doc.sidecar_hit",
        parsed_artifact_id=parsed_artifact_id,
        sections=len(parsed_doc.sections),
    )
    return parsed_doc


def reparse_from_raw(
    parsed_artifact_id: str,
    source_id: str,
    *,
    settings: Settings | None = None,
) -> ParsedDoc:
    """Recover a ParsedDoc by re-parsing the raw_document parent (fallback).

    Only call this when load_parsed_doc() returns None — it re-runs the
    parser-fallback chain on the raw bytes, which is not cheap (Docling took
    ~40s on a 19-page PDF in testing). This is the ONLY way to recover real
    section structure for a parsed_document artifact created before Task 8
    (no sections sidecar was ever written for it).

    Args:
        parsed_artifact_id: ID of the parsed_document artifact to recover sections for.
        source_id:          Source ID that owns the parsed artifact (unused directly,
                             kept for call-site symmetry with parse()/chunk()/tree_index()).
        settings:            Settings override.

    Returns:
        A freshly re-parsed ParsedDoc with real section structure.

    Raises:
        ValueError: If the parsed artifact, its raw parent, or the raw
                    parent's storage_uri cannot be resolved.
    """
    s = settings or get_settings()
    storage = StorageBackend(s.storage)

    with get_session() as session:
        parsed_artifact = registry_repo.get_artifact(session, parsed_artifact_id)
        if parsed_artifact is None:
            raise ValueError(
                f"reparse_from_raw: parsed_artifact {parsed_artifact_id!r} not found in registry"
            )
        raw_artifact_id = parsed_artifact.parent_artifact_id
        if not raw_artifact_id:
            raise ValueError(
                f"reparse_from_raw: parsed_artifact {parsed_artifact_id!r} has no parent "
                "raw_document artifact — cannot re-parse to recover sections."
            )
        raw_artifact = registry_repo.get_artifact(session, raw_artifact_id)
        if raw_artifact is None:
            raise ValueError(f"reparse_from_raw: raw_artifact {raw_artifact_id!r} not found in registry")
        raw_storage_uri = raw_artifact.storage_uri
        if not raw_storage_uri:
            raise ValueError(f"reparse_from_raw: raw_artifact {raw_artifact_id!r} has no storage_uri")
        stored_mime = raw_artifact.mime_type
        if stored_mime in (None, "application/octet-stream"):
            from knowledge_lake.pipeline.ingest import _detect_mime_from_uri
            stored_mime = _detect_mime_from_uri(raw_storage_uri)
        mime_type = stored_mime or "application/pdf"

    raw_key = _uri_to_key(raw_storage_uri)
    raw_bytes = storage.get_object(raw_key)

    log.info(
        "parse.reparse_from_raw.start",
        parsed_artifact_id=parsed_artifact_id,
        raw_artifact_id=raw_artifact_id,
    )
    parsed_doc, parser_used, quality_score = parse_with_fallback(raw_bytes, mime_type, settings=s)
    log.info(
        "parse.reparse_from_raw.complete",
        parsed_artifact_id=parsed_artifact_id,
        sections=len(parsed_doc.sections),
        parser_used=parser_used,
        quality_score=quality_score,
    )
    return parsed_doc


# _uri_to_key is re-exported from pipeline.utils as _uri_to_key (imported above)
