"""Tests for pipeline/export.py — Parquet/JSONL export with column allow-listing.

Uses an in-memory-SQLite-backed session (mirrors tests/unit/test_enrich.py's
engine/session fixtures) with knowledge_lake.registry.db.get_engine monkeypatched.
StorageBackend is patched at the pipeline.export module level so no real S3 client
is constructed.

Security coverage:
    - T-05-08: _RAG_CORPUS_FIELDS allow-list enforced (test_rag_corpus_export_uses_allow_list_only)
    - T-05-10: dangling lineage detection (test_finetune_export_skips_dangling_lineage)
    - PROJECT.md "no local filesystem as production store" (test_no_local_disk_writes)
    - 05-AI-SPEC Section 6/7 train/eval contamination hard gate (test_contamination_*)
"""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.registry.db as registry_db


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    """In-memory SQLite engine, shared connection via StaticPool."""
    from knowledge_lake.registry.models import Base

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _patch_engine(monkeypatch, engine):
    """Route registry.db.get_session() to the in-memory test engine."""
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)


@pytest.fixture()
def session(engine):
    with Session(engine) as sess:
        yield sess


@pytest.fixture()
def source(session):
    """Seed a minimal Source row."""
    from knowledge_lake.registry import repo as registry_repo

    src = registry_repo.create_source(
        session,
        name="test-source",
        source_type="upload",
        config={"domain": "healthcare"},
    )
    session.flush()
    return src


@pytest.fixture()
def export_settings():
    """ExportSettings with defaults."""
    from knowledge_lake.config.settings import ExportSettings

    return ExportSettings()


def _make_settings(engine, *, storage_settings=None):
    """Build a Settings instance with the test DB and a mocked storage."""
    from knowledge_lake.config.settings import Settings, StorageSettings

    ss = storage_settings or StorageSettings(
        endpoint_url="http://localhost:9000",
        bucket="test-bucket",
        access_key_id="test",
        secret_access_key="test",
    )
    return Settings(
        database_url=str(engine.url),
        storage=ss,
        _env_file=None,  # type: ignore[call-arg]
    )


# ── Task 2 tests ──────────────────────────────────────────────────────────────


class TestPretrain:
    """EXPORT-02: pretraining corpus → JSONL from curated_document text."""

    def test_pretrain_jsonl_schema(self, session, source, engine):
        """export_pretrain_corpus() writes one JSONL line per qualifying document."""
        from knowledge_lake.registry import repo as registry_repo
        from knowledge_lake.config.settings import Settings, StorageSettings, ExportSettings

        # Seed two cleaned documents and their curated_document children
        # cleaned 1 → curated with quality_score=0.8 (above threshold)
        raw1 = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="raw1hash"
        )
        session.flush()
        parsed1 = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw1.id,
            content_hash="parsed1hash",
        )
        session.flush()
        cleaned1 = registry_repo.create_cleaned_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed1.id,
            content_hash="cleaned1hash",
            storage_uri="s3://bucket/silver/doc1.md",
        )
        session.flush()
        curated1 = registry_repo.create_curated_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=cleaned1.id,
            content_hash="curated1hash",
            metadata={"dedup_status": "unique"},
            quality_score=0.8,
        )
        session.flush()

        # cleaned 2 → curated with quality_score=0.1 (below threshold=0.4)
        raw2 = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="raw2hash"
        )
        session.flush()
        parsed2 = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw2.id,
            content_hash="parsed2hash",
        )
        session.flush()
        cleaned2 = registry_repo.create_cleaned_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed2.id,
            content_hash="cleaned2hash",
            storage_uri="s3://bucket/silver/doc2.md",
        )
        session.flush()
        curated2 = registry_repo.create_curated_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=cleaned2.id,
            content_hash="curated2hash",
            metadata={"dedup_status": "unique"},
            quality_score=0.1,
        )
        session.flush()
        session.commit()

        settings = _make_settings(engine)

        written_data: dict[str, bytes] = {}

        def mock_put_object(key, data, **kwargs):
            written_data[key] = data

        def mock_get_object(key):
            # Return mock text for the cleaned document
            return b"This is test document text."

        mock_storage = MagicMock()
        mock_storage.put_object.side_effect = mock_put_object
        mock_storage.get_object.side_effect = mock_get_object
        mock_storage.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"

        import knowledge_lake.pipeline.export as export_module

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            result = export_module.export_pretrain_corpus(settings=settings)

        assert result["row_count"] == 1, f"Expected 1 row (quality≥0.4), got {result['row_count']}"

        # Find the JSONL key
        jsonl_keys = [k for k in written_data if k.endswith(".jsonl")]
        assert len(jsonl_keys) == 1, f"Expected exactly 1 JSONL file, got {jsonl_keys}"

        written_bytes = written_data[jsonl_keys[0]]
        lines = [l for l in written_bytes.decode().splitlines() if l.strip()]
        assert len(lines) == 1, f"Expected 1 JSONL line, got {len(lines)}"
        row = json.loads(lines[0])
        assert "text" in row, f"Expected 'text' key in JSONL row, got {list(row.keys())}"


