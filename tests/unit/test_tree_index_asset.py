"""Tests for dagster_defs/assets.py — tree_index_document asset (TREE-05).

Verifies that tree_index_document is a thin shell over pipeline.tree_index.tree_index()
that fans out from the clean_document dict in parallel to chunk_document and
enrich_document (same input shape).

Tests fail with ImportError until Plan 13-06 ships — that is the correct RED state
for Wave 0.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from knowledge_lake.dagster_defs.assets import tree_index_document
from knowledge_lake.pipeline.tree_index import tree_index
from knowledge_lake.plugins.protocols import ParsedDoc, Section


# ── TestTreeIndexDocumentAsset ────────────────────────────────────────────────


class TestTreeIndexDocumentAsset:
    """Tests for the tree_index_document Dagster asset (TREE-05)."""

    def _make_clean_document(self) -> dict:
        """Construct a minimal clean_document dict matching the fan-out input shape."""
        return {
            "parsed_artifact_id": "prs_test_001",
            "source_id": "src_test_001",
            "parsed_doc": ParsedDoc(
                text="Minimal test document.",
                sections=[
                    Section(heading="Introduction", section_path="§1", page=1),
                ],
                metadata={"title": "Test Doc", "page_count": 2},
            ),
        }

    def _make_mock_resources(self):
        """Return mock Postgres, MinIO, and LiteLLM resources."""
        postgres = MagicMock()
        postgres.database_url = "sqlite:///:memory:"
        minio = MagicMock()
        minio.endpoint_url = "http://localhost:9000"
        minio.bucket = "test-bucket"
        minio.access_key_id = "minio"
        minio.secret_access_key = "minio123"
        minio.region = "us-east-1"
        litellm_resource = MagicMock()
        litellm_resource.litellm_url = "http://localhost:4000"
        return postgres, minio, litellm_resource

    def test_asset_calls_pipeline(self) -> None:
        """tree_index_document delegates entirely to pipeline.tree_index.tree_index()
        and returns the pipeline result dict unchanged (thin shell — no added logic).

        Verifies TREE-05: asset is a thin shell with no duplicated logic.
        """
        clean_document = self._make_clean_document()
        postgres, minio, litellm_resource = self._make_mock_resources()

        expected_result = {
            "artifact_id": "idx_result_001",
            "status": "tree_indexed",
            "cached": False,
        }
        mock_pipeline_fn = MagicMock(return_value=expected_result)

        with patch("knowledge_lake.pipeline.tree_index.tree_index", mock_pipeline_fn):
            result = tree_index_document(
                clean_document=clean_document,
                postgres=postgres,
                minio=minio,
                litellm=litellm_resource,
            )

        # Asset must return the same dict the pipeline function returned
        assert result == expected_result, (
            f"tree_index_document must return pipeline result unchanged, "
            f"got {result!r}"
        )
        # Pipeline function must have been called exactly once
        assert mock_pipeline_fn.call_count == 1, (
            "pipeline.tree_index.tree_index must be called exactly once by the asset"
        )
        # Pipeline must have received the correct identifiers from clean_document
        call_kwargs = mock_pipeline_fn.call_args
        # Allow either positional or keyword args
        if call_kwargs.args:
            assert call_kwargs.args[0] == clean_document["parsed_artifact_id"]
            assert call_kwargs.args[1] == clean_document["source_id"]
        else:
            assert call_kwargs.kwargs.get("parsed_artifact_id") == clean_document["parsed_artifact_id"]
            assert call_kwargs.kwargs.get("source_id") == clean_document["source_id"]

    def test_asset_input_shape_matches_chunk_document(self) -> None:
        """tree_index_document's function signature accepts clean_document as its
        first positional parameter, matching chunk_document's fan-out input shape.

        Verifies TREE-05: parallel fan-out from clean_document.
        """
        from knowledge_lake.dagster_defs.assets import chunk_document

        # Inspect parameter names
        tree_sig = inspect.signature(tree_index_document.op.compute_fn.decorated_fn)
        chunk_sig = inspect.signature(chunk_document.op.compute_fn.decorated_fn)

        tree_params = list(tree_sig.parameters.keys())
        chunk_params = list(chunk_sig.parameters.keys())

        # Both assets must accept clean_document as a parameter
        assert "clean_document" in tree_params, (
            f"tree_index_document must accept 'clean_document' parameter, "
            f"got {tree_params!r}"
        )
        assert "clean_document" in chunk_params, (
            f"chunk_document must accept 'clean_document' parameter for fan-out parity, "
            f"got {chunk_params!r}"
        )
