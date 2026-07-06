"""Curate stage: cleaned_document artifact → curated_document artifact (CURATE-01..03).

Implements DataTrove-style quality filtering, corpus-wide MinHash deduplication,
and composite quality scoring — all sourced from the existing Postgres registry +
S3 storage, never from DataTrove's file-based I/O scaffolding.

Design decisions this module implements:
  D-01: curated_document always parents off the cleaned_document artifact,
        mirroring enriched_document's own parent convention exactly.
  D-02: corpus-wide dedup replaces Phase 3's transient per-call LSH scan as the
        authoritative dedup signal; batch_dedup_corpus() is the Phase 5 batch job
        that CONTEXT.md explicitly anticipated.
  CURATE-01: DataTrove filter classes are called via their .filter(doc) method
        DIRECTLY in a loop (never .run() which silently drops on first failure),
        recording every heuristic's pass/fail regardless of earlier failures.
  CURATE-02: ONE MinHashLSH index is built once over the whole corpus — O(1)
        amortized per insertion vs. the O(n) per-call pattern in clean.py.
  CURATE-03: Composite quality score combines Phase 3's parse-quality heuristic
        (metadata_["quality_score"]), Phase 4's enrichment quality_score column,
        and Phase 5's DataTrove filter pass ratio, queryable via CLI/API.

RESEARCH.md Anti-Pattern: Only `datatrove.data.Document` and
`datatrove.pipeline.filters.*` are ever imported — DataTrove's disk-based
reader/writer/executor scaffolding is never used. This preserves the FOUND-03
single S3 client invariant (StorageBackend via boto3/MinIO) and never introduces
a second S3 client path via fsspec/s3fs.
"""

from __future__ import annotations

import hashlib
from typing import Optional

import structlog
from datasketch import MinHashLSH
from sqlalchemy.exc import IntegrityError

from knowledge_lake.config.settings import CurateSettings, Settings, get_settings
from knowledge_lake.pipeline.clean import compute_minhash
from knowledge_lake.pipeline.utils import uri_to_key as _uri_to_key
from knowledge_lake.quality.scorer import compute_composite_quality_score
from knowledge_lake.registry.db import get_session
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.storage.s3 import StorageBackend

log = structlog.get_logger(__name__)


# ── Private helpers ───────────────────────────────────────────────────────────


def _build_filters(settings: CurateSettings) -> list:
    """Factory returning the configured DataTrove filter instances.

    Factored as a standalone function so tests can monkeypatch it with fake
    filter doubles that never require real nltk punkt_tab data (Pitfall 1).

    Imports are inside the function so they are deferred — tests that do not
    exercise the real filters never need datatrove or nltk punkt_tab installed.
    """
    from datatrove.pipeline.filters.c4_filters import C4QualityFilter  # noqa: PLC0415
    from datatrove.pipeline.filters.gopher_quality_filter import GopherQualityFilter  # noqa: PLC0415
    from datatrove.pipeline.filters.gopher_repetition_filter import GopherRepetitionFilter  # noqa: PLC0415

    return [
        GopherRepetitionFilter(),
        GopherQualityFilter(
            min_doc_words=settings.gopher_min_doc_words,
            max_doc_words=settings.gopher_max_doc_words,
        ),
        C4QualityFilter(
            filter_no_terminal_punct=settings.filter_no_terminal_punct,
        ),
    ]


def _curation_cache_key(cleaned_content_hash: str, filter_config_version: str) -> str:
    """Derive the synthetic content_hash used to look up a cached curated artifact.

    Mirrors _enrichment_cache_key exactly:
    sha256(f"{cleaned_content_hash}:{filter_config_version}")

    This drives idempotent re-runs via the existing
    UNIQUE(content_hash, artifact_type) constraint on artifacts.
    """
    return hashlib.sha256(
        f"{cleaned_content_hash}:{filter_config_version}".encode()
    ).hexdigest()


