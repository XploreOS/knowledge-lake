"""Tests for pipeline/tree_search.py — two-stage tree retrieval (RETR-04..08, D-11).

Wave 0 scaffold: knowledge_lake.pipeline.tree_search and
knowledge_lake.plugins.builtin.pageindex_retriever do not exist until Plans
14-03 (retriever builtin) and 14-04 (orchestrator+CLI) ship. The resulting
ImportError at collection time is the correct Wave 0 RED state (mirrors
test_tree_index.py's Wave 0 scaffold from Phase 13).

Fixtures (engine, _patch_engine, session, seeded) are reused verbatim from
test_tree_index.py: in-memory SQLite via StaticPool with
registry.db.get_engine monkeypatched so tree_search()'s own get_session()
calls resolve against the same in-memory database. StorageBackend and
litellm.completion are mocked; no real S3 or LLM egress from this suite.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import MagicMock, patch

import orjson
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.pipeline.tree_search as tree_search_module
import knowledge_lake.registry.db as registry_db
from knowledge_lake.plugins.protocols import Hit, TreeIndex, TreeNode


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    """In-memory SQLite engine, shared connection via StaticPool (mirrors
    test_tree_index.py) so multiple Session() instances opened by separate
    get_session() calls all see the same database.
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
    """Route registry.db.get_session() calls made inside tree_search() to the
    in-memory test engine (mirrors test_tree_index.py)."""
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)


@pytest.fixture()
def session(engine):
    with Session(engine) as sess:
        yield sess


@pytest.fixture()
def seeded(session):
    """Seed a Source -> raw -> parsed artifact chain (mirrors test_tree_index.py)."""
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
        content_hash="abc123",
        storage_uri="s3://b/silver/abc123.md",
    )
    session.commit()
    return {"source_id": source.id, "parsed_artifact_id": parsed.id}


@pytest.fixture()
def hand_tree(seeded) -> TreeIndex:
    """Hand-built 2-level TreeIndex fixture (no S3, no DB) for heuristic scoring
    and _dict_to_tree round-trip tests.

    Titles/summaries are chosen so the fixed query "budget cap" matches §1 and
    §1.1 (both discuss budget/cap terms) but not §2 (unrelated content),
    exercising keyword scoring (D-05).
    """
    child = TreeNode(
        node_id="node_1.1",
        title="Budget Cap Details",
        summary="Explains the budget cap threshold and enforcement.",
        page_start=2,
        page_end=3,
        level=2,
        section_path="§1.1",
        children=[],
    )
    root1 = TreeNode(
        node_id="node_1",
        title="Budget Overview",
        summary="Overview of the budget cap policy.",
        page_start=1,
        page_end=3,
        level=1,
        section_path="§1",
        children=[child],
    )
    root2 = TreeNode(
        node_id="node_2",
        title="Unrelated Topic",
        summary="Discusses something entirely different, no matching terms.",
        page_start=4,
        page_end=5,
        level=1,
        section_path="§2",
        children=[],
    )
    return TreeIndex(
        parsed_artifact_id=seeded["parsed_artifact_id"],
        source_id=seeded["source_id"],
        roots=[root1, root2],
        mode="deterministic",
        schema_version="1",
        content_hash="hand_tree_hash",
    )


def _node_to_dict(node: TreeNode) -> dict:
    """Mirrors tree_index.py:_tree_to_dict (verified against the real
    implementation) — used to build hand_tree_dict without importing
    tree_index.py directly (keeps this fixture independent of Phase 13
    internals)."""
    return {
        "node_id": node.node_id,
        "title": node.title,
        "summary": node.summary,
        "page_start": node.page_start,
        "page_end": node.page_end,
        "level": node.level,
        "section_path": node.section_path,
        "children": [_node_to_dict(c) for c in node.children],
    }


