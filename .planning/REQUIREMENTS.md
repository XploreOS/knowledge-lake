# Requirements: Knowledge Lake Framework

**Defined:** 2026-07-13
**Core Value:** Every domain resource ingested must be traceable from raw source through every transformation to its final AI-ready output — and the framework must remain tool-agnostic so any processor can be swapped without breaking lineage.

## v2.5 Requirements

Requirements for PageIndex Plugin Integration milestone. Each maps to roadmap phases.

### Tree Indexing

- [x] **TREE-01**: System generates a hierarchical tree index (JSON) from any parsed document's sections, stored as a silver-zone artifact with full lineage
- [x] **TREE-02**: Tree index generation is skipped when content hash matches an existing tree artifact (no redundant LLM calls)
- [x] **TREE-03**: Each tree node carries a title, summary, page range, and child nodes — deterministic mode uses heading text as summary
- [x] **TREE-04**: LLM-generated node summaries are available as opt-in mode (via config flag), gated by LlmSpend budget cap
- [x] **TREE-05**: Tree index generation runs as a Dagster asset parallel to chunking (fan-out from clean_document)

### Tree Retrieval

- [x] **RETR-04**: Two-stage search composes Qdrant document-level shortlist (stage 1) with per-document tree traversal (stage 2)
- [x] **RETR-05**: Heuristic tree traversal (keyword matching + DFS) retrieves relevant page ranges without LLM calls
- [x] **RETR-06**: LLM-guided tree navigation reasons through node summaries to select relevant subtrees (opt-in mode)
- [x] **RETR-07**: Tree search loads candidate document trees in parallel (asyncio) with configurable concurrency limit
- [x] **RETR-08**: Tree search results produce Hit objects with page-level citations and a `citation_source: tree` discriminator

### Query Routing

- [ ] **ROUTE-01**: Search mode is configurable as `chunk | tree | two_stage | auto` via settings, CLI flag, and API parameter
- [ ] **ROUTE-02**: Heuristic router detects structural/multi-hop queries (section references, page mentions, comparison patterns) and upgrades to tree search
- [ ] **ROUTE-03**: Auto mode defaults to chunk search when no structural signals are detected (conservative routing)
- [ ] **ROUTE-04**: MCP tools and API endpoints expose the route parameter alongside existing mode parameter

### OpenKB Export

- [ ] **KB-01**: System compiles ingested documents into an interlinked wiki of Markdown pages with `[[wikilinks]]` in the gold zone
- [ ] **KB-02**: Wiki pages include per-document summaries, cross-document concept pages, and a root index
- [ ] **KB-03**: Entity cross-linking uses IDF-filtered entities from enrichment metadata (only link on specific terms)
- [ ] **KB-04**: Wiki compilation is incremental — adding a new source rebuilds only affected pages, not the full wiki
- [ ] **KB-05**: Wiki export is available via CLI (`klake export-wiki`) and API endpoint

## Future Requirements

Deferred to future releases. Tracked but not in current roadmap.

### Enhanced Routing

- **ROUTE-05**: LLM-based routing for ambiguous queries (when heuristics are uncertain)
- **ROUTE-06**: Routing telemetry and feedback loop for tuning heuristics

### OpenKB Advanced

- **KB-06**: Watch mode — drop files into raw/ and wiki auto-updates
- **KB-07**: Wiki lint command (contradictions, orphaned pages, stale content)
- **KB-08**: Multi-turn chat grounded in wiki content

### Tree Enhancements

- **TREE-06**: Tree schema versioning with migration strategy
- **TREE-07**: PageIndex File System (meta-tree over all documents for corpus-level navigation)

## Out of Scope

| Feature | Reason |
|---------|--------|
| ConDB (KV-cache native context DB) | Not released/mature; Qdrant + S3 sufficient for v2.5 scale |
| PageIndex cloud API | Self-hosted only; no external API dependencies per project constraints |
| Real-time wiki updates | Batch-first architecture; incremental rebuild sufficient |
| GraphRAG entity extraction | Over-complex for wiki linking; IDF-filtered enrichment entities sufficient |
| Custom tree traversal model training | Use off-the-shelf LLM via LiteLLM; training is downstream concern |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| TREE-01 | Phase 13 | Complete |
| TREE-02 | Phase 13 | Complete |
| TREE-03 | Phase 13 | Complete |
| TREE-04 | Phase 13 | Complete |
| TREE-05 | Phase 13 | Complete |
| RETR-04 | Phase 14 | Complete |
| RETR-05 | Phase 14 | Complete |
| RETR-06 | Phase 14 | Complete |
| RETR-07 | Phase 14 | Complete |
| RETR-08 | Phase 14 | Complete |
| ROUTE-01 | Phase 15 | Pending |
| ROUTE-02 | Phase 15 | Pending |
| ROUTE-03 | Phase 15 | Pending |
| ROUTE-04 | Phase 15 | Pending |
| KB-01 | Phase 16 | Pending |
| KB-02 | Phase 16 | Pending |
| KB-03 | Phase 16 | Pending |
| KB-04 | Phase 16 | Pending |
| KB-05 | Phase 16 | Pending |

**Coverage:**

- v2.5 requirements: 19 total
- Mapped to phases: 19
- Unmapped: 0

---
*Requirements defined: 2026-07-13*
*Last updated: 2026-07-13 after roadmap creation (traceability complete)*
