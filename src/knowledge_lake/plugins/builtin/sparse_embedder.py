"""BM25 sparse encoder wrapper for Knowledge Lake (RETR-01, D-01, D-02, D-03).

Wraps fastembed's ``SparseTextEmbedding`` with the ``Qdrant/bm25`` model to
produce ``SparseVector`` objects for both index time (document side) and query
time (query side) — Pitfall 6.

Lives inside the ``plugins/builtin/`` seam per the D-01 plugin ethos: sparse
construction is fully contained here, consumed by:
  - ``index.py``  → ``embed_sparse_doc``  (upsert path)
  - ``search.py`` → ``embed_sparse_query`` (search path)

The ONNX model is loaded once via a module-level lazy singleton so the model
stays warm across calls without incurring repeated start-up cost.

Model reference:
    BM25 model: ``Qdrant/bm25`` (HuggingFace, Qdrant org)
    fastembed: ``>=0.8,<0.9`` (CPU ONNX only — no torch/GPU, D-02)
    IDF correction: applied server-side via ``Modifier.IDF`` at collection
    create time (D-13); this module only emits raw term-frequency vectors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from fastembed import SparseTextEmbedding as _SparseTextEmbeddingType
    from qdrant_client.models import SparseVector

log = structlog.get_logger(__name__)

_MODEL_NAME = "Qdrant/bm25"

# Module-level lazy singleton — None until first call.
_bm25_model: _SparseTextEmbeddingType | None = None


def _get_model() -> _SparseTextEmbeddingType:
    """Return the cached BM25 model, loading it on first call.

    Uses a module-level singleton so the ONNX model initialises once per
    process and stays warm across ``embed_sparse_doc`` / ``embed_sparse_query``
    invocations.  The deferred import avoids paying the fastembed import cost
    when the sparse path is unused (e.g. dense-only mode).
    """
    global _bm25_model  # noqa: PLW0603
    if _bm25_model is None:
        from fastembed import SparseTextEmbedding  # lazy import (D-01)

        log.debug("sparse_embedder.load_model", model=_MODEL_NAME)
        _bm25_model = SparseTextEmbedding(model_name=_MODEL_NAME)
    return _bm25_model


def embed_sparse_doc(text: str) -> SparseVector:
    """Produce a BM25 sparse vector for a *document* (index-time, D-03).

    Uses the document-side embedding method (``SparseTextEmbedding.embed``),
    which is distinct from the query-side method (Pitfall 6).

    Returns an empty ``SparseVector`` when *text* is empty or whitespace so
    callers do not need to guard against empty strings before calling.

    Args:
        text: Plain text of the chunk / document to embed.

    Returns:
        ``qdrant_client.models.SparseVector`` with non-negative ``indices``
        and ``values`` appropriate for server-side IDF-weighted BM25.
    """
    from qdrant_client.models import SparseVector

    if not text or not text.strip():
        return SparseVector(indices=[], values=[])

    model = _get_model()
    # .embed() is the document-side method; returns an iterable of
    # SparseEmbedding objects each with .indices and .values ndarrays.
    embeddings = list(model.embed([text]))
    if not embeddings:
        return SparseVector(indices=[], values=[])

    e = embeddings[0]
    return SparseVector(indices=e.indices.tolist(), values=e.values.tolist())


def embed_sparse_query(text: str) -> SparseVector:
    """Produce a BM25 sparse vector for a *query* (search-time, D-03).

    Uses the query-side embedding method (``SparseTextEmbedding.query_embed``),
    which is distinct from the document-side method — Pitfall 6.  Mixing the
    two yields incorrect BM25 weights.

    Returns an empty ``SparseVector`` when *text* is empty or whitespace.

    Args:
        text: Query string to embed.

    Returns:
        ``qdrant_client.models.SparseVector`` suitable for passing as the
        ``query`` argument in a Qdrant sparse or hybrid search.
    """
    from qdrant_client.models import SparseVector

    if not text or not text.strip():
        return SparseVector(indices=[], values=[])

    model = _get_model()
    # .query_embed() is the query-side method (not .embed) — Pitfall 6.
    # Returns an iterable of SparseEmbedding objects.
    embeddings = list(model.query_embed(text))
    if not embeddings:
        return SparseVector(indices=[], values=[])

    e = embeddings[0]
    return SparseVector(indices=e.indices.tolist(), values=e.values.tolist())
