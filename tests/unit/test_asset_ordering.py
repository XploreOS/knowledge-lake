"""Unit tests for the KL-06 asset ordering fix (clean -> enrich -> curate -> chunk).

D-01 originally made enrich_document and curate_document_asset parallel
branches off clean_document that "did not block" chunk_document. That was
false parallelism: curate reads the enriched sibling for the 40% enrich term
of its composite score and silently substitutes a hardcoded 0.5 default when
enrichment hasn't run yet, and index reads the enriched sibling at runtime for
the payload. Whichever branch Dagster happened to schedule first changed the
composite score by 21% on the same document (E2E-GAP-ANALYSIS.md KL-06).

These tests assert the non-data ``deps=[...]`` edges exist directly on the
AssetsDefinition objects (curate depends on enrich; chunk depends on curate)
AND that the full registered asset graph (knowledge_lake.dagster_defs.definitions.defs)
reflects the same edges transitively — this is the regression guard against
the scheduling race silently returning, since it fails loud if a future
refactor drops a ``deps=`` entry rather than relying on flaky timing-based
assertions.
"""

from __future__ import annotations

from dagster import AssetKey


class TestCurateDependsOnEnrich:
    """curate_document_asset must declare a non-data dependency on enrich_document."""

    def test_curate_dependency_keys_include_enrich_document(self) -> None:
        from knowledge_lake.dagster_defs.assets import curate_document_asset

        assert AssetKey("enrich_document") in curate_document_asset.dependency_keys, (
            "curate_document_asset must depend on enrich_document (KL-06) — "
            f"got dependency_keys={curate_document_asset.dependency_keys}"
        )

    def test_curate_still_takes_clean_document_as_data_input(self) -> None:
        """The DATA input must stay clean_document — only ordering was added (locked design)."""
        from knowledge_lake.dagster_defs.assets import curate_document_asset

        assert AssetKey("clean_document") in curate_document_asset.dependency_keys


class TestChunkDependsOnCurate:
    """chunk_document must declare a non-data dependency on curate_document_asset."""

    def test_chunk_dependency_keys_include_curate_document_asset(self) -> None:
        from knowledge_lake.dagster_defs.assets import chunk_document

        assert AssetKey("curate_document_asset") in chunk_document.dependency_keys, (
            "chunk_document must depend on curate_document_asset (KL-06) — "
            f"got dependency_keys={chunk_document.dependency_keys}"
        )

    def test_chunk_still_takes_clean_document_as_data_input(self) -> None:
        """The DATA input must stay clean_document — only ordering was added (locked design)."""
        from knowledge_lake.dagster_defs.assets import chunk_document

        assert AssetKey("clean_document") in chunk_document.dependency_keys


class TestIndexChunksDependsOnCurateTransitively:
    """index_chunks must transitively depend on curate_document_asset and enrich_document
    via the registered asset graph (chunk_document -> embed_chunks -> index_chunks),
    per the plan's 'index_chunks then depends on curate transitively' requirement.
    """

    def test_index_chunks_ancestors_include_curate_and_enrich(self) -> None:
        from knowledge_lake.dagster_defs.definitions import defs

        asset_graph = defs.get_repository_def().asset_graph
        ancestors = asset_graph.get_ancestor_asset_keys(AssetKey("index_chunks"))

        assert AssetKey("curate_document_asset") in ancestors, (
            "index_chunks must transitively depend on curate_document_asset "
            f"(KL-06) — ancestors={ancestors}"
        )
        assert AssetKey("enrich_document") in ancestors, (
            "index_chunks must transitively depend on enrich_document "
            f"(KL-06) — ancestors={ancestors}"
        )

    def test_chunk_document_ancestors_include_curate_and_enrich(self) -> None:
        """The race-closing edge lives at chunk_document; assert it directly too."""
        from knowledge_lake.dagster_defs.definitions import defs

        asset_graph = defs.get_repository_def().asset_graph
        ancestors = asset_graph.get_ancestor_asset_keys(AssetKey("chunk_document"))

        assert AssetKey("curate_document_asset") in ancestors
        assert AssetKey("enrich_document") in ancestors


class TestOrderingSurvivesFullGraphResolution:
    """The deps= edges must not just compile — they must resolve in the real,
    registered Definitions object (knowledge_lake.dagster_defs.definitions.defs),
    not only in an ad-hoc materialize() call assembled by a test.
    """

    def test_defs_asset_graph_has_curate_before_chunk_edge(self) -> None:
        from knowledge_lake.dagster_defs.definitions import defs

        asset_graph = defs.get_repository_def().asset_graph
        chunk_parents = asset_graph.get(AssetKey("chunk_document")).parent_keys
        assert AssetKey("curate_document_asset") in chunk_parents

    def test_defs_asset_graph_has_enrich_before_curate_edge(self) -> None:
        from knowledge_lake.dagster_defs.definitions import defs

        asset_graph = defs.get_repository_def().asset_graph
        curate_parents = asset_graph.get(AssetKey("curate_document_asset")).parent_keys
        assert AssetKey("enrich_document") in curate_parents
