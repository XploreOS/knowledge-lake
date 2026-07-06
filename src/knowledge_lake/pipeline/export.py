"""Export stage: curated corpus, dataset examples → gold-zone Parquet/JSONL files.

Implements EXPORT-01 (RAG corpus → Parquet), EXPORT-02 (pretraining corpus → JSONL),
and EXPORT-03 (fine-tuning dataset → OpenAI chat-messages JSONL).

Design decisions:
    D-09: All exports write to a gold zone in the EXISTING StorageBackend (raw →
          bronze → silver → gold zone progression) — never a new storage backend.
    D-10: Polars writes the actual Parquet/JSONL files; DuckDB is the query/verify
          engine — DuckDB never writes export files.
    FOUND-03: Every write path uses a single in-memory io.BytesIO buffer, then
              StorageBackend.put_object() — never open() in write mode, never tempfile,
              never a local filesystem path.
    T-05-08: _RAG_CORPUS_FIELDS explicit allow-list enforced — export rows are built
             key-by-key, never via dataclasses.asdict() or a raw metadata_ dump.

05-AI-SPEC Section 6/7 hard-block guardrail:
    check_train_eval_contamination() is called as the FIRST statement of every export
    function. Any non-zero undocumented overlap between DATA-01's eval-set source
    documents and EXPORT-02/03's training-oriented source documents raises
    TrainEvalContaminationError and writes NO file — fail closed.
    ExportSettings.contamination_override_artifact_ids is the ONLY sanctioned bypass.

Security mitigations implemented:
    T-05-08: column allow-list (_RAG_CORPUS_FIELDS) — test_rag_corpus_export_uses_allow_list_only
    T-05-10: dangling lineage skip — test_finetune_export_skips_dangling_lineage
    T-05-11: train/eval contamination hard gate — test_contamination_blocks_*
"""

from __future__ import annotations

import io
from typing import Optional

import orjson
import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.ids import new_id
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.storage.s3 import StorageBackend

log = structlog.get_logger(__name__)

# ── Zone prefix ───────────────────────────────────────────────────────────────

# Module-level zone-prefix constant (mirrors pipeline/clean.py's _SILVER_PREFIX pattern).
# Lives beside the pipeline stage that uses it, not inside storage/s3.py (which is
# zone-agnostic).
_GOLD_PREFIX = "gold"

# ── RAG corpus column allow-list (T-05-08, ASVS V5 information-disclosure) ───

# Every export row is built key-by-key from this exact list.
# Never use dataclasses.asdict(), a raw metadata_ dump, or a wildcard dict expansion.
# This is the explicit rejection of DataTrove's own DiskWriter._default_adapter() pattern.
_RAG_CORPUS_FIELDS: list[str] = [
    "chunk_id",
    "document_id",
    "section_path",
    "page",
    "text",
    "domain",
    "document_type",
    "keywords",
    "quality_score",
]


# ── Exceptions ────────────────────────────────────────────────────────────────


class TrainEvalContaminationError(RuntimeError):
    """Raised when check_train_eval_contamination() finds undocumented overlap.

    05-AI-SPEC Section 7: "hard block, not an alert — export command fails closed."
    Add the offending cleaned_document artifact IDs to
    ExportSettings.contamination_override_artifact_ids only after explicit operator
    review of the accepted overlap.
    """


# ── Storage factory ───────────────────────────────────────────────────────────


def _make_storage(s: Settings) -> StorageBackend:
    """Build the single StorageBackend from Settings.

    Extracted as a module-level function so tests can monkeypatch it without
    constructing a real boto3 client.
    """
    return StorageBackend(s.storage)


# ── Train/eval contamination hard gate ────────────────────────────────────────


