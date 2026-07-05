"""Clean stage: parsed_document artifact → cleaned_document artifact.

Performs boilerplate removal, whitespace normalization, language detection,
and exact/near-duplicate flagging (CLEAN-01..03). Raw zone is never touched —
this stage reads from and writes to the silver zone only.

T-03-06 (DoS — transient LSH corpus scan): The near-duplicate check builds an
in-memory MinHash LSH from all existing cleaned artifacts per clean() call.
This is O(n) per call — acceptable for Phase 3 MVP corpus sizes (< 10,000
documents). Phase 5 DataTrove pipeline replaces this with batch dedup.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

import structlog
from datasketch import MinHash, MinHashLSH

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.pipeline.utils import uri_to_key as _uri_to_key
from knowledge_lake.registry.db import get_session
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.storage.s3 import StorageBackend

log = structlog.get_logger(__name__)

_SILVER_PREFIX = "silver"

# ── Boilerplate patterns ──────────────────────────────────────────────────────
#
# All patterns are line-level and only match entire lines of boilerplate.
# Inline citations like "(HHS, 2023)", "[1]", or "see §3.2" appear mid-sentence
# and will not match these patterns (T-03-07).

BOILERPLATE_PATTERNS: list[re.Pattern] = [
    # Page headers/footers: "Page 1 of 5" or a bare page number on its own line
    re.compile(r"^(?:Page \d+ of \d+|\d+)\s*$", re.MULTILINE),
    # Cookie/privacy banners
    re.compile(
        r"(?i)(?:this site uses cookies|accept all cookies|cookie policy)[^\n]*$",
        re.MULTILINE,
    ),
    # Navigation elements from HTML crawls (entire line only)
    re.compile(
        r"(?im)^(?:home|about us|contact|sitemap|skip to (?:main )?content)\s*$",
    ),
    # Repeated copyright/disclaimer lines
    re.compile(r"(?i)^(?:disclaimer|copyright \d{4})[^\n]*$", re.MULTILINE),
]


# ── Text cleaning helpers ─────────────────────────────────────────────────────


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace in cleaned text.

    1. Strip trailing whitespace from each line.
    2. Collapse 3+ consecutive blank lines to exactly 2.
    3. Strip leading/trailing whitespace from the full string.
    """
    # Strip trailing whitespace per line
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    # Collapse 3+ consecutive newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def remove_boilerplate(text: str) -> str:
    """Remove common boilerplate patterns from cleaned text.

    Applies each pattern in BOILERPLATE_PATTERNS via substitution, then
    normalizes whitespace. Inline citations are preserved because all patterns
    are anchored to full lines (T-03-07).
    """
    for pattern in BOILERPLATE_PATTERNS:
        text = pattern.sub("", text)
    return _normalize_whitespace(text)


# ── Language detection ────────────────────────────────────────────────────────


def detect_language(text: str) -> str:
    """Detect the language of text and return an ISO 639-1 code.

    Uses lingua-language-detector (local ML model — no external HTTP call,
    T-03-08). Detects English, Spanish, French, German, and Portuguese.
    Falls back to 'unknown' on empty text, undetected language, or ImportError.

    Args:
        text: The text to detect language for.

    Returns:
        ISO 639-1 code as lowercase string, e.g. 'en', 'es', or 'unknown'.
    """
    if not text or not text.strip():
        return "unknown"

    try:
        from lingua import Language, LanguageDetectorBuilder  # noqa: PLC0415

        detector = LanguageDetectorBuilder.from_languages(
            Language.ENGLISH,
            Language.SPANISH,
            Language.FRENCH,
            Language.GERMAN,
            Language.PORTUGUESE,
        ).build()

        detected = detector.detect_language_of(text[:2000])
        if detected is None:
            return "unknown"
        return detected.iso_code_639_1.name.lower()

    except ImportError:
        log.warning("lingua_not_available", msg="Install lingua-language-detector for language detection")
        return "unknown"
    except Exception as exc:  # noqa: BLE001
        log.warning("language_detection_error", error=str(exc))
        return "unknown"


