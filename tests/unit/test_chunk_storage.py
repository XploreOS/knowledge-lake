"""Tests for chunk-text persistence to object storage (Finding 1).

chunk() must write each NEWLY created chunk's text to the chunks storage zone
under {domain}/{source_id}/{content_hash}.txt and set the chunk artifact's
storage_uri to that object — so QA generation can read a grounded excerpt back
instead of the previously-empty metadata text.

Mirrors tests/unit/test_datasets.py's in-memory-SQLite engine + _patch_engine
fixture style; StorageBackend is patched inside knowledge_lake.pipeline.chunk to
capture put_object(key, data) calls without touching a real S3 endpoint.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.registry.db as registry_db
from knowledge_lake.config.settings import Settings
from knowledge_lake.plugins.protocols import ParsedDoc


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    """In-memory SQLite engine shared across sessions via StaticPool."""
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
    """Route chunk()'s internal get_session() to the in-memory test engine."""
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)


@pytest.fixture()
def fake_storage(monkeypatch):
    """Patch StorageBackend inside pipeline.chunk to capture put_object calls.

    object_uri returns a deterministic s3:// URI so the test can assert the
    created chunk artifact's storage_uri matches the key that was written.
    """
    from knowledge_lake.pipeline.chunk import StorageBackend

    fake = MagicMock()
    fake.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"
    monkeypatch.setattr("knowledge_lake.pipeline.chunk.StorageBackend", lambda *_a, **_k: fake)
    return fake


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _seed_source_and_parsed(engine, *, domain: str | None):
    """Seed a Source (optionally with a config domain) + a parsed_document parent."""
    from knowledge_lake.registry import repo as registry_repo

    with Session(engine) as session:
        config = {"domain": domain} if domain else None
        source = registry_repo.create_source(
            session, name="Test Source", source_type="web", config=config
        )
        session.flush()
        raw = registry_repo.create_raw_artifact(
            session,
            source_id=source.id,
            content_hash="raw_h",
            storage_uri="s3://b/raw/raw_h.pdf",
        )
        session.flush()
        parsed = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash="parsed_h",
            storage_uri="s3://b/silver/parsed_h.md",
        )
        session.commit()
        return source.id, parsed.id


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_chunk_persists_text_to_domain_scoped_key(engine, fake_storage, test_settings):
    """A domain'd source writes chunk text under chunks/{domain}/{source_id}/{hash}.txt
    and the created chunk artifact's storage_uri matches that object (Finding 1)."""
    from knowledge_lake.pipeline.chunk import chunk

    source_id, parsed_id = _seed_source_and_parsed(engine, domain="healthcare")
    parsed_doc = ParsedDoc(
        text="The HIPAA Security Rule requires administrative safeguards for ePHI.",
        sections=[],
        metadata={},
    )

    results = chunk(parsed_id, source_id, parsed_doc, settings=test_settings)

    assert len(results) == 1
    content_hash = results[0]["content_hash"]

    # put_object was called with a chunks-zone key containing domain, source_id, hash
    assert fake_storage.put_object.call_count == 1
    call = fake_storage.put_object.call_args
    key = call.args[0]
    data = call.args[1]
    assert key == f"chunks/healthcare/{source_id}/{content_hash}.txt"
    assert data == parsed_doc.text.encode("utf-8")
    assert call.kwargs["tags"]["domain"] == "healthcare"
    assert call.kwargs["tags"]["artifact_type"] == "chunk"

    # The created chunk artifact carries a non-null storage_uri == object_uri(key)
    from knowledge_lake.registry import repo as registry_repo

    with Session(engine) as check:
        artifact = registry_repo.get_artifact(check, results[0]["artifact_id"])
        assert artifact is not None
        assert artifact.storage_uri == f"s3://test-bucket/{key}"