def check_train_eval_contamination(
    *,
    settings: Optional[Settings] = None,
) -> dict:
    """Full-corpus train/eval contamination check (05-AI-SPEC Section 6/7).

    Computes the overlap between:
    - eval_cleaned_doc_ids: cleaned_document parents of chunk artifacts cited by
      QA-shaped dataset_examples (source of ground-truth RAG-eval examples)
    - train_cleaned_doc_ids: union of
        a) finetune_cleaned_doc_ids: cleaned_document parents of enriched_document
           artifacts cited by instruction-shaped dataset_examples
        b) pretrain_cleaned_doc_ids: cleaned_document parents of curated_document
           artifacts whose quality_score >= min_quality_score_for_pretrain

    Direct overlap (same cleaned_document ID in eval and train sets) is always
    reported. Near-dup overlap: if any cleaned_document on BOTH the eval side AND
    the training side have dedup_status='near_dup', they are treated as an
    unresolved overlap risk (conservative by design — batch_dedup_corpus() records
    a per-document binary flag, not pairwise cluster membership).

    The contamination_override_artifact_ids exclusion is applied AFTER computing
    the raw overlap — only documented, reviewed overlaps are allowed through.

    Returns
    -------
    dict with keys:
        contaminated_count: int — total undocumented overlap after override exclusion
        contaminated_artifact_ids: list[str] — sorted list of offending cleaned_document IDs
        direct_overlap_count: int — count from direct ID match (post-override)
        near_dup_overlap_count: int — count from near-dup flag match (post-override)
    """
    s = settings or get_settings()
    override_ids = set(s.export.contamination_override_artifact_ids)

    with get_session() as session:
        # Step 1: Build eval_cleaned_doc_ids from QA-shaped examples
        # and finetune_cleaned_doc_ids from instruction-shaped examples
        all_examples = registry_repo.list_all_dataset_examples(session)

        eval_cleaned_doc_ids: set[str] = set()
        finetune_cleaned_doc_ids: set[str] = set()

        for ex in all_examples:
            payload = ex.payload or {}
            if "question" in payload:
                # QA-shaped → eval set
                if ex.source_artifact_id:
                    artifact = registry_repo.get_artifact(session, ex.source_artifact_id)
                    if artifact is not None and artifact.artifact_type == "chunk":
                        # chunk -> parsed -> cleaned lineage: chunk.parent_artifact_id = parsed
                        # We need the cleaned_document, which is a parent of parsed via chunk
                        # Actually: chunk's parent = parsed_document
                        # We need to go: chunk -> parsed -> cleaned
                        # But chunk's parent_artifact_id IS the parsed_document,
                        # and cleaned_document's parent_artifact_id IS the parsed_document.
                        # So cleaned_document shares the same parsed parent as chunk.
                        # Look up the cleaned child of the parsed parent.
                        parsed_id = artifact.parent_artifact_id
                        if parsed_id:
                            cleaned = registry_repo.get_child_artifact_by_type(
                                session, parsed_id, "cleaned_document"
                            )
                            if cleaned is not None:
                                eval_cleaned_doc_ids.add(cleaned.id)
            elif "instruction" in payload:
                # Instruction-shaped → fine-tuning (train) set
                if ex.source_artifact_id:
                    artifact = registry_repo.get_artifact(session, ex.source_artifact_id)
                    if artifact is not None and artifact.artifact_type == "enriched_document":
                        # enriched_document.parent_artifact_id = cleaned_document
                        if artifact.parent_artifact_id:
                            finetune_cleaned_doc_ids.add(artifact.parent_artifact_id)
                    # silently skip on unresolved source (EXPORT-03's dangling check handles it)

        # Step 2: Build pretrain_cleaned_doc_ids from curated_document quality gate
        all_curated = registry_repo.list_artifacts_by_type(session, "curated_document")
        pretrain_cleaned_doc_ids: set[str] = set()
        min_q = s.export.min_quality_score_for_pretrain
        for curated in all_curated:
            if (curated.quality_score or 0.0) >= min_q:
                if curated.parent_artifact_id:
                    pretrain_cleaned_doc_ids.add(curated.parent_artifact_id)

        # Step 3: Union training sides
        train_cleaned_doc_ids = finetune_cleaned_doc_ids | pretrain_cleaned_doc_ids

        # Step 4: Direct overlap
        direct_overlap: set[str] = eval_cleaned_doc_ids & train_cleaned_doc_ids

        # Step 5: Near-dup overlap — conservative by design
        # Any cleaned_document flagged near_dup on BOTH the eval side AND the training
        # side is treated as an unresolved overlap risk (binary flag, not pairwise cluster)
        near_dup_artifacts = registry_repo.list_curated_documents_by_dedup_status(
            session, "near_dup"
        )
        near_dup_cleaned_doc_ids = {a.parent_artifact_id for a in near_dup_artifacts if a.parent_artifact_id}

        eval_near_dup = eval_cleaned_doc_ids & near_dup_cleaned_doc_ids
        train_near_dup = train_cleaned_doc_ids & near_dup_cleaned_doc_ids
        # Only flag as near-dup overlap when BOTH sides have near_dup documents
        near_dup_overlap: set[str] = (eval_near_dup | train_near_dup) if (eval_near_dup and train_near_dup) else set()

        # Step 6: Apply override exclusion
        all_overlap = (direct_overlap | near_dup_overlap) - override_ids
        direct_overlap_clean = direct_overlap - override_ids
        near_dup_overlap_clean = near_dup_overlap - override_ids

    return {
        "contaminated_count": len(all_overlap),
        "contaminated_artifact_ids": sorted(all_overlap),
        "direct_overlap_count": len(direct_overlap_clean),
        "near_dup_overlap_count": len(near_dup_overlap_clean),
    }