class TestFinetune:
    """EXPORT-03: fine-tuning dataset → OpenAI chat-messages JSONL."""

    def _seed_dataset_with_examples(self, session, source, *, qa=True, instruction=False):
        """Seed a Dataset + DatasetExample(s) with valid source artifacts.

        QA examples and instruction examples MUST use separate document trees
        to avoid triggering the train/eval contamination check (test_contamination_*
        tests validate that behavior separately).
        """
        from knowledge_lake.registry import repo as registry_repo

        # Document tree A: for QA examples (eval set) — separate from instruction tree
        raw_a = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="raw_chunk_hash_qa"
        )
        session.flush()
        parsed_a = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw_a.id,
            content_hash="parsed_chunk_hash_qa",
        )
        session.flush()
        # cleaned_a is only seeded when qa=True (needs separate cleaned for contamination check)
        cleaned_a = registry_repo.create_cleaned_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed_a.id,
            content_hash="cleaned_qa_hash",
        )
        session.flush()
        chunk = registry_repo.create_chunk_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed_a.id,
            content_hash="chunk_hash",
            metadata={"text": "The HIPAA Security Rule requires safeguards."},
        )
        session.flush()

        # Document tree B: for instruction examples (train set) — separate from QA tree
        raw_b = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="raw_instr_hash"
        )
        session.flush()
        parsed_b = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw_b.id,
            content_hash="parsed_instr_hash",
        )
        session.flush()
        cleaned_b = registry_repo.create_cleaned_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed_b.id,
            content_hash="cleaned_ft_hash",
            storage_uri="s3://bucket/silver/ft_doc.md",
        )
        session.flush()
        enriched = registry_repo.create_enriched_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=cleaned_b.id,
            content_hash="enriched_ft_hash",
        )
        session.flush()

        dataset = registry_repo.get_or_create_dataset(
            session, name="test_finetune_ds", dataset_type="instruction_tuning"
        )
        session.flush()

        examples = []
        if qa:
            qa_example = registry_repo.create_dataset_example(
                session,
                dataset_id=dataset.id,
                source_artifact_id=chunk.id,
                example_index=0,
                payload={
                    "question": "What does HIPAA require?",
                    "answer": "Administrative safeguards.",
                    "citation_chunk_id": chunk.id,
                    "_cache_key": "qa_cache_key",
                },
            )
            session.flush()
            examples.append(qa_example)

        if instruction:
            instr_example = registry_repo.create_dataset_example(
                session,
                dataset_id=dataset.id,
                source_artifact_id=enriched.id,
                example_index=1 if qa else 0,
                payload={
                    "instruction": "Explain HIPAA Security Rule",
                    "input": "Focus on administrative safeguards",
                    "output": "HIPAA Security Rule requires administrative safeguards.",
                    "_cache_key": "instr_cache_key",
                },
            )
            session.flush()
            examples.append(instr_example)

        session.commit()
        return dataset, examples, chunk, enriched

    def test_finetune_jsonl_chat_format(self, session, source, engine):
        """export_finetune_dataset() writes chat-messages format JSONL for QA + instruction examples."""
        dataset, examples, chunk, enriched = self._seed_dataset_with_examples(
            session, source, qa=True, instruction=True
        )

        settings = _make_settings(engine)

        written_data: dict[str, bytes] = {}

        def mock_put_object(key, data, **kwargs):
            written_data[key] = data

        mock_storage = MagicMock()
        mock_storage.put_object.side_effect = mock_put_object
        mock_storage.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"

        import knowledge_lake.pipeline.export as export_module

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            result = export_module.export_finetune_dataset(
                "test_finetune_ds", settings=settings
            )

        assert result["row_count"] == 2, f"Expected 2 rows, got {result['row_count']}"

        jsonl_keys = [k for k in written_data if k.endswith(".jsonl")]
        assert len(jsonl_keys) == 1
        lines = [l for l in written_data[jsonl_keys[0]].decode().splitlines() if l.strip()]
        assert len(lines) == 2

        for line in lines:
            row = json.loads(line)
            assert "messages" in row, f"Expected 'messages' key, got {list(row.keys())}"
            messages = row["messages"]
            assert len(messages) >= 2
            roles = [m["role"] for m in messages]
            assert "user" in roles
            assert "assistant" in roles

        # Check QA-shaped line: user content == question
        qa_row = json.loads(lines[0])
        user_msg = next(m for m in qa_row["messages"] if m["role"] == "user")
        assert user_msg["content"] == "What does HIPAA require?"

        # Check instruction-shaped line: user content == instruction (+ input suffix)
        instr_row = json.loads(lines[1])
        user_msg_instr = next(m for m in instr_row["messages"] if m["role"] == "user")
        assert "Explain HIPAA Security Rule" in user_msg_instr["content"]
        assert "Focus on administrative safeguards" in user_msg_instr["content"]

    def test_finetune_export_skips_dangling_lineage(self, session, source, engine):
        """export_finetune_dataset() skips examples with non-existent source_artifact_id."""
        from knowledge_lake.registry import repo as registry_repo

        dataset = registry_repo.get_or_create_dataset(
            session, name="ds_dangling", dataset_type="instruction_tuning"
        )
        session.flush()

        # Create an example whose source_artifact_id points at a FAKE (non-existent) ID
        dangling_example = registry_repo.create_dataset_example(
            session,
            dataset_id=dataset.id,
            source_artifact_id="chk_DOES_NOT_EXIST_000000000000",
            example_index=0,
            payload={
                "question": "Does this artifact exist?",
                "answer": "No.",
                "_cache_key": "dangling_key",
            },
        )
        session.flush()
        session.commit()

        settings = _make_settings(engine)

        written_data: dict[str, bytes] = {}

        def mock_put_object(key, data, **kwargs):
            written_data[key] = data

        mock_storage = MagicMock()
        mock_storage.put_object.side_effect = mock_put_object
        mock_storage.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"

        import knowledge_lake.pipeline.export as export_module

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            result = export_module.export_finetune_dataset("ds_dangling", settings=settings)

        assert result["row_count"] == 0, f"Expected 0 surviving rows, got {result['row_count']}"
        assert result["skipped_dangling_lineage"] >= 1, (
            f"Expected ≥1 skipped_dangling_lineage, got {result['skipped_dangling_lineage']}"
        )


