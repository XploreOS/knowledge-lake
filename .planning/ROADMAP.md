# Roadmap: Knowledge Lake Framework

## Milestones

- ✅ **v1.0 MVP** — Phases 1-6 (shipped 2026-07-07)
- ✅ **v2.0 Agent-Ready Lake** — Phases 7-12 (shipped 2026-07-12)
- 🚧 **v2.5 PageIndex Plugin Integration** — Phases 13-16 (in progress)

## Phases

<details>
<summary>✅ v2.0 Agent-Ready Lake (Phases 7-12) — SHIPPED 2026-07-12</summary>

Full archive: [.planning/milestones/v2.0-ROADMAP.md](.planning/milestones/v2.0-ROADMAP.md)

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 7 | Metadata Foundation | 4/4 | ✅ Complete | 2026-07-08 |
| 8 | Crawl Maturation | 6/6 | ✅ Complete | 2026-07-08 |
| 9 | Storage Segmentation | 6/6 | ✅ Complete | 2026-07-09 |
| 10 | Hybrid Retrieval | 8/8 | ✅ Complete | 2026-07-10 |
| 11 | Crawl Scheduling | 6/6 | ✅ Complete | 2026-07-10 |
| 12 | Agent Surfaces | 8/8 | ✅ Complete | 2026-07-11 |

**Total:** 6 phases, 38 plans, 252 commits, 85 files changed (+14,487/-419). All phases verified `passed` (19/19 requirements), threat-secured (`threats_open: 0`), and Nyquist-compliant.

</details>

<details>
<summary>✅ v1.0 MVP (Phases 1-6) — SHIPPED 2026-07-07</summary>

Full archive: [.planning/milestones/v1.0-ROADMAP.md](.planning/milestones/v1.0-ROADMAP.md)

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 1 | Foundation & End-to-End Spike | 6/6 | ✅ Complete | 2026-07-03 |
| 2 | Ingestion | 6/6 | ✅ Complete | 2026-07-04 |
| 3 | Parse, Clean & Chunk | 3/3 | ✅ Complete | 2026-07-05 |
| 4 | Enrichment, Embedding & Search | 3/3 | ✅ Complete | 2026-07-06 |
| 5 | Curation, Datasets & Export | 3/3 | ✅ Complete | 2026-07-06 |
| 6 | Healthcare Domain Pack & Full-Surface Validation | 4/4 | ✅ Complete | 2026-07-07 |

**Total:** 6 phases, 25 plans, 259 commits, 303 files changed

</details>

### 🚧 v2.5 PageIndex Plugin Integration (In Progress)

**Milestone Goal:** Add tree-based reasoning retrieval (PageIndex) and compiled knowledge bases (OpenKB) alongside the existing vector RAG pipeline, with a two-stage hybrid routing architecture.

- [x] **Phase 13: Tree Index Foundation** - Hierarchical tree index generation from parsed documents as a new silver-zone artifact type (completed 2026-07-13)
- [x] **Phase 14: Tree Retrieval** - Two-stage search: Qdrant document shortlist then per-document tree traversal for page-level precision (completed 2026-07-14)
- [x] **Phase 15: Query Router** - Dispatch queries between chunk-search and tree-search paths based on query characteristics (completed 2026-07-14)
- [ ] **Phase 16: OpenKB Export** - Compiled interlinked wiki knowledge base from ingested documents in the gold zone

## Phase Details

### Phase 13: Tree Index Foundation

**Goal**: Users can generate hierarchical tree indexes from any ingested document, stored as traceable silver-zone artifacts
**Depends on**: Nothing (builds on existing v2.0 parse/clean pipeline)
**Requirements**: TREE-01, TREE-02, TREE-03, TREE-04, TREE-05
**Success Criteria** (what must be TRUE):

  1. Running tree index generation on a parsed document produces a hierarchical JSON artifact in the silver zone with full lineage back to the source document
  2. Re-running tree index on an unchanged document is a no-op (content-hash match skips all processing, including LLM calls)
  3. Each tree node contains a title, summary, page range, and child nodes -- deterministic mode derives summaries from heading text without any LLM call
  4. Setting tree index mode to LLM generates richer node summaries, gated by the existing LlmSpend budget cap
  5. Tree index generation runs as a Dagster asset parallel to the existing chunking asset (fan-out from clean_document)

**Plans**: 6/6 plans complete

Plans:
**Wave 1**

