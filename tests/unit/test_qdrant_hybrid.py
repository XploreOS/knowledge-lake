"""Unit tests for QdrantVectorStore hybrid retrieval (RETR-01, D-05, D-07, D-11, D-12, D-14).

RED test scaffold — these tests encode acceptance behaviors for the hybrid
retrieval surface (named dense+sparse collections, hybrid prefetch/RRF assembly,
get_collection_dim named-vector branch, server preflight, and upsert shape
branching).  Each is marked xfail(strict=False) because the implementation lives
in Plan 10-06 — the xfail decorators will be removed as each behavior lands.

Fixture mirrors tests/unit/test_qdrant_payload_indexes.py: uses
QdrantVectorStore.__new__ + MagicMock _client to avoid any real Qdrant connection.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from knowledge_lake.plugins.builtin.qdrant_store import QdrantVectorStore
from knowledge_lake.plugins.protocols import VectorPoint

# Guard imports of symbols that Plan 10-06 will add to qdrant_store or helpers.
# If the import fails we still collect cleanly (tests xfail anyway).
try:
    from knowledge_lake.plugins.builtin.qdrant_store import assert_server_supports_hybrid
except ImportError:
    assert_server_supports_hybrid = None


# ── Shared fixture ──────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_store():
    """Return a QdrantVectorStore with a fully-mocked _client (no real connection).

    Uses __new__ to bypass __init__ so no QdrantClient() is ever constructed.
    All qdrant_client model references are replaced with MagicMock so the
    instance is self-contained.  Extends the payload-indexes fixture with
    sparse/hybrid model mocks.
    """
    store = QdrantVectorStore.__new__(QdrantVectorStore)
    store._client = MagicMock()
    store._Distance = MagicMock()
    store._PointStruct = MagicMock()
    store._VectorParams = MagicMock()

    # Hybrid-related cached model mocks (Plan 10-06 adds these attributes)
    store._SparseVectorParams = MagicMock()
    store._Modifier = MagicMock()
    store._SparseVector = MagicMock()
    store._Prefetch = MagicMock()
    store._FusionQuery = MagicMock()
    store._Fusion = MagicMock()

    return store


# ── Test: Named create-path config (D-05, D-13, RETR-01) ────────────────────────


@pytest.mark.xfail(reason="Plan 10-06: named create-path not yet implemented", strict=False)
def test_named_create_config(mock_store):
    """After ensure_aliased_collection(alias, dim=384), assert create_collection
    was called with vectors_config carrying a 'dense' key and
    sparse_vectors_config carrying a 'sparse' key with modifier=Modifier.IDF.
    """
    store = mock_store
    # Stub collection_exists to trigger the create path
    store._client.collection_exists.return_value = False

    store.ensure_aliased_collection("test_alias", dim=384)

    call_kwargs = store._client.create_collection.call_args
    assert call_kwargs is not None, "create_collection was not called"

    # vectors_config must be a dict with 'dense' key (named vector)
    vectors_config = call_kwargs.kwargs.get("vectors_config") or call_kwargs[1].get("vectors_config")
    assert isinstance(vectors_config, dict), f"Expected dict vectors_config, got {type(vectors_config)}"
    assert "dense" in vectors_config, "Missing 'dense' key in vectors_config"

    # sparse_vectors_config must have a 'sparse' key with Modifier.IDF
    sparse_config = call_kwargs.kwargs.get("sparse_vectors_config") or call_kwargs[1].get(
        "sparse_vectors_config"
    )
    assert sparse_config is not None, "sparse_vectors_config not passed to create_collection"
    assert "sparse" in sparse_config, "Missing 'sparse' key in sparse_vectors_config"

    # The SparseVectorParams should have modifier=Modifier.IDF
    sparse_param = sparse_config["sparse"]
    # Verify modifier attribute (will be a real SparseVectorParams once implemented)
    from qdrant_client.models import Modifier

    assert hasattr(sparse_param, "modifier"), "SparseVectorParams missing modifier"
    assert sparse_param.modifier == Modifier.IDF, (
        f"Expected Modifier.IDF, got {sparse_param.modifier}"
    )


# ── Test: get_collection_dim for named collections (Pitfall 2) ──────────────────


@pytest.mark.xfail(reason="Plan 10-06: get_collection_dim named-vector branch not yet implemented", strict=False)
def test_get_dim_named(mock_store):
    """Stub _client.get_collection(...).config.params.vectors to a dict
    {'dense': obj(size=384)} and assert get_collection_dim returns 384
    without AttributeError.
    """
    store = mock_store

    # Build a mock that looks like a named-vector collection config
    dense_params = MagicMock()
    dense_params.size = 384

    collection_info = MagicMock()
    collection_info.config.params.vectors = {"dense": dense_params}

    store._client.get_collection.return_value = collection_info

    dim = store.get_collection_dim("test_alias")
    assert dim == 384, f"Expected 384, got {dim}"


# ── Test: Hybrid prefetch limits + RRF (D-11, D-12, D-14) ───────────────────────


def test_hybrid_prefetch_limits(mock_store):
    """Call search(mode='hybrid') and assert query_points received:
    - prefetch as a two-element list
    - first Prefetch with using='dense', second with using='sparse'
    - each with limit == top_k + offset
    - each carrying filter == the passed query_filter object (D-14)
    - query is a FusionQuery with fusion == Fusion.RRF (D-11)
    """
    store = mock_store
    top_k = 5
    offset = 0
    expected_limit = top_k + offset  # D-12

    # Build a mock filter object (replicates the Phase 7 filter builder output)
    query_filter = MagicMock(name="QueryFilter")

    # Build a mock sparse query vector
    sparse_query = MagicMock(name="SparseQueryVector")

    # Stub query_points response
    store._client.query_points.return_value = MagicMock(points=[])

    # Call the hybrid search path
    store.search(
        collection="test_collection",
        query=[0.1] * 384,
        top_k=top_k,
        query_filter=query_filter,
        mode="hybrid",
        sparse_query=sparse_query,
        offset=offset,
    )

    # Assert query_points was called
    qp_call = store._client.query_points.call_args
    assert qp_call is not None, "query_points was not called"

    kwargs = qp_call.kwargs if qp_call.kwargs else {}
    if not kwargs:
        # Fallback: positional + keyword mix
        kwargs = qp_call[1] if len(qp_call) > 1 else {}

    # Prefetch must be a two-element list
    prefetch = kwargs.get("prefetch")
    assert prefetch is not None, "prefetch not passed to query_points"
    assert len(prefetch) == 2, f"Expected 2 prefetch branches, got {len(prefetch)}"

    # The fixture injects a bare MagicMock as self._Prefetch, so its return value
    # carries child-mock attributes rather than the passed kwargs. Assert on the
    # construction call kwargs instead (same pattern as the create-path tests).
    prefetch_calls = store._Prefetch.call_args_list
    assert len(prefetch_calls) == 2, f"Expected 2 Prefetch constructions, got {len(prefetch_calls)}"

    # First branch: dense
    dense_kwargs = prefetch_calls[0].kwargs
    assert dense_kwargs.get("using") == "dense", (
        f"First branch using={dense_kwargs.get('using')}, expected 'dense'"
    )
    assert dense_kwargs.get("limit") == expected_limit, (
        f"Dense branch limit={dense_kwargs.get('limit')}, expected {expected_limit}"
    )
    assert dense_kwargs.get("filter") == query_filter, "Dense branch filter != passed query_filter (D-14)"

    # Second branch: sparse
    sparse_kwargs = prefetch_calls[1].kwargs
    assert sparse_kwargs.get("using") == "sparse", (
        f"Second branch using={sparse_kwargs.get('using')}, expected 'sparse'"
    )
    assert sparse_kwargs.get("limit") == expected_limit, (
        f"Sparse branch limit={sparse_kwargs.get('limit')}, expected {expected_limit}"
    )
    assert sparse_kwargs.get("filter") == query_filter, "Sparse branch filter != passed query_filter (D-14)"

    # Query must be FusionQuery with Fusion.RRF
    query_arg = kwargs.get("query")
    assert query_arg is not None, "query not passed to query_points"

    from qdrant_client.models import Fusion, FusionQuery

    assert isinstance(query_arg, FusionQuery), f"Expected FusionQuery, got {type(query_arg)}"
    assert query_arg.fusion == Fusion.RRF, f"Expected Fusion.RRF, got {query_arg.fusion}"


# ── Test: Server preflight (D-07) ───────────────────────────────────────────────


@pytest.mark.xfail(reason="Plan 10-06: server preflight helper not yet implemented", strict=False)
def test_server_preflight(mock_store):
    """Stub _client.info() to return version='1.9.0' and assert the preflight
    raises RuntimeError naming the version and >= 1.10 requirement.
    """
    store = mock_store

    # Stub the server info to return a too-old version
    info_mock = MagicMock()
    info_mock.version = "1.9.0"
    store._client.info.return_value = info_mock

    # The preflight should raise RuntimeError for server < 1.10
    if assert_server_supports_hybrid is not None:
        with pytest.raises(RuntimeError, match=r"1\.\s*10"):
            assert_server_supports_hybrid(store._client)
    else:
        # Symbol not yet imported — try calling the method on the store
        # (Plan 10-06 will add this as a method or standalone helper)
        with pytest.raises(RuntimeError, match=r"1\.\s*10"):
            store._assert_server_supports_hybrid()


# ── Test: Upsert named shape (Pitfall 1, D-09) ──────────────────────────────────


@pytest.mark.xfail(reason="Plan 10-06: named upsert shape branching not yet implemented", strict=False)
def test_upsert_named_shape(mock_store):
    """With _is_named returning True, upsert a VectorPoint carrying a sparse
    value; assert the built point vector is a dict with 'dense' and 'sparse' keys.
    """
    store = mock_store

    # Stub _is_named to return True (named collection)
    store._is_named = MagicMock(return_value=True)

    # Build a VectorPoint with both dense and sparse data
    sparse_mock = MagicMock(name="SparseVector")
    point = VectorPoint(
        id="chk_test123",
        vector=[0.1, 0.2, 0.3, 0.4],
        payload={"text": "test chunk", "chunk_id": "chk_test123"},
    )
    # Plan 10-06 adds VectorPoint.sparse optional field; simulate it
    point.sparse = sparse_mock  # type: ignore[attr-defined]

    store._client.upsert.return_value = None
    store._PointStruct.side_effect = lambda **kwargs: kwargs

    store.upsert("named_collection", [point])

    # Assert the PointStruct was built with a dict vector (named shape)
    ps_call = store._PointStruct.call_args
    assert ps_call is not None, "_PointStruct was not called"
    vector_arg = ps_call.kwargs.get("vector") or ps_call[1].get("vector")
    assert isinstance(vector_arg, dict), f"Expected dict vector for named shape, got {type(vector_arg)}"
    assert "dense" in vector_arg, "Missing 'dense' key in named vector"
    assert "sparse" in vector_arg, "Missing 'sparse' key in named vector"


# ── Test: Upsert legacy shape (Pitfall 1, D-09) ─────────────────────────────────


@pytest.mark.xfail(reason="Plan 10-06: upsert shape branching not yet implemented", strict=False)
def test_upsert_legacy_shape(mock_store):
    """With _is_named returning False, upsert a VectorPoint; assert the built
    point vector is the bare list (legacy unnamed collection) AND that the
    shape-detection helper _is_named was consulted to make the branching decision.
    """
    store = mock_store

    # Stub _is_named to return False (legacy unnamed collection)
    store._is_named = MagicMock(return_value=False)

    point = VectorPoint(
        id="chk_legacy456",
        vector=[0.5, 0.6, 0.7, 0.8],
        payload={"text": "legacy chunk", "chunk_id": "chk_legacy456"},
    )

    store._client.upsert.return_value = None
    store._PointStruct.side_effect = lambda **kwargs: kwargs

    store.upsert("legacy_collection", [point])

    # Assert _is_named was called (branching logic exists in the implementation)
    store._is_named.assert_called()

    # Assert the PointStruct was built with a bare list vector (unnamed shape)
    ps_call = store._PointStruct.call_args
    assert ps_call is not None, "_PointStruct was not called"
    vector_arg = ps_call.kwargs.get("vector") or ps_call[1].get("vector")
    assert isinstance(vector_arg, list), f"Expected list vector for legacy shape, got {type(vector_arg)}"
    assert vector_arg == [0.5, 0.6, 0.7, 0.8]
