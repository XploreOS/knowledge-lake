"""Query router dispatch layer (ROUTE-01..03, D-01..D-08).

Additive module: wraps search() and tree_search() without modifying either (D-02).
Provides classify_route() (deterministic heuristic classifier) and routed_search()
(dispatch orchestrator that selects between chunk and tree retrieval paths).

MUST stay synchronous (plain def). tree_search() raises RuntimeError if called from
a running event loop (it does asyncio.run() internally — Pitfall 2).
"""

from __future__ import annotations

import re

import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.pipeline.search import search
from knowledge_lake.pipeline.tree_search import tree_search
from knowledge_lake.plugins.protocols import Hit

log = structlog.get_logger(__name__)


# ── Tree-trigger classifier (D-04) ────────────────────────────────────────────
# Patterns are linear with literal keyword anchors — no nested quantifiers (T-15-02 ReDoS guard).
# Compiled once at module load; no user input is interpolated into patterns.

_TREE_TRIGGERS: list[tuple[str, re.Pattern[str]]] = [
    (
        "section_page_ref",
        re.compile(
            r"\bsection\s+\d|§|\bpages?\s+\d|\bchapter\s+\d",
            re.IGNORECASE,
        ),
    ),
    (
        "comparison_multihop",
        re.compile(
            r"\bcompare\b|\bdifference between\b|\bvs\.?\b|\bversus\b"
            r"|\bhow does .+ (?:affect|relate to|impact)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "structural_breadth",
        re.compile(
            r"\boutline of\b|\btable of contents\b|\ball sections\b"
            r"|\bsummarize (?:the|all)\b",
            re.IGNORECASE,
        ),
    ),
]


def classify_route(query: str) -> tuple[str, str]:
    """Classify a query as tree or chunk retrieval using heuristic regex triggers (D-04).

    Iterates _TREE_TRIGGERS in order, returns on first match.

    Returns:
        ("tree", category_name) — one of "section_page_ref", "comparison_multihop",
                                   or "structural_breadth" (ROUTE-02, ROUTE-03).
        ("chunk", "no_match")   — no structural signal detected (ROUTE-03).
    """
    for category, pat in _TREE_TRIGGERS:
        if pat.search(query):
            return "tree", category
    return "chunk", "no_match"


def routed_search(
    query: str,
    *,
    route: str | None = None,
    collection: str = "klake_chunks",
    top_k: int = 5,
    mode: str | None = None,
    tree_mode: str | None = None,
    settings: Settings | None = None,
    domain: str | None = None,
    document_type: str | None = None,
    min_quality_score: float | None = None,
    source_name: str | None = None,
    format: str | None = None,  # noqa: A002
    tags: list[str] | None = None,
    source_id: str | None = None,
) -> list[Hit]:
    """Dispatch a search query to the appropriate retrieval path (ROUTE-01..03, D-01..D-08).

    Per-call route wins over settings.router.default_route (ROUTE-01, D-07).
    Dispatch is synchronous — never call from a running event loop (Pitfall 2).

    Args:
        query:             Natural-language search query.
        route:             Explicit route override: 'chunk', 'tree', 'two_stage', or 'auto'.
                           None falls through to settings.router.default_route.
        collection:        Qdrant collection to search.
        top_k:             Maximum number of results to return.
        mode:              Chunk-retrieval sub-mode forwarded to search() only:
                           'hybrid' | 'dense' | 'sparse'. None → settings default.
        tree_mode:         Tree-traversal mode forwarded to tree_search() only:
                           'heuristic' | 'llm'. None → settings default.
        settings:          Settings override.
        domain:            Chunk-path filter (forwarded to search() only).
        document_type:     Chunk-path filter (forwarded to search() only).
        min_quality_score: Chunk-path filter (forwarded to search() only).
        source_name:       Chunk-path filter (forwarded to search() only).
        format:            Chunk-path filter (forwarded to search() only).
        tags:              Chunk-path filter (forwarded to search() only).
        source_id:         Chunk-path filter (forwarded to search() only).

    Returns:
        list[Hit] from the selected retrieval path, possibly empty.
    """
    if not query.strip():
        log.warning("route.empty_query")
        return []

    s = settings or get_settings()
    effective_route = route or s.router.default_route  # Pattern 1 per-call override (D-07)

    # Chunk filter kwargs forwarded to search() only — tree_search() accepts none of these.
    chunk_filters = dict(
        domain=domain,
        document_type=document_type,
        min_quality_score=min_quality_score,
        source_name=source_name,
        format=format,
        tags=tags,
        source_id=source_id,
    )
    # Strip None values so search() receives only filters that were actually specified.
    chunk_filters = {k: v for k, v in chunk_filters.items() if v is not None}

    if effective_route == "auto":
        decided, category = classify_route(query)  # deterministic-first (D-04)
        if decided == "tree":
            hits = tree_search(
                query,
                collection=collection,
                top_k=top_k,
                mode=tree_mode,   # tree-traversal mode: heuristic|llm
                settings=s,
            )
            if hits:
                log.info("route.dispatch", route="tree", trigger=category, fallback=False)
                return hits
            # D-05 auto-fallback: tree upgraded but empty → chunk (auto mode only)
            log.info("route.dispatch", route="tree", trigger=category, fallback=True)
            return search(
                query,
                collection=collection,
                top_k=top_k,
                mode=mode,        # chunk-retrieval mode: hybrid|dense|sparse
                settings=s,
                **chunk_filters,
            )
        # No structural signal — chunk path
        log.info("route.dispatch", route="chunk", trigger="no_match", fallback=False)
        return search(
            query,
            collection=collection,
            top_k=top_k,
            mode=mode,            # chunk-retrieval mode: hybrid|dense|sparse
            settings=s,
            **chunk_filters,
        )

    # Explicit operator override — D-05: NO fallback regardless of result
    if effective_route in ("tree", "two_stage"):  # D-01 alias
        log.info(
            "route.dispatch",
            route=effective_route,
            trigger="operator_override",
            fallback=False,
        )
        return tree_search(
            query,
            collection=collection,
            top_k=top_k,
            mode=tree_mode,       # tree-traversal mode: heuristic|llm
            settings=s,
        )

    # effective_route == "chunk" (also safe fallthrough for unrecognised values — WR-02 guard below)
    if effective_route != "chunk":
        log.warning("route.unknown_route", effective_route=effective_route)
    log.info("route.dispatch", route="chunk", trigger="operator_override", fallback=False)
    return search(
        query,
        collection=collection,
        top_k=top_k,
        mode=mode,                # chunk-retrieval mode: hybrid|dense|sparse
        settings=s,
        **chunk_filters,
    )