class TestRagCorpus:
    """EXPORT-01: RAG corpus → Parquet with column allow-list."""

    def _seed_chunk_with_internal_key(self, session, source):
        """Seed a chunk artifact whose metadata_ has a fake internal-only key."""
        from knowledge_lake.registry import repo as registry_repo

        raw = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="raw_rag_hash"
        )
        session.flush()
        parsed = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash="parsed_rag_hash",
        )
        session.flush()
        chunk = registry_repo.create_chunk_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed.id,
            content_hash="chunk_rag_hash",
            metadata={
                "text": "This is chunk text.",
                "section_path": "§1 Overview",
                "page": 1,
                "_internal_debug_note": "should NOT appear in export",  # T-05-08
            },
        )
        session.flush()
        session.commit()
        return chunk, parsed

    def test_rag_corpus_export_uses_allow_list_only(self, session, source, engine):
        """export_rag_corpus() only writes _RAG_CORPUS_FIELDS columns — never internal keys."""
        chunk, parsed = self._seed_chunk_with_internal_key(session, source)

        settings = _make_settings(engine)

        written_data: dict[str, bytes] = {}

        def mock_put_object(key, data, **kwargs):
            written_data[key] = data

        mock_storage = MagicMock()
        mock_storage.put_object.side_effect = mock_put_object
        mock_storage.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"

        import knowledge_lake.pipeline.export as export_module

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            result = export_module.export_rag_corpus(settings=settings)

        assert result["row_count"] >= 1

        # Read the written Parquet bytes with polars to inspect column names
        import polars as pl

        parquet_keys = [k for k in written_data if k.endswith(".parquet")]
        assert len(parquet_keys) == 1, f"Expected 1 Parquet file, got {parquet_keys}"

        buf = io.BytesIO(written_data[parquet_keys[0]])
        df = pl.read_parquet(buf)

        column_names = set(df.columns)
        assert "_internal_debug_note" not in column_names, (
            "Internal key '_internal_debug_note' leaked into Parquet export (T-05-08)"
        )

        # All columns must be from the allow-list
        from knowledge_lake.pipeline.export import _RAG_CORPUS_FIELDS

        for col in column_names:
            assert col in _RAG_CORPUS_FIELDS, (
                f"Unexpected column '{col}' in export — not in allow-list"
            )