def _enforce_no_contamination(s: Settings) -> None:
    """Call check_train_eval_contamination() and raise TrainEvalContaminationError
    if any undocumented overlap exists.

    This is the fail-closed hard gate 05-AI-SPEC Section 6/7 requires at
    'every klake export invocation, not sampled.' Call this as the FIRST statement
    of every export function.
    """
    result = check_train_eval_contamination(settings=s)
    if result["contaminated_count"] > 0:
        raise TrainEvalContaminationError(
            f"train/eval contamination: {result['contaminated_count']} undocumented overlap(s) "
            f"— {result['contaminated_artifact_ids']}. "
            f"Add to ExportSettings.contamination_override_artifact_ids if this overlap "
            f"is deliberate and documented."
        )


# ── Export functions ──────────────────────────────────────────────────────────


def export_rag_corpus(
    *,
    settings: Optional[Settings] = None,
) -> dict:
    """Export all chunk artifacts as a Parquet file to the gold zone (EXPORT-01).

    Fails closed with TrainEvalContaminationError if any undocumented train/eval
    overlap exists (05-AI-SPEC Section 6/7 hard gate — checked FIRST).

    Joins each chunk's citation fields with its enrichment sibling via
    registry_repo.get_enriched_artifact_for_parsed() — the same join pattern
    pipeline.index.index() already uses (INDEX-01 D-07).

    Every export row is built strictly from _RAG_CORPUS_FIELDS — never a raw
    metadata_ dump (T-05-08, ASVS V5 information-disclosure mitigation).

    All bytes go through an in-memory io.BytesIO buffer → StorageBackend.put_object()
    — never a local filesystem write (PROJECT.md constraint).

    Returns
    -------
    dict with keys: dataset_id, storage_uri, row_count
    """
    import polars as pl

    s = settings or get_settings()
    # Hard gate: fail closed on any undocumented train/eval contamination
    _enforce_no_contamination(s)

    storage = _make_storage(s)

    with get_session() as session:
        chunks = registry_repo.list_artifacts_by_type(session, "chunk")

        rows: list[dict] = []
        for chunk in chunks:
            # Resolve domain and enrichment sibling — same pattern as pipeline/index.py
            domain = registry_repo.get_domain_for_source(session, chunk.source_id)

            parsed_id = chunk.parent_artifact_id  # chunk -> parsed
            enriched = (
                registry_repo.get_enriched_artifact_for_parsed(session, parsed_id)
                if parsed_id
                else None
            )
            enrichment_metadata = (enriched.metadata_ or {}) if enriched else {}
            quality_score = enriched.quality_score if enriched else None

            meta = chunk.metadata_ or {}

            # Build row strictly from allow-list — never **meta or asdict() (T-05-08)
            row = {
                "chunk_id": chunk.id,
                "document_id": parsed_id or "",
                "section_path": meta.get("section_path", chunk.section_path or ""),
                "page": meta.get("page", chunk.page_ref or 1),
                "text": meta.get("text", ""),
                "domain": domain,
                "document_type": enrichment_metadata.get("document_type"),
                "keywords": enrichment_metadata.get("keywords", []),
                "quality_score": quality_score,
            }
            rows.append(row)

        log.info("export.rag_corpus.building", row_count=len(rows))

        if not rows:
            # Write an empty Parquet file with the schema so DuckDB can read it
            df = pl.DataFrame({f: [] for f in _RAG_CORPUS_FIELDS})
        else:
            df = pl.DataFrame(rows, schema={
                "chunk_id": pl.Utf8,
                "document_id": pl.Utf8,
                "section_path": pl.Utf8,
                "page": pl.Int64,
                "text": pl.Utf8,
                "domain": pl.Utf8,
                "document_type": pl.Utf8,
                "keywords": pl.List(pl.Utf8),
                "quality_score": pl.Float64,
            })

        buf = io.BytesIO()
        df.write_parquet(buf)
        buf.seek(0)

        export_id = new_id("dataset")
        key = f"{s.export.gold_prefix}/rag_corpus/{export_id}.parquet"
        storage.put_object(key, buf.getvalue())
        uri = storage.object_uri(key)

        dataset = registry_repo.create_dataset(
            session,
            name=f"rag_corpus_{export_id}",
            dataset_type="rag_corpus",
            format="parquet",
            storage_uri=uri,
            example_count=len(rows),
        )
        session.flush()
        dataset_id = dataset.id
        session.commit()

    log.info("export.rag_corpus.complete", dataset_id=dataset_id, row_count=len(rows), uri=uri)
    return {"dataset_id": dataset_id, "storage_uri": uri, "row_count": len(rows)}


