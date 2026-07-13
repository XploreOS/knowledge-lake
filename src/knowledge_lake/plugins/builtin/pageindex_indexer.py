"""Built-in IndexerPlugin: deterministic section-tree construction (D-04/D-05).

Builds a TreeIndex directly from ParsedDoc.sections — no re-parse, no
pageindex==0.3.0.dev3 import this phase (RESEARCH.md Open Question 1).

The actual ``pageindex`` pre-release library is NOT imported here. It is flagged
[SUS] (pre-release, no stable API) and its build-from-PDF approach conflicts with
D-03 (parse-once, transform downstream). This implementation satisfies the
IndexerPlugin seam by using the deterministic tree builder from the pipeline layer.

LiteLLM URL and API key are injected via the constructor so no os.environ read
happens in this module (CR-03). Satisfies IndexerPlugin Protocol (runtime_checkable).

Entry-point registration:
    [project.entry-points."knowledge_lake.indexers"]
    pageindex = "knowledge_lake.plugins.builtin.pageindex_indexer:PageIndexIndexer"
"""
from __future__ import annotations

from typing import Any

from knowledge_lake.plugins.protocols import IndexerPlugin, ParsedDoc, TreeIndex


class PageIndexIndexer:
    """Built-in IndexerPlugin using deterministic section-tree construction (D-04/D-05).

    Builds a tree directly from ParsedDoc.sections — no re-parse, no
    pageindex==0.3.0.dev3 import this phase (RESEARCH.md Open Question 1).
    LiteLLM URL injected via constructor (CR-03).
    Satisfies IndexerPlugin Protocol (runtime_checkable).

    Protocol attributes:
        name = 'pageindex'
    """

    name: str = "pageindex"

    def __init__(
        self,
        litellm_url: str = "http://localhost:4000",
        litellm_api_key: str = "sk-local-noauth",
    ) -> None:
        # Proxy base URL — injected by the resolver from Settings.litellm_url (CR-03).
        # Reserved for future LLM-summary mode (D-09). Not used in deterministic mode.
        self._litellm_url: str = litellm_url
        self._litellm_api_key: str = litellm_api_key

    def build_index(
        self,
        parsed_doc: ParsedDoc,
        *,
        mode: str = "deterministic",
        metadata: dict[str, Any] | None = None,
    ) -> TreeIndex:
        """Build a TreeIndex from parsed_doc.sections.

        Imports ``_build_deterministic_tree`` from the pipeline layer via a deferred
        import to avoid circular-import issues at class-definition time (mirrors the
        lazy-import pattern in st_embedder.py and enrich.py).

        For deterministic mode the summary of each node equals the section heading
        (same as the pipeline-layer builder). LLM summarisation is deferred to a
        future plan once the pageindex library situation is resolved (Open Q#1).

        Args:
            parsed_doc: Parsed document with sections and metadata.
            mode:       Build mode — "deterministic" (default) or "llm" (future).
            metadata:   Optional metadata dict; may contain "parsed_artifact_id"
                        and "source_id" keys for constructing the TreeIndex.

        Returns:
            A TreeIndex with roots derived from parsed_doc.sections.
        """
        # Deferred import to avoid circular dependency at module load time
        from knowledge_lake.pipeline.tree_index import _build_deterministic_tree

        meta = metadata or {}
        page_count: int = int(parsed_doc.metadata.get("page_count", 1))
        roots = _build_deterministic_tree(parsed_doc.sections, page_count)

        return TreeIndex(
            parsed_artifact_id=meta.get("parsed_artifact_id", ""),
            source_id=meta.get("source_id", ""),
            roots=roots,
            mode=mode,
            schema_version="1",
            content_hash="",
        )
