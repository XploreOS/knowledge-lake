"""Integration tests for the MCP Streamable HTTP surface (MCP-02, Plan 12-06).

Proves that the Starlette app built by ``agent/http.py`` is safe-by-default for a
localhost agent server:

  (a) **Localhost bind + Host guard** — the app is constructed with host
      ``127.0.0.1`` and a populated ``TransportSecuritySettings.allowed_hosts``;
      a request carrying a foreign ``Host`` header is rejected (T-12-01).
  (b) **Optional constant-time bearer** — when ``token`` is set, a request with a
      missing/wrong bearer returns 401 and one with the correct bearer does not;
      when ``token`` is unset no auth is required (D-10, T-12-04).
  (c) **Read-only posture over HTTP** — a server built from
      ``registered_tools(readonly=True)`` lists only the 4 read tools over the
      wire (search, list_sources, lineage, stats) — same tool set as stdio (D-11).

Uses the import-guard pattern from test_api_new_endpoints.py:12-19 and the
module-scoped ``TestClient`` fixture from :22-28.  Streamable HTTP (stateless)
responds to ``tools/list`` directly as an SSE ``text/event-stream`` frame, which
these tests parse without a full session handshake.
"""

from __future__ import annotations

import json

import pytest

try:
    from starlette.testclient import TestClient

    from knowledge_lake.agent.http import StaticBearerMiddleware, build_http_app
    from knowledge_lake.agent.registry import registered_tools
    from knowledge_lake.agent.server import build_server

    _IMPORT_OK = True
except ImportError:
    TestClient = None  # type: ignore[assignment, misc]
    build_http_app = None  # type: ignore[assignment]
    StaticBearerMiddleware = None  # type: ignore[assignment, misc]
    registered_tools = None  # type: ignore[assignment]
    build_server = None  # type: ignore[assignment]
    _IMPORT_OK = False


_HOST = "127.0.0.1"
_PORT = 3001
_GOOD_HOST = f"{_HOST}:{_PORT}"
_ACCEPT = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
_LIST_TOOLS_REQ = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

# The 4 read tools the read-only posture must expose (D-11).
_READ_TOOLS = {"search", "list_sources", "lineage", "stats"}


def _extract_result(resp) -> dict:  # noqa: ANN001
    """Parse a JSON-RPC result from a JSON or SSE (text/event-stream) response."""
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        # SSE frame: one or more ``data: {json}`` lines.
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[len("data:"):].strip())
        raise AssertionError(f"no SSE data line in response: {resp.text!r}")
    return resp.json()


def _build_app(*, readonly: bool = False, token: str | None = None):  # noqa: ANN202
    if not _IMPORT_OK:
        pytest.skip("agent.http not importable")
    server = build_server(registered_tools(readonly=readonly))
    return build_http_app(server, host=_HOST, port=_PORT, token=token)


@pytest.fixture(scope="module")
def mcp_http_client():
    """Module-scoped TestClient over the read-only MCP HTTP app (no bearer)."""
    if not _IMPORT_OK:
        pytest.skip("agent.http not yet importable")
    app = _build_app(readonly=True, token=None)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


# ── (a) localhost bind + Host guard ─────────────────────────────────────────


@pytest.mark.integration
def test_build_http_app_is_callable() -> None:
    """build_http_app must be importable and callable."""
    assert _IMPORT_OK, "knowledge_lake.agent.http.build_http_app is not importable"
    assert callable(build_http_app)


@pytest.mark.integration
def test_foreign_host_is_rejected(mcp_http_client) -> None:
    """A request with a Host not in allowed_hosts must be rejected (T-12-01).

    DNS-rebinding protection is on and allowed_hosts is populated with the bind
    host:port, so a foreign Host header is refused with a client error.
    """
    resp = mcp_http_client.post(
        "/mcp",
        json=_LIST_TOOLS_REQ,
        headers={**_ACCEPT, "Host": "attacker.example.com"},
    )
    assert resp.status_code >= 400 and resp.status_code != 200, (
        f"Foreign Host was accepted (status {resp.status_code}); "
        "DNS-rebinding/allowed_hosts guard must reject non-listed Host headers"
    )


