"""MCP server core: build_server — list_tools + call_tool (D-01, MCP-01).

This module builds the single ``mcp.server.lowlevel.Server`` instance that is
reused by every transport (stdio, HTTP).  The server is constructed from a
pre-filtered ``list[ToolDef]`` so the read-only posture flows through unchanged —
the caller (stdio.py / http.py) passes ``registered_tools(readonly=...)`` directly.

Key design decisions (PLAN 12-05 must_haves):
- One Server object, two transports  →  ``stdio == http`` by construction (D-01)
- inputSchema = input_model.model_json_schema()  →  single source of truth (D-01)
- Async bridge uses ``await`` for async handlers (D-12 correction)
- Expected errors return ``CallToolResult(isError=True)``; unexpected propagate (D-13)
- Dict returns are passed directly — SDK auto-wraps as structuredContent + TextContent
- Server validates inputs with validate_input=True  →  double validation (T-12-07)

RESEARCH.md Pattern 1 is the authoritative source; Pattern 4 is the async bridge.
"""

from __future__ import annotations

import inspect
import logging

import mcp.types as types
from mcp.server.lowlevel import Server

log = logging.getLogger(__name__)

# Expected errors that map to isError=True (D-13).
# ValueError  — invalid args, missing dataset, bad kind, etc.
# LookupError — unknown artifact ID, unknown source, etc.
# All others propagate as protocol errors (SDK converts via _make_error_result).
_EXPECTED_ERRORS = (ValueError, LookupError)

# TrainEvalContaminationError is imported lazily to avoid a hard dep at module
# level — it lives in pipeline.export which is import-heavy.


def build_server(tools: "list") -> Server:
    """Build a low-level MCP Server from the provided tool list.

    The server exposes ``list_tools`` and ``call_tool`` handlers.  Pass the
    result of ``registered_tools(readonly=...)`` to enforce the read-only
    posture before building.

    Args:
        tools: A pre-filtered list of ``ToolDef`` entries (from registry.py).
               Typically ``registered_tools(readonly=settings.mcp.readonly)``.

    Returns:
        A configured ``mcp.server.lowlevel.Server`` ready to run on any
        transport.
    """
    # Avoid circular import: registry imports are at the call site; here we only
    # need the ToolDef *type* for annotation purposes, hence the string annotation.
    server = Server("knowledge-lake")
    by_name = {t.name: t for t in tools}

    # ── list_tools ─────────────────────────────────────────────────────────────

    @server.list_tools()
    async def _list() -> list[types.Tool]:
        """Return one Tool per ToolDef with inputSchema from input_model."""
        return [
            types.Tool(
                name=t.name,
                description=t.description,
                inputSchema=t.input_model.model_json_schema(),  # D-01: one schema source
            )
            for t in tools
        ]

    # ── call_tool ──────────────────────────────────────────────────────────────

    @server.call_tool()
    async def _call(name: str, arguments: dict) -> object:
        """Validate arguments, invoke the handler, return the result.

        Flow (RESEARCH.md Pattern 1 + Pattern 4):
        1. Look up the ToolDef by name (KeyError → protocol error, not isError).
        2. Construct input_model(**arguments) for Pydantic re-validation (T-12-07).
        3. Unpack via model_dump(exclude_none=True) — excludes unset optionals.
        4. Invoke handler:
           - async (crawl_source, crawl_all_sources) → await directly (D-12)
           - sync (everything else) → call directly
        5. Expected errors → CallToolResult(isError=True) (D-13).
        6. Dict returns pass through (SDK auto-wraps as structuredContent + text).
        """
        tdef = by_name[name]  # KeyError propagates → protocol error (not our concern)

        # Pydantic double-validation (T-12-07: SDK validates inputSchema JSON schema
        # first, then we re-validate via the Pydantic model for coercion + type safety)
        model = tdef.input_model(**arguments)
        kwargs = model.model_dump(exclude_none=True)

        fn = tdef.handler

        try:
            # Async bridge (D-12 correction): inside the async call_tool handler
            # the event loop is already running — await async handlers directly.
            if inspect.iscoroutinefunction(fn):
                result = await fn(**kwargs)  # crawl_source / crawl_all_sources
            else:
                result = fn(**kwargs)  # all sync handlers

        except _EXPECTED_ERRORS as exc:
            # D-13: expected errors produce a readable isError result; the client
            # sees the message without exposing internal stack traces.
            log.warning("mcp.call_tool.expected_error", tool=name, error=str(exc))
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=str(exc))],
                isError=True,
            )

        except Exception:
            # Lazy import to avoid hard dependency at module load time.
            # TrainEvalContaminationError is a RuntimeError subclass.
            try:
                from knowledge_lake.pipeline.export import TrainEvalContaminationError
            except ImportError:
                TrainEvalContaminationError = None  # type: ignore[assignment,misc]

            # Re-raise the current exception context
            import sys
            exc_info = sys.exc_info()
            exc = exc_info[1]

            if TrainEvalContaminationError is not None and isinstance(
                exc, TrainEvalContaminationError
            ):
                # D-13: contamination errors are expected — surface readable message
                log.warning("mcp.call_tool.contamination_error", tool=name, error=str(exc))
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=str(exc))],
                    isError=True,
                )
            # Unexpected exceptions propagate — SDK wraps them via _make_error_result
            raise

        # Dict return: SDK auto-wraps as structuredContent + TextContent (verified in
        # mcp.server.lowlevel.Server.call_tool source — RESEARCH.md Pattern 1 note).
        if isinstance(result, dict):
            return result
        # Non-dict returns (list, str, None) — wrap in a dict for consistency
        return {"result": result}

    return server