@pytest.fixture()
def hand_tree_dict(hand_tree) -> dict:
    """Serialized dict form of hand_tree, matching tree_index.py's
    _tree_to_dict + tree_dict wrapper shape (D-11): parsed_artifact_id,
    source_id, mode, schema_version, content_hash, roots."""
    return {
        "parsed_artifact_id": hand_tree.parsed_artifact_id,
        "source_id": hand_tree.source_id,
        "mode": hand_tree.mode,
        "schema_version": hand_tree.schema_version,
        "content_hash": hand_tree.content_hash,
        "roots": [_node_to_dict(r) for r in hand_tree.roots],
    }


# ── TestHitContract ───────────────────────────────────────────────────────────


class TestHitContract:
    """Regression guard for the additive citation_source field (D-02)."""

    def test_hit_citation_source_default(self) -> None:
        hit = Hit(id="x", score=1.0)
        assert hit.citation_source == "chunk", (
            f"Hit.citation_source must default to 'chunk' for back-compat "
            f"(chunk search unchanged), got {hit.citation_source!r}"
        )


# ── TestDictToTree ────────────────────────────────────────────────────────────


class TestDictToTree:
    """_dict_to_tree_index round-trip test (D-11)."""

    def test_dict_to_tree_roundtrip(self, hand_tree, hand_tree_dict) -> None:
        rebuilt = tree_search_module._dict_to_tree_index(hand_tree_dict)

        assert rebuilt.parsed_artifact_id == hand_tree.parsed_artifact_id
        assert rebuilt.source_id == hand_tree.source_id
        assert rebuilt.mode == hand_tree.mode
        assert rebuilt.schema_version == hand_tree.schema_version
        assert rebuilt.content_hash == hand_tree.content_hash
        assert len(rebuilt.roots) == len(hand_tree.roots)

        def _assert_node_equal(a: TreeNode, b: TreeNode) -> None:
            assert a.node_id == b.node_id
            assert a.title == b.title
            assert a.summary == b.summary
            assert a.page_start == b.page_start
            assert a.page_end == b.page_end
            assert a.level == b.level
            assert a.section_path == b.section_path
            assert len(a.children) == len(b.children)
            for child_a, child_b in zip(a.children, b.children):
                _assert_node_equal(child_a, child_b)

        for orig_root, rebuilt_root in zip(hand_tree.roots, rebuilt.roots):
            _assert_node_equal(orig_root, rebuilt_root)


# ── TestHeuristicRetriever ────────────────────────────────────────────────────


class TestHeuristicRetriever:
    """Heuristic keyword+DFS traversal tests — zero LLM, deterministic (RETR-05, RETR-08)."""

    def test_heuristic_no_llm(self, hand_tree) -> None:
        from knowledge_lake.plugins.builtin.pageindex_retriever import PageIndexRetriever

        retriever = PageIndexRetriever()
        with patch("litellm.completion") as mock_completion:
            hits1 = retriever.search(hand_tree, "budget cap", mode="heuristic")
            hits2 = retriever.search(hand_tree, "budget cap", mode="heuristic")

        assert mock_completion.call_count == 0, (
            "Heuristic mode must never call litellm.completion (RETR-05)"
        )
        assert [h.id for h in hits1] == [h.id for h in hits2], (
            "Heuristic search must return identically-ordered Hits across "
            "repeated calls (deterministic, no random/clock dependence)"
        )
        assert len(hits1) > 0, "Query 'budget cap' must match at least one node"

        # Empty/whitespace query returns [] (Pitfall 6)
        assert retriever.search(hand_tree, "", mode="heuristic") == []
        assert retriever.search(hand_tree, "   ", mode="heuristic") == []

        # Tree with no roots returns [] (Pitfall 6)
        empty_tree = TreeIndex(
            parsed_artifact_id=hand_tree.parsed_artifact_id,
            source_id=hand_tree.source_id,
            roots=[],
        )
        assert retriever.search(empty_tree, "budget cap", mode="heuristic") == []

    def test_citation_source_tree(self, hand_tree) -> None:
        from knowledge_lake.plugins.builtin.pageindex_retriever import PageIndexRetriever

        retriever = PageIndexRetriever()
        hits = retriever.search(hand_tree, "budget cap", mode="heuristic")

        assert len(hits) > 0
        for hit in hits:
            assert hit.citation_source == "tree", (
                f"Tree search hits must set citation_source='tree', got "
                f"{hit.citation_source!r}"
            )
            for key in (
                "document",
                "node_id",
                "section_path",
                "page_start",
                "page_end",
                "node_path",
            ):
                assert key in hit.payload, f"Hit.payload missing required key {key!r}"
            assert hit.payload["node_path"], (
                "node_path must be the non-empty root->node title chain"
            )

    def test_no_hardcoded_provider_model_ids(self) -> None:
        from knowledge_lake.plugins.builtin import pageindex_retriever

        source = inspect.getsource(pageindex_retriever)

        forbidden = [
            "anthropic/",
            "claude-",
            "amazon.titan",
            "bedrock/",
            "gpt-",
            "text-embedding-",
        ]
        for fragment in forbidden:
            assert fragment not in source, (
                f"Found hardcoded provider ID fragment {fragment!r} in "
                f"pageindex_retriever.py (CLAUDE.md constraint: task-based "
                f"aliases only)"
            )

        assert "openai/" in source, (
            "pageindex_retriever.py must build the LLM-nav model argument as "
            "the f-string form 'openai/' + settings alias (LiteLLM "
            "wire-protocol prefix, never a hardcoded provider ID)"
        )


