# Architecture Research — v2.5 PageIndex/OpenKB Integration

**Domain:** Knowledge Lake Framework (`klake`) — v2.5 "PageIndex Plugin Integration" into shipped v2.0
**Researched:** 2026-07-13
**Confidence:** HIGH (grounded in direct reads of the shipped v2.0 source; every integration point references a real file/function)

## Scope

This document answers: *How do PageIndex tree indexing, OpenKB wiki compilation, and two-stage query routing integrate with the existing Knowledge Lake architecture?*

Specifically:
1. Where does tree index generation fit in the asset DAG?
2. How to store tree indexes (new artifact type? silver zone JSON?)
3. New plugin protocols needed (IndexerPlugin? RetrieverPlugin?)
4. Two-stage search: document-level Qdrant -> per-doc tree search
5. OpenKB as a new export format
6. Query router dispatch mechanism
7. New Dagster assets/resources needed

## Existing Architecture (v2.0 baseline)

```
Typer CLI (cli/app.py)  ─┐
FastAPI (api/app.py)     ─┼─►  pipeline/*.py service functions  ─►  plugins (resolver-keyed)  ─►  Postgres registry + S3 + Qdrant
Dagster assets           ─┘        (ingest/parse/clean/chunk/            (parsers/crawlers/
MCP server (agent/)               enrich/curate/index/search/           embedders/vectorstore/
                                   export/datasets)                      storage/discovery)
```

**Asset DAG (current):**
```
ingest_raw_document → parsed_document → clean_document → ┬─ chunk_document → embed_chunks → index_chunks
                                                          ├─ enrich_document
                                                          └─ curate_document_asset
```

**Key facts from code reads:**
- `Artifact.artifact_type` discriminator values: `raw_document`, `parsed_document`, `cleaned_document`, `chunk`, `enriched_document`, `curated_document`, `bronze_document`
- `ids.py._PREFIX` maps entity kinds to short prefixes (`doc_`, `chk_`, `art_`, etc.)
- Silver zone stores parsed markdown: `silver/{domain}/{source_id}/{hash}.md`
- Chunks stored separately: `chunks/{domain}/{source_id}/{hash}.txt`
- Gold zone: `gold/{domain}/{rag_corpus|pretrain|finetune}/{id}.{parquet|jsonl}`
- Plugin swap via entry-point groups: `knowledge_lake.{parsers|embedders|vectorstores|crawlers|discovery}`
- Three thin adapters (CLI/API/Dagster) + MCP server all call `pipeline/*.py` directly (D-02 invariant)
- `ParsedDoc` carries full text + sections with heading/section_path/page/text/is_table
- `VectorPoint` has id, vector, payload, sparse (optional)
- Registry: self-referencing `parent_artifact_id` chain for lineage

## Recommended Architecture

### 1. Tree Index Generation — Placement in the Asset DAG

**Decision: Parallel to chunk_document, off clean_document (same fan-out pattern)**

The tree index is a *structural representation* of a document — it captures the hierarchical section/subsection/paragraph topology. This is fundamentally different from chunking (which fragments text for embedding) and from enrichment (which adds LLM-judged metadata). The tree index preserves document structure for reasoning traversal.

**Why parallel to chunk, not after it:**
- Tree indexes need the full document structure (`ParsedDoc` with sections), which is available from `clean_document` (forwarded as `parsed_doc` in-memory)
- Tree indexes do NOT depend on chunks — they are an alternative representation
- Chunking destroys structure (splits by token count); tree indexing preserves it
- The fan-out pattern already proven: `clean_document → {chunk_document, enrich_document, curate_document_asset}` — adding `build_tree_index` is architecturally identical

**New asset DAG:**
```
ingest_raw_document → parsed_document → clean_document → ┬─ chunk_document → embed_chunks → index_chunks
                                                          ├─ enrich_document
                                                          ├─ curate_document_asset
                                                          └─ build_tree_index (NEW)
```

**Implementation point:** `dagster_defs/assets.py` — add a new `@asset` with `clean_document` as its dependency (same pattern as `curate_document_asset` at line 638). The asset calls a new `pipeline/tree_index.py:build_tree_index()` function (D-02: logic in pipeline, asset is thin wrapper).

### 2. Tree Index Storage — New Artifact Type in Silver Zone