@pytest.mark.integration
def test_allowed_host_is_accepted(mcp_http_client) -> None:
    """A request with the bound Host:port must be accepted (allowed_hosts populated)."""
    resp = mcp_http_client.post(
        "/mcp", json=_LIST_TOOLS_REQ, headers={**_ACCEPT, "Host": _GOOD_HOST}
    )
    assert resp.status_code == 200, (
        f"Bound Host {_GOOD_HOST} rejected (status {resp.status_code}); "
        "allowed_hosts must include the bind host:port"
    )


# ── (b) optional constant-time bearer ───────────────────────────────────────


@pytest.mark.integration
def test_no_bearer_middleware_when_token_unset(mcp_http_client) -> None:
    """With no token configured, requests are unauthenticated (no 401) — D-10."""
    resp = mcp_http_client.post(
        "/mcp", json=_LIST_TOOLS_REQ, headers={**_ACCEPT, "Host": _GOOD_HOST}
    )
    assert resp.status_code != 401, (
        "401 returned without a token configured — the bearer must be optional (D-10)"
    )


@pytest.mark.integration
def test_bearer_enforced_only_when_token_set() -> None:
    """With a token set: missing/wrong bearer → 401; correct bearer → not 401 (T-12-04)."""
    app = _build_app(readonly=True, token="s3cret-token")
    with TestClient(app, raise_server_exceptions=False) as client:
        # Missing Authorization → 401
        missing = client.post(
            "/mcp", json=_LIST_TOOLS_REQ, headers={**_ACCEPT, "Host": _GOOD_HOST}
        )
        assert missing.status_code == 401, (
            f"Expected 401 with token set and no Authorization, got {missing.status_code}"
        )
        # Wrong bearer → 401
        wrong = client.post(
            "/mcp",
            json=_LIST_TOOLS_REQ,
            headers={**_ACCEPT, "Host": _GOOD_HOST, "Authorization": "Bearer nope"},
        )
        assert wrong.status_code == 401, (
            f"Expected 401 with a wrong bearer, got {wrong.status_code}"
        )
        # Correct bearer → not 401 (constant-time match)
        good = client.post(
            "/mcp",
            json=_LIST_TOOLS_REQ,
            headers={**_ACCEPT, "Host": _GOOD_HOST, "Authorization": "Bearer s3cret-token"},
        )
        assert good.status_code != 401, (
            f"Correct bearer was rejected (status {good.status_code}); "
            "constant-time compare must accept the matching token"
        )


@pytest.mark.integration
def test_bearer_middleware_uses_constant_time_compare() -> None:
    """StaticBearerMiddleware must use secrets.compare_digest, never ==  (T-12-04)."""
    import inspect

    src = inspect.getsource(StaticBearerMiddleware.dispatch)
    assert "compare_digest" in src, "bearer compare must use secrets.compare_digest"
    # Strip comments before checking for a raw == token comparison (timing leak).
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    assert "==" not in code, "bearer must not use == token comparison (T-12-04)"


# ── (c) read-only posture over HTTP ─────────────────────────────────────────


@pytest.mark.integration
def test_readonly_lists_only_read_tools_over_http(mcp_http_client) -> None:
    """A server built from registered_tools(readonly=True) exposes only 4 read tools."""
    resp = mcp_http_client.post(
        "/mcp", json=_LIST_TOOLS_REQ, headers={**_ACCEPT, "Host": _GOOD_HOST}
    )
    assert resp.status_code == 200, f"tools/list failed: {resp.status_code} {resp.text[:200]}"
    result = _extract_result(resp)
    names = {t["name"] for t in result["result"]["tools"]}
    assert names == _READ_TOOLS, (
        f"read-only HTTP surface must expose exactly {_READ_TOOLS}, got {names}"
    )
