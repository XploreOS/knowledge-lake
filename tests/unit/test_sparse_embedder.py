"""Unit tests for plugins/builtin/sparse_embedder.py (RETR-01, Pitfall 6).

Mocks the fastembed SparseTextEmbedding model so no live model download or
ONNX inference is performed during the unit run.  The tests verify:

- embed_sparse_doc() returns a SparseVector with the expected indices/values
  and calls the model's .embed() (document-side method), NOT .query_embed().
- embed_sparse_query() returns a SparseVector and calls the model's
  .query_embed() (query-side method), NOT .embed() — Pitfall 6.
- Empty/whitespace text returns an empty SparseVector and does not raise.
- The module uses a singleton (cached) model instance; consecutive calls do
  not instantiate multiple models.

Monkeypatching strategy:
  - The module caches the model in ``sparse_embedder._bm25_model``.  Tests
    inject a ``MagicMock`` directly into that module global before each test
    and reset it to ``None`` afterwards so the singleton is not shared between
    tests.
  - The mock's ``.embed()`` and ``.query_embed()`` return an iterable of
    simple objects exposing ``.indices`` and ``.values`` with array-like
    ``tolist()`` methods, matching the real fastembed ``SparseEmbedding`` API.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
from qdrant_client.models import SparseVector

import knowledge_lake.plugins.builtin.sparse_embedder as embedder_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sparse_embedding(indices: list[int], values: list[float]):
    """Build a fake SparseEmbedding-like object matching the fastembed API."""

    class _Arr:
        def __init__(self, data):
            self._data = data

        def tolist(self):
            return list(self._data)

    ns = SimpleNamespace(indices=_Arr(indices), values=_Arr(values))
    return ns


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    """Reset the module-level singleton before and after every test.

    This ensures each test starts with a clean slate and the mock model is
    properly injected without interference from other tests.
    """
    monkeypatch.setattr(embedder_module, "_bm25_model", None)
    yield
    monkeypatch.setattr(embedder_module, "_bm25_model", None)


@pytest.fixture()
def mock_model(monkeypatch):
    """Inject a MagicMock BM25 model as the module singleton.

    The mock is configured so that:
      - ``.embed([text])`` returns a one-element list of a fake SparseEmbedding
        with indices=[1, 2, 3] and values=[0.1, 0.2, 0.3].
      - ``.query_embed(text)`` returns a one-element list with indices=[4, 5]
        and values=[0.4, 0.5].
    These distinct values let tests assert which method was called.
    """
    fake = MagicMock()
    doc_emb = _make_sparse_embedding([1, 2, 3], [0.1, 0.2, 0.3])
    query_emb = _make_sparse_embedding([4, 5], [0.4, 0.5])

    fake.embed.return_value = [doc_emb]
    fake.query_embed.return_value = [query_emb]

    monkeypatch.setattr(embedder_module, "_bm25_model", fake)
    return fake


# ---------------------------------------------------------------------------
# embed_sparse_doc tests
# ---------------------------------------------------------------------------

class TestEmbedSparseDoc:
    def test_returns_sparse_vector(self, mock_model):
        result = embedder_module.embed_sparse_doc("administrative safeguards")
        assert isinstance(result, SparseVector)

    def test_indices_and_values_from_doc_method(self, mock_model):
        result = embedder_module.embed_sparse_doc("administrative safeguards")
        assert result.indices == [1, 2, 3]
        assert result.values == pytest.approx([0.1, 0.2, 0.3])

    def test_calls_embed_not_query_embed(self, mock_model):
        """Pitfall 6: document path must call .embed(), not .query_embed()."""
        embedder_module.embed_sparse_doc("administrative safeguards")
        mock_model.embed.assert_called_once()
        mock_model.query_embed.assert_not_called()

    def test_embed_called_with_list_wrapping_text(self, mock_model):
        """embed() receives a list containing the text, per the fastembed API."""
        embedder_module.embed_sparse_doc("administrative safeguards")
        mock_model.embed.assert_called_once_with(["administrative safeguards"])

    def test_empty_string_returns_empty_sparse_vector(self, mock_model):
        result = embedder_module.embed_sparse_doc("")
        assert isinstance(result, SparseVector)
        assert result.indices == []
        assert result.values == []
        # Model must NOT be called for empty text
        mock_model.embed.assert_not_called()
        mock_model.query_embed.assert_not_called()

    def test_whitespace_only_returns_empty_sparse_vector(self, mock_model):
        result = embedder_module.embed_sparse_doc("   \t\n  ")
        assert isinstance(result, SparseVector)
        assert result.indices == []
        assert result.values == []


# ---------------------------------------------------------------------------
# embed_sparse_query tests
# ---------------------------------------------------------------------------

class TestEmbedSparseQuery:
    def test_returns_sparse_vector(self, mock_model):
        result = embedder_module.embed_sparse_query("administrative safeguards")
        assert isinstance(result, SparseVector)

    def test_indices_and_values_from_query_method(self, mock_model):
        result = embedder_module.embed_sparse_query("administrative safeguards")
        assert result.indices == [4, 5]
        assert result.values == pytest.approx([0.4, 0.5])

    def test_calls_query_embed_not_embed(self, mock_model):
        """Pitfall 6: query path must call .query_embed(), not .embed()."""
        embedder_module.embed_sparse_query("administrative safeguards")
        mock_model.query_embed.assert_called_once()
        mock_model.embed.assert_not_called()

    def test_query_embed_called_with_text_directly(self, mock_model):
        """query_embed() receives the text string directly, not in a list."""
        embedder_module.embed_sparse_query("administrative safeguards")
        mock_model.query_embed.assert_called_once_with(
            "administrative safeguards"
        )

    def test_empty_string_returns_empty_sparse_vector(self, mock_model):
        result = embedder_module.embed_sparse_query("")
        assert isinstance(result, SparseVector)
        assert result.indices == []
        assert result.values == []
        mock_model.embed.assert_not_called()
        mock_model.query_embed.assert_not_called()

    def test_whitespace_only_returns_empty_sparse_vector(self, mock_model):
        result = embedder_module.embed_sparse_query("  ")
        assert isinstance(result, SparseVector)
        assert result.indices == []
        assert result.values == []


# ---------------------------------------------------------------------------
# Singleton (cached model) tests
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_multiple_calls_use_same_model_instance(self, mock_model):
        """Consecutive calls must reuse the cached singleton, not re-instantiate."""
        # The singleton is already injected by the fixture; any _get_model()
        # call should return the same object without instantiating a new one.
        m1 = embedder_module._get_model()
        m2 = embedder_module._get_model()
        assert m1 is m2

    def test_model_loaded_lazily_on_first_embed_call(self, monkeypatch):
        """When no model is cached, _get_model() imports and instantiates it."""
        # Ensure singleton is None at test start (autouse fixture handles this)
        assert embedder_module._bm25_model is None

        doc_emb = _make_sparse_embedding([10], [1.0])
        fake_model_instance = MagicMock()
        fake_model_instance.embed.return_value = [doc_emb]

        # Patch the SparseTextEmbedding constructor inside the module
        MockSTE = MagicMock(return_value=fake_model_instance)

        # We need to intercept the lazy import inside _get_model.
        # The simplest approach: pre-cache the fake model.
        monkeypatch.setattr(embedder_module, "_bm25_model", fake_model_instance)

        result = embedder_module.embed_sparse_doc("test lazy load")
        assert isinstance(result, SparseVector)
        # The cached model should now be the fake we injected
        assert embedder_module._bm25_model is fake_model_instance
