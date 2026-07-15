# Feature Landscape: v2.5 PageIndex Plugin Integration

**Domain:** Knowledge Lake Framework — tree-based retrieval, compiled knowledge bases, hybrid routing
**Researched:** 2026-07-13
**Overall confidence:** MEDIUM (cross-referenced multiple ecosystem implementations; VectifyAI/PageIndex is a real but young library; OpenKB is a custom concept without a direct OSS equivalent)

## Scope

This document maps the feature landscape for v2.5 ONLY: PageIndex tree indexing, two-stage retrieval, OpenKB compiled knowledge base export, query routing, and architectural documentation. All v2.0 features (MCP, hybrid BM25+dense, crawl scheduling, domain packs) are shipped and not re-scoped here.

---

## Ecosystem Context

### PageIndex (VectifyAI)

PageIndex is a **vectorless, reasoning-based RAG** system. It builds hierarchical tree structures from documents where each node has a title, page range (start_index/end_index), summary, and children. Retrieval uses LLM reasoning to traverse the tree top-down rather than vector similarity. The PyPI package (`pageindex` v0.2.8, pre-release 0.3.0.dev3) is very small (6KB wheel) and serves primarily as a thin SDK for their cloud service. The self-hosted version uses a CLI (`run_pageindex.py`) that generates tree JSON from PDFs/markdown.

Key architectural facts:
- Tree output is nested JSON: `{title, node_id, start_index, end_index, summary, nodes[]}`
- LLM generates the tree structure from document content (uses LiteLLM for provider flexibility)
- Markdown tree generation uses heading hierarchy (`#`/`##`/`###`) to determine levels
- PDF tree generation uses TOC detection + LLM segmentation
- Retrieval is agentic: LLM reasons about which branches to explore given a query
- Achieved 98.7% accuracy on FinanceBench (financial document QA)
- Configurable: `--max-pages-per-node` (default 10), `--max-tokens-per-node` (default 20000)

### RAPTOR (Academic Pattern)

RAPTOR (Recursive Abstractive Processing for Tree-Organized Retrieval) is the academic foundation for tree-based RAG. It builds trees **bottom-up**: chunk, embed, cluster similar chunks, summarize clusters with LLM to create parent nodes, recurse. Two retrieval strategies: (1) collapsed tree (flatten all levels, do similarity search across all), (2) tree traversal (start at root, select relevant children, descend). 20% accuracy improvement on QuALITY benchmark over flat RAG.

### LlamaIndex TreeIndex (Reference Implementation)

LlamaIndex provides a production TreeIndex with modes: select_leaf (top-down LLM traversal, O(log N)), select_leaf_embedding (embeddings for selection, cheaper), all_leaf (retrieve everything), tree_root (use root summary). RouterQueryEngine provides LLM/Pydantic selectors for multi-strategy routing.

### GraphRAG (Microsoft) — Closest OpenKB Analogue

GraphRAG extracts entities/relationships via LLM, builds knowledge graph, detects communities via Leiden clustering, generates hierarchical community summaries. Query modes: local (fan out from entity), global (community summaries), DRIFT (entity + community context), basic (vector fallback). This is the closest existing system to the "compiled knowledge base" concept.

### Query Routing Ecosystem

- **Semantic Router** (aurelio-labs): embedding similarity for sub-millisecond intent classification without LLM calls
- **LlamaIndex RouterQueryEngine**: LLM/Pydantic selectors choose between retrieval strategies based on tool descriptions
- **Adaptive-RAG** (NAACL 2024): trained classifier predicts query complexity, routes to no-retrieval/single-step/multi-step
- **Agentic RAG**: ReAct loops where agent reasons about which tool/backend to query

---

## Table Stakes

