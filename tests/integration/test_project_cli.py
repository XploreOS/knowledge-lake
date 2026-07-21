"""Tests for the Dataset Project / Specification CLI surface (PROJ-03, SPEC-01/03, SURFACE-01).

Uses typer.testing.CliRunner against the live dev registry (compose stack),
mirroring test_domain_init.py's exact import-guard + invoke() + exit_code/
output assertion pattern.

Each test uses a uuid4()-suffixed project name to avoid uq_dataset_projects_name
collisions across repeated runs, mirroring test_api_project.py's established
integration-test uniqueness convention.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

try:
    from typer.testing import CliRunner
    from knowledge_lake.cli.app import app
    _IMPORT_OK = True
except ImportError:
    CliRunner = None  # type: ignore[assignment, misc]
    app = None  # type: ignore[assignment]
    _IMPORT_OK = False


def _unique_name(prefix: str) -> str:
    return f"{prefix} {uuid4()}"


def _create_project(runner, *, name: str | None = None, dataset_type: str = "rag_eval") -> str:
    """Invoke `klake project new` and return the created project's id."""
    project_name = name or _unique_name("CLI Project")
    result = runner.invoke(
        app, ["project", "new", project_name, "--dataset-type", dataset_type]
    )
    assert result.exit_code == 0, (
        f"klake project new failed, exit_code={result.exit_code}. Output: {result.output!r}"
    )
    # Output format: "Created project 'dpj_...' in state 'draft'"
    start = result.output.index("'") + 1
    end = result.output.index("'", start)
    return str(result.output[start:end])


@pytest.mark.integration
def test_project_new_creates_draft() -> None:
    """klake project new <name> --dataset-type <type> exits 0 and prints draft state."""
    if not _IMPORT_OK:
        pytest.skip("CLI app import failed")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["project", "new", _unique_name("Draft Status Project"), "--dataset-type", "rag_eval"],
    )
    assert result.exit_code == 0, (
        f"Expected exit_code 0, got {result.exit_code}. Output: {result.output!r}"
    )
    assert "draft" in result.output


@pytest.mark.integration
def test_project_new_duplicate_name_exits_1() -> None:
    """A second `klake project new` with the same name exits 1."""
    if not _IMPORT_OK:
        pytest.skip("CLI app import failed")

    runner = CliRunner()
    name = _unique_name("Duplicate Name Project")

    first = runner.invoke(app, ["project", "new", name, "--dataset-type", "rag_eval"])
    assert first.exit_code == 0, (
        f"Expected exit_code 0, got {first.exit_code}. Output: {first.output!r}"
    )

    second = runner.invoke(app, ["project", "new", name, "--dataset-type", "rag_eval"])
    assert second.exit_code == 1, (
        f"Expected exit_code 1, got {second.exit_code}. Output: {second.output!r}"
    )


@pytest.mark.integration
def test_project_list_empty_or_populated_exits_0() -> None:
    """klake project list always exits 0, whether or not projects exist."""
    if not _IMPORT_OK:
        pytest.skip("CLI app import failed")

    runner = CliRunner()
    result = runner.invoke(app, ["project", "list"])
    assert result.exit_code == 0, (
        f"Expected exit_code 0, got {result.exit_code}. Output: {result.output!r}"
    )
    assert "No projects found." in result.output or result.output.strip() != ""


@pytest.mark.integration
def test_project_show_unknown_exits_1() -> None:
    """klake project show <unknown-id> exits 1."""
    if not _IMPORT_OK:
        pytest.skip("CLI app import failed")

    runner = CliRunner()
    result = runner.invoke(app, ["project", "show", "dpj_totally_unknown_id_00000000"])
    assert result.exit_code == 1, (
        f"Expected exit_code 1, got {result.exit_code}. Output: {result.output!r}"
    )


@pytest.mark.integration
def test_project_transition_illegal_exits_1_with_message() -> None:
    """klake project transition <id> released on a fresh draft project exits 1
    and prints the from/to state detail."""
    if not _IMPORT_OK:
        pytest.skip("CLI app import failed")

    runner = CliRunner()
    project_id = _create_project(runner, name=_unique_name("Illegal Transition Project"))

    result = runner.invoke(app, ["project", "transition", project_id, "released"])
    assert result.exit_code == 1, (
        f"Expected exit_code 1, got {result.exit_code}. Output: {result.output!r}"
    )
    assert "draft" in result.output
    assert "configured" in result.output


@pytest.mark.integration
def test_dataset_spec_create_and_validate_round_trip(tmp_path) -> None:
    """klake dataset spec create followed by klake dataset spec validate round-trips."""
    if not _IMPORT_OK:
        pytest.skip("CLI app import failed")

    runner = CliRunner()
    project_id = _create_project(runner, name=_unique_name("Spec Round Trip Project"))

    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text("purpose: p\ndataset_type: t\ndomain: d\n")

    create_result = runner.invoke(
        app,
        ["dataset", "spec", "create", project_id, str(spec_path), "--author", "test-author"],
    )
    assert create_result.exit_code == 0, (
        f"Expected exit_code 0, got {create_result.exit_code}. Output: {create_result.output!r}"
    )

    validate_result = runner.invoke(app, ["dataset", "spec", "validate", project_id])
    assert validate_result.exit_code == 0, (
        f"Expected exit_code 0, got {validate_result.exit_code}. "
        f"Output: {validate_result.output!r}"
    )
    assert "is valid" in validate_result.output


@pytest.mark.integration
def test_dataset_spec_validate_no_spec_exits_1() -> None:
    """klake dataset spec validate on a project with zero spec versions exits 1."""
    if not _IMPORT_OK:
        pytest.skip("CLI app import failed")

    runner = CliRunner()
    project_id = _create_project(runner, name=_unique_name("No Spec Project"))

    result = runner.invoke(app, ["dataset", "spec", "validate", project_id])
    assert result.exit_code == 1, (
        f"Expected exit_code 1, got {result.exit_code}. Output: {result.output!r}"
    )
    assert "no spec version exists" in result.output


@pytest.mark.integration
def test_dataset_spec_validate_missing_argument_exits_nonzero() -> None:
    """klake dataset spec validate with no project_id argument fails via Typer's
    own missing-argument handling."""
    if not _IMPORT_OK:
        pytest.skip("CLI app import failed")

    runner = CliRunner()
    result = runner.invoke(app, ["dataset", "spec", "validate"])
    assert result.exit_code != 0, (
        f"Expected non-zero exit_code, got {result.exit_code}. Output: {result.output!r}"
    )
