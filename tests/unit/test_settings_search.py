"""Unit tests for SearchSettings — KLAKE_SEARCH__MODE env resolution (RETR-03, D-08).

Plan 10-04: Implementation landed in settings.py. xfail markers removed — all tests
now run as normal passing tests.

Pattern mirrors tests/unit/test_settings.py (lines 21-58): Settings(_env_file=None) +
patch.dict(os.environ) to isolate from .env files and environment state.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


class TestSearchSettingsDefaults:
    """SearchSettings loads with 'hybrid' as default mode (D-08, RETR-03)."""

    def test_search_mode_default_hybrid(self) -> None:
        """settings.search.mode must be 'hybrid' with no env override.

        Encodes: must_have truth §1 (D-08 — SearchSettings nested model, default hybrid).
        """
        from knowledge_lake.config.settings import Settings

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert hasattr(s, "search"), (
            "Settings missing 'search' attribute — Plan 10-04 adds SearchSettings nested model"
        )
        assert s.search.mode == "hybrid", (
            f"Expected default mode 'hybrid', got {s.search.mode!r}"
        )

    def test_search_mode_env_dense(self) -> None:
        """KLAKE_SEARCH__MODE=dense must resolve to settings.search.mode == 'dense'.

        Encodes: must_have truth §1 (D-08 — env override via KLAKE_SEARCH__MODE).
        """
        from knowledge_lake.config.settings import Settings

        env = {"KLAKE_SEARCH__MODE": "dense"}
        with patch.dict(os.environ, env, clear=False):
            s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert hasattr(s, "search"), (
            "Settings missing 'search' attribute — Plan 10-04 adds SearchSettings nested model"
        )
        assert s.search.mode == "dense", (
            f"Expected mode 'dense' from KLAKE_SEARCH__MODE=dense, got {s.search.mode!r}"
        )

    def test_search_mode_env_sparse(self) -> None:
        """KLAKE_SEARCH__MODE=sparse must resolve to settings.search.mode == 'sparse'.

        Additional coverage beyond the must_have — verifies all three Literal values
        work as env overrides.
        """
        from knowledge_lake.config.settings import Settings

        env = {"KLAKE_SEARCH__MODE": "sparse"}
        with patch.dict(os.environ, env, clear=False):
            s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert hasattr(s, "search"), (
            "Settings missing 'search' attribute — Plan 10-04 adds SearchSettings nested model"
        )
        assert s.search.mode == "sparse", (
            f"Expected mode 'sparse' from KLAKE_SEARCH__MODE=sparse, got {s.search.mode!r}"
        )

    def test_search_settings_class_exported(self) -> None:
        """SearchSettings class must be importable from knowledge_lake.config.settings."""
        from knowledge_lake.config.settings import SearchSettings  # noqa: F401

        ds = SearchSettings()  # type: ignore[call-arg]
        assert ds.mode == "hybrid", f"Default mode must be 'hybrid', got {ds.mode!r}"
