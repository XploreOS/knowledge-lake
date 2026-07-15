"""Tree search stage: two-stage orchestrator combining Qdrant shortlist +
per-document PageIndex tree traversal (RETR-04/07/08, D-08..D-11).

Stage 1 (D-08): reuse pipeline.search.search() UNCHANGED to get a chunk-level
shortlist, then group hits by payload["document"] (keeping the max score per
document) and take the top settings.tree_search.max_docs candidates. This
keeps the Phase-15 router's chunk path byte-identical.

Stage 2 (D-09): for each shortlisted document, resolve its tree_index
artifact via registry.repo.get_child_artifact_by_type(). A document with no
tree_index artifact is skipped gracefully — a missing tree never fails the
query.

Parallel load (D-10, RETR-07): candidate tree JSON blobs are loaded
concurrently via asyncio.Semaphore + run_in_executor, driven by exactly one
top-level event-loop entry point inside this sync module (CR-02: never nest
that entry point — a future async caller, e.g. the Phase-15 router, should
await _load_all() directly instead of calling tree_search() from within a
running loop).

Deserialize + dispatch (D-11): loaded JSON bytes are parsed with orjson and
rebuilt into TreeIndex/TreeNode via _dict_to_tree_index/_dict_to_tree — the
exact inverse of tree_index.py's _tree_to_dict + tree_dict wrapper. Each
resolved TreeIndex is handed to the resolved RetrieverPlugin
(plugins/resolver.get_retriever) which returns page-level Hits
(citation_source="tree").

The final result is the cross-document merge of all per-tree Hits, sorted
deterministically and truncated to the effective top_k.
"""

from __future__ import annotations

import asyncio
from typing import Any

import orjson
import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.pipeline.search import search
from knowledge_lake.pipeline.utils import uri_to_key
from knowledge_lake.plugins.protocols import Hit, TreeIndex, TreeNode
from knowledge_lake.plugins.resolver import get_retriever
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.storage.s3 import StorageBackend

log = structlog.get_logger(__name__)

# Per-key timeout (seconds) for the storage.get_object() call in _load_all's
# executor offload. Bounds a single hung backend call so it degrades that one
# document to None instead of blocking the whole batch forever (WR-06).
_TREE_LOAD_TIMEOUT_SECONDS = 30.0


# ── Deserialization (D-11, inverse of tree_index.py:_tree_to_dict) ───────────


def _dict_to_tree(d: dict[str, Any]) -> TreeNode:
    """Recursively rebuild a TreeNode from its serialized dict form.

    Exact inverse of tree_index.py:_tree_to_dict — reads fields explicitly
    (never **spread) so malformed/oversized JSON cannot inject unexpected
    attributes (T-14-10, ASVS V5).
    """
    return TreeNode(
        node_id=d["node_id"],
        title=d["title"],
        summary=d["summary"],
        page_start=d["page_start"],
        page_end=d["page_end"],
        level=d["level"],
        section_path=d["section_path"],
        children=[_dict_to_tree(c) for c in d.get("children", [])],
    )


def _dict_to_tree_index(d: dict[str, Any]) -> TreeIndex:
    """Rebuild a TreeIndex from its serialized dict form (D-11).

    Exact inverse of tree_index.py's tree_dict wrapper (parsed_artifact_id,
    source_id, mode, schema_version, content_hash, roots).
    """
    return TreeIndex(
        parsed_artifact_id=d["parsed_artifact_id"],
        source_id=d["source_id"],
        roots=[_dict_to_tree(r) for r in d.get("roots", [])],
        mode=d.get("mode", "deterministic"),
        schema_version=d.get("schema_version", "1"),
        content_hash=d.get("content_hash", ""),
    )


# ── Parallel loader (D-10, RETR-07) ──────────────────────────────────────────