# ── TestLlmNav ────────────────────────────────────────────────────────────────


class TestLlmNav:
    """LLM-guided navigation tests — budget-gated, never raises (RETR-06, D-06/D-07)."""

    def test_llm_nav_degrades(self, session, hand_tree) -> None:
        from knowledge_lake.config.settings import Settings
        from knowledge_lake.plugins.builtin.pageindex_retriever import PageIndexRetriever
        from knowledge_lake.registry import repo as registry_repo

        retriever = PageIndexRetriever()
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        heuristic_hits = retriever.search(
            hand_tree, "budget cap", mode="heuristic", settings=settings
        )

        # (a) Budget seeded at/over budget_usd -> degrade to heuristic, zero LLM calls.
        registry_repo.record_llm_spend(
            session, scope="tree_search", cost_usd=settings.tree_search.budget_usd
        )
        session.commit()

        with patch("litellm.completion") as mock_completion:
            budget_hits = retriever.search(
                hand_tree, "budget cap", mode="llm", settings=settings
            )

        assert mock_completion.call_count == 0, (
            "LLM-nav must not call litellm.completion once scope='tree_search' "
            "spend is at/over budget_usd (D-06/D-07, budget degrade)"
        )
        assert [h.id for h in budget_hits] == [h.id for h in heuristic_hits], (
            "Budget-exceeded LLM-nav must return the heuristic result"
        )

        # (b) litellm.completion raises -> caught, degrade to heuristic (never raises).
        fresh_settings = Settings(_env_file=None)  # type: ignore[call-arg]
        with patch("litellm.completion", side_effect=RuntimeError("boom")):
            error_hits = retriever.search(
                hand_tree, "budget cap", mode="llm", settings=fresh_settings
            )

        assert [h.id for h in error_hits] == [h.id for h in heuristic_hits], (
            "LLM-nav must catch litellm.completion exceptions and degrade to "
            "the heuristic result (D-06), never raise out of the query path"
        )


# ── TestTwoStageSearch ────────────────────────────────────────────────────────