class TestNoDiskWrites:
    """PROJECT.md 'no local filesystem as production store' guard."""

    def test_no_local_disk_writes(self):
        """export.py must not call open() in write mode or use pathlib write methods."""
        import ast
        import pathlib

        from knowledge_lake.pipeline import export as export_module

        export_src = pathlib.Path(export_module.__file__).read_text()
        tree = ast.parse(export_src)

        # Check no import of tempfile module
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    names = [node.module or ""]
                for name in names:
                    assert "tempfile" not in name, (
                        f"export.py imports tempfile — all writes must go through StorageBackend"
                    )

        # Check no write-mode open() calls
        import re
        write_open_calls = re.findall(r'\bopen\s*\([^)]*["\']w["\']', export_src)
        assert not write_open_calls, (
            f"Found write-mode open() calls in export.py: {write_open_calls}"
        )

        # No pathlib write_text/write_bytes calls (write_parquet/write_ndjson are polars methods, not pathlib)
        # We look for pathlib.Path patterns + write_ that aren't Polars DataFrame methods
        path_write = re.findall(r'Path\([^)]*\)\.\s*write_(?!parquet|ndjson)', export_src)
        assert not path_write, (
            f"Found pathlib write_ calls in export.py: {path_write}"
        )


# ── Task 4 tests: Train/eval contamination hard gate ─────────────────────────


