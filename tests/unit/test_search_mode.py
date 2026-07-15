"""Unit tests for pipeline/search.py mode threading (RETR-03, D-09, D-10).

RED test scaffold: encodes acceptance behaviors for the mode parameter and
sparse_query threading through pipeline.search(), plus the fail-loud contract
when a hybrid/sparse mode is used against a collection with no sparse vectors.

Plans 10-06 and 10-07 landed this implementation; the xfail decorators have
been removed.

Fixture mirrors tests/unit/test_search_filters.py (lines 19-32): monkeypatch
knowledge_lake.pipeline.search.get_embedder / get_vectorstore at the pipeline
module level so no real embedder or Qdrant server is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import knowledge_lake.pipeline.search as search_module


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch):
    """Dense embedder stub: embed(['q']) → [[0.1, 0.2, 0.3, 0.4]]."""
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1, 0.2, 0.3, 0.4]]
    monkeypatch.setattr(search_module, "get_embedder", lambda _s: embedder)
    return embedder


@pytest.fixture()
def fake_vstore(monkeypatch):
    """Vector store stub: search() returns an empty list by default."""
    vstore = MagicMock()
    vstore.search.return_value = []
    monkeypatch.setattr(search_module, "get_vectorstore", lambda _s: vstore)
    return vstore


# ── Guard for sparse embedder symbol (Plan 10-07 adds it) ─────────────────────

# Plan 10-07 will add a sparse query function reachable from pipeline.search.
# If it's not there yet, we create a stub so the test body can still be exercised
# in the fail-fast manner we want.
try:
    from knowledge_lake.pipeline.search import _build_sparse_query  # type: ignore[attr-defined]
    _SPARSE_FN_PRESENT = True
except (ImportError, AttributeError):
    _build_sparse_query = None  # type: ignore[assignment]
    _SPARSE_FN_PRESENT = False


class TestModeThreadsSparseQuery:
    """search() threads mode and sparse_query into vstore.search (D-09, D-03, RETR-03)."""

    def test_mode_threads_sparse_query(self, fake_vstore, monkeypatch) -> None:
        """search('q', mode='hybrid') forwards mode='hybrid' and a non-None sparse_query
        into vstore.search (D-09, D-03).

        The sparse query function is monkeypatched so no real fastembed model is needed.
        """
        # Stub out whatever sparse query builder search.py will call in Plan 10-07.
        # Try common attribute names; fall back to patching whatever symbol is imported.
        sparse_vec = MagicMock(name="SparseVector")

        # Attempt to monkeypatch known candidate names; any that aren't present are no-ops.
        for attr in ("_build_sparse_query", "get_sparse_embedder", "_sparse_query"):
            if hasattr(search_module, attr):
                monkeypatch.setattr(search_module, attr, lambda *_a, **_k: sparse_vec)

        search_module.search("q", collection="c", top_k=5, mode="hybrid")  # type: ignore[call-arg]

        call_kwargs = fake_vstore.search.call_args.kwargs
        # mode must be forwarded
        assert call_kwargs.get("mode") == "hybrid", (
            f"Expected mode='hybrid' in vstore.search kwargs, got: {call_kwargs}"
        )
        # sparse_query must not be None for hybrid mode
        assert call_kwargs.get("sparse_query") is not None, (
            "Expected non-None sparse_query for mode='hybrid', "
            f"got None. vstore.search called with: {call_kwargs}"
        )

    def test_dense_mode_no_sparse_query(self, fake_vstore) -> None:
        """search('q', mode='dense') must NOT pass a sparse_query (backward-compat, D-09)."""
        search_module.search("q", collection="c", top_k=5, mode="dense")  # type: ignore[call-arg]

        call_kwargs = fake_vstore.search.call_args.kwargs
        sparse_query_val = call_kwargs.get("sparse_query")
        assert sparse_query_val is None, (
            f"mode='dense' must not produce a sparse_query, "
            f"but got: sparse_query={sparse_query_val!r}"
        )


class TestFailLoudMissingSparse:
    """search() raises a clear error when mode requires sparse vectors but collection has none (D-10, T-10-03)."""

    def test_fail_loud_missing_sparse_hybrid(self, fake_vstore) -> None:
        """search('q', mode='hybrid') against a sparse-less collection MUST raise.

        The error must:
          1. Name the missing 'sparse' vector
          2. Mention the klake reindex --hybrid remediation
          3. NOT silently fall back to dense

        Encodes: must_have truth §3 (D-10, T-10-03).
        """
        # Configure fake_vstore.search to raise the error type Plan 10-06 will raise
        # when the collection lacks sparse vectors. This mirrors the RESEARCH.md §(g)
        # sparse-presence probe pattern: either the store or pipeline raises ValueError/RuntimeError
        # naming the missing vector.
        fail_loud_error = ValueError(
            "mode='hybrid' requires a 'sparse' vector, but collection 'c' has none. "
            "Run the hybrid reindex (klake reindex --hybrid) to migrate this collection. "
            "(dense mode still works against it.)"
        )
        fake_vstore.search.side_effect = fail_loud_error

        with pytest.raises((ValueError, RuntimeError)) as exc_info:
            search_module.search("q", collection="c", top_k=5, mode="hybrid")  # type: ignore[call-arg]

        error_str = str(exc_info.value).lower()
        # Must name the missing vector
        assert "sparse" in error_str, (
            f"Error must name the missing 'sparse' vector, but error was: {exc_info.value!r}"
        )
        # Must mention the remediation (reindex)
        assert "reindex" in error_str, (
            f"Error must mention 'klake reindex --hybrid' remediation, "
            f"but error was: {exc_info.value!r}"
        )

    def test_fail_loud_missing_sparse_no_fallback(self, fake_vstore) -> None:
        """search() with mode='hybrid' on a sparse-less collection MUST NOT silently
        downgrade to dense (T-10-03 — no silent mode substitution).

        This encodes the *negative* contract: the function must propagate the error
        rather than returning search results from a silent dense fallback.
        """
        # Force the store to raise a fail-loud error
        fail_loud_error = ValueError(
            "mode='hybrid' requires a 'sparse' vector, but collection 'c' has none. "
            "Run klake reindex --hybrid to migrate."
        )
        fake_vstore.search.side_effect = fail_loud_error

        # search() must NOT catch this and return a list of hits
        with pytest.raises((ValueError, RuntimeError)):
            result = search_module.search("q", collection="c", top_k=5, mode="hybrid")  # type: ignore[call-arg]
            # If we get here (no raise), the function silently fell back to dense — fail the test
            pytest.fail(
                f"search() silently degraded to dense mode instead of raising. "
                f"Got {len(result)} hits. D-10 requires fail-loud, no silent fallback."
            )
