"""Unit tests for the built-in plugin implementations (D-11, D-13).

Tests:
 - SentenceTransformerEmbedder ('local'): embed short strings, dim=384, shape correct
 - LiteLLMEmbedder ('litellm'): structurally satisfies EmbedderPlugin; routes via LiteLLM
 - DoclingParser ('docling'): structurally satisfies ParserPlugin; can_parse PDF
 - QdrantVectorStore ('qdrant'): structurally satisfies VectorStorePlugin
 - Each built-in satisfies its Protocol via runtime isinstance
 - Entry-point registrations exist in pyproject.toml (three groups, five names)

Network/model-heavy paths (Docling PDF parsing, Qdrant live ops) are integration
tests or are lightly exercised with mocks where a live service is required.
"""
from __future__ import annotations

import importlib.metadata
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from knowledge_lake.plugins.protocols import (
    EmbedderPlugin,
    Hit,
    ParsedDoc,
    ParserPlugin,
    VectorPoint,
    VectorStorePlugin,
)


# ---------------------------------------------------------------------------
# Entry-point registration tests
# ---------------------------------------------------------------------------


class TestEntryPointRegistrations:
    """Verify that built-ins are registered in the correct groups with correct names."""

    def _get_ep_names(self, group: str) -> set[str]:
        eps = importlib.metadata.entry_points(group=group)
        return {ep.name for ep in eps}

    def test_parsers_group_has_docling(self) -> None:
        names = self._get_ep_names("knowledge_lake.parsers")
        assert "docling" in names, f"Expected 'docling' in parsers, got: {names}"

    def test_embedders_group_has_local(self) -> None:
        names = self._get_ep_names("knowledge_lake.embedders")
        assert "local" in names, f"Expected 'local' in embedders, got: {names}"

    def test_embedders_group_has_litellm(self) -> None:
        names = self._get_ep_names("knowledge_lake.embedders")
        assert "litellm" in names, f"Expected 'litellm' in embedders, got: {names}"

    def test_vectorstores_group_has_qdrant(self) -> None:
        names = self._get_ep_names("knowledge_lake.vectorstores")
        assert "qdrant" in names, f"Expected 'qdrant' in vectorstores, got: {names}"


# ---------------------------------------------------------------------------
# SentenceTransformerEmbedder tests (local, zero AWS creds, D-13)
# ---------------------------------------------------------------------------


class TestSentenceTransformerEmbedder:
    """Tests for the default local sentence-transformers embedder."""

    @pytest.fixture
    def embedder(self) -> Any:
        from knowledge_lake.plugins.builtin.st_embedder import (
            SentenceTransformerEmbedder,
        )
        return SentenceTransformerEmbedder()

    def test_satisfies_embedder_protocol(self, embedder: Any) -> None:
        assert isinstance(embedder, EmbedderPlugin)

    def test_name_is_local(self, embedder: Any) -> None:
        assert embedder.name == "local"

    def test_dim_is_384(self, embedder: Any) -> None:
        assert embedder.dim == 384

    def test_embed_returns_list_of_vectors(self, embedder: Any) -> None:
        vecs = embedder.embed(["hello world", "foo bar"])
        assert isinstance(vecs, list)
        assert len(vecs) == 2

    def test_embed_vector_has_correct_dim(self, embedder: Any) -> None:
        vecs = embedder.embed(["test"])
        assert len(vecs[0]) == embedder.dim

    def test_embed_returns_floats(self, embedder: Any) -> None:
        vecs = embedder.embed(["check types"])
        assert all(isinstance(v, float) for v in vecs[0])

    def test_embed_single_string(self, embedder: Any) -> None:
        vecs = embedder.embed(["single"])
        assert len(vecs) == 1
        assert len(vecs[0]) == embedder.dim

    def test_embed_batch(self, embedder: Any) -> None:
        texts = [f"sentence {i}" for i in range(5)]
        vecs = embedder.embed(texts)
        assert len(vecs) == 5
        for v in vecs:
            assert len(v) == embedder.dim