class TestTrainEvalContamination:
    """05-AI-SPEC Section 6/7: train/eval contamination hard-block guardrail."""

    def _seed_eval_document(self, session, source, *, dedup_status="unique"):
        """Seed a cleaned_document + curated + chunk + QA dataset_example (eval set)."""
        from knowledge_lake.registry import repo as registry_repo

        raw = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash=f"raw_eval_{dedup_status}"
        )
        session.flush()
        parsed = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash=f"parsed_eval_{dedup_status}",
        )
        session.flush()
        cleaned = registry_repo.create_cleaned_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed.id,
            content_hash=f"cleaned_eval_{dedup_status}",
        )
        session.flush()
        curated = registry_repo.create_curated_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=cleaned.id,
            content_hash=f"curated_eval_{dedup_status}",
            metadata={"dedup_status": dedup_status},
            quality_score=0.8,
        )
        session.flush()
        chunk = registry_repo.create_chunk_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed.id,
            content_hash=f"chunk_eval_{dedup_status}",
            metadata={"text": "Eval chunk text."},
        )
        session.flush()

        # QA-shaped example = eval set indicator
        dataset = registry_repo.get_or_create_dataset(
            session, name="eval_ds", dataset_type="rag_eval"
        )
        session.flush()
        example = registry_repo.create_dataset_example(
            session,
            dataset_id=dataset.id,
            source_artifact_id=chunk.id,
            example_index=0,
            payload={"question": "Q?", "answer": "A.", "_cache_key": f"eval_{dedup_status}"},
        )
        session.flush()
        return cleaned, curated, chunk, dataset

    def _seed_pretrain_document(self, session, source, *, dedup_status="unique"):
        """Seed a cleaned_document + curated_document (pretrain candidate, quality=0.8)."""
        from knowledge_lake.registry import repo as registry_repo

        raw = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash=f"raw_pretrain_{dedup_status}"
        )
        session.flush()
        parsed = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash=f"parsed_pretrain_{dedup_status}",
        )
        session.flush()
        cleaned = registry_repo.create_cleaned_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed.id,
            content_hash=f"cleaned_pretrain_{dedup_status}",
            storage_uri="s3://bucket/silver/pretrain.md",
        )
        session.flush()
        curated = registry_repo.create_curated_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=cleaned.id,
            content_hash=f"curated_pretrain_{dedup_status}",
            metadata={"dedup_status": dedup_status},
            quality_score=0.8,  # above min_quality_score_for_pretrain=0.4
        )
        session.flush()
        return cleaned, curated

    def test_contamination_blocks_direct_overlap(self, session, source, engine):
        """Direct overlap: same cleaned_document is both eval source and pretrain candidate."""
        from knowledge_lake.registry import repo as registry_repo
        from knowledge_lake.config.settings import ExportSettings
        import knowledge_lake.pipeline.export as export_module

        # Seed a cleaned_document whose chunk is cited by an eval QA example
        # AND whose curated_document has quality_score >= 0.4 (pretrain candidate)
        raw = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="raw_overlap"
        )
        session.flush()
        parsed = registry_repo.create_parsed_artifact(
            session, source_id=source.id, parent_artifact_id=raw.id, content_hash="parsed_overlap"
        )
        session.flush()
        cleaned = registry_repo.create_cleaned_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed.id,
            content_hash="cleaned_overlap",
            storage_uri="s3://bucket/silver/overlap.md",
        )
        session.flush()
        curated = registry_repo.create_curated_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=cleaned.id,
            content_hash="curated_overlap",
            metadata={"dedup_status": "unique"},
            quality_score=0.8,  # pretrain candidate
        )
        session.flush()
        chunk = registry_repo.create_chunk_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed.id,
            content_hash="chunk_overlap",
            metadata={"text": "Overlap chunk text."},
        )
        session.flush()
        eval_ds = registry_repo.get_or_create_dataset(
            session, name="eval_ds_overlap", dataset_type="rag_eval"
        )
        session.flush()
        registry_repo.create_dataset_example(
            session,
            dataset_id=eval_ds.id,
            source_artifact_id=chunk.id,
            example_index=0,
            payload={"question": "Q?", "answer": "A.", "_cache_key": "overlap_key"},
        )
        session.flush()
        session.commit()

        settings = _make_settings(engine)

        result = export_module.check_train_eval_contamination(settings=settings)
        assert result["contaminated_count"] >= 1, (
            f"Expected ≥1 contaminated, got {result['contaminated_count']}"
        )
        assert cleaned.id in result["contaminated_artifact_ids"], (
            f"Expected {cleaned.id} in contaminated_artifact_ids"
        )

        # export_pretrain_corpus must raise TrainEvalContaminationError and NOT call put_object
        mock_storage = MagicMock()
        mock_storage.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            with pytest.raises(export_module.TrainEvalContaminationError):
                export_module.export_pretrain_corpus(settings=settings)

        assert mock_storage.put_object.call_count == 0, (
            "put_object was called despite contamination — hard gate failed"
        )

    def test_contamination_blocks_near_dup_overlap(self, session, source, engine):
        """Near-dup overlap: both eval-side and train-side have dedup_status='near_dup'."""
        from knowledge_lake.registry import repo as registry_repo
        import knowledge_lake.pipeline.export as export_module

        # Document A: contributes to eval set (chunk cited in QA example), dedup_status=near_dup
        raw_a = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="raw_neardup_a"
        )
        session.flush()
        parsed_a = registry_repo.create_parsed_artifact(
            session, source_id=source.id, parent_artifact_id=raw_a.id, content_hash="parsed_neardup_a"
        )
        session.flush()
        cleaned_a = registry_repo.create_cleaned_artifact(
            session, source_id=source.id, parent_artifact_id=parsed_a.id, content_hash="cleaned_neardup_a"
        )
        session.flush()
        curated_a = registry_repo.create_curated_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=cleaned_a.id,
            content_hash="curated_neardup_a",
            metadata={"dedup_status": "near_dup"},
            quality_score=0.2,  # below pretrain threshold — not a pretrain candidate
        )
        session.flush()
        chunk_a = registry_repo.create_chunk_artifact(
            session, source_id=source.id, parent_artifact_id=parsed_a.id, content_hash="chunk_neardup_a",
            metadata={"text": "Near dup eval chunk."}
        )
        session.flush()
        eval_ds = registry_repo.get_or_create_dataset(
            session, name="eval_neardup", dataset_type="rag_eval"
        )
        session.flush()
        registry_repo.create_dataset_example(
            session, dataset_id=eval_ds.id, source_artifact_id=chunk_a.id, example_index=0,
            payload={"question": "Q?", "answer": "A.", "_cache_key": "neardup_eval_key"}
        )
        session.flush()

        # Document B: instruction-tuning example (train set), dedup_status=near_dup
        raw_b = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="raw_neardup_b"
        )
        session.flush()
        parsed_b = registry_repo.create_parsed_artifact(
            session, source_id=source.id, parent_artifact_id=raw_b.id, content_hash="parsed_neardup_b"
        )
        session.flush()
        cleaned_b = registry_repo.create_cleaned_artifact(
            session, source_id=source.id, parent_artifact_id=parsed_b.id, content_hash="cleaned_neardup_b",
            storage_uri="s3://bucket/silver/neardup_b.md"
        )
        session.flush()
        curated_b = registry_repo.create_curated_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=cleaned_b.id,
            content_hash="curated_neardup_b",
            metadata={"dedup_status": "near_dup"},
            quality_score=0.8,  # above pretrain threshold
        )
        session.flush()
        session.commit()

        settings = _make_settings(engine)

        result = export_module.check_train_eval_contamination(settings=settings)
        assert result["contaminated_count"] > 0, (
            f"Expected >0 near-dup contamination, got {result['contaminated_count']}"
        )

        # export_finetune_dataset must also raise on any active (non-empty) dataset
        # Create a finetune dataset with one instruction-shaped example from enriched doc B
        with Session(engine) as s2:
            enriched_b = registry_repo.create_enriched_artifact(
                s2, source_id=source.id, parent_artifact_id=cleaned_b.id, content_hash="enriched_neardup_b"
            )
            s2.flush()
            ft_ds = registry_repo.get_or_create_dataset(
                s2, name="ft_neardup", dataset_type="instruction_tuning"
            )
            s2.flush()
            registry_repo.create_dataset_example(
                s2, dataset_id=ft_ds.id, source_artifact_id=enriched_b.id, example_index=0,
                payload={"instruction": "Inst", "input": "", "output": "Out", "_cache_key": "neardup_ft"}
            )
            s2.flush()
            s2.commit()

        mock_storage = MagicMock()
        mock_storage.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            with pytest.raises(export_module.TrainEvalContaminationError):
                export_module.export_finetune_dataset("ft_neardup", settings=settings)

    def test_contamination_allows_clean_export(self, session, source, engine):
        """Disjoint eval + pretrain → no contamination → export proceeds."""
        from knowledge_lake.registry import repo as registry_repo
        import knowledge_lake.pipeline.export as export_module

        # Eval document (unique, not in pretrain)
        raw_e = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="raw_clean_eval"
        )
        session.flush()
        parsed_e = registry_repo.create_parsed_artifact(
            session, source_id=source.id, parent_artifact_id=raw_e.id, content_hash="parsed_clean_eval"
        )
        session.flush()
        cleaned_e = registry_repo.create_cleaned_artifact(
            session, source_id=source.id, parent_artifact_id=parsed_e.id, content_hash="cleaned_clean_eval"
        )
        session.flush()
        curated_e = registry_repo.create_curated_artifact(
            session, source_id=source.id, parent_artifact_id=cleaned_e.id, content_hash="curated_clean_eval",
            metadata={"dedup_status": "unique"}, quality_score=0.1
        )
        session.flush()
        chunk_e = registry_repo.create_chunk_artifact(
            session, source_id=source.id, parent_artifact_id=parsed_e.id, content_hash="chunk_clean_eval",
            metadata={"text": "Eval only."}
        )
        session.flush()
        eval_ds = registry_repo.get_or_create_dataset(
            session, name="eval_clean", dataset_type="rag_eval"
        )
        session.flush()
        registry_repo.create_dataset_example(
            session, dataset_id=eval_ds.id, source_artifact_id=chunk_e.id, example_index=0,
            payload={"question": "Q?", "answer": "A.", "_cache_key": "clean_eval_key"}
        )
        session.flush()

        # Pretrain document (unique, not in eval)
        raw_p = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="raw_clean_pretrain"
        )
        session.flush()
        parsed_p = registry_repo.create_parsed_artifact(
            session, source_id=source.id, parent_artifact_id=raw_p.id, content_hash="parsed_clean_pretrain"
        )
        session.flush()
        cleaned_p = registry_repo.create_cleaned_artifact(
            session, source_id=source.id, parent_artifact_id=parsed_p.id, content_hash="cleaned_clean_pretrain",
            storage_uri="s3://bucket/silver/clean_pretrain.md"
        )
        session.flush()
        curated_p = registry_repo.create_curated_artifact(
            session, source_id=source.id, parent_artifact_id=cleaned_p.id, content_hash="curated_clean_pretrain",
            metadata={"dedup_status": "unique"}, quality_score=0.8
        )
        session.flush()
        session.commit()

        settings = _make_settings(engine)

        result = export_module.check_train_eval_contamination(settings=settings)
        assert result["contaminated_count"] == 0, (
            f"Expected 0 contamination in clean corpus, got {result['contaminated_count']}"
        )

        # Both exports should proceed and call put_object
        mock_storage = MagicMock()
        mock_storage.put_object.side_effect = lambda key, data, **kw: None
        mock_storage.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"
        mock_storage.get_object.return_value = b"Pretrain doc text."

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            pretrain_result = export_module.export_pretrain_corpus(settings=settings)

        assert mock_storage.put_object.call_count >= 1, "export_pretrain_corpus did not call put_object"

    def test_contamination_override_allowlist(self, session, source, engine):
        """contamination_override_artifact_ids excludes the overridden ID from contaminated set."""
        from knowledge_lake.registry import repo as registry_repo
        from knowledge_lake.config.settings import Settings, StorageSettings, ExportSettings
        import knowledge_lake.pipeline.export as export_module

        # Reproduce the direct-overlap seed from test_contamination_blocks_direct_overlap
        raw = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="raw_override"
        )
        session.flush()
        parsed = registry_repo.create_parsed_artifact(
            session, source_id=source.id, parent_artifact_id=raw.id, content_hash="parsed_override"
        )
        session.flush()
        cleaned = registry_repo.create_cleaned_artifact(
            session, source_id=source.id, parent_artifact_id=parsed.id,
            content_hash="cleaned_override", storage_uri="s3://bucket/silver/override.md"
        )
        session.flush()
        curated = registry_repo.create_curated_artifact(
            session, source_id=source.id, parent_artifact_id=cleaned.id,
            content_hash="curated_override", metadata={"dedup_status": "unique"}, quality_score=0.8
        )
        session.flush()
        chunk = registry_repo.create_chunk_artifact(
            session, source_id=source.id, parent_artifact_id=parsed.id, content_hash="chunk_override",
            metadata={"text": "Override chunk text."}
        )
        session.flush()
        eval_ds = registry_repo.get_or_create_dataset(
            session, name="eval_override", dataset_type="rag_eval"
        )
        session.flush()
        registry_repo.create_dataset_example(
            session, dataset_id=eval_ds.id, source_artifact_id=chunk.id, example_index=0,
            payload={"question": "Q?", "answer": "A.", "_cache_key": "override_key"}
        )
        session.flush()
        session.commit()

        # Settings with contamination_override_artifact_ids including cleaned.id
        export_s = ExportSettings(contamination_override_artifact_ids=[cleaned.id])
        settings = Settings(
            database_url=str(engine.url),
            storage=StorageSettings(
                endpoint_url="http://localhost:9000",
                bucket="test-bucket",
                access_key_id="test",
                secret_access_key="test",
            ),
            export=export_s,
            _env_file=None,  # type: ignore[call-arg]
        )

        result = export_module.check_train_eval_contamination(settings=settings)
        assert result["contaminated_count"] == 0, (
            f"Expected 0 after override, got {result['contaminated_count']}"
        )

        # export_pretrain_corpus should now succeed
        mock_storage = MagicMock()
        mock_storage.put_object.side_effect = lambda key, data, **kw: None
        mock_storage.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"
        mock_storage.get_object.return_value = b"Override doc text."

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            pretrain_result = export_module.export_pretrain_corpus(settings=settings)

        assert pretrain_result["row_count"] >= 1
        assert mock_storage.put_object.call_count >= 1


