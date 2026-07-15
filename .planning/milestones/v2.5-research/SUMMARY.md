# Project Research Summary

**Project:** Knowledge Lake Framework — v2.5 PageIndex Plugin Integration
**Domain:** Data pipeline / AI-ready knowledge management — tree-based retrieval extension
**Researched:** 2026-07-13
**Confidence:** HIGH

## Executive Summary

The v2.5 milestone adds tree-based reasoning retrieval (PageIndex), compiled wiki knowledge bases (OpenKB-inspired), and two-stage query routing to the shipped v2.0 Knowledge Lake framework. The research confirms this is architecturally clean: tree indexing slots in as a parallel branch off `clean_document` (same fan-out pattern as chunk/enrich/curate), requires zero Alembic migrations, and introduces only 4 net-new runtime dependencies. PageIndex already uses LiteLLM internally, making it natively compatible with the framework's LLM gateway constraint.

The recommended approach is additive and layered: build tree index generation first (deterministic mode, no LLM cost), then tree retrieval, then the query router that dispatches between chunk and tree paths, then OpenKB wiki compilation. This ordering respects hard dependencies (cannot search trees that do not exist) and follows the project's deterministic-first constraint (free heuristic mode before paid LLM mode). The OpenKB export is partially independent and can overlap with retrieval work once tree artifacts exist.

Key risks center on LLM cost control (tree indexing can burn budget without content-hash caching), search latency (sequential tree traversal adds 3-15s without parallelization), and over-routing (sending simple queries to the expensive tree path). All are mitigable with patterns already proven in v2.0: content-hash dedup, budget caps via LlmSpend, and deterministic-first defaults with LLM as opt-in.

## Key Findings

### Recommended Stack

v2.5 requires only 4 new runtime dependencies. PageIndex (0.3.0.dev3) provides tree indexing with native LiteLLM support. markitdown (0.1.5) handles office-format-to-markdown for wiki compilation. PyPDF2 (3.0.1) and pymupdf are PageIndex hard dependencies. No new infrastructure services needed — all connect to existing LiteLLM proxy, S3, and Qdrant.

**Core technologies:**
- **pageindex 0.3.0.dev3**: Tree-based hierarchical document indexing — uses LiteLLM natively, MIT license, vendorable (6 files)
- **markitdown 0.1.5**: Office format to markdown conversion — lightweight, Microsoft-maintained, for wiki pipeline
- **json-repair**: Robust JSON recovery from LLM wiki output — complements existing partial-JSON handling

**Critical version notes:**
- PageIndex pinned to exact pre-release (0.3.0.dev3) — the `PageIndexClient` API only exists in 0.3.x
- PyPDF2 is deprecated but frozen (final release) — accepted as transitive, isolated behind plugin boundary
- No existing dependency version bumps required

### Expected Features

**Must have (table stakes):**
- Tree index generation from parsed documents (two modes: deterministic + LLM-summarized)
- Tree index as registered artifact with full lineage
- Two-stage retrieval pipeline (Qdrant shortlist then tree traversal)
- Query router (chunk vs tree dispatch, heuristic-first)
- Plugin protocols for tree indexer + retriever (swappability constraint)
- OpenKB compiled knowledge base export (interlinked wiki pages in gold zone)

