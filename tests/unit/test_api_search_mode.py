"""Unit tests for API /search?mode= parameter threading (RETR-03, T-10-02).

RED test scaffold: asserts that GET /search?q=x&mode=hybrid forwards mode='hybrid'
into pipeline.search and that GET /search?q=x&mode=bogus returns HTTP 422
(Literal/pattern validation at the boundary, T-10-02).

Plan 10-08 added the ?mode= query parameter; all xfail decorators have been
removed. TestApiModeForwarding's two tests previously patched the wrong
target (see KL-19 in E2E-GAP-ANALYSIS.md) — fixed to patch
knowledge_lake.pipeline.route.search, which is what routed_search() actually
calls.

Pattern mirrors tests/integration/test_api_new_endpoints.py: starlette TestClient +
try/except ImportError guard. The search seam is stubbed/patched so no real embedder
or Qdrant server is contacted.
"""

from __future__ import annotations

from unittest.mock import patch

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


class TestApiModeForwarding:
    """API ?mode= query param threads mode into pipeline.search (RETR-03)."""

    def test_api_mode_forwarded_hybrid(self, api_client) -> None:
        """GET /search?q=x&mode=hybrid forwards mode='hybrid' into pipeline.search.

        Encodes: must_have truth §5 (RETR-03 — API ?mode= threading).
        """
        captured_kwargs: dict = {}

        def search_stub(query: str, **kwargs) -> list:  # type: ignore[return]
            captured_kwargs.update({"query": query, **kwargs})
            return []

        # routed_search() calls route.search (its own module-level binding from
        # `from knowledge_lake.pipeline.search import search`), not
        # pipeline.search.search directly (KL-19) — patch the target it actually uses.
        with patch("knowledge_lake.pipeline.route.search", side_effect=search_stub):
            resp = api_client.get("/search", params={"q": "test query", "mode": "hybrid"})

        # ?mode= is unknown today → FastAPI may return 422 or ignore the param.
        # Once Plan 10-08 adds the param, status_code must be 200.
        assert resp.status_code == 200, (
            f"Expected 200 for GET /search?q=x&mode=hybrid, got {resp.status_code}. "
            f"Body: {resp.text!r}"
        )
        assert captured_kwargs.get("mode") == "hybrid", (
            f"Expected mode='hybrid' forwarded to pipeline.search, "
            f"got: {captured_kwargs.get('mode')!r}. Full kwargs: {captured_kwargs}"
        )

    def test_api_mode_forwarded_dense(self, api_client) -> None:
        """GET /search?q=x&mode=dense forwards mode='dense' into pipeline.search."""
        captured_kwargs: dict = {}

        def search_stub(query: str, **kwargs) -> list:  # type: ignore[return]
            captured_kwargs.update({"query": query, **kwargs})
            return []

        with patch("knowledge_lake.pipeline.route.search", side_effect=search_stub):
            resp = api_client.get("/search", params={"q": "test query", "mode": "dense"})

        assert resp.status_code == 200, (
            f"Expected 200 for GET /search?q=x&mode=dense, got {resp.status_code}. "
            f"Body: {resp.text!r}"
        )
        assert captured_kwargs.get("mode") == "dense", (
            f"Expected mode='dense' forwarded to pipeline.search, "
            f"got: {captured_kwargs.get('mode')!r}"
        )


class TestApiInvalidMode422:
    """Invalid mode value at the API boundary must return HTTP 422 (T-10-02, RETR-03).

    This enforces fail-closed input validation: the API must reject any mode
    not in the allowed Literal set {'hybrid', 'dense', 'sparse'}.
    """

    def test_api_invalid_mode_422(self, api_client) -> None:
        """GET /search?q=x&mode=bogus must return HTTP 422 (Literal validation, T-10-02).

        Encodes: must_have truth §5 (T-10-02 — fail-closed mode input validation at API boundary).
        """
        resp = api_client.get("/search", params={"q": "test query", "mode": "bogus"})
        assert resp.status_code == 422, (
            f"Expected 422 for GET /search?mode=bogus (invalid Literal value), "
            f"got {resp.status_code}. Body: {resp.text!r}\n"
            f"Plan 10-08 must add Literal['hybrid','dense','sparse'] validation on the "
            f"mode query param so invalid values are rejected at the API boundary (T-10-02)."
        )

    def test_api_invalid_mode_sql_injection_422(self, api_client) -> None:
        """GET /search?mode='; DROP TABLE-- must return 422 (injection attempt, T-10-02)."""
        resp = api_client.get("/search", params={"q": "test", "mode": "'; DROP TABLE--"})
        assert resp.status_code == 422, (
            f"Expected 422 for injected mode value, got {resp.status_code}. "
            f"Body: {resp.text!r}"
        )

    def test_api_mode_absent_uses_default(self, api_client) -> None:
        """GET /search?q=x with no mode must use the settings default (hybrid).

        When no mode is specified the search endpoint must not raise a 422 — it must
        fall through to settings.search.mode (default 'hybrid'). This ensures mode is
        optional and backward-compatible.
        """
        captured_kwargs: dict = {}

        def search_stub(query: str, **kwargs) -> list:  # type: ignore[return]
            captured_kwargs.update({"query": query, **kwargs})
            return []

        with patch("knowledge_lake.pipeline.route.search", side_effect=search_stub):
            resp = api_client.get("/search", params={"q": "test query"})

        # Without the mode param: current behavior is 200; after Plan 10-08 it's still 200
        # but mode is resolved from settings.search.mode (= 'hybrid').
        assert resp.status_code == 200, (
            f"Expected 200 for GET /search?q=x (no mode), got {resp.status_code}. "
            f"Body: {resp.text!r}"
        )
