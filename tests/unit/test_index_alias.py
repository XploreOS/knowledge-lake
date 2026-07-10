"""Unit tests for Qdrant alias bootstrap + zero-downtime reindex (INDEX-02, D-06).

Mocks QdrantVectorStore._client (mirrors tests/unit/test_builtin_plugins.py's
TestQdrantVectorStore mocking style) so no live Qdrant server is required for
these structural/behavioral assertions. The live alias-swap behavior itself is
covered by tests/integration/test_qdrant_alias_reindex.py against a real server.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def store() -> Any:
    from knowledge_lake.plugins.builtin.qdrant_store import QdrantVectorStore

    return QdrantVectorStore()


def _alias_desc(alias_name: str, collection_name: str) -> MagicMock:
    a = MagicMock()
    a.alias_name = alias_name
    a.collection_name = collection_name
    return a


def _collection_desc(name: str) -> MagicMock:
    c = MagicMock()
    c.name = name
    return c


# ---------------------------------------------------------------------------
# ensure_aliased_collection
# ---------------------------------------------------------------------------


class TestEnsureAliasedCollection:
    def test_creates_v1_and_alias_when_missing(self, store: Any) -> None:
        mock_client = MagicMock()
        mock_client.collection_exists.return_value = False
        store._client = mock_client

        physical, created = store.ensure_aliased_collection("klake_chunks", dim=384)

        assert physical == "klake_chunks_v1"
        assert created is True
        mock_client.create_collection.assert_called_once()
        create_kwargs = mock_client.create_collection.call_args.kwargs
        assert create_kwargs.get("collection_name") == "klake_chunks_v1"
        mock_client.update_collection_aliases.assert_called_once()

    def test_noop_when_alias_already_exists(self, store: Any) -> None:
        mock_client = MagicMock()
        mock_client.collection_exists.return_value = True
        store._client = mock_client

        physical, created = store.ensure_aliased_collection("klake_chunks", dim=384)

        assert physical == "klake_chunks"
        assert created is False
        mock_client.create_collection.assert_not_called()
        mock_client.update_collection_aliases.assert_not_called()


# ---------------------------------------------------------------------------
# _next_version_name
# ---------------------------------------------------------------------------


class TestNextVersionName:
    def test_returns_next_after_highest_existing_version(self, store: Any) -> None:
        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(
            collections=[
                _collection_desc("col_v1"),
                _collection_desc("col_v3"),
                _collection_desc("unrelated"),
            ]
        )
        store._client = mock_client

        assert store._next_version_name("col") == "col_v4"

    def test_returns_v1_when_none_exist(self, store: Any) -> None:
        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])
        store._client = mock_client

        assert store._next_version_name("col") == "col_v1"


# ---------------------------------------------------------------------------
# reindex
# ---------------------------------------------------------------------------


class TestReindex:
    def test_reindex_deletes_and_creates_alias_in_one_call(self, store: Any) -> None:
        mock_client = MagicMock()
        mock_client.get_aliases.return_value = MagicMock(
            aliases=[_alias_desc("col", "col_v1")]
        )
        mock_client.get_collections.return_value = MagicMock(
            collections=[_collection_desc("col_v1")]
        )
        mock_client.count.return_value.count = 2  # D-06 parity gate: old == new
        store._client = mock_client

        calls: list[str] = []

        def upsert_fn(new_physical: str) -> None:
            calls.append(new_physical)

        result = store.reindex("col", dim=4, upsert_fn=upsert_fn)

        assert result == {"new_physical": "col_v2", "old_physical": "col_v1"}
        assert calls == ["col_v2"]

        mock_client.update_collection_aliases.assert_called_once()
        ops = mock_client.update_collection_aliases.call_args.kwargs[
            "change_aliases_operations"
        ]
        assert len(ops) == 2
        assert ops[0].delete_alias.alias_name == "col"
        assert ops[1].create_alias.collection_name == "col_v2"
        assert ops[1].create_alias.alias_name == "col"

    def test_upsert_fn_called_before_alias_swap(self, store: Any) -> None:
        mock_client = MagicMock()
        mock_client.get_aliases.return_value = MagicMock(
            aliases=[_alias_desc("col", "col_v1")]
        )
        mock_client.get_collections.return_value = MagicMock(
            collections=[_collection_desc("col_v1")]
        )
        mock_client.count.return_value.count = 2  # D-06 parity gate: old == new
        store._client = mock_client

        call_order: list[str] = []
        mock_client.update_collection_aliases.side_effect = (
            lambda **_: call_order.append("alias_swap")
        )

        def upsert_fn(new_physical: str) -> None:
            call_order.append("upsert_fn")

        store.reindex("col", dim=4, upsert_fn=upsert_fn)

        assert call_order == ["upsert_fn", "alias_swap"]

    def test_first_ever_reindex_issues_only_create(self, store: Any) -> None:
        mock_client = MagicMock()
        mock_client.get_aliases.return_value = MagicMock(aliases=[])
        mock_client.get_collections.return_value = MagicMock(collections=[])
        store._client = mock_client

        result = store.reindex("col", dim=4, upsert_fn=lambda _n: None)

        assert result == {"new_physical": "col_v1", "old_physical": None}
        ops = mock_client.update_collection_aliases.call_args.kwargs[
            "change_aliases_operations"
        ]
        assert len(ops) == 1
        assert ops[0].create_alias.collection_name == "col_v1"


# ---------------------------------------------------------------------------
# copy_all_points
# ---------------------------------------------------------------------------


class TestCopyAllPoints:
    def _record(self, point_id: str) -> MagicMock:
        r = MagicMock()
        r.id = point_id
        r.vector = [0.1, 0.2]
        r.payload = {"chunk_id": point_id}
        return r

    def test_copies_one_batch_then_stops(self, store: Any) -> None:
        mock_client = MagicMock()
        records = [self._record("a"), self._record("b")]
        mock_client.scroll.side_effect = [
            (records, None),
        ]
        store._client = mock_client

        count = store.copy_all_points("src", "dst")

        assert count == 2
        mock_client.upsert.assert_called_once()
        upsert_kwargs = mock_client.upsert.call_args.kwargs
        assert upsert_kwargs.get("collection_name") == "dst"
        assert len(upsert_kwargs.get("points")) == 2

    def test_empty_source_returns_zero_without_upsert(self, store: Any) -> None:
        mock_client = MagicMock()
        mock_client.scroll.return_value = ([], None)
        store._client = mock_client

        count = store.copy_all_points("src", "dst")

        assert count == 0
        mock_client.upsert.assert_not_called()

    def test_multiple_batches_accumulate_count(self, store: Any) -> None:
        mock_client = MagicMock()
        mock_client.scroll.side_effect = [
            ([self._record("a")], "offset-1"),
            ([self._record("b")], None),
        ]
        store._client = mock_client

        count = store.copy_all_points("src", "dst", batch_size=1)

        assert count == 2
        assert mock_client.upsert.call_count == 2