# ── Task 3: STORE-03 gold-zone domain-scoped key RED tests ────────────────────
#
# These four classes are Wave 0 xfail scaffolds. The domain kwarg does NOT yet
# exist on export_rag_corpus / export_pretrain_corpus / export_finetune_dataset
# (PATTERNS.md Pitfall 2). Passing domain= raises TypeError, which causes each
# test to xfail. Plan 09-06 adds the domain kwarg and makes these tests pass.


class TestGoldZoneDomainKey:
    """STORE-03: export_rag_corpus() must write to gold/{domain}/rag_corpus/ prefix."""

    def test_rag_corpus_key_contains_domain_segment(self, session, source, engine):
        """export_rag_corpus(domain="healthcare") must use gold/healthcare/rag_corpus/ key."""
        from knowledge_lake.registry import repo as registry_repo
        import knowledge_lake.pipeline.export as export_module

        # Seed a minimal chunk so export_rag_corpus has something to write
        raw = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="raw_gold_domain_key"
        )
        session.flush()
        parsed = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash="parsed_gold_domain_key",
        )
        session.flush()
        chunk = registry_repo.create_chunk_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed.id,
            content_hash="chunk_gold_domain_key",
            metadata={"text": "Gold zone domain test chunk."},
        )
        session.flush()
        session.commit()

        settings = _make_settings(engine)

        mock_storage = MagicMock()
        mock_storage.put_object.side_effect = lambda key, data, **kw: None
        mock_storage.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            # TypeError expected until Plan 09-06 adds domain kwarg
            export_module.export_rag_corpus(domain="healthcare", settings=settings)

        # After Plan 09-06: the put_object key must contain the domain segment
        call_args = mock_storage.put_object.call_args
        key_arg = call_args[0][0]
        assert "gold/healthcare/rag_corpus/" in key_arg, (
            f"Expected 'gold/healthcare/rag_corpus/' in key, got: {key_arg!r}"
        )


