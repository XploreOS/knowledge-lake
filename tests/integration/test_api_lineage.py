"""Integration tests for FastAPI search + lineage endpoints (FOUND-07 API, D-02).

Tests the /search and /lineage/{artifact_id} endpoints against a seeded registry.
Uses FastAPI's TestClient to drive the endpoints without spinning up a server.

Requirements:
    - Compose stack must be up (PostgreSQL + MinIO + Qdrant).
    - Uses the local embedder (SentenceTransformerEmbedder, 384-dim, zero creds).

Endpoints tested:
    GET /search?q=...&top_k=...   — returns hits with score + citation
    GET /lineage/{artifact_id}    — returns the six-field lineage graph
    GET /lineage/{unknown_id}     — returns 404 with clear error body
    GET /openapi.json             — OpenAPI spec lists both endpoints
    GET /health                   — remains healthy after new endpoints added
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SPIKE_PDF = _FIXTURES_DIR / "hhs_security_rule.pdf"
COLLECTION_NAME = "klake_api_test"

# Six FOUND-06 fields required on every lineage node
FOUND_06_FIELDS = {"id", "artifact_type", "content_hash", "created_at", "pipeline_version", "storage_uri"}


@pytest.fixture(scope="module")
def pipeline_result():
    """Run pipeline once for the module — seeds registry + Qdrant for all API tests."""
    assert SPIKE_PDF.exists(), f"Fixture missing: {SPIKE_PDF}"

    from knowledge_lake.pipeline.run import run_document

    return run_document(
        fixture_path=SPIKE_PDF,
        source_name="HIPAA Security Rule (API Test)",
        collection=COLLECTION_NAME,
    )


@pytest.fixture(scope="module")
def api_client(pipeline_result):
    """Return a TestClient for the FastAPI app, with pipeline_result already seeded."""
    from knowledge_lake.api.app import app

    # TestClient works synchronously over ASGI — no server startup needed.
    with TestClient(app) as client:
        yield client, pipeline_result


class TestHealthStillWorks:
    """Health endpoint must remain healthy after adding search + lineage."""

    def test_health_returns_ok(self, api_client) -> None:
        client, _ = api_client
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestSearchEndpoint:
    """GET /search?q=...&top_k=... — returns hits with score + citation."""

    def test_search_returns_200(self, api_client) -> None:
        client, _ = api_client
        resp = client.get("/search", params={"q": "administrative safeguards", "top_k": 3})
        assert resp.status_code == 200

    def test_search_returns_hits(self, api_client) -> None:
        client, _ = api_client
        resp = client.get("/search", params={"q": "administrative safeguards", "top_k": 3})
        hits = resp.json()
        assert isinstance(hits, list), f"Expected list, got {type(hits)}"
        assert len(hits) >= 1, "Expected at least one search hit"

    def test_search_hit_has_score(self, api_client) -> None:
        """Each hit must carry a float score in [0, 1]."""
        client, _ = api_client
        resp = client.get("/search", params={"q": "administrative safeguards", "top_k": 3})
        hits = resp.json()
        for hit in hits:
            assert "score" in hit, f"Hit missing 'score': {hit.keys()}"
            score = hit["score"]
            assert isinstance(score, float), f"score must be float, got {type(score)}"
            assert 0.0 <= score <= 1.0, f"score out of [0, 1]: {score}"

    def test_search_hit_has_citation_fields(self, api_client) -> None:
        """Each hit must carry citation fields: document, section_path, page."""
        client, _ = api_client
        resp = client.get("/search", params={"q": "administrative safeguards", "top_k": 3})
        hits = resp.json()
        for hit in hits:
            assert "document" in hit, f"Hit missing 'document': {hit.keys()}"
            assert "section_path" in hit, f"Hit missing 'section_path': {hit.keys()}"
            assert "page" in hit, f"Hit missing 'page': {hit.keys()}"
            assert "chunk_id" in hit, f"Hit missing 'chunk_id': {hit.keys()}"

    def test_search_top_k_limits_results(self, api_client) -> None:
        """top_k parameter must be respected."""
        client, _ = api_client
        resp = client.get("/search", params={"q": "technical safeguards", "top_k": 2})
        hits = resp.json()
        assert len(hits) <= 2, f"Expected ≤2 hits for top_k=2, got {len(hits)}"

    def test_search_default_top_k(self, api_client) -> None:
        """Without top_k, endpoint uses its default (should not crash)."""
        client, _ = api_client
        resp = client.get("/search", params={"q": "security rule"})
        assert resp.status_code == 200

    def test_search_empty_query_returns_empty(self, api_client) -> None:
        """Empty/whitespace query must return empty list, not error."""
        client, _ = api_client
        resp = client.get("/search", params={"q": "   "})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_search_top_k_validation_rejects_zero(self, api_client) -> None:
        """top_k=0 should return 422 (pydantic validation, V5 ASVS)."""
        client, _ = api_client
        resp = client.get("/search", params={"q": "anything", "top_k": 0})
        assert resp.status_code == 422

    def test_search_top_k_validation_rejects_negative(self, api_client) -> None:
        """top_k=-1 should return 422."""
        client, _ = api_client
        resp = client.get("/search", params={"q": "anything", "top_k": -1})
        assert resp.status_code == 422

    def test_search_top_k_validation_rejects_too_large(self, api_client) -> None:
        """top_k > 100 should return 422 (DoS guard)."""
        client, _ = api_client
        resp = client.get("/search", params={"q": "anything", "top_k": 999})
        assert resp.status_code == 422


class TestLineageEndpoint:
    """GET /lineage/{artifact_id} — returns six-field lineage graph."""

    @pytest.fixture(scope="class")
    def chunk_id(self, pipeline_result) -> str:
        chunk_ids = pipeline_result["chunk_artifact_ids"]
        assert chunk_ids, "Pipeline must produce at least one chunk"
        return chunk_ids[0]

    def test_lineage_returns_200(self, api_client, chunk_id: str) -> None:
        client, _ = api_client
        resp = client.get(f"/lineage/{chunk_id}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_lineage_returns_json_array(self, api_client, chunk_id: str) -> None:
        client, _ = api_client
        resp = client.get(f"/lineage/{chunk_id}")
        data = resp.json()
        assert isinstance(data, list), f"Expected list of lineage nodes, got {type(data)}"

    def test_lineage_has_at_least_three_nodes(self, api_client, chunk_id: str) -> None:
        """Chain must cover chunk → parsed_document → raw_document."""
        client, _ = api_client
        resp = client.get(f"/lineage/{chunk_id}")
        nodes = resp.json()
        assert len(nodes) >= 3, (
            f"Expected ≥3 lineage nodes (chunk+parsed+raw), got {len(nodes)}: "
            f"{[n.get('artifact_type') for n in nodes]}"
        )

    def test_lineage_nodes_have_six_found06_fields(self, api_client, chunk_id: str) -> None:
        """Every node must carry all six FOUND-06 fields."""
        client, _ = api_client
        resp = client.get(f"/lineage/{chunk_id}")
        nodes = resp.json()
        for i, node in enumerate(nodes):
            for field in FOUND_06_FIELDS:
                assert field in node, (
                    f"Node {i} (type={node.get('artifact_type')}) missing FOUND-06 field {field!r}. "
                    f"Keys present: {list(node.keys())}"
                )

    def test_lineage_first_node_is_requested_chunk(self, api_client, chunk_id: str) -> None:
        """Depth-0 node must be the queried artifact."""
        client, _ = api_client
        resp = client.get(f"/lineage/{chunk_id}")
        nodes = resp.json()
        assert nodes[0]["id"] == chunk_id, (
            f"First node id {nodes[0]['id']!r} != requested chunk_id {chunk_id!r}"
        )
        assert nodes[0]["artifact_type"] == "chunk", (
            f"First node type must be 'chunk', got {nodes[0]['artifact_type']!r}"
        )

    def test_lineage_chain_contains_raw_document(self, api_client, chunk_id: str) -> None:
        client, _ = api_client
        resp = client.get(f"/lineage/{chunk_id}")
        nodes = resp.json()
        types = [n["artifact_type"] for n in nodes]
        assert "raw_document" in types, f"Expected 'raw_document' in lineage chain, got {types}"

    def test_lineage_nodes_have_nonempty_content_hash(self, api_client, chunk_id: str) -> None:
        client, _ = api_client
        resp = client.get(f"/lineage/{chunk_id}")
        nodes = resp.json()
        for node in nodes:
            assert node["content_hash"], (
                f"Node {node['id']} has empty content_hash"
            )


class TestLineageNotFound:
    """GET /lineage/{unknown_id} — must return 404 with clear error body."""

    def test_unknown_id_returns_404(self, api_client) -> None:
        client, _ = api_client
        fake_id = "chk_00000000-0000-0000-0000-000000000000"
        resp = client.get(f"/lineage/{fake_id}")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"

    def test_404_body_has_detail_field(self, api_client) -> None:
        client, _ = api_client
        fake_id = "chk_00000000-0000-0000-0000-000000000001"
        resp = client.get(f"/lineage/{fake_id}")
        body = resp.json()
        assert "detail" in body, f"404 body must have 'detail' field, got keys: {list(body.keys())}"
        assert body["detail"], "404 detail must not be empty"


class TestOpenAPISpec:
    """OpenAPI docs must list both new endpoints."""

    def test_openapi_json_served(self, api_client) -> None:
        client, _ = api_client
        resp = client.get("/openapi.json")
        assert resp.status_code == 200

    def test_openapi_lists_search_endpoint(self, api_client) -> None:
        client, _ = api_client
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/search" in paths, f"/search not in OpenAPI paths: {list(paths.keys())}"

    def test_openapi_lists_lineage_endpoint(self, api_client) -> None:
        client, _ = api_client
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert any("lineage" in p for p in paths), (
            f"No /lineage endpoint in OpenAPI paths: {list(paths.keys())}"
        )

    def test_openapi_lists_health_endpoint(self, api_client) -> None:
        """Health endpoint must remain in OpenAPI spec."""
        client, _ = api_client
        spec = client.get("/openapi.json").json()
        paths = spec.get("paths", {})
        assert "/health" in paths, f"/health not in OpenAPI paths: {list(paths.keys())}"