# ---------------------------------------------------------------------------
# LiteLLMEmbedder tests (litellm switch — gateway via embedding_model alias)
# ---------------------------------------------------------------------------


class TestLiteLLMEmbedder:
    """Tests for the LiteLLM gateway embedder.

    The gateway path requires a live LiteLLM proxy and Bedrock credentials so
    actual embedding calls are mocked here. Structural and config-constraint
    checks are validated without network access.
    """

    @pytest.fixture
    def embedder(self) -> Any:
        from knowledge_lake.plugins.builtin.st_embedder import LiteLLMEmbedder
        return LiteLLMEmbedder()

    def test_satisfies_embedder_protocol(self, embedder: Any) -> None:
        assert isinstance(embedder, EmbedderPlugin)

    def test_name_is_litellm(self, embedder: Any) -> None:
        assert embedder.name == "litellm"

    def test_dim_is_1536(self, embedder: Any) -> None:
        # Amazon Titan Text Embeddings V2 via Bedrock outputs 1536-dim by default
        assert embedder.dim == 1536

    def test_no_hardcoded_provider_model_ids_in_source(self) -> None:
        """Verify the LiteLLMEmbedder source file contains no hardcoded provider model IDs."""
        import inspect
        from knowledge_lake.plugins.builtin import st_embedder
        source = inspect.getsource(st_embedder)
        forbidden_patterns = [
            "anthropic/",
            "claude-",
            "amazon.titan",
            "bedrock/",
            "gpt-",
            "text-embedding-",  # OpenAI
        ]
        for pattern in forbidden_patterns:
            assert pattern not in source, (
                f"Found hardcoded provider model ID pattern {pattern!r} "
                f"in st_embedder.py — use task aliases only (CLAUDE.md constraint)"
            )

    def test_uses_embedding_model_alias_not_hardcoded_id(self, embedder: Any) -> None:
        """The LiteLLM call must use the task alias 'embedding_model', not a provider ID."""
        # Mock litellm.embedding to capture what model name is used
        fake_response = MagicMock()
        fake_response.data = [MagicMock(embedding=[0.1] * 1536)]
        with patch("litellm.embedding", return_value=fake_response) as mock_emb:
            result = embedder.embed(["test text"])
        call_kwargs = mock_emb.call_args
        model_used = call_kwargs[1].get("model") or call_kwargs[0][0]
        assert model_used == "openai/embedding_model", (
            f"LiteLLMEmbedder must pass model='openai/embedding_model' "
            f"(openai/ = wire protocol, embedding_model = task alias), got {model_used!r}"
        )

    def test_embed_returns_correct_dim_via_mock(self, embedder: Any) -> None:
        """Verify embed() returns dim-correct vectors from the mocked LiteLLM response."""
        fake_response = MagicMock()
        fake_response.data = [MagicMock(embedding=[0.5] * 1536)]
        with patch("litellm.embedding", return_value=fake_response):
            vecs = embedder.embed(["hello"])
        assert len(vecs) == 1
        assert len(vecs[0]) == 1536


# ---------------------------------------------------------------------------
# DoclingParser tests
# ---------------------------------------------------------------------------


class TestDoclingParser:
    """Tests for the Docling-backed parser.

    Full PDF parsing is heavy (model loading), so structural tests use isinstance
    checks and can_parse validation. Actual PDF parsing is in integration tests.
    """

    @pytest.fixture
    def parser(self) -> Any:
        from knowledge_lake.plugins.builtin.docling_parser import DoclingParser
        return DoclingParser()

    def test_satisfies_parser_protocol(self, parser: Any) -> None:
        assert isinstance(parser, ParserPlugin)

    def test_can_parse_pdf(self, parser: Any) -> None:
        assert parser.can_parse("application/pdf") is True

    def test_cannot_parse_unknown_type(self, parser: Any) -> None:
        assert parser.can_parse("application/unknown") is False

    def test_can_parse_html_phase3(self, parser: Any) -> None:
        # Phase 3 extends DoclingParser to support HTML/DOCX/MD/CSV/XLSX (PARSE-01)
        assert parser.can_parse("text/html") is True


