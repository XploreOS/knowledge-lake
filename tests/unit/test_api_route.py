"""Unit tests for API /search?route= parameter threading (ROUTE-04, ASVS V5).

Pattern mirrors tests/unit/test_api_search_mode.py: starlette TestClient +
try/except ImportError guard. The routed_search seam is patched at the import
location used by the REST handler.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
    """Return a starlette TestClient for the FastAPI app."""
    if not _IMPORT_OK:
        pytest.skip("FastAPI app import failed")
    with TestClient(app) as client:
        yield client


class TestApiRouteForwarding:
    """API ?route= query param threads route into routed_search (ROUTE-04)."""

    def test_route_param_forwarded(self, api_client) -> None:
        """GET /search?q=test&route=tree verifies routed_search called with route='tree'."""
        captured_kwargs: dict = {}

        def routed_search_stub(query: str, **kwargs) -> list:
            captured_kwargs.update({"query": query, **kwargs})
            return []

        with patch(
            "knowledge_lake.pipeline.route.routed_search",
            side_effect=routed_search_stub,
        ):
            resp = api_client.get("/search", params={"q": "test query", "route": "tree"})

        assert resp.status_code == 200, (
            f"Expected 200 for GET /search?q=test&route=tree, got {resp.status_code}. "
            f"Body: {resp.text!r}"
        )
        assert captured_kwargs.get("route") == "tree", (
            f"Expected route='tree' forwarded to routed_search, "
            f"got: {captured_kwargs.get('route')!r}. Full kwargs: {captured_kwargs}"
        )

    def test_route_invalid_422(self, api_client) -> None:
        """GET /search?q=test&route=bogus returns HTTP 422 (ASVS V5 fail-closed)."""
        resp = api_client.get("/search", params={"q": "test query", "route": "bogus"})
        assert resp.status_code == 422, (
            f"Expected 422 for GET /search?route=bogus (invalid value), "
            f"got {resp.status_code}. Body: {resp.text!r}"
        )

    def test_route_omitted_forwards_none(self, api_client) -> None:
        """GET /search?q=test (no route) calls routed_search with route=None."""
        captured_kwargs: dict = {}

        def routed_search_stub(query: str, **kwargs) -> list:
            captured_kwargs.update({"query": query, **kwargs})
            return []

        with patch(
            "knowledge_lake.pipeline.route.routed_search",
            side_effect=routed_search_stub,
        ):
            resp = api_client.get("/search", params={"q": "test query"})

        assert resp.status_code == 200, (
            f"Expected 200 for GET /search?q=test (no route), got {resp.status_code}. "
            f"Body: {resp.text!r}"
        )
        assert captured_kwargs.get("route") is None, (
            f"Expected route=None when not specified, "
            f"got: {captured_kwargs.get('route')!r}. Full kwargs: {captured_kwargs}"
        )
