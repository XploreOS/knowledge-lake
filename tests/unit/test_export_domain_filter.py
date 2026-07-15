"""Regression tests for KL-01 — domain= must FILTER export rows, not just label them.

.planning/E2E-GAP-ANALYSIS.md KL-01: export_rag_corpus(), export_pretrain_corpus(),
and export_finetune_dataset() all accepted a `domain` kwarg but used it only to
build the S3 path segment / tag — the row query ignored it entirely. A
domain-scoped export measured 62% foreign rows.

Each of the three export functions is exercised with three sources — one
classified "aviation", one classified "functional-medicine", and one left
unclassified (domain=None in Source.config) — mirroring the real registry
state described in the quick-task environment. domain="aviation" must return
ONLY the aviation row; domain=None must return everything (regression guard
on the preserved, byte-for-byte-unchanged default — this is the current
CLI/API behavior and must not change, per the locked plan decision).

Fixture/mocking pattern mirrors tests/unit/test_export.py: in-memory SQLite
session via StaticPool, StorageBackend mocked at the pipeline.export module
level so no real S3 client is constructed.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

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


def _make_settings(engine):
    from knowledge_lake.config.settings import Settings, StorageSettings

    ss = StorageSettings(
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


def _mock_storage(get_object_bytes: bytes = b"placeholder text"):
    """MagicMock StorageBackend recording every put_object() call's payload."""
    written: dict[str, bytes] = {}

    def _put(key, data, **kw):
        written[key] = data

    m = MagicMock()
    m.put_object.side_effect = _put
    m.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"
    m.get_object.return_value = get_object_bytes
    return m, written


def _make_source(session, name: str, domain: str | None):
    """Seed a Source with (or without) a domain classification in config."""
    from knowledge_lake.registry import repo as registry_repo

    config = {"domain": domain} if domain is not None else {}
    src = registry_repo.create_source(session, name=name, source_type="upload", config=config)
    session.flush()
    return src


def _seed_chunk(session, source, *, suffix: str, text: str):
    """Seed a raw -> parsed -> chunk artifact tree under `source`."""
    from knowledge_lake.registry import repo as registry_repo

    raw = registry_repo.create_raw_artifact(session, source_id=source.id, content_hash=f"raw_{suffix}")
    session.flush()
    parsed = registry_repo.create_parsed_artifact(
        session, source_id=source.id, parent_artifact_id=raw.id, content_hash=f"parsed_{suffix}"
    )
    session.flush()
    chunk = registry_repo.create_chunk_artifact(
        session,
        source_id=source.id,
        parent_artifact_id=parsed.id,
        content_hash=f"chunk_{suffix}",
        metadata={"text": text},
    )
    session.flush()
    return chunk, parsed, raw


def _seed_curated(session, source, *, suffix: str, quality_score: float = 0.8):
    """Seed a raw -> parsed -> cleaned -> curated_document tree under `source`."""
    from knowledge_lake.registry import repo as registry_repo

    raw = registry_repo.create_raw_artifact(session, source_id=source.id, content_hash=f"raw_{suffix}")
    session.flush()
    parsed = registry_repo.create_parsed_artifact(
        session, source_id=source.id, parent_artifact_id=raw.id, content_hash=f"parsed_{suffix}"
    )
    session.flush()
    cleaned = registry_repo.create_cleaned_artifact(
        session,
        source_id=source.id,
        parent_artifact_id=parsed.id,
        content_hash=f"cleaned_{suffix}",
        storage_uri=f"s3://test-bucket/silver/{suffix}.md",
    )
    session.flush()
    curated = registry_repo.create_curated_artifact(
        session,
        source_id=source.id,
        parent_artifact_id=cleaned.id,
        content_hash=f"curated_{suffix}",
        metadata={"dedup_status": "unique"},
        quality_score=quality_score,
    )
    session.flush()
    return curated


# ── Task 1 tests: export_rag_corpus ─────────────────────────────────────────────


