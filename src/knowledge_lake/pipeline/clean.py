"""Clean stage: parsed_document artifact → cleaned_document artifact.

Performs boilerplate removal, whitespace normalization, language detection,
and exact/near-duplicate flagging (CLEAN-01..03). Raw zone is never touched —
this stage reads from and writes to the silver zone only.

T-03-06 (DoS — transient LSH corpus scan): The near-duplicate check builds an
in-memory MinHash LSH from all existing cleaned artifacts per clean() call.
This is O(n) per call — acceptable for Phase 3 MVP corpus sizes (< 10,000
documents).

As of Phase 5, `pipeline.curate.batch_dedup_corpus()` is the AUTHORITATIVE
corpus-wide dedup signal — it builds one MinHashLSH index over ALL
cleaned_document artifacts in a single batch pass and records the result on
curated_document.metadata_["dedup_status"] (D-02, CURATE-02). The per-call
transient LSH block below remains running as a legacy best-effort advisory-only
flag on cleaned_document.metadata_["dedup_status"]. It is retained here to
avoid destabilising Phase 3's existing tests/CLI/API contract — D-02 explicitly
leaves removing it to planner discretion.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace

import structlog
from datasketch import MinHash, MinHashLSH

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.pipeline.utils import uri_to_key as _uri_to_key
from knowledge_lake.plugins.protocols import ParsedDoc, Section
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.storage.s3 import _UNCLASSIFIED_DOMAIN, StorageBackend

log = structlog.get_logger(__name__)

_SILVER_PREFIX = "silver"

# ── Boilerplate patterns ──────────────────────────────────────────────────────
#
# All patterns are line-level and only match entire lines of boilerplate.
# Inline citations like "(HHS, 2023)", "[1]", or "see §3.2" appear mid-sentence
# and will not match these patterns (T-03-07).
#
# 9 entries total (CLEAN-05): the original 4 (page headers, cookie/privacy
# banners, navigation, copyright/disclaimer) plus 5 added in Phase 19 covering
# navigation menus, terms-of-service blocks, marketing/enrollment CTAs, cookie
# consent (additional phrasing), and government disclaimer boilerplate. The
# extension is additive-only via .extend() — indices 0-3 are byte-identical to
# their pre-Phase-19 form so the Phase 18 gate signature (crawl.py's frozen
# _GATE_BOILERPLATE_PATTERNS copy) remains unaffected (GATE-01, D-06).

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

BOILERPLATE_PATTERNS.extend(
    [
        # Navigation (extended): additional nav-chrome phrases, full-line-only
        re.compile(
            r"(?im)^(?:main menu|breadcrumbs?|skip to footer|jump to navigation|back to top|search this site|toggle navigation)\s*$"
        ),
        # Terms-of-service blocks: strip the whole line containing the phrase
        re.compile(r"(?im)^.*(?:terms of service|terms and conditions|terms of use)\b.*$"),
        # Marketing/enrollment CTAs, full-line-anchored
        re.compile(
            r"(?im)^(?:enroll now|sign up today|register for .*|subscribe now|get started for free|schedule a demo|contact sales)[^\n]*$"
        ),
        # Cookie consent (additional phrasing beyond the existing pattern)
        re.compile(r"(?im)^.*(?:we use cookies|manage cookie preferences|cookie settings)\b.*$"),
        # Government disclaimer: anchored to specific multi-word phrases only
        # (deliberately NOT a generic "disclaimer"/"warning" keyword match — this
        # narrowness is what keeps genuine clinical safety text intact).
        re.compile(
            r"(?im)^(?:this website is not a substitute for professional medical advice|for official use only|privacy policy|accessibility statement|no fear act|foia)[^\n]*$"
        ),
    ]
)


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


# ── Per-section cleaning (CLEAN-01, QUAL-04, QUAL-05) ─────────────────────────


def _clean_sections(
    sections: list[Section],
) -> tuple[list[Section], int, int, int, dict[str, int]]:
    """Apply boilerplate removal to each section's text without dropping any.

    Builds a new list of Section instances (via dataclasses.replace — never
    mutates the caller's original Section objects, avoiding the mutation-
    aliasing hazard called out in 17-RESEARCH.md Pitfall 3, since the same
    cleaned ParsedDoc is later shared read-only across three Dagster
    consumers). The returned list always has the same length as `sections` —
    CLEAN-04's section *removal* is explicitly Phase 19's job, not this
    plan's; a section whose text goes empty after stripping is still
    returned, just counted as rejected.

    Args:
        sections: The parsed document's sections, as-is from the parser.

    Returns:
        Tuple of (cleaned_sections, sections_considered, sections_kept,
        sections_rejected, rejection_reasons). `rejection_reasons` maps a
        reason string to its count (e.g. {"empty_after_boilerplate_removal": 2})
        — counts are additive so a caller accumulating across multiple
        `_clean_sections()` calls (e.g. a quality-audit run) can sum them
        rather than overwrite (QUAL-04 adjacency). An empty input returns
        considered=kept=rejected=0 and does not raise — distinct from a gate
        that rejected all N sections (QUAL-05 empty-input boundary).
    """
    cleaned_sections: list[Section] = []
    rejection_reasons: dict[str, int] = {}
    sections_kept = 0
    sections_rejected = 0

    for section in sections:
        cleaned_section_text = remove_boilerplate(section.text)
        cleaned_sections.append(replace(section, text=cleaned_section_text))
        if cleaned_section_text.strip():
            sections_kept += 1
        else:
            sections_rejected += 1
            reason = "empty_after_boilerplate_removal"
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1

    sections_considered = len(sections)
    return cleaned_sections, sections_considered, sections_kept, sections_rejected, rejection_reasons


# ── Main clean() function ─────────────────────────────────────────────────────


def clean(
    parsed_artifact_id: str,
    source_id: str,
    *,
    parsed_doc: ParsedDoc | None = None,
    settings: Settings | None = None,
) -> dict:
    """Clean a parsed_document artifact and create a cleaned_document artifact.

    Flow:
    1. Fetch parsed artifact from registry to get storage_uri (always — even
       when parsed_doc is supplied, parsed_artifact_id is still used as the
       parent_artifact_id for the cleaned artifact).
    2. Retrieve parsed text — from the caller's in-memory `parsed_doc` when
       supplied (CLEAN-01/02: avoids a redundant S3 round trip for load-
       bearing callers that already hold it), else from the silver zone
       (legacy/standalone path, unchanged S3-read behavior).
    2b. When parsed_doc is supplied, clean each section's text via
        _clean_sections() (dataclasses.replace — never mutating the caller's
        Section objects) without dropping any section from the list, and
        count sections_considered/kept/rejected (QUAL-04/05).
    3. Apply boilerplate removal to the flattened text (before MinHash to
       avoid false near-dups).
    4. Compute WR-05 parent-scoped SHA256 for exact dedup (CLEAN-03) —
       `f"{parsed_artifact_id}:{cleaned_text}"` — so two documents whose
       cleaned text collides never share one cleaned_document artifact.
    5. If exact dup found, return existing artifact (no new artifact created)
       — still carries fresh cleaned_doc/sections counts (QUAL-04 adjacency,
       never read stale counts off the existing artifact's metadata).
    6. Detect language via lingua (annotate-only).
    7. Compute MinHash signature.
    8. Build transient LSH from existing cleaned artifacts for near-dup check.
    9. Write cleaned text to silver zone.
    10. Create cleaned_document artifact with metadata (including
        sections_considered/kept/rejected/rejection_reasons).

    Args:
        parsed_artifact_id: ID of the parsed_document artifact to clean.
        source_id:          Source ID (used for silver zone key path).
        parsed_doc:         Optional in-memory ParsedDoc. When supplied, skips
                             the S3 re-fetch and cleans parsed_doc.sections at
                             section granularity without dropping any section
                             (CLEAN-04 section removal is Phase 19's job).
        settings:           Settings override (for testing).

    Returns:
        dict with keys: artifact_id, content_hash, language, dedup_status,
        storage_uri, cleaned_doc (ParsedDoc | None — None unless parsed_doc
        was supplied), sections_considered, sections_kept, sections_rejected,
        rejection_reasons (dict[str, int] — all four are 0/{} when parsed_doc
        was not supplied).

    Raises:
        ValueError: If the parsed artifact does not exist or has no storage_uri.
        RuntimeError: If the QUAL-05 conservation invariant
            (sections_rejected + sections_kept == sections_considered) is
            violated — indicates a bug in _clean_sections, never expected in
            normal operation.
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

    # Step 2: Retrieve parsed text — in-memory parsed_doc (CLEAN-01/02) or,
    # for the legacy/standalone caller, the silver zone (unchanged S3-read
    # behavior; single get_object() call, matching test_clean_silver_key.py).
    if parsed_doc is not None:
        parsed_text = parsed_doc.text
        # Step 2b: clean each section's text without dropping any section from
        # the list (CLEAN-04 section removal is Phase 19's job, not this
        # plan's) and count kept/rejected/considered (QUAL-04/05).
        (
            cleaned_sections,
            sections_considered,
            sections_kept,
            sections_rejected,
            rejection_reasons,
        ) = _clean_sections(parsed_doc.sections)
    else:
        key = _uri_to_key(storage_uri)
        raw_bytes = storage.get_object(key)
        parsed_text = raw_bytes.decode("utf-8")
        cleaned_sections = []
        sections_considered = 0
        sections_kept = 0
        sections_rejected = 0
        rejection_reasons = {}
    log.info("clean.loaded_parsed", size=len(parsed_text))

    # QUAL-05: conservation invariant — never a bare assert (this codebase's
    # pipeline/*.py convention: structlog call immediately followed by a
    # raised typed exception, e.g. the ValueError raises above).
    if sections_rejected + sections_kept != sections_considered:
        log.error(
            "clean.conservation_invariant_violated",
            parsed_artifact_id=parsed_artifact_id,
            sections_considered=sections_considered,
            sections_kept=sections_kept,
            sections_rejected=sections_rejected,
        )
        raise RuntimeError(
            f"clean: conservation invariant violated for {parsed_artifact_id!r}: "
            f"{sections_rejected} + {sections_kept} != {sections_considered}"
        )
    # QUAL-05's other half — a broken parser (0 sections) must be distinguishable
    # from a correct gate that rejected everything (N sections, 0 kept). Only
    # meaningful when parsed_doc was supplied — the legacy S3 path has no
    # per-section data at all, so it would trivially and noisily "zero" every call.
    if parsed_doc is not None and sections_considered == 0:
        log.warning(
            "clean.zero_sections",
            parsed_artifact_id=parsed_artifact_id,
            msg="parser produced zero sections — distinct from a gate rejecting all sections",
        )

    # Step 3: Apply boilerplate removal to the flattened text (CLEAN-01)
    # Must happen BEFORE MinHash computation (Pitfall 3 from RESEARCH.md)
    cleaned_text = remove_boilerplate(parsed_text)

    # Step 4: WR-05 parent-scoped content hash (CLEAN-03) — prevents
    # cross-document lineage corruption when two documents' cleaned text
    # collides (mirrors chunk.py's already-shipped WR-05 convention).
    hash_input = f"{parsed_artifact_id}:{cleaned_text}"
    content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
    cleaned_bytes = cleaned_text.encode("utf-8")  # still needed for the S3 put_object body

    # cleaned_doc: forwarded in-memory to Dagster/CLI callers so they never
    # need to re-read the flattened silver blob to recover sections
    # (RESEARCH.md Primary recommendation). None unless parsed_doc was supplied.
    cleaned_doc = (
        ParsedDoc(text=cleaned_text, sections=cleaned_sections, metadata=parsed_doc.metadata)
        if parsed_doc is not None
        else None
    )

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
    # O(n) per call — accepted for Phase 3 MVP (T-03-06).
    #
    # NOTE (Phase 5): pipeline.curate.batch_dedup_corpus() is the AUTHORITATIVE
    # corpus-wide dedup signal (recorded on curated_document.metadata_["dedup_status"],
    # CURATE-02 / D-02). This per-call block is retained as a legacy advisory-only
    # flag on cleaned_document.metadata_["dedup_status"]; removing it is left to
    # planner discretion per D-02. Do NOT remove without updating Phase 3 tests.
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
    with get_session() as session:
        source_obj = registry_repo.get_source(session, source_id)
        source_name = source_obj.name if source_obj else "unknown"
        domain = (source_obj.config or {}).get("domain") or _UNCLASSIFIED_DOMAIN if source_obj else _UNCLASSIFIED_DOMAIN
        cleaned_key = f"{_SILVER_PREFIX}/{domain}/{source_id}/cleaned/{content_hash}.md"
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
                "cleaned_doc": cleaned_doc,
                # QUAL-04: computed unconditionally above from the in-memory
                # parsed_doc, never read off existing.metadata_ — a
                # quality-audit re-run against an already-cleaned document
                # must see live counts, not stale/absent ones.
                "sections_considered": sections_considered,
                "sections_kept": sections_kept,
                "sections_rejected": sections_rejected,
                "rejection_reasons": rejection_reasons,
            }

        # Step 9: Write cleaned text to silver zone (idempotent for same key)
        storage.put_object(cleaned_key, cleaned_bytes, tags={
            "domain": domain,
            "source_name": source_name,
            "format": "md",
            "artifact_type": "cleaned_document",
        })
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
                # QUAL-04/QUAL-05: computed unconditionally above from the
                # in-memory parsed_doc — see the exact-dup branch's identical
                # keys for why this must never be conditional on this branch
                # having fired.
                "sections_considered": sections_considered,
                "sections_kept": sections_kept,
                "sections_rejected": sections_rejected,
                "rejection_reasons": rejection_reasons,
            },
        )
        session.flush()
        result = {
            "artifact_id": artifact.id,
            "content_hash": content_hash,
            "language": language,
            "dedup_status": dedup_status,
            "storage_uri": cleaned_uri,
            "cleaned_doc": cleaned_doc,
            "sections_considered": sections_considered,
            "sections_kept": sections_kept,
            "sections_rejected": sections_rejected,
            "rejection_reasons": rejection_reasons,
        }

    log.info(
        "clean.complete",
        artifact_id=result["artifact_id"],
        language=language,
        dedup_status=dedup_status,
    )
    return result