def score_document(
    cleaned_text: str,
    artifact_id: str,
    settings: CurateSettings,
) -> dict[str, dict]:
    """Call each configured DataTrove filter's .filter(doc) method directly.

    Wraps cleaned_text as an in-memory datatrove.data.Document (no file I/O),
    then calls each filter in the list returned by _build_filters() DIRECTLY
    via .filter(doc) — never .run() or a pipeline-list chain (RESEARCH.md
    Pitfall 2: .run() silently drops a document at its first failing filter
    and only records that one reason).

    Args:
        cleaned_text: The cleaned document text to evaluate.
        artifact_id:  The artifact ID (used as the DataTrove Document id field).
        settings:     CurateSettings (filter thresholds, config version).

    Returns:
        dict[str, dict] mapping filter class name to
        {"passed": bool, "reason": str | None} — one entry per configured
        filter, regardless of pass/fail order.
    """
    from datatrove.data import Document  # noqa: PLC0415 — deferred, avoids cold-start cost

    doc = Document(text=cleaned_text, id=artifact_id, metadata={})
    results: dict[str, dict] = {}
    for f in _build_filters(settings):
        outcome = f.filter(doc)
        if isinstance(outcome, tuple):
            passed, reason = outcome
        else:
            passed, reason = bool(outcome), None
        results[type(f).__name__] = {"passed": passed, "reason": reason}
    return results


# ── Public entry points ───────────────────────────────────────────────────────


