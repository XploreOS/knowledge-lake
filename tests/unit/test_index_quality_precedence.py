"""Unit tests for pipeline/index.py's quality_score precedence (KL-04/05/06).

Precedence: curated_document's real quality_score column wins, falling back to
enriched_document's real quality_score column, falling back to None.
document_type/keywords/title still come only from enrichment metadata.

Also covers the reindex payload-refresh repair path (KL-06): opt-in
--refresh-payload re-derives the payload from the registry per point instead
of copying it verbatim; the default path still copies verbatim.

Uses the same in-memory-SQLite-backed session harness as
tests/unit/test_index_payload.py: knowledge_lake.registry.db.get_engine is
monkeypatched to a StaticPool sqlite engine so index()'s own get_session()
calls resolve against the same database the test seeds via registry_repo.
get_vectorstore() is mocked at the pipeline.index module level so no real
Qdrant server is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.pipeline.index as index_module
import knowledge_lake.registry.db as registry_db
from knowledge_lake.registry import repo as registry_repo

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    """In-memory SQLite engine, shared connection via StaticPool so multiple
    Session() instances (opened by separate get_session() calls inside
    index()/reindex_collection()) all see the same committed data.
    """
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
    """Route registry.db.get_session() at index()'s call sites to the test engine."""
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)


@pytest.fixture()
def session(engine):
    with Session(engine) as sess:
        yield sess


@pytest.fixture()
def fake_vstore(monkeypatch):
    """Mock get_vectorstore() so index() never touches a real Qdrant server."""
    vstore = MagicMock()
    vstore.ensure_aliased_collection.return_value = ("klake_chunks_v1", False)
    monkeypatch.setattr(index_module, "get_vectorstore", lambda _s: vstore)
    return vstore


def _one_chunk(chunk_id: str = "chk_001") -> dict:
    return {
        "chunk_id": chunk_id,
        "section_path": "§1",
        "page": 1,
        "text": "hello world",
    }


def _captured_payload(vstore: MagicMock) -> dict:
    """Extract the single upserted VectorPoint's payload from the mocked upsert call."""
    upsert_call = vstore.upsert.call_args
    points = (
        upsert_call.args[1] if upsert_call.args and len(upsert_call.args) > 1 else upsert_call.kwargs["points"]
    )
    return points[0].payload


def _seed_source_and_parsed(session, hash_prefix: str) -> tuple:
    source = registry_repo.create_source(session, name=f"{hash_prefix} Source", source_type="web")
    raw = registry_repo.create_raw_artifact(
        session, source_id=source.id, content_hash=f"{hash_prefix}_raw",
        storage_uri=f"s3://b/raw/{hash_prefix}_raw.pdf",
    )
    parsed = registry_repo.create_parsed_artifact(
        session, source_id=source.id, parent_artifact_id=raw.id,
        content_hash=f"{hash_prefix}_parsed", storage_uri=f"s3://b/silver/{hash_prefix}_parsed.json",
    )
    return source, parsed


def _seed_cleaned(session, source, parsed, hash_prefix: str):
    return registry_repo.create_cleaned_artifact(
        session, source_id=source.id, parent_artifact_id=parsed.id,
        content_hash=f"{hash_prefix}_cleaned", storage_uri=f"s3://b/silver/{hash_prefix}_cleaned.md",
    )


# ── quality_score precedence tests ─────────────────────────────────────────────


