"""Unit tests for QdrantVectorStore.ensure_payload_indexes (D-07, D-08, D-09).

Covers PAYLOAD-02 acceptance criteria:
- ensure_payload_indexes() calls create_payload_index for each field in _KEYWORD_FIELDS
- ensure_aliased_collection() calls ensure_payload_indexes() on the new physical collection
- reindex() calls ensure_payload_indexes() on the next physical collection

These tests are in RED state until Plan 03 adds ensure_payload_indexes() to
QdrantVectorStore and wires the call sites in ensure_aliased_collection() and reindex().

Fixture pattern mirrors tests/unit/test_builtin_plugins.py monkeypatch style:
uses QdrantVectorStore.__new__ to bypass __init__ and assigns a MagicMock _client
so no real Qdrant server connection is made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from knowledge_lake.plugins.builtin.qdrant_store import QdrantVectorStore


# ── Shared fixture ──────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_store():
    """Return a QdrantVectorStore with a fully-mocked _client (no real connection).

    Uses __new__ to bypass __init__ so no QdrantClient() is ever constructed.
    All qdrant_client model references (_Distance, _PointStruct, _VectorParams)
    are also replaced with MagicMock so the instance is self-contained.
    """
    store = QdrantVectorStore.__new__(QdrantVectorStore)
    store._client = MagicMock()
    store._Distance = MagicMock()
    store._PointStruct = MagicMock()
    store._VectorParams = MagicMock()
    return store


# ── TestEnsurePayloadIndexes ────────────────────────────────────────────────────


class TestEnsurePayloadIndexes:
    """Verify that ensure_payload_indexes() calls create_payload_index for all
    expected fields in _KEYWORD_FIELDS (D-07, D-09).

    Expected fields (7 total):
      domain, document_type, source_name, format, source_id, tags, keywords
    """

    def test_calls_create_payload_index_for_all_expected_fields(
        self, mock_store
    ) -> None:
        """create_payload_index must be called once per field in _KEYWORD_FIELDS."""
        mock_store.ensure_payload_indexes("klake_chunks_v1")

        # 7 fields expected: domain, document_type, source_name, format, source_id, tags, keywords
        assert mock_store._client.create_payload_index.call_count == 7

        called_field_names = {
            c.kwargs["field_name"]
            for c in mock_store._client.create_payload_index.call_args_list
        }
        expected_fields = {
            "domain",
            "document_type",
            "source_name",
            "format",
            "source_id",
            "tags",
            "keywords",
        }
        assert expected_fields.issubset(called_field_names), (
            f"Missing fields: {expected_fields - called_field_names}"
        )


# ── TestEnsureAliasedCollectionCallsIndexes ─────────────────────────────────────


class TestEnsureAliasedCollectionCallsIndexes:
    """Verify that ensure_aliased_collection() calls ensure_payload_indexes() on the
    newly created physical collection (D-08).

    When collection_exists returns False, the physical collection (alias + '_v1') is
    created and ensure_payload_indexes() must be called with that physical name.
    """

    def test_calls_ensure_payload_indexes_on_new_physical(
        self, mock_store, monkeypatch
    ) -> None:
        """ensure_aliased_collection must call ensure_payload_indexes('klake_chunks_v1')
        when collection_exists returns False (new bootstrap path).
        """
        mock_store._client.collection_exists.return_value = False
        monkeypatch.setattr(mock_store, "ensure_payload_indexes", MagicMock())

        mock_store.ensure_aliased_collection("klake_chunks", dim=384)

        mock_store.ensure_payload_indexes.assert_called_once_with("klake_chunks_v1")


# ── TestReindexCallsIndexes ─────────────────────────────────────────────────────


class TestReindexCallsIndexes:
    """Verify that reindex() calls ensure_payload_indexes() on the next physical
    collection after upsert_fn has populated it (D-08, Pitfall 4).

    When get_collections and get_aliases return empty lists, the next physical
    name is alias + '_v1'. ensure_payload_indexes() must be called with that name.
    """

    def test_calls_ensure_payload_indexes_on_next_physical(
        self, mock_store, monkeypatch
    ) -> None:
        """reindex must call ensure_payload_indexes('klake_chunks_v1') after upsert_fn
        but before the alias swap (no existing versions → _v1 is the next name).
        """
        collections_response = MagicMock()
        collections_response.collections = []
        mock_store._client.get_collections.return_value = collections_response

        aliases_response = MagicMock()
        aliases_response.aliases = []
        mock_store._client.get_aliases.return_value = aliases_response

        monkeypatch.setattr(mock_store, "ensure_payload_indexes", MagicMock())

        mock_store.reindex("klake_chunks", dim=384, upsert_fn=lambda col: None)

        mock_store.ensure_payload_indexes.assert_called_once_with("klake_chunks_v1")
