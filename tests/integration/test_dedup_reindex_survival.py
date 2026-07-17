"""Integration test: reindex_collection() survives a deduplicated point (D-08).

Proves, against the live dev Postgres + Qdrant stack (no mocks), that
``reindex_collection()`` — in BOTH its default ``copy_all_points()`` path and
its ``refresh_payload=True`` (``refresh_all_points_payload()``) path — never
disturbs a deduplicated point's ``contributors``/``contributor_count``
payload fields or the ``chunk_dedup_ledger`` row's reference to it. Reindex
never writes to Postgres at all (the ledger row is asserted byte-for-byte
unchanged); only the Qdrant-side mirror is exercised by the reindex call.

This is RESEARCH.md Open Question 1 (D-08's dual-ID-scheme note from Plan
21-05) proven by test rather than merely documented: ``copy_all_points()``/
``refresh_all_points_payload()`` copy every point verbatim BY ITS EXISTING
ID, so a deterministic dedup point_id (uuid5-derived) and a legacy
``_strip_prefix(chunk_id)``-derived point_id can coexist in the same
collection without either function attempting to re-key one to the other's
scheme — this test only asserts the DEDUP point survives, since re-keying is
explicitly out of scope for this function (see index.py's D-08 docstring).

Run with:
    uv run pytest tests/integration/test_dedup_reindex_survival.py -v -m integration
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete

from knowledge_lake.config.settings import get_settings
from knowledge_lake.pipeline.dedup import dedup_chunks, text_sha256_for
from knowledge_lake.pipeline.embed import embed
from knowledge_lake.pipeline.index import index, reindex_collection
from knowledge_lake.plugins.builtin.qdrant_store import QdrantVectorStore
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.registry.models import ChunkDedupLedger

pytestmark = pytest.mark.integration

# At least 30 characters, distinct from the CLI/Dagster parity test's fixture text.
SHARED_BOILERPLATE_TEXT = (
    "All content on this page is provided for general informational purposes "
    "only and does not constitute professional or clinical advice of any kind."
)


def _cleanup_collection(alias_name: str) -> None:
    """Best-effort teardown: drop every physical collection version behind
    ``alias_name`` and delete this test's ledger rows, mirroring
    ``test_qdrant_alias_reindex.py``'s ``alias`` fixture teardown pattern."""
    settings = get_settings()
    store = QdrantVectorStore(qdrant_url=settings.qdrant_url)
    for suffix in ("_v1", "_v2", "_v3"):
        physical = f"{alias_name}{suffix}"
        try:
            if store._client.collection_exists(physical):
                store._client.delete_collection(physical)
        except Exception:  # noqa: BLE001 — best-effort cleanup, never fail the test on teardown
            pass

    with get_session() as session:
        session.execute(delete(ChunkDedupLedger).where(ChunkDedupLedger.collection == alias_name))


@pytest.fixture
def alias():
    """A fresh test alias name; cleans up all physical collections + ledger
    rows afterward (mirrors test_qdrant_alias_reindex.py's ``alias`` fixture)."""
    name = f"test_dedup_reindex_{uuid4().hex[:8]}"
    yield name
    _cleanup_collection(name)


def _seed_deduplicated_point(collection: str) -> dict:
    """Seed two documents' worth of chunks with the SAME boilerplate text into
    ``collection`` via ``dedup_chunks()`` + ``embed()`` + ``index()`` (Plan
    21-06's exact call shape), producing one deduplicated Qdrant point whose
    ledger row has ``contributor_count == 2`` and whose Qdrant payload
    carries a ``contributors`` list of length 2.

    Returns the ledger row's ``point_id``/``text_sha256`` plus a snapshot of
    the pre-reindex ``contributors``/``contributor_count`` for later
    byte-for-byte comparison.
    """
    for doc_id, chunk_id in (
        ("doc_dedup_reindex_1", "chk_dedup_reindex_1"),
        ("doc_dedup_reindex_2", "chk_dedup_reindex_2"),
    ):
        chunks_list = [
            {
                "chunk_id": chunk_id,
                "text": SHARED_BOILERPLATE_TEXT,
                "section_path": "s1",
                "page": 1,
            }
        ]
        dedup_result = dedup_chunks(
            chunks_list, doc_id, "src_dedup_reindex", collection=collection
        )
        vectors, dim = embed(dedup_result["new"])
        index(
            dedup_result["new"],
            vectors,
            dim,
            doc_id,
            collection=collection,
            duplicate_chunks=dedup_result["duplicates"],
        )

    text_sha256 = text_sha256_for(SHARED_BOILERPLATE_TEXT)
    with get_session() as session:
        ledger_row = registry_repo.get_dedup_ledger_entry(
            session, collection=collection, text_sha256=text_sha256
        )
        assert ledger_row is not None
        assert ledger_row.contributor_count == 2, (
            "seed setup must produce a deduplicated point (2 contributors) "
            f"before reindex runs, got contributor_count={ledger_row.contributor_count}"
        )
        return {
            "point_id": ledger_row.point_id,
            "text_sha256": text_sha256,
            "contributors_before": list(ledger_row.contributors),
            "contributor_count_before": ledger_row.contributor_count,
        }