# ── MinHash computation ───────────────────────────────────────────────────────


def compute_minhash(text: str, num_perm: int = 128, shingle_size: int = 5) -> MinHash:
    """Compute a MinHash signature for near-duplicate detection.

    Uses word-level shingles (5-word default per DataTrove/FineWeb production
    values). Falls back to a single shingle for very short text.

    Args:
        text:        The text to fingerprint.
        num_perm:    Number of MinHash permutations (default 128).
        shingle_size: Word-level shingle window size (default 5).

    Returns:
        MinHash object with num_perm permutations.
    """
    m = MinHash(num_perm=num_perm)
    words = text.lower().split()

    if len(words) < shingle_size:
        # Very short text — add the whole text as a single shingle
        m.update(text.lower().encode("utf-8"))
    else:
        for i in range(len(words) - shingle_size + 1):
            shingle = " ".join(words[i : i + shingle_size])
            m.update(shingle.encode("utf-8"))

    return m


# ── Main clean() function ─────────────────────────────────────────────────────


def clean(
    parsed_artifact_id: str,
    source_id: str,
    *,
    settings: Optional[Settings] = None,
) -> dict:
    """Clean a parsed_document artifact and create a cleaned_document artifact.

    Flow:
    1. Fetch parsed artifact from registry to get storage_uri.
    2. Retrieve parsed markdown bytes from silver zone.
    3. Apply boilerplate removal (before MinHash to avoid false near-dups).
    4. Compute SHA256 for exact dedup.
    5. If exact dup found, return existing artifact (no new artifact created).
    6. Detect language via lingua (annotate-only).
    7. Compute MinHash signature.
    8. Build transient LSH from existing cleaned artifacts for near-dup check.
    9. Write cleaned text to silver zone.
    10. Create cleaned_document artifact with metadata.

    Args:
        parsed_artifact_id: ID of the parsed_document artifact to clean.
        source_id:          Source ID (used for silver zone key path).
        settings:           Settings override (for testing).

    Returns:
        dict with keys: artifact_id, content_hash, language, dedup_status,
        storage_uri.

    Raises:
        ValueError: If the parsed artifact does not exist or has no storage_uri.
    """
    s = settings or get_settings()
    storage = StorageBackend(s.storage)

    log.info("clean.start", parsed_artifact_id=parsed_artifact_id)

    # Step 1: Fetch parsed artifact metadata
    with get_session() as session:
        parsed_artifact = registry_repo.get_artifact(session, parsed_artifact_id)
        if parsed_artifact is None:
            raise ValueError(
                f"clean: parsed_artifact {parsed_artifact_id!r} not found in registry"
            )
        storage_uri = parsed_artifact.storage_uri
        if not storage_uri:
            raise ValueError(
                f"clean: parsed_artifact {parsed_artifact_id!r} has no storage_uri"
            )

    # Step 2: Retrieve parsed markdown from silver zone
    key = _uri_to_key(storage_uri)
    raw_bytes = storage.get_object(key)
    parsed_text = raw_bytes.decode("utf-8")
    log.info("clean.loaded_parsed", size=len(parsed_text))

    # Step 3: Apply boilerplate removal (CLEAN-01)
    # Must happen BEFORE MinHash computation (Pitfall 3 from RESEARCH.md)
    cleaned_text = remove_boilerplate(parsed_text)

    # Step 4: Compute SHA256 for exact dedup (CLEAN-03)
    cleaned_bytes = cleaned_text.encode("utf-8")
    content_hash = hashlib.sha256(cleaned_bytes).hexdigest()

    # Step 6: Language detection (CLEAN-02 — annotate only)
    # Done before the session block so no I/O happens inside the critical section.
    language = detect_language(cleaned_text)

    # Step 7: Compute MinHash signature for near-dup detection (CLEAN-03)
    minhash = compute_minhash(
        cleaned_text,
        num_perm=s.clean.minhash_num_perm,
        shingle_size=s.clean.minhash_shingle_size,
    )

    # Step 8: Transient LSH near-dup check (read-only; separate session is safe here
    # because this result is advisory — near_dup is metadata only, not a gate).
    # O(n) per call — acceptable for Phase 3 MVP (T-03-06 accepted).
    dedup_status = "unique"
    with get_session() as session:
        existing_cleaned = registry_repo.list_cleaned_artifacts(session)
        if existing_cleaned:
            lsh = MinHashLSH(
                threshold=s.clean.minhash_threshold,
                num_perm=s.clean.minhash_num_perm,
            )
            for artifact in existing_cleaned:
                if not artifact.storage_uri:
                    continue
                try:
                    art_key = _uri_to_key(artifact.storage_uri)
                    art_bytes = storage.get_object(art_key)
                    art_text = art_bytes.decode("utf-8")
                    art_minhash = compute_minhash(
                        art_text,
                        num_perm=s.clean.minhash_num_perm,
                        shingle_size=s.clean.minhash_shingle_size,
                    )
                    lsh.insert(artifact.id, art_minhash)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "clean.lsh_insert_failed",
                        artifact_id=artifact.id,
                        error=str(exc),
                    )
                    continue

            matches = lsh.query(minhash)
            if matches:
                dedup_status = "near_dup"
                log.info(
                    "clean.near_dup",
                    content_hash=content_hash,
                    matches=matches,
                )

    # Steps 5 + 9 + 10: Exact-dedup check, S3 write, and artifact creation in a
    # single session block — mirroring parse.py's session discipline (WR-01).
    # Both the read (dedup check) and the write (artifact insert) happen within the
    # same session, making the dedup + insert effectively atomic and preventing two
    # concurrent clean() calls for the same content from both creating an artifact
    # and hitting the unique constraint with an unhandled IntegrityError.
    # The S3 put_object call is idempotent for the same key, so it is safe here.
    cleaned_key = f"{_SILVER_PREFIX}/{source_id}/cleaned/{content_hash}.md"
    with get_session() as session:
        # Step 5: Exact dedup check — same pattern as parse stage (FOUND-04)
        existing = registry_repo.get_artifact_by_hash(session, content_hash, "cleaned_document")
        if existing is not None:
            log.info(
                "clean.exact_dup",
                content_hash=content_hash,
                existing_artifact_id=existing.id,
            )
            return {
                "artifact_id": existing.id,
                "content_hash": content_hash,
                "language": existing.metadata_.get("language", "unknown")
                if existing.metadata_
                else "unknown",
                "dedup_status": "exact_dup",
                "storage_uri": existing.storage_uri,
            }

        # Step 9: Write cleaned text to silver zone (idempotent for same key)
        storage.put_object(cleaned_key, cleaned_bytes)
        cleaned_uri = storage.object_uri(cleaned_key)
        log.info("clean.stored_silver", cleaned_uri=cleaned_uri)

        # Step 10: Create cleaned_document artifact in registry
        artifact = registry_repo.create_cleaned_artifact(
            session,
            source_id=source_id,
            parent_artifact_id=parsed_artifact_id,
            content_hash=content_hash,
            storage_uri=cleaned_uri,
            mime_type="text/markdown",
            metadata={
                "language": language,
                "dedup_status": dedup_status,
                "minhash_num_perm": s.clean.minhash_num_perm,
            },
        )
        session.flush()
        result = {
            "artifact_id": artifact.id,
            "content_hash": content_hash,
            "language": language,
            "dedup_status": dedup_status,
            "storage_uri": cleaned_uri,
        }

    log.info(
        "clean.complete",
        artifact_id=result["artifact_id"],
        language=language,
        dedup_status=dedup_status,
    )
    return result
