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
— the audit must never trigger vector-store writes or embedding spend
(D-07's "the pipeline IS the measurement").

WR-01: ``run_full_pipeline_audit()`` is NOT side-effect-free. It persists
real ``chunk()`` artifacts and calls the real ``export_rag_corpus()``, which
mints a fresh gold-zone Parquet object + ``Dataset`` row on every invocation
(no cleanup, no dedup against a prior run's export). Treat ``--full`` as a
real pipeline run for measurement purposes, not a read-only inspection —
repeated/scheduled invocations will accumulate gold-zone exports over time.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)

# Phase 22 D-06: the two originally-audited baselines from the milestone's
# first end-to-end run against real healthcare data (.planning/MILESTONE-CONTEXT.md)
# — reported side by side with this run's own measured rates for before/after
# comparison. Not thresholds, not gates — pure reporting constants.
_BASELINE_CHUNK_GARBAGE_RATE = 0.28
"""28% garbage chunks (4,499 chunks) — .planning/MILESTONE-CONTEXT.md."""

_BASELINE_EXPORT_JUNK_RATE = 0.33
"""33% junk rows (357 gold rows) — .planning/MILESTONE-CONTEXT.md."""


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
        ``sections_garbage_rate``/``chunk_garbage_rate`` computed identically,
        plus ``export_kept``/``export_junk``/``export_junk_rate`` (criterion
        #2, D-04-safe — scoped to only this run's own chunk IDs, tracked from
        the real persisting ``chunk()`` call's return value, never inferred
        from registry timestamps) and ``baseline_chunk_garbage_rate``/
        ``baseline_export_junk_rate`` (D-06 reporting constants).
    """
    from sqlalchemy import select

    from knowledge_lake.config.settings import Settings, get_settings  # noqa: F401
    from knowledge_lake.pipeline.chunk import _apply_substance_gate, _build_token_chunks, chunk
    from knowledge_lake.pipeline.clean import clean
    from knowledge_lake.pipeline.ingest import _detect_mime_from_uri
    from knowledge_lake.pipeline.parse import load_parsed_doc, parse, reparse_from_raw
    from knowledge_lake.registry import repo as registry_repo
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.models import Artifact, Source

    s = settings or get_settings()
    domain_filters = _resolve_domain_filters(s)
    # Corpus-wide (not per-source/per-document) — initialized before the
    # per-source loop so this run's chunk-ID set spans every source.
    this_run_chunk_ids: set[str] = set()

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

            try:
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

                # Real persisted chunk() call (criterion #2 groundwork). Enforce
                # mode (the shipped default) never persists a rejected chunk in
                # the first place (RESEARCH.md Pitfall 2) — every chunk_id this
                # run tracks is, by construction, already substance_passed=True.
                # Track chunk IDs from the RETURN VALUE only (RESEARCH.md
                # Pitfall 4) — a content-hash no-op branch means a re-run of an
                # already-chunked document is a legitimate reuse, not a bug, and
                # the returned dict's substance_passed is always freshly
                # computed by THIS call regardless of which branch fired.
                chunk_results = chunk(
                    parsed_id, source_id, cleaned_doc, settings=s, domain_filters=domain_filters,
                )
                this_run_chunk_ids.update(r["chunk_id"] for r in chunk_results)
            except Exception:
                # CR-01: chunk-level measurement and the real, persisting
                # chunk() call must never abort the whole domain scan — mirror
                # the parse/clean error-isolation contract above so a
                # transient S3/DB failure on one document is counted and
                # skipped, not propagated out of run_full_pipeline_audit().
                documents_errored += 1
                log.warning(
                    "quality_audit.chunk_failed",
                    source_id=source_id,
                    raw_id=raw_id,
                    parsed_id=parsed_id,
                    exc_info=True,
                )
                continue

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

    # D-04-safe export-junk scoping (criterion #2): call the REAL
    # export_rag_corpus() once, corpus-wide, strictly after the per-source
    # loop (D-03 — never per-document/per-source) — then filter its output
    # Parquet to only this run's own chunk-ID set. This proves the actual
    # shipped export path behaves correctly on freshly-gated data without
    # ever re-implementing export_rag_corpus()'s substance_passed filter as
    # a second predicate (RESEARCH.md Anti-Pattern) and without a registry-
    # wide list_artifacts_by_type() scan (RESEARCH.md Pattern 2).
    if this_run_chunk_ids:
        import io

        import polars as pl

        from knowledge_lake.pipeline.export import (
            TrainEvalContaminationError,
            _make_storage,
            export_rag_corpus,
        )
        from knowledge_lake.pipeline.utils import uri_to_key

        try:
            export_result = export_rag_corpus(domain=domain, settings=s)
        except TrainEvalContaminationError:
            # CR-02: export_rag_corpus()'s first statement is a corpus-wide
            # train/eval contamination hard gate, unrelated to this run's own
            # freshly-chunked documents. A "measurement" command must never
            # crash on a pre-existing, undocumented corpus-wide overlap —
            # report export-level measurement as unavailable and let the
            # section/chunk-level rows still return.
            log.warning(
                "quality_audit.export_scoping_skipped_contamination",
                domain=domain,
            )
            export_kept = 0
            export_junk = 0
            export_junk_rate = None
        else:
            # _make_storage (not a fresh StorageBackend(s.storage)) is used
            # deliberately — it is export.py's own test patch point, so a
            # caller-side read-back of the exported Parquet goes through the
            # same storage double as export_rag_corpus()'s own write in tests
            # (patch.object(export_module, "_make_storage", ...)).
            storage = _make_storage(s)
            buf = io.BytesIO(storage.get_object(uri_to_key(export_result["storage_uri"])))
            df = pl.read_parquet(buf)
            export_kept = df.filter(pl.col("chunk_id").is_in(list(this_run_chunk_ids))).height
            export_junk = len(this_run_chunk_ids) - export_kept
            export_junk_rate = export_junk / len(this_run_chunk_ids)
    else:
        export_kept = 0
        export_junk = 0
        export_junk_rate = None

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
        "export_kept": export_kept,
        "export_junk": export_junk,
        "export_junk_rate": export_junk_rate,
        "baseline_chunk_garbage_rate": _BASELINE_CHUNK_GARBAGE_RATE,
        "baseline_export_junk_rate": _BASELINE_EXPORT_JUNK_RATE,
    }

    return {"rows": rows, "summary": summary}
