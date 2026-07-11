"""fd-level stdout lockdown for the MCP stdio transport.

DESIGN RATIONALE (RESEARCH.md Pattern 2 / Pitfall 1 / D-07)
------------------------------------------------------------
``src/knowledge_lake/__init__.py`` configures structlog with
``PrintLoggerFactory()`` (no ``file=`` arg) which defaults to **stdout** —
the same channel the MCP stdio JSON-RPC framing owns.  Any stray log, print,
or C-extension write on stdout corrupts the JSON-RPC stream and kills the
session.

An fd-level ``dup2`` is the robust fix because it catches writes that Python-
level logger reconfiguration cannot (C extensions, subprocess inheritance).

Mandatory ordering (RESEARCH.md anti-pattern guard):
  1. ``os.dup(1)``        — preserve the real JSON-RPC fd BEFORE any redirect
  2. ``os.dup2(2, 1)``    — point process fd 1 at stderr
  3. reconfigure loggers  — belt-and-suspenders for Python-level writes
  4. ``stdio_server(stdout=preserved)`` — pass the preserved handle explicitly

If you call dup2 before dup, JSON-RPC frames go to stderr and the client sees
nothing.  If you let the SDK grab ``sys.stdout.buffer`` after the dup2, same
outcome (SDK grabs at call time — verified in mcp.server.stdio source).

This module is stdio-only.  HTTP mode never calls ``run_stdio`` (D-08).
"""

from __future__ import annotations

import logging
import os
import sys
from io import TextIOWrapper

import anyio
import structlog
from mcp.server.lowlevel import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server


async def run_stdio(
    server: Server,
    init_opts: InitializationOptions,
) -> None:
    """Run *server* on the stdio transport with an fd-level stdout lockdown.

    Applies the lockdown in this exact order so that no log, print, or
    C-extension byte can corrupt the JSON-RPC channel:

    1. Preserve the real JSON-RPC fd with ``os.dup(1)`` — **must run before
       any redirect** so the fd is still pointing at the original stdout.
    2. Redirect process fd 1 to stderr with ``os.dup2(2, 1)`` and update
       ``sys.stdout`` so Python-level ``print()`` also goes to stderr.
    3. Reconfigure structlog's ``PrintLoggerFactory`` to ``sys.stderr``
       (mirrors the processor list in ``knowledge_lake.__init__._configure_logging``),
       set ``logging.basicConfig(stream=sys.stderr)``, and
       ``logging.captureWarnings(True)`` so all Python-level emitters are
       redirected.
    4. Build a clean binary stream on the *preserved* fd, wrap it in
       ``anyio.wrap_file``, and pass it explicitly as
       ``stdio_server(stdout=preserved)`` — if the SDK were to grab
       ``sys.stdout.buffer`` instead, it would pick up the redirected-to-stderr
       handle and JSON-RPC would be written to stderr.

    Parameters
    ----------
    server:
        The pre-built low-level MCP ``Server`` instance (already has
        ``list_tools`` + ``call_tool`` handlers registered).
    init_opts:
        ``InitializationOptions`` produced by
        ``server.create_initialization_options()``.
    """
    # ── Step 1: preserve the real JSON-RPC stdout fd BEFORE any redirect ──────
    real_fd = os.dup(1)  # preserve fd 1 while it still points at the real stdout

    # ── Step 2: redirect process fd 1 → stderr so stray writes cannot corrupt ─
    os.dup2(2, 1)                    # point fd 1 at stderr at the OS level
    sys.stdout = sys.stderr          # Python-level print() → stderr too

    # ── Step 3: reconfigure all Python logging to stderr ──────────────────────
    # Mirror the processor list from knowledge_lake.__init__._configure_logging
    # but swap the logger_factory to write to sys.stderr instead of stdout.
    _use_dev = (
        sys.stderr.isatty()
        or os.environ.get("KLAKE_LOG_FORMAT", "").lower() == "dev"
    )
    _renderer = (
        structlog.dev.ConsoleRenderer()
        if _use_dev
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,  # force re-bind to the new factory
    )

    # Stdlib logging and warnings → stderr
    logging.basicConfig(stream=sys.stderr, force=True)
    logging.captureWarnings(True)

    # ── Step 4: build the preserved stream and hand it to the SDK ─────────────
    # anyio.wrap_file wraps a sync file-like into an AsyncFile;
    # TextIOWrapper around the raw wb fd gives us a text-mode write handle.
    preserved = anyio.wrap_file(
        TextIOWrapper(os.fdopen(real_fd, "wb", buffering=0), encoding="utf-8")
    )

    # stdio_server(stdout=preserved) is MANDATORY — do not rely on the SDK
    # picking up sys.stdout.buffer, which now points at stderr after the dup2.
    async with stdio_server(stdout=preserved) as (read, write):
        await server.run(read, write, init_opts)
