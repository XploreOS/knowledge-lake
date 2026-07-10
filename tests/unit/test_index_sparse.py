"""Unit tests for pipeline/index.py sparse-vector attachment (RETR-01, D-05).

Covers:
  - index() attaches embed_sparse_doc result as VectorPoint.sparse for every chunk
  - Empty chunk text produces an empty SparseVector, not an exception
  - embed_sparse_doc is called once per chunk with the chunk text
  - reindex_collection(hybrid=True) calls assert_server_supports_hybrid() before creating
    the new collection, and routes through vstore.reembed_all_points (not copy_all_points)
  - reindex_collection(hybrid=False) preserves existing copy_all_points behavior

No DB, Qdrant server, or live fastembed model contact — all external dependencies
are monkeypatched at the pipeline.index module level (mirrors test_index_payload.py).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.pipeline.index as index_module
import knowledge_lake.registry.db as registry_db
from knowledge_lake.registry import repo as registry_repo


# ── DB fixtures (mirrors test_index_payload.py) ───────────────────────────────


@pytest.fixture()
def engine():
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
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)


@pytest.fixture()
def session(engine):
    with Session(engine) as sess:
        yield sess


# ── Store + sparse-embedder fakes ─────────────────────────────────────────────


@pytest.fixture()
def fake_vstore(monkeypatch):
    """Mock get_vectorstore() at pipeline.index module level."""
    vstore = MagicMock()
    vstore.ensure_aliased_collection.return_value = ("klake_chunks_v1", False)
    monkeypatch.setattr(index_module, "get_vectorstore", lambda _s: vstore)
    return vstore


@pytest.fixture()
def fake_sparse(monkeypatch):
    """Monkeypatch embed_sparse_doc at the index module level.

    Returns a MagicMock that records calls and returns a distinct SparseVector
    stub so tests can assert it ends up on each VectorPoint.
    """
    from qdrant_client.models import SparseVector

    sparse_vec = SparseVector(indices=[1, 2], values=[0.5, 0.7])

    sparse_fn = MagicMock(return_value=sparse_vec)
    # embed_sparse_doc is imported into index_module namespace after Task 1 implementation
    monkeypatch.setattr(index_module, "embed_sparse_doc", sparse_fn, raising=True)
    return sparse_fn, sparse_vec


# ── Helpers ───────────────────────────────────────────────────────────────────


def _one_chunk(chunk_id: str = "chk_001", text: str = "hello world") -> dict:
    return {
        "chunk_id": chunk_id,
        "section_path": "§1",
        "page": 1,
        "text": text,
    }


def _seed_parsed(session, source_name: str = "S", chunk_id_suffix: str = "x") -> Any:
    """Create source → raw → parsed row; return the parsed artifact ID."""
    source = registry_repo.create_source(session, name=source_name, source_type="web")
    raw = registry_repo.create_raw_artifact(
        session,
        source_id=source.id,
        content_hash=f"raw_{chunk_id_suffix}",
        storage_uri=f"s3://b/raw/raw_{chunk_id_suffix}.pdf",
    )
    parsed = registry_repo.create_parsed_artifact(
        session,
        source_id=source.id,
        parent_artifact_id=raw.id,
        content_hash=f"parsed_{chunk_id_suffix}",
        storage_uri=f"s3://b/silver/parsed_{chunk_id_suffix}.json",
    )
    session.commit()
    return parsed.id


def _captured_points(vstore: MagicMock) -> list[Any]:
    """Extract the VectorPoint list passed to vstore.upsert."""
    upsert_call = vstore.upsert.call_args
    points = (
        upsert_call.args[1]
        if upsert_call.args and len(upsert_call.args) > 1
        else upsert_call.kwargs["points"]
    )
    return list(points)


# ── Task 1: index() sparse attachment ─────────────────────────────────────────


class TestIndexSparseAttach:
    """index() attaches embed_sparse_doc result as VectorPoint.sparse (D-05, RETR-01)."""

    def test_every_vector_point_has_sparse_set(
        self, session, fake_vstore, fake_sparse
    ) -> None:
        """Each VectorPoint upserted by index() carries a non-None sparse field."""
        sparse_fn, sparse_vec = fake_sparse
        parsed_id = _seed_parsed(session, chunk_id_suffix="a")

        chunks = [_one_chunk("chk_001", "clinical text"), _one_chunk("chk_002", "patient data")]
        vectors = [[0.1] * 4, [0.2] * 4]
        index_module.index(chunks, vectors, dim=4, parsed_artifact_id=parsed_id)

        points = _captured_points(fake_vstore)
        assert len(points) == 2, f"Expected 2 upserted points, got {len(points)}"
        for i, pt in enumerate(points):
            assert pt.sparse is not None, (
                f"VectorPoint {i} has sparse=None; expected sparse to be set from embed_sparse_doc"
            )
            assert pt.sparse is sparse_vec, (
                f"VectorPoint {i}.sparse must be the SparseVector returned by embed_sparse_doc"
            )

    def test_embed_sparse_doc_called_once_per_chunk_with_text(
        self, session, fake_vstore, fake_sparse
    ) -> None:
        """embed_sparse_doc is called exactly once per chunk, passing the chunk text."""
        sparse_fn, _ = fake_sparse
        parsed_id = _seed_parsed(session, chunk_id_suffix="b")

        chunks = [
            _one_chunk("chk_010", "chunk A text"),
            _one_chunk("chk_011", "chunk B text"),
        ]
        vectors = [[0.1] * 4, [0.2] * 4]
        index_module.index(chunks, vectors, dim=4, parsed_artifact_id=parsed_id)

        assert sparse_fn.call_count == 2, (
            f"embed_sparse_doc should be called once per chunk; got {sparse_fn.call_count}"
        )
        sparse_fn.assert_any_call("chunk A text")
        sparse_fn.assert_any_call("chunk B text")

    def test_empty_chunk_text_yields_no_exception(
        self, session, fake_vstore, monkeypatch
    ) -> None:
        """index() with an empty chunk text must not raise — sparse is still set."""
        from qdrant_client.models import SparseVector

        empty_sv = SparseVector(indices=[], values=[])
        sparse_fn = MagicMock(return_value=empty_sv)
        monkeypatch.setattr(index_module, "embed_sparse_doc", sparse_fn, raising=True)

        parsed_id = _seed_parsed(session, chunk_id_suffix="c")
        chunks = [_one_chunk("chk_020", text="")]
        vectors = [[0.1] * 4]
        # Must not raise
        index_module.index(chunks, vectors, dim=4, parsed_artifact_id=parsed_id)

        points = _captured_points(fake_vstore)
        assert len(points) == 1
        assert points[0].sparse is empty_sv, (
            "Empty chunk text must still produce a SparseVector (empty, not None)"
        )


# ── Task 2: reindex_collection hybrid migration ────────────────────────────────


class TestReindexCollectionHybrid:
    """reindex_collection(hybrid=True) wires assert_server_supports_hybrid + reembed_all_points."""

    @pytest.fixture()
    def fake_vstore_reindex(self, monkeypatch):
        """Fake vstore configured for reindex path (get_collection_dim + reindex)."""
        vstore = MagicMock()
        vstore.get_collection_dim.return_value = 4
        # reindex captures the upsert_fn and records it
        captured: dict = {}

        def _reindex(alias, *, dim, upsert_fn, **kwargs):
            captured["upsert_fn"] = upsert_fn
            captured["alias"] = alias
            return {"new_physical": f"{alias}_v2", "old_physical": f"{alias}_v1"}

        vstore.reindex.side_effect = _reindex
        monkeypatch.setattr(index_module, "get_vectorstore", lambda _s: vstore)
        monkeypatch.setattr(index_module, "get_session", MagicMock())
        return vstore, captured

    def test_hybrid_true_calls_assert_server_supports_hybrid_before_reindex(
        self, session, fake_vstore_reindex
    ) -> None:
        """assert_server_supports_hybrid() is called before vstore.reindex() (D-07)."""
        vstore, captured = fake_vstore_reindex

        call_order: list[str] = []
        vstore.assert_server_supports_hybrid.side_effect = (
            lambda: call_order.append("preflight")
        )
        vstore.reindex.side_effect = (
            lambda *a, **kw: (
                call_order.append("reindex"),
                {"new_physical": "klake_chunks_v2", "old_physical": "klake_chunks_v1"},
            )[1]
        )

        index_module.reindex_collection(hybrid=True)

        assert "preflight" in call_order, "assert_server_supports_hybrid was not called"
        assert call_order.index("preflight") < call_order.index("reindex"), (
            "preflight must run BEFORE reindex, not after"
        )

    def test_hybrid_true_uses_reembed_fn_not_copy(
        self, session, fake_vstore_reindex
    ) -> None:
        """reindex_collection(hybrid=True) calls vstore.reembed_all_points, not copy_all_points."""
        vstore, captured = fake_vstore_reindex

        # vstore.reindex actually invokes upsert_fn(new_physical); simulate that
        new_physical_target = "klake_chunks_v2"

        def _reindex(alias, *, dim, upsert_fn, **kwargs):
            upsert_fn(new_physical_target)  # simulate vstore.reindex invoking the fn
            return {
                "new_physical": new_physical_target,
                "old_physical": "klake_chunks_v1",
            }

        vstore.reindex.side_effect = _reindex

        index_module.reindex_collection(hybrid=True)

        vstore.reembed_all_points.assert_called_once()
        # copy_all_points must NOT be called
        vstore.copy_all_points.assert_not_called()

    def test_hybrid_false_uses_copy_fn_not_reembed(
        self, session, fake_vstore_reindex
    ) -> None:
        """reindex_collection(hybrid=False) keeps the existing copy_all_points path."""
        vstore, captured = fake_vstore_reindex

        def _reindex(alias, *, dim, upsert_fn, **kwargs):
            upsert_fn("klake_chunks_v2")  # invoke the copy fn
            return {
                "new_physical": "klake_chunks_v2",
                "old_physical": "klake_chunks_v1",
            }

        vstore.reindex.side_effect = _reindex

        index_module.reindex_collection(hybrid=False)

        vstore.copy_all_points.assert_called_once()
        vstore.reembed_all_points.assert_not_called()
        vstore.assert_server_supports_hybrid.assert_not_called()
