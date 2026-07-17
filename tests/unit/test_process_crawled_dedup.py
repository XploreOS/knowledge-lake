"""DEDUP-01 call-order/argument-identity tests: process_crawled must dedup
chunks between chunk() and embed()/index().

process_crawled (pipeline/process.py) is the single implementation shared by
the CLI, API, and MCP entry points (D-03 "one function, many callers"). Before
this plan it ran chunk() -> embed(chunks_list) -> index(chunks_list, ...) with
no dedup stage at all, so every chunk (including exact-text duplicates already
seen elsewhere in the corpus) was re-embedded and re-indexed as a brand new
Qdrant point. These tests prove:

  1. dedup_chunks() is called with the exact chunks_list object chunk()
     returned, plus parsed_id/src_id positionally and collection= as a keyword.
  2. embed() is called with dedup_result["new"] specifically — never the
     original chunks_list, never dedup_result["duplicates"].
  3. index() is called with dedup_result["new"] as its chunks argument and
     duplicate_chunks=dedup_result["duplicates"] as a keyword argument.
  4. When chunk() returns an empty list (all chunks rejected upstream), the
     existing "if not chunks_list: processed += 1; continue" branch fires
     and dedup_chunks() is never called.
  5. When dedup_chunks() returns {"new": [], "duplicates": [...]} (every
     chunk in this document was a pre-existing duplicate), embed() and
     index() are still called with those (empty new / non-empty duplicates)
     values, not skipped.

Mocking note (mirrors test_process_crawled_clean.py's own documented
rationale): process_crawled imports parse/clean/chunk/dedup_chunks/embed/index
as FUNCTION-LOCAL imports (``from knowledge_lake.pipeline.dedup import
dedup_chunks`` etc., executed fresh each call inside the function body)
rather than module-level imports. Because of that,
``knowledge_lake.pipeline.process`` never carries these as module attributes,
so ``unittest.mock.patch("knowledge_lake.pipeline.process.dedup_chunks")``
would raise AttributeError. The correct, actually-working interception point
is the SOURCE module each local import reads from at call-time --
``knowledge_lake.pipeline.dedup.dedup_chunks`` -- which is what these tests
patch, alongside the same parse/clean/chunk/embed/index interception points
test_process_crawled_clean.py established.
"""

from __future__ import annotations

from typing import Any
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


@pytest.fixture()
def source(session):
    """Seed a Source row for the raw_document artifact to belong to."""
    from knowledge_lake.registry import repo as registry_repo

    src = registry_repo.create_source(
        session,
        name="test-source-process-crawled-dedup",
        source_type="upload",
        config={},
    )
    session.flush()
    session.commit()
    return src


def _seed_raw_document(session, source_id: str) -> Any:
    """Create a raw_document artifact with no parsed_document child."""
    from knowledge_lake.registry import repo as registry_repo

    raw_art = registry_repo.create_raw_artifact(
        session,
        source_id=source_id,
        content_hash="rawprocessdedup123456789abcdef",
        storage_uri="s3://test-bucket/raw/test-source-process-crawled-dedup/rawprocessdedup123456789abcdef.html",
        mime_type="text/html",
    )
    session.flush()
    session.commit()
    return raw_art


def _base_mocks(chunks_list: list[dict]):
    """Return the standard parse/clean/chunk mocks that most tests share."""
    mock_parse = MagicMock(return_value=({"artifact_id": "parsed-1"}, object()))
    mock_clean = MagicMock(return_value={"cleaned_doc": object()})
    mock_chunk = MagicMock(return_value=chunks_list)
    return mock_parse, mock_clean, mock_chunk


# ── Task 1: dedup_chunks() call-order and argument-identity tests ────────────