def curate_document(
    cleaned_artifact_id: str,
    source_id: str,
    *,
    settings: Optional[Settings] = None,
) -> dict:
    """Curate a cleaned_document artifact (CURATE-01, CURATE-03).

    Flow:
    1. Fetch cleaned artifact from registry (validates type == 'cleaned_document').
    2. Retrieve cleaned text from S3 silver zone.
    3. Compute filter_results via score_document() (all heuristics recorded).
    4. Compute synthetic content_hash = _curation_cache_key(...).
    5. Cache check — return "cached" if this hash+type already exists.
    6. Resolve parse_quality_score from parent parsed_document.metadata_.
    7. Resolve enrich_quality_score from enriched_document sibling via
       get_child_artifact_by_type (Pitfall 4: sibling lookup, not ancestor walk).
    8. Compute composite_score via compute_composite_quality_score().
    9. Write curated_document artifact with filter_results + composite_score +
       dedup_status="not_yet_computed" in metadata_, and quality_score as real column.
    10. Handle concurrent race via IntegrityError → cache hit (mirrors WR-02).

    Args:
        cleaned_artifact_id: ID of the cleaned_document artifact to curate.
        source_id:           Source ID that owns the cleaned artifact.
        settings:            Settings override (for testing).

    Returns:
        dict with keys: artifact_id, status (curated/cached), cached, quality_score,
        and optionally dedup_status (from metadata_).

    Raises:
        ValueError: If the cleaned artifact does not exist or is not a
                    cleaned_document artifact.
    """
    s = settings or get_settings()
    storage = StorageBackend(s.storage)

    log.info("curate.start", cleaned_artifact_id=cleaned_artifact_id)

    # Step 1: Fetch cleaned artifact metadata
    with get_session() as session:
        cleaned_artifact = registry_repo.get_artifact(session, cleaned_artifact_id)
        if cleaned_artifact is None:
            raise ValueError(
                f"curate_document: cleaned_artifact {cleaned_artifact_id!r} not found in registry"
            )
        if cleaned_artifact.artifact_type != "cleaned_document":
            raise ValueError(
                f"curate_document: artifact {cleaned_artifact_id!r} has type "
                f"{cleaned_artifact.artifact_type!r}, expected 'cleaned_document' "
                "— curation always parents off the cleaned_document artifact (D-01)"
            )
        cleaned_content_hash = cleaned_artifact.content_hash
        storage_uri = cleaned_artifact.storage_uri
        if not storage_uri:
            raise ValueError(
                f"curate_document: cleaned_artifact {cleaned_artifact_id!r} has no storage_uri"
            )
        # Resolve parse_quality_score from parent parsed_document (step 6)
        parent_parsed = (
            registry_repo.get_artifact(session, cleaned_artifact.parent_artifact_id)
            if cleaned_artifact.parent_artifact_id
            else None
        )
        parse_quality_score = 0.5
        if parent_parsed and parent_parsed.metadata_:
            parse_quality_score = float(
                parent_parsed.metadata_.get("quality_score", 0.5)
            )

    # Step 2: Retrieve cleaned text from S3 (outside any session)
    cleaned_text = storage.get_object(_uri_to_key(storage_uri)).decode("utf-8")

    # Step 3: Compute filter results (no session, no DB — pure CPU)
    filter_results = score_document(cleaned_text, cleaned_artifact_id, s.curate)

    # Step 4: Compute synthetic content_hash for cache key
    synthetic_hash = _curation_cache_key(cleaned_content_hash, s.curate.filter_config_version)

    # Step 5: Cache check + resolve enriched sibling (step 7)
    with get_session() as session:
        existing = registry_repo.get_artifact_by_hash(session, synthetic_hash, "curated_document")
        if existing is not None:
            log.info(
                "curate.cache_hit",
                cleaned_artifact_id=cleaned_artifact_id,
                synthetic_hash=synthetic_hash,
            )
            return {
                "artifact_id": existing.id,
                "cached": True,
                "status": "cached",
                "quality_score": existing.quality_score,
            }

        # Step 7: Enriched sibling lookup (Pitfall 4 — sibling, not ancestor walk)
        enriched_sibling = registry_repo.get_child_artifact_by_type(
            session, cleaned_artifact_id, "enriched_document"
        )
        enrich_quality_score = 0.5
        if enriched_sibling is None:
            log.warning(
                "curate.enrich_sibling_missing",
                cleaned_artifact_id=cleaned_artifact_id,
                msg="No enriched_document sibling found; defaulting enrich_quality_score to 0.5",
            )
        else:
            enrich_quality_score = (
                float(enriched_sibling.quality_score)
                if enriched_sibling.quality_score is not None
                else 0.5
            )

        # Step 8: Composite quality score
        composite_score = compute_composite_quality_score(
            parse_quality_score=parse_quality_score,
            enrich_quality_score=enrich_quality_score,
            filter_results=filter_results,
        )

        # Step 9 + 10: Write artifact, handling concurrent race (WR-02)
        try:
            artifact = registry_repo.create_curated_artifact(
                session,
                source_id=source_id,
                parent_artifact_id=cleaned_artifact_id,
                content_hash=synthetic_hash,
                metadata={
                    "filter_results": filter_results,
                    "composite_quality_score": composite_score,
                    "parse_quality_score": parse_quality_score,
                    "enrich_quality_score": enrich_quality_score,
                    "dedup_status": "not_yet_computed",
                },
                quality_score=composite_score,
            )
            session.flush()
            result = {
                "artifact_id": artifact.id,
                "cached": False,
                "status": "curated",
                "quality_score": composite_score,
            }
        except IntegrityError:
            log.info(
                "curate.cache_race_lost",
                cleaned_artifact_id=cleaned_artifact_id,
                synthetic_hash=synthetic_hash,
            )
            # Rollback already handled by context manager exit on IntegrityError;
            # open a fresh session to fetch the winner's row.

    # Handle race-condition case (IntegrityError raised above, result not set)
    if "result" not in locals():
        with get_session() as session:
            existing = registry_repo.get_artifact_by_hash(
                session, synthetic_hash, "curated_document"
            )
            if existing is None:
                raise
            return {
                "artifact_id": existing.id,
                "cached": True,
                "status": "cached",
                "quality_score": existing.quality_score,
            }

    log.info(
        "curate.complete",
        artifact_id=result["artifact_id"],
        quality_score=result["quality_score"],
    )
    return result