- [x] 13-01-PLAN.md — Wave 0: test scaffolds for TREE-01..05 (test_tree_index.py, test_tree_index_asset.py, extend test_builtin_plugins.py)
- [x] 13-02-PLAN.md — Wave 1: enabling edits (ids.py _PREFIX, protocols.py TreeNode/TreeIndex/IndexerPlugin, settings.py TreeSettings)
- [x] 13-03-PLAN.md — Wave 1: registry helper create_tree_index_artifact (repo.py)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 13-04-PLAN.md — Wave 2: pipeline/tree_index.py — deterministic builder + content-hash no-op + LLM mode
- [x] 13-05-PLAN.md — Wave 2: PageIndexIndexer builtin + resolver.py get_indexer + entry-point registration

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 13-06-PLAN.md — Wave 3: tree_index_document Dagster asset + definitions.py wiring + human checkpoint

### Phase 14: Tree Retrieval

**Goal**: Users can search within documents using two-stage retrieval that narrows from document selection to precise page-level results
**Depends on**: Phase 13
**Requirements**: RETR-04, RETR-05, RETR-06, RETR-07, RETR-08
**Success Criteria** (what must be TRUE):

  1. A search query first selects candidate documents via Qdrant (stage 1), then traverses each document's tree index to find relevant page ranges (stage 2)
  2. Heuristic tree traversal retrieves relevant sections using keyword matching and DFS without any LLM calls
  3. LLM-guided tree navigation is available as an opt-in mode that reasons through node summaries to select relevant subtrees
  4. Tree search results produce Hit objects with page-level citations and a `citation_source: tree` discriminator distinguishing them from chunk hits
  5. Multiple document trees load from S3 and traverse in parallel (asyncio) with a configurable concurrency limit

**Plans**: 4/4 plans complete
**Wave 1**

- [x] 14-01-PLAN.md — Wave 0 test scaffold (test_tree_search.py + RetrieverPlugin conformance stub) covering RETR-04..08
- [x] 14-02-PLAN.md — Hit.citation_source + RetrieverPlugin Protocol + TreeSearchSettings + retriever swap key (contracts)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 14-03-PLAN.md — PageIndexRetriever (heuristic DFS + opt-in budget-capped LLM-nav) + get_retriever entry-point seam

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 14-04-PLAN.md — Two-stage tree_search orchestrator (shortlist → parallel tree load → traversal) + thin klake tree-search CLI

### Phase 15: Query Router

**Goal**: System automatically dispatches queries to the optimal retrieval path based on query characteristics
**Depends on**: Phase 14
**Requirements**: ROUTE-01, ROUTE-02, ROUTE-03, ROUTE-04
**Success Criteria** (what must be TRUE):

  1. User can set search route to `chunk`, `tree`, `two_stage`, or `auto` via settings, CLI flag (`--route`), and API parameter
  2. In auto mode, the heuristic router detects structural queries (section references, page mentions, comparison patterns) and upgrades to tree search
  3. Auto mode defaults to chunk search when no structural signals are detected (conservative routing)
  4. MCP tools and API endpoints expose the `route` parameter alongside the existing `mode` parameter

**Plans**: 2/2 plans complete
**Wave 1**

- [x] 15-01-PLAN.md — Wave 0 tests + RouterSettings + SearchParams.route + pipeline/route.py (classify_route + routed_search)
- [x] 15-02-PLAN.md — Wire route to REST/CLI/MCP surfaces + regenerate docs/openapi.json

### Phase 16: OpenKB Export

**Goal**: Users can compile ingested documents into an interlinked knowledge base wiki in the gold zone
**Depends on**: Phase 13
**Requirements**: KB-01, KB-02, KB-03, KB-04, KB-05
**Success Criteria** (what must be TRUE):

  1. Running `klake export-wiki` produces a set of interlinked Markdown pages with `[[wikilinks]]` in the gold zone
  2. Wiki output includes per-document summary pages, cross-document concept pages, and a root index page
  3. Entity cross-linking uses IDF-filtered terms from enrichment metadata so only specific terms generate links (not common ones)
  4. Adding a new source and re-running wiki export rebuilds only affected pages, not the entire wiki
  5. Wiki export is available via both CLI (`klake export-wiki`) and API endpoint

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 13 -> 14 -> 15 -> 16

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-6 | v1.0 MVP | 25/25 | ✅ Shipped | 2026-07-07 |
| 7-12 | v2.0 Agent-Ready Lake | 38/38 | ✅ Shipped | 2026-07-12 |
| 13. Tree Index Foundation | v2.5 | 6/6 | Complete    | 2026-07-13 |
| 14. Tree Retrieval | v2.5 | 4/4 | Complete   | 2026-07-14 |
| 15. Query Router | v2.5 | 2/2 | Complete   | 2026-07-14 |
| 16. OpenKB Export | v2.5 | 0/0 | Not started | - |