class TestProcessCrawledDedupWiring:
    """dedup_chunks() sits between chunk() and embed()/index(); embed() gets
    only the new chunks, index() gets new chunks plus duplicate_chunks=."""

    def test_dedup_chunks_called_with_chunks_list_identity_and_ids(
        self, session, source
    ):
        """dedup_chunks() must be called with the exact chunks_list object
        chunk() returned, plus parsed_id/src_id and collection=."""
        from knowledge_lake.pipeline.process import process_crawled

        _seed_raw_document(session, source.id)

        sentinel_chunks_list = [{"chunk_id": "c1", "text": "hello"}]
        mock_parse, mock_clean, mock_chunk = _base_mocks(sentinel_chunks_list)
        mock_chunk.return_value = sentinel_chunks_list
        mock_dedup = MagicMock(
            return_value={"new": sentinel_chunks_list, "duplicates": []}
        )
        mock_embed = MagicMock(return_value=([[0.1]], 1))
        mock_index = MagicMock(return_value=None)

        with (
            patch("knowledge_lake.pipeline.parse.parse", mock_parse),
            patch("knowledge_lake.pipeline.clean.clean", mock_clean),
            patch("knowledge_lake.pipeline.chunk.chunk", mock_chunk),
            patch("knowledge_lake.pipeline.dedup.dedup_chunks", mock_dedup),
            patch("knowledge_lake.pipeline.embed.embed", mock_embed),
            patch("knowledge_lake.pipeline.index.index", mock_index),
        ):
            result = process_crawled(collection="klake_chunks")

        assert result["failed"] == 0
        mock_dedup.assert_called_once()
        args, kwargs = mock_dedup.call_args
        assert args[0] is sentinel_chunks_list, (
            "dedup_chunks() must receive the exact chunks_list object chunk() "
            "returned"
        )
        assert args[1] == "parsed-1"
        # source_id: pull from the seeded raw doc via the actual call — just
        # assert it's a string (the seeded source id), not None/sentinel.
        assert isinstance(args[2], str) and args[2]
        assert kwargs.get("collection") == "klake_chunks"

    def test_embed_receives_dedup_new_not_chunks_list_not_duplicates(
        self, session, source
    ):
        """embed() must be called with dedup_result['new'] specifically —
        never the original chunks_list, never dedup_result['duplicates']."""
        from knowledge_lake.pipeline.process import process_crawled

        _seed_raw_document(session, source.id)

        original_chunks_list = [{"chunk_id": "c1"}, {"chunk_id": "c2"}]
        new_sentinel = [{"chunk_id": "c1", "point_id": "p1"}]
        duplicates_sentinel = [{"chunk_id": "c2", "point_id": "p2"}]
        mock_parse, mock_clean, mock_chunk = _base_mocks(original_chunks_list)
        mock_dedup = MagicMock(
            return_value={"new": new_sentinel, "duplicates": duplicates_sentinel}
        )
        mock_embed = MagicMock(return_value=([[0.1]], 1))
        mock_index = MagicMock(return_value=None)

        with (
            patch("knowledge_lake.pipeline.parse.parse", mock_parse),
            patch("knowledge_lake.pipeline.clean.clean", mock_clean),
            patch("knowledge_lake.pipeline.chunk.chunk", mock_chunk),
            patch("knowledge_lake.pipeline.dedup.dedup_chunks", mock_dedup),
            patch("knowledge_lake.pipeline.embed.embed", mock_embed),
            patch("knowledge_lake.pipeline.index.index", mock_index),
        ):
            result = process_crawled()

        assert result["failed"] == 0
        mock_embed.assert_called_once()
        args, _ = mock_embed.call_args
        assert args[0] is new_sentinel
        assert args[0] is not original_chunks_list
        assert args[0] is not duplicates_sentinel

    def test_index_receives_dedup_new_and_duplicate_chunks_kwarg(
        self, session, source
    ):
        """index() must be called with dedup_result['new'] as its first
        (chunks) argument and duplicate_chunks=dedup_result['duplicates']."""
        from knowledge_lake.pipeline.process import process_crawled

        _seed_raw_document(session, source.id)

        original_chunks_list = [{"chunk_id": "c1"}, {"chunk_id": "c2"}]
        new_sentinel = [{"chunk_id": "c1", "point_id": "p1"}]
        duplicates_sentinel = [{"chunk_id": "c2", "point_id": "p2"}]
        mock_parse, mock_clean, mock_chunk = _base_mocks(original_chunks_list)
        mock_dedup = MagicMock(
            return_value={"new": new_sentinel, "duplicates": duplicates_sentinel}
        )
        mock_embed = MagicMock(return_value=([[0.1]], 1))
        mock_index = MagicMock(return_value=None)

        with (
            patch("knowledge_lake.pipeline.parse.parse", mock_parse),
            patch("knowledge_lake.pipeline.clean.clean", mock_clean),
            patch("knowledge_lake.pipeline.chunk.chunk", mock_chunk),
            patch("knowledge_lake.pipeline.dedup.dedup_chunks", mock_dedup),
            patch("knowledge_lake.pipeline.embed.embed", mock_embed),
            patch("knowledge_lake.pipeline.index.index", mock_index),
        ):
            result = process_crawled()

        assert result["failed"] == 0
        mock_index.assert_called_once()
        args, kwargs = mock_index.call_args
        assert args[0] is new_sentinel
        assert kwargs.get("duplicate_chunks") is duplicates_sentinel