class TestQualityScorePrecedence:
    """curated wins over enriched; enriched is the fallback; neither -> None."""

    def test_curated_present_curated_wins_over_enriched(self, session, fake_vstore) -> None:
        """Real-data-shaped regression: curated=0.797, enriched=0.92 -> payload uses 0.797."""
        source, parsed = _seed_source_and_parsed(session, "curwin")
        cleaned = _seed_cleaned(session, source, parsed, "curwin")
        registry_repo.create_enriched_artifact(
            session, source_id=source.id, parent_artifact_id=cleaned.id,
            content_hash="curwin_enriched", quality_score=0.92,
        )
        registry_repo.create_curated_artifact(
            session, source_id=source.id, parent_artifact_id=cleaned.id,
            content_hash="curwin_curated", quality_score=0.797,
        )
        session.commit()

        index_module.index([_one_chunk()], [[0.1] * 4], dim=4, parsed_artifact_id=parsed.id)
        payload = _captured_payload(fake_vstore)

        assert payload["quality_score"] == pytest.approx(0.797), (
            "quality_score must prefer the curated composite over the enriched "
            f"LLM score (KL-04/05/06); got {payload['quality_score']}"
        )

    def test_only_enriched_enriched_is_used(self, session, fake_vstore) -> None:
        source, parsed = _seed_source_and_parsed(session, "enronly")
        cleaned = _seed_cleaned(session, source, parsed, "enronly")
        registry_repo.create_enriched_artifact(
            session, source_id=source.id, parent_artifact_id=cleaned.id,
            content_hash="enronly_enriched", quality_score=0.65,
        )
        session.commit()

        index_module.index([_one_chunk()], [[0.1] * 4], dim=4, parsed_artifact_id=parsed.id)
        payload = _captured_payload(fake_vstore)

        assert payload["quality_score"] == pytest.approx(0.65)

    def test_neither_present_quality_score_is_none(self, session, fake_vstore) -> None:
        source, parsed = _seed_source_and_parsed(session, "neither")
        session.commit()

        index_module.index([_one_chunk()], [[0.1] * 4], dim=4, parsed_artifact_id=parsed.id)
        payload = _captured_payload(fake_vstore)

        assert payload["quality_score"] is None

    def test_document_type_and_keywords_still_come_from_enrichment_only(
        self, session, fake_vstore
    ) -> None:
        """Curation carries no document_type/keywords/title — those still come from enrich."""
        source, parsed = _seed_source_and_parsed(session, "dtype")
        cleaned = _seed_cleaned(session, source, parsed, "dtype")
        registry_repo.create_enriched_artifact(
            session, source_id=source.id, parent_artifact_id=cleaned.id,
            content_hash="dtype_enriched",
            metadata={"document_type": "guidance", "keywords": ["aviation"], "title": "Flight Ops"},
            quality_score=0.5,
        )
        registry_repo.create_curated_artifact(
            session, source_id=source.id, parent_artifact_id=cleaned.id,
            content_hash="dtype_curated", quality_score=0.9,
        )
        session.commit()

        index_module.index([_one_chunk()], [[0.1] * 4], dim=4, parsed_artifact_id=parsed.id)
        payload = _captured_payload(fake_vstore)

        assert payload["quality_score"] == pytest.approx(0.9)
        assert payload["document_type"] == "guidance"
        assert payload["keywords"] == ["aviation"]
        assert payload["title"] == "Flight Ops"

    def test_curated_none_quality_score_falls_back_to_enriched(self, session, fake_vstore) -> None:
        """A curated_document row with quality_score=None must not shadow the enriched fallback."""
        source, parsed = _seed_source_and_parsed(session, "curnone")
        cleaned = _seed_cleaned(session, source, parsed, "curnone")
        registry_repo.create_enriched_artifact(
            session, source_id=source.id, parent_artifact_id=cleaned.id,
            content_hash="curnone_enriched", quality_score=0.42,
        )
        registry_repo.create_curated_artifact(
            session, source_id=source.id, parent_artifact_id=cleaned.id,
            content_hash="curnone_curated", quality_score=None,
        )
        session.commit()

        index_module.index([_one_chunk()], [[0.1] * 4], dim=4, parsed_artifact_id=parsed.id)
        payload = _captured_payload(fake_vstore)

        assert payload["quality_score"] == pytest.approx(0.42)


class TestGetCuratedArtifactForParsed:
    """registry_repo.get_curated_artifact_for_parsed mirrors get_enriched_artifact_for_parsed."""

    def test_walks_parsed_to_cleaned_to_curated(self, session) -> None:
        source, parsed = _seed_source_and_parsed(session, "walk")
        cleaned = _seed_cleaned(session, source, parsed, "walk")
        curated = registry_repo.create_curated_artifact(
            session, source_id=source.id, parent_artifact_id=cleaned.id,
            content_hash="walk_curated", quality_score=0.71,
        )
        session.commit()

        result = registry_repo.get_curated_artifact_for_parsed(session, parsed.id)
        assert result is not None
        assert result.id == curated.id
        assert result.quality_score == pytest.approx(0.71)

    def test_returns_none_when_no_cleaned_child(self, session) -> None:
        source, parsed = _seed_source_and_parsed(session, "nocleaned")
        session.commit()

        assert registry_repo.get_curated_artifact_for_parsed(session, parsed.id) is None

    def test_returns_none_when_cleaned_has_no_curated_child(self, session) -> None:
        source, parsed = _seed_source_and_parsed(session, "nocurated")
        _seed_cleaned(session, source, parsed, "nocurated")
        session.commit()

        assert registry_repo.get_curated_artifact_for_parsed(session, parsed.id) is None


# ── reindex payload-refresh tests (KL-06 repair path) ──────────────────────────