def _assert_ledger_row_unchanged(collection: str, seed: dict) -> None:
    """Reindex never writes to Postgres — the ledger row must be
    byte-for-byte identical to its pre-reindex snapshot."""
    with get_session() as session:
        ledger_row = registry_repo.get_dedup_ledger_entry(
            session, collection=collection, text_sha256=seed["text_sha256"]
        )
        assert ledger_row is not None
        assert ledger_row.point_id == seed["point_id"], (
            "reindex must never re-key a deduplicated point's ledger point_id "
            "(D-08)"
        )
        assert ledger_row.contributor_count == seed["contributor_count_before"]
        assert list(ledger_row.contributors) == seed["contributors_before"]


class TestDedupSurvivesDefaultCopyReindex:
    """reindex_collection(hybrid=False, refresh_payload=False) — the default,
    verbatim copy_all_points() path."""

    def test_default_reindex_preserves_ledger_and_contributors_payload(
        self, alias: str
    ) -> None:
        seed = _seed_deduplicated_point(alias)

        settings = get_settings()
        store = QdrantVectorStore(qdrant_url=settings.qdrant_url)
        pre_records = store._client.retrieve(alias, [seed["point_id"]], with_payload=True)
        assert len(pre_records) == 1
        pre_payload = pre_records[0].payload

        result = reindex_collection(collection=alias, hybrid=False, refresh_payload=False)
        assert result["collection"] == alias
        assert result["new_physical"] != result["old_physical"]

        _assert_ledger_row_unchanged(alias, seed)

        # The alias now resolves to the NEW physical collection — the point
        # (by its existing, unchanged ID) must still resolve through it with
        # its contributors/contributor_count payload intact, byte-for-byte.
        post_records = store._client.retrieve(alias, [seed["point_id"]], with_payload=True)
        assert len(post_records) == 1
        post_payload = post_records[0].payload
        assert post_payload["contributors"] == pre_payload["contributors"] == seed["contributors_before"]
        assert post_payload["contributor_count"] == pre_payload["contributor_count"] == 2


class TestDedupSurvivesRefreshPayloadReindex:
    """reindex_collection(hybrid=False, refresh_payload=True) — the opt-in
    payload-re-derivation path (KL-06 repair path,
    ``refresh_all_points_payload()``)."""

    def test_refresh_payload_reindex_preserves_contributors_payload(
        self, alias: str
    ) -> None:
        seed = _seed_deduplicated_point(alias)

        settings = get_settings()
        store = QdrantVectorStore(qdrant_url=settings.qdrant_url)
        pre_records = store._client.retrieve(alias, [seed["point_id"]], with_payload=True)
        assert len(pre_records) == 1
        pre_payload = pre_records[0].payload

        result = reindex_collection(collection=alias, hybrid=False, refresh_payload=True)
        assert result["collection"] == alias
        assert result["new_physical"] != result["old_physical"]

        _assert_ledger_row_unchanged(alias, seed)

        # _build_payload_refresh_fn()'s _resolve() does
        # `new_payload = dict(old_payload); new_payload.update(cache[...])`
        # — this test proves that existing merge behavior does in fact keep
        # contributors/contributor_count intact (they are not part of
        # _resolve_document_payload_fields()'s output, so `.update()` never
        # touches them), NOT a code change.
        post_records = store._client.retrieve(alias, [seed["point_id"]], with_payload=True)
        assert len(post_records) == 1
        post_payload = post_records[0].payload
        assert post_payload["contributors"] == pre_payload["contributors"] == seed["contributors_before"]
        assert post_payload["contributor_count"] == pre_payload["contributor_count"] == 2
