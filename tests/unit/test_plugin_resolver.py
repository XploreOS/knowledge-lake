"""Unit tests for the plugin protocol system and config-keyed resolver (FOUND-08).

These tests prove:
 - Protocols are runtime_checkable and match built-ins structurally
 - resolve(group, name) loads via entry points and instantiates
 - An unregistered name raises a clear LookupError naming group + name
 - A dummy plugin registered in a group is returned when its name is requested,
   proving swap-by-name without any resolver code change
 - get_embedder/get_parser/get_vectorstore read config swap keys from Settings
"""
from __future__ import annotations

import sys
from importlib.metadata import EntryPoint
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from knowledge_lake.config.settings import Settings
from knowledge_lake.plugins.protocols import (
    EmbedderPlugin,
    Hit,
    ParsedDoc,
    ParserPlugin,
    VectorPoint,
    VectorStorePlugin,
)
from knowledge_lake.plugins.resolver import (
    get_embedder,
    get_parser,
    get_vectorstore,
    resolve,
)


# ---------------------------------------------------------------------------
# Dummy implementations used as stand-ins in resolver tests
# ---------------------------------------------------------------------------


class DummyEmbedder:
    name = "dummy"
    dim = 4

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dim for _ in texts]


class DummyParser:
    def can_parse(self, mime_type: str) -> bool:
        return mime_type == "text/plain"

    def parse(self, raw: bytes, mime_type: str) -> ParsedDoc:
        return ParsedDoc(
            text=raw.decode("utf-8", errors="replace"),
            sections=[],
        )


class DummyStore:
    def ensure_collection(
        self, name: str, dim: int, distance: str = "Cosine"
    ) -> None:
        pass

    def ensure_aliased_collection(
        self, alias: str, dim: int, distance: str = "Cosine"
    ) -> tuple[str, bool]:
        return (alias, False)

    def reindex(self, alias: str, dim: int, upsert_fn, distance: str = "Cosine") -> dict:
        return {"new_physical": alias, "old_physical": None}

    def copy_all_points(self, source: str, dest: str, batch_size: int = 256) -> int:
        return 0

    def get_collection_dim(self, alias: str) -> int:
        return 0

    def upsert(self, collection: str, points: list[VectorPoint]) -> None:
        pass

    def search(
        self, collection: str, query: list[float], top_k: int, query_filter=None
    ) -> list[Hit]:
        return []

    def assert_server_supports_hybrid(self) -> None:
        pass

    def reembed_all_points(
        self, source: str, dest: str, sparse_doc_fn, batch_size: int = 256
    ) -> tuple[int, int]:
        return 0, 0

    def refresh_all_points_payload(
        self, source: str, dest: str, payload_resolve_fn, batch_size: int = 256
    ) -> int:
        return 0


# ---------------------------------------------------------------------------
# Tests: Protocols are runtime_checkable
# ---------------------------------------------------------------------------


class TestProtocolStructure:
    def test_embedder_protocol_is_runtime_checkable(self) -> None:
        e = DummyEmbedder()
        assert isinstance(e, EmbedderPlugin)

    def test_parser_protocol_is_runtime_checkable(self) -> None:
        p = DummyParser()
        assert isinstance(p, ParserPlugin)

    def test_vectorstore_protocol_is_runtime_checkable(self) -> None:
        s = DummyStore()
        assert isinstance(s, VectorStorePlugin)

    def test_parsed_doc_dataclass(self) -> None:
        doc = ParsedDoc(text="hello", sections=[])
        assert doc.text == "hello"
        assert doc.sections == []

    def test_vector_point_dataclass(self) -> None:
        vp = VectorPoint(
            id="chk_001",
            vector=[0.1, 0.2],
            payload={
                "document": "doc_001",
                "section_path": "§1.2",
                "page": 3,
                "chunk_id": "chk_001",
            },
        )
        assert vp.id == "chk_001"
        assert vp.payload["page"] == 3

    def test_hit_dataclass(self) -> None:
        h = Hit(
            id="chk_002",
            score=0.87,
            payload={"document": "doc_001", "section_path": "§2", "page": 5, "chunk_id": "chk_002"},
        )
        assert h.score == pytest.approx(0.87)

    def test_object_not_satisfying_embedder_fails_isinstance(self) -> None:
        class BadEmbedder:
            """Missing dim and embed()."""
            name = "bad"

        b = BadEmbedder()
        assert not isinstance(b, EmbedderPlugin)


# ---------------------------------------------------------------------------
# Tests: resolve() over monkeypatched entry points
# ---------------------------------------------------------------------------


