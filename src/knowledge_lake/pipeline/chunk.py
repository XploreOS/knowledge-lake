"""Chunk stage: parsed_document → section-aware chunk artifacts.

Produces chunks from a ParsedDoc that:
  - Respect section boundaries (headings = natural chunk boundaries, CHUNK-01)
  - Keep tables atomic — a table section is never split across chunks (CHUNK-03)
  - Carry section_path + page_ref from the Section metadata (CHUNK-04)
  - Use tiktoken cl100k_base token counting instead of character limits (CHUNK-02, D-03)
  - Are registered as chunk artifacts with parent = parsed_document

Module-level tiktoken encoder caching (Pitfall 2 from RESEARCH.md):
    _encoder is instantiated once at import time via tiktoken.get_encoding().
    Subsequent calls to token_count() are O(1) encoder.encode() calls — no
    per-call re-instantiation overhead.

Chunking strategy (Phase 3, token-aware):
    - For each Section in ParsedDoc.sections:
        - Tables (section.is_table=True) → emit as single atomic chunk regardless of size.
        - Text sections → call chunk_section() which splits on sentence boundaries
          accumulating sentences until max_tokens is reached, then starts a new
          chunk with overlap_tokens token overlap (D-03, CHUNK-02).
    - If ParsedDoc has no sections, emit full text as single chunk with section_path='§1'.

Returns:
    list of dicts, each dict:
      chunk_id, artifact_id, text, section_path, page, content_hash, is_table, oversized
"""

from __future__ import annotations

import functools
import hashlib
import importlib.metadata  # noqa: F401 — defensive: ensures FineWebQualityFilter's

# lazy tokenizer probe (datatrove.utils.text.split_into_words) never hits the
# "module 'importlib' has no attribute 'metadata'" AttributeError regardless
# of future import-order changes elsewhere in the app (RESEARCH.md Pitfall 4).
import re

import structlog
import tiktoken as _tiktoken

from knowledge_lake.config.settings import ChunkQualitySettings, Settings, get_settings
from knowledge_lake.domains.models import DomainFilters
from knowledge_lake.pipeline.quality import (
    PredicateResult,
    check_alpha_ratio,
    check_domain_allowlist,
    check_link_density,
    check_stopword_ratio,
    check_table_exemption,
    check_terminal_punct_ratio,
    check_token_floor,
    run_predicates,
)
from knowledge_lake.plugins.protocols import ParsedDoc
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.storage.s3 import _UNCLASSIFIED_DOMAIN, StorageBackend

log = structlog.get_logger(__name__)

# Chunk-text zone prefix. Chunk text is a derived (silver-tier) artifact — it is
# persisted so downstream stages (QA generation) can read grounded text back via
# the artifact's storage_uri instead of relying on in-memory pipeline state.
# Mirrors parse.py's _SILVER_PREFIX literal convention.
_CHUNK_PREFIX = "chunks"

# Module-level tiktoken encoder — instantiated once, never re-instantiated per call.
# Avoidance of Pitfall 2 from RESEARCH.md: get_encoding() is expensive (~100ms); caching
# at module scope makes token_count() an O(1) lookup per call.
_encoder = _tiktoken.get_encoding("cl100k_base")


# ── Public helpers ────────────────────────────────────────────────────────────


