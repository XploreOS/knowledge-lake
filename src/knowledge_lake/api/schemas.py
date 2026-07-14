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

Plan 12-03: SearchParams extended with all search() filter kwargs so the
    tool registry and GET /search share one model (Pitfall 4, SKILL-03 no-drift).
    Six new input models added for tools without an existing request schema.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── Request schemas ────────────────────────────────────────────────────────────


class SearchParams(BaseModel):
    """Query parameters for GET /search and the MCP ``search`` tool (D-02).

    Pydantic validates these before the handler runs, satisfying ASVS V5
    (input validation at the API boundary).

    Extended in Plan 12-03 to cover every ``search()`` filter kwarg so that
    ``SearchParams().model_dump(exclude_none=True)`` unpacks cleanly into
    ``search(**kwargs)`` without an unexpected-keyword error (Pitfall 4,
    SKILL-03 no-drift rule).

    Handler note: ``q`` maps to the ``query`` positional arg of ``search()``;
    callers must pass it as ``search(query=params.q, **rest)`` (the field
    is kept as ``q`` for URL-query-parameter brevity in GET /search).
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
    mode: str | None = Field(
        default=None,
        pattern=r"^(hybrid|dense|sparse)$",
        description=(
            "Search mode; default resolves from KLAKE_SEARCH__MODE (hybrid). "
            "Must be one of: hybrid, dense, sparse. "
            "An unrecognised value is rejected with 422 (T-10-02, ASVS V5)."
        ),
    )
    route: str | None = Field(
        default=None,
        pattern=r"^(chunk|tree|two_stage|auto)$",
        description=(
            "Retrieval route; default resolves from KLAKE_ROUTER__DEFAULT_ROUTE (auto). "
            "Must be one of: chunk, tree, two_stage, auto. "
            "An unrecognised value is rejected with 422 (ASVS V5, ROUTE-04). "
            "This field feeds the MCP inputSchema and OpenAI tool defs automatically "
            "via model_json_schema() (Pitfall 5 — default=None, not 'auto', so "
            "model_dump(exclude_none=True) omits it when unset, letting "
            "settings.router.default_route take effect in routed_search())."
        ),
    )
    # ── Filter fields added in Plan 12-03 (Pitfall 4 fix) ────────────────────
    # Each field maps directly to the same-named kwarg in pipeline.search().
    # Types and optionality mirror the search() signature (search.py:35-48).
    domain: str | None = Field(
        default=None,
        description="Payload filter: restrict results to this domain (e.g. 'healthcare').",
    )
    document_type: str | None = Field(
        default=None,
        description="Payload filter: restrict results to this document type (e.g. 'regulation').",
    )
    min_quality_score: float | None = Field(
        default=None,
        description="Payload filter: only return chunks with quality_score >= this value.",
        ge=0.0,
        le=1.0,
    )
    source_name: str | None = Field(
        default=None,
        description="Payload filter: restrict results to this source name.",
    )
    format: str | None = Field(  # noqa: A003
        default=None,
        description=(
            "Payload filter: restrict results to this source format "
            "(e.g. 'pdf', 'html'). Shadows Python built-in — only safe because "
            "the built-in is not used within this class scope (mirrors noqa A002 in search.py)."
        ),
    )
    tags: list[str] | None = Field(
        default=None,
        description=(
            "Payload filter: restrict results to chunks whose tags contain "
            "all of the listed values. Single tag uses MatchValue; multiple use MatchAny (D-11)."
        ),
    )
    source_id: str | None = Field(
        default=None,
        description="Payload filter: restrict results to chunks from this source registry ID.",
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
    domain: str | None = Field(
        default=None, description="Domain classification from the source (e.g. 'healthcare')."
    )
    document_type: str | None = Field(
        default=None, description="Enrichment-derived document type (e.g. 'regulation', 'guidance')."
    )
    keywords: list[str] = Field(
        default_factory=list, description="Enrichment-derived keywords for this document."
    )
    quality_score: float | None = Field(
        default=None, description="LLM-judged quality score in [0, 1] from enrichment."
    )

    # PAYLOAD-02: source provenance fields (Phase 7 — only populated on points indexed
    # after Phase 7 or after a full reindex; pre-Phase-7 points return None / []).
    source_id: str | None = Field(
        default=None, description="Registry source ID for this chunk's source (src_...)."
    )
    source_name: str | None = Field(
        default=None, description="Human-readable source name."
    )
    source_url: str | None = Field(
        default=None, description="Canonical source URL."
    )
    format: str | None = Field(
        default=None,
        description="Source format label (e.g. 'html', 'pdf', 'csv') from Source.source_type.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Curated source tags from Source.config (distinct from LLM-extracted keywords).",
    )
    title: str | None = Field(
        default=None, description="Document title from enrichment metadata."
    )
    organization: str | None = Field(
        default=None,
        description="Publishing organization from Source.config (None until sources.yaml carries organization key).",
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
    storage_uri: str | None = Field(
        default=None,
        description="S3 URI where the artifact bytes are stored.",
    )

    # Additional lineage / provenance fields
    source_id: str | None = Field(default=None, description="Source registry ID (src_...).")
    parent_artifact_id: str | None = Field(
        default=None,
        description="Parent artifact ID (None for root raw_document).",
    )
    depth: int = Field(default=0, description="Depth from the queried artifact (0 = the artifact itself).")

    # Citation fields (available on chunk nodes)
    section_path: str | None = Field(default=None, description="Section path (chunk nodes only).")
    page: int | None = Field(default=None, description="Page number (chunk nodes only).")
    mime_type: str | None = Field(default=None, description="MIME type of the artifact.")


class LineageGraph(BaseModel):
    """The full lineage chain returned by GET /lineage/{artifact_id}.

    ``nodes`` is ordered leaf-first (depth 0 = the queried artifact,
    deepest = the root raw_document).
    """

    artifact_id: str = Field(description="The queried artifact ID.")
    nodes: list[LineageNode] = Field(description="Ordered ancestry nodes (leaf → root).")


# ── Export schemas (EXPORT-01..03) ─────────────────────────────────────────────


class ExportRequest(BaseModel):
    """Request body for POST /exports.

    Bounded to the three valid export kinds via Pydantic pattern validation
    (T-05-09: no free-form string ever reaches the gold-zone S3 key construction).
    """

    kind: str = Field(
        ...,
        pattern=r"^(rag-corpus|pretrain|finetune)$",
        description="Export kind: 'rag-corpus', 'pretrain', or 'finetune'.",
    )
    dataset_name: str | None = Field(
        default=None,
        max_length=255,
        description="Required for kind='finetune'. The logical Dataset name to export.",
    )


class ExportResponse(BaseModel):
    """Response body for POST /exports."""

    dataset_id: str = Field(description="Registry ID of the created/updated Dataset row.")
    storage_uri: str = Field(description="S3 URI of the exported file in the gold zone.")
    row_count: int = Field(description="Number of rows/examples written to the export file.")
    skipped_dangling_lineage: int | None = Field(
        default=None,
        description="(finetune only) Number of examples skipped due to unresolvable source_artifact_id.",
    )


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
    name: str | None = Field(
        default=None,
        description="Human-readable source name (defaults to URL hostname).",
    )
    domain: str | None = Field(
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
    normalized_url: str | None = Field(
        default=None,
        description="D-06 normalized URL used for dedup.",
    )
    domain: str | None = Field(
        default=None,
        description="Domain classification.",
    )
    is_new: bool = Field(description="True if newly created, False if dedup hit.")


class UploadOut(BaseModel):
    """Response body for POST /uploads — uploaded artifact details."""

    source_id: str = Field(description="Source registry ID (src_...).")
    artifact_id: str = Field(description="Raw artifact ID (doc_...).")
    storage_uri: str | None = Field(
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
    crawler: str | None = Field(
        default=None,
        description="Override crawler adapter name (must be a registered crawler).",
        max_length=64,
    )
    max_pages: int | None = Field(
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


# ── Batch crawl schemas (08-06) — CRAWL-02 ────────────────────────────────────
# M-01 fix: CrawlAllRequest was dead code — the /crawl-all endpoint reads
# `domain` as a Query parameter, not a request body.  Clients POSTing
# {"domain": "healthcare"} would have silently received domain=None.
# Removed; the endpoint contract is now documented via its Query annotation.


class CrawlAllSourceResult(BaseModel):
    """Per-source result entry in a CrawlAllOut response.

    CRAWL-02 D-09: each source's crawl is independent — failures on one source
    are logged and counted but do not abort the batch.
    """

    source_id: str = Field(description="Source registry ID (src_...).")
    status: str = Field(description="'ok' if crawl succeeded, 'failed' otherwise.")
    error: str | None = Field(
        default=None,
        description="Error message if status is 'failed', else None.",
    )
    pages_complete: int | None = Field(
        default=None,
        description="Number of pages successfully crawled (None if failed before crawl started).",
    )


class CrawlAllOut(BaseModel):
    """Response body for POST /crawl-all — batch-crawl summary.

    CRAWL-02 D-09: reports aggregate totals and a per-source result list.
    A failure on one source is reflected in 'failed' and 'results' but the
    endpoint still returns 200 with partial results for the remaining sources.
    """

    total: int = Field(description="Total number of sources attempted.")
    succeeded: int = Field(description="Number of sources whose crawl completed without error.")
    failed: int = Field(description="Number of sources whose crawl raised an exception.")
    results: list[CrawlAllSourceResult] = Field(
        description="Per-source crawl result list (one entry per source attempted).",
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

    artifact_id: str | None = Field(
        default=None,
        description="Enriched document artifact ID (doc_...), None when skipped.",
    )
    status: str = Field(
        description="'enriched', 'cached', 'skipped_budget_exceeded', or 'skipped_enrichment_failed'."
    )
    cached: bool = Field(description="True when this call was an ENRICH-04 cache hit.")
    quality_score: float | None = Field(
        default=None,
        description="LLM-judged quality score in [0,1], None when skipped.",
    )


class CurateRequest(BaseModel):
    """Request body for POST /curate — run the curate pipeline stage (CURATE-01..03).

    Pydantic validates at the API boundary (ASVS V5, T-05-03).
    """

    cleaned_artifact_id: str = Field(
        ...,
        description="ID of the cleaned_document artifact to curate.",
        min_length=1,
    )
    source_id: str = Field(
        ...,
        description="Source registry ID that owns the cleaned artifact.",
        min_length=1,
    )


class CurateResponse(BaseModel):
    """Response body for POST /curate (CURATE-01..03)."""

    artifact_id: str | None = Field(
        default=None,
        description="Curated document artifact ID (doc_...), None when unavailable.",
    )
    status: str = Field(
        description="'curated' or 'cached'.",
    )
    cached: bool = Field(
        default=False,
        description="True when this call was a cache hit (same content_hash + filter_config_version).",
    )
    quality_score: float | None = Field(
        default=None,
        description="Composite quality score in [0,1] spanning parse + enrich + curation stages.",
    )
    dedup_status: str | None = Field(
        default=None,
        description=(
            "'not_yet_computed' until batch_dedup_corpus() runs; "
            "'near_dup' or 'unique' after."
        ),
    )


class CuratedDocumentOut(BaseModel):
    """A single curated document summary for GET /curated-documents (CURATE-03)."""

    artifact_id: str = Field(description="Curated document artifact ID (doc_...).")
    quality_score: float | None = Field(
        default=None,
        description="Composite quality score in [0,1], None if not yet computed.",
    )
    dedup_status: str | None = Field(
        default=None,
        description="'near_dup', 'unique', or 'not_yet_computed'.",
    )
    created_at: str = Field(description="ISO-8601 creation timestamp.")


class DedupeResponse(BaseModel):
    """Response body for POST /curate/dedupe — corpus-wide MinHash batch dedup result (CURATE-02)."""

    total: int = Field(description="Total cleaned_document artifacts scanned.")
    unique: int = Field(description="Artifacts classified as unique (no near-duplicate found).")
    near_dup: int = Field(description="Artifacts classified as near-duplicate.")
    skipped_no_curation: int = Field(
        description="Artifacts skipped because no curated_document child exists yet."
    )


class ReindexResponse(BaseModel):
    """Response body for POST /reindex — zero-downtime alias reindex result (INDEX-02)."""

    collection: str = Field(description="Qdrant alias that was reindexed.")
    new_physical: str = Field(description="New physical collection the alias now points to.")
    old_physical: str | None = Field(
        default=None,
        description="Prior physical collection (retained, never auto-dropped); None on first-ever reindex.",
    )


class GenerateDatasetRequest(BaseModel):
    """Request body for POST /datasets/examples — generate a dataset example (DATA-01/02).

    Pydantic validates at the API boundary (ASVS V5, T-05-07):
      - kind is bounded to '^(qa|instruction)$' via pattern validation
      - Artifact lookups use parameterised SQLAlchemy queries (no raw SQL)
    """

    kind: str = Field(
        ...,
        description="Dataset kind: 'qa' (chunk → Q&A via eval_model) or 'instruction' (enriched_document → instruction via strong_model).",
        pattern=r"^(qa|instruction)$",
    )
    source_artifact_id: str = Field(
        ...,
        description="Source artifact ID: chunk ID for 'qa', enriched_document ID for 'instruction'.",
        min_length=1,
    )
    dataset_name: str = Field(
        ...,
        description="Name of the dataset to accumulate this example into (get-or-create).",
        min_length=1,
        max_length=255,
    )


class GenerateDatasetResponse(BaseModel):
    """Response body for POST /datasets/examples (DATA-01/02/03)."""

    status: str = Field(
        description="'generated', 'cached', 'skipped_budget_exceeded', or 'skipped_generation_failed'.",
    )
    example_id: str | None = Field(
        default=None,
        description="DatasetExample ID (dex_...), None when skipped.",
    )
    dataset_id: str | None = Field(
        default=None,
        description="Dataset ID (dst_...) this example belongs to.",
    )
    cost_usd: float | None = Field(
        default=None,
        description="LLM call cost in USD for this generation. 0.0 on cache hit, None when skipped.",
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
    source_id: str | None = Field(
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


# ── Registry list/get schemas (D-07 gap audit — 8 new endpoints) ─────────────


class SourceListItem(BaseModel):
    """A single source registry entry for GET /sources and GET /sources/{source_id}.

    Surfaced by the 8-endpoint gap audit (D-07). Contains the key display fields
    for operators browsing registered sources; no credentials or internal keys.
    """

    source_id: str = Field(description="Source registry ID (src_...).")
    name: str = Field(description="Human-readable source name.")
    url: str | None = Field(default=None, description="Canonical source URL.")
    source_type: str = Field(
        default="unknown",
        description="Kind of source: 'web', 'upload', 'crawler', etc.",
    )
    license_type: str | None = Field(default=None, description="SPDX license identifier.")
    domain: str | None = Field(
        default=None,
        description="Domain classification extracted from Source.config['domain'].",
    )
    created_at: str = Field(description="ISO-8601 creation timestamp.")


class ArtifactOut(BaseModel):
    """A single artifact entry for GET /documents and GET /documents/{artifact_id}.

    Returns the registry metadata for a document artifact of any type.
    """

    id: str = Field(description="Artifact registry ID (type-prefixed UUIDv7).")
    artifact_type: str = Field(description="Node type: raw_document, parsed_document, chunk, etc.")
    source_id: str | None = Field(default=None, description="Source registry ID (src_...).")
    parent_artifact_id: str | None = Field(
        default=None,
        description="Parent artifact ID (None for root raw_document).",
    )
    content_hash: str = Field(description="SHA-256 hash of the artifact bytes.")
    created_at: str = Field(description="ISO-8601 creation timestamp.")
    storage_uri: str | None = Field(
        default=None,
        description="S3 URI where the artifact bytes are stored.",
    )
    mime_type: str | None = Field(default=None, description="MIME type of the artifact.")


class DatasetOut(BaseModel):
    """A single dataset entry for GET /datasets and GET /datasets/{dataset_id}.

    Returns the registry metadata for a curated dataset.
    """

    dataset_id: str = Field(description="Dataset registry ID (dst_...).")
    name: str = Field(description="Human-readable, unique dataset name.")
    created_at: str = Field(description="ISO-8601 creation timestamp.")
    row_count: int = Field(
        default=0,
        description="Number of examples in the dataset (0 until exported).",
    )


class DomainLoadRequest(BaseModel):
    """Request body for POST /domains/load — load a domain pack and register its sources.

    Security (T-06-08 / ASVS V5):
        - name validated against r'^[a-zA-Z][a-zA-Z0-9_-]{0,63}$' via Pydantic pattern.
        - Pattern blocks path traversal attempts (e.g. '../etc', 'foo/../bar').
    """

    name: str = Field(
        ...,
        description="Domain pack name to load (e.g. 'healthcare').",
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$",
    )


class DomainLoadResponse(BaseModel):
    """Response body for POST /domains/load."""

    name: str = Field(description="Domain pack name that was loaded.")
    loaded_count: int = Field(description="Number of new sources registered.")
    skipped_count: int = Field(description="Number of sources already in the registry (dedup).")
    upload_required_count: int = Field(
        description="Number of upload-type sources that require manual download first.",
    )


# ── MCP tool input models (Plan 12-03, D-02 / SKILL-03 no-drift) ─────────────
#
# Each model is the single source of truth for one MCP tool's argument shape.
# Field names match the target pipeline function's kwargs exactly so that
# ``model.model_dump(exclude_none=True)`` unpacks cleanly into the function call.
#
# Tools that already have a matching request schema reuse it:
#   - crawl        → CrawlJobCreate (source_url, crawler, max_pages)
#   - add_source   → SourceCreate   (url, name, domain, license_type)
#   - export       → ExportRequest  (kind, dataset_name)
#   - init_domain  → DomainLoadRequest (name — carries the path-traversal guard)
#
# The six new models below cover the remaining tools (no prior request schema).


class StatsInput(BaseModel):
    """MCP ``stats`` tool input — maps to ``pipeline.query.stats()``.

    ``stats()`` signature: stats(*, collection="klake_chunks", domain=None)
    All fields are optional; defaults mirror the pipeline function defaults.
    """

    collection: str = Field(
        default="klake_chunks",
        description="Qdrant collection to count points in.",
    )
    domain: str | None = Field(
        default=None,
        description="Optional domain to scope source and artifact counts (e.g. 'healthcare').",
    )


class ProcessCrawledInput(BaseModel):
    """MCP ``process_crawled`` tool input — maps to ``pipeline.process.process_crawled()``.

    ``process_crawled()`` signature:
        process_crawled(*, source_id=None, limit=100, collection="klake_chunks")
    """

    source_id: str | None = Field(
        default=None,
        description="Restrict processing to raw docs from this source registry ID.",
    )
    limit: int = Field(
        default=100,
        description="Maximum number of raw documents to process.",
        ge=1,
        le=10000,
    )
    collection: str = Field(
        default="klake_chunks",
        description="Qdrant collection to index chunks into.",
    )


class ListSourcesInput(BaseModel):
    """MCP ``list_sources`` tool input — maps to ``pipeline.query.list_sources()``.

    ``list_sources()`` signature:
        list_sources(domain=None, *, limit=50, offset=0)
    """

    domain: str | None = Field(
        default=None,
        description="Filter results to this domain (e.g. 'healthcare').",
    )
    limit: int = Field(
        default=50,
        description="Maximum number of sources to return.",
        ge=1,
        le=1000,
    )
    offset: int = Field(
        default=0,
        description="Zero-based pagination offset.",
        ge=0,
    )


class LineageInput(BaseModel):
    """MCP ``lineage`` tool input — maps to ``lineage.resolve_ancestry(artifact_id)``.

    The FastAPI endpoint uses artifact_id as a path parameter; the MCP tool
    passes it as a body field.  Security: the lineage resolver raises
    LookupError on unknown IDs (no SSRF surface — DB-only lookup).
    """

    artifact_id: str = Field(
        ...,
        description="Artifact ID to trace lineage for (type-prefixed UUIDv7, e.g. 'chk_...').",
        min_length=1,
    )


class IngestUrlInput(BaseModel):
    """MCP ``ingest_url`` tool input — maps to ``pipeline.ingest.ingest_url()``.

    ``ingest_url()`` signature:
        ingest_url(url, source_name, *, mime_type=None, license_type="unknown",
                   robots_checked=False, settings=None)

    SSRF guard (ASVS V5, T-12-07): scheme/SSRF validation is performed by
    ``ingest_url()`` itself — this model validates the surface-level format only.
    Do NOT re-implement the guard here (DRY, plan prohibition).
    """

    url: str = Field(
        ...,
        description="https:// URL of the document to ingest.",
        min_length=8,
    )
    source_name: str = Field(
        ...,
        description="Human-readable name for the source registry entry.",
        min_length=1,
        max_length=255,
    )
    mime_type: str | None = Field(
        default=None,
        description="MIME type override (e.g. 'application/pdf'). Defaults to Content-Type header.",
    )
    license_type: str = Field(
        default="unknown",
        description="SPDX license identifier or 'unknown'.",
        max_length=64,
    )
    robots_checked: bool = Field(
        default=False,
        description="Set to True only after verifying robots.txt allows fetching.",
    )


class CrawlAllInput(BaseModel):
    """MCP ``crawl_all`` tool input — maps to ``pipeline.crawl.crawl_all_sources()``.

    ``crawl_all_sources()`` signature:
        crawl_all_sources(domain=None, settings=None)

    ``settings`` is internal infrastructure — not exposed as a tool input field.
    """

    domain: str | None = Field(
        default=None,
        description="Optional domain filter; when set, only sources matching this domain are crawled.",
    )
