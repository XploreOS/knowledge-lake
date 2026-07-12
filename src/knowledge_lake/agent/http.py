"""MCP Streamable HTTP transport: build_http_app + StaticBearerMiddleware (MCP-02).

This module serves the **same** ``mcp.server.lowlevel.Server`` built by
``agent/server.py`` over MCP **Streamable HTTP** — a sibling surface to the
stdio transport so ``stdio == http`` by construction (D-01).  It is safe-by-
default for a localhost agent server:

- **Localhost bind** — default host ``127.0.0.1`` (never ``0.0.0.0``, D-09).
- **DNS-rebinding / Host guard** — ``TransportSecuritySettings`` with
  DNS-rebinding protection enabled and a populated ``allowed_hosts``
  (an empty ``allowed_hosts`` with protection on rejects *all* requests, so it
  MUST list the bind ``host:port``).  Foreign Host headers are rejected (T-12-01).
- **Closed CORS** — an empty ``allowed_origins`` keeps browser origins closed; agent
  clients are not browsers (D-10, T-12-CORS).
- **Optional constant-time bearer** — ``StaticBearerMiddleware`` 401s a request
  whose ``Authorization`` header does not match ``Bearer {token}`` using
  ``secrets.compare_digest`` (never ``==`` — timing leak, T-12-04).  The
  middleware is attached **only** when a token is configured (D-10: enforced
  only when set).
- **Read-only posture** — the ``Server`` is built from
  ``registered_tools(settings.mcp.readonly)`` so the HTTP surface exposes the
  same filtered tool set as stdio (T-12-02, D-11).

RESEARCH.md Pattern 3 is the authoritative source.  The deprecated HTTP+SSE
transport is intentionally NOT used — Streamable HTTP only (MCP-02).
"""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager

from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

# Sentinel distinguishing "token not provided" (resolve from settings) from
# "token explicitly disabled" (caller passed None/empty → no auth). Without this,
# a factory/direct caller that omits ``token`` would silently lose auth even when
# KLAKE_MCP__TOKEN is configured (WR-01 fail-open).
_UNSET = object()


class _StreamableHTTPASGIApp:
    """Minimal ASGI wrapper delegating to ``StreamableHTTPSessionManager``.

    Passing a *class instance* (not a bare function) to a Starlette ``Route``
    makes Starlette treat the endpoint as a raw ASGI app with ``methods=None``
    (all methods allowed) — the Streamable HTTP transport uses GET, POST, and
    DELETE on the same path.  Using ``Route`` (not ``Mount``) also avoids the
    trailing-slash 307 redirect a ``Mount("/mcp")`` would emit for ``POST /mcp``
    (that redirect makes httpx drop the ``Authorization`` header, breaking the
    bearer guard).
    """

    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self._manager = manager

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        await self._manager.handle_request(scope, receive, send)


class StaticBearerMiddleware(BaseHTTPMiddleware):
    """Optional constant-time bearer guard for the MCP HTTP surface (T-12-04).

    401s any request whose ``Authorization`` header does not exactly equal
    ``Bearer {token}``.  The comparison uses ``secrets.compare_digest`` — a
    constant-time compare — never ``==`` (a plain ``==`` short-circuits on the
    first mismatching byte and leaks token length/prefix via timing).

    The middleware is only attached when a token is configured (see
    ``build_http_app``); when no token is set the HTTP surface is unauthenticated
    (localhost default, D-10).
    """

    def __init__(self, app, token: str) -> None:  # noqa: ANN001
        super().__init__(app)
        # Pre-render the expected header once; compared constant-time per request.
        self._expected = f"Bearer {token}"

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001, ANN201
        provided = request.headers.get("Authorization", "")
        # secrets.compare_digest is constant-time (T-12-04) — never ``==``.
        if not secrets.compare_digest(provided, self._expected):
            return JSONResponse(
                {"error": "unauthorized", "detail": "invalid or missing bearer token"},
                status_code=401,
            )
        return await call_next(request)


def build_http_app(
    server: Server | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    token=_UNSET,  # noqa: ANN001 — sentinel default; resolved from settings below
) -> Starlette:
    """Build the MCP **Streamable HTTP** Starlette app around a shared ``Server``.

    The ``Server`` is served over Streamable HTTP (never the deprecated HTTP+SSE
    transport) at ``/mcp`` with DNS-rebinding protection, a populated
    ``allowed_hosts``, closed CORS, localhost bind, and an optional constant-time
    bearer.

    Args:
        server:  The shared ``mcp.server.lowlevel.Server``.  When ``None``, a
                 default server is built from
                 ``registered_tools(settings.mcp.readonly)`` so the HTTP surface
                 honours the read-only posture (D-11) with the same tool set as
                 stdio.
        host:    Bind host used to populate ``allowed_hosts``.  Defaults to
                 ``settings.mcp.host`` (``127.0.0.1`` — never ``0.0.0.0``, D-09).
        port:    Bind port used to populate ``allowed_hosts``.  Defaults to
                 ``settings.mcp.port``.
        token:   Optional bearer token.  When omitted, it is resolved from
                 ``settings.mcp.token`` so a configured ``KLAKE_MCP__TOKEN`` is
                 honoured automatically (WR-01 — no fail-open for direct callers).
                 Pass ``None``/empty explicitly to disable auth. When truthy,
                 ``StaticBearerMiddleware`` is attached and enforces the token
                 (constant-time); when falsy, no auth middleware is added (D-10).

    Returns:
        A Starlette ASGI app mounting the Streamable-HTTP handler at ``/mcp``.
    """
    # Resolve defaults from settings so the app is localhost-safe by default and
    # the same read-only flag that drives stdio also drives the HTTP tool set.
    # ``token`` is resolved alongside host/port/server so an omitted token still
    # honours KLAKE_MCP__TOKEN (WR-01); an explicit None/empty stays "no auth".
    if server is None or host is None or port is None or token is _UNSET:
        from knowledge_lake.config.settings import get_settings

        settings = get_settings()
        if host is None:
            host = settings.mcp.host
        if port is None:
            port = settings.mcp.port
        if token is _UNSET:
            token = settings.mcp.token
        if server is None:
            from knowledge_lake.agent.registry import registered_tools
            from knowledge_lake.agent.server import build_server

            server = build_server(registered_tools(readonly=settings.mcp.readonly))

    # DNS-rebinding / Host guard.  allowed_hosts MUST be populated — with
    # protection on and an empty list, ALL requests are rejected (T-12-01).
    # An empty allowed_origins keeps browser CORS closed (D-10, T-12-CORS).
    sec = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"{host}:{port}", f"localhost:{port}"],
        allowed_origins=[],
    )

    # One Server, Streamable-HTTP transport — stateless single-user localhost server.
    mgr = StreamableHTTPSessionManager(app=server, stateless=True, security_settings=sec)

    @asynccontextmanager
    async def lifespan(app):  # noqa: ANN001, ANN202
        async with mgr.run():
            yield

    # Attach the bearer middleware ONLY when a token is configured (D-10).
    middleware = [Middleware(StaticBearerMiddleware, token=token)] if token else []

    # Route (not Mount) at exactly /mcp: no trailing-slash redirect, all methods.
    return Starlette(
        routes=[Route("/mcp", endpoint=_StreamableHTTPASGIApp(mgr))],
        lifespan=lifespan,
        middleware=middleware,
    )