**Decision: New artifact_type `tree_index`, stored as JSON in `silver/{domain}/{source_id}/{hash}_tree.json`**

**Why a new artifact_type (not a metadata JSON blob):**
- Tree indexes have their own lineage: `parsed_document → tree_index` (parent chain)
- They have their own content hash (tree structure changes when doc is re-parsed)
- They are queryable by type (`list_artifacts_by_type(session, "tree_index")`)
- They follow the existing pattern: every distinct representation gets its own artifact_type

**Schema changes needed:**
- Add `"tree_index": "idx"` to `ids.py._PREFIX` (new prefix for tree index artifacts)
- Add `create_tree_index_artifact()` to `registry/repo.py` (follows `create_chunk_artifact` pattern)
- No Alembic migration needed — `Artifact.artifact_type` is a plain `String(64)`, not an enum

**Storage format (silver zone JSON):**
```json
{
  "version": "1.0",
  "document_id": "doc_<parsed_artifact_id>",
  "source_id": "src_...",
  "root": {
    "id": "node_0",
    "type": "document",
    "title": "Document Title",
    "summary": "",
    "children": [
      {
        "id": "node_1",
        "type": "section",
        "heading": "Introduction",
        "section_path": "section-1",
        "page": 1,
        "content": "Section text...",
        "summary": "",
        "children": [...]
      }
    ]
  }
}
```

**Why silver zone (not gold):** The tree index is a processed, structured derivative of the parsed document — it lives at the same data maturity level as parsed markdown and enrichment JSON. Gold zone is for export-ready datasets. The tree index is an internal retrieval artifact, not an export.

**S3 key pattern:** `silver/{domain}/{source_id}/{content_hash}_tree.json` — mirrors existing silver zone conventions. Object tags: `{domain, source_name, format: "json", artifact_type: "tree_index"}`.

### 3. New Plugin Protocols — IndexerPlugin and RetrieverPlugin

**Decision: Add two new plugin protocols — `IndexerPlugin` for tree index construction and `RetrieverPlugin` for tree-based search**

The existing protocol hierarchy has 5 plugins: ParserPlugin, EmbedderPlugin, VectorStorePlugin, DiscoveryPlugin, CrawlerPlugin. Each owns a distinct capability that is swappable. Tree indexing introduces two new swappable capabilities:

#### IndexerPlugin (tree index construction)

```python
@runtime_checkable
class IndexerPlugin(Protocol):
    """Protocol for building tree indexes from parsed documents."""

    name: str

    def build_index(self, parsed_doc: ParsedDoc, metadata: dict[str, Any]) -> dict[str, Any]:
        """Build a tree index from a parsed document.

        Args:
            parsed_doc: ParsedDoc with sections (from parse stage).
            metadata: Document-level metadata (source_id, enrichment, etc.).

        Returns:
            Tree index as a JSON-serializable dict (the tree structure).
        """
        ...
```

**Why a plugin (not hardcoded):**
- PageIndex is the first implementation, but other tree index strategies exist (RAPTOR, hierarchical clustering, knowledge graphs)
- The framework constraint is tool-agnosticism: any processor must be swappable
- Entry-point group: `knowledge_lake.indexers`
- Settings swap key: `Settings.indexer = "pageindex"` (default)
- Built-in: `plugins/builtin/pageindex_indexer.py:PageIndexBuilder`

#### RetrieverPlugin (tree-based search)

```python
@runtime_checkable
class RetrieverPlugin(Protocol):
    """Protocol for searching within a tree index."""

    name: str

    def search(
        self,
        tree_index: dict[str, Any],
        query: str,
        *,
        top_k: int = 5,
        mode: str = "reasoning",
    ) -> list[TreeHit]:
        """Search within a tree index for relevant nodes.

        Args:
            tree_index: The tree structure (loaded from silver zone JSON).
            query: Natural-language query string.
            top_k: Maximum number of leaf nodes to return.
            mode: Search mode ("reasoning" for LLM-guided traversal,
                  "keyword" for section-heading match).

        Returns:
            List of TreeHit results with node path + content + score.
        """
        ...
```

**Why separate from VectorStorePlugin:**
- Tree search is fundamentally different from ANN vector search
- It may or may not use embeddings (PageIndex uses LLM-guided traversal)
- The search input is a loaded JSON tree, not a vector collection
- Different implementations: LLM-guided (strong_model), embedding-based top-down, keyword matching

