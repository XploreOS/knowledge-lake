"""Sentence-transformers embedder (default) and LiteLLM gateway embedder (D-11, D-13).

Two EmbedderPlugin implementations:

  SentenceTransformerEmbedder ('local'):
    Default embedder. Uses the local sentence-transformers library with a
    384-dimensional model (all-MiniLM-L6-v2). Zero AWS credentials required.
    This is the spike default per D-13: `docker compose up` + demo runs entirely
    offline. Swap to 'litellm' is a pure KLAKE_EMBEDDER config change.

  LiteLLMEmbedder ('litellm'):
    Routes through the LiteLLM gateway using the 'embedding_model' task alias.
    Never uses a hardcoded provider model ID (CLAUDE.md constraint).
    The alias is mapped to a concrete model in infra/litellm/config.yaml (not in code).
    Expected output dim = 1536 (Amazon Titan Text Embeddings V2 via Bedrock is the
    dev mapping; any model behind the alias that outputs 1536-dim vectors works).

Registered as entry points:
    [project.entry-points."knowledge_lake.embedders"]
    local   = "knowledge_lake.plugins.builtin.st_embedder:SentenceTransformerEmbedder"
    litellm = "knowledge_lake.plugins.builtin.st_embedder:LiteLLMEmbedder"
"""
from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# SentenceTransformerEmbedder
# ---------------------------------------------------------------------------

#: Local model name — 384-dim MiniLM, fast and accurate enough for Phase 1 spike.
#: Larger models (bge-base, bge-large) are straightforward swap-ins with a dim change.
_LOCAL_MODEL_NAME = "all-MiniLM-L6-v2"
_LOCAL_DIM = 384


class SentenceTransformerEmbedder:
    """Local sentence-transformers embedder (zero AWS credentials, D-13).

    Loads the model on first call to embed() and caches it for the lifetime
    of the instance. Suitable for the Phase 1 spike; GPU-capable via the
    sentence-transformers device selection if available.

    Protocol attributes:
        name = 'local'
        dim  = 384
    """

    name: str = "local"
    dim: int = _LOCAL_DIM

    def __init__(self) -> None:
        self._model: object | None = None

    def _load_model(self) -> object:
        if self._model is None:
            log.info("st_embedder.load_model", model=_LOCAL_MODEL_NAME)
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
            self._model = SentenceTransformer(_LOCAL_MODEL_NAME)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts with the local sentence-transformer model.

        Args:
            texts: One or more strings to embed.

        Returns:
            List of 384-dimensional float vectors, one per input string.
        """
        model = self._load_model()
        # SentenceTransformer.encode() returns a numpy array (batch, dim)
        raw = model.encode(texts, show_progress_bar=False)  # type: ignore[union-attr]
        # Convert to plain Python list[list[float]] for Protocol compliance
        result: list[list[float]] = [row.tolist() for row in raw]
        log.debug("st_embedder.embed", count=len(texts), dim=self.dim)
        return result


# ---------------------------------------------------------------------------
# LiteLLMEmbedder
# ---------------------------------------------------------------------------

#: LiteLLM task alias for embeddings — mapped to concrete model in infra/litellm/config.yaml.
#: NEVER set this to a provider model ID (CLAUDE.md constraint).
_LITELLM_ALIAS = "embedding_model"

#: Output dimension for the LiteLLM gateway path.
#: The dev mapping (Amazon Titan Text Embeddings V2 via Bedrock) outputs 1536 dimensions.
_LITELLM_DIM = 1536


class LiteLLMEmbedder:
    """LiteLLM gateway embedder for routing through the configured LLM proxy.

    Routes all embedding calls through the LiteLLM proxy using the task alias
    'embedding_model'. The alias is resolved to a concrete provider model in
    infra/litellm/config.yaml — never in this code.

    Swap from 'local' to 'litellm':
        KLAKE_EMBEDDER=litellm  (no code change required — FOUND-08)

    The LiteLLM proxy URL is injected via the constructor (from Settings.litellm_url),
    consistent with the CLAUDE.md constraint that only the settings module reads env vars.

    Protocol attributes:
        name = 'litellm'
        dim  = 1536
    """

    name: str = "litellm"
    dim: int = _LITELLM_DIM

    def __init__(
        self,
        litellm_url: str = "http://localhost:4000",
        litellm_api_key: str = "sk-local-noauth",
    ) -> None:
        # Proxy base URL — injected by the resolver from Settings.litellm_url (CR-03)
        self._proxy_url: str = litellm_url
        # Required by the litellm SDK for any api_base call even when the proxy
        # has no LITELLM_MASTER_KEY configured — client-side requirement, not
        # proxy-side auth (Phase 4 checkpoint finding).
        self._api_key: str = litellm_api_key

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts via the LiteLLM gateway using the 'embedding_model' alias.

        Calls litellm.embedding() with model='embedding_model'. The LiteLLM proxy
        resolves this alias to the concrete backend model (e.g. Amazon Titan v2).
        No provider model ID ever appears in this code (CLAUDE.md constraint).

        Args:
            texts: One or more strings to embed.

        Returns:
            List of float vectors. Dimension matches the model behind the alias
            (1536 for the Amazon Titan Text Embeddings V2 default mapping).

        Raises:
            RuntimeError: If the LiteLLM call fails (wraps the underlying error).
        """
        import litellm  # local import to keep the gateway off the local-only path

        log.info(
            "litellm_embedder.embed",
            model=_LITELLM_ALIAS,
            count=len(texts),
            proxy_url=self._proxy_url,
        )
        try:
            response = litellm.embedding(
                # "openai/" declares the wire protocol the LiteLLM proxy speaks
                # (OpenAI-compatible), not the actual model provider — see
                # pipeline/enrich.py::_call_llm_for_enrichment for full rationale.
                model=f"openai/{_LITELLM_ALIAS}",
                input=texts,
                api_base=self._proxy_url,
                api_key=self._api_key,
            )
        except Exception as exc:
            raise RuntimeError(
                f"LiteLLMEmbedder.embed() failed calling model alias "
                f"'{_LITELLM_ALIAS}' at {self._proxy_url}: {exc}"
            ) from exc

        vectors: list[list[float]] = [item.embedding for item in response.data]
        # Validate that the model output dimension matches the configured dim (CR-09).
        # A mismatch here indicates the LiteLLM alias points at a model with a
        # different dimension than expected — fail early rather than at Qdrant upsert.
        if vectors and len(vectors[0]) != self.dim:
            actual = len(vectors[0])
            raise RuntimeError(
                f"LiteLLMEmbedder: model returned {actual}-dim vectors but "
                f"dim={self.dim} is configured. Update _LITELLM_DIM or the model alias."
            )
        log.debug("litellm_embedder.embed_complete", count=len(vectors))
        return vectors
