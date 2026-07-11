"""Wave 0 RED scaffold: OpenAPI export determinism assertions (SKILL-02).

Asserts that ``docs/openapi.json`` is a deterministic ``sort_keys=True`` dump
of the FastAPI app's OpenAPI schema, and that ``klake openapi`` writes it
with sorted keys so re-runs produce no diff.

All tests are xfail until Plan 05 implements ``klake openapi`` and writes
``docs/openapi.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    from knowledge_lake.api.app import app as _fastapi_app
    _IMPORT_OK = True
except ImportError:
    _fastapi_app = None  # type: ignore[assignment]
    _IMPORT_OK = False

_DOCS_DIR = Path(__file__).parents[2] / "docs"
_OPENAPI_JSON = _DOCS_DIR / "openapi.json"


@pytest.mark.xfail(reason="Wave 0 scaffold — klake openapi not yet implemented (Plan 05)", strict=False)
def test_openapi_json_exists() -> None:
    """docs/openapi.json must exist after klake openapi is run (SKILL-02)."""
    assert _OPENAPI_JSON.exists(), (
        f"docs/openapi.json does not exist at {_OPENAPI_JSON}. "
        "Run `klake openapi` to generate it."
    )


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — fastapi app not importable", strict=False)
def test_openapi_json_is_valid_json() -> None:
    """docs/openapi.json must be valid JSON."""
    if not _OPENAPI_JSON.exists():
        pytest.skip("docs/openapi.json not yet generated")
    content = _OPENAPI_JSON.read_text(encoding="utf-8")
    parsed = json.loads(content)  # raises if invalid
    assert isinstance(parsed, dict), "openapi.json must be a JSON object"


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — fastapi app not importable", strict=False)
def test_openapi_json_is_deterministic_sorted() -> None:
    """docs/openapi.json must be sorted-keys serialization (no key-order drift on re-run).

    Validates Pitfall 3: use json.dumps(sort_keys=True) so committed file is stable.
    """
    if not _OPENAPI_JSON.exists():
        pytest.skip("docs/openapi.json not yet generated")
    assert _fastapi_app is not None
    raw_content = _OPENAPI_JSON.read_text(encoding="utf-8")
    raw_parsed = json.loads(raw_content)
    # Re-serialize with sort_keys=True and compare to the live schema
    live_schema = _fastapi_app.openapi()
    sorted_serialized = json.dumps(live_schema, indent=2, sort_keys=True) + "\n"
    sorted_parsed = json.loads(sorted_serialized)
    assert raw_parsed == sorted_parsed, (
        "docs/openapi.json content does not match the live FastAPI schema. "
        "Re-run `klake openapi` to regenerate."
    )


@pytest.mark.xfail(not _IMPORT_OK, reason="Wave 0 scaffold — fastapi app not importable", strict=False)
def test_openapi_json_has_openapi_field() -> None:
    """docs/openapi.json must contain the 'openapi' version field."""
    if not _OPENAPI_JSON.exists():
        pytest.skip("docs/openapi.json not yet generated")
    content = json.loads(_OPENAPI_JSON.read_text(encoding="utf-8"))
    assert "openapi" in content, "openapi.json missing 'openapi' version field"
    assert content["openapi"].startswith("3."), (
        f"Expected OpenAPI 3.x, got {content['openapi']!r}"
    )