Features users expect. Missing = the v2.5 milestone fails to deliver its stated goal.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Tree index generation from parsed documents** | Entire milestone premise; no tree = no tree search | Med | Two modes: deterministic (heading hierarchy) and LLM-summarized (PageIndex-style). Output is silver-zone JSON matching PageIndex schema: `{title, node_id, start_index, end_index, summary, nodes[]}` |
| **Tree index as registered artifact** | Framework constraint: every artifact traceable | Low | New `artifact_type = "tree_index"`, parent = parsed_document, content_hash of JSON, stored in silver zone. Follows existing artifact pattern exactly. |
| **Two-stage retrieval pipeline** | Stated core requirement; the headline capability | High | Stage 1: existing Qdrant hybrid search narrows to top-N documents. Stage 2: load tree indexes for shortlisted docs, LLM reasons over tree structure to find relevant pages/sections. |
| **Query router (chunk vs tree dispatch)** | Without routing, every query hits the expensive tree path or misses it entirely | Med | Deterministic-first: regex/heuristic classifies query type before any LLM call (project constraint). LLM classification opt-in. Routes: "chunk" (existing), "tree" (new), "auto" (router decides). |
| **Plugin protocols for tree indexer + retriever** | Framework constraint: all external tools swappable | Low | Two new protocols: `TreeIndexerPlugin` (doc -> tree JSON) and `TreeRetrieverPlugin` (tree + query -> relevant nodes). Same pattern as existing `ParserPlugin`, `EmbedderPlugin`, etc. |
| **Settings model for retrieval config** | Operators need to configure: max_tree_depth, tree_search_mode, routing strategy | Low | Nested Pydantic model under Settings, same as existing SearchSettings. |
| **CLI/API/MCP surface integration** | Framework invariant: one registry, all surfaces | Low | Add `--route auto|chunk|tree` to search command. Add `klake tree-build` for manual tree generation. Expose through MCP tool registry. |
| **OpenKB compiled knowledge base export** | Stated milestone requirement; new export format | High | Generate interlinked wiki pages from enriched documents + tree structures. Each concept/entity becomes a page with cross-references. Stored in gold zone. |
| **Architectural documentation** | Stated milestone requirement | Med | System architecture covering full pipeline, new retrieval architecture, component boundaries, decision records. |

## Differentiators

Features that set the Knowledge Lake v2.5 apart from standard RAG systems.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Deterministic tree generation (no LLM)** | Most tree-RAG systems require LLM for tree building. A deterministic mode (heading hierarchy + text truncation for summaries) makes indexes reproducible, free, and fast. | Low | Use ParsedDoc.sections heading hierarchy directly; first N tokens of section text as "summary". Zero API cost. Falls back gracefully when LLM unavailable. |
| **LLM-guided tree traversal with reasoning traces** | Unlike flat RAG, produces explainable retrieval chains: "I selected section X because..." with full provenance. | High | Uses `cheap_model` alias through LiteLLM. Each traversal step logged with rationale. Differentiator over PageIndex cloud: fully traceable within lineage system. |
| **Corpus-level recall + document-level precision** | Two-stage gives vector search speed for corpus filtering AND structural reasoning for precision — the combination is rare in OSS. | Med | Architectural differentiator. Most systems do either flat RAG OR tree search, not both composed. |
| **Heuristic routing (no LLM cost per query)** | Semantic Router requires embedding model. LlamaIndex router requires LLM call. Deterministic-first heuristic routing is free and instant. | Low | Regex patterns: multi-hop indicators ("relationship between", "how does X affect Y"), structural queries ("what sections cover"), breadth queries ("summarize all"). Simple but effective. |
| **OpenKB wikilinks between concepts across documents** | Turns a document collection into navigable, interlinked knowledge — not just search results. | High | Entity extraction from enrichment metadata, cross-reference linking via exact + normalized match, concept page synthesis. Like GraphRAG communities but rendered as human-readable wiki. |
| **Tree index persistence with S3 lineage** | PageIndex cloud is ephemeral. Our tree indexes are persisted S3 artifacts with full lineage tracing, content hashing, and reproducibility. | Low | Direct benefit of existing framework architecture. Content-addressed, immutable, auditable. |
| **Mixed-mode retrieval within single query** | Router can invoke BOTH chunk and tree paths and merge results (RRF or LLM synthesis), not just one-or-the-other. | Med | Extension of existing RRF fusion pattern. When router confidence is low, try both and fuse. |

## Anti-Features

