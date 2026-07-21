"""Integration test: D-02 export-identity-ambiguity resolution (Plan 23-04).

Proves, against the live dev Postgres stack (no mocks), that
``registry_repo.get_latest_released_dataset_by_name()`` — the fix for
RESEARCH.md Pattern 5 / PITFALLS.md Pitfall 2 — resolves a ``Dataset`` row
FK'd to a Dataset Project by joining on ``DatasetProject.status == "released"``
alone, never any ``DatasetSpec`` field (that table carries no status column,
Plan 23-01's single-source-of-truth decision).

Exercises the full real lifecycle path a Dataset Project takes to reach
``"released"`` (``pipeline.project.create_project()`` /
``create_spec_version()`` / ``transition_project()``), mirroring
``test_dedup_cli_dagster_parity.py``'s established convention of proving
identity-resolution fixes against the real stack rather than the SQLite unit
harness, plus its best-effort teardown / ``uuid4()``-suffixed naming
convention for repeated-run isolation.

Run with:
    uv run pytest tests/integration/test_export_project_resolution.py -v -m integration
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete

from knowledge_lake.pipeline import project as pipeline_project
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.registry.models import Dataset, DatasetProject, DatasetSpec

pytestmark = pytest.mark.integration


def _cleanup_project(project_id: str, dataset_name: str) -> None:
    """Best-effort teardown: delete this test's Dataset/DatasetSpec/DatasetProject
    rows (including the ``_v2``-suffixed second Dataset row), mirroring
    test_dedup_cli_dagster_parity.py's teardown convention, so repeated test
    runs don't accumulate rows or collide on the dataset_projects.name /
    datasets.name UNIQUE constraints."""
    try:
        with get_session() as session:
            session.execute(
                delete(Dataset).where(
                    Dataset.name.in_([dataset_name, f"{dataset_name}_v2"])
                )
            )
            session.execute(
                delete(DatasetSpec).where(DatasetSpec.dataset_project_id == project_id)
            )
            session.execute(delete(DatasetProject).where(DatasetProject.id == project_id))
    except Exception:  # noqa: BLE001 — best-effort cleanup, never fail the test on teardown
        pass


def _create_project_with_two_spec_versions(dataset_name: str) -> tuple[str, str, str]:
    """Create a Dataset Project, two spec versions, and two Dataset rows FK'd
    to that project, representing two exports taken at different points in
    the project's lifecycle.

    NOTE on naming: ``datasets.name`` carries a real ``uq_datasets_name``
    UNIQUE constraint (migration 0008) — two Dataset rows can never share one
    literal ``name`` value. This deliberately differs from the plan's literal
    action text ("set BOTH Dataset rows to the SAME name value"), which is
    infeasible against the actual schema. It does NOT change what is proven:
    per this plan's own <action> spec, get_latest_released_dataset_by_name()'s
    second query resolves purely on ``Dataset.dataset_project_id`` (not on
    ``name`` again) once the initial by-name lookup has identified the
    project — so calling it with ``dataset_name`` (the EARLIER row's name)
    must still resolve to the LATER row for the same project, proving the
    "latest wins" rule exactly as specified.
    """
    project_name = f"test_export_resolution_{uuid4().hex[:8]}"
    project = pipeline_project.create_project(
        name=project_name, dataset_type="instruction_tuning", domain="healthcare"
    )
    project_id = project["id"]

    # Two distinct spec versions (SPEC-02's immutable insert-only chain).
    pipeline_project.create_spec_version(
        project_id,
        {"purpose": "v1 purpose", "dataset_type": "instruction_tuning", "domain": "healthcare"},
        author="test-suite",
    )
    pipeline_project.create_spec_version(
        project_id,
        {
            "purpose": "v2 purpose — genuinely different",
            "dataset_type": "instruction_tuning",
            "domain": "healthcare",
        },
        author="test-suite",
    )

    # Two Dataset rows tied to the project (two exports taken at different
    # points in the project's lifecycle). Distinct names (see docstring above).
    with get_session() as session:
        earlier = registry_repo.create_dataset(
            session, name=dataset_name, dataset_type="instruction_tuning"
        )
        earlier.dataset_project_id = project_id
        session.flush()
        earlier_id = earlier.id

    with get_session() as session:
        later = registry_repo.create_dataset(
            session, name=f"{dataset_name}_v2", dataset_type="instruction_tuning"
        )
        later.dataset_project_id = project_id
        session.flush()
        later_id = later.id

    return project_id, earlier_id, later_id


class TestLatestReleasedDatasetResolution:
    """D-02 (Pitfall 2): get_latest_released_dataset_by_name() end-to-end."""

    def test_latest_released_resolution(self) -> None:
        """A Dataset Project carrying two spec versions and two associated
        Dataset rows, walked through the full lifecycle to 'released':
        get_latest_released_dataset_by_name() resolves to the LATER Dataset
        row, not an arbitrary/earlier one (ROADMAP Success Criterion 5)."""
        dataset_name = f"test_export_resolution_ds_{uuid4().hex[:8]}"
        project_id, earlier_id, later_id = _create_project_with_two_spec_versions(dataset_name)

        try:
            for to_state in (
                "configured",
                "sources_pending",
                "ready",
                "processing",
                "validating",
                "review_required",
                "releasable",
                "released",
            ):
                pipeline_project.transition_project(project_id, to_state)

            with get_session() as session:
                resolved = registry_repo.get_latest_released_dataset_by_name(
                    session, dataset_name
                )
                assert resolved is not None, (
                    "Expected a resolved Dataset for a released project, got None"
                )
                assert resolved.id == later_id, (
                    f"Expected the LATER Dataset row ({later_id!r}) to resolve, "
                    f"got {resolved.id!r} (earlier was {earlier_id!r})"
                )
        finally:
            _cleanup_project(project_id, dataset_name)

    def test_pre_release_project_yields_no_released_dataset(self) -> None:
        """A Dataset Project whose status has NOT reached 'released' (stopped
        at 'review_required'): get_latest_released_dataset_by_name() returns
        None even though a Dataset row physically exists and is FK'd to the
        project."""
        dataset_name = f"test_export_resolution_pre_{uuid4().hex[:8]}"
        project_id, earlier_id, later_id = _create_project_with_two_spec_versions(dataset_name)

        try:
            for to_state in (
                "configured",
                "sources_pending",
                "ready",
                "processing",
                "validating",
                "review_required",
            ):
                pipeline_project.transition_project(project_id, to_state)

            with get_session() as session:
                resolved = registry_repo.get_latest_released_dataset_by_name(
                    session, dataset_name
                )
                assert resolved is None, (
                    f"Expected None for a not-yet-released project, got Dataset "
                    f"id={resolved.id if resolved else None!r}"
                )
        finally:
            _cleanup_project(project_id, dataset_name)
