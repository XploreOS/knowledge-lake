"""CLEAN-02 parity tests: process_crawled must clean() between parse() and chunk().

process_crawled (pipeline/process.py) is the single implementation shared by
the CLI, API, and MCP entry points (D-03 "one function, many callers"). Before
this plan it ran parse -> chunk -> embed -> index with NO clean stage at all —
the exact code path the original 28%-garbage audit ran. These tests prove:

  1. clean() is called between parse() and chunk(), with parsed_doc= set to
     the exact object parse() returned.
  2. chunk() receives clean_result["cleaned_doc"] as its third positional
     argument, never the raw parsed_doc.
  3. chunk()'s first positional argument (parsed_artifact_id) is unchanged —
     chunks are never re-parented to the cleaned artifact.
  4. A clean() failure (ValueError, matching clean()'s documented Raises) is
     absorbed by the existing except Exception block into result["failed"] —
     no new failure mode, no new except-branch.
  5. A document whose cleaned sections produce zero chunks still increments
     result["processed"] via the existing empty-chunks-continue branch, and
     embed()/index() are not called for that document.

Mocking note (deviation from the plan's literal read_first pointer): process_crawled
imports parse/clean/chunk/embed/index as FUNCTION-LOCAL imports
(``from knowledge_lake.pipeline.parse import parse`` etc., executed fresh each
call inside the function body) rather than module-level imports. Because of
that, ``knowledge_lake.pipeline.process`` never carries ``parse``/``clean``/...
as module attributes, so ``unittest.mock.patch("knowledge_lake.pipeline.process.parse")``
raises AttributeError (verified empirically). The standing gotcha this plan's
read_first cites (``pipeline/route.py`` binding ``search`` at *module* import
time) does not apply to this local-import shape. The correct, actually-working
interception point is the SOURCE module each local import reads from at
call-time -- ``knowledge_lake.pipeline.parse.parse``, ``.clean.clean``,
``.chunk.chunk``, ``.embed.embed``, ``.index.index`` -- which is what these
tests patch.
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
        name="test-source-process-crawled",
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
        content_hash="rawprocess123456789abcdef",
        storage_uri="s3://test-bucket/raw/test-source-process-crawled/rawprocess123456789abcdef.html",
        mime_type="text/html",
    )
    session.flush()
    session.commit()
    return raw_art


# ── Task 1: call-order and argument-identity tests ────────────────────────────


class TestProcessCrawledCleanWiring:
    """clean() sits between parse() and chunk(); chunk() gets the cleaned doc."""

    def test_clean_called_with_parse_result_parsed_doc(self, session, source):
        """clean() must be called with parsed_doc= set to parse()'s returned object."""
        from knowledge_lake.pipeline.process import process_crawled

        _seed_raw_document(session, source.id)

        sentinel_parsed_doc = object()
        mock_parse = MagicMock(
            return_value=({"artifact_id": "parsed-1"}, sentinel_parsed_doc)
        )
        mock_clean = MagicMock(return_value={"cleaned_doc": object()})
        mock_chunk = MagicMock(return_value=[{"chunk_id": "c1"}])
        mock_embed = MagicMock(return_value=([[0.1]], 1))
        mock_index = MagicMock(return_value=None)

        with (
            patch("knowledge_lake.pipeline.parse.parse", mock_parse),
            patch("knowledge_lake.pipeline.clean.clean", mock_clean),
            patch("knowledge_lake.pipeline.chunk.chunk", mock_chunk),
            patch("knowledge_lake.pipeline.embed.embed", mock_embed),
            patch("knowledge_lake.pipeline.index.index", mock_index),
        ):
            result = process_crawled()

        assert result["failed"] == 0
        mock_clean.assert_called_once()
        _, kwargs = mock_clean.call_args
        assert kwargs.get("parsed_doc") is sentinel_parsed_doc, (
            "clean() must receive parsed_doc= as the exact object parse() returned"
        )

    def test_chunk_receives_cleaned_doc_not_raw_parsed_doc(self, session, source):
        """chunk()'s third positional argument must be clean_result['cleaned_doc']."""
        from knowledge_lake.pipeline.process import process_crawled

        _seed_raw_document(session, source.id)

        raw_parsed_doc = object()
        cleaned_doc_sentinel = object()
        mock_parse = MagicMock(return_value=({"artifact_id": "parsed-1"}, raw_parsed_doc))
        mock_clean = MagicMock(return_value={"cleaned_doc": cleaned_doc_sentinel})
        mock_chunk = MagicMock(return_value=[{"chunk_id": "c1"}])
        mock_embed = MagicMock(return_value=([[0.1]], 1))
        mock_index = MagicMock(return_value=None)

        with (
            patch("knowledge_lake.pipeline.parse.parse", mock_parse),
            patch("knowledge_lake.pipeline.clean.clean", mock_clean),
            patch("knowledge_lake.pipeline.chunk.chunk", mock_chunk),
            patch("knowledge_lake.pipeline.embed.embed", mock_embed),
            patch("knowledge_lake.pipeline.index.index", mock_index),
        ):
            result = process_crawled()

        assert result["failed"] == 0
        mock_chunk.assert_called_once()
        args, _ = mock_chunk.call_args
        assert args[2] is cleaned_doc_sentinel, (
            "chunk()'s third positional argument must be clean_result['cleaned_doc'], "
            "not the raw parsed_doc"
        )
        assert args[2] is not raw_parsed_doc

    def test_chunk_parsed_artifact_id_unchanged(self, session, source):
        """chunk()'s first positional argument (parsed_artifact_id) is never re-parented."""
        from knowledge_lake.pipeline.process import process_crawled

        _seed_raw_document(session, source.id)

        mock_parse = MagicMock(return_value=({"artifact_id": "parsed-fixed-id"}, object()))
        mock_clean = MagicMock(return_value={"cleaned_doc": object()})
        mock_chunk = MagicMock(return_value=[{"chunk_id": "c1"}])
        mock_embed = MagicMock(return_value=([[0.1]], 1))
        mock_index = MagicMock(return_value=None)

        with (
            patch("knowledge_lake.pipeline.parse.parse", mock_parse),
            patch("knowledge_lake.pipeline.clean.clean", mock_clean),
            patch("knowledge_lake.pipeline.chunk.chunk", mock_chunk),
            patch("knowledge_lake.pipeline.embed.embed", mock_embed),
            patch("knowledge_lake.pipeline.index.index", mock_index),
        ):
            result = process_crawled()

        assert result["failed"] == 0
        mock_chunk.assert_called_once()
        args, _ = mock_chunk.call_args
        assert args[0] == "parsed-fixed-id"
        # clean() must also have received the same, unchanged parsed_artifact_id
        # as its first positional argument.
        clean_args, _ = mock_clean.call_args
        assert clean_args[0] == "parsed-fixed-id"


