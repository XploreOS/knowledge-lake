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

from collections.abc import Callable
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

    is_table: bool = False
    """True when this section is a table that must be chunked atomically (CHUNK-03).

    Tables are never split even if they exceed max_tokens — an oversized table emits
    as a single chunk with ``oversized=True`` in its metadata.  Default False so all
    existing code constructing Section without this field continues to work.
    """


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

    sparse: Any | None = None
    """Optional BM25 sparse vector for named collections (RETR-01, D-09).

    Carries the Qdrant SparseVector (indices + values) produced by the fastembed
    BM25 encoder. Defaults to None so all existing VectorPoint constructions
    remain valid without modification — additive-default convention (mirrors
    CrawlPageResult.http_status_code). Points without sparse vectors work in
    dense-only mode; hybrid/sparse modes require the field to be populated
    (populated at index time after the named-vector reindex, D-05).
    """


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
      ensure_collection(name, dim, distance)          — idempotently create/verify a collection
      ensure_aliased_collection(alias, dim, distance) — idempotently create the first versioned
                                                          collection behind an alias (D-06, INDEX-02)
      reindex(alias, dim, upsert_fn, distance)        — zero-downtime reindex via atomic alias swap
      copy_all_points(source, dest, batch_size)       — scroll+upsert all points between collections
      get_collection_dim(alias)                       — read back a collection's configured vector size
      upsert(collection, points)                      — batch-upsert VectorPoint records
      search(collection, query, top_k, query_filter)  — ANN search returning Hits with citation payload

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

    def ensure_aliased_collection(
        self, alias: str, dim: int, distance: str = "Cosine"
    ) -> tuple[str, bool]:
        """Idempotently create the first versioned collection behind ``alias``.

        Only creates a physical collection (named ``f"{alias}_v1"``) and points
        the alias at it the FIRST time ``alias`` is used — every subsequent call
        with an existing alias is a no-op (D-06). Callers keep passing ``alias``
        to embed()/index()/search() unchanged; only the resolution layer
        underneath changes when a reindex happens.

        Args:
            alias:    Stable collection name applications use (never a physical
                      collection name directly).
            dim:      Vector dimension (must match the embedder's dim).
            distance: Distance metric to use (default: 'Cosine').

        Returns:
            (physical_collection_name, created) — ``created`` is True only the
            first time this alias is bootstrapped.
        """
        ...

    def reindex(
        self,
        alias: str,
        dim: int,
        upsert_fn: Any,
        distance: str = "Cosine",
    ) -> dict:
        """Zero-downtime reindex: build a new physical collection, then atomically
        repoint ``alias`` at it (D-06, INDEX-02).

        Creates the next versioned collection after the highest existing
        ``f"{alias}_vN"`` suffix, calls ``upsert_fn(new_physical_name)`` to
        populate it, then issues a single ``update_collection_aliases()`` call
        containing both the delete-old-alias and create-new-alias operations so
        the alias never resolves to nothing mid-swap. The prior physical
        collection is retained — never auto-dropped; the caller decides if/when
        to drop it.

        Args:
            alias:     Stable collection name applications use.
            dim:       Vector dimension for the new physical collection.
            upsert_fn: Callable invoked with the new physical collection name;
                       responsible for populating it (e.g. copy_all_points or
                       a full re-embed).
            distance:  Distance metric to use (default: 'Cosine').

        Returns:
            {"new_physical": ..., "old_physical": ...} (``old_physical`` is
            None on the very first reindex of a never-aliased collection).
        """
        ...

    def copy_all_points(self, source: str, dest: str, batch_size: int = 256) -> int:
        """Scroll all points (vectors + payload) out of ``source`` and upsert
        them into ``dest``. The default ``upsert_fn`` ``reindex()`` uses when no
        re-embedding is needed.

        Args:
            source:     Source collection name.
            dest:       Destination collection name.
            batch_size: Number of points to scroll/upsert per batch.

        Returns:
            Total count of points copied (0 for an empty source collection).
        """
        ...

    def get_collection_dim(self, alias: str) -> int:
        """Return the configured vector dimension for a collection or alias.

        Args:
            alias: Collection name or alias to inspect.

        Returns:
            The vector dimension (size) configured for this collection.
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
        self,
        collection: str,
        query: list[float],
        top_k: int,
        query_filter: Any | None = None,
        *,
        mode: str = "dense",
        sparse_query: Any | None = None,
        offset: int = 0,
    ) -> list[Hit]:
        """Perform approximate nearest-neighbour search.

        Args:
            collection:    Collection to search.
            query:         Dense query vector (must have the same dimension as the
                           collection). Used for 'dense' and 'hybrid' modes.
            top_k:         Maximum number of results to return.
            query_filter:  Optional backend-specific filter object (Qdrant's
                           ``Filter`` for the built-in implementation) — an
                           acknowledged simplification for this MVP phase since
                           there is currently only one VectorStorePlugin
                           implementation.
            mode:          Retrieval mode — 'dense' | 'sparse' | 'hybrid'.
                           Keyword-only. Defaults to 'dense' so existing callers
                           are unaffected until they opt in (additive-default
                           back-compat convention, D-09). The concrete
                           implementation (Plan 10-06) enforces fail-loud when
                           the requested mode's vectors are absent (D-10).
            sparse_query:  Query-side SparseVector (indices + values) for
                           'sparse' and 'hybrid' modes. Keyword-only. Defaults
                           to None — existing callers are unaffected. Must be
                           provided for sparse/hybrid when the concrete
                           implementation requires it.
            offset:        Number of results to skip for pagination. Keyword-only.
                           The concrete implementation uses this for prefetch-limit
                           headroom: prefetch limit == top_k + offset (D-12).
                           Defaults to 0.

        Returns:
            List of Hit objects ordered by score descending.
        """
        ...

    def assert_server_supports_hybrid(self) -> None:
        """Assert the vector store server supports hybrid/sparse retrieval.

        Must raise RuntimeError (or a subclass) when the server version is
        too old to support sparse/hybrid search.  Implementations may memoize
        the check so the round-trip is at most once per process.
        """
        ...

    def reembed_all_points(
        self,
        source: str,
        dest: str,
        sparse_doc_fn: Callable[[str], Any],
        batch_size: int = 256,
    ) -> tuple[int, int]:
        """Re-embed all points from ``source`` into ``dest`` with added sparse vectors.

        Scrolls every point from ``source``, reuses the existing dense vector,
        synthesizes a sparse vector via ``sparse_doc_fn(text)``, and upserts
        named {dense+sparse} PointStructs into ``dest``.

        Args:
            source:         Physical collection name to scroll from.
            dest:           Physical collection name to upsert into.
            sparse_doc_fn:  Callable(str) → SparseVector — encodes payload text.
            batch_size:     Number of points to scroll/upsert per batch.

        Returns:
            Tuple of (total_upserted, total_skipped). Points whose dense vector
            is absent are skipped with a warning (WR-04); the caller (reindex)
            uses total_skipped to adjust the D-06 count-parity gate.
        """
        ...


# ---------------------------------------------------------------------------
# Discovery data structures (INGEST-07)
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryResult:
    """A single discovery result returned by a DiscoveryPlugin.

    Carries only the minimal fields needed to register a candidate source:
    the URL and a human-readable title (D-09: URL + title only).
    """

    url: str
    """The discovered URL."""

    title: str
    """Human-readable title of the discovered resource (empty string if absent)."""


# ---------------------------------------------------------------------------
# Discovery Plugin Protocol (INGEST-07, D-10)
# ---------------------------------------------------------------------------


@runtime_checkable
class DiscoveryPlugin(Protocol):
    """Protocol for source discovery engines that find candidate URLs.

    Implementations must expose:
      name   — stable identifier for resolver lookup
      search — run a query and return a list of DiscoveryResult items

    Default built-in: SearXNGDiscovery ('searxng') — self-hosted meta-search,
    JSON API, no API keys needed.

    The discovery swap key (settings.discovery) selects the active implementation
    via the 'knowledge_lake.discovery' entry-point group. No os.environ reads
    in builtins (CR-03); searxng_url injected from Settings.
    """

    name: str
    """Stable name used to look up this implementation via the resolver."""

    def search(self, query: str, limit: int) -> list[DiscoveryResult]:
        """Run a discovery query and return candidate results.

        Args:
            query: Natural-language search query.
            limit: Maximum number of results to return.

        Returns:
            List of DiscoveryResult items (url + title), capped at limit.
        """
        ...


# ---------------------------------------------------------------------------
# Crawler data structures (INGEST-04, INGEST-09)
# ---------------------------------------------------------------------------


@dataclass
class CrawlJob:
    """Represents an in-progress or completed crawl job.

    Created by CrawlerPlugin.start_crawl() and tracked in the jobs table.
    The status field reflects the crawler adapter's view of the job lifecycle.
    """

    job_id: str
    """Registry job ID (prefixed UUIDv7, e.g. 'job_<uuid>')."""

    source_url: str
    """The seed URL that initiated this crawl."""

    crawler: str
    """Name of the crawler adapter that owns this job (e.g. 'crawl4ai')."""

    status: str = "pending"
    """Job status: 'pending', 'running', 'complete', 'failed'."""

    config: dict[str, Any] = field(default_factory=dict)
    """Crawler-specific configuration passed at job creation."""


@dataclass
class CrawlPageResult:
    """A single page result from a completed crawl.

    Returned by CrawlerPlugin.get_results() for each URL fetched during the
    crawl.  The html/markdown fields may be None for failed or blocked pages.
    """

    url: str
    """The URL that was fetched."""

    status: str
    """Page-level status: 'complete', 'failed', 'robots_blocked'."""

    html: bytes | None = None
    """Raw HTML bytes (None if fetch failed or was blocked)."""

    markdown: str | None = None
    """Cleaned markdown output (None if not produced by the crawler)."""

    error: str | None = None
    """Error message if status is 'failed' (None on success)."""

    fetched_at: str | None = None
    """ISO-8601 timestamp of when the page was fetched (None if not fetched)."""

    http_status_code: int | None = None
    """HTTP status code from the network response (None if not available).

    Set by adapters that have access to the raw HTTP status (e.g. crawl4ai).
    Used by the crawl orchestrator to detect 429/403 for adaptive backoff
    (CRAWL-03, Pitfall 1).  Defaults to None so all existing CrawlPageResult
    constructions remain valid without modification.
    """


# ---------------------------------------------------------------------------
# Crawler Plugin Protocol (INGEST-04, D-02)
# ---------------------------------------------------------------------------


@runtime_checkable
class CrawlerPlugin(Protocol):
    """Protocol for web crawlers that fetch pages from a seed URL.

    Implementations must expose a multi-method interface supporting long-running
    crawls (D-02):
      name        — stable identifier for resolver lookup
      start_crawl — initiate a crawl job for a given URL
      poll_status — check the current status of a running job
      get_results — retrieve page results once a job completes

    Default built-in: Crawl4AIAdapter ('crawl4ai') — async-first, JS-rendered,
    LLM-ready markdown output.
    Config switch:    ScrapyAdapter ('scrapy') — high-volume structured crawling.

    The crawler swap key (settings.crawler) selects the active implementation
    via the 'knowledge_lake.crawlers' entry-point group. No os.environ reads
    in builtins (CR-03); service URLs/config injected from Settings.
    """

    name: str
    """Stable name used to look up this implementation via the resolver."""

    def start_crawl(self, source_url: str, config: dict[str, Any]) -> CrawlJob:
        """Initiate a crawl job for the given seed URL.

        Args:
            source_url: The URL to start crawling from.
            config:     Crawler-specific configuration (max_pages, max_depth, etc.).

        Returns:
            A CrawlJob with a unique job_id and initial status 'pending'.
        """
        ...

    def poll_status(self, job_id: str) -> str:
        """Check the current status of a crawl job.

        Args:
            job_id: The job ID returned by start_crawl().

        Returns:
            Current status string: 'pending', 'running', 'complete', or 'failed'.
        """
        ...

    def get_results(self, job_id: str) -> list[CrawlPageResult]:
        """Retrieve the page results of a completed crawl job.

        Args:
            job_id: The job ID of a completed crawl.

        Returns:
            List of CrawlPageResult objects, one per URL fetched during the crawl.

        Raises:
            RuntimeError: If the job is not yet complete.
        """
        ...


# ---------------------------------------------------------------------------
# Tree index data structures (TREE-01..05, D-01, D-02)
# ---------------------------------------------------------------------------


@dataclass
class TreeNode:
    """Tree index node per D-02.

    level and page_end are DERIVED by the builder — Section has no level or
    page_end fields (Finding 1 in 13-RESEARCH.md). node_id is derived from
    section_path (stable — never a uuid/clock/randomness, Pitfall 3).
    children is a list of child TreeNode objects (nested sections).
    """

    node_id: str
    """Stable node ID derived from section_path (e.g. 'node_1.1')."""

    title: str
    """Section heading text."""

    summary: str
    """LLM-generated or heuristic summary of the section (empty in deterministic mode)."""

    page_start: int
    """Page number where this section begins (from Section.page, 1-indexed)."""

    page_end: int
    """Page number where this section ends (DERIVED by builder — Section has no page_end)."""

    level: int
    """Nesting level (DERIVED by builder from section_path depth — Section has no level)."""

    section_path: str
    """Canonical dot-notation section path (e.g. '§3.2')."""

    children: list[TreeNode] = field(default_factory=list)
    """Child TreeNode objects (nested subsections)."""


@dataclass
class TreeIndex:
    """Tree index artifact wrapper per D-02.

    mode is 'deterministic' or 'llm'. schema_version anchors TREE-06 migration
    (deferred to v2.6+). content_hash enables the dedup no-op check (D-06).
    """

    parsed_artifact_id: str
    """ID of the parsed_document artifact this tree was built from (D-07)."""

    source_id: str
    """ID of the source this tree index belongs to."""

    roots: list[TreeNode] = field(default_factory=list)
    """Top-level TreeNode objects (level-1 sections)."""

    mode: str = "deterministic"
    """Build mode: 'deterministic' (heuristic) or 'llm' (LLM-assisted summaries)."""

    schema_version: str = "1"
    """Schema version for forward-compatibility (TREE-06 migration deferred to v2.6+)."""

    content_hash: str = ""
    """SHA-256 of parsed content + mode + schema_version for dedup no-op (D-06)."""


# ---------------------------------------------------------------------------
# Indexer Plugin Protocol (TREE-05, D-05)
# ---------------------------------------------------------------------------


@runtime_checkable
class IndexerPlugin(Protocol):
    """Swap-capable tree indexer plugin (D-05, FOUND-08).

    Swap via settings.indexer entry-point group 'knowledge_lake.indexers'.

    Implementations must expose:
      name        — stable identifier used to register and resolve the plugin
      build_index — build a TreeIndex from a ParsedDoc with the given mode

    Default built-in: PageIndexIndexer ('pageindex') — deterministic Section-to-tree
    nesting with optional LLM-assisted node summaries.

    The indexer swap key (settings.indexer) selects the active implementation
    via the 'knowledge_lake.indexers' entry-point group. No os.environ reads
    in builtins (CR-03); service URLs/config injected from Settings.
    """

    name: str
    """Stable name used to look up this implementation via the resolver."""

    def build_index(
        self,
        parsed_doc: ParsedDoc,
        *,
        mode: str,
        metadata: dict[str, Any],
    ) -> TreeIndex:
        """Build a TreeIndex from a ParsedDoc.

        Args:
            parsed_doc: Structured parsed document output from a ParserPlugin.
            mode:       Build mode — 'deterministic' (heuristic nesting) or
                        'llm' (LLM-assisted per-node summaries).
            metadata:   Document-level metadata dict (source_id, artifact_id, etc.).

        Returns:
            TreeIndex with roots populated; content_hash and schema_version set.
        """
        ...