def _make_entry_point(name: str, factory: Any) -> EntryPoint:
    """Return an entry point whose .load() returns factory."""
    ep = MagicMock(spec=EntryPoint)
    ep.name = name
    ep.load.return_value = factory
    return ep


class TestResolver:
    def test_resolve_returns_instantiated_plugin(self) -> None:
        ep = _make_entry_point("dummy", DummyEmbedder)
        with patch(
            "knowledge_lake.plugins.resolver.entry_points",
            return_value=[ep],
        ):
            result = resolve("knowledge_lake.embedders", "dummy")
        assert isinstance(result, DummyEmbedder)

    def test_resolve_raises_lookup_error_for_missing_name(self) -> None:
        with patch(
            "knowledge_lake.plugins.resolver.entry_points",
            return_value=[],
        ):
            with pytest.raises(LookupError) as exc_info:
                resolve("knowledge_lake.embedders", "nonexistent")
        msg = str(exc_info.value)
        assert "nonexistent" in msg
        assert "knowledge_lake.embedders" in msg

    def test_resolve_selects_correct_name_among_multiple(self) -> None:
        ep_dummy = _make_entry_point("dummy", DummyEmbedder)
        ep_other = _make_entry_point("other", DummyParser)
        with patch(
            "knowledge_lake.plugins.resolver.entry_points",
            return_value=[ep_dummy, ep_other],
        ):
            result = resolve("knowledge_lake.embedders", "dummy")
        assert isinstance(result, DummyEmbedder)

    def test_swap_by_name_no_resolver_code_change(self) -> None:
        """Changing the requested name selects a different plugin without editing resolver."""

        class AlternativeEmbedder:
            name = "alternative"
            dim = 8

            def embed(self, texts: list[str]) -> list[list[float]]:
                return [[1.0] * self.dim for _ in texts]

        ep_a = _make_entry_point("alternative", AlternativeEmbedder)
        with patch(
            "knowledge_lake.plugins.resolver.entry_points",
            return_value=[ep_a],
        ):
            result = resolve("knowledge_lake.embedders", "alternative")
        assert isinstance(result, AlternativeEmbedder)
        assert result.dim == 8


# ---------------------------------------------------------------------------
# Tests: get_embedder / get_parser / get_vectorstore read from Settings
# ---------------------------------------------------------------------------


class TestConvenienceFunctions:
    def test_get_embedder_reads_settings_embedder_key(self) -> None:
        settings = Settings(embedder="dummy", _env_file=None)
        ep = _make_entry_point("dummy", DummyEmbedder)
        with patch(
            "knowledge_lake.plugins.resolver.entry_points",
            return_value=[ep],
        ):
            result = get_embedder(settings)
        assert isinstance(result, DummyEmbedder)

    def test_get_parser_reads_settings_parser_key(self) -> None:
        settings = Settings(parser="dummy_parser", _env_file=None)
        ep = _make_entry_point("dummy_parser", DummyParser)
        with patch(
            "knowledge_lake.plugins.resolver.entry_points",
            return_value=[ep],
        ):
            result = get_parser(settings)
        assert isinstance(result, DummyParser)

    def test_get_vectorstore_reads_settings_vectorstore_key(self) -> None:
        settings = Settings(vectorstore="dummy_store", _env_file=None)
        ep = _make_entry_point("dummy_store", DummyStore)
        with patch(
            "knowledge_lake.plugins.resolver.entry_points",
            return_value=[ep],
        ):
            result = get_vectorstore(settings)
        assert isinstance(result, DummyStore)

    def test_changing_embedder_config_changes_returned_plugin(self) -> None:
        """Proves swap-by-config: different Settings.embedder = different object returned."""

        class EmbedderA:
            name = "impl_a"
            dim = 2

            def embed(self, texts: list[str]) -> list[list[float]]:
                return [[0.0, 0.0]]

        class EmbedderB:
            name = "impl_b"
            dim = 3

            def embed(self, texts: list[str]) -> list[list[float]]:
                return [[0.0, 0.0, 0.0]]

        ep_a = _make_entry_point("impl_a", EmbedderA)
        ep_b = _make_entry_point("impl_b", EmbedderB)
        all_eps = [ep_a, ep_b]

        settings_a = Settings(embedder="impl_a", _env_file=None)
        settings_b = Settings(embedder="impl_b", _env_file=None)
        with patch(
            "knowledge_lake.plugins.resolver.entry_points",
            return_value=all_eps,
        ):
            result_a = get_embedder(settings_a)
            result_b = get_embedder(settings_b)
        assert result_a.name == "impl_a"
        assert result_b.name == "impl_b"
        assert type(result_a) is not type(result_b)