class TestReindexPayloadRefresh:
    """--refresh-payload re-derives payloads from the registry; default still copies verbatim."""

    def test_default_reindex_copies_verbatim(self, monkeypatch) -> None:
        """Default (refresh_payload=False, hybrid=False) still uses copy_all_points."""
        vstore = MagicMock()
        vstore.get_collection_dim.return_value = 4
        vstore.reindex.side_effect = lambda alias, dim, upsert_fn, **kw: (
            upsert_fn("klake_chunks_v2"),
            {"new_physical": "klake_chunks_v2", "old_physical": "klake_chunks_v1"},
        )[1]
        monkeypatch.setattr(index_module, "get_vectorstore", lambda _s: vstore)

        index_module.reindex_collection("klake_chunks")

        vstore.copy_all_points.assert_called_once_with("klake_chunks", "klake_chunks_v2")
        vstore.refresh_all_points_payload.assert_not_called()

    def test_refresh_payload_true_uses_refresh_all_points_payload(self, monkeypatch) -> None:
        """refresh_payload=True routes through vstore.refresh_all_points_payload, not copy."""
        vstore = MagicMock()
        vstore.get_collection_dim.return_value = 4
        vstore.reindex.side_effect = lambda alias, dim, upsert_fn, **kw: (
            upsert_fn("klake_chunks_v2"),
            {"new_physical": "klake_chunks_v2", "old_physical": "klake_chunks_v1"},
        )[1]
        monkeypatch.setattr(index_module, "get_vectorstore", lambda _s: vstore)

        index_module.reindex_collection("klake_chunks", refresh_payload=True)

        vstore.copy_all_points.assert_not_called()
        vstore.refresh_all_points_payload.assert_called_once()
        call_args = vstore.refresh_all_points_payload.call_args
        assert call_args.args[0] == "klake_chunks"
        assert call_args.args[1] == "klake_chunks_v2"
        assert callable(call_args.args[2])

    def test_refresh_resolve_fn_rederives_quality_score_from_registry(
        self, session, monkeypatch
    ) -> None:
        """The payload_resolve_fn built for refresh must re-read the registry — proving
        this is a real re-derivation, not a pass-through of the old payload.
        """
        source, parsed = _seed_source_and_parsed(session, "refresh")
        cleaned = _seed_cleaned(session, source, parsed, "refresh")
        # At original index-time there was no curated sibling; only enriched existed.
        registry_repo.create_enriched_artifact(
            session, source_id=source.id, parent_artifact_id=cleaned.id,
            content_hash="refresh_enriched", quality_score=0.5,
        )
        session.commit()

        resolve_fn = index_module._build_payload_refresh_fn()

        old_payload = {
            "document": parsed.id,
            "section_path": "§1",
            "page": 1,
            "chunk_id": "chk_001",
            "qdrant_id": "001",
            "text": "hello",
            "quality_score": None,  # stale: was indexed before enrichment ran
        }
        new_payload = resolve_fn(old_payload)
        assert new_payload["quality_score"] == pytest.approx(0.5)
        # Citation fields must be preserved untouched.
        assert new_payload["text"] == "hello"
        assert new_payload["chunk_id"] == "chk_001"

        # Curation lands later — a second refresh call must pick up the curated
        # score without needing new construction of the resolve_fn.
        registry_repo.create_curated_artifact(
            session, source_id=source.id, parent_artifact_id=cleaned.id,
            content_hash="refresh_curated", quality_score=0.88,
        )
        session.commit()

        resolve_fn2 = index_module._build_payload_refresh_fn()
        newer_payload = resolve_fn2(old_payload)
        assert newer_payload["quality_score"] == pytest.approx(0.88)

    def test_refresh_resolve_fn_preserves_payload_when_no_document_key(self) -> None:
        """A malformed/legacy point payload with no 'document' key must not raise."""
        resolve_fn = index_module._build_payload_refresh_fn()
        old_payload = {"chunk_id": "chk_orphan", "text": "orphan"}
        new_payload = resolve_fn(old_payload)
        assert new_payload == old_payload

    def test_reindex_cli_wraps_refresh_payload_through(self, monkeypatch) -> None:
        """CLI cmd_index/cmd_reindex must forward --refresh-payload to reindex_collection."""
        from typer.testing import CliRunner

        from knowledge_lake.cli.app import app

        captured = {}

        def _fake_reindex_collection(collection, *, hybrid=False, refresh_payload=False, settings=None):
            captured["refresh_payload"] = refresh_payload
            return {"collection": collection, "new_physical": "v2", "old_physical": "v1"}

        monkeypatch.setattr(
            "knowledge_lake.pipeline.index.reindex_collection", _fake_reindex_collection
        )

        runner = CliRunner()
        result = runner.invoke(app, ["index", "--refresh-payload"])
        assert result.exit_code == 0, result.output
        assert captured["refresh_payload"] is True

        result2 = runner.invoke(app, ["index"])
        assert result2.exit_code == 0, result2.output
        assert captured["refresh_payload"] is False
