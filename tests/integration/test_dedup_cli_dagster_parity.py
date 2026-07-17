"""Integration test: D-18 CLI/Dagster point-ID and ledger-state parity (DEDUP-01/02/03).

Proves, against the live dev Postgres + Qdrant stack (no mocks), that the two
wired call sites — CLI/API/MCP (``process_crawled()``, Plan 21-06) and Dagster
(``dedup_chunks``/``embed_chunks``/``index_chunks`` assets, Plan 21-07) —
produce identical, deterministic point IDs for identical text, and that each
path's own ``chunk_dedup_ledger`` row correctly reflects a single dedup event
(``contributor_count == 2``) after a second document contributes the same
text.

D-18: "parity is enforced by test, not by shared function" — so this test
independently recomputes the EXPECTED point_id via ``point_id_for_text()``
rather than only cross-checking the two paths against each other (agreeing
with each other while both being wrong would pass a weaker test).

The Dagster path is exercised via DIRECT INVOCATION of the real
``dedup_chunks``/``embed_chunks``/``index_chunks`` asset functions (a
standard, Dagster-documented testing pattern — the ``@asset``-decorated
function objects remain plain-callable) rather than a full
``dagster.materialize()`` graph run from raw ingest. This avoids needing a
real parseable document fixture (this test's focus is the DEDUP layer, not
parsing/ingest) while still calling the exact production asset code, with
real ``PostgresResource``/``QdrantResource`` instances, against the live
stack — not mocks of the assets.

Run with:
    uv run pytest tests/integration/test_dedup_cli_dagster_parity.py -v -m integration
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import delete

from knowledge_lake.config.settings import get_settings
from knowledge_lake.pipeline.dedup import point_id_for_text, text_sha256_for
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.registry.models import ChunkDedupLedger

pytestmark = pytest.mark.integration

# At least 30 characters, distinct from other fixtures in the suite.
SHARED_BOILERPLATE_TEXT = (
    "This site uses cookies to improve your browsing experience. By continuing "
    "to use this site you consent to our cookie policy and privacy notice."
)


def _cleanup_collection(alias_name: str) -> None:
    """Best-effort teardown: drop every physical collection version behind
    ``alias_name`` and delete this test's ledger rows, mirroring
    ``test_qdrant_alias_reindex.py``'s ``alias`` fixture teardown pattern."""
    from knowledge_lake.plugins.builtin.qdrant_store import QdrantVectorStore

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


@pytest.fixture(scope="class")
def parity_run() -> Iterator[dict]:
    """Process the SAME shared boilerplate text, as two separate documents
    each, through BOTH the CLI path and the Dagster path — each into its own
    collection (D-12: the ledger is scoped by collection, so the two paths
    must never share a collection or they'd interfere with each other's
    ledger rows).
    """
    cli_collection = f"test_dedup_cli_{uuid4().hex[:8]}"
    dagster_collection = f"test_dedup_dagster_{uuid4().hex[:8]}"

    # ── CLI/API/MCP path (Plan 21-06's exact call shape: dedup_chunks() ->
    # embed() -> index(), the same three calls process_crawled() makes) ──
    from knowledge_lake.pipeline.dedup import dedup_chunks
    from knowledge_lake.pipeline.embed import embed
    from knowledge_lake.pipeline.index import index

    for doc_id, chunk_id in (
        ("doc_dedup_parity_cli_1", "chk_dedup_parity_cli_1"),
        ("doc_dedup_parity_cli_2", "chk_dedup_parity_cli_2"),
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
            chunks_list, doc_id, "src_dedup_parity_cli", collection=cli_collection
        )
        vectors, dim = embed(dedup_result["new"])
        index(
            dedup_result["new"],
            vectors,
            dim,
            doc_id,
            collection=cli_collection,
            duplicate_chunks=dedup_result["duplicates"],
        )

    # ── Dagster path (Plan 21-07's exact asset chain, direct invocation
    # against the real assets with real resources) ──
    from knowledge_lake.dagster_defs.assets import (
        dedup_chunks as dagster_dedup_chunks,
    )
    from knowledge_lake.dagster_defs.assets import (
        embed_chunks as dagster_embed_chunks,
    )
    from knowledge_lake.dagster_defs.assets import (
        index_chunks as dagster_index_chunks,
    )
    from knowledge_lake.dagster_defs.resources import PostgresResource, QdrantResource

    settings = get_settings()
    postgres = PostgresResource(database_url=settings.database_url)
    qdrant = QdrantResource(qdrant_url=settings.qdrant_url)

    for doc_id, chunk_id in (
        ("doc_dedup_parity_dagster_1", "chk_dedup_parity_dagster_1"),
        ("doc_dedup_parity_dagster_2", "chk_dedup_parity_dagster_2"),
    ):
        chunk_document = {
            "chunks": [
                {
                    "chunk_id": chunk_id,
                    "text": SHARED_BOILERPLATE_TEXT,
                    "section_path": "s1",
                    "page": 1,
                }
            ],
            "parsed_artifact_id": doc_id,
            "source_id": "src_dedup_parity_dagster",
            "collection": dagster_collection,
        }
        dedup_out = dagster_dedup_chunks(chunk_document=chunk_document, postgres=postgres)
        embed_out = dagster_embed_chunks(dedup_chunks=dedup_out)
        dagster_index_chunks(embed_chunks=embed_out, qdrant=qdrant)

    yield {"cli_collection": cli_collection, "dagster_collection": dagster_collection}

    _cleanup_collection(cli_collection)
    _cleanup_collection(dagster_collection)


