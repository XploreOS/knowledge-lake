"""Tests for pipeline/curate.py — DataTrove-style quality filtering, corpus-wide
MinHash dedup, and composite quality scoring (CURATE-01, CURATE-02, CURATE-03).

Uses an in-memory-SQLite-backed session (mirrors tests/unit/test_enrich.py's
engine/session/seeded/fake_storage fixture pattern) with
knowledge_lake.registry.db.get_engine monkeypatched so curate_document()'s own
get_session() calls resolve against the same in-memory database.
StorageBackend is patched at the pipeline.curate module level so no real S3
client is constructed.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.pipeline.curate as curate_module
import knowledge_lake.registry.db as registry_db
from knowledge_lake.config.settings import Settings

# Texts A and B are near-identical (same content, one has a trailing word).
# When measured with 5-word shingles and num_perm=128, the shared shingle count
# is high enough that with threshold=0.5 they are detected as near-dups.
# Text C is completely unrelated.
_HIPAA_SENTENCE = "The HIPAA Security Rule requires administrative safeguards to protect electronic health information."
CLEANED_TEXT_A = (_HIPAA_SENTENCE + " ") * 15
CLEANED_TEXT_B = (_HIPAA_SENTENCE + " ") * 15 + "Additional minor note here."
CLEANED_TEXT_C = "Totally unrelated quantum physics mathematics algorithms advanced research. " * 15


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    """In-memory SQLite engine, shared connection via StaticPool so multiple
    Session() instances all see the same database."""
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
    """Route registry.db.get_session() at curate_document() call sites to the
    in-memory test engine."""
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)


@pytest.fixture()
def session(engine):
    with Session(engine) as sess:
        yield sess


@pytest.fixture()
def seeded(session):
    """Seed a Source -> raw -> parsed -> cleaned_document artifact chain."""
    from knowledge_lake.registry import repo as registry_repo

    source = registry_repo.create_source(session, name="Test Source", source_type="web")
    raw = registry_repo.create_raw_artifact(
        session,
        source_id=source.id,
        content_hash="raw_h",
        storage_uri="s3://b/raw/raw_h.pdf",
    )
    parsed = registry_repo.create_parsed_artifact(
        session,
        source_id=source.id,
        parent_artifact_id=raw.id,
        content_hash="parsed_h",
        storage_uri="s3://b/silver/parsed_h.md",
        metadata={"quality_score": 0.7, "parser_used": "docling", "title": "HIPAA Overview"},
    )
    cleaned = registry_repo.create_cleaned_artifact(
        session,
        source_id=source.id,
        parent_artifact_id=parsed.id,
        content_hash="cleaned_h",
        storage_uri="s3://b/silver/cleaned_h.md",
    )
    session.commit()
    return {
        "source_id": source.id,
        "cleaned_artifact_id": cleaned.id,
        "parsed_artifact_id": parsed.id,
    }


@pytest.fixture()
def fake_storage(monkeypatch):
    """Patch StorageBackend inside pipeline.curate to return canned bytes."""
    fake = MagicMock()
    fake.get_object.return_value = CLEANED_TEXT_A.encode("utf-8")
    monkeypatch.setattr(curate_module, "StorageBackend", lambda *_a, **_k: fake)
    return fake


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


# ── Helper: fake filter double ────────────────────────────────────────────────


def _FakeFilter(name: str, passes: bool, reason: str | None = None):
    """Factory returning a filter double whose type(f).__name__ == name.

    Creates a unique subclass per call so that different _FakeFilter instances
    have distinct type(f).__name__ values — a shared class attribute would be
    overwritten by the last created instance.
    """
    _passes = passes
    _reason = reason

    def _filter_method(self, doc):  # noqa: A003
        if _reason:
            return (_passes, _reason)
        return _passes

    # Create a fresh class with the given name — type(instance).__name__ returns name
    fake_cls = type(name, (), {"filter": _filter_method})
    return fake_cls()


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_filter_results_records_all_heuristics(
    engine, seeded, fake_storage, test_settings, monkeypatch
) -> None:
    """All configured filters' pass/fail must be recorded, not just the first failure.

    CURATE-01: metadata_["filter_results"] must have one entry per configured filter
    even when the first filter fails.
    """
    # Create 3 fake filters: first fails, next two pass
    filters = [
        _FakeFilter("FilterAlpha", False, "too short"),
        _FakeFilter("FilterBeta", True),
        _FakeFilter("FilterGamma", True),
    ]
    monkeypatch.setattr(curate_module, "_build_filters", lambda s: filters)

    result = curate_module.curate_document(
        seeded["cleaned_artifact_id"],
        seeded["source_id"],
        settings=test_settings,
    )

    assert result["status"] == "curated"
    artifact_id = result["artifact_id"]

    with Session(engine) as check_session:
        from knowledge_lake.registry import repo as registry_repo

        artifact = registry_repo.get_artifact(check_session, artifact_id)
        assert artifact is not None
        fr = artifact.metadata_["filter_results"]
        # All 3 filters must be represented — not just the first failing one
        assert len(fr) == 3, f"Expected 3 filter results, got {len(fr)}: {fr}"
        assert "FilterAlpha" in fr
        assert "FilterBeta" in fr
        assert "FilterGamma" in fr
        assert fr["FilterAlpha"]["passed"] is False
        assert fr["FilterBeta"]["passed"] is True
        assert fr["FilterGamma"]["passed"] is True


def test_curate_is_idempotent_cache_hit(
    engine, seeded, fake_storage, test_settings, monkeypatch
) -> None:
    """Calling curate_document() twice for the same cleaned artifact + unchanged
    filter_config_version returns status='cached' on the second call without
    creating a second artifact (mirrors test_enrich_cache_hit_is_noop).
    CURATE-01 idempotency.
    """
    filters = [_FakeFilter("FilterAlpha", True)]
    monkeypatch.setattr(curate_module, "_build_filters", lambda s: filters)

    first = curate_module.curate_document(
        seeded["cleaned_artifact_id"],
        seeded["source_id"],
        settings=test_settings,
    )
    second = curate_module.curate_document(
        seeded["cleaned_artifact_id"],
        seeded["source_id"],
        settings=test_settings,
    )

    assert first["status"] == "curated"
    assert second["status"] == "cached"
    assert second["cached"] is True
    assert second["artifact_id"] == first["artifact_id"]

    # Only one artifact should exist in the registry
    with Session(engine) as check_session:
        from sqlalchemy import select
        from knowledge_lake.registry.models import Artifact

        rows = list(
            check_session.execute(
                select(Artifact).where(Artifact.artifact_type == "curated_document")
            ).scalars()
        )
        assert len(rows) == 1, f"Expected 1 curated artifact, got {len(rows)}"


def test_batch_dedup_single_pass(engine, seeded, fake_storage, test_settings, monkeypatch) -> None:
    """batch_dedup_corpus() builds exactly ONE MinHashLSH index over the whole corpus
    and correctly flags near-duplicates.

    CURATE-02: the two near-identical texts (A and B) must be flagged 'near_dup';
    the distinct text (C) must be flagged 'unique'.
    """
    from knowledge_lake.registry import repo as registry_repo

    # Seed 3 cleaned_document artifacts (A is already in seeded fixture)
    with Session(engine) as seed_session:
        source_id = seeded["source_id"]
        parsed_a = registry_repo.get_artifact(seed_session, seeded["parsed_artifact_id"])

        # Parsed B — reuse same parent raw for simplicity
        raw_b = registry_repo.create_raw_artifact(
            seed_session, source_id=source_id, content_hash="raw_b"
        )
        parsed_b = registry_repo.create_parsed_artifact(
            seed_session,
            source_id=source_id,
            parent_artifact_id=raw_b.id,
            content_hash="parsed_b",
            metadata={"quality_score": 0.7},
        )
        cleaned_b = registry_repo.create_cleaned_artifact(
            seed_session,
            source_id=source_id,
            parent_artifact_id=parsed_b.id,
            content_hash="cleaned_b",
            storage_uri="s3://b/silver/cleaned_b.md",
        )
        # Parsed C
        raw_c = registry_repo.create_raw_artifact(
            seed_session, source_id=source_id, content_hash="raw_c"
        )
        parsed_c = registry_repo.create_parsed_artifact(
            seed_session,
            source_id=source_id,
            parent_artifact_id=raw_c.id,
            content_hash="parsed_c",
            metadata={"quality_score": 0.7},
        )
        cleaned_c = registry_repo.create_cleaned_artifact(
            seed_session,
            source_id=source_id,
            parent_artifact_id=parsed_c.id,
            content_hash="cleaned_c",
            storage_uri="s3://b/silver/cleaned_c.md",
        )
        seed_session.commit()
        cleaned_a_id = seeded["cleaned_artifact_id"]
        cleaned_b_id = cleaned_b.id
        cleaned_c_id = cleaned_c.id

    # Stub storage to return the right text per key (uri_to_key strips the bucket prefix:
    # "s3://b/silver/cleaned_h.md" -> "silver/cleaned_h.md")
    storage_texts = {
        "silver/cleaned_h.md": CLEANED_TEXT_A,
        "silver/cleaned_b.md": CLEANED_TEXT_B,
        "silver/cleaned_c.md": CLEANED_TEXT_C,
    }

    def _get_object(key):
        for stored_key, text in storage_texts.items():
            if key == stored_key or key.endswith(stored_key):
                return text.encode("utf-8")
        return CLEANED_TEXT_A.encode("utf-8")

    fake_storage.get_object.side_effect = _get_object

    # First, create curated_document children for all three so batch_dedup_corpus
    # can update their dedup_status
    filters = [_FakeFilter("FilterAlpha", True)]
    monkeypatch.setattr(curate_module, "_build_filters", lambda s: filters)

    # Override get_object for curate_document calls too (use key-based storage_texts)
    key_to_text = {
        "silver/cleaned_h.md": CLEANED_TEXT_A,
        "silver/cleaned_b.md": CLEANED_TEXT_B,
        "silver/cleaned_c.md": CLEANED_TEXT_C,
    }
    for cleaned_id, key in [
        (cleaned_a_id, "silver/cleaned_h.md"),
        (cleaned_b_id, "silver/cleaned_b.md"),
        (cleaned_c_id, "silver/cleaned_c.md"),
    ]:
        fake_storage.get_object.return_value = key_to_text[key].encode("utf-8")
        curate_module.curate_document(cleaned_id, source_id, settings=test_settings)

    # Restore side_effect for batch_dedup_corpus
    fake_storage.get_object.side_effect = _get_object
    fake_storage.get_object.return_value = None  # ensure side_effect is used

    # Use a lower minhash_threshold so the near-identical texts are detected as near_dup
    # (the two texts share ~74% Jaccard similarity, which is above 0.5 but below 0.8)
    from knowledge_lake.config.settings import CleanSettings

    dedup_settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        clean=CleanSettings(minhash_threshold=0.5, minhash_num_perm=128, minhash_shingle_size=5),
    )

    # Count MinHashLSH constructor calls to verify single-pass
    import datasketch as _datasketch

    lsh_call_count = {"n": 0}
    original_lsh_cls = _datasketch.MinHashLSH

    class _CountingLSH(original_lsh_cls):
        def __init__(self, *a, **kw):
            lsh_call_count["n"] += 1
            super().__init__(*a, **kw)

    monkeypatch.setattr(_datasketch, "MinHashLSH", _CountingLSH)
    monkeypatch.setattr(curate_module, "MinHashLSH", _CountingLSH)

    summary = curate_module.batch_dedup_corpus(settings=dedup_settings)

    assert lsh_call_count["n"] == 1, (
        f"Expected exactly 1 MinHashLSH construction (single-pass), got {lsh_call_count['n']}"
    )
    assert summary["total"] == 3
    assert summary["near_dup"] + summary["unique"] == 3

    # Verify dedup_status on the curated_document children
    with Session(engine) as check_session:
        from knowledge_lake.registry import repo as registry_repo

        curated_a = registry_repo.get_child_artifact_by_type(
            check_session, cleaned_a_id, "curated_document"
        )
        curated_b = registry_repo.get_child_artifact_by_type(
            check_session, cleaned_b_id, "curated_document"
        )
        curated_c = registry_repo.get_child_artifact_by_type(
            check_session, cleaned_c_id, "curated_document"
        )
        # C must always be unique
        assert curated_c is not None
        assert curated_c.metadata_["dedup_status"] == "unique"
        # A and B are near-dups of each other — at least one of them must be near_dup
        statuses = set()
        if curated_a:
            statuses.add(curated_a.metadata_["dedup_status"])
        if curated_b:
            statuses.add(curated_b.metadata_["dedup_status"])
        assert "near_dup" in statuses, (
            f"Expected at least one near_dup among A and B; got statuses={statuses}"
        )


def test_never_adopts_datatrove_file_io_scaffolding() -> None:
    """pipeline/curate.py must never reference DataTrove's disk-based executor/
    reader/writer scaffolding (RESEARCH.md Anti-Patterns, FOUND-03 one-client invariant).
    """
    source = inspect.getsource(curate_module)
    forbidden = [
        "LocalPipelineExecutor",
        "datatrove.io",
        "BaseDiskReader",
        "DiskWriter",
        "DataFolder",
    ]
    for fragment in forbidden:
        assert fragment not in source, (
            f"Found forbidden DataTrove file-I/O reference {fragment!r} in pipeline/curate.py"
        )
