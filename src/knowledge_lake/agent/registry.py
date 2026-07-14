"""MCP tool registry: ToolDef + TOOLS + registered_tools (D-01, D-11, MCP-01).

This module is the **single source of truth** for all 11 Knowledge Lake MCP
tools.  Every surface (stdio, HTTP, OpenAI defs) reads from ``TOOLS`` so that
``stdio == http`` by construction.

Design contract (from PLAN 12-05 must_haves):

D-01: ``TOOLS`` is a module-level list of 11 ``ToolDef`` entries.  No other
      file builds tool schemas — everyone reads from here.

D-03: Each ``ToolDef.handler`` is a callable imported from ``pipeline/*.py``
      (or ``lineage.resolve_ancestry``), **never** from ``api.app``.  REST
      and MCP are siblings over the same pipeline functions.

D-11: Read tools = {search, list_sources, lineage, stats}.
      Write tools = all other seven.

The ``registered_tools(readonly)`` helper returns the pre-filtered list so
the MCP server never has to do its own access-control logic.

Prohibitions (PLAN 12-05):
- No FastMCP / @tool() decorators — inputSchema comes from input_model.
- No import of api.app — no REST proxying.
- No asyncio.run — the server uses ``await`` directly for async handlers.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel


@dataclass
class ToolDef:
    """Descriptor for a single MCP tool.

    Attributes:
        name:         Tool name as sent to the client (unique in TOOLS).
        description:  Human-readable description surfaced in list_tools.
        input_model:  Pydantic model class; ``input_model.model_json_schema()``
                      becomes the ``inputSchema`` in the protocol message (D-01).
        handler:      Callable imported from ``pipeline/*.py`` (D-03).
                      Async handlers (crawl, crawl_all) are detected via
                      ``inspect.iscoroutinefunction`` in ``build_server`` and
                      awaited directly — no ``asyncio.run``.
        access:       'read' for safe read-only tools, 'write' for mutating tools.
    """

    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable
    access: Literal["read", "write"]


# ---------------------------------------------------------------------------
# Handler imports — pipeline/* only (D-03 hard rule, MCP-01).
# Any addition here must NOT import api.app or make an HTTP call.
# ---------------------------------------------------------------------------

# Read handlers
# ---------------------------------------------------------------------------
# Input models — from api/schemas.py (D-02: one schema, two surfaces).
# ---------------------------------------------------------------------------
from knowledge_lake.api.schemas import (  # noqa: E402
    CrawlAllInput,
    # Crawl
    CrawlJobCreate,
    # Domain
    DomainLoadRequest,
    # Export
    ExportRequest,
    # Ingest
    IngestUrlInput,
    LineageInput,
    ListSourcesInput,
    # Process
    ProcessCrawledInput,
    # Search & lineage
    SearchParams,
    # Source management
    SourceCreate,
    # Query (MCP-only models, no prior request schema)
    StatsInput,
)
from knowledge_lake.lineage import resolve_ancestry  # noqa: E402
from knowledge_lake.pipeline.crawl import crawl_all_sources, crawl_source  # noqa: E402
from knowledge_lake.pipeline.domains import load_domain  # noqa: E402
from knowledge_lake.pipeline.export import (  # noqa: E402
    export_finetune_dataset,
    export_pretrain_corpus,
    export_rag_corpus,
)

# Write handlers
from knowledge_lake.pipeline.ingest import ingest_url, register_source  # noqa: E402
from knowledge_lake.pipeline.process import process_crawled  # noqa: E402
from knowledge_lake.pipeline.query import list_sources, stats  # noqa: E402
from knowledge_lake.pipeline.route import routed_search  # noqa: E402
from knowledge_lake.pipeline.search import search  # noqa: E402

# ---------------------------------------------------------------------------
# Export dispatch handler (mirrors api/app.py:1191-1204 verbatim).
# call_tool uses this single callable; the dispatch on kind is done inside.
# ---------------------------------------------------------------------------

def _export_dispatch(
    kind: str,
    dataset_name: str | None = None,
) -> dict:
    """Dispatch export to the correct pipeline function based on kind.

    Mirrors the dispatch block in ``api/app.py:1191-1204`` verbatim.
    ``TrainEvalContaminationError`` and ``ValueError`` are propagated to
    ``build_server``'s call_tool handler which converts them to isError results.
    """

    if kind == "rag-corpus":
        return export_rag_corpus()
    elif kind == "pretrain":
        return export_pretrain_corpus()
    else:
        if not dataset_name:
            raise ValueError("dataset_name is required for kind='finetune'.")
        return export_finetune_dataset(dataset_name)


# ---------------------------------------------------------------------------
# Handler shims — each shim unpacks the validated Pydantic model into the
# pipeline function's kwargs.  Shims are called FROM build_server's
# call_tool handler; the shim itself is synchronous (wrapping async at the
# point of dispatch in build_server, not here).
# ---------------------------------------------------------------------------


def _search_handler(
    q: str,
    collection: str = "klake_chunks",
    top_k: int = 5,
    domain: str | None = None,
    document_type: str | None = None,
    min_quality_score: float | None = None,
    source_name: str | None = None,
    format: str | None = None,  # noqa: A002
    tags: list[str] | None = None,
    source_id: str | None = None,
    mode: str | None = None,
    route: str | None = None,
    tree_mode: str | None = None,
) -> list:
    """Thin shim: maps SearchParams fields to routed_search() signature (ROUTE-04, D-08)."""
    hits = routed_search(
        query=q,
        route=route,
        collection=collection,
        top_k=top_k,
        domain=domain,
        document_type=document_type,
        min_quality_score=min_quality_score,
        source_name=source_name,
        format=format,  # noqa: A002
        tags=tags,
        source_id=source_id,
        mode=mode,
        tree_mode=tree_mode,
    )
    # Return serialisable list of dicts (SDK auto-wraps).
    # Hit is a @dataclass; use dataclasses.asdict() which handles nested dataclasses
    # recursively — dict(h) would raise TypeError since dataclass has no mapping interface.
    return [dataclasses.asdict(h) for h in hits]


def _ingest_url_handler(
    url: str,
    source_name: str,
    mime_type: str | None = None,
    license_type: str = "unknown",
    robots_checked: bool = False,
) -> dict:
    """Thin shim: maps IngestUrlInput fields to ingest_url()."""
    result = ingest_url(
        url=url,
        source_name=source_name,
        mime_type=mime_type,
        license_type=license_type,
        robots_checked=robots_checked,
    )
    # ingest_url returns a dict with artifact_id, source_id, content_hash, etc.
    if isinstance(result, dict):
        return result
    # Fallback: serialize attrs
    return {k: getattr(result, k) for k in ("artifact_id", "source_id") if hasattr(result, k)}


def _add_source_handler(
    url: str,
    name: str | None = None,
    domain: str | None = None,
    license_type: str = "unknown",
) -> dict:
    """Thin shim: maps SourceCreate fields to register_source()."""
    # CLI parity (WR-02): register_source(name: str) requires a real name.
    # When the caller omits it, default to the URL hostname, matching the CLI.
    if not name:
        name = urlparse(url).hostname or url

    # register_source(url, name, *, domain=..., license_type=...) takes NO
    # session parameter — it opens and commits its own session and returns a
    # plain dict with keys source_id / name / url / normalized_url / domain /
    # is_new (CR-01). Do NOT wrap in get_session() or pass a session arg.
    result = register_source(
        url,
        name,
        domain=domain,
        license_type=license_type,
    )
    return {
        "source_id": result["source_id"],
        "name": result["name"],
        "url": result["url"],
        "is_new": result["is_new"],
    }


def _lineage_handler(artifact_id: str) -> dict:
    """Thin shim: maps LineageInput.artifact_id to resolve_ancestry()."""
    nodes = resolve_ancestry(artifact_id)
    return {"artifact_id": artifact_id, "nodes": nodes}


def _export_handler(kind: str, dataset_name: str | None = None) -> dict:
    """Thin shim: maps ExportRequest fields to the export dispatch."""
    return _export_dispatch(kind=kind, dataset_name=dataset_name)


# ---------------------------------------------------------------------------
# TOOLS — the 11-entry single source of truth (D-11).
# Order: 4 read tools first, then 7 write tools.
# ---------------------------------------------------------------------------

TOOLS: list[ToolDef] = [
    # ── Read tools (access='read') ─────────────────────────────────────────
    ToolDef(
        name="search",
        description=(
            "Semantic search over the knowledge lake. "
            "Returns ranked chunk hits with scores and citation metadata. "
            "Supports dense, sparse, and hybrid retrieval modes."
        ),
        input_model=SearchParams,
        handler=_search_handler,
        access="read",
    ),
    ToolDef(
        name="list_sources",
        description=(
            "List registered sources in the knowledge lake registry. "
            "Supports optional domain filtering and pagination."
        ),
        input_model=ListSourcesInput,
        handler=list_sources,
        access="read",
    ),
    ToolDef(
        name="lineage",
        description=(
            "Trace the full ancestry chain of any artifact. "
            "Returns an ordered list of nodes from the queried artifact back "
            "to the original raw document."
        ),
        input_model=LineageInput,
        handler=_lineage_handler,
        access="read",
    ),
    ToolDef(
        name="stats",
        description=(
            "Return aggregate statistics about the knowledge lake: "
            "source count, document count, artifact counts by type, "
            "and Qdrant vector point count."
        ),
        input_model=StatsInput,
        handler=stats,
        access="read",
    ),
    # ── Write tools (access='write') ──────────────────────────────────────
    ToolDef(
        name="ingest_url",
        description=(
            "Ingest a single document from a URL into the knowledge lake. "
            "Fetches, stores in the raw zone, and returns the artifact ID. "
            "SSRF-guarded via validate_public_url (RFC-1918/IMDS blocked)."
        ),
        input_model=IngestUrlInput,
        handler=_ingest_url_handler,
        access="write",
    ),
    ToolDef(
        name="add_source",
        description=(
            "Register a new source in the knowledge lake registry. "
            "Deduplicates by normalized URL — returns existing source if already present."
        ),
        input_model=SourceCreate,
        handler=_add_source_handler,
        access="write",
    ),
    ToolDef(
        name="crawl",
        description=(
            "Start a crawl job for a seed URL. "
            "Follows links up to max_pages depth, stores raw HTML artifacts. "
            "Async — use process_crawled to parse and index after crawling."
        ),
        input_model=CrawlJobCreate,
        handler=crawl_source,  # async — awaited in build_server's call_tool
        access="write",
    ),
    ToolDef(
        name="crawl_all",
        description=(
            "Batch-crawl all registered sources (or a domain subset). "
            "Runs each source crawl independently — failures on one source "
            "do not abort others."
        ),
        input_model=CrawlAllInput,
        handler=crawl_all_sources,  # async — awaited in build_server's call_tool
        access="write",
    ),
    ToolDef(
        name="process_crawled",
        description=(
            "Process crawled raw_document artifacts through the full pipeline: "
            "parse → chunk → embed → index. "
            "Finds all unprocessed raw docs and converts them to searchable vectors."
        ),
        input_model=ProcessCrawledInput,
        handler=process_crawled,
        access="write",
    ),
    ToolDef(
        name="export",
        description=(
            "Export the curated knowledge lake corpus to the gold zone. "
            "Supports three kinds: 'rag-corpus' (Parquet), 'pretrain' (JSONL), "
            "'finetune' (JSONL from a named dataset)."
        ),
        input_model=ExportRequest,
        handler=_export_handler,
        access="write",
    ),
    ToolDef(
        name="init_domain",
        description=(
            "Load a domain pack and register all its sources. "
            "Reads the domain YAML, validates, and registers each source via add_source."
        ),
        input_model=DomainLoadRequest,
        handler=load_domain,
        access="write",
    ),
]

assert len(TOOLS) == 11, f"TOOLS must have exactly 11 entries, got {len(TOOLS)}"
assert len({t.name for t in TOOLS}) == 11, "TOOLS has duplicate tool names"


def registered_tools(readonly: bool = False) -> list[ToolDef]:
    """Return the filtered tool list based on the readonly posture.

    When ``readonly=True``, only the 4 read-access tools (search, list_sources,
    lineage, stats) are returned — suitable for the read-only MCP transport
    posture controlled by ``settings.mcp.readonly`` (D-11).

    When ``readonly=False`` (default), all 11 tools are returned.

    Args:
        readonly: If True, return only tools with ``access='read'``.

    Returns:
        Filtered list of ToolDef entries.
    """
    return [t for t in TOOLS if not readonly or t.access == "read"]
