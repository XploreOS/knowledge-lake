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

Scope is strictly ``parse -> clean``. This module must never import
``knowledge_lake.pipeline.embed`` or ``knowledge_lake.pipeline.index`` — the
audit is read/measurement-only (D-07's "the pipeline IS the measurement")
and must never trigger vector-store writes or embedding spend.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


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
                    parsed_id, source_id, parsed_doc=parsed_doc, settings=s
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