# ── Task 2: error-handling parity and empty-sections boundary tests ───────────


class TestProcessCrawledCleanBoundaries:
    """clean()'s new failure mode and empty-sections case are absorbed by
    process_crawled's existing except/continue branches — no new branch."""

    def test_clean_failure_counted_as_failed_not_processed(self, session, source):
        """A clean() ValueError lands in result['failed'], not result['processed'],
        and does not propagate out of process_crawled()."""
        from knowledge_lake.pipeline.process import process_crawled

        _seed_raw_document(session, source.id)

        mock_parse = MagicMock(return_value=({"artifact_id": "parsed-1"}, object()))
        mock_clean = MagicMock(
            side_effect=ValueError("clean: parsed_artifact not found")
        )
        mock_chunk = MagicMock(return_value=[{"chunk_id": "c1"}])
        mock_embed = MagicMock(return_value=([[0.1]], 1))
        mock_index = MagicMock(return_value=None)

        with (
            patch("knowledge_lake.pipeline.parse.parse", mock_parse),
            patch("knowledge_lake.pipeline.clean.clean", mock_clean),
            patch("knowledge_lake.pipeline.chunk.chunk", mock_chunk),
            patch("knowledge_lake.pipeline.embed.embed", mock_embed),
            patch("knowledge_lake.pipeline.index.index", mock_index),
        ):
            # Must not raise: process_crawled() absorbs clean()'s ValueError via
            # the existing except Exception block.
            result = process_crawled()

        assert result["failed"] == 1
        assert result["processed"] == 0
        mock_chunk.assert_not_called()
        mock_embed.assert_not_called()
        mock_index.assert_not_called()

    def test_empty_chunks_still_counted_processed_no_embed_index(self, session, source):
        """An all-empty-section cleaned_doc that yields zero chunks still hits
        the existing 'if not chunks_list: processed += 1; continue' branch."""
        from knowledge_lake.pipeline.process import process_crawled

        _seed_raw_document(session, source.id)

        cleaned_doc_sentinel = object()
        mock_parse = MagicMock(return_value=({"artifact_id": "parsed-1"}, object()))
        mock_clean = MagicMock(return_value={"cleaned_doc": cleaned_doc_sentinel})
        mock_chunk = MagicMock(return_value=[])
        mock_embed = MagicMock(return_value=([], 0))
        mock_index = MagicMock(return_value=None)

        with (
            patch("knowledge_lake.pipeline.parse.parse", mock_parse),
            patch("knowledge_lake.pipeline.clean.clean", mock_clean),
            patch("knowledge_lake.pipeline.chunk.chunk", mock_chunk),
            patch("knowledge_lake.pipeline.embed.embed", mock_embed),
            patch("knowledge_lake.pipeline.index.index", mock_index),
        ):
            result = process_crawled()

        assert result["failed"] == 0
        assert result["processed"] == 1
        assert result["chunks_indexed"] == 0
        mock_chunk.assert_called_once()
        mock_embed.assert_not_called()
        mock_index.assert_not_called()