class TestRagCorpusDomainFilter:
    """KL-01: export_rag_corpus(domain=X) must return ONLY domain X's rows."""

    def test_domain_filters_to_only_that_domain(self, session, engine):
        aviation_src = _make_source(session, "aviation-src", "aviation")
        med_src = _make_source(session, "med-src", "functional-medicine")
        null_src = _make_source(session, "null-src", None)

        _seed_chunk(session, aviation_src, suffix="rag_av1", text="Aviation chunk")
        _seed_chunk(session, med_src, suffix="rag_med1", text="Medicine chunk")
        _seed_chunk(session, null_src, suffix="rag_null1", text="Unclassified chunk")
        session.commit()

        settings = _make_settings(engine)
        mock_storage, written = _mock_storage()

        import knowledge_lake.pipeline.export as export_module

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            result = export_module.export_rag_corpus(domain="aviation", settings=settings)

        assert result["row_count"] == 1, f"Expected 1 aviation row, got {result['row_count']}"

        import polars as pl

        parquet_bytes = next(v for k, v in written.items() if k.endswith(".parquet"))
        df = pl.read_parquet(io.BytesIO(parquet_bytes))
        assert df["domain"].to_list() == ["aviation"], (
            f"Expected only aviation rows in the export, got {df['domain'].to_list()}"
        )

    def test_domain_none_includes_everything(self, session, engine):
        """Regression guard: domain=None must preserve the unfiltered default."""
        aviation_src = _make_source(session, "aviation-src2", "aviation")
        med_src = _make_source(session, "med-src2", "functional-medicine")
        null_src = _make_source(session, "null-src2", None)

        _seed_chunk(session, aviation_src, suffix="rag_av2", text="Aviation chunk 2")
        _seed_chunk(session, med_src, suffix="rag_med2", text="Medicine chunk 2")
        _seed_chunk(session, null_src, suffix="rag_null2", text="Unclassified chunk 2")
        session.commit()

        settings = _make_settings(engine)
        mock_storage, written = _mock_storage()

        import knowledge_lake.pipeline.export as export_module

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            result = export_module.export_rag_corpus(domain=None, settings=settings)

        assert result["row_count"] == 3, f"Expected all 3 rows with domain=None, got {result['row_count']}"

        key_arg = mock_storage.put_object.call_args[0][0]
        assert "gold/_unclassified/rag_corpus/" in key_arg


# ── Task 2 tests: export_pretrain_corpus ────────────────────────────────────────


class TestPretrainDomainFilter:
    """KL-01: export_pretrain_corpus(domain=X) must return ONLY domain X's rows."""

    def test_domain_filters_to_only_that_domain(self, session, engine):
        aviation_src = _make_source(session, "aviation-src3", "aviation")
        med_src = _make_source(session, "med-src3", "functional-medicine")
        null_src = _make_source(session, "null-src3", None)

        _seed_curated(session, aviation_src, suffix="pre_av1")
        _seed_curated(session, med_src, suffix="pre_med1")
        _seed_curated(session, null_src, suffix="pre_null1")
        session.commit()

        settings = _make_settings(engine)
        mock_storage, written = _mock_storage()

        import knowledge_lake.pipeline.export as export_module

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            result = export_module.export_pretrain_corpus(domain="aviation", settings=settings)

        assert result["row_count"] == 1, f"Expected 1 aviation row, got {result['row_count']}"

    def test_domain_none_includes_everything(self, session, engine):
        """Regression guard: domain=None must preserve the unfiltered default."""
        aviation_src = _make_source(session, "aviation-src4", "aviation")
        med_src = _make_source(session, "med-src4", "functional-medicine")
        null_src = _make_source(session, "null-src4", None)

        _seed_curated(session, aviation_src, suffix="pre_av2")
        _seed_curated(session, med_src, suffix="pre_med2")
        _seed_curated(session, null_src, suffix="pre_null2")
        session.commit()

        settings = _make_settings(engine)
        mock_storage, written = _mock_storage()

        import knowledge_lake.pipeline.export as export_module

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            result = export_module.export_pretrain_corpus(domain=None, settings=settings)

        assert result["row_count"] == 3, f"Expected all 3 rows with domain=None, got {result['row_count']}"


