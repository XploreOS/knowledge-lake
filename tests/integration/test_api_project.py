"""Tests for the Dataset Project / Specification API routes (PROJ-03, SPEC-03, SURFACE-02).

Uses FastAPI TestClient pattern from test_api_new_endpoints.py.
Requires live DB (PostgreSQL) for all tests in this file.

Each test uses a uuid4()-suffixed project name to avoid uq_dataset_projects_name
collisions across repeated runs (this codebase's established integration-test
uniqueness convention, e.g. test_dedup_cli_dagster_parity.py's
SHARED_BOILERPLATE_TEXT precedent, adapted here to name-uniqueness).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

try:
    from starlette.testclient import TestClient
    from knowledge_lake.api.app import app
    _IMPORT_OK = True
except ImportError:
    TestClient = None  # type: ignore[assignment, misc]
    app = None  # type: ignore[assignment]
    _IMPORT_OK = False


@pytest.fixture(scope="module")
def api_client():
    """Return a TestClient for the FastAPI app."""
    if not _IMPORT_OK:
        pytest.skip("FastAPI app import failed")
    with TestClient(app) as client:
        yield client


def _unique_name(prefix: str) -> str:
    return f"{prefix} {uuid4()}"


def _create_project(api_client, *, name: str | None = None, dataset_type: str = "rag_eval") -> dict:
    resp = api_client.post(
        "/projects",
        json={"name": name or _unique_name("Project"), "dataset_type": dataset_type},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    result: dict = resp.json()
    return result


# ── POST /projects ──────────────────────────────────────────────────────────


@pytest.mark.integration
def test_create_project_returns_draft(api_client) -> None:
    """POST /projects must create a project in status='draft'."""
    resp = api_client.post(
        "/projects",
        json={"name": _unique_name("Draft Status Project"), "dataset_type": "rag_eval"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["status"] == "draft"
    assert data["dataset_type"] == "rag_eval"


@pytest.mark.integration
def test_create_project_duplicate_name_returns_422(api_client) -> None:
    """POST /projects with a duplicate name must return 422 with the ValueError message."""
    name = _unique_name("Duplicate Name Project")
    first = api_client.post("/projects", json={"name": name, "dataset_type": "rag_eval"})
    assert first.status_code == 200, f"Expected 200, got {first.status_code}: {first.text}"

    second = api_client.post("/projects", json={"name": name, "dataset_type": "rag_eval"})
    assert second.status_code == 422, f"Expected 422, got {second.status_code}: {second.text}"
    assert name in second.json()["detail"]


# ── GET /projects, GET /projects/{id} ───────────────────────────────────────


@pytest.mark.integration
def test_get_project_unknown_returns_404(api_client) -> None:
    """GET /projects/{unknown_id} must return 404."""
    resp = api_client.get("/projects/dpj_totally_unknown_id_00000000")
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


@pytest.mark.integration
def test_list_projects_returns_200_list(api_client) -> None:
    """GET /projects must return 200 with a list."""
    resp = api_client.get("/projects")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert isinstance(data, list), f"Expected list, got {type(data)}"


# ── POST /projects/{id}/transition ──────────────────────────────────────────


@pytest.mark.integration
def test_transition_illegal_edge_returns_409_with_detail(api_client) -> None:
    """POST /projects/{id}/transition on an illegal edge must return 409 with
    the full structured detail body (RESEARCH.md Pattern 4)."""
    project = _create_project(api_client, name=_unique_name("Illegal Transition Project"))

    resp = api_client.post(
        f"/projects/{project['id']}/transition",
        json={"to_state": "released"},
    )
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
    assert resp.json()["detail"] == {
        "error": "illegal_transition",
        "from_state": "draft",
        "to_state": "released",
        "legal_next_states": ["configured"],
    }


@pytest.mark.integration
def test_transition_legal_edge_returns_200(api_client) -> None:
    """POST /projects/{id}/transition on a legal edge must return 200 + ProjectOut."""
    project = _create_project(api_client, name=_unique_name("Legal Transition Project"))

    resp = api_client.post(
        f"/projects/{project['id']}/transition",
        json={"to_state": "configured"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert resp.json()["status"] == "configured"


# ── POST /projects/{id}/specs ────────────────────────────────────────────────


@pytest.mark.integration
def test_create_spec_version_returns_200_and_hash(api_client) -> None:
    """POST /projects/{id}/specs must return 200 + SpecVersionOut with a content_hash."""
    project = _create_project(api_client, name=_unique_name("Spec Version Project"))

    resp = api_client.post(
        f"/projects/{project['id']}/specs",
        json={
            "spec": {"purpose": "p", "dataset_type": "t", "domain": "d"},
            "author": "alice",
        },
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["dataset_project_id"] == project["id"]
    assert data["content_hash"]
    assert data["parent_spec_id"] is None


# ── POST /specs/{id}/validate ────────────────────────────────────────────────


@pytest.mark.integration
def test_spec_validate_unknown_source_returns_200_invalid(api_client) -> None:
    """POST /specs/{id}/validate for a spec with an unresolvable source must
    return 200 with valid=False — a validation failure is a report, not an
    HTTP error (QCON-02)."""
    project = _create_project(api_client, name=_unique_name("Unknown Source Spec Project"))
    spec_resp = api_client.post(
        f"/projects/{project['id']}/specs",
        json={
            "spec": {
                "purpose": "p",
                "dataset_type": "t",
                "domain": "d",
                "included_sources": ["src_does_not_exist"],
            },
            "author": "alice",
        },
    )
    assert spec_resp.status_code == 200, f"Expected 200, got {spec_resp.status_code}: {spec_resp.text}"
    spec_id = spec_resp.json()["id"]

    resp = api_client.post(f"/specs/{spec_id}/validate")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["valid"] is False
    assert any("src_does_not_exist" in err for err in data["errors"])


@pytest.mark.integration
def test_spec_validate_all_refs_resolve_returns_200_valid(api_client) -> None:
    """POST /specs/{id}/validate when every source reference resolves must
    return 200 with valid=True and no errors."""
    source_resp = api_client.post(
        "/sources",
        json={"url": f"https://example.com/{uuid4()}", "name": _unique_name("Real Source")},
    )
    assert source_resp.status_code == 201, f"Expected 201, got {source_resp.status_code}: {source_resp.text}"
    source_id = source_resp.json()["source_id"]

    project = _create_project(api_client, name=_unique_name("All Refs Resolve Spec Project"))
    spec_resp = api_client.post(
        f"/projects/{project['id']}/specs",
        json={
            "spec": {
                "purpose": "p",
                "dataset_type": "t",
                "domain": "d",
                "included_sources": [source_id],
            },
            "author": "alice",
        },
    )
    assert spec_resp.status_code == 200, f"Expected 200, got {spec_resp.status_code}: {spec_resp.text}"
    spec_id = spec_resp.json()["id"]

    resp = api_client.post(f"/specs/{spec_id}/validate")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["valid"] is True
    assert data["errors"] == []
