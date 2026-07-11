"""Wave 0 RED scaffold + normalize() parity helper (SKILL-03, D-04).

The ``normalize`` and ``canonical`` helpers are implemented here (no implementation
dependency) and can be imported by other tests.

Surface parity asserts:
  - stdio inputSchema == openai parameters == model_json_schema, normalized.
  - Schemas are compared after stripping ``title`` and canonicalizing ``$ref``/``$defs``.

Tests are xfail until Plan 02 (registry) + Plan 03 (server) + Plan 07 (openai_defs) land.
Uses import-guard pattern from test_api_new_endpoints.py lines 12-19.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

try:
    from knowledge_lake.agent.registry import TOOLS
    _REGISTRY_OK = True
except ImportError:
    TOOLS = None  # type: ignore[assignment]
    _REGISTRY_OK = False

try:
    from knowledge_lake.agent.openai_defs import openai_tool_defs
    _OPENAI_OK = True
except ImportError:
    openai_tool_defs = None  # type: ignore[assignment]
    _OPENAI_OK = False

try:
    from knowledge_lake.agent.server import build_server
    _SERVER_OK = True
except ImportError:
    build_server = None  # type: ignore[assignment]
    _SERVER_OK = False

_IMPORT_OK = _REGISTRY_OK and _OPENAI_OK and _SERVER_OK

# ── normalize / canonical helpers ────────────────────────────────────────────
# These are fully implemented here — they have no runtime dependency on the
# agent/* modules that are not yet built. Other test files may import them.


def normalize(schema: Any, *, _depth: int = 0) -> Any:
    """Recursively normalize a JSON Schema for comparison.

    Transformations (RESEARCH.md Pitfall 2):
    1. Drop all ``title`` keys (Pydantic adds per-field titles that vary).
    2. Canonicalize ``$ref`` paths: replace any ``#/$defs/...`` or
       ``#/definitions/...`` prefix with the canonical token
       ``#/DEFS/`` so schema shape comparison ignores definition-root names.
    3. Recursively normalize all nested dict/list values.

    Args:
        schema: Any JSON-serializable value (dict, list, str, int, bool, None).

    Returns:
        A new normalized value (input is not mutated).
    """
    if isinstance(schema, dict):
        result: dict[str, Any] = {}
        for k, v in schema.items():
            if k == "title":
                # Drop title everywhere
                continue
            if k == "$ref" and isinstance(v, str):
                # Canonicalize $ref path
                v = re.sub(r"^#/(\$defs|definitions)/", "#/DEFS/", v)
            result[k] = normalize(v, _depth=_depth + 1)
        return result
    elif isinstance(schema, list):
        return [normalize(item, _depth=_depth + 1) for item in schema]
    else:
        return schema


def canonical(schema: Any) -> str:
    """Return a deterministic, sort-keyed JSON string of the normalized schema.

    Two schemas that differ only in ``title`` fields or ``$ref``/``$defs``
    prefix styles will produce the same canonical string.

    Args:
        schema: Any JSON-serializable value.

    Returns:
        A JSON string with ``sort_keys=True``.
    """
    return json.dumps(normalize(schema), sort_keys=True)


# ── helper tests (no implementation dependency) ───────────────────────────────


def test_normalize_strips_title() -> None:
    """normalize() must drop 'title' at any nesting level."""
    schema = {"title": "Foo", "type": "object", "properties": {"x": {"title": "X", "type": "string"}}}
    result = normalize(schema)
    assert "title" not in result
    assert "title" not in result["properties"]["x"]


def test_normalize_preserves_type() -> None:
    """normalize() must preserve non-title fields."""
    schema = {"type": "object", "description": "A thing"}
    assert normalize(schema) == {"type": "object", "description": "A thing"}


def test_canonical_equality_strips_title() -> None:
    """canonical() must equate schemas that differ only in title (Pitfall 2)."""
    s1 = {"title": "X", "type": "object"}
    s2 = {"type": "object"}
    assert canonical(s1) == canonical(s2), (
        "canonical() did not strip title before comparison"
    )


def test_canonical_ref_canonicalization() -> None:
    """canonical() must equate $ref paths under $defs vs definitions."""
    s1 = {"$ref": "#/$defs/MyModel"}
    s2 = {"$ref": "#/definitions/MyModel"}
    # Both should normalize to #/DEFS/MyModel
    assert canonical(s1) == canonical(s2), (
        "canonical() did not canonicalize $ref/$defs paths"
    )


def test_canonical_nested_normalization() -> None:
    """canonical() must normalize nested structures recursively."""
    schema = {
        "type": "object",
        "properties": {
            "q": {"title": "Q", "type": "string"},
        },
        "$defs": {
            "Sub": {"title": "Sub", "type": "integer"},
        },
    }
    result = normalize(schema)
    assert "title" not in result["properties"]["q"]
    assert "title" not in result["$defs"]["Sub"]


# ── parity tests (require implementation) ─────────────────────────────────────


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — agent modules not yet implemented", strict=False)
def test_stdio_schema_matches_openai_parameters() -> None:
    """inputSchema for each tool must match openai 'parameters' schema, normalized (D-04)."""
    assert TOOLS is not None
    assert openai_tool_defs is not None
    openai_defs_map = {d["function"]["name"]: d["function"]["parameters"] for d in openai_tool_defs()}
    for tool in TOOLS:
        assert tool.name in openai_defs_map, f"Tool {tool.name!r} missing from openai_tool_defs()"
        stdio_schema = tool.input_model.model_json_schema()
        openai_params = openai_defs_map[tool.name]
        assert canonical(stdio_schema) == canonical(openai_params), (
            f"Tool {tool.name!r}: stdio inputSchema != openai parameters after normalization.\n"
            f"stdio:  {canonical(stdio_schema)}\n"
            f"openai: {canonical(openai_params)}"
        )


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — agent modules not yet implemented", strict=False)
def test_openai_schema_matches_model_json_schema() -> None:
    """openai_tool_defs() parameters must equal model_json_schema() for each tool (SKILL-03)."""
    assert TOOLS is not None
    assert openai_tool_defs is not None
    openai_defs_map = {d["function"]["name"]: d["function"]["parameters"] for d in openai_tool_defs()}
    for tool in TOOLS:
        model_schema = tool.input_model.model_json_schema()
        openai_params = openai_defs_map.get(tool.name)
        assert openai_params is not None, f"openai_tool_defs() missing tool {tool.name!r}"
        assert canonical(model_schema) == canonical(openai_params), (
            f"Tool {tool.name!r}: model_json_schema() != openai parameters.\n"
            f"model:  {canonical(model_schema)}\n"
            f"openai: {canonical(openai_params)}"
        )