def token_count(text: str) -> int:
    """Return the number of cl100k_base tokens in ``text``.

    Uses the module-level cached encoder (Pitfall 2 avoidance).
    Safe for arbitrary text lengths — tiktoken.encode() handles Unicode correctly.
    """
    return len(_encoder.encode(text))


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using a punctuation-aware boundary regex.

    Uses a positive lookbehind for sentence-ending punctuation followed by
    whitespace and an uppercase letter.  This guards against common abbreviations
    (e.g. 'Dr. Smith', 'U.S. gov') which are lower-case after the period.

    Falls back to returning [text] if no sentences can be extracted.
    """
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    parts = [p for p in parts if p]
    return parts if parts else [text]


def chunk_section(
    text: str,
    max_tokens: int,
    overlap_tokens: int,
    heading_prefix: str = "",
) -> list[str]:
    """Split ``text`` into token-aware sub-chunks of at most ``max_tokens`` each.

    Algorithm:
    1. If token_count(text) <= max_tokens: return [text] immediately (single chunk).
    2. Split text into sentences via _split_sentences().
    3. Pre-compute per-sentence token costs (one encode call per sentence).
    4. Sliding-window accumulation:
       - Accumulate sentences until adding the next would exceed max_tokens.
       - Emit current accumulation as a chunk.
       - Compute overlap: keep trailing sentences whose total cost <= overlap_tokens.
       - Continue from the overlap sentences.
    5. Emit remaining sentences as final chunk.
    6. If no chunks produced (single sentence > max_tokens): return [text] as atomic.

    Note: ``heading_prefix`` is accepted for API symmetry but is NOT prepended to
    chunk text — it is stored separately in chunk metadata to avoid inflating the
    retrieval embedding token budget (Pitfall 6 from RESEARCH.md).

    Args:
        text:          Full section text to split.
        max_tokens:    Maximum tokens per output chunk.
        overlap_tokens: Maximum tokens to carry forward as overlap between chunks.
        heading_prefix: Section heading (accepted but not prepended to text).

    Returns:
        List of text strings, each at most max_tokens tokens.
    """
    if token_count(text) <= max_tokens:
        return [text]

    sentences = _split_sentences(text)
    if len(sentences) == 1:
        # Single sentence exceeds max_tokens — return atomically (same as table rule)
        return [text]

    # Pre-compute token costs for each sentence (one encode call each)
    costs = [token_count(s) for s in sentences]

    chunks: list[str] = []
    current_sentences: list[str] = []
    current_tokens: int = 0

    i = 0
    while i < len(sentences):
        sent = sentences[i]
        cost = costs[i]

        if current_tokens + cost > max_tokens and current_sentences:
            # Emit current chunk
            chunks.append(" ".join(current_sentences))

            # Compute overlap: keep trailing sentences whose total cost <= overlap_tokens
            overlap_sents: list[str] = []
            overlap_cost = 0
            for s in reversed(current_sentences):
                s_cost = token_count(s)
                if overlap_cost + s_cost <= overlap_tokens:
                    overlap_sents.insert(0, s)
                    overlap_cost += s_cost
                else:
                    break

            current_sentences = overlap_sents
            current_tokens = overlap_cost
            # Guard: if the overlap window still cannot accommodate the current
            # sentence, force-add it to break the infinite loop. This handles the
            # case where a sentence whose token cost > (max_tokens - overlap_tokens)
            # would otherwise cause the loop to emit the same overlap chunk forever.
            if overlap_cost + costs[i] > max_tokens:
                current_sentences.append(sentences[i])
                current_tokens += costs[i]
                i += 1
            # Do NOT advance i otherwise — re-process current sentence in the new window
        else:
            current_sentences.append(sent)
            current_tokens += cost
            i += 1

    if current_sentences:
        chunks.append(" ".join(current_sentences))

    return chunks if chunks else [text]


# ── Internal chunking logic ───────────────────────────────────────────────────


def _build_token_chunks(
    parsed_doc: ParsedDoc,
    max_tokens: int,
    overlap_tokens: int,
    breadcrumb_depth: int,
) -> list[dict]:
    """Build raw chunk dicts from ParsedDoc sections using token-aware splitting.

    Tables (section.is_table=True) are emitted as single atomic chunks regardless
    of their token count.  Oversized tables carry oversized=True in their dict.

    Text sections are split via chunk_section() — the sliding-window sentence
    accumulation algorithm.

    Each produced dict has keys:
      text, section_path, page, is_table (bool), oversized (bool), heading_prefix (str)

    Args:
        parsed_doc:     Parsed document with sections list.
        max_tokens:     Maximum tokens per text chunk.
        overlap_tokens: Token overlap between adjacent text chunks.
        breadcrumb_depth: Heading hierarchy depth for heading_prefix (stored in metadata,
                          NOT prepended to chunk text — Pitfall 6 from RESEARCH.md).

    Returns:
        List of raw chunk dicts.
    """
    raw_chunks: list[dict] = []

    if not parsed_doc.sections:
        # No sections: emit full text as single chunk
        if parsed_doc.text.strip():
            raw_chunks.append({
                "text": parsed_doc.text,
                "section_path": "§1",
                "page": 1,
                "is_table": False,
                "oversized": False,
                "heading_prefix": "",
            })
        return raw_chunks

    for section in parsed_doc.sections:
        heading = section.heading or ""
        body = section.text or ""

        # Combine heading + body for the full section text
        full_text = f"{heading}\n\n{body}".strip() if heading else body.strip()

        if not full_text:
            continue

        # Heading prefix for metadata (not prepended to text — Pitfall 6)
        heading_prefix = heading if breadcrumb_depth >= 1 else ""

        if section.is_table:
            # Tables are always atomic regardless of size (CHUNK-03)
            oversized = token_count(full_text) > max_tokens
            raw_chunks.append({
                "text": full_text,
                "section_path": section.section_path,
                "page": section.page,
                "is_table": True,
                "oversized": oversized,
                "heading_prefix": heading_prefix,
            })
        else:
            # Text section: split via token-aware chunk_section()
            subs = chunk_section(full_text, max_tokens, overlap_tokens, heading_prefix)
            for i, sub in enumerate(subs):
                sub_path = (
                    f"{section.section_path}.{i + 1}" if len(subs) > 1 else section.section_path
                )
                raw_chunks.append({
                    "text": sub,
                    "section_path": sub_path,
                    "page": section.page,
                    "is_table": False,
                    "oversized": False,
                    "heading_prefix": heading_prefix,
                })

    return raw_chunks


# ── Chunk-level substance gate (QUAL-02, QUAL-03) ──────────────────────────────


def _build_fineweb_filter(settings: ChunkQualitySettings):
    """Factory returning a configured FineWebQualityFilter instance.

    Deferred import — tests that don't exercise the real filter never need
    datatrove installed at import time (mirrors curate.py::_build_filters()'s
    Pitfall-1 avoidance).
    """
    from datatrove.pipeline.filters.fineweb_quality_filter import (  # noqa: PLC0415
        FineWebQualityFilter,
    )

    return FineWebQualityFilter(
        line_punct_thr=settings.fineweb_line_punct_thr,
        short_line_thr=settings.fineweb_short_line_thr,
        short_line_length=settings.fineweb_short_line_length,
    )


def _fineweb_predicate(text: str, metadata: dict, *, filter_instance) -> PredicateResult:
    """Wraps FineWebQualityFilter.filter() as a run_predicates()-compatible predicate.

    FineWebQualityFilter.filter() returns bool | tuple[bool, str] — mirrors
    curate.py::score_document()'s isinstance(outcome, tuple) handling exactly.
    """
    from datatrove.data import Document  # noqa: PLC0415

    doc = Document(text=text, id="chunk", metadata={})
    outcome = filter_instance.filter(doc)
    if isinstance(outcome, tuple):
        passed, reason = outcome
    else:
        passed, reason = bool(outcome), "fineweb_ok"
    return PredicateResult(passed, reason or "fineweb_reject")


def _assert_chunk_conservation_invariant(
    *,
    kept_count: int,
    rejected_count: int,
    total_generated: int,
    parsed_artifact_id: str,
) -> None:
    """QUAL-05 conservation invariant: rejected + kept == total_generated.

    Mirrors clean.py's log-then-raise shape exactly — never a bare assert.
    """
    if kept_count + rejected_count != total_generated:
        log.error(
            "chunk.substance_gate.conservation_invariant_violated",
            parsed_artifact_id=parsed_artifact_id,
            total_generated=total_generated,
            kept=kept_count,
            rejected=rejected_count,
        )
        raise RuntimeError(
            f"chunk: conservation invariant violated for {parsed_artifact_id!r}: "
            f"{kept_count} + {rejected_count} != {total_generated}"
        )


def _apply_substance_gate(
    raw_chunks: list[dict],
    s: Settings,
    domain_filters: DomainFilters | None,
    parsed_artifact_id: str,
) -> list[dict]:
    """Run the composite substance gate over ``raw_chunks`` (QUAL-02, QUAL-03).

    Pure w.r.t. I/O (no DB/S3 access) so it is independently unit-testable —
    the only "impure" behavior is structlog logging. Annotates every entry in
    ``raw_chunks`` with ``substance_passed``/``rejection_reason`` in place,
    then returns either the full (annotated) list (report mode, D-13) or the
    subset that passed (enforce mode, the default).

    Predicate order [check_table_exemption, domain_allowlist, fineweb,
    token_floor, alpha_ratio, link_density, stopword_ratio,
    terminal_punct_ratio] mirrors classify_sections()'s established ordering
    discipline: exemption predicates first so they short-circuit before any
    threshold predicate ever runs (D-01).
    """
    allowlist_patterns = list(domain_filters.normative_allowlists) if domain_filters else []
    allowlist_pred = functools.partial(check_domain_allowlist, allowlist_patterns=allowlist_patterns)
    fineweb_pred = functools.partial(
        _fineweb_predicate, filter_instance=_build_fineweb_filter(s.chunk_quality)
    )
    token_pred = functools.partial(check_token_floor, min_tokens=s.chunk_quality.min_token_count)
    alpha_pred = functools.partial(check_alpha_ratio, min_ratio=s.chunk_quality.min_alpha_ratio)
    link_pred = functools.partial(check_link_density, max_density=s.chunk_quality.max_link_density)
    stopword_pred = functools.partial(
        check_stopword_ratio, min_ratio=s.chunk_quality.min_stopword_ratio
    )

    preds = [
        check_table_exemption,
        allowlist_pred,
        fineweb_pred,
        token_pred,
        alpha_pred,
        link_pred,
        stopword_pred,
        check_terminal_punct_ratio,
    ]
    # WR-03: reuse the SAME allowlist_pred object reference in both the list
    # and the exemption set — never construct two separate functools.partial
    # instances (identity matching in run_predicates()).
    exemptions = {check_table_exemption, allowlist_pred}

    kept_count = 0
    rejected_count = 0
    rejection_reason_counts: dict[str, int] = {}

    for raw in raw_chunks:
        result = run_predicates(
            raw["text"], {"is_table": raw["is_table"]}, preds, exemption_predicates=exemptions
        )
        raw["substance_passed"] = result.passed
        raw["rejection_reason"] = None if result.passed else result.reason
        if result.passed:
            kept_count += 1
        else:
            rejected_count += 1
            rejection_reason_counts[result.reason] = rejection_reason_counts.get(result.reason, 0) + 1

    _assert_chunk_conservation_invariant(
        kept_count=kept_count,
        rejected_count=rejected_count,
        total_generated=len(raw_chunks),
        parsed_artifact_id=parsed_artifact_id,
    )

    # Log unconditionally (both modes) — closes the chunk-level rejection
    # audit-trail gap, extending QUAL-04's Phase-17 "every rejected chunk
    # must be recorded" contract to this new rejection path.
    log.info(
        "chunk.substance_gate.complete",
        parsed_artifact_id=parsed_artifact_id,
        total_generated=len(raw_chunks),
        kept=kept_count,
        rejected=rejected_count,
        rejection_reasons=rejection_reason_counts,
        gate_mode=s.chunk_quality.gate_mode,
    )

    if s.chunk_quality.gate_mode == "enforce":
        return [r for r in raw_chunks if r["substance_passed"]]
    return raw_chunks


# ── Public pipeline function ──────────────────────────────────────────────────


def chunk(
    parsed_artifact_id: str,
    source_id: str,
    parsed_doc: ParsedDoc,
    *,
    settings: Settings | None = None,
    domain_filters: DomainFilters | None = None,
) -> list[dict]:
    """Split a ParsedDoc into section-aware chunks and register artifact nodes.

    Replaces the previous character-based MAX_CHUNK_CHARS=1200 splitter with
    token-aware cl100k_base splitting (CHUNK-02, D-03).

    Args:
        parsed_artifact_id: ID of the parsed_document artifact (parent).
        source_id:          Source ID (propagated to each chunk artifact).
        parsed_doc:         ParsedDoc returned by the parse stage.
        settings:           Settings override.
        domain_filters:     Optional DomainFilters (normative_allowlists) used
                             to exempt domain-specific clinical codes from the
                             substance gate (QUAL-03). None = no exemption
                             beyond is_table. Resolved and passed by callers
                             (chunk_document/process_crawled) via DomainLoader.

    Returns:
        List of chunk dicts with keys:
          chunk_id, artifact_id, text, section_path, page, content_hash,
          is_table, oversized
    """
    s = settings or get_settings()
    storage = StorageBackend(s.storage)

    # Build raw chunks from sections using token-aware splitting
    raw_chunks = _build_token_chunks(
        parsed_doc,
        s.chunk.max_tokens,
        s.chunk.overlap_tokens,
        s.chunk.heading_breadcrumb_depth,
    )
    log.info("chunk.raw_chunks", count=len(raw_chunks))

    # QUAL-02/QUAL-03: composite substance gate — rejects (enforce mode) or
    # flags (report mode) garbage chunks before persistence/embedding. Each
    # surviving/annotated raw dict carries substance_passed/rejection_reason,
    # consumed by the per-chunk persistence loop below (PIPE-01 hash formula
    # and metadata annotation).
    raw_chunks = _apply_substance_gate(raw_chunks, s, domain_filters, parsed_artifact_id)

    results: list[dict] = []

    with get_session() as session:
        # Resolve the domain segment and source name once before the loop.
        # domain routes chunk text under {domain}/ (falling back to the shared
        # _unclassified literal so parse.py/put_bronze/chunk all agree). source_name
        # is carried into the object tags, mirroring parse.py's silver-zone tags.
        domain = registry_repo.get_domain_for_source(session, source_id) or _UNCLASSIFIED_DOMAIN
        source_obj = registry_repo.get_source(session, source_id)
        source_name = source_obj.name if source_obj else "unknown"

        for raw in raw_chunks:
            text = raw["text"]
            section_path = raw["section_path"]
            page = raw["page"]

            # Include parsed_artifact_id in the hash so identical chunk text from
            # different documents creates distinct artifacts (WR-05: dedup key must
            # include parent to prevent lineage corruption across documents).
            # PIPE-01: also fold in filter_config_version so a threshold-config
            # bump produces a NEW content_hash — without this, the deterministic
            # chunk text would hit the SAME hash and the no-op branch below would
            # short-circuit re-evaluation of the gate (RESEARCH.md Pitfall 3).
            hash_input = f"{parsed_artifact_id}:{s.chunk_quality.filter_config_version}:{text}"
            content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

            # Registry no-op: if this chunk already exists for THIS parent, use existing node.
            # substance_passed/rejection_reason are sourced from `raw` (this call's fresh gate
            # computation), never from the existing artifact's persisted metadata — idempotency
            # holds by construction regardless of which branch is taken.
            existing = registry_repo.get_artifact_by_hash(session, content_hash, "chunk")
            if existing is not None:
                results.append({
                    "chunk_id": existing.id,
                    "artifact_id": existing.id,
                    "text": text,
                    "section_path": section_path,
                    "page": page,
                    "content_hash": content_hash,
                    "is_table": raw["is_table"],
                    "oversized": raw.get("oversized", False),
                    "substance_passed": raw["substance_passed"],
                    "rejection_reason": raw["rejection_reason"],
                })
                continue

            # Persist the chunk text to the chunks storage zone so QA generation
            # can read a grounded excerpt back via storage_uri (Finding 1). Only
            # NEW chunks are written — the get_artifact_by_hash no-op branch above
            # returns before reaching here, so existing chunk text is never rewritten.
            chunk_key = f"{_CHUNK_PREFIX}/{domain}/{source_id}/{content_hash}.txt"
            storage.put_object(
                chunk_key,
                text.encode("utf-8"),
                tags={
                    "domain": domain,
                    "source_name": source_name,
                    "format": "txt",
                    "artifact_type": "chunk",
                },
            )
            chunk_uri = storage.object_uri(chunk_key)

            artifact = registry_repo.create_chunk_artifact(
                session,
                source_id=source_id,
                parent_artifact_id=parsed_artifact_id,
                content_hash=content_hash,
                storage_uri=chunk_uri,
                mime_type="text/plain",
                page_ref=page,
                section_path=section_path,
                metadata={
                    "is_table": raw["is_table"],
                    "oversized": raw.get("oversized", False),
                    "heading_prefix": raw.get("heading_prefix", ""),
                    "substance_passed": raw["substance_passed"],
                    "rejection_reason": raw["rejection_reason"],
                },
            )
            session.flush()

            results.append({
                "chunk_id": artifact.id,
                "artifact_id": artifact.id,
                "text": text,
                "section_path": section_path,
                "page": page,
                "content_hash": content_hash,
                "is_table": raw["is_table"],
                "oversized": raw.get("oversized", False),
                "substance_passed": raw["substance_passed"],
                "rejection_reason": raw["rejection_reason"],
            })

    log.info("chunk.complete", chunk_count=len(results))
    return results