Features to explicitly NOT build in v2.5.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Automatic tree indexing of all existing documents** | ~500+ parsed docs at LLM summarization cost. Expensive, slow, not all benefit from tree search. | On-demand: build tree for new docs in pipeline; batch-build existing via explicit `klake tree-build --all` command. |
| **Always-on LLM routing** | Violates deterministic-first constraint. Adds latency + cost to EVERY search. | Heuristic regex routing by default; LLM routing opt-in via `settings.retrieval.route_mode = "llm"`. |
| **Replace chunk search entirely** | Simple factoid queries (70%+ of queries in most RAG systems) work fine with chunk search. Tree search adds unnecessary latency. | Both paths coexist; router dispatches. Chunk search remains default for unclassified queries. |
| **Graph database for tree/knowledge storage** | Adds Neo4j/etc. operational complexity. Trees are per-document, accessed one-at-a-time. | S3 JSON per tree (loaded on demand). For OpenKB cross-refs: PostgreSQL relation table or inline JSON links. |
| **Full GraphRAG entity extraction pipeline** | spaCy NER + relationship extraction + Leiden clustering is a massive scope expansion. | Use existing LLM enrichment metadata (entities already extracted per-doc). Cross-reference via normalized string matching on enriched fields. |
| **RAPTOR-style bottom-up clustering** | Requires re-embedding all chunks, running clustering algorithms, and LLM summarization per cluster. Heavy. Different approach from PageIndex. | Top-down tree generation (PageIndex-style) from document structure. Respects existing heading hierarchy from ParsedDoc. |
| **Real-time OpenKB incremental updates** | Wiki compilation is expensive (cross-document analysis). Real-time is overkill. | Batch export triggered manually or on schedule. Lint mode validates existing KB without regenerating. |
| **Unbounded LLM calls during tree traversal** | Deep trees can spiral costs. Each traversal step = 1 LLM call. | Cap at `max_traversal_depth` (configurable, default 4). Stop at leaf nodes. Budget enforcement via existing LlmSpend mechanism. |

---

## Feature Dependencies

```
[existing] ParsedDoc.sections (heading hierarchy)
    |
    v
TreeIndexerPlugin protocol ─────────────────────────────────────┐
    |                                                            |
    v                                                            |
tree_index pipeline function (build_tree)                        |
    |                                                            |
    ├── Dagster build_tree_index asset                           |
    |                                                            |
    v                                                            v
tree_index artifacts in S3 ──────────> OpenKB export (reads tree + enrichment)
    |
    v
TreeRetrieverPlugin protocol
    |
    v
tree_search pipeline function
    |
    v
[existing] search.py (stage 1 shortlist)
    |
    v
two_stage_search pipeline function (composes stages)
    |
    v
query_router (dispatches chunk vs tree vs both)
    |
    v
CLI/API/MCP surface integration (--route param)
```

Key ordering constraints:
1. TreeIndexerPlugin + tree generation MUST precede tree search (no tree = nothing to search)
2. tree_search MUST precede query router (router dispatches TO tree search)
3. OpenKB export requires BOTH tree indexes AND enriched documents (parallel to tree search, not sequential)
4. Documentation phase is independent — can run anytime after architecture stabilizes

## MVP Recommendation

### Prioritize (delivers core v2.5 value):

1. **TreeIndexerPlugin + deterministic tree generation** — Foundation. Generates tree JSON from ParsedDoc sections without LLM calls. Establishes artifact type, storage pattern, lineage. Unblocks everything else.
2. **LLM-assisted tree generation** — Upgrade: uses `cheap_model` to produce node summaries (like PageIndex). Makes tree search more effective.
3. **TreeRetrieverPlugin + tree_search pipeline** — The headline capability. LLM reasons over tree to find relevant sections.
4. **Two-stage pipeline (Qdrant shortlist -> tree search)** — Composes existing search with new tree search. The architectural innovation.
5. **Query router** — Heuristic-first dispatch between chunk and tree paths.
6. **Surface integration** — `--route` flag on CLI/API/MCP search.

### Add once core works:

7. **OpenKB compiled knowledge base export** — Wiki compilation from enriched docs + tree structure. Entity cross-linking, concept pages.
8. **OpenKB lint/watch mode** — Validate existing KB for broken links, stale content, missing cross-refs.
9. **Mixed-mode retrieval (both paths + fusion)** — For low-confidence routing, try both and fuse.

### Defer to v2.6+:

- Complex entity resolution beyond exact matching (spaCy NER, coreference)
- RAPTOR-style bottom-up tree construction (alternative to top-down)
- Tree index rebuild scheduling (manual trigger sufficient)
- Performance benchmarking framework
- Knowledge graph visualization UI

---

## Feature Sizing Estimates

Based on v2.0 execution velocity (STATE.md: ~5-15 min/plan, 3-8 plans/phase):

| Feature | Estimated Plans | Rationale |
|---------|----------------|-----------|
| TreeIndexerPlugin + tree pipeline + Dagster asset | 3-4 | Protocol + pipeline fn + deterministic builder + LLM builder + asset |
| TreeRetrieverPlugin + tree_search + two_stage | 3-4 | Protocol + pipeline fn + LLM traversal + stage composition |
| Query router + settings + integration | 2-3 | Heuristic classifier + settings model + surface integration |
| OpenKB export + wiki compilation | 3-4 | Entity extraction + cross-linking + page generation + CLI |
| OpenKB lint/watch | 1-2 | Validation logic + file watcher |
| Documentation | 2-3 | Architecture docs, ADRs, component diagrams |

**Total estimated: 14-20 plans across 4-5 phases**

---

## Integration Points with Existing v2.0 Architecture

| Existing Component | How v2.5 Integrates |
|--------------------|---------------------|
| `pipeline/search.py` | Stage 1 of two-stage retrieval. Called unchanged to produce Qdrant shortlist. |
| `pipeline/chunk.py` | Tree generation is PARALLEL to chunking, not a replacement. Both derive from parsed_document. |
| `pipeline/enrich.py` | OpenKB reads enrichment metadata (entities, keywords, document_type) for cross-linking. |
| `pipeline/index.py` | Tree indexes stored alongside chunk vectors. New artifact type, same lineage pattern. |
| `plugins/protocols.py` | New protocols added here (TreeIndexerPlugin, TreeRetrieverPlugin). |
| `plugins/resolver.py` | New resolver functions (get_tree_indexer, get_tree_retriever). |
| `registry/models.py` | New artifact_type value "tree_index". No schema migration needed (artifacts table already generic). |
| `config/settings.py` | New RetrievalSettings, TreeSettings, OpenKBSettings nested models. |
| `agent/registry.py` | New MCP tools: tree_search, build_tree, export_openkb. Same ToolDef pattern. |
| `dagster_defs/assets.py` | New build_tree_index asset. Parent = parse_document asset. |
| `llm/__init__.py` | Tree traversal uses cheap_model alias. Tree summarization uses cheap_model. OpenKB synthesis uses strong_model. |
| `storage/s3.py` | Tree JSON stored under `trees/{domain}/{source_id}/{content_hash}.json` in silver zone. |

---

## Sources

- VectifyAI/PageIndex GitHub repository (https://github.com/VectifyAI/PageIndex) — LOW confidence (web fetch, single source)
- RAPTOR paper (arxiv.org/abs/2401.18059) — LOW confidence (web fetch, academic paper)
- LlamaIndex TreeIndex implementation (GitHub source tree) — LOW confidence (web fetch)
- LlamaIndex Router documentation (developers.llamaindex.ai) — LOW confidence (web fetch)
- GraphRAG documentation (microsoft.github.io/graphrag) — LOW confidence (web fetch)
- Semantic Router (github.com/aurelio-labs/semantic-router) — LOW confidence (web fetch)
- Adaptive-RAG paper (arxiv.org/abs/2403.14403) — LOW confidence (web fetch)
- Agentic RAG patterns (weaviate.io/blog) — LOW confidence (web fetch)
- Knowledge Lake v2.0 codebase (direct reads) — HIGH confidence (primary source)
- PROJECT.md milestone requirements — HIGH confidence (primary source)

**Cross-referencing note:** PageIndex tree structure, RAPTOR's retrieval modes, LlamaIndex's TreeIndex API, and GraphRAG's community summaries all converge on the same architectural pattern: hierarchical document representation with multi-level retrieval. This convergence across 4+ independent implementations increases confidence in the approach despite individual sources being LOW confidence.

---
*Feature research for: Knowledge Lake Framework v2.5 (PageIndex/OpenKB integration)*
*Researched: 2026-07-13*