**New data structures:**
```python
@dataclass
class TreeHit:
    """A single result from tree-based retrieval."""
    node_id: str
    node_path: list[str]  # e.g. ["Document", "Section 3", "Subsection 3.2"]
    content: str
    score: float
    page: int | None = None
    section_path: str = ""
```

### 4. Two-Stage Search Architecture

**Decision: Document-level Qdrant selection (stage 1) then per-document tree search (stage 2), orchestrated by a new `pipeline/tree_search.py`**

**How it works:**
1. **Stage 1 — Document shortlist (Qdrant):** Use the existing `pipeline/search.py:search()` with expanded top_k and group results by `document` (parsed_artifact_id from payload). This identifies which documents are relevant. The grouping leverages the existing `payload["document"]` field already indexed on every chunk.
2. **Stage 2 — Tree traversal (per shortlisted doc):** For each shortlisted document, load its `tree_index` artifact from silver zone, then invoke `RetrieverPlugin.search(tree_index, query)` to find the precise relevant nodes within that document.

**New pipeline function: `pipeline/tree_search.py`**
```python
def tree_search(
    query: str,
    *,
    collection: str = "klake_chunks",
    shortlist_k: int = 20,
    top_k: int = 5,
    max_docs: int = 3,
    mode: str = "reasoning",
    settings: Settings | None = None,
) -> list[TreeSearchResult]:
    """Two-stage retrieval: Qdrant doc selection -> tree search for precision.

    Stage 1: search() with shortlist_k, group by document, take top max_docs
    Stage 2: For each doc, load tree_index, run RetrieverPlugin.search()
    Merge and rank stage 2 results, return top_k
    """
```

**Why this architecture (not tree search alone):**
- Tree search is expensive per document (LLM calls for reasoning mode) — you cannot traverse every indexed document
- Qdrant is cheap and fast for narrowing to relevant documents (BM25+dense hybrid)
- The combination gets you: recall from vector search + precision from structural reasoning
- Existing `search()` is reused unchanged (stage 1 is just a call with higher top_k)

**Integration with existing search:**
- `pipeline/search.py:search()` remains the chunk-level search (unchanged)
- `pipeline/tree_search.py:tree_search()` is the two-stage alternative
- Both return results with citation fields (chunk_id/node_path, section_path, page)
- The query router (section 6) decides which path to use

**Key implementation detail:** The Qdrant shortlist groups by `payload["document"]` (parsed_artifact_id). This field is already present on every indexed point (index.py line 153). To get document-level scores, aggregate chunk scores per document (max or mean). Then for each top-doc, look up the tree_index artifact via `registry_repo.get_child_artifact_by_type(session, parsed_id, "tree_index")`.

### 5. OpenKB as a New Export Format

**Decision: New export function `pipeline/export.py:export_openkb()`, writing interlinked wiki JSON to gold zone alongside existing Parquet/JSONL exports**

**What OpenKB produces:** A compiled knowledge base — a set of interlinked wiki pages derived from the ingested documents. Each page corresponds to a topic/entity/concept extracted during enrichment, with cross-references forming a graph.

**Where it fits:**
- It is an **export** (gold zone output), not a pipeline intermediate
- It builds on enriched_document metadata (entities, keywords, summaries) and tree indexes
- Pattern: same as `export_rag_corpus()` / `export_pretrain_corpus()` — query registry, build output, write to gold zone

**Gold zone key:** `gold/{domain}/openkb/{export_id}/` (directory with `index.json` + per-page JSON files)

**Structure:**
```json
// index.json
{
  "version": "1.0",
  "domain": "healthcare",
  "page_count": 42,
  "pages": [
    {"id": "page_001", "title": "HIPAA Administrative Safeguards", "file": "page_001.json"}
  ],
  "links": [
    {"from": "page_001", "to": "page_003", "relation": "references"}
  ]
}

// page_001.json
{
  "id": "page_001",
  "title": "HIPAA Administrative Safeguards",
  "content_markdown": "...",
  "source_documents": ["doc_...", "doc_..."],
  "entities": [...],
  "outgoing_links": [{"target": "page_003", "anchor_text": "...", "relation": "references"}]
}
```

