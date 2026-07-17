"""Parametrized CI proof that the MEAS-02 must_not_reject.yaml fixture set
survives the REAL chunk() substance gate end-to-end (D-16).

Closes RESEARCH.md Pitfall 1's explicitly-flagged gap: a fixture test that
only calls run_predicates()/check_domain_allowlist() directly can pass while
the real pipeline still drops the same text, because chunk() never had
domain_filters wired in. Plan 20-02 fixed that wiring (chunk_document,
process_crawled); this module is the CI proof that the fix actually protects
every fixture entry when domain_filters is resolved exactly as production
resolves it: DomainLoader.from_name("healthcare").filters.

Fixture-loading and parametrize style mirrors tests/unit/test_chunk_storage.py's
engine/_patch_engine/fake_storage/test_settings/_seed_source_and_parsed
fixtures (this is a real chunk() call requiring the same in-memory-SQLite +
mocked-StorageBackend harness).
"""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.registry.db as registry_db
from knowledge_lake.config.settings import Settings
from knowledge_lake.plugins.protocols import ParsedDoc, Section

# ── Fixture data: load + collection-time non-empty assertion ─────────────────

_FIXTURE_PATH = pathlib.Path(__file__).parent.parent / "fixtures" / "must_not_reject.yaml"
_FIXTURES: list[dict] = yaml.safe_load(_FIXTURE_PATH.read_text(encoding="utf-8"))

# Module-level assertion — fires at collection time, not per-test. If the
# fixture file is accidentally emptied or corrupted, this fails loudly
# instead of silently collecting 0 parametrized tests (which would otherwise
# "pass" vacuously with an empty test run).
assert isinstance(_FIXTURES, list) and len(_FIXTURES) >= 20, (
    f"must_not_reject.yaml must contain >= 20 entries, found {len(_FIXTURES) if isinstance(_FIXTURES, list) else 'non-list'}"
)


# ── Fixtures (mirrors tests/unit/test_chunk_storage.py verbatim) ─────────────


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
    """Patch StorageBackend inside pipeline.chunk to capture put_object calls."""
    from knowledge_lake.pipeline.chunk import StorageBackend  # noqa: F401

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


# ── The proof test ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "entry",
    _FIXTURES,
    ids=[e["label"] for e in _FIXTURES],
)
def test_fixture_survives_real_chunk_substance_gate(entry, engine, fake_storage, test_settings):
    """Every must_not_reject.yaml entry survives chunk()'s real composite
    substance gate with domain_filters resolved via the real, production-shape
    DomainLoader.from_name("healthcare").filters call — not a mock, not a bare
    predicate-function call.

    Iterates ALL chunks returned for the fixture (not just the first) in case
    a fixture text is long enough to be split into multiple chunks by
    _build_token_chunks.
    """
    from knowledge_lake.domains.loader import DomainLoader
    from knowledge_lake.pipeline.chunk import chunk

    source_id, parsed_id = _seed_source_and_parsed(engine, domain="healthcare")
    parsed_doc = ParsedDoc(
        text="ignored",
        sections=[
            Section(
                heading="",
                section_path="§1",
                page=1,
                text=entry["text"],
                is_table=False,
            )
        ],
        metadata={},
    )

    domain_filters = DomainLoader.from_name("healthcare").filters

    results = chunk(
        parsed_id,
        source_id,
        parsed_doc,
        settings=test_settings,
        domain_filters=domain_filters,
    )

    assert len(results) >= 1, (
        f"Fixture '{entry['label']}' (category={entry['category']!r}) produced "
        f"zero chunks — the entire text was dropped before the substance gate "
        f"could even annotate it."
    )
    for r in results:
        assert r["substance_passed"], (
            f"Fixture '{entry['label']}' (category={entry['category']!r}) was "
            f"REJECTED by the substance gate: rejection_reason="
            f"{r.get('rejection_reason')!r}, text={entry['text']!r}"
        )
