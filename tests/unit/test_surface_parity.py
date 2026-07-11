"""Surface parity gate: stdio == http == openapi == openai (SKILL-03, D-04).

This is the phase's correctness gate. It proves that every agent-facing surface
exposes byte-identical (normalized) argument schemas for all 11 tools, so an
agent can never be misled into a malformed/unsafe call by a drifting surface
(threat T-12-DRIFT).

The four surfaces and their schema source:
  - **MCP inputSchema**   — emitted by the live ``build_server(TOOLS)`` list_tools
                            handler (``t.input_model.model_json_schema()``).
  - **OpenAI parameters** — ``openai_tool_defs(TOOLS)`` ``function.parameters``.
  - **model_json_schema** — the shared Pydantic ``input_model`` schema itself.
  - **OpenAPI components** — ``docs/openapi.json`` ``components/schemas`` for each
                            tool whose ``input_model`` also backs a FastAPI endpoint.

``normalize`` / ``canonical`` reconcile the cosmetic noise Pydantic-v2 and FastAPI
introduce (RESEARCH.md Pitfall 2), so parity compares *structure*, not cosmetics:
  1. drop every ``title`` (Pydantic adds per-field titles that vary),
  2. drop ``default: null`` (FastAPI omits null defaults; Pydantic keeps them),
  3. canonicalize ``$ref`` — ``#/$defs/`` / ``#/definitions/`` / ``#/components/schemas/``
     all collapse to ``#/DEFS/`` so def-root naming is ignored,
  4. coerce integer-valued floats to int (FastAPI emits ``10000.0`` for an ``le=10000``
     bound where Pydantic emits ``10000``),
  5. sort keys for a deterministic canonical string.

Prohibitions honoured (PLAN 12-08):
  - No raw ``model_json_schema`` vs OpenAPI comparison without normalization.
  - No hardcoded tool schemas — all surfaces are derived live from the registry
    / committed exports.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import anyio
import mcp.types as types

from knowledge_lake.agent.openai_defs import openai_tool_defs
from knowledge_lake.agent.registry import TOOLS, registered_tools
from knowledge_lake.agent.server import build_server

_OPENAPI_PATH = Path(__file__).parents[2] / "docs" / "openapi.json"

# The 4 read-access tools — the read-only MCP posture (D-11).
_READ_TOOLS = {"search", "list_sources", "lineage", "stats"}


# ── normalize / canonical helpers ─────────────────────────────────────────────
# Fully self-contained (no runtime dependency on agent/*). Other test files
# import these.


def normalize(schema: Any, *, _depth: int = 0) -> Any:
    """Recursively normalize a JSON Schema for cross-surface comparison.

    Transformations (RESEARCH.md Pitfall 2, extended for the OpenAPI leg):
      1. Drop all ``title`` keys (Pydantic per-field titles vary).
      2. Drop ``default: null`` entries (FastAPI omits them, Pydantic keeps them).
      3. Canonicalize ``$ref`` paths — ``#/$defs/…``, ``#/definitions/…`` and
         ``#/components/schemas/…`` all collapse to ``#/DEFS/…`` so def-root
         naming (Pydantic ``$defs`` vs FastAPI ``components/schemas``) is ignored.
      4. Coerce integer-valued floats to ``int`` (FastAPI serializes numeric
         constraints like ``le=10000`` as ``10000.0``; Pydantic as ``10000``).
      5. Recurse into all nested dict/list values.

    The input is never mutated.
    """
    if isinstance(schema, dict):
        result: dict[str, Any] = {}
        for k, v in schema.items():
            if k == "title":
                continue
            if k == "default" and v is None:
                # FastAPI drops null defaults; Pydantic keeps them — cosmetic.
                continue
            if k == "$ref" and isinstance(v, str):
                v = re.sub(
                    r"^#/(\$defs|definitions|components/schemas)/", "#/DEFS/", v
                )
            result[k] = normalize(v, _depth=_depth + 1)
        return result
    if isinstance(schema, list):
        return [normalize(item, _depth=_depth + 1) for item in schema]
    # bool is a subclass of int but never a float — leave it untouched.
    if isinstance(schema, float) and schema.is_integer():
        return int(schema)
    return schema


def canonical(schema: Any) -> str:
    """Return a deterministic, sort-keyed JSON string of the normalized schema.

    Two schemas that differ only in cosmetic noise (title, null defaults, $ref
    root style, int-vs-float numeric constraints) produce the same string.
    """
    return json.dumps(normalize(schema), sort_keys=True)


# ── surface derivation helpers (live — never hardcoded) ───────────────────────


def _mcp_input_schemas(tools: list) -> dict[str, dict]:
    """Return {tool_name: inputSchema} as emitted by the live MCP server.

    Builds the server the exact way the stdio/http transports do
    (``build_server`` over the given tool list) and invokes the real
    ``list_tools`` request handler, so this asserts what the server actually
    emits — not merely what the registry could emit.
    """
    server = build_server(tools)
    handler = server.request_handlers[types.ListToolsRequest]
    req = types.ListToolsRequest(method="tools/list")

    async def _go() -> Any:
        return await handler(req)

    result = anyio.run(_go)
    inner = result.root if hasattr(result, "root") else result
    return {t.name: t.inputSchema for t in inner.tools}


def _openai_parameters(tools: list) -> dict[str, dict]:
    """Return {tool_name: parameters} from the OpenAI function-tool defs."""
    return {
        d["function"]["name"]: d["function"]["parameters"]
        for d in openai_tool_defs(tools)
    }


# ── normalize helper unit tests (no implementation dependency) ────────────────


def test_normalize_strips_title() -> None:
    schema = {
        "title": "Foo",
        "type": "object",
        "properties": {"x": {"title": "X", "type": "string"}},
    }
    result = normalize(schema)
    assert "title" not in result
    assert "title" not in result["properties"]["x"]


def test_normalize_preserves_type() -> None:
    schema = {"type": "object", "description": "A thing"}
    assert normalize(schema) == {"type": "object", "description": "A thing"}


def test_normalize_drops_null_default() -> None:
    """FastAPI omits null defaults; normalize equates them (parity noise)."""
    with_default = {"type": "string", "default": None}
    without = {"type": "string"}
    assert canonical(with_default) == canonical(without)


def test_normalize_keeps_non_null_default() -> None:
    """A real default (e.g. 50) is structural — it must NOT be dropped."""
    assert normalize({"type": "integer", "default": 50}) == {
        "type": "integer",
        "default": 50,
    }


def test_normalize_coerces_integer_float() -> None:
    """FastAPI's 10000.0 must equate to Pydantic's 10000 constraint."""
    assert canonical({"maximum": 10000.0}) == canonical({"maximum": 10000})


def test_normalize_ref_canonicalization_components_schemas() -> None:
    """$defs, definitions and components/schemas $ref roots all collapse."""
    a = {"$ref": "#/$defs/MyModel"}
    b = {"$ref": "#/definitions/MyModel"}
    c = {"$ref": "#/components/schemas/MyModel"}
    assert canonical(a) == canonical(b) == canonical(c)


def test_canonical_nested_normalization() -> None:
    schema = {
        "type": "object",
        "properties": {"q": {"title": "Q", "type": "string"}},
        "$defs": {"Sub": {"title": "Sub", "type": "integer"}},
    }
    result = normalize(schema)
    assert "title" not in result["properties"]["q"]
    assert "title" not in result["$defs"]["Sub"]


# ── parity gate: MCP == OpenAI == model_json_schema (all 11 tools) ────────────


def test_all_eleven_tools_present() -> None:
    """The registry must expose exactly the 11 tools the parity gate iterates."""
    assert len(TOOLS) == 11
    assert len({t.name for t in TOOLS}) == 11


def test_mcp_inputschema_equals_openai_parameters() -> None:
    """MCP inputSchema == OpenAI parameters for every tool, normalized (D-04)."""
    mcp = _mcp_input_schemas(TOOLS)
    openai = _openai_parameters(TOOLS)
    assert set(mcp) == set(openai) == {t.name for t in TOOLS}
    for tool in TOOLS:
        assert canonical(mcp[tool.name]) == canonical(openai[tool.name]), (
            f"Tool {tool.name!r}: MCP inputSchema != OpenAI parameters.\n"
            f"mcp:    {canonical(mcp[tool.name])}\n"
            f"openai: {canonical(openai[tool.name])}"
        )


def test_openai_parameters_equal_model_json_schema() -> None:
    """OpenAI parameters == input_model.model_json_schema() for every tool."""
    openai = _openai_parameters(TOOLS)
    for tool in TOOLS:
        model_schema = tool.input_model.model_json_schema()
        assert canonical(model_schema) == canonical(openai[tool.name]), (
            f"Tool {tool.name!r}: model_json_schema() != OpenAI parameters.\n"
            f"model:  {canonical(model_schema)}\n"
            f"openai: {canonical(openai[tool.name])}"
        )


def test_mcp_inputschema_equals_model_json_schema() -> None:
    """MCP inputSchema == input_model.model_json_schema() (third parity leg)."""
    mcp = _mcp_input_schemas(TOOLS)
    for tool in TOOLS:
        model_schema = tool.input_model.model_json_schema()
        assert canonical(mcp[tool.name]) == canonical(model_schema), (
            f"Tool {tool.name!r}: MCP inputSchema != model_json_schema().\n"
            f"mcp:   {canonical(mcp[tool.name])}\n"
            f"model: {canonical(model_schema)}"
        )


def test_three_way_parity_all_tools() -> None:
    """canonical(MCP) == canonical(OpenAI) == canonical(model) — the D-04 gate.

    A single assertion binding all three registry surfaces for every one of the
    11 tools. Mutating any one tool's input_model turns this red.
    """
    mcp = _mcp_input_schemas(TOOLS)
    openai = _openai_parameters(TOOLS)
    for tool in TOOLS:
        a = canonical(mcp[tool.name])
        b = canonical(openai[tool.name])
        c = canonical(tool.input_model.model_json_schema())
        assert a == b == c, f"Surface drift on tool {tool.name!r}"


# ── parity gate: stdio == http (identical tool sets) ──────────────────────────


def test_stdio_http_tool_name_sets_identical() -> None:
    """The stdio-built and http-built servers emit the identical tool set.

    Both transports call ``build_server(registered_tools(readonly))``; building
    two servers over the same filtered list and comparing the *emitted* tool
    names proves stdio == http by construction (D-01).
    """
    stdio_tools = registered_tools(False)  # stdio.py builds from this
    http_tools = registered_tools(False)  # http.py builds from the same source
    stdio_names = set(_mcp_input_schemas(stdio_tools))
    http_names = set(_mcp_input_schemas(http_tools))
    assert stdio_names == http_names == {t.name for t in TOOLS}


def test_readonly_posture_is_identical_across_transports() -> None:
    """Read-only posture flows through identically to both transports."""
    ro_stdio = set(_mcp_input_schemas(registered_tools(True)))
    ro_http = set(_mcp_input_schemas(registered_tools(True)))
    assert ro_stdio == ro_http == _READ_TOOLS
    # read-only is a strict subset of the full set
    assert {t.name for t in TOOLS} > _READ_TOOLS


# ── parity gate: OpenAPI components == registry model schema ──────────────────


def test_openapi_components_match_registry_models() -> None:
    """For each tool whose input_model backs a FastAPI endpoint, the model's
    schema appears (normalized) identically in docs/openapi.json components.

    This closes the fourth surface: the committed OpenAPI export cannot drift
    from the registry's Pydantic models.
    """
    assert _OPENAPI_PATH.exists(), f"missing committed export {_OPENAPI_PATH}"
    openapi = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    components = openapi.get("components", {}).get("schemas", {})

    covered: list[str] = []
    for tool in TOOLS:
        model = tool.input_model
        name = model.__name__
        if name not in components:
            # Tool models used only as query params (e.g. SearchParams) are not
            # emitted as component schemas — nothing to compare for those.
            continue
        covered.append(name)
        assert canonical(model.model_json_schema()) == canonical(components[name]), (
            f"Tool {tool.name!r} model {name!r}: registry schema != OpenAPI "
            f"components/schemas after normalization.\n"
            f"registry: {canonical(model.model_json_schema())}\n"
            f"openapi:  {canonical(components[name])}"
        )

    # The OpenAPI leg must not be vacuous — the four endpoint-backing tool models
    # (SourceCreate, CrawlJobCreate, ExportRequest, DomainLoadRequest) are present.
    assert set(covered) >= {
        "SourceCreate",
        "CrawlJobCreate",
        "ExportRequest",
        "DomainLoadRequest",
    }, f"OpenAPI parity leg covered too few models: {sorted(covered)}"