**Implementation pattern (mirrors existing exports):**
```python
def export_openkb(
    *,
    domain: str | None = None,
    settings: Settings | None = None,
) -> dict:
    """Export an interlinked wiki knowledge base to the gold zone.

    Builds wiki pages from enriched documents' entities/summaries/keywords,
    cross-links them by shared entities, and writes a navigable JSON structure.
    """
```

**New Dagster asset:** `export_openkb` (in the `export` group, same pattern as `export_rag_corpus`).

**CLI/API surface:** `klake export openkb [--domain healthcare]`, `POST /export/openkb`.

**Key difference from Parquet/JSONL:** OpenKB is multi-file (index + pages), but still written to S3 as individual objects under a shared prefix — `StorageBackend.put_object()` handles each file. The `Dataset` registry row tracks the index URI.

### 6. Query Router Dispatch Mechanism

**Decision: Config-driven with query-analysis override — a new `pipeline/route.py` module**

The query router decides whether a query should use:
- **Chunk search** (`pipeline/search.py`) — fast, good for factoid questions
- **Tree search** (`pipeline/tree_search.py`) — precise, good for reasoning/multi-hop questions
- **Both** (merge results) — when uncertain

**Architecture:**
```python
class RouteDecision(Enum):
    CHUNK = "chunk"
    TREE = "tree"
    BOTH = "both"

class QueryRouter:
    """Routes queries to the appropriate retrieval path."""

    def __init__(self, settings: Settings):
        self.default_mode = settings.retrieval.default_route  # config-driven default
        self.analysis_enabled = settings.retrieval.route_analysis  # LLM analysis toggle

    def route(self, query: str) -> RouteDecision:
        """Determine the retrieval path for a query.

        Priority:
        1. If route_analysis is enabled and query matches heuristic triggers
           for tree search (multi-hop, "how does X relate to Y", structural),
           return TREE.
        2. Otherwise, return the configured default_mode.
        """
```

**Two-layer dispatch (config + query analysis):**

1. **Config layer (always active):** `Settings.retrieval.default_route` = `"chunk"` | `"tree"` | `"both"` | `"auto"`. Defaults to `"auto"`. When set to a specific mode, it always uses that mode (operator override).

2. **Query analysis layer (when `default_route="auto"`):** Lightweight heuristic classification (regex-based, deterministic-first per project constraints):
   - Structural indicators: "how is X organized", "what sections cover", "outline of"
   - Multi-hop indicators: "relationship between", "how does X affect Y", "trace the path"
   - Factoid indicators: "what is", "define", "when was"

   If heuristics are inconclusive and `route_analysis=True`, use a cheap LLM call (via `cheap_model` alias) to classify. Cache by query hash.

**New settings model:**
```python
class RetrievalSettings(BaseModel):
    default_route: Literal["chunk", "tree", "both", "auto"] = "auto"
    route_analysis: bool = False  # LLM-assisted routing (costs money)
    tree_shortlist_k: int = 20
    tree_max_docs: int = 3
    tree_mode: str = "reasoning"
```

**Integration with existing search surface:**
- `pipeline/search.py:search()` unchanged (chunk path)
- New `pipeline/route.py:routed_search()` — the unified entry point that routes and merges
- CLI: `klake search` gains `--route chunk|tree|both|auto`
- API: `/search` gains `route` query param
- MCP: `search` tool gains `route` parameter

### 7. New Dagster Assets and Resources

**New assets (all in `dagster_defs/assets.py`, following existing patterns):**

| Asset | Group | Depends On | Calls | RetryPolicy |
|-------|-------|-----------|-------|-------------|
| `build_tree_index` | `pipeline` | `clean_document` | `pipeline.tree_index.build_tree_index()` | `_PIPELINE_RETRY` |
| `export_openkb` | `export` | (standalone, like other exports) | `pipeline.export.export_openkb()` | `_EXPORT_RETRY` |

**No new resources needed.** Tree index generation may optionally use LiteLLM (for summary generation at tree nodes), which is already available as `LiteLLMResource`. Tree storage uses MinIO (already `MinIOResource`). Tree search uses LiteLLM for reasoning traversal (already available). No new external service is introduced.