def export_pretrain_corpus(
    *,
    settings: Optional[Settings] = None,
) -> dict:
    """Export quality-filtered curated_document text as JSONL to the gold zone (EXPORT-02).

    Fails closed with TrainEvalContaminationError if any undocumented train/eval
    overlap exists (05-AI-SPEC Section 6/7 hard gate — checked FIRST).

    Only documents whose composite_quality_score >= ExportSettings.min_quality_score_for_pretrain
    are included — quality gate applied at export time only (curation stays annotate-only).

    Returns
    -------
    dict with keys: dataset_id, storage_uri, row_count
    """
    s = settings or get_settings()
    # Hard gate: fail closed on any undocumented train/eval contamination
    _enforce_no_contamination(s)

    storage = _make_storage(s)
    min_q = s.export.min_quality_score_for_pretrain

    with get_session() as session:
        all_curated = registry_repo.list_artifacts_by_type(session, "curated_document")
        qualifying = [
            a for a in all_curated
            if (a.quality_score or 0.0) >= min_q
        ]

        log.info("export.pretrain.qualifying", total=len(all_curated), qualifying=len(qualifying))

        rows: list[dict] = []
        for curated in qualifying:
            parent_id = curated.parent_artifact_id  # curated -> cleaned
            if not parent_id:
                continue
            cleaned = registry_repo.get_artifact(session, parent_id)
            if cleaned is None:
                continue
            # Retrieve text from S3 silver zone
            if cleaned.storage_uri:
                # Extract the S3 key from the URI (s3://bucket/key)
                parts = cleaned.storage_uri.split("/", 3)
                key = parts[3] if len(parts) == 4 else cleaned.storage_uri
                try:
                    text_bytes = storage.get_object(key)
                    text = text_bytes.decode("utf-8", errors="replace")
                except Exception:
                    text = ""
            else:
                text = ""

            rows.append({
                "text": text,
                "document_id": parent_id,
                "quality_score": curated.quality_score,
            })

        # Write JSONL via orjson — one object per line
        jsonl_lines = [orjson.dumps(row) for row in rows]
        jsonl_bytes = b"\n".join(jsonl_lines)
        if jsonl_bytes:
            jsonl_bytes += b"\n"

        export_id = new_id("dataset")
        key = f"{s.export.gold_prefix}/pretrain/{export_id}.jsonl"
        storage.put_object(key, jsonl_bytes)
        uri = storage.object_uri(key)

        dataset = registry_repo.create_dataset(
            session,
            name=f"pretrain_{export_id}",
            dataset_type="pretrain_corpus",
            format="jsonl",
            storage_uri=uri,
            example_count=len(rows),
        )
        session.flush()
        dataset_id = dataset.id
        session.commit()

    log.info("export.pretrain.complete", dataset_id=dataset_id, row_count=len(rows), uri=uri)
    return {"dataset_id": dataset_id, "storage_uri": uri, "row_count": len(rows)}


