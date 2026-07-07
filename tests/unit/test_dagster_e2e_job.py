"""Unit tests for healthcare_e2e_job Dagster job definition.

Validates that the healthcare_e2e_job is importable, has the correct type
(JobDefinition), and is registered in the Definitions object.
"""

from __future__ import annotations

import pytest


class TestHealthcareE2eJobImportable:
    """healthcare_e2e_job must be importable from assets module."""

    def test_healthcare_e2e_job_importable(self) -> None:
        """healthcare_e2e_job can be imported from knowledge_lake.dagster_defs.assets."""
        from knowledge_lake.dagster_defs.assets import healthcare_e2e_job  # noqa: F401

        assert healthcare_e2e_job is not None, "healthcare_e2e_job must not be None"

    def test_healthcare_e2e_job_is_job_definition(self) -> None:
        """healthcare_e2e_job must be a Dagster UnresolvedAssetJobDefinition or JobDefinition (DOMAIN-04).

        define_asset_job() returns an UnresolvedAssetJobDefinition that is resolved
        to JobDefinition when Definitions.resolve_all_job_defs() is called.
        Both types are valid; we check that it has a .name attribute matching the expected name.
        """
        from dagster import JobDefinition
        from dagster._core.definitions.unresolved_asset_job_definition import (
            UnresolvedAssetJobDefinition,
        )
        from knowledge_lake.dagster_defs.assets import healthcare_e2e_job

        assert isinstance(
            healthcare_e2e_job, (JobDefinition, UnresolvedAssetJobDefinition)
        ), (
            f"healthcare_e2e_job must be dagster.JobDefinition or UnresolvedAssetJobDefinition, "
            f"got {type(healthcare_e2e_job).__name__}"
        )
        assert healthcare_e2e_job.name == "healthcare_e2e_job", (
            f"Job name must be 'healthcare_e2e_job', got '{healthcare_e2e_job.name}'"
        )


class TestHealthcareE2eJobInDefinitions:
    """healthcare_e2e_job must be registered in the Definitions object."""

    def test_healthcare_e2e_job_in_definitions(self) -> None:
        """defs.jobs (or defs.resolve_all_job_defs) must contain 'healthcare_e2e_job'."""
        from knowledge_lake.dagster_defs.definitions import defs

        # defs.jobs stores UnresolvedAssetJobDefinition objects before resolution
        # Both jobs list and resolved job defs are checked for the expected name
        direct_names = [j.name for j in (defs.jobs or [])]
        resolved_names = [j.name for j in defs.resolve_all_job_defs()]
        all_names = set(direct_names) | set(resolved_names)
        assert "healthcare_e2e_job" in all_names, (
            f"healthcare_e2e_job not registered in Definitions.jobs. "
            f"Direct job names: {direct_names}, Resolved: {resolved_names}"
        )