def batch_dedup_corpus(*, settings: Optional[Settings] = None) -> dict:
    """Build ONE MinHash LSH index over ALL cleaned_document artifacts in a single pass.

    This is the Phase 5 authoritative corpus-wide deduplication (CURATE-02),
    replacing Phase 3's transient per-call O(n) MinHash rebuild (T-03-06).

    Algorithm:
    1. Fetch ALL cleaned_document artifacts in one session read.
    2. Build ONE MinHashLSH instance (never rebuilt per document pair).
    3. Retrieve each artifact's text from S3 and compute its MinHash via
       pipeline.clean.compute_minhash (import and reuse — never reimplement).
    4. Insert every MinHash into the single LSH index.
    5. For each artifact, query the SAME index (excluding self-matches) to
       classify "near_dup" vs "unique".
    6. Look up each cleaned_document's curated_document child via
       get_child_artifact_by_type and update metadata_["dedup_status"] in place.
       SQLAlchemy dirty-tracking on mutable JSON requires re-assigning the whole
       dict (not a nested key mutation) to register the change with the ORM.
    7. If no curated_document child exists yet, count under "skipped_no_curation".

    Args:
        settings: Settings override (for testing).

    Returns:
        dict with keys: total, unique, near_dup, skipped_no_curation.
    """
    s = settings or get_settings()
    storage = StorageBackend(s.storage)

    log.info("curate.batch_dedup.start")

    # Step 1: Fetch all cleaned_document artifacts
    with get_session() as session:
        all_cleaned = registry_repo.list_cleaned_artifacts(session)
        # Collect IDs and URIs so we can close this session before doing S3 I/O
        cleaned_info = [
            (artifact.id, artifact.storage_uri)
            for artifact in all_cleaned
            if artifact.storage_uri
        ]

    total = len(cleaned_info)
    if total == 0:
        log.info("curate.batch_dedup.no_artifacts")
        return {"total": 0, "unique": 0, "near_dup": 0, "skipped_no_curation": 0}

    # Step 2: Build ONE MinHashLSH instance for the whole corpus
    lsh = MinHashLSH(
        threshold=s.clean.minhash_threshold,
        num_perm=s.clean.minhash_num_perm,
    )

    # Steps 3-4: Compute and insert all MinHashes
    minhashes: dict[str, object] = {}
    for artifact_id, storage_uri in cleaned_info:
        try:
            key = _uri_to_key(storage_uri)
            text = storage.get_object(key).decode("utf-8")
            mh = compute_minhash(
                text,
                num_perm=s.clean.minhash_num_perm,
                shingle_size=s.clean.minhash_shingle_size,
            )
            minhashes[artifact_id] = mh
            lsh.insert(artifact_id, mh)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "curate.batch_dedup.insert_failed",
                artifact_id=artifact_id,
                error=str(exc),
            )

    # Step 5: Classify each artifact as near_dup or unique
    dedup_status: dict[str, str] = {}
    for artifact_id, mh in minhashes.items():
        matches = [m for m in lsh.query(mh) if m != artifact_id]
        dedup_status[artifact_id] = "near_dup" if matches else "unique"

    # Steps 6-7: Update curated_document children
    unique_count = 0
    near_dup_count = 0
    skipped_count = 0

    with get_session() as session:
        for artifact_id, status in dedup_status.items():
            curated_child = registry_repo.get_child_artifact_by_type(
                session, artifact_id, "curated_document"
            )
            if curated_child is None:
                skipped_count += 1
                log.debug(
                    "curate.batch_dedup.no_curated_child",
                    cleaned_artifact_id=artifact_id,
                )
                continue

            # Re-assign the whole dict (not a nested key mutation) so SQLAlchemy's
            # mutable JSON dirty-tracking picks up the change.
            new_metadata = dict(curated_child.metadata_ or {})
            new_metadata["dedup_status"] = status
            curated_child.metadata_ = new_metadata

            if status == "near_dup":
                near_dup_count += 1
                log.info(
                    "curate.batch_dedup.near_dup",
                    cleaned_artifact_id=artifact_id,
                    curated_artifact_id=curated_child.id,
                )
            else:
                unique_count += 1

    summary = {
        "total": total,
        "unique": unique_count,
        "near_dup": near_dup_count,
        "skipped_no_curation": skipped_count,
    }

    log.info(
        "curate.batch_dedup.complete",
        **summary,
    )
    return summary