class TestTwoStageSearch:
    """Two-stage orchestrator tests — shortlist, resolve, parallel-load (RETR-04, RETR-07)."""

    def test_two_stage_shortlist(self, session, seeded, hand_tree_dict) -> None:
        from knowledge_lake.registry import repo as registry_repo

        # A second document so stage-1 grouping/shortlisting is exercised across docs.
        source2 = registry_repo.create_source(session, name="Source 2", source_type="web")
        raw2 = registry_repo.create_raw_artifact(
            session,
            source_id=source2.id,
            content_hash="raw_h2",
            storage_uri="s3://b/raw/raw_h2.pdf",
        )
        parsed2 = registry_repo.create_parsed_artifact(
            session,
            source_id=source2.id,
            parent_artifact_id=raw2.id,
            content_hash="def456",
            storage_uri="s3://b/silver/def456.md",
        )
        session.commit()

        doc_a = seeded["parsed_artifact_id"]
        doc_b = parsed2.id

        chunk_hits = [
            Hit(id="c1", score=0.9, payload={"document": doc_a}),
            Hit(id="c2", score=0.5, payload={"document": doc_a}),
            Hit(id="c3", score=0.8, payload={"document": doc_b}),
            Hit(id="c4", score=0.1, payload={"document": "doc_never_shortlisted"}),
        ]

        fake_artifact = MagicMock()
        fake_artifact.storage_uri = "s3://bucket/tree_index/domain/src/hash.json"

        mock_storage = MagicMock()
        mock_storage.get_object.return_value = orjson.dumps(hand_tree_dict)

        with (
            patch.object(tree_search_module, "search", return_value=chunk_hits) as mock_search,
            patch(
                "knowledge_lake.registry.repo.get_child_artifact_by_type",
                return_value=fake_artifact,
            ) as mock_get_child,
            patch.object(tree_search_module, "StorageBackend", return_value=mock_storage),
        ):
            hits = tree_search_module.tree_search("budget cap", max_docs=2)

        assert mock_search.call_count == 1, "Stage 1 must call search() exactly once"
        assert mock_get_child.call_count <= 2, (
            "Only the shortlisted (max_docs) documents are resolved to a "
            "tree_index artifact — max score per doc, top max_docs (D-08)"
        )
        returned_docs = {h.payload.get("document") for h in hits}
        assert "doc_never_shortlisted" not in returned_docs, (
            "Documents outside the top max_docs shortlist must never produce "
            "tree hits"
        )

    def test_parallel_load_and_skip(self, session, seeded, hand_tree_dict) -> None:
        from knowledge_lake.config.settings import Settings
        from knowledge_lake.registry import repo as registry_repo

        source2 = registry_repo.create_source(session, name="Source 3", source_type="web")
        raw2 = registry_repo.create_raw_artifact(
            session,
            source_id=source2.id,
            content_hash="raw_h3",
            storage_uri="s3://b/raw/raw_h3.pdf",
        )
        parsed2 = registry_repo.create_parsed_artifact(
            session,
            source_id=source2.id,
            parent_artifact_id=raw2.id,
            content_hash="ghi789",
            storage_uri="s3://b/silver/ghi789.md",
        )
        session.commit()

        doc_a = seeded["parsed_artifact_id"]
        doc_b = parsed2.id

        chunk_hits = [
            Hit(id="c1", score=0.9, payload={"document": doc_a}),
            Hit(id="c2", score=0.8, payload={"document": doc_b}),
        ]

        fake_artifact = MagicMock()
        fake_artifact.storage_uri = "s3://bucket/tree_index/domain/src/hash.json"

        def _get_child_side_effect(_session, parsed_id, _artifact_type):
            # doc_b has no tree_index artifact -> skipped gracefully (D-09).
            return fake_artifact if parsed_id == doc_a else None

        mock_storage = MagicMock()
        mock_storage.get_object.return_value = orjson.dumps(hand_tree_dict)

        settings = Settings(_env_file=None)  # type: ignore[call-arg]

        with (
            patch.object(tree_search_module, "search", return_value=chunk_hits),
            patch(
                "knowledge_lake.registry.repo.get_child_artifact_by_type",
                side_effect=_get_child_side_effect,
            ),
            patch.object(tree_search_module, "StorageBackend", return_value=mock_storage),
            patch.object(asyncio, "Semaphore", wraps=asyncio.Semaphore) as mock_semaphore,
        ):
            hits = tree_search_module.tree_search(
                "budget cap", max_docs=2, settings=settings
            )

        assert len(hits) > 0, (
            "The remaining shortlisted document (doc_a) must still return "
            "Hits after doc_b is skipped for having no tree_index artifact"
        )
        assert mock_semaphore.call_count >= 1, (
            "Parallel tree loading must construct an asyncio.Semaphore "
            "bounded by settings.tree_search.concurrency (RETR-07)"
        )
        mock_semaphore.assert_any_call(settings.tree_search.concurrency)