def export_finetune_dataset(
    dataset_name: str,
    *,
    settings: Optional[Settings] = None,
) -> dict:
    """Export a named dataset's examples as OpenAI chat-messages JSONL (EXPORT-03).

    Fails closed with TrainEvalContaminationError if any undocumented train/eval
    overlap exists (05-AI-SPEC Section 6/7 hard gate — checked FIRST).

    For each DatasetExample:
    - Verifies source_artifact_id resolves to a live artifact; skips (counting as
      skipped_dangling_lineage) if not found — DATA-03 lineage-integrity safeguard.
    - Branches on payload shape:
        QA-shaped (question/answer): {"messages": [{"role": "user", "content": question},
                                                    {"role": "assistant", "content": answer}]}
        Instruction-shaped (instruction/output): user content = instruction + optional
            "\n\n" + input; assistant content = output.

    Returns
    -------
    dict with keys: dataset_id, storage_uri, row_count, skipped_dangling_lineage
    """
    s = settings or get_settings()
    # Hard gate: fail closed on any undocumented train/eval contamination
    _enforce_no_contamination(s)

    storage = _make_storage(s)

    with get_session() as session:
        dataset = registry_repo.get_dataset_by_name(session, dataset_name)
        if dataset is None:
            raise ValueError(f"Dataset not found: {dataset_name!r}")

        examples = registry_repo.list_dataset_examples(session, dataset.id)

        surviving_rows: list[dict] = []
        skipped_dangling = 0

        for ex in examples:
            # DATA-03 lineage-integrity safeguard: skip examples with dangling source
            if ex.source_artifact_id is None:
                skipped_dangling += 1
                log.warning(
                    "export.finetune.dangling_lineage",
                    example_id=ex.id,
                    reason="source_artifact_id is NULL",
                )
                continue

            artifact = registry_repo.get_artifact(session, ex.source_artifact_id)
            if artifact is None:
                skipped_dangling += 1
                log.warning(
                    "export.finetune.dangling_lineage",
                    example_id=ex.id,
                    source_artifact_id=ex.source_artifact_id,
                )
                continue

            payload = ex.payload or {}

            # Build chat-messages format based on payload shape
            if "question" in payload:
                # QA-shaped (DATA-01 RAG-eval)
                messages = [
                    {"role": "user", "content": payload["question"]},
                    {"role": "assistant", "content": payload["answer"]},
                ]
            else:
                # Instruction-shaped (DATA-02 instruction-tuning)
                user_content = payload.get("instruction", "")
                if payload.get("input"):
                    user_content = user_content + "\n\n" + payload["input"]
                messages = [
                    {"role": "user", "content": user_content},
                    {"role": "assistant", "content": payload.get("output", "")},
                ]

            surviving_rows.append({"messages": messages})

        log.info(
            "export.finetune.building",
            total=len(examples),
            surviving=len(surviving_rows),
            skipped_dangling=skipped_dangling,
        )

        # Write JSONL — one object per line
        jsonl_lines = [orjson.dumps(row) for row in surviving_rows]
        jsonl_bytes = b"\n".join(jsonl_lines)
        if jsonl_bytes:
            jsonl_bytes += b"\n"

        key = f"{s.export.gold_prefix}/finetune/{dataset.id}.jsonl"
        storage.put_object(key, jsonl_bytes)
        uri = storage.object_uri(key)

        registry_repo.update_dataset_export(
            session,
            dataset.id,
            format="jsonl",
            storage_uri=uri,
            example_count=len(surviving_rows),
        )
        session.flush()
        dataset_id = dataset.id
        session.commit()

    log.info(
        "export.finetune.complete",
        dataset_id=dataset_id,
        row_count=len(surviving_rows),
        skipped_dangling=skipped_dangling,
        uri=uri,
    )
    return {
        "dataset_id": dataset_id,
        "storage_uri": uri,
        "row_count": len(surviving_rows),
        "skipped_dangling_lineage": skipped_dangling,
    }


def verify_export(
    export_uri: str,
    *,
    settings: Optional[Settings] = None,
) -> int:
    """Verify an exported file by reading it through DuckDB (D-10, read-only).

    For Parquet files: uses DuckDB's httpfs extension with MinIO path-style S3 API.
    For JSONL files: uses DuckDB's read_json_auto.

    DuckDB is the query/verification engine — it reads the file Polars wrote,
    never writes export files itself (D-10 role split).

    Configures s3_url_style='path' for MinIO compatibility (RESEARCH.md Code Examples
    pattern): strips http(s):// prefix from endpoint_url for s3_endpoint.

    Parameters
    ----------
    export_uri:
        S3 URI of the exported file (s3://bucket/path/to/file).
    settings:
        Settings override.

    Returns
    -------
    int
        Row count from the DuckDB COUNT(*) query.
    """
    import duckdb

    s = settings or get_settings()
    st = s.storage

    con = duckdb.connect()
    try:
        con.execute("INSTALL httpfs;")
        con.execute("LOAD httpfs;")
        con.execute("SET s3_url_style='path';")
        con.execute("SET s3_use_ssl=false;")

        # Strip http(s):// prefix from endpoint_url for s3_endpoint
        # (RESEARCH.md exact Code Examples pattern for MinIO compatibility)
        endpoint = ""
        if st.endpoint_url:
            endpoint = st.endpoint_url
            for prefix in ("https://", "http://"):
                if endpoint.startswith(prefix):
                    endpoint = endpoint[len(prefix):]
                    break
        con.execute(f"SET s3_endpoint='{endpoint}';")

        if st.access_key_id:
            con.execute(f"SET s3_access_key_id='{st.access_key_id}';")
        if st.secret_access_key:
            con.execute(f"SET s3_secret_access_key='{st.secret_access_key}';")

        if export_uri.endswith(".parquet"):
            query = f"SELECT COUNT(*) FROM read_parquet('{export_uri}')"
        else:
            query = f"SELECT COUNT(*) FROM read_json_auto('{export_uri}')"

        result = con.execute(query).fetchone()
        return int(result[0]) if result else 0
    finally:
        con.close()