class TestDedupCliDagsterPointIdLedgerParity:
    """D-18: parity between the CLI path and the Dagster path, proven by test."""

    def test_point_id_is_deterministic_and_present_in_both_collections(
        self, parity_run: dict
    ) -> None:
        """The independently-computed expected point_id must equal the
        actual point_id in BOTH the CLI-path ledger row AND the Dagster-path
        ledger row, and a real Qdrant point must exist under that ID in
        EACH collection — proving determinism holds across both call
        sites (not merely that the two paths agree with each other, which
        could both be wrong)."""
        from knowledge_lake.plugins.builtin.qdrant_store import QdrantVectorStore

        expected_point_id = point_id_for_text(SHARED_BOILERPLATE_TEXT)
        text_sha256 = text_sha256_for(SHARED_BOILERPLATE_TEXT)

        settings = get_settings()
        store = QdrantVectorStore(qdrant_url=settings.qdrant_url)

        for collection in (parity_run["cli_collection"], parity_run["dagster_collection"]):
            with get_session() as session:
                ledger_row = registry_repo.get_dedup_ledger_entry(
                    session, collection=collection, text_sha256=text_sha256
                )
                assert ledger_row is not None, (
                    f"No dedup ledger row found for collection={collection!r}"
                )
                assert ledger_row.point_id == expected_point_id, (
                    f"collection={collection!r}: ledger point_id "
                    f"{ledger_row.point_id!r} != independently-computed "
                    f"point_id_for_text() {expected_point_id!r}"
                )

            records = store._client.retrieve(collection, [expected_point_id])
            assert len(records) == 1, (
                f"collection={collection!r}: expected exactly one Qdrant point "
                f"at the deterministic point_id {expected_point_id!r}, found "
                f"{len(records)}"
            )

    def test_contributor_count_is_two_for_both_paths(self, parity_run: dict) -> None:
        """Each collection's ledger row for the shared text must show
        contributor_count == 2 — proving the SECOND document's chunk was
        recognized as a duplicate on BOTH paths, not just the first."""
        text_sha256 = text_sha256_for(SHARED_BOILERPLATE_TEXT)

        for collection in (parity_run["cli_collection"], parity_run["dagster_collection"]):
            with get_session() as session:
                ledger_row = registry_repo.get_dedup_ledger_entry(
                    session, collection=collection, text_sha256=text_sha256
                )
                assert ledger_row is not None
                assert ledger_row.contributor_count == 2, (
                    f"collection={collection!r}: expected contributor_count == 2 "
                    f"(2 documents processed, same text), got "
                    f"{ledger_row.contributor_count}"
                )
                assert len(ledger_row.contributors) == 2

    def test_text_sha256_identical_across_cli_and_dagster_ledger_rows(
        self, parity_run: dict
    ) -> None:
        """The text_sha256 column value must be IDENTICAL between the
        CLI-path ledger row and the Dagster-path ledger row (same text, same
        hash) even though the two rows differ by collection/point_id/
        primary_* fields (D-12: each collection gets its own row) —
        confirming the underlying hash/normalization logic is identical
        across both invocation paths."""
        expected_text_sha256 = text_sha256_for(SHARED_BOILERPLATE_TEXT)

        with get_session() as session:
            cli_row = registry_repo.get_dedup_ledger_entry(
                session,
                collection=parity_run["cli_collection"],
                text_sha256=expected_text_sha256,
            )
            dagster_row = registry_repo.get_dedup_ledger_entry(
                session,
                collection=parity_run["dagster_collection"],
                text_sha256=expected_text_sha256,
            )
            assert cli_row is not None
            assert dagster_row is not None
            assert cli_row.text_sha256 == dagster_row.text_sha256 == expected_text_sha256
