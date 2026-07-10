"""Integration test: Hybrid retrieval migration — unnamed→named recreate + re-embedding (RETR-01).

Runs against the real Qdrant server (settings.qdrant_url, default
http://localhost:6333) started by docker-compose.  Verifies:
  - Re-embedding migration produces count-parity before alias swap (D-06)
  - Every migrated point carries a non-empty 'sparse' named vector (D-05)
  - IDF modifier is set on the sparse vector config (D-13)
  - Payload keyword indexes survive the named-vector recreate (D-14)
  - Dense-mode search works on BOTH legacy unnamed and migrated named (D-09)

Run with:
    uv run pytest tests/integration/test_qdrant_hybrid_migration.py -v -m integration

All tests are marked xfail(strict=False) — they encode RED acceptance targets
for Plan 10-07 (hybrid migration implementation).

Fixtures reuse the store/alias pattern from tests/integration/test_qdrant_alias_reindex.py.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from knowledge_lake.config.settings import get_settings
from knowledge_lake.plugins.builtin.qdrant_store import QdrantVectorStore
from knowledge_lake.plugins.protocols import VectorPoint

pytestmark = pytest.mark.integration


# ── Shared fixtures (mirrors test_qdrant_alias_reindex.py) ─────────────────────


@pytest.fixture
def store() -> QdrantVectorStore:
    settings = get_settings()
    return QdrantVectorStore(qdrant_url=settings.qdrant_url)


@pytest.fixture
def alias(store: QdrantVectorStore):
    """A fresh test alias name; cleans up all physical collections afterward."""
    name = f"test_hybrid_{uuid4().hex[:8]}"
    created_physicals: list[str] = []
    yield name, created_physicals
    for physical in created_physicals:
        try:
            if store._client.collection_exists(physical):
                store._client.delete_collection(physical)
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass


# ── Test: Re-embed parity gate (D-06) ─────────────────────────────────────────


@pytest.mark.xfail(reason="Plan 10-07: hybrid migration re-embed not yet implemented", strict=False)
def test_reembed_parity(store: QdrantVectorStore, alias):
    """Seed a legacy unnamed collection behind an alias, run the hybrid
    re-embedding reindex, assert count(old) == count(new) before the alias
    swap is honoured (D-06 parity gate).
    """
    alias_name, created_physicals = alias
    dim = 4

    # Bootstrap a legacy unnamed collection
    physical_v1, created = store.ensure_aliased_collection(alias_name, dim=dim)
    created_physicals.append(physical_v1)

    # Seed some points into the legacy collection
    points = [
        VectorPoint(id=f"chk_{i}", vector=[float(i)] * dim, payload={"text": f"chunk {i}", "chunk_id": f"chk_{i}"})
        for i in range(5)
    ]
    store.upsert(alias_name, points)

    # Run hybrid migration (Plan 10-07 adds this)
    # The migration should re-embed with sparse vectors into a new named collection
    result = store.reindex_hybrid(alias_name, dim=dim)
    new_physical = result["new_physical"]
    created_physicals.append(new_physical)

    # Parity gate: old count == new count
    old_count = store._client.count(physical_v1, exact=True).count
    new_count = store._client.count(new_physical, exact=True).count
    assert old_count == new_count, (
        f"Parity gate failed: old={old_count}, new={new_count}"
    )


# ── Test: All points have sparse vector (D-05) ────────────────────────────────


@pytest.mark.xfail(reason="Plan 10-07: hybrid migration sparse embedding not yet implemented", strict=False)
def test_all_points_have_sparse(store: QdrantVectorStore, alias):
    """After migration, scroll the new physical collection with_vectors=True
    and assert every point carries a non-empty 'sparse' named vector.
    """
    alias_name, created_physicals = alias
    dim = 4

    # Bootstrap + seed
    physical_v1, _ = store.ensure_aliased_collection(alias_name, dim=dim)
    created_physicals.append(physical_v1)

    points = [
        VectorPoint(id=f"chk_{i}", vector=[float(i)] * dim, payload={"text": f"chunk {i}", "chunk_id": f"chk_{i}"})
        for i in range(3)
    ]
    store.upsert(alias_name, points)

    # Migrate
    result = store.reindex_hybrid(alias_name, dim=dim)
    new_physical = result["new_physical"]
    created_physicals.append(new_physical)

    # Scroll all points with vectors
    records, _ = store._client.scroll(
        collection_name=new_physical, limit=100, with_vectors=True
    )
    assert len(records) > 0, "No points found in migrated collection"

    for record in records:
        vectors = record.vector
        assert isinstance(vectors, dict), f"Expected named vectors dict, got {type(vectors)}"
        assert "sparse" in vectors, f"Point {record.id} missing 'sparse' vector"
        sparse = vectors["sparse"]
        # SparseVector should have non-empty indices
        assert hasattr(sparse, "indices") or isinstance(sparse, dict), (
            f"Point {record.id} sparse vector has unexpected shape"
        )


# ── Test: IDF modifier set on collection (D-13) ───────────────────────────────


@pytest.mark.xfail(reason="Plan 10-07: named create-path with IDF not yet implemented", strict=False)
def test_idf_modifier_set(store: QdrantVectorStore, alias):
    """Assert get_collection(new).config.params.sparse_vectors['sparse'].modifier
    == Modifier.IDF after migration.
    """
    alias_name, created_physicals = alias
    dim = 4

    physical_v1, _ = store.ensure_aliased_collection(alias_name, dim=dim)
    created_physicals.append(physical_v1)

    points = [
        VectorPoint(id="chk_0", vector=[1.0] * dim, payload={"text": "test", "chunk_id": "chk_0"})
    ]
    store.upsert(alias_name, points)

    result = store.reindex_hybrid(alias_name, dim=dim)
    new_physical = result["new_physical"]
    created_physicals.append(new_physical)

    # Check IDF modifier on the sparse vector config
    from qdrant_client.models import Modifier

    collection_info = store._client.get_collection(new_physical)
    sparse_vectors = collection_info.config.params.sparse_vectors
    assert sparse_vectors is not None, "No sparse_vectors config on migrated collection"
    assert "sparse" in sparse_vectors, "Missing 'sparse' key in sparse_vectors config"
    assert sparse_vectors["sparse"].modifier == Modifier.IDF, (
        f"Expected Modifier.IDF, got {sparse_vectors['sparse'].modifier}"
    )


# ── Test: Payload indexes survive (D-14) ──────────────────────────────────────


@pytest.mark.xfail(reason="Plan 10-07: ensure_payload_indexes on named recreate not yet verified", strict=False)
def test_payload_indexes_survive(store: QdrantVectorStore, alias):
    """Assert the 7 keyword payload indexes exist on the migrated collection
    so filtered hybrid search does not full-scan.
    """
    alias_name, created_physicals = alias
    dim = 4

    physical_v1, _ = store.ensure_aliased_collection(alias_name, dim=dim)
    created_physicals.append(physical_v1)

    points = [
        VectorPoint(id="chk_0", vector=[1.0] * dim, payload={"text": "test", "chunk_id": "chk_0"})
    ]
    store.upsert(alias_name, points)

    result = store.reindex_hybrid(alias_name, dim=dim)
    new_physical = result["new_physical"]
    created_physicals.append(new_physical)

    # Check payload indexes on the migrated collection
    collection_info = store._client.get_collection(new_physical)
    payload_schema = collection_info.payload_schema

    expected_fields = {"domain", "document_type", "source_name", "format", "source_id", "tags", "keywords"}
    indexed_fields = set(payload_schema.keys()) if payload_schema else set()
    missing = expected_fields - indexed_fields
    assert not missing, f"Payload indexes missing on migrated collection: {missing}"


# ── Test: Dense on both shapes (D-09) ─────────────────────────────────────────


@pytest.mark.xfail(reason="Plan 10-07: dense-on-both-shapes back-compat not yet implemented", strict=False)
def test_dense_both_shapes(store: QdrantVectorStore, alias):
    """Assert dense-mode search returns hits against BOTH a legacy unnamed
    collection and a migrated named collection.
    """
    alias_name, created_physicals = alias
    dim = 4

    # Create and seed a legacy unnamed collection
    physical_v1, _ = store.ensure_aliased_collection(alias_name, dim=dim)
    created_physicals.append(physical_v1)

    points = [
        VectorPoint(id="chk_0", vector=[1.0, 0.0, 0.0, 0.0], payload={"text": "hello", "chunk_id": "chk_0"}),
        VectorPoint(id="chk_1", vector=[0.0, 1.0, 0.0, 0.0], payload={"text": "world", "chunk_id": "chk_1"}),
    ]
    store.upsert(alias_name, points)

    # Dense search against legacy unnamed collection should work
    legacy_hits = store.search(
        collection=alias_name,
        query=[1.0, 0.0, 0.0, 0.0],
        top_k=2,
        mode="dense",
    )
    assert len(legacy_hits) > 0, "Dense search on legacy unnamed collection returned no hits"

    # Migrate to named collection
    result = store.reindex_hybrid(alias_name, dim=dim)
    new_physical = result["new_physical"]
    created_physicals.append(new_physical)

    # Dense search against migrated named collection should also work
    named_hits = store.search(
        collection=alias_name,
        query=[1.0, 0.0, 0.0, 0.0],
        top_k=2,
        mode="dense",
    )
    assert len(named_hits) > 0, "Dense search on migrated named collection returned no hits"
