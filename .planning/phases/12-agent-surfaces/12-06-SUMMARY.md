---
phase: 12-agent-surfaces
plan: 06
subsystem: agent-surfaces
status: complete
tags: [mcp, streamable-http, security, transport, bearer, cors, dns-rebinding]
requires:
  - agent/server.py (build_server)
  - agent/registry.py (registered_tools)
  - config/settings.py (McpSettings)
  - mcp==1.28.1 (StreamableHTTPSessionManager, TransportSecuritySettings)
provides:
  - agent/http.py:build_http_app
  - agent/http.py:StaticBearerMiddleware
affects:
  - Plan 12-07 (klake mcp --sse CLI verb wires build_http_app under uvicorn)
tech-stack:
  added: []
  patterns:
    - "Route (not Mount) at /mcp with a class-instance ASGI endpoint — avoids the trailing-slash 307 redirect that drops the Authorization header"
    - "TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=[host:port, localhost:port], allowed_origins=[]) as the safe-by-default HTTP posture"
    - "Optional bearer via constant-time secrets.compare_digest, middleware attached only when token is set"
key-files:
  created:
    - src/knowledge_lake/agent/http.py
  modified:
    - tests/integration/test_mcp_http.py
decisions:
  - "Route + _StreamableHTTPASGIApp instead of Mount('/mcp') — Mount emits a 307 to /mcp/ and httpx drops Authorization on the redirect, breaking the bearer guard (mirrors FastMCP.streamable_http_app which also uses Route)"
  - "build_http_app(server=None, host=None, port=None, token=None) resolves unset args from settings.mcp so the app is localhost-safe by default and the read-only flag drives the HTTP tool set"
  - "Foreign Host rejection surfaces as HTTP 421 (Misdirected Request) from the SDK's transport-security layer; the test asserts a client-error rejection (>=400, !=200) rather than a fixed code"
metrics:
  duration: ~15m
  completed: 2026-07-11
  tasks: 2
  files: 2
---

# Phase 12 Plan 06: MCP Streamable HTTP Surface Summary

Serve the shared MCP `Server` over MCP Streamable HTTP with localhost bind, DNS-rebinding/Host protection, closed CORS, an optional constant-time bearer, and the read-only posture — the security half of MCP-02, verified by a 7-case integration test.

## What Was Built

**`agent/http.py`** — the Streamable HTTP transport, a sibling surface over the identical `Server` object so `stdio == http` by construction:

- **`build_http_app(server=None, *, host=None, port=None, token=None) -> Starlette`** mounts the Streamable-HTTP handler at `/mcp`. Unset `server`/`host`/`port` resolve from `settings.mcp` (default host `127.0.0.1`, never `0.0.0.0`), and a default `server` is built from `registered_tools(readonly=settings.mcp.readonly)` so the read-only flag filters the HTTP tool set exactly as it does for stdio.
- **`TransportSecuritySettings`** with `enable_dns_rebinding_protection=True`, `allowed_hosts=[f"{host}:{port}", f"localhost:{port}"]` (populated — an empty list with protection on rejects *all* requests), and `allowed_origins=[]` (CORS closed, D-10).
- **`StreamableHTTPSessionManager(app=server, stateless=True, security_settings=sec)`** with an `@asynccontextmanager` lifespan running `async with mgr.run()`.
- **`StaticBearerMiddleware`** — 401s any request whose `Authorization` header does not equal `Bearer {token}` using `secrets.compare_digest` (constant-time, never `==`); attached only when `token` is truthy (D-10, T-12-04).

**`tests/integration/test_mcp_http.py`** — replaced the Plan-01 xfail scaffold with 7 real integration assertions.

## Task Commits

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Streamable-HTTP app: host guard, closed CORS, read-only posture | `50294b6` | src/knowledge_lake/agent/http.py |
| 2 | Constant-time bearer middleware + HTTP integration test | `fd608d1` | src/knowledge_lake/agent/http.py, tests/integration/test_mcp_http.py |

## Verification

- `uv run pytest tests/integration/test_mcp_http.py` → **7 passed** (foreign-Host rejection, allowed-Host accept, no-auth-when-token-unset, bearer-enforced-only-when-set with missing/wrong/correct bearer, constant-time-compare source check, readonly-lists-only-4-read-tools over HTTP).
- `grep -c 'enable_dns_rebinding_protection=True' src/knowledge_lake/agent/http.py` → 1; `grep -c 'allowed_origins=\[\]'` → 1; `grep -c 'sse_app'` → 0 (deprecated transport absent); `grep -c 'compare_digest'` → 4.
- Default `settings.mcp.host` is `127.0.0.1`; `allowed_hosts` populated with the bind host:port.
- `uv run ruff check` on both files → clean.

## Must-Haves Satisfied

| Truth | Evidence |
| ----- | -------- |
| Streamable HTTP via StreamableHTTPSessionManager wrapping the SAME Server (not deprecated HTTP+SSE) | `build_http_app` builds `StreamableHTTPSessionManager(app=server, ...)`; `grep sse_app` == 0 |
| DNS-rebinding protection on + allowed_hosts populated; non-listed Host rejected | `TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=[...])`; `test_foreign_host_is_rejected` (421) |
| allowed_origins empty (CORS closed); binds 127.0.0.1 by default | `allowed_origins=[]`; host default from `settings.mcp.host` |
| Bearer 401s on mismatch (constant-time); no middleware when unset | `StaticBearerMiddleware` + `compare_digest`; `test_bearer_enforced_only_when_token_set` |
| readonly=True registers only read tools over HTTP | `test_readonly_lists_only_read_tools_over_http` → `{search, list_sources, lineage, stats}` |

## Deviations from Plan

**1. [Rule 1 - Bug] `Mount('/mcp')` broke the bearer guard via a trailing-slash redirect**
- **Found during:** Task 2 (bearer test)
- **Issue:** RESEARCH Pattern 3 uses `Mount("/mcp", app=handle)`. A `POST /mcp` against a Mount emits a 307 redirect to `/mcp/`; the httpx client (and TestClient) follows it and drops the `Authorization` header, so a request with the *correct* bearer was wrongly rejected with 401.
- **Fix:** Switched to `Route("/mcp", endpoint=_StreamableHTTPASGIApp(mgr))` — a `Route` at exactly `/mcp` with a class-instance ASGI endpoint (Starlette treats class instances as raw ASGI apps with all methods allowed). This matches how the MCP SDK's own `FastMCP.streamable_http_app` mounts the transport and eliminates the redirect.
- **Files modified:** src/knowledge_lake/agent/http.py
- **Commit:** `fd608d1`

**2. [Rule 2 - Missing critical functionality] Default-server / default-host resolution**
- **Issue:** The plan signature is `build_http_app(server, *, host, port, token)`. To keep the app localhost-safe by default and let the read-only flag drive the tool set without every caller re-deriving it, unset `server`/`host`/`port` now resolve from `settings.mcp` and a default `server` is built from `registered_tools(readonly=settings.mcp.readonly)`.
- **Files modified:** src/knowledge_lake/agent/http.py
- **Commit:** `50294b6`

## Threat Surface

No new surface beyond the plan's `<threat_model>`. T-12-01 (Host guard), T-12-02 (localhost bind + read-only + optional bearer), T-12-04 (constant-time compare), and T-12-CORS (closed CORS) are all mitigated and test-covered. No stubs introduced.

## Self-Check: PASSED

- FOUND: src/knowledge_lake/agent/http.py
- FOUND: tests/integration/test_mcp_http.py (real assertions, 7 passing)
- FOUND commit: 50294b6
- FOUND commit: fd608d1