class TestGoldZoneUnclassified:
    """STORE-03: export_rag_corpus(domain=None) must write to gold/_unclassified/rag_corpus/."""

    def test_rag_corpus_none_domain_uses_unclassified(self, session, source, engine):
        """export_rag_corpus(domain=None) must use gold/_unclassified/rag_corpus/ key."""
        from knowledge_lake.registry import repo as registry_repo
        import knowledge_lake.pipeline.export as export_module

        # Seed a minimal chunk
        raw = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="raw_gold_unclassified"
        )
        session.flush()
        parsed = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash="parsed_gold_unclassified",
        )
        session.flush()
        chunk = registry_repo.create_chunk_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed.id,
            content_hash="chunk_gold_unclassified",
            metadata={"text": "Gold zone unclassified test chunk."},
        )
        session.flush()
        session.commit()

        settings = _make_settings(engine)

        mock_storage = MagicMock()
        mock_storage.put_object.side_effect = lambda key, data, **kw: None
        mock_storage.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            # TypeError expected until Plan 09-06 adds domain kwarg
            export_module.export_rag_corpus(domain=None, settings=settings)

        call_args = mock_storage.put_object.call_args
        key_arg = call_args[0][0]
        assert "gold/_unclassified/rag_corpus/" in key_arg, (
            f"Expected 'gold/_unclassified/rag_corpus/' in key, got: {key_arg!r}"
        )


