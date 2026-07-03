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
