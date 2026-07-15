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

They ALSO pin core_pipeline_e2e_job's selection. Declaring the deps= edges is
not sufficient on its own: Dagster drops a ``deps=`` edge whose target is not
in a job's selected set, so a job that omits curate_document_asset executes a
graph where chunk_document has no ordering relative to enrich_document — the
race, alive again, in the job people actually run. That is precisely how this
bug reached production, so the selection is pinned here too.
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


class TestCorePipelineE2eJobSelectionPreservesOrdering:
    """The job people actually run must contain every asset the ordering chain needs.

    This is the guard against the exact way the race got here (KL-06): Dagster
    DROPS a ``deps=`` edge whose target is outside the selected set. When
    core_pipeline_e2e_job's selection omitted curate_document_asset,
    chunk_document's deps=[curate_document_asset] edge silently vanished for
    that job, so chunk regained an unordered relationship with enrich and the
    race was alive in the main E2E job — even though the abstract asset graph
    looked correct. A fix that holds in the abstract graph but not in the job
    people run is not a fix.

    Re-narrowing the selection later must fail these tests loudly.
    """

    def _resolved_job(self):
        from knowledge_lake.dagster_defs.definitions import defs

        return defs.resolve_job_def("core_pipeline_e2e_job")

    def test_job_selection_contains_curate_and_enrich(self) -> None:
        job = self._resolved_job()
        selected = set(job.asset_layer.executable_asset_keys)

        assert AssetKey("curate_document_asset") in selected, (
            "core_pipeline_e2e_job's selection must contain curate_document_asset "
            "(KL-06) — excluding it makes Dagster drop chunk_document's "
            "deps=[curate_document_asset] edge for this job, resurrecting the "
            f"scheduling race. Selected: {sorted(k.to_user_string() for k in selected)}"
        )
        assert AssetKey("enrich_document") in selected, (
            "core_pipeline_e2e_job's selection must contain enrich_document "
            f"(KL-06). Selected: {sorted(k.to_user_string() for k in selected)}"
        )

    def test_index_chunks_ancestors_within_job_are_executable_in_the_job(self) -> None:
        """Ancestry alone is NOT enough — the ancestor must also be EXECUTED by the job.

        Measured: ``job.asset_layer.asset_graph`` IS job-scoped (8 keys vs the
        global 13), but it still contains ``curate_document_asset`` as a
        NON-EXECUTABLE node, pulled in only because chunk_document declares
        ``deps=[curate_document_asset]``. So a pure ancestry assertion passes
        even when the job never materializes curate — i.e. while the KL-06 race
        is live. That is a vacuous guard.

        ``executable_asset_keys`` is the only thing that pins what the job
        actually runs, so intersect ancestry with it.
        """
        job = self._resolved_job()
        job_asset_graph = job.asset_layer.asset_graph
        ancestors = set(job_asset_graph.get_ancestor_asset_keys(AssetKey("index_chunks")))
        executable = set(job.asset_layer.executable_asset_keys)

        for name in ("curate_document_asset", "enrich_document"):
            key = AssetKey(name)
            assert key in ancestors, (
                f"Within core_pipeline_e2e_job, index_chunks must have {name} as an "
                f"ancestor (KL-06). Ancestors: {sorted(k.to_user_string() for k in ancestors)}"
            )
            assert key in executable, (
                f"{name} is an ancestor of index_chunks but is NOT executable in "
                "core_pipeline_e2e_job — Dagster pulled it into the job graph as an "
                "external node and will never materialize it, so the ordering edge is "
                "not enforced and the KL-06 race is live. Add it to the job's "
                f"selection. Executable: {sorted(k.to_user_string() for k in executable)}"
            )

    def test_chunk_document_ordering_edge_survives_inside_the_job(self) -> None:
        """The specific edge Dagster silently dropped when curate was unselected."""
        job = self._resolved_job()
        job_asset_graph = job.asset_layer.asset_graph
        chunk_parents = job_asset_graph.get(AssetKey("chunk_document")).parent_keys

        assert AssetKey("curate_document_asset") in chunk_parents, (
            "chunk_document's deps=[curate_document_asset] edge must survive inside "
            f"core_pipeline_e2e_job. Parents within job: {chunk_parents}"
        )

    def test_generate_dataset_stays_excluded_from_the_job(self) -> None:
        """generate_dataset's exclusion IS legitimate — it needs source_artifact_id
        run config (Pitfall 6 / T-06-14), unlike curate_document_asset which takes
        no Config at all. Pin the distinction so the two aren't conflated again.
        """
        job = self._resolved_job()
        selected = set(job.asset_layer.executable_asset_keys)

        assert AssetKey("generate_dataset") not in selected, (
            "generate_dataset must stay OUT of core_pipeline_e2e_job — it declares "
            "GenerateDatasetConfig (kind/source_artifact_id/dataset_name) and would "
            "require run config unrelated to the ingest-to-index chain (T-06-14)."
        )

    def test_curate_asset_requires_no_run_config(self) -> None:
        """The factual basis for including curate: it declares no Config, so the
        Pitfall 6 'needs run config' rationale never applied to it.
        """
        from knowledge_lake.dagster_defs.assets import (
            curate_document_asset,
            generate_dataset,
        )

        curate_schema = curate_document_asset.node_def.config_schema
        curate_fields = getattr(curate_schema.config_type, "fields", None) if curate_schema else None
        assert not curate_fields, (
            "curate_document_asset must require no run config — if it ever gains a "
            "Config, revisit its inclusion in core_pipeline_e2e_job. "
            f"Got config fields: {list(curate_fields.keys()) if curate_fields else None}"
        )

        # Contrast: generate_dataset genuinely does need run config.
        gd_schema = generate_dataset.node_def.config_schema
        gd_fields = getattr(gd_schema.config_type, "fields", None) if gd_schema else None
        assert gd_fields and "source_artifact_id" in gd_fields, (
            "generate_dataset is expected to declare source_artifact_id config — "
            "that is the real basis for its exclusion (T-06-14)."
        )


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
