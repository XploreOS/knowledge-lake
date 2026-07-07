"""Unit tests for Dagster RetryPolicy on all 12 pipeline and export assets.

Validates that every @asset in assets.py has a retry_policy argument configured
correctly: pipeline group assets use max_retries=2, export group assets use
max_retries=1 (per RESEARCH.md §IFACE-03 and T-06-12 threat mitigation).
"""

from __future__ import annotations

import pytest


# ── Pipeline assets (9) ───────────────────────────────────────────────────────

class TestPipelineAssetsHaveRetryPolicy:
    """All 9 pipeline group assets must have retry_policy set."""

    def _get_pipeline_assets(self):
        from knowledge_lake.dagster_defs.assets import (
            ingest_raw_document,
            parsed_document,
            clean_document,
            chunk_document,
            enrich_document,
            curate_document_asset,
            generate_dataset,
            embed_chunks,
            index_chunks,
        )
        return [
            ingest_raw_document,
            parsed_document,
            clean_document,
            chunk_document,
            enrich_document,
            curate_document_asset,
            generate_dataset,
            embed_chunks,
            index_chunks,
        ]

    def test_all_pipeline_assets_have_retry_policy(self) -> None:
        """All 9 pipeline assets must have retry_policy set (not None).

        Note: Dagster's AssetsDefinition exposes retry_policy via
        asset.node_def.retry_policy (set by the @asset(retry_policy=...) decorator arg).
        """
        pipeline_assets = self._get_pipeline_assets()
        for a in pipeline_assets:
            retry = a.node_def.retry_policy
            assert retry is not None, (
                f"Asset {a.key} is missing retry_policy — "
                "all pipeline assets must have RetryPolicy configured (IFACE-03)"
            )

    def test_pipeline_retry_policy_max_retries(self) -> None:
        """Pipeline assets must have retry_policy.max_retries == 2."""
        pipeline_assets = self._get_pipeline_assets()
        for a in pipeline_assets:
            retry = a.node_def.retry_policy
            assert retry is not None, f"Asset {a.key} has no retry_policy"
            assert retry.max_retries == 2, (
                f"Asset {a.key} retry_policy.max_retries == {retry.max_retries}, "
                "expected 2 for pipeline assets"
            )


# ── Export assets (3) ─────────────────────────────────────────────────────────

class TestExportAssetsHaveRetryPolicy:
    """All 3 export group assets must have retry_policy set with max_retries=1."""

    def _get_export_assets(self):
        from knowledge_lake.dagster_defs.assets import (
            export_rag_corpus,
            export_pretrain_corpus,
            export_finetune_dataset,
        )
        return [export_rag_corpus, export_pretrain_corpus, export_finetune_dataset]

    def test_all_export_assets_have_retry_policy(self) -> None:
        """All 3 export assets must have retry_policy set (not None).

        Note: Dagster's AssetsDefinition exposes retry_policy via
        asset.node_def.retry_policy (set by the @asset(retry_policy=...) decorator arg).
        """
        export_assets = self._get_export_assets()
        for a in export_assets:
            retry = a.node_def.retry_policy
            assert retry is not None, (
                f"Asset {a.key} is missing retry_policy — "
                "export assets must use RetryPolicy(max_retries=1) "
                "(T-06-12: TrainEvalContaminationError is not transient)"
            )

    def test_export_retry_policy_max_retries(self) -> None:
        """Export assets must have retry_policy.max_retries == 1 (T-06-12)."""
        export_assets = self._get_export_assets()
        for a in export_assets:
            retry = a.node_def.retry_policy
            assert retry is not None, f"Asset {a.key} has no retry_policy"
            assert retry.max_retries == 1, (
                f"Asset {a.key} retry_policy.max_retries == {retry.max_retries}, "
                "expected 1 for export assets (TrainEvalContaminationError is not transient, T-06-12)"
            )
