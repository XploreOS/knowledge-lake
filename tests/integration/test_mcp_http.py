"""Wave 0 RED scaffold: MCP Streamable HTTP integration tests (MCP-01, MCP-02).

Asserts that the Starlette-based Streamable HTTP app built by ``agent/http.py``:
  (a) binds to 127.0.0.1 (localhost only, RESEARCH.md Pattern 3)
  (b) enforces ``TransportSecuritySettings.allowed_hosts`` so non-127.0.0.1
      Host headers are rejected (host-header injection guard)
  (c) enforces bearer token authentication only when ``KLAKE_MCP__TOKEN`` is set;
      when unset, no auth is required (RESEARCH.md D-13)

All tests are xfail until Plan 06 implements ``agent/http.py``.
Uses import-guard pattern from test_api_new_endpoints.py lines 12-19.
Mirrors TestClient fixture from test_api_new_endpoints.py:22-28.
"""

from __future__ import annotations

import pytest

try:
    from knowledge_lake.agent.http import build_http_app
    _IMPORT_OK = True
except ImportError:
    build_http_app = None  # type: ignore[assignment]
    _IMPORT_OK = False

try:
    from starlette.testclient import TestClient
    _TESTCLIENT_OK = True
except ImportError:
    TestClient = None  # type: ignore[assignment, misc]
    _TESTCLIENT_OK = False


@pytest.fixture(scope="module")
def mcp_http_client():
    """Build the Starlette MCP HTTP app and return a TestClient."""
    if not _IMPORT_OK:
        pytest.skip("agent.http not yet implemented (Plan 06)")
    if not _TESTCLIENT_OK:
        pytest.skip("starlette.testclient not available")
    app = build_http_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.integration
@pytest.mark.xfail(
    not _IMPORT_OK,
    reason="Wave 0 scaffold — agent.http not yet implemented (Plan 06)",
    strict=False,
)
def test_build_http_app_is_callable() -> None:
    """build_http_app must be importable and callable from agent.http."""
    assert _IMPORT_OK, (
        "knowledge_lake.agent.http.build_http_app is not importable — "
        "Plan 06 must create agent/http.py"
    )
    assert callable(build_http_app), "build_http_app must be callable"


@pytest.mark.integration
@pytest.mark.xfail(
    not _IMPORT_OK,
    reason="Wave 0 scaffold — agent.http not yet implemented (Plan 06)",
    strict=False,
)
def test_http_app_is_starlette_app(mcp_http_client) -> None:
    """build_http_app() must return a Starlette ASGI app (TestClient-compatible)."""
    # If TestClient fixture was created, the app is Starlette-compatible
    assert mcp_http_client is not None


@pytest.mark.integration
@pytest.mark.xfail(
    not _IMPORT_OK,
    reason="Wave 0 scaffold — agent.http not yet implemented (Plan 06)",
    strict=False,
)
def test_http_app_binds_localhost_only(mcp_http_client) -> None:
    """MCP HTTP app must bind to 127.0.0.1 only (RESEARCH.md Pattern 3, T-12-H2).

    Requests with a non-localhost Host header must be rejected (host-header injection).
    AllowedHosts middleware should reject requests with unrecognised Host values.
    """
    # Request with non-localhost Host must be rejected
    resp = mcp_http_client.get("/mcp", headers={"Host": "attacker.example.com"})
    assert resp.status_code in (400, 403, 404), (
        f"Non-localhost Host was accepted (status {resp.status_code}); "
        "AllowedHostsMiddleware must reject external Host headers"
    )


@pytest.mark.integration
@pytest.mark.xfail(
    not _IMPORT_OK,
    reason="Wave 0 scaffold — agent.http not yet implemented (Plan 06)",
    strict=False,
)
def test_http_app_no_auth_when_token_unset(mcp_http_client, monkeypatch) -> None:
    """When KLAKE_MCP__TOKEN is not set, the MCP HTTP app must not require bearer auth.

    Unauthenticated requests must not return 401/403 (D-13: optional bearer).
    """
    monkeypatch.delenv("KLAKE_MCP__TOKEN", raising=False)
    resp = mcp_http_client.get("/mcp", headers={"Host": "127.0.0.1"})
    # Should not be 401 when no token is configured
    assert resp.status_code != 401, (
        "HTTP 401 returned without KLAKE_MCP__TOKEN set — bearer should be optional (D-13)"
    )


@pytest.mark.integration
@pytest.mark.xfail(
    not _IMPORT_OK,
    reason="Wave 0 scaffold — agent.http not yet implemented (Plan 06)",
    strict=False,
)
def test_http_app_enforces_bearer_when_token_set(mcp_http_client, monkeypatch) -> None:
    """When KLAKE_MCP__TOKEN is set, requests without Authorization must return 401.

    The StaticBearerMiddleware must enforce token authentication (D-13).
    """
    monkeypatch.setenv("KLAKE_MCP__TOKEN", "test-secret-token")
    resp = mcp_http_client.get("/mcp", headers={"Host": "127.0.0.1"})
    assert resp.status_code == 401, (
        f"Expected 401 with KLAKE_MCP__TOKEN set and no Authorization header, "
        f"got {resp.status_code}. StaticBearerMiddleware must enforce auth."
    )