# ── Task 1 (20-02): domain_filters resolution and threading ───────────────────


class TestProcessCrawledDomainFilters:
    """process_crawled() must resolve settings.domain.domain_name via
    DomainLoader.from_name(...).filters and thread the result into every
    chunk() call — closing RESEARCH.md Pitfall 1's explicitly-flagged gap:
    a unit-level predicate test alone does not prove the production pipeline
    protects clinical codes. Patches knowledge_lake.config.settings.get_settings
    (the SOURCE module process_crawled's function-local import reads from) and
    knowledge_lake.domains.loader.DomainLoader.from_name."""

    def test_domain_filters_resolved_and_threaded_when_domain_configured(
        self, session, source
    ):
        """settings.domain.domain_name set -> DomainLoader.from_name(...).filters
        is resolved once and threaded into chunk(domain_filters=...)."""
        from knowledge_lake.config.settings import DomainSettings, Settings
        from knowledge_lake.pipeline.process import process_crawled

        _seed_raw_document(session, source.id)

        sentinel_filters = object()
        mock_domain_loader_instance = MagicMock(filters=sentinel_filters)
        mock_from_name = MagicMock(return_value=mock_domain_loader_instance)

        configured_settings = Settings(
            domain=DomainSettings(domain_name="healthcare"),
            _env_file=None,  # type: ignore[call-arg]
        )
        mock_get_settings = MagicMock(return_value=configured_settings)

        mock_parse = MagicMock(return_value=({"artifact_id": "parsed-1"}, object()))
        mock_clean = MagicMock(return_value={"cleaned_doc": object()})
        mock_chunk = MagicMock(return_value=[{"chunk_id": "c1"}])
        mock_embed = MagicMock(return_value=([[0.1]], 1))
        mock_index = MagicMock(return_value=None)

        with (
            patch("knowledge_lake.config.settings.get_settings", mock_get_settings),
            patch(
                "knowledge_lake.domains.loader.DomainLoader.from_name",
                mock_from_name,
            ),
            patch("knowledge_lake.pipeline.parse.parse", mock_parse),
            patch("knowledge_lake.pipeline.clean.clean", mock_clean),
            patch("knowledge_lake.pipeline.chunk.chunk", mock_chunk),
            patch("knowledge_lake.pipeline.embed.embed", mock_embed),
            patch("knowledge_lake.pipeline.index.index", mock_index),
        ):
            result = process_crawled()

        assert result["failed"] == 0
        mock_from_name.assert_called_once_with("healthcare")
        mock_chunk.assert_called_once()
        assert mock_chunk.call_args.kwargs["domain_filters"] is sentinel_filters, (
            "chunk() must receive the resolved DomainLoader.filters as "
            "domain_filters= — proving process_crawled() genuinely resolves "
            "and threads it, not just that a predicate-level unit test passes"
        )

    def test_domain_filters_none_when_no_domain_configured(self, session, source):
        """settings.domain.domain_name left at its default None -> domain_filters
        stays None and DomainLoader.from_name is never called (no regression)."""
        from knowledge_lake.config.settings import Settings
        from knowledge_lake.pipeline.process import process_crawled

        _seed_raw_document(session, source.id)

        mock_from_name = MagicMock()

        default_settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert default_settings.domain.domain_name is None
        mock_get_settings = MagicMock(return_value=default_settings)

        mock_parse = MagicMock(return_value=({"artifact_id": "parsed-1"}, object()))
        mock_clean = MagicMock(return_value={"cleaned_doc": object()})
        mock_chunk = MagicMock(return_value=[{"chunk_id": "c1"}])
        mock_embed = MagicMock(return_value=([[0.1]], 1))
        mock_index = MagicMock(return_value=None)

        with (
            patch("knowledge_lake.config.settings.get_settings", mock_get_settings),
            patch(
                "knowledge_lake.domains.loader.DomainLoader.from_name",
                mock_from_name,
            ),
            patch("knowledge_lake.pipeline.parse.parse", mock_parse),
            patch("knowledge_lake.pipeline.clean.clean", mock_clean),
            patch("knowledge_lake.pipeline.chunk.chunk", mock_chunk),
            patch("knowledge_lake.pipeline.embed.embed", mock_embed),
            patch("knowledge_lake.pipeline.index.index", mock_index),
        ):
            result = process_crawled()

        assert result["failed"] == 0
        mock_from_name.assert_not_called()
        mock_chunk.assert_called_once()
        assert mock_chunk.call_args.kwargs.get("domain_filters") is None
