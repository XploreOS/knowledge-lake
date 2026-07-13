"""Tests for pipeline/tree_index.py — deterministic and LLM-mode tree indexing (TREE-01..04).

Uses an in-memory-SQLite-backed session (mirrors test_enrich.py's engine/session
fixtures) with knowledge_lake.registry.db.get_engine monkeypatched so
tree_index()'s own get_session() calls resolve against the same in-memory
database.  StorageBackend is patched at the pipeline.tree_index module level so
no real S3 client is constructed.  litellm.completion is mocked via
unittest.mock.patch (mirrors test_enrich.py's mocking style).

Tests will fail with ImportError until Plan 13-04 ships — that is the correct
RED state for Wave 0.
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.pipeline.tree_index as tree_index_module
import knowledge_lake.registry.db as registry_db
from knowledge_lake.config.settings import Settings
from knowledge_lake.plugins.protocols import ParsedDoc, Section


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    """In-memory SQLite engine, shared connection via StaticPool so multiple
    Session() instances (opened by separate get_session() calls) all see the
    same database.
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
    """Route registry.db.get_session() at the tree_index() call sites to
    the in-memory test engine.
    """
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)


@pytest.fixture()
def session(engine):
    with Session(engine) as sess:
        yield sess


@pytest.fixture()
def seeded(session):
    """Seed a Source -> raw -> parsed artifact chain.

    Tree index parents off parsed_document (D-07), so we only need
    Source -> raw -> parsed (no cleaned artifact needed here).
    """
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
def fake_storage(monkeypatch):
    """Patch StorageBackend used inside pipeline.tree_index to capture calls."""
    fake = MagicMock()
    fake.put_object = MagicMock()
    fake.get_object.return_value = b""
    fake.object_uri.side_effect = lambda key: f"s3://bucket/{key}"
    monkeypatch.setattr(tree_index_module, "StorageBackend", lambda *_a, **_k: fake)
    return fake