async def _load_all(
    keys: list[str],
    storage: StorageBackend,
    concurrency: int,
) -> list[bytes | None]:
    """Load *keys* from *storage* concurrently, bounded by an asyncio.Semaphore.

    Each key's blocking storage.get_object() call is offloaded to the default
    executor (mirrors crawl.py's run_in_executor precedent). A per-key
    failure is logged and represented as None in the result list — it never
    aborts the batch (D-09).

    Returns a list aligned with the input *keys* order.
    """
    semaphore = asyncio.Semaphore(concurrency)
    loop = asyncio.get_running_loop()

    async def _load_one(key: str) -> bytes | None:
        async with semaphore:
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(None, storage.get_object, key),
                    timeout=_TREE_LOAD_TIMEOUT_SECONDS,
                )
            except Exception as exc:  # noqa: BLE001 — never fail the batch on one load (D-09)
                log.warning("tree_search.tree_load_failed", key=key, error=str(exc))
                return None

    return await asyncio.gather(*(_load_one(key) for key in keys))


# ── Stage-1 shortlist (shared by tree_search() and tree_index_coverage()) ────


def _shortlist_documents(
    query: str,
    *,
    collection: str,
    max_docs: int,
    s: Settings,
) -> list[str]:
    """Stage-1 (D-08): chunk shortlist via search() UNCHANGED, grouped by
    payload["document"] (max score per document), truncated to *max_docs*.

    Factored out of tree_search() so tree_index_coverage() (KL-09) can run
    the exact same candidate-selection logic when diagnosing an empty
    tree_search() result, without duplicating the grouping/sort behavior.
    """
    chunk_hits = search(
        query,
        collection=collection,
        top_k=s.tree_search.shortlist_k,
        settings=s,
    )

    doc_scores: dict[str, float] = {}
    for hit in chunk_hits:
        doc_id = hit.payload.get("document")
        if not doc_id:
            continue
        if doc_id not in doc_scores or hit.score > doc_scores[doc_id]:
            doc_scores[doc_id] = hit.score

    return [
        doc_id
        for doc_id, _score in sorted(
            doc_scores.items(), key=lambda item: (-item[1], item[0])
        )[:max_docs]
    ]


# ── Two-stage orchestrator (RETR-04) ─────────────────────────────────────────