# ---------------------------------------------------------------------------
# QdrantVectorStore tests
# ---------------------------------------------------------------------------


class TestQdrantVectorStore:
    """Tests for the Qdrant vector store implementation.

    Qdrant requires a live server for actual operations. Structural tests verify
    Protocol conformance. Network-dependent paths use mocks.
    """

    @pytest.fixture
    def store(self) -> Any:
        from knowledge_lake.plugins.builtin.qdrant_store import QdrantVectorStore
        return QdrantVectorStore()

    def test_satisfies_vectorstore_protocol(self, store: Any) -> None:
        assert isinstance(store, VectorStorePlugin)

    def test_ensure_collection_calls_qdrant_client(self, store: Any) -> None:
        mock_client = MagicMock()
        mock_client.collection_exists.return_value = False
        store._client = mock_client
        store.ensure_collection("test_col", dim=384)
        mock_client.create_collection.assert_called_once()
        call_args = mock_client.create_collection.call_args
        # create_collection is called with keyword args
        collection_name = call_args.kwargs.get("collection_name")
        assert collection_name == "test_col", (
            f"Expected collection_name='test_col', got kwargs={call_args.kwargs}"
        )

    def test_ensure_collection_is_idempotent(self, store: Any) -> None:
        mock_client = MagicMock()
        mock_client.collection_exists.return_value = True  # already exists
        store._client = mock_client
        store.ensure_collection("existing_col", dim=384)
        mock_client.create_collection.assert_not_called()

    def test_upsert_calls_qdrant_upsert(self, store: Any) -> None:
        mock_client = MagicMock()
        store._client = mock_client
        points = [
            VectorPoint(
                id="chk_001",
                vector=[0.1] * 384,
                payload={
                    "document": "doc_001",
                    "section_path": "§1",
                    "page": 1,
                    "chunk_id": "chk_001",
                },
            )
        ]
        store.upsert("test_col", points)
        mock_client.upsert.assert_called_once()

    def test_upsert_payload_carries_citation_fields(self, store: Any) -> None:
        """Verify citation fields are preserved in the qdrant point payload (D-07)."""
        from qdrant_client.models import PointStruct

        captured_points: list[Any] = []

        def capture_upsert(collection_name: str, points: Any, **kwargs: Any) -> None:
            captured_points.extend(points)

        mock_client = MagicMock()
        mock_client.upsert.side_effect = capture_upsert
        store._client = mock_client

        vp = VectorPoint(
            id="chk_abc",
            vector=[0.2] * 384,
            payload={
                "document": "doc_xyz",
                "section_path": "§3.2 Administrative Safeguards",
                "page": 12,
                "chunk_id": "chk_abc",
                "extra_field": "allowed",
            },
        )
        store.upsert("col", [vp])

        assert len(captured_points) == 1
        point = captured_points[0]
        assert isinstance(point, PointStruct)
        payload = point.payload
        assert payload["document"] == "doc_xyz"
        assert payload["section_path"] == "§3.2 Administrative Safeguards"
        assert payload["page"] == 12
        assert payload["chunk_id"] == "chk_abc"

    def test_search_returns_hits(self, store: Any) -> None:
        from qdrant_client.models import ScoredPoint

        mock_client = MagicMock()
        mock_scored = ScoredPoint(
            id="chk_001",
            score=0.91,
            version=1,
            payload={"document": "doc_001", "section_path": "§1", "page": 1, "chunk_id": "chk_001"},
            vector=None,
        )
        mock_client.query_points.return_value = MagicMock(points=[mock_scored])
        store._client = mock_client

        hits = store.search("col", [0.1] * 384, top_k=5)
        assert len(hits) == 1
        h = hits[0]
        assert isinstance(h, Hit)
        assert h.score == pytest.approx(0.91)
        assert h.payload["document"] == "doc_001"

    def test_search_returns_empty_when_no_results(self, store: Any) -> None:
        mock_client = MagicMock()
        mock_client.query_points.return_value = MagicMock(points=[])
        store._client = mock_client
        hits = store.search("col", [0.0] * 384, top_k=5)
        assert hits == []