**Should have (differentiators):**
- Deterministic tree generation without LLM (free, reproducible, fast)
- LLM-guided tree traversal with reasoning traces (explainable retrieval)
- Heuristic routing at zero LLM cost per query
- Mixed-mode retrieval (both paths + RRF fusion)
- Tree index persistence with S3 lineage (vs PageIndex cloud's ephemeral approach)

**Defer to v2.6+:**
- RAPTOR-style bottom-up tree construction
- Complex entity resolution (spaCy NER, coreference)
- Knowledge graph visualization UI
- Performance benchmarking framework

### Architecture Approach

Tree indexing integrates as a parallel fan-out from `clean_document`, identical to the existing chunk/enrich/curate pattern. New artifacts (`tree_index`) live in the silver zone as content-addressed JSON. Two new plugin protocols (IndexerPlugin, RetrieverPlugin) follow the established entry-point pattern. The query router is a thin dispatch layer in `pipeline/route.py`. Zero Alembic migrations needed — all new capabilities use existing schema flexibility.

**Major components:**
1. `pipeline/tree_index.py` — Builds tree index from ParsedDoc, registers artifact, content-hash dedup
2. `pipeline/tree_search.py` — Two-stage orchestration: Qdrant doc shortlist then per-doc tree traversal
3. `pipeline/route.py` — Query routing (heuristic patterns + optional LLM classification)
4. `pipeline/export.py` (extended) — OpenKB wiki compilation from enrichment + tree data
5. `plugins/builtin/pageindex_{indexer,retriever}.py` — PageIndex plugin implementations

### Critical Pitfalls

1. **LLM budget burn on tree indexing** — Implement content-hash caching and deterministic-only mode BEFORE adding LLM summarization. Same no-op pattern as chunk.py.
2. **O(N) latency in two-stage search** — Parallelize S3 loads and tree traversals; offer keyword retriever mode for latency-sensitive use.
3. **Over-routing to expensive tree path** — Default to chunk search when uncertain; keep heuristic patterns narrow; log routing decisions.
4. **Schema coupling between IndexerPlugin and RetrieverPlugin** — Define a shared Pydantic tree schema contract FIRST, before implementing either plugin.
5. **OpenKB over-linking (fully-connected graph)** — Filter cross-links by entity specificity (IDF threshold); cap outgoing links per page.

## Implications for Roadmap

### Phase 1: Tree Index Foundation
**Rationale:** Everything depends on tree indexes existing. Lowest risk, unblocks all subsequent phases.
**Delivers:** IndexerPlugin protocol, `pipeline/tree_index.py`, PageIndex built-in indexer, Dagster asset, CLI command.
**Addresses:** Tree index generation, artifact registration, plugin protocol.
**Avoids:** Pitfall 1 (budget burn — deterministic-only first), Pitfall 4 (schema contract defined upfront), Pitfall 9 (content-hash dedup from day 1).

### Phase 2: Tree Retrieval
**Rationale:** Depends on Phase 1 (needs tree indexes to search). The headline capability.
**Delivers:** RetrieverPlugin protocol, `pipeline/tree_search.py`, PageIndex built-in retriever, CLI/API/MCP surface.
**Addresses:** Two-stage retrieval, LLM-guided traversal, unified SearchResult type.
**Avoids:** Pitfall 2 (parallel loading), Pitfall 7 (content size bounds), Pitfall 10 (unified result format).

### Phase 3: Query Router
**Rationale:** Depends on Phase 2 (dispatches TO tree_search which must exist). Thin glue layer.
**Delivers:** `pipeline/route.py`, RetrievalSettings, `--route` flag on all surfaces, routed_search unified entry point.
**Addresses:** Heuristic routing, auto mode, mixed-mode retrieval.
**Avoids:** Pitfall 3 (conservative defaults), Pitfall 8 (deterministic routing, decision logging).

### Phase 4: OpenKB Export
**Rationale:** Needs enriched documents + tree indexes (Phase 1). Partially independent of Phases 2-3. Can overlap.
**Delivers:** `export_openkb()`, wiki page generation, entity cross-linking, Dagster asset, CLI/API surface.
**Addresses:** Compiled knowledge base, wikilinks, gold zone wiki output.
**Avoids:** Pitfall 5 (specificity filtering), Pitfall 11 (batch writes at scale), Pitfall 12 (embedded metadata).

### Phase 5: Documentation and Integration Testing
**Rationale:** Independent; best done after architecture stabilizes.
**Delivers:** Architecture docs, ADRs, integration tests, performance baseline.

### Phase Ordering Rationale

- Phase 1 before 2: Cannot search trees that do not exist
- Phase 2 before 3: Router dispatches to tree_search which must be implemented
- Phase 4 after 1 (but parallel to 2-3): OpenKB reads stored trees, doesn't need tree search
- Phase 3 after 2: Router is thin glue — build the things it routes to first
- Phase 5 last: Documentation follows stabilized architecture

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2:** LLM-guided tree traversal prompt engineering; parallel execution model; latency budget allocation
- **Phase 4:** Entity specificity scoring algorithm; cross-link quality heuristics; wiki page generation prompts

Phases with standard patterns (skip research-phase):
- **Phase 1:** Follows existing fan-out + content-hash + plugin protocol patterns exactly
- **Phase 3:** Simple heuristic dispatch; well-documented router patterns
- **Phase 5:** Standard documentation work

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | PageIndex source code directly verified; dependency compatibility confirmed against existing lockfile |
| Features | MEDIUM | Feature landscape cross-referenced across 4+ implementations (PageIndex, RAPTOR, LlamaIndex, GraphRAG); convergence increases confidence |
| Architecture | HIGH | Grounded in direct reads of shipped v2.0 source; every integration point references a real file/function |
| Pitfalls | HIGH | Derived from existing v2.0 patterns (budget cap, content-hash dedup, latency) applied to new features |

**Overall confidence:** HIGH

### Gaps to Address

- **PageIndex pre-release stability:** 0.3.0.dev3 may change; vendoring fallback plan exists but untested. Validate during Phase 1.
- **Tree traversal prompt quality:** No ground-truth benchmarks for our domain. Need to evaluate retrieval quality empirically during Phase 2.
- **OpenKB entity specificity threshold:** No empirical data on what IDF threshold produces useful links. Needs tuning during Phase 4.
- **"Auto" routing accuracy:** No labeled query dataset to validate heuristic patterns. Start conservative; tune with production data.

## Sources

### Primary (HIGH confidence)
- Shipped v2.0 source code (direct reads) — architecture, integration points, existing patterns
- PROJECT.md v2.5 milestone requirements — feature scope and constraints
- PageIndex GitHub source (utils.py, client.py, retrieve.py, requirements.txt) — API surface, LiteLLM usage

### Secondary (MEDIUM confidence)
- OpenKB pyproject.toml — dependency pins, architecture patterns
- PageIndex/RAPTOR/LlamaIndex/GraphRAG convergence — tree-based retrieval validity

### Tertiary (LOW confidence)
- Academic papers (RAPTOR, Adaptive-RAG) — theoretical foundations, needs empirical validation
- LLM latency estimates — approximate, varies by provider/model

---
*Research completed: 2026-07-13*
*Ready for roadmap: yes*