def test_chunk_without_domain_routes_under_unclassified(engine, fake_storage, test_settings):
    """A source with no domain routes chunk text under the _unclassified segment."""
    from knowledge_lake.pipeline.chunk import chunk
    from knowledge_lake.storage.s3 import _UNCLASSIFIED_DOMAIN

    source_id, parsed_id = _seed_source_and_parsed(engine, domain=None)
    parsed_doc = ParsedDoc(
        text="A generic paragraph with no domain classification whatsoever.",
        sections=[],
        metadata={},
    )

    results = chunk(parsed_id, source_id, parsed_doc, settings=test_settings)

    assert len(results) == 1
    key = fake_storage.put_object.call_args.args[0]
    assert key.startswith(f"chunks/{_UNCLASSIFIED_DOMAIN}/{source_id}/")


# ── PIPE-01: filter_config_version cache versioning ──────────────────────────


def test_chunk_different_filter_config_version_produces_different_content_hash(
    engine, fake_storage, test_settings
):
    """Two chunk() calls on the identical ParsedDoc, one with
    filter_config_version="1.0" and one with "2.0", produce DIFFERENT
    content_hash values for the same chunk text (PIPE-01)."""
    from knowledge_lake.config.settings import ChunkQualitySettings
    from knowledge_lake.pipeline.chunk import chunk

    source_id, parsed_id = _seed_source_and_parsed(engine, domain=None)
    parsed_doc = ParsedDoc(
        text="A generic paragraph with no domain classification whatsoever.",
        sections=[],
        metadata={},
    )

    v1_settings = test_settings.model_copy(
        update={"chunk_quality": ChunkQualitySettings(filter_config_version="1.0")}
    )
    v2_settings = test_settings.model_copy(
        update={"chunk_quality": ChunkQualitySettings(filter_config_version="2.0")}
    )

    results_v1 = chunk(parsed_id, source_id, parsed_doc, settings=v1_settings)
    results_v2 = chunk(parsed_id, source_id, parsed_doc, settings=v2_settings)

    assert results_v1[0]["content_hash"] != results_v2[0]["content_hash"]
    assert results_v1[0]["artifact_id"] != results_v2[0]["artifact_id"]
    # Different content_hash -> both are genuinely new writes, not a cache hit.
    assert fake_storage.put_object.call_count == 2


def test_chunk_same_filter_config_version_hits_existing_cache(engine, fake_storage, test_settings):
    """Two chunk() calls with the SAME filter_config_version on the same input
    still hit the pre-existing get_artifact_by_hash() cache (no duplicate S3
    write, no duplicate artifact) — the PIPE-01 fix is additive to the hash
    formula, not a new cache layer."""
    from knowledge_lake.pipeline.chunk import chunk

    source_id, parsed_id = _seed_source_and_parsed(engine, domain=None)
    parsed_doc = ParsedDoc(
        text="A generic paragraph with no domain classification whatsoever.",
        sections=[],
        metadata={},
    )

    results_1 = chunk(parsed_id, source_id, parsed_doc, settings=test_settings)
    results_2 = chunk(parsed_id, source_id, parsed_doc, settings=test_settings)

    assert results_1[0]["content_hash"] == results_2[0]["content_hash"]
    assert results_1[0]["artifact_id"] == results_2[0]["artifact_id"]
    assert fake_storage.put_object.call_count == 1


def test_chunk_existing_hit_branch_carries_substance_gate_keys(engine, fake_storage, test_settings):
    """Both the existing-hit branch and the new-artifact branch carry
    substance_passed/rejection_reason keys sourced from the gate computation
    (Task 2), not stale persisted metadata — the gate always recomputes fresh."""
    from knowledge_lake.pipeline.chunk import chunk

    source_id, parsed_id = _seed_source_and_parsed(engine, domain=None)
    parsed_doc = ParsedDoc(
        text="A generic paragraph with no domain classification whatsoever.",
        sections=[],
        metadata={},
    )

    results_new = chunk(parsed_id, source_id, parsed_doc, settings=test_settings)
    assert results_new[0]["substance_passed"] is True
    assert results_new[0]["rejection_reason"] is None

    results_hit = chunk(parsed_id, source_id, parsed_doc, settings=test_settings)
    assert results_hit[0]["substance_passed"] is True
    assert results_hit[0]["rejection_reason"] is None
