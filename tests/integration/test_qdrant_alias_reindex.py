"""Integration test: Qdrant alias bootstrap + zero-downtime reindex (INDEX-02, D-06).

Runs against the real Qdrant server (settings.qdrant_url, default
http://localhost:6333) started by docker-compose. Verifies:
  - ensure_aliased_collection() creates a physical v1 collection behind an alias
  - reindex() creates v2, copies all points via copy_all_points(), and atomically
    repoints the alias — search() through the alias keeps working with zero
    downtime, and the old physical collection remains independently queryable
    until the caller explicitly drops it.

Run with:
    uv run pytest tests/integration/test_qdrant_alias_reindex.py -v -m integration
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from knowledge_lake.config.settings import get_settings
from knowledge_lake.plugins.builtin.qdrant_store import QdrantVectorStore
from knowledge_lake.plugins.protocols import VectorPoint

pytestmark = pytest.mark.integration


@pytest.fixture
def store() -> QdrantVectorStore:
    settings = get_settings()
    return QdrantVectorStore(qdrant_url=settings.qdrant_url)


@pytest.fixture
def alias(store: QdrantVectorStore):
    """A fresh test alias name; cleans up both physical collections afterward."""
    name = f"test_alias_{uuid4().hex[:8]}"
    created_physicals: list[str] = []
    yield name, created_physicals
    for physical in created_physicals:
        try:
            if store._client.collection_exists(physical):
                store._client.delete_collection(physical)
        except Exception:  # noqa: BLE001 — best-effort cleanup, never fail the test on teardown
            pass


class TestAliasBootstrapAndReindex:
    def test_ensure_aliased_collection_then_reindex_preserves_search(
        self, store: QdrantVectorStore, alias
    ) -> None:
        alias_name, created_physicals = alias
        dim = 4

        physical_v1, created = store.ensure_aliased_collection(alias_name, dim=dim)
        created_physicals.append(physical_v1)
        assert created is True
        assert physical_v1 == f"{alias_name}_v1"

        points = [
            VectorPoint(
                id=str(uuid4()),
                vector=[0.1, 0.1, 0.1, 0.1],
                payload={"chunk_id": f"chk_{i}", "text": f"point {i}"},
            )
            for i in range(3)
        ]
        store.upsert(alias_name, points)

        result = store.reindex(
            alias_name,
            dim=dim,
            upsert_fn=lambda new_name: store.copy_all_points(alias_name, new_name),
        )
        new_physical = result["new_physical"]
        old_physical = result["old_physical"]
        created_physicals.append(new_physical)

        assert old_physical == physical_v1
        assert new_physical == f"{alias_name}_v2"

        # The alias transparently now resolves to the new physical collection —
        # all 3 points are still searchable through the alias.
        hits = store.search(alias_name, [0.1, 0.1, 0.1, 0.1], top_k=5)
        assert len(hits) == 3

        # The OLD physical collection is retained (never auto-dropped) and
        # independently queryable by its own physical name.
        assert store._client.collection_exists(old_physical) is True
        old_hits = store.search(old_physical, [0.1, 0.1, 0.1, 0.1], top_k=5)
        assert len(old_hits) == 3