class TestGoldZonePretrain:
    """STORE-03: export_pretrain_corpus() must write to gold/{domain}/pretrain/ prefix."""

    def test_pretrain_key_contains_domain_segment(self, session, source, engine):
        """export_pretrain_corpus(domain="healthcare") must use gold/healthcare/pretrain/ key."""
        from knowledge_lake.registry import repo as registry_repo
        import knowledge_lake.pipeline.export as export_module

        # Seed a minimal curated document above quality threshold
        raw = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="raw_pretrain_domain"
        )
        session.flush()
        parsed = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash="parsed_pretrain_domain",
        )
        session.flush()
        cleaned = registry_repo.create_cleaned_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed.id,
            content_hash="cleaned_pretrain_domain",
            storage_uri="s3://test-bucket/silver/pretrain_domain_doc.md",
        )
        session.flush()
        curated = registry_repo.create_curated_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=cleaned.id,
            content_hash="curated_pretrain_domain",
            metadata={"dedup_status": "unique"},
            quality_score=0.8,
        )
        session.flush()
        session.commit()

        settings = _make_settings(engine)

        mock_storage = MagicMock()
        mock_storage.put_object.side_effect = lambda key, data, **kw: None
        mock_storage.get_object.return_value = b"Pretrain domain test document text."
        mock_storage.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            # TypeError expected until Plan 09-06 adds domain kwarg
            export_module.export_pretrain_corpus(domain="healthcare", settings=settings)

        call_args = mock_storage.put_object.call_args
        key_arg = call_args[0][0]
        assert "gold/healthcare/pretrain/" in key_arg, (
            f"Expected 'gold/healthcare/pretrain/' in key, got: {key_arg!r}"
        )


class TestGoldZoneFinetune:
    """STORE-03: export_finetune_dataset() must write to gold/{domain}/finetune/ prefix."""

    def test_finetune_key_contains_domain_segment(self, session, source, engine):
        """export_finetune_dataset(dataset_id=..., domain="healthcare") must use gold/healthcare/finetune/ key."""
        from knowledge_lake.registry import repo as registry_repo
        import knowledge_lake.pipeline.export as export_module

        # Seed a minimal dataset with one QA example
        raw = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="raw_finetune_domain"
        )
        session.flush()
        parsed = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash="parsed_finetune_domain",
        )
        session.flush()
        chunk = registry_repo.create_chunk_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed.id,
            content_hash="chunk_finetune_domain",
            metadata={"text": "Finetune domain test chunk."},
        )
        session.flush()
        dataset = registry_repo.get_or_create_dataset(
            session, name="finetune_domain_test_ds", dataset_type="instruction_tuning"
        )
        session.flush()
        registry_repo.create_dataset_example(
            session,
            dataset_id=dataset.id,
            source_artifact_id=chunk.id,
            example_index=0,
            payload={
                "question": "What is domain segmentation?",
                "answer": "It routes objects to domain-scoped S3 keys.",
                "_cache_key": "finetune_domain_key",
            },
        )
        session.flush()
        session.commit()

        settings = _make_settings(engine)

        mock_storage = MagicMock()
        mock_storage.put_object.side_effect = lambda key, data, **kw: None
        mock_storage.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            # TypeError expected until Plan 09-06 adds domain kwarg
            export_module.export_finetune_dataset(
                "finetune_domain_test_ds", domain="healthcare", settings=settings
            )

        call_args = mock_storage.put_object.call_args
        key_arg = call_args[0][0]
        assert "gold/healthcare/finetune/" in key_arg, (
            f"Expected 'gold/healthcare/finetune/' in key, got: {key_arg!r}"
        )
