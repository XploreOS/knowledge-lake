"""
Shared test fixtures and configuration for the Knowledge Lake test suite.

Wave 0: This is the foundational fixture layer that all later test plans write against.
"""

from __future__ import annotations

import os
import pytest
from typing import Generator
from unittest.mock import patch


# ── Environment isolation ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_env() -> Generator[None, None, None]:
    """Autouse fixture: save and restore KLAKE_* env vars around each test.

    Prevents test pollution from developer's actual .env or shell env.
    After the test, removes any NEW KLAKE_* keys added during the test
    and restores the original keys.
    """
    # Snapshot all KLAKE_* vars present before the test
    before = {k: v for k, v in os.environ.items() if k.startswith("KLAKE_")}
    # Remove them so each test starts from a clean state
    for k in before:
        del os.environ[k]
    try:
        yield
    finally:
        # Remove any KLAKE_* vars that were added during the test
        for k in list(os.environ.keys()):
            if k.startswith("KLAKE_"):
                del os.environ[k]
        # Restore the original vars
        os.environ.update(before)


# ── Settings fixture ─────────────────────────────────────────────────────────

@pytest.fixture
def settings():
    """Return a Settings instance with known test overrides.

    Uses env-override approach so pydantic-settings picks them up; cleans up after.
    """
    from knowledge_lake.config.settings import Settings

    test_env = {
        "KLAKE_DATABASE_URL": "postgresql+psycopg://klake:klake@localhost:5432/klake_test",
        "KLAKE_QDRANT_URL": "http://localhost:6333",
        "KLAKE_LITELLM_URL": "http://localhost:4000",
        "KLAKE_STORAGE__ENDPOINT_URL": "http://localhost:9000",
        "KLAKE_STORAGE__BUCKET": "klake-test",
        "KLAKE_STORAGE__ACCESS_KEY_ID": "testkey",
        "KLAKE_STORAGE__SECRET_ACCESS_KEY": "testsecret",
        "KLAKE_EMBEDDER": "local",
        "KLAKE_PARSER": "docling",
        "KLAKE_VECTORSTORE": "qdrant",
    }
    with patch.dict(os.environ, test_env, clear=False):
        # Force fresh Settings from the patched env (no cached instance)
        s = Settings(_env_file=None)  # type: ignore[call-arg]
    return s