class TestProcessCrawledDedupBoundaries:
    """Empty-chunks guard still skips dedup_chunks entirely; all-duplicates
    batch still runs embed()/index() (not skipped)."""

    def test_empty_chunks_list_skips_dedup_chunks_entirely(self, session, source):
        """chunk() returning [] must hit the existing empty-guard branch
        BEFORE dedup_chunks() is ever called."""
        from knowledge_lake.pipeline.process import process_crawled

        _seed_raw_document(session, source.id)

        mock_parse, mock_clean, mock_chunk = _base_mocks([])
        mock_dedup = MagicMock()
        mock_embed = MagicMock(return_value=([], 0))
        mock_index = MagicMock(return_value=None)

        with (
            patch("knowledge_lake.pipeline.parse.parse", mock_parse),
            patch("knowledge_lake.pipeline.clean.clean", mock_clean),
            patch("knowledge_lake.pipeline.chunk.chunk", mock_chunk),
            patch("knowledge_lake.pipeline.dedup.dedup_chunks", mock_dedup),
            patch("knowledge_lake.pipeline.embed.embed", mock_embed),
            patch("knowledge_lake.pipeline.index.index", mock_index),
        ):
            result = process_crawled()

        assert result["failed"] == 0
        assert result["processed"] == 1
        assert result["chunks_indexed"] == 0
        mock_dedup.assert_not_called()
        mock_embed.assert_not_called()
        mock_index.assert_not_called()

    def test_all_duplicates_still_calls_embed_and_index(self, session, source):
        """dedup_chunks() returning {'new': [], 'duplicates': [<n>]} (every
        chunk in this document was a pre-existing duplicate) must still
        call embed([]) and index([], ..., duplicate_chunks=[<n>]) — not
        skipped."""
        from knowledge_lake.pipeline.process import process_crawled

        _seed_raw_document(session, source.id)

        original_chunks_list = [{"chunk_id": "c1"}]
        duplicates_sentinel = [{"chunk_id": "c1", "point_id": "p1"}]
        mock_parse, mock_clean, mock_chunk = _base_mocks(original_chunks_list)
        mock_dedup = MagicMock(
            return_value={"new": [], "duplicates": duplicates_sentinel}
        )
        mock_embed = MagicMock(return_value=([], 0))
        mock_index = MagicMock(return_value=None)

        with (
            patch("knowledge_lake.pipeline.parse.parse", mock_parse),
            patch("knowledge_lake.pipeline.clean.clean", mock_clean),
            patch("knowledge_lake.pipeline.chunk.chunk", mock_chunk),
            patch("knowledge_lake.pipeline.dedup.dedup_chunks", mock_dedup),
            patch("knowledge_lake.pipeline.embed.embed", mock_embed),
            patch("knowledge_lake.pipeline.index.index", mock_index),
        ):
            result = process_crawled()

        assert result["failed"] == 0
        assert result["processed"] == 1
        # total_chunks counts chunks PRODUCED by chunk(), independent of dedup.
        assert result["chunks_indexed"] == 1

        mock_embed.assert_called_once()
        embed_args, _ = mock_embed.call_args
        assert embed_args[0] == []

        mock_index.assert_called_once()
        index_args, index_kwargs = mock_index.call_args
        assert index_args[0] == []
        assert index_kwargs.get("duplicate_chunks") is duplicates_sentinel