**New Dagster sensor (optional, later):** A tree index rebuild sensor that triggers `build_tree_index` when a document's parsed content changes. But for v2.5 MVP, tree indexes are built as part of the standard pipeline flow (the asset dependency on `clean_document` handles this automatically).

## Data Flow — What Changes

### New pipeline path (tree index):
```
clean_document → build_tree_index → store tree JSON in silver zone
                                   → register tree_index artifact in Postgres
```

### New search path (two-stage):
```
query → router → TREE path:
                   ├─ search() [stage 1: Qdrant shortlist, group by doc]
                   ├─ load tree_index artifacts for top docs [registry + S3]
                   └─ RetrieverPlugin.search() per doc [stage 2: tree traversal]
                 → CHUNK path:
                   └─ search() [existing, unchanged]
                 → BOTH path:
                   └─ merge TREE + CHUNK results, deduplicate, re-rank
```

### New export path (OpenKB):
```
enriched_documents + tree_indexes → compile wiki pages → cross-link by entities → write to gold zone
```

## Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| `pipeline/tree_index.py` (NEW) | Build tree index from ParsedDoc; register artifact | `plugins/resolver` (IndexerPlugin), `registry/repo`, `storage/s3` |
| `pipeline/tree_search.py` (NEW) | Two-stage search orchestration | `pipeline/search` (stage 1), `plugins/resolver` (RetrieverPlugin), `registry/repo`, `storage/s3` |
| `pipeline/route.py` (NEW) | Query routing decision | `pipeline/search`, `pipeline/tree_search`, `config/settings` |
| `pipeline/export.py` (MODIFIED) | Add `export_openkb()` | `registry/repo`, `storage/s3` |
| `plugins/protocols.py` (MODIFIED) | Add `IndexerPlugin`, `RetrieverPlugin`, `TreeHit` | (protocol definitions only) |
| `plugins/resolver.py` (MODIFIED) | Add `get_indexer()`, `get_retriever()` | `config/settings`, entry-points |
| `plugins/builtin/pageindex_indexer.py` (NEW) | PageIndex tree index builder | `plugins/protocols` |
| `plugins/builtin/pageindex_retriever.py` (NEW) | PageIndex tree search (LLM-guided) | `plugins/protocols`, LiteLLM |
| `config/settings.py` (MODIFIED) | Add `RetrievalSettings`, `indexer`/`retriever` swap keys | (configuration only) |
| `dagster_defs/assets.py` (MODIFIED) | Add `build_tree_index` asset | `pipeline/tree_index` |
| `ids.py` (MODIFIED) | Add `"tree_index": "idx"` prefix | (ID generation only) |
| `cli/app.py` (MODIFIED) | Add `--route` to search, `export openkb` | `pipeline/route`, `pipeline/export` |
| `api/app.py` (MODIFIED) | Add `route` param to search, `/export/openkb` | `pipeline/route`, `pipeline/export` |
| `agent/registry.py` (MODIFIED) | Add `route` param to search tool, `export_openkb` tool | `pipeline/route`, `pipeline/export` |

## Anti-Patterns to Avoid

### Anti-Pattern 1: Tree index depends on chunks
**Mistake:** Making `build_tree_index` depend on `chunk_document` output.
**Why wrong:** Tree indexing needs the full document structure (sections/hierarchy), which chunking destroys. They are alternative representations of the same source, not sequential.
**Instead:** Both branch from `clean_document` independently. Tree index uses `parsed_doc` (the in-memory ParsedDoc forwarded through clean).

### Anti-Pattern 2: Loading all tree indexes into memory for search
**Mistake:** Loading every document's tree index at query time.
**Why wrong:** At scale (1000+ documents), loading all trees for every query is O(N) in memory and I/O.
**Instead:** Stage 1 (Qdrant) narrows to max_docs (default 3) documents FIRST. Only those trees are loaded.

### Anti-Pattern 3: Making tree search the only search path
**Mistake:** Replacing chunk-based search with tree search entirely.
**Why wrong:** Tree search is slower (LLM calls), more expensive, and not better for simple factoid queries. Chunk search is fast and sufficient for most queries.
**Instead:** Router dispatches; chunk search remains the default for simple queries.

