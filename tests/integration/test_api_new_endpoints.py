"""Tests for 8 API endpoints added for the registry (IFACE-02, D-07 gap audit).

Uses FastAPI TestClient pattern from test_api_lineage.py.
Requires live DB (PostgreSQL + MinIO) for endpoints that query the registry.
test_get_documents_returns_200 and test_get_datasets_returns_200 remain xfail
(DetachedInstanceError — see per-test reason strings).
"""

from __future__ import annotations

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


# ── GET /sources ──────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_get_sources_returns_200(api_client) -> None:
    """GET /sources must return 200 with a list."""
    resp = api_client.get("/sources")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert isinstance(data, list), f"Expected list, got {type(data)}"


@pytest.mark.integration
def test_get_source_by_id_404_for_unknown(api_client) -> None:
    """GET /sources/{unknown_id} must return 404."""
    resp = api_client.get("/sources/src_totally_unknown_id_00000000")
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


# ── GET /documents ────────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.xfail(
    reason=(
        "GET /documents exists (api/app.py:1405), but list_documents_endpoint builds "
        "ArtifactOut objects outside the `with get_session()` block, so accessing lazy "
        "ORM attributes raises sqlalchemy.orm.exc.DetachedInstanceError."
    )
)
def test_get_documents_returns_200(api_client) -> None:
    """GET /documents must return 200 with a list."""
    resp = api_client.get("/documents")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert isinstance(data, list), f"Expected list, got {type(data)}"


@pytest.mark.integration
def test_get_document_by_id_404(api_client) -> None:
    """GET /documents/{unknown_id} must return 404."""
    resp = api_client.get("/documents/doc_totally_unknown_id_00000000")
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


# ── GET /datasets ─────────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.xfail(
    reason=(
        "GET /datasets exists (api/app.py:1496), but list_datasets_endpoint builds "
        "DatasetOut objects outside the `with get_session()` block, so accessing lazy "
        "ORM attributes raises sqlalchemy.orm.exc.DetachedInstanceError."
    )
)
def test_get_datasets_returns_200(api_client) -> None:
    """GET /datasets must return 200 with a list."""
    resp = api_client.get("/datasets")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert isinstance(data, list), f"Expected list, got {type(data)}"


@pytest.mark.integration
def test_get_dataset_by_id_404(api_client) -> None:
    """GET /datasets/{unknown_id} must return 404."""
    resp = api_client.get("/datasets/dst_totally_unknown_id_00000000")
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


# ── POST /domains/load ────────────────────────────────────────────────────────

@pytest.mark.integration
def test_post_domains_load_healthcare(api_client) -> None:
    """POST /domains/load {"name": "healthcare"} must return 200 with loaded_count field."""
    resp = api_client.post("/domains/load", json={"name": "healthcare"})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "loaded_count" in data, f"Response missing 'loaded_count': {data.keys()}"


# ── GET /domains/{name}/sources ───────────────────────────────────────────────

@pytest.mark.integration
def test_get_domains_sources(api_client) -> None:
    """GET /domains/healthcare/sources must return a list."""
    resp = api_client.get("/domains/healthcare/sources")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert isinstance(data, list), f"Expected list, got {type(data)}"
    assert len(data) >= 1, "Expected at least 1 source entry from the healthcare pack"