def tree_search(
    query: str,
    *,
    top_k: int | None = None,
    mode: str | None = None,
    max_docs: int | None = None,
    collection: str = "klake_chunks",
    settings: Settings | None = None,
) -> list[Hit]:
    """Two-stage tree retrieval: Qdrant shortlist -> per-document tree search.

    Args:
        query:      Natural-language search query.
        top_k:      Maximum number of Hits to return. Defaults to
                    settings.tree_search.top_k.
        mode:       Tree traversal mode override ('heuristic' | 'llm').
                    Defaults to settings.tree_search.mode.
        max_docs:   Maximum number of shortlisted documents to load/traverse.
                    Defaults to settings.tree_search.max_docs.
        collection: Qdrant collection used for the stage-1 chunk shortlist.
        settings:   Settings override.

    Returns:
        list[Hit] with citation_source="tree", merged across documents,
        sorted deterministically, and truncated to the effective top_k.

    Never raises on a missing tree_index artifact or a failed tree load
    (D-09) — a document simply contributes no Hits in that case.
    """
    s = settings or get_settings()
    effective_top_k = top_k if top_k is not None else s.tree_search.top_k
    effective_mode = mode if mode is not None else s.tree_search.mode
    effective_max_docs = max_docs if max_docs is not None else s.tree_search.max_docs

    if not query.strip():
        log.warning("tree_search.empty_query")
        return []

    # ── Stage 1 (D-08): chunk shortlist via search() UNCHANGED ────────────────
    top_docs = _shortlist_documents(
        query, collection=collection, max_docs=effective_max_docs, s=s
    )

    if not top_docs:
        log.info("tree_search.no_shortlist", query=query[:80])
        return []

    # ── Stage 2 resolution (D-09): resolve tree_index artifact per doc ────────
    resolved: list[tuple[str, str]] = []  # (parsed_id, storage_key)
    with get_session() as session:
        for parsed_id in top_docs:
            artifact = registry_repo.get_child_artifact_by_type(
                session, parsed_id, "tree_index"
            )
            if artifact is None:
                log.info("tree_search.no_tree_index", document=parsed_id)
                continue
            try:
                key = uri_to_key(artifact.storage_uri)
            except (ValueError, AttributeError) as exc:
                log.warning(
                    "tree_search.bad_storage_uri",
                    document=parsed_id,
                    storage_uri=artifact.storage_uri,
                    error=str(exc),
                )
                continue
            resolved.append((parsed_id, key))

    if not resolved:
        return []

    # ── Parallel load (D-10, RETR-07) ─────────────────────────────────────────
    storage = StorageBackend(s.storage)
    keys = [key for _parsed_id, key in resolved]
    # Single, non-nested event-loop entry point drives the batch — a future
    # async caller (e.g. the Phase-15 router) must await _load_all() directly
    # instead (CR-02, WR-03). Fail fast with a clear message rather than an
    # opaque asyncio RuntimeError if this is ever invoked from within a
    # running event loop.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "tree_search() cannot be called from within a running event loop; "
            "await _load_all() directly instead (see module docstring, CR-02)."
        )
    raw_blobs = asyncio.run(_load_all(keys, storage, s.tree_search.concurrency))

    # ── Deserialize + dispatch (D-11) ─────────────────────────────────────────
    retriever = get_retriever(s)
    results: list[Hit] = []
    for (parsed_id, _key), raw in zip(resolved, raw_blobs, strict=False):
        if raw is None:
            continue
        try:
            tree_dict = orjson.loads(raw)
            tree_index_obj = _dict_to_tree_index(tree_dict)
        except Exception as exc:  # noqa: BLE001 — malformed tree JSON must not fail the query (D-09)
            log.warning("tree_search.tree_parse_failed", document=parsed_id, error=str(exc))
            continue

        try:
            hits = retriever.search(
                tree_index_obj,
                query,
                top_k=effective_top_k,
                mode=effective_mode,
                settings=s,
            )
        except Exception as exc:  # noqa: BLE001 — a retriever plugin bug must not fail the query (D-09)
            log.warning("tree_search.retriever_failed", document=parsed_id, error=str(exc))
            continue
        results.extend(hits)

    # ── Merge (deterministic) ─────────────────────────────────────────────────
    results.sort(
        key=lambda h: (
            -h.score,
            h.payload.get("document", ""),
            h.payload.get("section_path", ""),
        )
    )
    return results[:effective_top_k]


# ── Empty-result diagnosis (KL-09) ───────────────────────────────────────────


def tree_index_coverage(
    query: str,
    *,
    collection: str = "klake_chunks",
    max_docs: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Diagnose why tree_search(query) might have returned no hits (KL-09).

    Runs the identical stage-1 shortlist tree_search() uses (via the shared
    ``_shortlist_documents`` helper) and reports whether any shortlisted
    document already has a tree_index artifact. Callers (the CLI) use this
    to tell "no tree index has been built yet for these documents" apart
    from "the tree search genuinely found nothing" — previously both cases
    printed the same ambiguous "No results for query" message.

    Never raises — mirrors tree_search()'s D-09 fail-open posture, since this
    is purely diagnostic and must not itself become a new failure mode.

    Returns:
        dict with keys:
          shortlisted   — number of documents in the stage-1 shortlist (0 if
                          the query matched no chunks at all)
          has_any_index — True if at least one shortlisted document has a
                          tree_index artifact
    """
    s = settings or get_settings()
    effective_max_docs = max_docs if max_docs is not None else s.tree_search.max_docs

    if not query.strip():
        return {"shortlisted": 0, "has_any_index": False}

    top_docs = _shortlist_documents(
        query, collection=collection, max_docs=effective_max_docs, s=s
    )
    if not top_docs:
        return {"shortlisted": 0, "has_any_index": False}

    has_any_index = False
    with get_session() as session:
        for parsed_id in top_docs:
            artifact = registry_repo.get_child_artifact_by_type(
                session, parsed_id, "tree_index"
            )
            if artifact is not None:
                has_any_index = True
                break

    return {"shortlisted": len(top_docs), "has_any_index": has_any_index}
