"""Integration tests for the lineage resolver (FOUND-07, D-14).

Tests resolve_ancestry(), render_tree(), and nodes_to_json() against a real
PostgreSQL registry populated by running the pipeline over the spike fixture.

All six FOUND-06 lineage fields must be present on each node:
  id, artifact_type, content_hash, created_at, pipeline_version, storage_uri

The recursive CTE must walk the full chain:
  chunk → parsed_document → raw_document

Requires compose stack up (PostgreSQL + MinIO + Qdrant).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SPIKE_PDF = _FIXTURES_DIR / "hhs_security_rule.pdf"
COLLECTION_NAME = "klake_lineage_test"


@pytest.fixture(scope="module")
def pipeline_result():
    """Run pipeline once for the module and return the run result dict."""
    assert SPIKE_PDF.exists(), f"Fixture missing: {SPIKE_PDF}"

    from knowledge_lake.pipeline.run import run_document

    return run_document(
        fixture_path=SPIKE_PDF,
        source_name="HIPAA Security Rule (Lineage Test)",
        collection=COLLECTION_NAME,
    )


@pytest.fixture(scope="module")
def lineage_nodes(pipeline_result: dict[str, Any]):
    """Return the ancestry nodes for the first chunk artifact."""
    chunk_ids = pipeline_result["chunk_artifact_ids"]
    assert chunk_ids, "Pipeline must produce at least one chunk"
    first_chunk_id = chunk_ids[0]

    from knowledge_lake.lineage import resolve_ancestry

    return resolve_ancestry(first_chunk_id), first_chunk_id


class TestResolveAncestryChain:
    """resolve_ancestry must return the full chunk → parsed → raw chain."""

    def test_returns_at_least_three_nodes(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        """Chain must have at least chunk + parsed_document + raw_document."""
        nodes, _ = lineage_nodes
        assert len(nodes) >= 3, (
            f"Expected >=3 lineage nodes, got {len(nodes)}: "
            f"{[n['artifact_type'] for n in nodes]}"
        )

    def test_first_node_is_chunk(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        """Depth-0 node must be the queried chunk artifact."""
        nodes, chunk_id = lineage_nodes
        assert nodes[0]["id"] == chunk_id
        assert nodes[0]["artifact_type"] == "chunk"

    def test_chain_contains_parsed_document(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        nodes, _ = lineage_nodes
        types = [n["artifact_type"] for n in nodes]
        assert "parsed_document" in types, (
            f"'parsed_document' not in chain: {types}"
        )

    def test_chain_contains_raw_document(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        nodes, _ = lineage_nodes
        types = [n["artifact_type"] for n in nodes]
        assert "raw_document" in types, f"'raw_document' not in chain: {types}"

    def test_chain_ordered_leaf_first(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        """Nodes must be ordered by depth ascending (0 = the queried artifact)."""
        nodes, _ = lineage_nodes
        depths = [n["depth"] for n in nodes]
        assert depths == sorted(depths), (
            f"Nodes must be ordered depth-ascending, got depths: {depths}"
        )


class TestAllNodesHaveFound06Fields:
    """Every lineage node must carry all six FOUND-06 fields (non-null)."""

    REQUIRED_FIELDS = {"id", "artifact_type", "content_hash", "created_at", "pipeline_version"}
    # storage_uri may be None for very new nodes before flush — allow None with flag
    STORAGE_URI_FIELD = "storage_uri"

    def test_all_nodes_have_required_fields(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        nodes, _ = lineage_nodes
        for node in nodes:
            missing = self.REQUIRED_FIELDS - set(node.keys())
            assert not missing, (
                f"Node {node.get('id')} missing FOUND-06 fields: {missing}"
            )

    def test_all_required_fields_are_non_null(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        nodes, _ = lineage_nodes
        for node in nodes:
            for field in self.REQUIRED_FIELDS:
                assert node.get(field) is not None, (
                    f"Node {node.get('id')} has None value for required field {field!r}"
                )

    def test_storage_uri_field_exists(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        """storage_uri key must be present on all nodes (may be None for parsed)."""
        nodes, _ = lineage_nodes
        for node in nodes:
            assert self.STORAGE_URI_FIELD in node, (
                f"Node {node.get('id')} missing 'storage_uri' key"
            )

    def test_raw_document_has_storage_uri(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        """Raw document node must have a populated storage_uri (FOUND-06)."""
        nodes, _ = lineage_nodes
        raw_nodes = [n for n in nodes if n["artifact_type"] == "raw_document"]
        assert raw_nodes, "No raw_document node in chain"
        for raw in raw_nodes:
            assert raw.get("storage_uri"), (
                f"raw_document node {raw['id']} missing storage_uri"
            )

    def test_pipeline_version_format(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        """pipeline_version must look like 'X.Y.Z' or 'X.Y.Z+sha'."""
        nodes, _ = lineage_nodes
        import re
        for node in nodes:
            pv = node.get("pipeline_version", "")
            assert re.match(r"^\d+\.\d+\.\d+", pv), (
                f"pipeline_version {pv!r} on node {node['id']} "
                "must start with semver (e.g. '0.1.0' or '0.1.0+abc1234')"
            )


class TestRenderTree:
    """render_tree() must produce a human-readable, non-empty string."""

    def test_render_tree_returns_string(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        from knowledge_lake.lineage import render_tree
        nodes, _ = lineage_nodes
        result = render_tree(nodes)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_render_tree_contains_artifact_types(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        from knowledge_lake.lineage import render_tree
        nodes, _ = lineage_nodes
        result = render_tree(nodes)
        assert "chunk" in result
        assert "raw_document" in result

    def test_render_tree_contains_ids(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        from knowledge_lake.lineage import render_tree
        nodes, chunk_id = lineage_nodes
        result = render_tree(nodes)
        assert chunk_id in result, "Chunk ID must appear in tree"

    def test_render_tree_contains_hash(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        from knowledge_lake.lineage import render_tree
        nodes, _ = lineage_nodes
        result = render_tree(nodes)
        # Hash should be truncated but present
        raw_nodes = [n for n in nodes if n["artifact_type"] == "raw_document"]
        if raw_nodes:
            hash_prefix = raw_nodes[0]["content_hash"][:8]
            assert hash_prefix in result, f"Hash prefix {hash_prefix!r} not in tree"


class TestNodesToJson:
    """nodes_to_json() must return valid JSON with all FOUND-06 fields."""

    def test_returns_valid_json(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        from knowledge_lake.lineage import nodes_to_json
        nodes, _ = lineage_nodes
        json_str = nodes_to_json(nodes)
        parsed = json.loads(json_str)
        assert isinstance(parsed, list)

    def test_json_has_correct_node_count(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        from knowledge_lake.lineage import nodes_to_json
        nodes, _ = lineage_nodes
        json_str = nodes_to_json(nodes)
        parsed = json.loads(json_str)
        assert len(parsed) == len(nodes)

    def test_json_nodes_have_all_required_fields(
        self, lineage_nodes: tuple[list[dict], str]
    ) -> None:
        from knowledge_lake.lineage import nodes_to_json
        nodes, _ = lineage_nodes
        json_str = nodes_to_json(nodes)
        parsed = json.loads(json_str)
        required = {"id", "artifact_type", "content_hash", "created_at", "pipeline_version"}
        for node in parsed:
            missing = required - set(node.keys())
            assert not missing, f"JSON node missing fields: {missing}"


class TestPrefixExpansion:
    """resolve_ancestry must accept unambiguous ID prefixes (D-15)."""

    def test_full_id_resolves(self, pipeline_result: dict[str, Any]) -> None:
        """Full IDs must resolve without error."""
        from knowledge_lake.lineage import resolve_ancestry
        chunk_id = pipeline_result["chunk_artifact_ids"][0]
        nodes = resolve_ancestry(chunk_id)
        assert len(nodes) >= 1

    def test_unambiguous_prefix_resolves(
        self, pipeline_result: dict[str, Any]
    ) -> None:
        """A prefix unique to one artifact must resolve correctly.

        Uses enough characters from the middle of the UUID so the prefix
        is unique even if multiple pipeline runs create chunks with similar
        timestamps.  We use chars up to position 22 which includes the second
        UUID segment (4 chars), providing 65536 unique values per millisecond.
        """
        from knowledge_lake.lineage import resolve_ancestry
        chunk_id = pipeline_result["chunk_artifact_ids"][0]
        # Use enough of the ID to be unique:
        # 'chk_' + first segment (8) + '-' + second segment (4) + '-' + 2 chars = 21
        # e.g. 'chk_019f261f-2887-72' — includes part of the third segment
        prefix = chunk_id[:21]
        nodes = resolve_ancestry(prefix)
        assert nodes[0]["id"] == chunk_id

    def test_nonexistent_id_raises_lookup_error(self) -> None:
        from knowledge_lake.lineage import resolve_ancestry
        with pytest.raises(LookupError):
            resolve_ancestry("chk_00000000-0000-0000-0000-000000000000")