### Anti-Pattern 4: Storing tree indexes as Artifact.metadata_ JSON
**Mistake:** Putting the tree structure in the artifact's `metadata_` JSONB column.
**Why wrong:** Tree indexes can be large (hundreds of KB for complex documents). `metadata_` is for lightweight fields. Large blobs belong in S3 with only the URI in the registry.
**Instead:** Store in silver zone S3 (content-addressed JSON), register as an artifact with `storage_uri` pointing at the file.

### Anti-Pattern 5: Tight coupling between IndexerPlugin and RetrieverPlugin
**Mistake:** Making the retriever assume a specific tree format (e.g., PageIndex's exact schema).
**Why wrong:** If someone swaps the indexer (e.g., RAPTOR instead of PageIndex), the retriever breaks.
**Instead:** Define a minimal tree schema contract (nodes with id/type/content/children) that both protocols agree on. The indexer produces it; the retriever consumes it.

### Anti-Pattern 6: OpenKB export running LLM calls at export time
**Mistake:** Having `export_openkb()` call the LLM to generate wiki content.
**Why wrong:** Exports should be fast, deterministic, and cheap. LLM calls are slow and non-deterministic.
**Instead:** OpenKB compiles from existing enrichment (summaries, entities, keywords) and tree index structure. All LLM work was done during enrich/tree-build; export just assembles and links.

## Patterns to Follow

### Pattern 1: Fan-out from clean_document
**What:** Multiple independent asset branches from the same dependency.
**Already proven by:** `chunk_document`, `enrich_document`, `curate_document_asset` all depend on `clean_document` independently (dagster_defs/assets.py).
**Apply to:** `build_tree_index` — same pattern, same dependency, same in-memory `parsed_doc` forwarding.

### Pattern 2: Content-addressed artifact with S3 storage
**What:** Hash the content, check for existing artifact, store in S3, register with `storage_uri`.
**Already proven by:** `pipeline/chunk.py:chunk()` lines 310-350 (hash input, check `get_artifact_by_hash`, `put_object`, `create_chunk_artifact`).
**Apply to:** Tree index storage — hash the serialized tree JSON, check dedup, store in silver zone.

### Pattern 3: Plugin via entry-point group
**What:** Define a Protocol, register built-in(s) via `pyproject.toml` entry-points, resolve via `resolver.py`.
**Already proven by:** All 5 existing plugin types (parsers, embedders, vectorstores, crawlers, discovery).
**Apply to:** `knowledge_lake.indexers` and `knowledge_lake.retrievers` — two new entry-point groups.

### Pattern 4: Pipeline function called by multiple adapters
**What:** Business logic in `pipeline/*.py`, thin shim in CLI/API/Dagster/MCP.
**Already proven by:** Every existing pipeline stage. `search()` is called by CLI (`cmd_search`), API (`/search`), MCP (`search` tool), and potentially Dagster.
**Apply to:** `tree_search()`, `routed_search()`, `export_openkb()` — all go in `pipeline/`, all adapters call them directly.

### Pattern 5: Additive defaults for back-compatibility
**What:** New kwargs default to today's behavior. New artifact types do not require migration.
**Already proven by:** `VectorPoint.sparse = None`, `search(mode="dense")`, `Settings.search.mode = "hybrid"` — all additive.
**Apply to:** `Settings.retrieval.default_route = "auto"` (existing `search()` callers unaffected), `search` tool gains optional `route` param.

## Scalability Considerations

| Concern | At 100 docs | At 10K docs | At 100K docs |
|---------|-------------|-------------|-------------|
| Tree index storage | ~100 JSON files in S3 (~50KB each = 5MB total) | ~10K files (~500MB) | ~100K files (~5GB) — consider batch builds |
| Stage 1 shortlist | Qdrant handles easily | Standard Qdrant scale | May need collection sharding |
| Stage 2 tree traversal | 3 trees loaded per query (~150KB) | Same (only top-3 loaded) | Same (Qdrant shortlist keeps it bounded) |
| OpenKB compilation | Fast (100 pages) | Minutes (entity graph resolution) | Needs incremental builds |
| Tree index build (LLM) | Budget-gated by LLM spend cap | Expensive — consider heuristic-only mode | Must have non-LLM fallback |

## Integration Points Summary

| Feature | Primary file(s) to modify | New file(s) | Migration? |
|---------|---------------------------|-------------|------------|
| Tree index generation | `dagster_defs/assets.py`, `ids.py`, `registry/repo.py` | `pipeline/tree_index.py`, `plugins/builtin/pageindex_indexer.py` | No (artifact_type is free-form string) |
| Tree index storage | `storage/s3.py` (no change — uses existing put_object) | — | No |
| IndexerPlugin protocol | `plugins/protocols.py`, `plugins/resolver.py` | — | No (new entry-point group in pyproject.toml) |
| RetrieverPlugin protocol | `plugins/protocols.py`, `plugins/resolver.py` | `plugins/builtin/pageindex_retriever.py` | No |
| Two-stage search | `pipeline/search.py` (unchanged) | `pipeline/tree_search.py` | No |
| Query router | `cli/app.py`, `api/app.py`, `agent/registry.py` | `pipeline/route.py` | No |
| OpenKB export | `pipeline/export.py` | — (added to existing file) | No |
| Settings | `config/settings.py` | — | No |
| Dagster assets | `dagster_defs/assets.py` | — | No |

**Zero Alembic migrations needed.** All new capabilities use existing schema flexibility (free-form `artifact_type`, `metadata_` JSON, `storage_uri`). The `tree_index` artifact type is just a new string value in the existing artifacts table.

## Dependency-Aware Build Order

```
Phase 1 — Tree Index Foundation (lowest risk, enables everything else)
  1. IndexerPlugin protocol + resolver + entry-point group
  2. pipeline/tree_index.py (build_tree_index function)
  3. PageIndex built-in indexer (plugins/builtin/pageindex_indexer.py)
  4. Dagster build_tree_index asset
  5. CLI: klake build-tree-index <document_id>
     Rationale: tree indexes must exist before tree search can work.

Phase 2 — Tree Retrieval (depends on Phase 1)
  6. RetrieverPlugin protocol + resolver + entry-point group
  7. pipeline/tree_search.py (two-stage search function)
  8. PageIndex built-in retriever (plugins/builtin/pageindex_retriever.py)
  9. CLI/API/MCP: tree-search surface
     Rationale: need tree indexes to search against.

Phase 3 — Query Router (depends on Phase 2)
 10. RetrievalSettings in config/settings.py
 11. pipeline/route.py (router logic)
 12. Integrate router into search surfaces (CLI --route, API ?route, MCP route param)
     Rationale: router dispatches to tree_search() which must already exist.

Phase 4 — OpenKB Export (partially independent, needs enrichment + tree indexes)
 13. export_openkb() in pipeline/export.py
 14. Dagster export_openkb asset
 15. CLI/API surface: klake export openkb
     Rationale: wiki compilation needs enriched entity data + tree structure.
     Can start in parallel with Phase 2 if tree index artifact is stored.

Phase 5 — Documentation & Integration Testing
 16. Architecture documentation (docs/)
 17. Integration tests: full pipeline with tree index + two-stage search
 18. Performance benchmarks: tree search latency vs chunk search
```

**Why this order:**
- **Phase 1 before 2:** Cannot search trees that do not exist
- **Phase 2 before 3:** Router dispatches to tree_search which must be implemented
- **Phase 4 after 1:** OpenKB needs tree indexes but not tree search (it reads the stored trees)
- **Phase 3 after 2:** Router is thin glue — build the things it routes to first

## Sources

- Direct reads of shipped v2.0 source (2026-07-13): `pipeline/{search,index,chunk,export,run}.py`, `plugins/{protocols,resolver}.py`, `dagster_defs/assets.py`, `registry/{models,repo}.py`, `config/settings.py`, `ids.py`, `lineage.py` — HIGH confidence (primary artifacts).
- PROJECT.md v2.5 milestone requirements — HIGH confidence (project specification).
- Existing v2.0 ARCHITECTURE.md research (`.planning/research/ARCHITECTURE.md`) — HIGH confidence (verified patterns).
- PageIndex/tree-based retrieval concepts (LlamaIndex tree index, RAPTOR, hierarchical retrieval) — MEDIUM confidence (training data, not verified against specific library versions).
- OpenKB compiled knowledge base pattern (wiki compilation from structured sources) — MEDIUM confidence (concept-level, implementation is custom to this project).

---
*Architecture research for: Knowledge Lake Framework v2.5 PageIndex/OpenKB integration*
*Researched: 2026-07-13*
