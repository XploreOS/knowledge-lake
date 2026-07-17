"""MEAS-01 quality-audit harness: re-run parse->clean and surface per-source
rejection counts (QUAL-04), without a separate frozen classifier (D-07).

``run_quality_audit()`` queries ``Source.domain`` (first-class indexed
column, KL-15 — never ``sources.yaml`` or the legacy ``Source.config['domain']``
JSON scan) for the requested domain, and for every ``raw_document`` artifact
under each matching source, reuses an existing ``parsed_document`` child when
one exists (``load_parsed_doc()``/``reparse_from_raw()``) and only calls
``parse()`` when no parsed child exists yet. It then calls ``clean()`` for
every raw doc and accumulates ``sections_considered``/``sections_kept``/
``sections_rejected``/``rejection_reasons`` into per-source running totals.

``run_full_pipeline_audit()`` (Phase 22) extends this same reuse discipline
to also measure the milestone's two originally-audited, literal-unit success
criteria: chunk-level garbage rate (via ``chunk.py``'s already-public
``_build_token_chunks()``/``_apply_substance_gate()``, applied in-memory —
no new gate logic) and gold-export junk rate (via a real
``export_rag_corpus()`` call, scoped to only this run's own chunk IDs to
avoid diluting the measurement with the domain's pre-v2.6 chunk population,
Phase 22 D-04).

Scope is ``parse -> clean -> chunk (-> export)``. This module must never
import ``knowledge_lake.pipeline.embed`` or ``knowledge_lake.pipeline.index``
— the audit is read/measurement-only (D-07's "the pipeline IS the
measurement") and must never trigger vector-store writes or embedding spend.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


def _resolve_domain_filters(s):
    """Resolve DomainFilters for the currently-configured domain pack, or None.

    Mirrors process.py's own resolution pattern (lines 112-113): guards
    against calling DomainLoader when no domain pack is configured, so
    existing callers using default Settings (domain.domain_name=None) are
    unaffected. Function-local import of DomainLoader, matching this file's
    existing function-local-import convention.
    """
    if not s.domain.domain_name:
        return None

    from knowledge_lake.domains.loader import DomainLoader

    return DomainLoader.from_name(s.domain.domain_name).filters


def run_quality_audit(*, domain: str = "healthcare", settings=None) -> list[dict]:
    """Re-run parse->clean across every source in ``domain`` and return per-source rows.

    Args:
        domain:   Source.domain filter (first-class column, KL-15). Defaults
                   to "healthcare" per D-06.
        settings: Settings override (for testing).

    Returns:
        A list of row dicts, one per matching source, ordered by
        ``Source.created_at`` ascending (deterministic, reproducible
        ordering). Each row has keys: ``source_id``, ``source_name``,
        ``sections_considered``, ``sections_kept``, ``sections_rejected``,
        ``rejection_reasons`` (dict[str, int], summed across documents),
        ``documents_errored``, ``garbage_rate`` (unrounded float, or
        ``None`` when the source has no considered sections — N/A, distinct
        from an explicit ``0.0``).
    """
    from sqlalchemy import select

    from knowledge_lake.config.settings import Settings, get_settings  # noqa: F401
    from knowledge_lake.pipeline.clean import clean
    from knowledge_lake.pipeline.ingest import _detect_mime_from_uri
    from knowledge_lake.pipeline.parse import load_parsed_doc, parse, reparse_from_raw
    from knowledge_lake.registry import repo as registry_repo
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.models import Artifact, Source

    s = settings or get_settings()
    domain_filters = _resolve_domain_filters(s)

    with get_session() as session:
        stmt = (
            select(Source)
            .where(Source.domain == domain)
            .order_by(Source.created_at.asc())
        )
        sources = session.execute(stmt).scalars().all()
        # Materialize to tuples inside the session (PAYLOAD-01 discipline —
        # the source loop below needs the ID/name after the session closes).
        source_rows = [(src.id, src.name) for src in sources]

    rows: list[dict] = []

    for source_id, source_name in source_rows:
        with get_session() as session:
            stmt = (
                select(Artifact)
                .where(Artifact.source_id == source_id)
                .where(Artifact.artifact_type == "raw_document")
                .order_by(Artifact.created_at.asc())
            )
            raw_artifacts = session.execute(stmt).scalars().all()
            raw_docs = [
                (a.id, a.mime_type, a.storage_uri) for a in raw_artifacts
            ]

        sections_considered = 0
        sections_kept = 0
        sections_rejected = 0
        rejection_reasons: dict[str, int] = {}
        documents_errored = 0

        for raw_id, mime, storage_uri in raw_docs:
            try:
                with get_session() as session:
                    children = registry_repo.list_children(session, raw_id)
                    parsed_id = next(
                        (
                            child.id
                            for child in children
                            if child.artifact_type == "parsed_document"
                        ),
                        None,
                    )

                if parsed_id is not None:
                    parsed_doc = load_parsed_doc(parsed_id, settings=s)
                    if parsed_doc is None:
                        parsed_doc = reparse_from_raw(parsed_id, source_id, settings=s)
                else:
                    parse_result, parsed_doc = parse(
                        raw_id,
                        source_id,
                        mime_type=(mime or _detect_mime_from_uri(storage_uri or "")),
                        settings=s,
                    )
                    parsed_id = parse_result["artifact_id"]

                clean_result = clean(
                    parsed_id, source_id, parsed_doc=parsed_doc, settings=s,
                    domain_filters=domain_filters,
                )
            except Exception:
                documents_errored += 1
                log.warning(
                    "quality_audit.document_failed",
                    source_id=source_id,
                    raw_id=raw_id,
                    exc_info=True,
                )
                continue

            sections_considered += clean_result["sections_considered"]
            sections_kept += clean_result["sections_kept"]
            sections_rejected += clean_result["sections_rejected"]
            for reason, count in clean_result["rejection_reasons"].items():
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + count

        total = sections_rejected + sections_kept
        garbage_rate = (sections_rejected / total) if total > 0 else None

        rows.append({
            "source_id": source_id,
            "source_name": source_name,
            "sections_considered": sections_considered,
            "sections_kept": sections_kept,
            "sections_rejected": sections_rejected,
            "rejection_reasons": rejection_reasons,
            "documents_errored": documents_errored,
            "garbage_rate": garbage_rate,
        })

    return rows


def run_full_pipeline_audit(*, domain: str = "healthcare", settings=None) -> dict:
    """Re-run parse->clean->chunk across every source in ``domain`` and
    return per-source rows plus a corpus-wide summary (Phase 22, MEAS-01
    extended).

    Extends ``run_quality_audit()``'s parse->clean loop with an in-memory
    chunk-level garbage-rate tally (criterion #1) computed purely from
    ``chunk.py``'s already-public ``_build_token_chunks()`` +
    ``_apply_substance_gate()`` functions (RESEARCH.md Pattern 1) — no new
    gate logic, no ``gate_mode="report"`` override. ``_apply_substance_gate``
    mutates its ``raw_chunks`` argument in place, annotating
    ``substance_passed``/``rejection_reason`` on every entry (kept AND
    rejected) regardless of ``gate_mode``, so this in-memory tally never
    persists a chunk artifact.

    Args:
        domain:   Source.domain filter (first-class column, KL-15). Defaults
                   to "healthcare" per D-06.
        settings: Settings override (for testing).

    Returns:
        ``{"rows": [...], "summary": {...}}``. Each row carries the same
        section-level keys as ``run_quality_audit()``'s rows, plus
        ``chunks_considered``/``chunks_kept``/``chunks_rejected``,
        ``chunk_rejection_reasons`` (dict[str, int], summed across
        documents), and ``chunk_garbage_rate`` (the same frozen
        ``rejected / (rejected + kept)`` formula, Phase 17 D-10 — ``None``
        when the source has no considered chunks, never an explicit
        ``0.0``). ``summary`` aggregates all rows' counts corpus-wide with
        ``sections_garbage_rate``/``chunk_garbage_rate`` computed identically.
    """
    from sqlalchemy import select

    from knowledge_lake.config.settings import Settings, get_settings  # noqa: F401
    from knowledge_lake.pipeline.chunk import _apply_substance_gate, _build_token_chunks
    from knowledge_lake.pipeline.clean import clean
    from knowledge_lake.pipeline.ingest import _detect_mime_from_uri
    from knowledge_lake.pipeline.parse import load_parsed_doc, parse, reparse_from_raw
    from knowledge_lake.registry import repo as registry_repo
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.models import Artifact, Source

    s = settings or get_settings()
    domain_filters = _resolve_domain_filters(s)

    with get_session() as session:
        stmt = (
            select(Source)
            .where(Source.domain == domain)
            .order_by(Source.created_at.asc())
        )
        sources = session.execute(stmt).scalars().all()
        # Materialize to tuples inside the session (PAYLOAD-01 discipline —
        # the source loop below needs the ID/name after the session closes).
        source_rows = [(src.id, src.name) for src in sources]

    rows: list[dict] = []

    for source_id, source_name in source_rows:
        with get_session() as session:
            stmt = (
                select(Artifact)
                .where(Artifact.source_id == source_id)
                .where(Artifact.artifact_type == "raw_document")
                .order_by(Artifact.created_at.asc())
            )
            raw_artifacts = session.execute(stmt).scalars().all()
            raw_docs = [
                (a.id, a.mime_type, a.storage_uri) for a in raw_artifacts
            ]

        sections_considered = 0
        sections_kept = 0
        sections_rejected = 0
        rejection_reasons: dict[str, int] = {}
        documents_errored = 0
        chunks_considered = 0
        chunks_kept = 0
        chunks_rejected = 0
        chunk_rejection_reasons: dict[str, int] = {}

        for raw_id, mime, storage_uri in raw_docs:
            try:
                with get_session() as session:
                    children = registry_repo.list_children(session, raw_id)
                    parsed_id = next(
                        (
                            child.id
                            for child in children
                            if child.artifact_type == "parsed_document"
                        ),
                        None,
                    )

                if parsed_id is not None:
                    parsed_doc = load_parsed_doc(parsed_id, settings=s)
                    if parsed_doc is None:
                        parsed_doc = reparse_from_raw(parsed_id, source_id, settings=s)
                else:
                    parse_result, parsed_doc = parse(
                        raw_id,
                        source_id,
                        mime_type=(mime or _detect_mime_from_uri(storage_uri or "")),
                        settings=s,
                    )
                    parsed_id = parse_result["artifact_id"]

                clean_result = clean(
                    parsed_id, source_id, parsed_doc=parsed_doc, settings=s,
                    domain_filters=domain_filters,
                )
            except Exception:
                documents_errored += 1
                log.warning(
                    "quality_audit.document_failed",
                    source_id=source_id,
                    raw_id=raw_id,
                    exc_info=True,
                )
                continue

            sections_considered += clean_result["sections_considered"]
            sections_kept += clean_result["sections_kept"]
            sections_rejected += clean_result["sections_rejected"]
            for reason, count in clean_result["rejection_reasons"].items():
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + count

            cleaned_doc = clean_result["cleaned_doc"]
            if cleaned_doc is None:
                continue

            # In-memory chunk-level tally (RESEARCH.md Pattern 1) — pure,
            # no registry writes. _apply_substance_gate mutates raw_chunks
            # in place, annotating substance_passed/rejection_reason on
            # every entry (kept AND rejected) regardless of gate_mode.
            raw_chunks = _build_token_chunks(
                cleaned_doc,
                s.chunk.max_tokens,
                s.chunk.overlap_tokens,
                s.chunk.heading_breadcrumb_depth,
            )
            _apply_substance_gate(raw_chunks, s, domain_filters, parsed_id)
            chunks_considered += len(raw_chunks)
            for r in raw_chunks:
                if r["substance_passed"]:
                    chunks_kept += 1
                else:
                    chunks_rejected += 1
                    reason = r["rejection_reason"]
                    chunk_rejection_reasons[reason] = (
                        chunk_rejection_reasons.get(reason, 0) + 1
                    )

        total = sections_rejected + sections_kept
        garbage_rate = (sections_rejected / total) if total > 0 else None

        chunk_total = chunks_rejected + chunks_kept
        chunk_garbage_rate = (
            (chunks_rejected / chunk_total) if chunk_total > 0 else None
        )

        rows.append({
            "source_id": source_id,
            "source_name": source_name,
            "sections_considered": sections_considered,
            "sections_kept": sections_kept,
            "sections_rejected": sections_rejected,
            "rejection_reasons": rejection_reasons,
            "documents_errored": documents_errored,
            "garbage_rate": garbage_rate,
            "chunks_considered": chunks_considered,
            "chunks_kept": chunks_kept,
            "chunks_rejected": chunks_rejected,
            "chunk_rejection_reasons": chunk_rejection_reasons,
            "chunk_garbage_rate": chunk_garbage_rate,
        })

    summary_sections_considered = sum(r["sections_considered"] for r in rows)
    summary_sections_kept = sum(r["sections_kept"] for r in rows)
    summary_sections_rejected = sum(r["sections_rejected"] for r in rows)
    summary_documents_errored = sum(r["documents_errored"] for r in rows)
    summary_chunks_considered = sum(r["chunks_considered"] for r in rows)
    summary_chunks_kept = sum(r["chunks_kept"] for r in rows)
    summary_chunks_rejected = sum(r["chunks_rejected"] for r in rows)
    summary_chunk_rejection_reasons: dict[str, int] = {}
    for r in rows:
        for reason, count in r["chunk_rejection_reasons"].items():
            summary_chunk_rejection_reasons[reason] = (
                summary_chunk_rejection_reasons.get(reason, 0) + count
            )

    sections_total = summary_sections_rejected + summary_sections_kept
    sections_garbage_rate = (
        (summary_sections_rejected / sections_total) if sections_total > 0 else None
    )

    chunks_total = summary_chunks_rejected + summary_chunks_kept
    summary_chunk_garbage_rate = (
        (summary_chunks_rejected / chunks_total) if chunks_total > 0 else None
    )

    summary = {
        "domain": domain,
        "sources_count": len(rows),
        "documents_errored": summary_documents_errored,
        "sections_considered": summary_sections_considered,
        "sections_kept": summary_sections_kept,
        "sections_rejected": summary_sections_rejected,
        "sections_garbage_rate": sections_garbage_rate,
        "chunks_considered": summary_chunks_considered,
        "chunks_kept": summary_chunks_kept,
        "chunks_rejected": summary_chunks_rejected,
        "chunk_rejection_reasons": summary_chunk_rejection_reasons,
        "chunk_garbage_rate": summary_chunk_garbage_rate,
    }

    return {"rows": rows, "summary": summary}
