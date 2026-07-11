"""OpenAPI export determinism tests (SKILL-02).

Asserts ``docs/openapi.json`` exists, is valid JSON with an ``openapi`` version
field, and is byte-identical to a fresh deterministic ``sort_keys=True`` dump of
the FastAPI app's OpenAPI schema — i.e. re-running ``klake openapi`` is a no-op
git diff (Pitfall 3).
"""

from __future__ import annotations

import json
from pathlib import Path

from knowledge_lake.api.app import app as _fastapi_app

_DOCS_DIR = Path(__file__).parents[2] / "docs"
_OPENAPI_JSON = _DOCS_DIR / "openapi.json"


def _live_dump() -> str:
    """The deterministic dump `klake openapi` writes — the single source of truth."""
    return json.dumps(_fastapi_app.openapi(), indent=2, sort_keys=True) + "\n"


def test_openapi_json_exists() -> None:
    """docs/openapi.json must be committed (SKILL-02)."""
    assert _OPENAPI_JSON.exists(), (
        f"docs/openapi.json does not exist at {_OPENAPI_JSON}. Run `klake openapi`."
    )


def test_openapi_json_is_valid_json_with_version() -> None:
    """docs/openapi.json must be valid JSON carrying an OpenAPI 3.x version field."""
    content = json.loads(_OPENAPI_JSON.read_text(encoding="utf-8"))
    assert isinstance(content, dict), "openapi.json must be a JSON object"
    assert "openapi" in content, "openapi.json missing 'openapi' version field"
    assert content["openapi"].startswith("3."), (
        f"Expected OpenAPI 3.x, got {content['openapi']!r}"
    )


def test_openapi_json_matches_deterministic_dump() -> None:
    """Committed file must be byte-identical to a fresh deterministic dump.

    Validates Pitfall 3: ``json.dumps(sort_keys=True) + "\\n"`` makes re-export a
    no-op diff. If this fails the committed file is stale — re-run ``klake openapi``.
    """
    committed = _OPENAPI_JSON.read_text(encoding="utf-8")
    assert committed == _live_dump(), (
        "docs/openapi.json is stale — re-run `klake openapi` to regenerate."
    )
