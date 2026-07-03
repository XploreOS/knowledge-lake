"""End-to-end smoke test for the walking skeleton demo (D-03, D-05).

This is the phase-level acceptance test.  It expresses the full acceptance
criteria for Plan 05:

  - One real document (HIPAA Security Rule PDF) flows ingest → parse → chunk
    → embed → index → search in-process using the cached fixture (D-05).
  - The fixed demo query "what are administrative safeguards" returns hits
    with score and citation fields (document, section_path, page).
  - The lineage of a returned chunk resolves back to source:
      chunk → parsed_document → raw_document → source
    Each node carries all six FOUND-06 fields.

This test is RED before Tasks 2-3 land.  That is intentional — it encodes the
end-state we are driving toward (D-03, TDD red step).

Requirements:
    - Compose stack must be up (PostgreSQL + MinIO + Qdrant).
    - Uses the local embedder (SentenceTransformerEmbedder, 384-dim, zero creds).
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path
from typing import Any

# Fixture PDF path — committed to tests/fixtures/ for hermetic testing (D-05)
_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SPIKE_PDF = _FIXTURES_DIR / "hhs_security_rule.pdf"

# Fixed demo query (D-07)
DEMO_QUERY = "what are administrative safeguards"

# Collection name used by the spike
COLLECTION_NAME = "klake_spike"


@pytest.fixture(scope="module")
def pipeline_run_result():
    """Run the pipeline over the spike PDF fixture and return the run result.

    This fixture executes ingest → parse → chunk → embed → index once for the
    module and caches the result for all tests in this module.

    Returns:
        dict with keys: source_id, raw_artifact_id, parsed_artifact_id,
        chunk_artifact_ids (list), collection_name.
    """
    assert SPIKE_PDF.exists(), (
        f"Spike fixture PDF not found at {SPIKE_PDF}. "
        "Ensure tests/fixtures/hhs_security_rule.pdf is committed."
    )

    from knowledge_lake.pipeline.run import run_document

    result = run_document(
        fixture_path=SPIKE_PDF,
        collection=COLLECTION_NAME,
    )
    return result


@pytest.fixture(scope="module")
def search_hits(pipeline_run_result: dict[str, Any]):
    """Run the fixed demo query and return the search hits."""
    from knowledge_lake.pipeline.search import search

    hits = search(
        query=DEMO_QUERY,
        collection=COLLECTION_NAME,
        top_k=5,
    )
    return hits


class TestSearchResultsHaveCorrectShape:
    """The fixed demo query must return hits with score and citation fields."""

    def test_search_returns_at_least_one_hit(
        self, search_hits: list[Any]
    ) -> None:
        assert len(search_hits) >= 1, (
            f"Expected at least one hit for query {DEMO_QUERY!r}, got 0"
        )

    def test_each_hit_has_a_score(self, search_hits: list[Any]) -> None:
        for hit in search_hits:
            assert hasattr(hit, "score"), f"Hit missing .score: {hit}"
            assert isinstance(hit.score, float), (
                f"hit.score must be float, got {type(hit.score)}"
            )
            assert 0.0 <= hit.score <= 1.0, (
                f"hit.score out of [0, 1] range: {hit.score}"
            )

    def test_each_hit_has_document_citation(self, search_hits: list[Any]) -> None:
        for hit in search_hits:
            payload = hit.payload
            assert "document" in payload, (
                f"Hit payload missing 'document' citation field: {payload}"
            )
            assert payload["document"], "Hit 'document' citation field must be non-empty"

    def test_each_hit_has_section_path_citation(
        self, search_hits: list[Any]
    ) -> None:
        for hit in search_hits:
            payload = hit.payload
            assert "section_path" in payload, (
                f"Hit payload missing 'section_path' citation field: {payload}"
            )

    def test_each_hit_has_page_citation(self, search_hits: list[Any]) -> None:
        for hit in search_hits:
            payload = hit.payload
            assert "page" in payload, (
                f"Hit payload missing 'page' citation field: {payload}"
            )
            assert isinstance(payload["page"], int), (
                f"'page' must be int, got {type(payload['page'])}"
            )

    def test_each_hit_has_chunk_id(self, search_hits: list[Any]) -> None:
        for hit in search_hits:
            payload = hit.payload
            assert "chunk_id" in payload, (
                f"Hit payload missing 'chunk_id' citation field: {payload}"
            )


class TestLineageResolvesFullChain:
    """The lineage of a returned chunk must walk back to source with all FOUND-06 fields."""

    def test_top_hit_lineage_resolves_chunk_to_source(
        self,
        search_hits: list[Any],
    ) -> None:
        """chunk → parsed_document → raw_document → source chain must resolve."""
        assert len(search_hits) >= 1, "Need at least one hit for lineage test"

        top_hit = search_hits[0]
        chunk_id = top_hit.payload.get("chunk_id") or top_hit.id

        from knowledge_lake.lineage import resolve_ancestry

        nodes = resolve_ancestry(chunk_id)
        assert len(nodes) >= 3, (
            f"Expected at least 3 lineage nodes (chunk→parsed→raw), got {len(nodes)}: "
            f"{[n.get('artifact_type') for n in nodes]}"
        )

    def test_lineage_chain_contains_expected_types(
        self, search_hits: list[Any]
    ) -> None:
        """Chain must include chunk, parsed_document, raw_document nodes."""
        top_hit = search_hits[0]
        chunk_id = top_hit.payload.get("chunk_id") or top_hit.id

        from knowledge_lake.lineage import resolve_ancestry

        nodes = resolve_ancestry(chunk_id)
        artifact_types = {n["artifact_type"] for n in nodes}
        assert "chunk" in artifact_types, (
            f"'chunk' not found in lineage chain types: {artifact_types}"
        )
        assert "raw_document" in artifact_types, (
            f"'raw_document' not found in lineage chain types: {artifact_types}"
        )

    def test_each_lineage_node_has_six_found_06_fields(
        self, search_hits: list[Any]
    ) -> None:
        """Every node must carry all six FOUND-06 lineage fields."""
        top_hit = search_hits[0]
        chunk_id = top_hit.payload.get("chunk_id") or top_hit.id

        from knowledge_lake.lineage import resolve_ancestry

        nodes = resolve_ancestry(chunk_id)
        required_fields = {
            "id",
            "artifact_type",
            "content_hash",
            "created_at",
            "pipeline_version",
            "storage_uri",
        }
        for node in nodes:
            missing = required_fields - set(node.keys())
            assert not missing, (
                f"Lineage node {node.get('id')} missing FOUND-06 fields: {missing}"
            )


class TestPipelineProducedCorrectArtifacts:
    """Verify the pipeline run produced the expected artifact chain."""

    def test_run_result_has_source_id(
        self, pipeline_run_result: dict[str, Any]
    ) -> None:
        assert "source_id" in pipeline_run_result
        assert pipeline_run_result["source_id"].startswith("src_")

    def test_run_result_has_raw_artifact_id(
        self, pipeline_run_result: dict[str, Any]
    ) -> None:
        assert "raw_artifact_id" in pipeline_run_result
        assert pipeline_run_result["raw_artifact_id"].startswith("doc_")

    def test_run_result_has_chunk_artifact_ids(
        self, pipeline_run_result: dict[str, Any]
    ) -> None:
        chunk_ids = pipeline_run_result.get("chunk_artifact_ids", [])
        assert len(chunk_ids) >= 1, "Pipeline must produce at least one chunk"
        for cid in chunk_ids:
            assert cid.startswith("chk_"), (
                f"Chunk ID must start with 'chk_', got {cid!r}"
            )
