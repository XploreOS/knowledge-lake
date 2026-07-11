"""OpenAI function-tool definitions from the MCP registry (SKILL-03, D-15).

``openai_tool_defs(tools)`` emits one OpenAI
``{"type": "function", "function": {name, description, parameters}}`` object per
``ToolDef``, using ``t.input_model.model_json_schema()`` as the ``parameters``
block — the **same** schema call that produces the MCP ``inputSchema`` in
``agent/server.py`` (D-01/D-15).  One Pydantic model, two surfaces: an agent using
OpenAI function-calling and an agent using MCP see byte-identical argument schemas
for every tool because both derive from ``model_json_schema()``.

``render_openai_tools_json`` / ``write_openai_tools_json`` produce the deterministic
committed artifact ``docs/openai_tools.json`` as
``json.dumps(..., indent=2, sort_keys=True) + "\n"`` so re-generating it is a no-op
git diff (Pitfall 3).
"""

from __future__ import annotations

import json
from pathlib import Path


def openai_tool_defs(tools) -> list[dict]:
    """Return OpenAI function-tool defs generated from the tool registry.

    One ``{"type": "function", "function": {"name", "description", "parameters"}}``
    object per tool.  ``parameters`` is ``t.input_model.model_json_schema()`` — the
    SAME schema source as the MCP ``inputSchema`` (D-15), so the OpenAI and MCP
    surfaces expose identical argument schemas.

    Args:
        tools: An iterable of ``ToolDef`` entries (typically ``registry.TOOLS``).

    Returns:
        A list of OpenAI function-tool dicts, one per tool.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_model.model_json_schema(),
            },
        }
        for t in tools
    ]


def render_openai_tools_json(tools) -> str:
    """Render the deterministic committed dump of ``openai_tool_defs(tools)``.

    Uses ``sort_keys=True`` and a trailing newline so re-runs produce no-op diffs
    (Pitfall 3 — deterministic committed artifact).
    """
    return json.dumps(openai_tool_defs(tools), indent=2, sort_keys=True) + "\n"


def write_openai_tools_json(path: str | Path, tools) -> Path:
    """Write ``docs/openai_tools.json`` deterministically and return the path."""
    out = Path(path)
    out.write_text(render_openai_tools_json(tools), encoding="utf-8")
    return out