# ── Task 3 tests: export_finetune_dataset ───────────────────────────────────────


class TestFinetuneDomainFilter:
    """KL-01: export_finetune_dataset(domain=X) must return ONLY domain X's rows."""

    def _seed_qa_example(self, session, dataset, source, *, suffix: str, index: int):
        """Seed one QA-shaped DatasetExample citing a chunk under `source`.

        Each example gets its own document tree (own content_hash suffix) so
        the train/eval contamination gate (checked FIRST by every export
        function) never sees a same-cleaned-document overlap between
        examples — mirrors tests/unit/test_export.py's TestFinetune pattern.
        """
        from knowledge_lake.registry import repo as registry_repo

        chunk, _parsed, _raw = _seed_chunk(session, source, suffix=suffix, text=f"Chunk text {suffix}")
        example = registry_repo.create_dataset_example(
            session,
            dataset_id=dataset.id,
            source_artifact_id=chunk.id,
            example_index=index,
            payload={
                "question": f"Question {suffix}?",
                "answer": f"Answer {suffix}.",
                "_cache_key": f"cache_{suffix}",
            },
        )
        session.flush()
        return example

    def test_domain_filters_to_only_that_domain(self, session, engine):
        from knowledge_lake.registry import repo as registry_repo

        aviation_src = _make_source(session, "aviation-src5", "aviation")
        med_src = _make_source(session, "med-src5", "functional-medicine")
        null_src = _make_source(session, "null-src5", None)

        dataset = registry_repo.get_or_create_dataset(
            session, name="ft_domain_filter_ds", dataset_type="rag_eval"
        )
        session.flush()

        self._seed_qa_example(session, dataset, aviation_src, suffix="ft_av1", index=0)
        self._seed_qa_example(session, dataset, med_src, suffix="ft_med1", index=1)
        self._seed_qa_example(session, dataset, null_src, suffix="ft_null1", index=2)
        session.commit()

        settings = _make_settings(engine)
        mock_storage, written = _mock_storage()

        import knowledge_lake.pipeline.export as export_module

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            result = export_module.export_finetune_dataset(
                "ft_domain_filter_ds", domain="aviation", settings=settings
            )

        assert result["row_count"] == 1, f"Expected 1 aviation row, got {result['row_count']}"
        assert result["skipped_dangling_lineage"] == 0

        jsonl_bytes = next(v for k, v in written.items() if k.endswith(".jsonl"))
        lines = [line for line in jsonl_bytes.decode().splitlines() if line.strip()]
        assert len(lines) == 1
        assert "ft_av1" in lines[0]

    def test_domain_none_includes_everything(self, session, engine):
        """Regression guard: domain=None must preserve the unfiltered default."""
        from knowledge_lake.registry import repo as registry_repo

        aviation_src = _make_source(session, "aviation-src6", "aviation")
        med_src = _make_source(session, "med-src6", "functional-medicine")
        null_src = _make_source(session, "null-src6", None)

        dataset = registry_repo.get_or_create_dataset(
            session, name="ft_domain_none_ds", dataset_type="rag_eval"
        )
        session.flush()

        self._seed_qa_example(session, dataset, aviation_src, suffix="ft_av2", index=0)
        self._seed_qa_example(session, dataset, med_src, suffix="ft_med2", index=1)
        self._seed_qa_example(session, dataset, null_src, suffix="ft_null2", index=2)
        session.commit()

        settings = _make_settings(engine)
        mock_storage, written = _mock_storage()

        import knowledge_lake.pipeline.export as export_module

        with patch.object(export_module, "_make_storage", return_value=mock_storage):
            result = export_module.export_finetune_dataset(
                "ft_domain_none_ds", domain=None, settings=settings
            )

        assert result["row_count"] == 3, f"Expected all 3 rows with domain=None, got {result['row_count']}"
