"""Pydantic request/response schemas for the Knowledge Lake API.

Defines the typed wire format for:
  - SearchParams   — query parameters for GET /search (V5 input validation)
  - SearchHit      — a single search result with score + citation
  - LineageNode    — a single artifact node with all six FOUND-06 fields
  - LineageGraph   — the full ordered ancestry chain returned by GET /lineage/{id}

Security (T-01-14, ASVS V5):
    - top_k is bounded [1, 100] — rejects zero/negative/oversized values
    - artifact_id is validated as a non-empty string (further format enforcement
      is handled by the lineage resolver which raises LookupError on unknown IDs)

D-02 compliance:
    SearchHit and LineageNode mirror the output of pipeline.search() and
    lineage.resolve_ancestry() exactly — the API is a thin JSON wrapper over
    those same functions, not a re-implementation.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Request schemas ────────────────────────────────────────────────────────────


class SearchParams(BaseModel):
    """Query parameters for GET /search.

    Pydantic validates these before the handler runs, satisfying ASVS V5
    (input validation at the API boundary).
    """

    q: str = Field(
        ...,
        description="Natural-language search query.",
        min_length=0,  # empty string is valid — handler returns []
    )
    top_k: int = Field(
        default=5,
        description="Maximum number of results to return.",
        ge=1,    # must be >= 1 (T-01-14: reject zero/negative)
        le=100,  # upper bound to prevent DoS
    )
    collection: str = Field(
        default="klake_chunks",
        description="Qdrant collection to search.",
    )


# ── Response schemas ───────────────────────────────────────────────────────────


class SearchHit(BaseModel):
    """A single search result from GET /search.

    Carries the score and all citation fields needed to surface the exact
    source passage without a follow-up registry lookup.

    Fields mirror Hit from plugins/protocols.py plus citation fields extracted
    from the payload — D-02: same pipeline.search() output, structured by pydantic.
    """

    id: str = Field(description="Qdrant point ID (bare UUID without type prefix).")
    score: float = Field(description="Cosine similarity score in [0, 1].")
    document: str = Field(description="Parsed-document artifact ID (registry ID).")
    section_path: str = Field(description="Section path (e.g. '§2 Administrative Safeguards').")
    page: int = Field(description="Page number where this chunk appears (1-indexed).")
    chunk_id: str = Field(description="Chunk artifact ID (registry ID, prefixed with 'chk_').")
    text: str = Field(default="", description="Chunk text snippet for display.")
    domain: Optional[str] = Field(
        default=None, description="Domain classification from the source (e.g. 'healthcare')."
    )
    document_type: Optional[str] = Field(
        default=None, description="Enrichment-derived document type (e.g. 'regulation', 'guidance')."
    )
    keywords: list[str] = Field(
        default_factory=list, description="Enrichment-derived keywords for this document."
    )
    quality_score: Optional[float] = Field(
        default=None, description="LLM-judged quality score in [0, 1] from enrichment."
    )


class LineageNode(BaseModel):
    """A single artifact node in the lineage chain (FOUND-06, FOUND-07).

    Carries all six FOUND-06 mandatory fields plus optional citation fields
    available on chunk/parsed-document nodes.
    """

    # Six FOUND-06 fields — required on every node
    id: str = Field(description="Artifact ID (type-prefixed UUIDv7).")
    artifact_type: str = Field(description="Node type: raw_document | parsed_document | chunk.")
    content_hash: str = Field(description="SHA-256 hash of the artifact bytes.")
    created_at: str = Field(description="ISO-8601 creation timestamp.")
    pipeline_version: str = Field(description="Pipeline version that created this artifact (pkg+git).")
    storage_uri: Optional[str] = Field(
        default=None,
        description="S3 URI where the artifact bytes are stored.",
    )

    # Additional lineage / provenance fields
    source_id: Optional[str] = Field(default=None, description="Source registry ID (src_...).")
    parent_artifact_id: Optional[str] = Field(
        default=None,
        description="Parent artifact ID (None for root raw_document).",
    )
    depth: int = Field(default=0, description="Depth from the queried artifact (0 = the artifact itself).")

    # Citation fields (available on chunk nodes)
    section_path: Optional[str] = Field(default=None, description="Section path (chunk nodes only).")
    page: Optional[int] = Field(default=None, description="Page number (chunk nodes only).")
    mime_type: Optional[str] = Field(default=None, description="MIME type of the artifact.")


class LineageGraph(BaseModel):
    """The full lineage chain returned by GET /lineage/{artifact_id}.

    ``nodes`` is ordered leaf-first (depth 0 = the queried artifact,
    deepest = the root raw_document).
    """

    artifact_id: str = Field(description="The queried artifact ID.")
    nodes: list[LineageNode] = Field(description="Ordered ancestry nodes (leaf → root).")


# ── Source registration schemas (02-01) ──────────────────────────────────────


class SourceCreate(BaseModel):
    """Request body for POST /sources — register a new source.

    Pydantic validates these at the API boundary (ASVS V5, T-02-04).
    """

    url: str = Field(
        ...,
        description="https:// URL of the source to register.",
        min_length=8,
    )
    name: Optional[str] = Field(
        default=None,
        description="Human-readable source name (defaults to URL hostname).",
    )
    domain: Optional[str] = Field(
        default=None,
        description="Domain classification (e.g. 'healthcare', 'legal').",
        max_length=64,
    )
    license_type: str = Field(
        default="unknown",
        description="SPDX license identifier or 'unknown'.",
        max_length=64,
    )


class SourceOut(BaseModel):
    """Response body for POST /sources — registered source details."""

    source_id: str = Field(description="Source registry ID (src_...).")
    name: str = Field(description="Human-readable source name.")
    url: str = Field(description="Original URL as provided.")
    normalized_url: Optional[str] = Field(
        default=None,
        description="D-06 normalized URL used for dedup.",
    )
    domain: Optional[str] = Field(
        default=None,
        description="Domain classification.",
    )
    is_new: bool = Field(description="True if newly created, False if dedup hit.")


class UploadOut(BaseModel):
    """Response body for POST /uploads — uploaded artifact details."""

    source_id: str = Field(description="Source registry ID (src_...).")
    artifact_id: str = Field(description="Raw artifact ID (doc_...).")
    storage_uri: Optional[str] = Field(
        default=None,
        description="S3 URI of the stored content.",
    )
    content_hash: str = Field(description="SHA-256 hash of the uploaded content.")


# ── Discovery schemas (02-06) ────────────────────────────────────────────────


# ── Crawl job schemas (02-03) ──────────────────────────────────────────────


class CrawlJobCreate(BaseModel):
    """Request body for POST /crawl-jobs — start a crawl.

    Pydantic validates at the API boundary (ASVS V5, T-02-13).
    """

    source_url: str = Field(
        ...,
        description="https:// seed URL to crawl.",
        min_length=8,
    )
    crawler: Optional[str] = Field(
        default=None,
        description="Override crawler adapter name (must be a registered crawler).",
        max_length=64,
    )
    max_pages: Optional[int] = Field(
        default=None,
        description="Maximum number of pages to crawl.",
        ge=1,
        le=10000,
    )


class CrawlStateOut(BaseModel):
    """Summary counts of crawl states for a job."""

    complete: int = Field(default=0, description="Number of pages successfully crawled.")
    robots_blocked: int = Field(default=0, description="Pages blocked by robots.txt.")
    failed: int = Field(default=0, description="Pages that failed to fetch.")
    pending: int = Field(default=0, description="Pages not yet processed.")


class CrawlJobOut(BaseModel):
    """Response body for POST /crawl-jobs and GET /crawl-jobs/{job_id}."""

    job_id: str = Field(description="Crawl job ID (job_...).")
    source_id: str = Field(description="Source registry ID (src_...).")
    crawler: str = Field(description="Crawler adapter used for this job.")
    status: str = Field(description="Job status: pending, running, complete, failed.")
    states: CrawlStateOut = Field(
        default_factory=CrawlStateOut,
        description="Summary of page-level crawl states.",
    )


# ── Parse / Clean / Chunk pipeline schemas (03-03) ───────────────────────────


class ParseRequest(BaseModel):
    """Request body for POST /parse — run the parse pipeline stage.

    Pydantic validates at the API boundary (ASVS V5, T-03-11).
    artifact_id is looked up via parameterised ORM query (no raw SQL injection).
    """

    raw_artifact_id: str = Field(
        ...,
        description="ID of the raw_document artifact to parse.",
        min_length=1,
    )
    source_id: str = Field(
        ...,
        description="Source registry ID that owns the raw artifact.",
        min_length=1,
    )
    mime_type: str = Field(
        default="application/pdf",
        description="MIME type of the raw document.",
    )


class ParseResponse(BaseModel):
    """Response body for POST /parse."""

    artifact_id: str = Field(description="Parsed document artifact ID (doc_...).")
    quality_score: float = Field(description="Heuristic quality score in [0, 1].")
    parser_used: str = Field(description="Name of the parser that succeeded (e.g. 'docling').")
    content_hash: str = Field(description="SHA-256 hash of the parsed document bytes.")


class CleanRequest(BaseModel):
    """Request body for POST /clean — run the clean pipeline stage.

    Pydantic validates at the API boundary (ASVS V5, T-03-11).
    """

    parsed_artifact_id: str = Field(
        ...,
        description="ID of the parsed_document artifact to clean.",
        min_length=1,
    )
    source_id: str = Field(
        ...,
        description="Source registry ID that owns the parsed artifact.",
        min_length=1,
    )


class CleanResponse(BaseModel):
    """Response body for POST /clean."""

    artifact_id: str = Field(description="Cleaned document artifact ID (doc_...).")
    language: str = Field(description="Detected language ISO 639-1 code (e.g. 'en').")
    dedup_status: str = Field(description="Near-duplicate status: 'unique', 'exact_dup', or 'near_dup'.")
    content_hash: str = Field(description="SHA-256 hash of the cleaned document bytes.")


class ChunkRequest(BaseModel):
    """Request body for POST /chunk — run the chunk pipeline stage.

    Pydantic validates at the API boundary (ASVS V5, T-03-11).
    """

    parsed_artifact_id: str = Field(
        ...,
        description="ID of the parsed_document artifact to chunk.",
        min_length=1,
    )
    source_id: str = Field(
        ...,
        description="Source registry ID that owns the parsed artifact.",
        min_length=1,
    )


class ChunkResponse(BaseModel):
    """Response body for POST /chunk."""

    chunk_count: int = Field(description="Number of chunk artifacts created.")
    chunk_ids: list[str] = Field(description="List of chunk artifact IDs (chk_...).")


class EnrichRequest(BaseModel):
    """Request body for POST /enrich — run the enrich pipeline stage.

    Pydantic validates at the API boundary (ASVS V5).
    """

    cleaned_artifact_id: str = Field(
        ...,
        description="ID of the cleaned_document artifact to enrich.",
        min_length=1,
    )
    source_id: str = Field(
        ...,
        description="Source registry ID that owns the cleaned artifact.",
        min_length=1,
    )


class EnrichResponse(BaseModel):
    """Response body for POST /enrich."""

    artifact_id: Optional[str] = Field(
        default=None,
        description="Enriched document artifact ID (doc_...), None when skipped.",
    )
    status: str = Field(
        description="'enriched', 'cached', 'skipped_budget_exceeded', or 'skipped_enrichment_failed'."
    )
    cached: bool = Field(description="True when this call was an ENRICH-04 cache hit.")
    quality_score: Optional[float] = Field(
        default=None,
        description="LLM-judged quality score in [0,1], None when skipped.",
    )


class ReindexResponse(BaseModel):
    """Response body for POST /reindex — zero-downtime alias reindex result (INDEX-02)."""

    collection: str = Field(description="Qdrant alias that was reindexed.")
    new_physical: str = Field(description="New physical collection the alias now points to.")
    old_physical: Optional[str] = Field(
        default=None,
        description="Prior physical collection (retained, never auto-dropped); None on first-ever reindex.",
    )


class DiscoverRequest(BaseModel):
    """Request body for POST /discover — run a discovery query.

    Pydantic validates at the API boundary (ASVS V5, T-02-25).
    """

    query: str = Field(
        ...,
        description="Natural-language search query for source discovery.",
        min_length=1,
        max_length=500,
    )
    limit: int = Field(
        default=20,
        description="Maximum number of results to request from the discovery engine.",
        ge=1,
        le=100,
    )


class DiscoverResultItem(BaseModel):
    """A single discovered source result in POST /discover response."""

    url: str = Field(description="The discovered URL.")
    title: str = Field(description="Title from the search result.")
    source_id: Optional[str] = Field(
        default=None,
        description="Registry source ID (None if skipped).",
    )
    status: str = Field(
        description="Result status: 'registered', 'existing', or 'skipped_ssrf'."
    )


class DiscoverOut(BaseModel):
    """Response body for POST /discover — list of discovery results."""

    query: str = Field(description="The query that was executed.")
    total: int = Field(description="Total number of results returned by the engine.")
    results: list[DiscoverResultItem] = Field(
        description="Per-result status with source IDs."
    )
