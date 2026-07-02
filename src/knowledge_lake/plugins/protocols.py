"""Plugin Protocol contracts for the Knowledge Lake tool-agnostic seam (FOUND-08).

Defines runtime_checkable Protocols for the three swappable plugin types:
  - ParserPlugin   — turns raw document bytes into a ParsedDoc
  - EmbedderPlugin — turns text strings into dense float vectors
  - VectorStorePlugin — manages a collection of VectorPoints and supports search

Supporting dataclasses:
  - ParsedDoc    — structured output from a parser (text + per-section metadata)
  - Section      — a single logical section within a parsed document
  - VectorPoint  — a record to upsert into the vector store (id, vector, payload)
  - Hit          — a single search result (id, score, payload)

The payload on VectorPoint / Hit carries citation fields required by D-07:
  document, section_path, page, chunk_id — so downstream consumers can
  surface exact citations without touching the raw document again.

Swapping a tool = registering a new implementation satisfying the Protocol and
changing a single settings value (KLAKE_EMBEDDER, KLAKE_PARSER, KLAKE_VECTORSTORE).
No core code edits required (FOUND-08, D-11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Shared data structures
# ---------------------------------------------------------------------------


@dataclass
class Section:
    """A logical section within a parsed document.

    Carries heading text, the section path (e.g. '§3.2 Administrative Safeguards'),
    the page number where the section begins, and the section's text content.
    Used by ParserPlugin implementations to preserve structure for citations (D-07).
    """

    heading: str
    """Section heading text (e.g. 'Administrative Safeguards')."""

    section_path: str
    """Canonical dot-notation path (e.g. '§3.2')."""

    page: int
    """Page number where this section begins (1-indexed)."""

    text: str = ""
    """Text content of the section (may be empty if not extracted)."""


@dataclass
class ParsedDoc:
    """Structured output from a ParserPlugin.

    Contains the full document text plus a list of Section objects that carry
    per-section heading, section_path, and page_ref metadata for citation (D-07).
    """

    text: str
    """Full document text (markdown or plain text)."""

    sections: list[Section] = field(default_factory=list)
    """Per-section metadata for citation construction."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Optional document-level metadata (e.g. page count, title)."""


@dataclass
class VectorPoint:
    """A point to upsert into the vector store.

    The payload MUST carry citation fields (D-07, D-14):
      document     — the artifact ID of the parsed document this chunk belongs to
      section_path — the section path string (e.g. '§3.2')
      page         — the page number (int)
      chunk_id     — the artifact ID of this chunk (matches the 'id' field)
    """

    id: str
    """Stable artifact ID (type-prefixed UUIDv7, e.g. 'chk_<uuid>')."""

    vector: list[float]
    """Dense embedding vector."""

    payload: dict[str, Any] = field(default_factory=dict)
    """Metadata payload. Must include: document, section_path, page, chunk_id."""


@dataclass
class Hit:
    """A single vector-search result returned by VectorStorePlugin.search().

    The payload carries citation fields (D-07) so callers can render
    'Document X, §Y, page Z' without an additional DB lookup.
    """

    id: str
    """ID of the matched VectorPoint."""

    score: float
    """Similarity score (higher = more similar for Cosine distance)."""

    payload: dict[str, Any] = field(default_factory=dict)
    """Payload from the matched VectorPoint (includes citation fields)."""


# ---------------------------------------------------------------------------
# Plugin Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class EmbedderPlugin(Protocol):
    """Protocol for embedding text into dense float vectors.

    Implementations must expose:
      name — a stable identifier used to register and resolve the plugin
      dim  — the output vector dimension (must match the Qdrant collection size)
      embed(texts) — batch-embed strings; returns one vector per input string

    Default built-in: SentenceTransformerEmbedder ('local', dim=384, zero AWS creds, D-13).
    Config switch:   LiteLLMEmbedder ('litellm', routes through gateway via 'embedding_model'
                     alias — never a hardcoded provider model ID, CLAUDE.md constraint).
    """

    name: str
    """Stable name used to look up this implementation via the resolver."""

    dim: int
    """Output vector dimension. Must match the Qdrant collection's vector size."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of text strings.

        Args:
            texts: One or more strings to embed.

        Returns:
            A list of float vectors, one per input string. Each vector has
            length == self.dim.
        """
        ...


@runtime_checkable
class ParserPlugin(Protocol):
    """Protocol for parsing raw document bytes into structured ParsedDoc output.

    Implementations must expose:
      can_parse(mime_type) — returns True if this parser handles the given MIME type
      parse(raw, mime_type) — converts bytes → ParsedDoc, preserving section/page metadata

    Default built-in: DoclingParser ('docling') — handles 'application/pdf' in Phase 1.
    """

    def can_parse(self, mime_type: str) -> bool:
        """Return True if this parser can handle the given MIME type.

        Args:
            mime_type: Standard MIME type string (e.g. 'application/pdf').

        Returns:
            True if the parser supports this format; False otherwise.
        """
        ...

    def parse(self, raw: bytes, mime_type: str) -> ParsedDoc:
        """Parse raw document bytes into a structured ParsedDoc.

        Args:
            raw:       Raw document bytes (e.g. PDF binary data).
            mime_type: MIME type of the document.

        Returns:
            ParsedDoc with full text and per-section metadata (headings,
            section paths, page references) for downstream citation (D-07).
        """
        ...


@runtime_checkable
class VectorStorePlugin(Protocol):
    """Protocol for managing a vector collection and performing similarity search.

    Implementations must expose:
      ensure_collection(name, dim, distance) — idempotently create/verify a collection
      upsert(collection, points)             — batch-upsert VectorPoint records
      search(collection, query, top_k)       — ANN search returning Hits with citation payload

    Default built-in: QdrantVectorStore ('qdrant', cosine similarity, citation-payload upsert).
    """

    def ensure_collection(
        self, name: str, dim: int, distance: str = "Cosine"
    ) -> None:
        """Create a collection if it does not exist.

        Args:
            name:     Collection name.
            dim:      Vector dimension (must match the embedder's dim).
            distance: Distance metric to use (default: 'Cosine').
        """
        ...

    def upsert(self, collection: str, points: list[VectorPoint]) -> None:
        """Upsert a batch of VectorPoints into the collection.

        Args:
            collection: Target collection name.
            points:     List of VectorPoint records to upsert.
        """
        ...

    def search(
        self, collection: str, query: list[float], top_k: int
    ) -> list[Hit]:
        """Perform approximate nearest-neighbour search.

        Args:
            collection: Collection to search.
            query:      Query vector (must have the same dimension as the collection).
            top_k:      Maximum number of results to return.

        Returns:
            List of Hit objects ordered by score descending.
        """
        ...