@pytest.fixture()
def multi_section_doc() -> ParsedDoc:
    """Multi-section ParsedDoc that exercises nesting, page_end derivation,
    and table leaf handling.

    Sections:
      §1     Introduction       page=1   (parent of §1.1)
      §1.1   Background         page=2   (child of §1)
      §2     Results            page=4   (top-level leaf)
      §2.1   Table 1            page=5   is_table=True (leaf under §2)
    """
    return ParsedDoc(
        text="Test document text",
        sections=[
            Section(heading="Introduction", section_path="§1", page=1),
            Section(heading="Background", section_path="§1.1", page=2),
            Section(heading="Results", section_path="§2", page=4),
            Section(heading="Table 1", section_path="§2.1", page=5, is_table=True),
        ],
        metadata={"title": "Test Doc", "page_count": 6},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mock_llm_response(summary: str = "LLM-generated summary"):
    """Build a mock litellm.completion response matching tree_index expectations."""
    resp = MagicMock()
    resp.choices = [
        MagicMock(
            message=MagicMock(content=json.dumps({"summary": summary}))
        )
    ]
    resp.usage = MagicMock(total_cost=0.001, prompt_tokens=50, completion_tokens=20)
    return resp


def _make_settings(**overrides):
    """Return a test Settings instance with env file disabled."""
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


# ── TestDeterministicTree ─────────────────────────────────────────────────────


class TestDeterministicTree:
    """Tests for mode='deterministic' tree generation (TREE-01, TREE-02, TREE-03)."""

    def test_deterministic_tree_from_sections(
        self, engine, seeded, fake_storage, multi_section_doc
    ) -> None:
        """Deterministic tree from multi-section ParsedDoc produces correctly nested
        TreeIndex with proper page ranges, levels, and table metadata.

        Verifies TREE-01: tree artifact registered with artifact_type='tree_index'
        and storage_uri set; node hierarchy and fields correct.
        """
        from knowledge_lake.pipeline.tree_index import tree_index
        from knowledge_lake.plugins.protocols import TreeIndex, TreeNode

        settings = _make_settings()
        result = tree_index(
            seeded["parsed_artifact_id"],
            seeded["source_id"],
            multi_section_doc,
            settings=settings,
        )

        assert result["status"] in ("indexed", "tree_indexed", "complete"), (
            f"Expected success status, got {result['status']!r}"
        )
        assert result.get("artifact_id") is not None, "artifact_id must be set on success"

        # Retrieve the produced TreeIndex from the result
        tree: TreeIndex = result["tree"]
        assert isinstance(tree, TreeIndex), f"result['tree'] must be a TreeIndex, got {type(tree)}"

        # §1 Introduction: level=1, page_start=1, page_end=3 (next top-level at page 4)
        intro_nodes = [n for n in tree.roots if n.section_path == "§1"]
        assert len(intro_nodes) == 1, "§1 must appear as a root node"
        intro = intro_nodes[0]
        assert intro.level == 1, f"§1 level must be 1, got {intro.level}"
        assert intro.page_start == 1, f"§1 page_start must be 1, got {intro.page_start}"
        assert intro.page_end == 3, (
            f"§1 page_end must be 3 (next top-level §2 starts at 4), got {intro.page_end}"
        )
        assert intro.summary == intro.title == "Introduction", (
            f"Deterministic summary must equal heading, got title={intro.title!r}, "
            f"summary={intro.summary!r}"
        )

        # §1.1 Background: level=2, child of §1
        assert len(intro.children) >= 1, "§1 must have at least one child (§1.1)"
        bg_nodes = [c for c in intro.children if c.section_path == "§1.1"]
        assert len(bg_nodes) == 1, "§1.1 must be a child of §1"
        bg = bg_nodes[0]
        assert bg.level == 2, f"§1.1 level must be 2, got {bg.level}"
        assert bg.page_start == 2, f"§1.1 page_start must be 2, got {bg.page_start}"
        assert bg.page_end == 3, (
            f"§1.1 page_end must be 3 (next section at page 4), got {bg.page_end}"
        )

        # §2 Results: top-level root, is_table leaf child
        results_nodes = [n for n in tree.roots if n.section_path == "§2"]
        assert len(results_nodes) == 1, "§2 must be a top-level root node"
        results = results_nodes[0]
        assert results.level == 1, f"§2 level must be 1, got {results.level}"

        # §2.1 Table 1: leaf with is_table metadata
        table_nodes = [c for c in results.children if c.section_path == "§2.1"]
        assert len(table_nodes) == 1, "§2.1 must be a child of §2"
        table_node = table_nodes[0]
        assert len(table_node.children) == 0, "Table nodes must be leaves (no children)"

        # Artifact persisted in registry
        from knowledge_lake.registry import repo as registry_repo
        with Session(engine) as check:
            artifact = registry_repo.get_artifact(check, result["artifact_id"])
            assert artifact is not None
            assert artifact.artifact_type == "tree_index"
            assert artifact.storage_uri is not None and artifact.storage_uri != ""

    def test_tree_storage_key(
        self, engine, seeded, fake_storage, multi_section_doc
    ) -> None:
        """put_object is called with key matching 'tree_index/{domain}/{source_id}/{hash}.json'
        and tags include domain, source_name, format='json', artifact_type='tree_index'.

        Verifies TREE-01 storage layout (D-07).
        """
        from knowledge_lake.pipeline.tree_index import tree_index

        settings = _make_settings()
        result = tree_index(
            seeded["parsed_artifact_id"],
            seeded["source_id"],
            multi_section_doc,
            settings=settings,
        )

        assert result.get("artifact_id") is not None, "Expected successful indexing"
        assert fake_storage.put_object.call_count >= 1, "put_object must be called once"

        call_args = fake_storage.put_object.call_args
        key = call_args.args[0] if call_args.args else call_args.kwargs.get("key", "")
        tags = call_args.kwargs.get("tags", {}) or (call_args.args[2] if len(call_args.args) > 2 else {})

        # Key pattern: tree_index/{domain}/{source_id}/{hash}.json
        assert key.startswith("tree_index/"), (
            f"Storage key must start with 'tree_index/', got {key!r}"
        )
        assert key.endswith(".json"), f"Storage key must end with '.json', got {key!r}"
        parts = key.split("/")
        assert len(parts) >= 4, f"Storage key must have at least 4 parts, got {key!r}"
        assert seeded["source_id"] in key, (
            f"Storage key must contain source_id, got {key!r}"
        )

        # Tags
        assert tags.get("format") == "json", f"tags['format'] must be 'json', got {tags!r}"
        assert tags.get("artifact_type") == "tree_index", (
            f"tags['artifact_type'] must be 'tree_index', got {tags!r}"
        )
        assert "domain" in tags, f"tags must include 'domain', got {tags!r}"
        assert "source_name" in tags, f"tags must include 'source_name', got {tags!r}"

    def test_content_hash_noop(
        self, engine, seeded, fake_storage, multi_section_doc
    ) -> None:
        """Second call with identical parsed_artifact_id + mode returns cached=True;
        put_object call count does not increase; no LLM call in LLM mode second run.

        Verifies TREE-02 content-hash dedup (D-06).
        """
        from knowledge_lake.pipeline.tree_index import tree_index

        settings = _make_settings()
        mock_llm = MagicMock(return_value=_mock_llm_response())
        with patch("litellm.completion", mock_llm):
            first = tree_index(
                seeded["parsed_artifact_id"],
                seeded["source_id"],
                multi_section_doc,
                settings=settings,
            )
            second = tree_index(
                seeded["parsed_artifact_id"],
                seeded["source_id"],
                multi_section_doc,
                settings=settings,
            )

        assert first.get("artifact_id") is not None, "First call must succeed"
        assert second.get("cached") is True, (
            f"Second call must be cached, got {second!r}"
        )
        assert second.get("artifact_id") == first.get("artifact_id"), (
            "Cached result must return same artifact_id"
        )
        # put_object must not have been called again on the second run
        put_count_after_second = fake_storage.put_object.call_count
        assert put_count_after_second == 1, (
            f"put_object must only be called once (first run), got {put_count_after_second}"
        )
        # LLM must not have been called (deterministic mode)
        assert mock_llm.call_count == 0, (
            "litellm.completion must not be called in deterministic mode"
        )

    def test_node_fields_and_fallback(
        self, engine, seeded, fake_storage
    ) -> None:
        """Every node has page_start, page_end, level, section_path populated.
        Deterministic summary == title == section heading.
        ParsedDoc with empty sections list produces a single root node.

        Verifies TREE-03 (D-03).
        """
        from knowledge_lake.pipeline.tree_index import tree_index
        from knowledge_lake.plugins.protocols import TreeIndex

        settings = _make_settings()

        # Test with empty sections list — fallback to single root
        empty_doc = ParsedDoc(
            text="A document with no section structure.",
            sections=[],
            metadata={"title": "Flat Doc", "page_count": 3},
        )
        result = tree_index(
            seeded["parsed_artifact_id"],
            seeded["source_id"],
            empty_doc,
            settings=settings,
        )
        assert result.get("artifact_id") is not None, "Empty-sections doc must still produce artifact"
        tree: TreeIndex = result["tree"]
        assert len(tree.roots) == 1, (
            f"Empty sections must produce exactly 1 root node, got {len(tree.roots)}"
        )
        root = tree.roots[0]
        assert root.page_start is not None, "Root node must have page_start"
        assert root.page_end is not None, "Root node must have page_end"
        assert root.level is not None, "Root node must have level"
        assert root.section_path is not None and root.section_path != "", (
            "Root node must have section_path"
        )

        # Verify deterministic summary == heading for a doc with sections
        # We need to clear the cache by using a distinct parsed artifact for this check
        from knowledge_lake.registry import repo as registry_repo
        with Session(engine) as s2:
            source = registry_repo.get_source(s2, seeded["source_id"])
            raw2 = registry_repo.create_raw_artifact(
                s2, source_id=seeded["source_id"],
                content_hash="raw_h2", storage_uri="s3://b/raw/r2.pdf"
            )
            parsed2 = registry_repo.create_parsed_artifact(
                s2, source_id=seeded["source_id"], parent_artifact_id=raw2.id,
                content_hash="def456", storage_uri="s3://b/silver/def456.md",
            )
            s2.commit()
            parsed2_id = parsed2.id

        single_section_doc = ParsedDoc(
            text="Administrative safeguards overview.",
            sections=[Section(heading="Administrative Safeguards", section_path="§1", page=1)],
            metadata={"title": "Single Section Doc", "page_count": 2},
        )
        result2 = tree_index(
            parsed2_id,
            seeded["source_id"],
            single_section_doc,
            settings=settings,
        )
        assert result2.get("artifact_id") is not None
        tree2: TreeIndex = result2["tree"]
        assert len(tree2.roots) >= 1
        node = tree2.roots[0]
        assert node.title == "Administrative Safeguards", (
            f"Deterministic title must equal heading, got {node.title!r}"
        )
        assert node.summary == "Administrative Safeguards", (
            f"Deterministic summary must equal heading, got {node.summary!r}"
        )


# ── TestLlmMode ───────────────────────────────────────────────────────────────


class TestLlmMode:
    """Tests for mode='llm' tree generation (TREE-04)."""

    def test_llm_mode_budget_cap(
        self, engine, seeded, fake_storage, multi_section_doc
    ) -> None:
        """After seeding LLM spend to fill the budget, tree_index(mode='llm') returns
        {'status': 'skipped_budget_exceeded'} with no artifact written and
        litellm.completion call count == 0.

        Happy-path LLM mode with mock litellm.completion returns populated summaries,
        record_llm_spend is called once, result contains cost_usd.

        Verifies TREE-04 (D-08, D-09).
        """
        from knowledge_lake.pipeline.tree_index import tree_index
        from knowledge_lake.registry import repo as registry_repo

        settings = _make_settings()
        budget_usd = settings.tree.budget_usd  # type: ignore[attr-defined]

        # --- Happy path: LLM mode with mocked completion ---
        # Use a distinct parsed artifact to avoid cache collision with deterministic tests
        with Session(engine) as s2:
            raw2 = registry_repo.create_raw_artifact(
                s2, source_id=seeded["source_id"],
                content_hash="raw_llm1", storage_uri="s3://b/raw/rllm1.pdf"
            )
            parsed_llm = registry_repo.create_parsed_artifact(
                s2, source_id=seeded["source_id"], parent_artifact_id=raw2.id,
                content_hash="llmhash1", storage_uri="s3://b/silver/llmhash1.md",
            )
            s2.commit()
            parsed_llm_id = parsed_llm.id

        llm_settings = Settings(  # type: ignore[call-arg]
            _env_file=None,
        )
        # Force mode=llm via tree settings override if needed; the test relies on
        # tree_index accepting a mode parameter directly or via settings
        mock_llm = MagicMock(return_value=_mock_llm_response("Summarized by LLM"))
        with patch("litellm.completion", mock_llm):
            happy_result = tree_index(
                parsed_llm_id,
                seeded["source_id"],
                multi_section_doc,
                settings=llm_settings,
                mode="llm",
            )

        assert happy_result.get("artifact_id") is not None, (
            f"LLM mode happy path must produce artifact, got {happy_result!r}"
        )
        assert mock_llm.call_count >= 1, "litellm.completion must be called in LLM mode"
        assert "cost_usd" in happy_result, "LLM mode result must include cost_usd"

        with Session(engine) as check:
            spend_after = registry_repo.get_llm_spend(check, scope="global")
        assert spend_after > 0, "record_llm_spend must have been called after LLM mode"

        # --- Budget-exceeded path ---
        # Use yet another distinct artifact to avoid cache hit from happy-path run
        with Session(engine) as s3:
            raw3 = registry_repo.create_raw_artifact(
                s3, source_id=seeded["source_id"],
                content_hash="raw_llm2", storage_uri="s3://b/raw/rllm2.pdf"
            )
            parsed_budget = registry_repo.create_parsed_artifact(
                s3, source_id=seeded["source_id"], parent_artifact_id=raw3.id,
                content_hash="llmhash2", storage_uri="s3://b/silver/llmhash2.md",
            )
            # Seed spend to the full budget amount
            registry_repo.record_llm_spend(s3, "global", budget_usd)
            s3.commit()
            parsed_budget_id = parsed_budget.id

        mock_llm2 = MagicMock(return_value=_mock_llm_response())
        put_count_before = fake_storage.put_object.call_count
        with patch("litellm.completion", mock_llm2):
            budget_result = tree_index(
                parsed_budget_id,
                seeded["source_id"],
                multi_section_doc,
                settings=_make_settings(),
                mode="llm",
            )

        assert budget_result.get("status") == "skipped_budget_exceeded", (
            f"Budget-exceeded must return status='skipped_budget_exceeded', "
            f"got {budget_result!r}"
        )
        assert budget_result.get("artifact_id") is None, (
            "Budget-exceeded must not write an artifact"
        )
        assert mock_llm2.call_count == 0, (
            "litellm.completion must NOT be called when budget is exceeded"
        )
        assert fake_storage.put_object.call_count == put_count_before, (
            "put_object must NOT be called when budget is exceeded"
        )

    def test_no_hardcoded_provider_model_ids(
        self, engine, seeded, fake_storage, multi_section_doc
    ) -> None:
        """pipeline/tree_index.py must never contain a hardcoded provider model ID
        literal. The 'openai/' prefix is a LiteLLM wire-protocol prefix, not a
        provider ID — it must only appear as 'openai/{model_alias}' where model_alias
        is a task alias like 'cheap_model'.

        Verifies TREE-04 (D-08, CLAUDE.md constraint).
        """
        from knowledge_lake.pipeline import tree_index as tree_index_mod_ref

        source = inspect.getsource(tree_index_mod_ref)

        # Forbidden hardcoded provider model ID fragments
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
                f"Found hardcoded provider ID fragment {fragment!r} in tree_index.py"
            )

        # Verify that when LLM mode is used, the model call uses the task alias
        # (openai/ prefix + cheap_model alias — never a provider ID)
        from knowledge_lake.registry import repo as registry_repo
        with Session(engine) as s4:
            raw4 = registry_repo.create_raw_artifact(
                s4, source_id=seeded["source_id"],
                content_hash="raw_model_check", storage_uri="s3://b/raw/rm.pdf"
            )
            parsed_mc = registry_repo.create_parsed_artifact(
                s4, source_id=seeded["source_id"], parent_artifact_id=raw4.id,
                content_hash="model_check_hash", storage_uri="s3://b/silver/mc.md",
            )
            s4.commit()
            parsed_mc_id = parsed_mc.id

        mock_llm = MagicMock(return_value=_mock_llm_response("alias-check summary"))
        with patch("litellm.completion", mock_llm):
            from knowledge_lake.pipeline.tree_index import tree_index
            result = tree_index(
                parsed_mc_id,
                seeded["source_id"],
                multi_section_doc,
                settings=_make_settings(),
                mode="llm",
            )

        if mock_llm.call_count > 0:
            # If LLM was called, verify model alias is correct
            call_kwargs = mock_llm.call_args.kwargs
            model_used = call_kwargs.get("model", "")
            assert model_used == "openai/cheap_model", (
                f"LLM call must use model='openai/cheap_model' (openai/= wire protocol, "
                f"cheap_model = task alias per CLAUDE.md constraint), got {model_used!r}"
            )
