# Knowledge Lake Framework

## What This Is

A reusable, domain-agnostic framework that orchestrates best-in-class open-source tools to turn public, private, and manually uploaded domain resources into AI-ready assets. It owns registries, lineage, domain packs, and export contracts — external tools (parsers, crawlers, vector stores, LLM gateways) are treated as replaceable plugins. Healthcare is the first domain pack.

## Core Value

Every domain resource ingested must be traceable from raw source through every transformation to its final AI-ready output — and the framework must remain tool-agnostic so any processor can be swapped without breaking lineage.

## Current State (v2.5 — Phase 16 complete 2026-07-14)

- **Shipped:** v2.0 — Agent-Ready Lake (Phases 7–12); v2.5 Phases 13–16 complete (Tree Index, Tree Retrieval, Query Router, OpenKB Export)
- **Source lines:** ~22,000 Python
- **Tests:** 651 unit passing (+35 xpass, 5 xfail) plus integration/e2e suites (Qdrant/Postgres-gated)
- **Pipeline:** ingest → parse → clean → chunk/tree_index → enrich → embed → index → curate → generate-dataset → export → wiki
- **Agent surface:** MCP server (stdio + Streamable HTTP), 11 intent-level tools over one registry; OpenAPI + OpenAI tool defs from a single Pydantic schema source; 4 Claude Code skills
- **Retrieval:** hybrid BM25 + dense (RRF), mode-switchable (`hybrid|dense|sparse`); two-stage tree retrieval; query router dispatching between chunk and tree paths (`chunk|tree|two_stage|auto`)
- **Query routing:** `classify_route()` heuristic classifier (section/comparison/structural triggers) + `routed_search()` dispatcher with auto-fallback on empty tree results; KLAKE_ROUTER__DEFAULT_ROUTE env var
- **Wiki export:** `compile_wiki()` builds interlinked Markdown knowledge base from enrichment metadata — IDF-filtered entity cross-links, per-document summary pages, concept pages, root index; manifest-based incremental rebuild; archive export for Obsidian vault import
- **Scheduling:** Dagster re-crawl sensor with normalized silver-text change gate + tick-storm dedup
- **Storage:** domain/source-scoped S3 keys + object tags; gold zone segmented by domain × dataset type (including `wiki/` prefix)
- **CLI:** `klake` Typer app extended with `crawl-all`, `set-schedule`, `mcp`, `openapi`, `search --mode --route`, `reindex --hybrid`, `export-wiki`
- **API:** FastAPI (Swagger at /docs) extended with `/crawl-all`, mode-aware and route-aware search, `/export-wiki`
- **Domain packs:** 1 (healthcare, 28 curated sources)  ·  **Dagster assets:** 12+ with RetryPolicy
- **Quality gates:** all v2.5 phases verified `passed`, threat-secured, Nyquist-compliant; code review phase 16: 2 criticals (orphan S3 page deletion, slug disambiguation) flagged for fix
- **Tech debt:** Typer <0.25.0 pin; MCP `_search_handler` crashes on non-empty results; `mode` param dual semantics on tree path; wiki orphan page deletion (CR-01); wiki slug second-collision overwrite (CR-02); Dagster container rebuild / code-location reload for new sensors

## Current Milestone: v2.5 PageIndex Plugin Integration

**Goal:** Add tree-based reasoning retrieval (PageIndex) and compiled knowledge bases (OpenKB) alongside the existing vector RAG pipeline, with a two-stage hybrid routing architecture and comprehensive system documentation.

**Target features:**
- PageIndex tree index generation as a new artifact type (silver zone JSON, parallel to chunking)
- Two-stage retrieval: Qdrant doc-level selection → PageIndex tree search for precision
- OpenKB-style compiled knowledge base export (interlinked wiki from ingested documents)
- Query router to dispatch between chunk-search and tree-search paths
- Comprehensive architectural documentation of the full system

## Requirements

### Validated (v1.0)

- ✓ Source registry, document registry, artifact registry with full lineage — Phase 1
- ✓ Raw/bronze/silver/gold data lake zones with immutable raw storage (SHA256-keyed, WORM policy) — Phase 1
- ✓ Document parsing via Docling/Unstructured/Tika as swappable plugins — Phases 1, 3
- ✓ Configurable embeddings (local sentence-transformers or LiteLLM API) — Phases 1, 4
- ✓ Vector search via Qdrant as a plugin — Phases 1, 4
- ✓ FastAPI service with full CRUD and pipeline trigger endpoints — Phases 1, 6
- ✓ Typer CLI (`klake`) for all operations — Phases 1, 6
- ✓ Dagster pipeline orchestration from day 1 — Phase 1, retries Phase 6
- ✓ S3-compatible object storage (MinIO dev, AWS S3 production) — Phase 1
- ✓ PostgreSQL metadata registry — Phase 1
- ✓ All LLM calls routed through LiteLLM with task-based model aliases — Phase 1
- ✓ Automated crawling via Crawl4AI, Scrapy, Playwright as swappable plugins — Phase 2
- ✓ Manual file upload + single-URL ingest with provenance and SHA256 dedup — Phase 2
- ✓ SearXNG-based source discovery with auto-registration — Phase 2
- ✓ Robots.txt, rate-limit, SSRF guard, resumable crawl jobs — Phase 2
- ✓ Multi-format document parsing with quality scoring — Phase 3
- ✓ Cleaning, normalization, language detection, deduplication pipeline — Phase 3
- ✓ Section-aware, token-aware, table-aware chunking — Phase 3
- ✓ LLM-based metadata enrichment through LiteLLM gateway with budget cap — Phase 4
- ✓ Quality scoring at document and source level — Phases 3, 4
- ✓ Zero-downtime Qdrant alias-based reindex — Phase 4
- ✓ Corpus curation for pretraining (DataTrove filtering + corpus-wide MinHash dedup) — Phase 5
- ✓ Dataset generation (RAG eval Q&A, instruction-tuning) with full lineage — Phase 5
- ✓ Export to Parquet, JSONL via gold zone (DuckDB queryable) — Phase 5
- ✓ Domain-agnostic core with pluggable domain packs — Phase 6
- ✓ Healthcare domain pack with 28 curated seed sources — Phase 6
- ✓ Healthcare enrichment prompts, taxonomy, and validator — Phase 6
- ✓ 5-source E2E validation (HTML, PDF, CSV) — Phase 6
- ✓ Resumable, idempotent jobs with retries and rate limits — Phase 6

### Validated (v2.0 — Agent-Ready Lake, milestone complete 2026-07-11)

**Metadata & Crawl Maturation**
- [x] PAYLOAD-01: Expanded Qdrant chunk payload (source_id, source_name, source_url, format, tags, title, organization) — Phase 7
- [x] PAYLOAD-02: Search filters for source_name, format, tags, source_id (API + CLI) — Phase 7
- [x] CRAWL-01: Per-source crawl_config (depth, rate_limit_rps) from sources.yaml — Phase 8
- [x] CRAWL-02: `klake crawl-all` batch crawl with optional --domain filter — Phase 8
- [x] CRAWL-03: Adaptive rate limiting (backoff on 429/403, per-host cooldown) — Phase 8
- [x] ENRICH-07: Partial JSON recovery on truncated LLM output — Phase 8
- [x] INGEST-10: PDF/doc ingest from crawled page links — Phase 8

**MinIO Domain Segmentation**
- [x] STORE-01: Domain/source-scoped S3 keys with `_unclassified` fallback — Phase 9
- [x] STORE-02: S3 object tags on every write (domain, source_name, format, artifact_type) — Phase 9
- [x] STORE-03: Gold-zone domain segmentation (rag_corpus / pretrain / finetune) — Phase 9

**AI Agent Skills**
- [x] MCP-01: MCP server (stdio + Streamable HTTP) exposing 11 curated tools over one registry — Phase 12
- [x] MCP-02: `klake mcp` (stdio) and `klake mcp --sse --port 3001` (Streamable HTTP; localhost bind, Host guard, closed CORS, optional bearer) — Phase 12
- [x] SKILL-01: Claude Code skills (build-corpus, search-knowledge, add-source, export-dataset) — Phase 12
- [x] SKILL-02: Static OpenAPI export (`klake openapi` + docs/openapi.json) — Phase 12
- [x] SKILL-03: OpenAI-format tool definitions from Pydantic schemas (surface parity: stdio==http==openapi==openai) — Phase 12

**Crawl Scheduling + Hybrid Search**
- [x] SCHED-01: Dagster sensor for periodic re-crawl (crawl_schedule) — Phase 11
- [x] SCHED-02: Content-hash change detection (skip unchanged) — Phase 11
- [x] RETR-01: Hybrid BM25 + dense search (Qdrant sparse vectors + RRF fusion) — Phase 10
- [x] RETR-03: Configurable search mode (hybrid | dense | sparse) — Phase 10

**PageIndex / Tree Retrieval (v2.5, Phases 13–15)**
- [x] TREE-01..05: Hierarchical tree index from parsed documents (silver zone JSON artifact) — Phase 13
- [x] RETR-04..08: Two-stage tree retrieval (Qdrant shortlist → per-document tree traversal) — Phase 14
- [x] ROUTE-01: `routed_search()` dispatcher with per-call override → settings.router.default_route fallthrough — Phase 15
- [x] ROUTE-02: `classify_route()` heuristic classifier (section_page_ref, comparison_multihop, structural_breadth) — Phase 15
- [x] ROUTE-03: chunk/tree/two_stage/auto dispatch with D-05 auto-fallback semantics — Phase 15
- [x] ROUTE-04: route param wired to REST (`?route=`), CLI (`--route`), MCP, and OpenAPI spec — Phase 15

### Deferred to v2.1

- EVAL-01/02 (RAGAS/Promptfoo eval harness; Langfuse/Arize observability), SDK-01 (klake-client SDK), DOMAIN-05/06 (multi-domain conflict resolution; pack registry + versioning), DISCOVER-01 (SearXNG auto-discovery scheduling), UI-02 (admin/crawl analytics dashboard), VERSION-01 (lakeFS/DVC data versioning), SITEMAP-01 (sitemap-first crawl strategy), QUALITY-01 (quality-score search propagation)

### Out of Scope

- Real-time streaming ingestion — batch-first; streaming adds complexity without MVP value
- Multi-tenant auth / RBAC — single user/small team for v1.0
- Admin UI / web dashboard — CLI + API + Swagger sufficient; avoids frontend complexity
- PHI/PII ingestion — only public data; PHI restricted to controlled test environments
- Crawling private/restricted resources — legal guardrail: robots.txt and licenses respected
- Custom embedding model training — use off-the-shelf models; training is a downstream concern
- Mobile/desktop clients — server-side framework only
- lakeFS/DVC data versioning — raw zone immutability covers the core need for now

## Context

- Running on DigitalOcean Ubuntu 24.04 droplet with Docker Compose
- Using AWS Bedrock models through LiteLLM proxy
- Healthcare domain is deeply familiar (HL7 FHIR, CMS, HIPAA, ONC, etc.)
- v1.0 shipped 2026-07-02 → 2026-07-07 (5 days, 259 commits, 303 files changed)
- Plugin architecture: every external tool is replaceable without breaking core registries or lineage
- Closest analogues: DataTrove (pretraining corpus), RAGFlow (RAG), Dagster (orchestration), Docling (parsing)

## Constraints

- **LLM Gateway**: All model calls through LiteLLM only — no direct provider SDK calls in business logic
- **Storage**: S3-compatible (MinIO for dev, AWS S3 for large-scale) — no local filesystem as production store
- **Orchestration**: Dagster from day 1 — no ad-hoc script pipelines
- **Immutability**: Raw zone must never be modified after write
- **Lineage**: Every artifact must trace back to source document with stable IDs, content hashes, and timestamps
- **Legal**: Respect robots.txt, track source licenses, no private/restricted scraping
- **Models**: Task-based aliases (cheap_model, strong_model, eval_model, embedding_model) — no hardcoded provider model IDs
- **Deterministic first**: Use regex/heuristic extraction before LLM enrichment

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Dagster over Prefect for orchestration | Better asset-based model for data pipelines, built-in lineage concepts | ✓ Validated — 12 assets, all retried |
| Docling as primary parser | Best balance of format support, quality, and open-source maturity | ✓ Validated — multi-format with 6-format fallback chain |
| S3-compatible storage (not local filesystem) | Production-portable, supports MinIO dev and AWS S3 prod | ✓ Validated — content-addressed put_raw + WORM policy |
| Plugin architecture for all external tools | Avoid lock-in, enable swapping parsers/crawlers/vector stores | ✓ Validated — entry-point resolver + built-ins registered |
| LiteLLM as sole model gateway | Unified interface for Bedrock, OpenAI, Anthropic, local models | ✓ Validated — task-based aliases only in business logic |
| PostgreSQL for metadata registry (not OpenMetadata yet) | Simpler for MVP, migrate to catalog tool later | ✓ Validated — 8 tables, self-referencing lineage graph |
| DataTrove-style curation over custom filters | Proven at scale for pretraining corpus preparation | ✓ Validated — batch MinHash dedup + DataTrove filters |
| No UI for MVP | CLI + API is sufficient for single user, avoids frontend complexity | ✓ Validated — klake CLI + FastAPI /docs working |
| Healthcare first domain pack | Deeply familiar domain, rich public data, high value for RAG/fine-tuning | ✓ Validated — 28 sources, DomainLoader, 5-source E2E passed |
| Single enrichment call per document (not per-field) | Cost efficiency; structured JSON output covers all fields at once | ✓ Validated — one LiteLLM call per doc, cached by content hash |
| Budget cap with graceful halt (LlmSpend table) | No surprise runaway costs; fail-closed on budget exhaustion | ✓ Validated — contamination gate + budget cap both enforced |
| Typer downgraded to <0.25.0 | docling-core has a conflicting dependency on typer | ⚠ Revisit — upgrade when docling drops the pin |
| uuid-utils approved (not uuid6) | PyPI legitimacy verified by human gate | ✓ — isolated to ids.py for easy stdlib swap in Python 3.14 |
| Domain convention over plugin entry-points | Zero core code changes per new domain pack | ✓ Validated — `domains/{name}/` convention proven by healthcare pack |
| Qdrant native sparse+dense + server-side RRF over a second search engine (OpenSearch) | Avoids operating a second engine; RRF fusion runs in Qdrant ≥1.10 | ✓ Validated (v2.0) — hybrid search live, old `RETR-02` OpenSearch req superseded |
| Re-embedding reindex with count-parity gate (not a pure copy) for hybrid migration | Every point must gain a sparse vector; alias holds old collection until parity passes | ✓ Validated (v2.0) — zero-downtime alias swap, reversible on mismatch |
| MCP tools as thin shims over `pipeline/*.py`, never proxying REST | One tool registry shared across stdio/HTTP/OpenAPI/OpenAI; no surface drift | ✓ Validated (v2.0) — parity gate proves `stdio==http==openapi==openai` |
| MCP Streamable HTTP (not deprecated HTTP+SSE); `--sse` kept as flag name | Legacy HTTP+SSE transport deprecated in current MCP spec | ✓ Validated (v2.0) — localhost bind + Host guard + closed CORS + optional bearer |
| Re-crawl change gate over normalized silver text, not raw bytes | Dynamic timestamps/nonces must not thrash the WORM raw zone; max-staleness backstop | ✓ Validated (v2.0) — inline timestamp/UUID/nonce suppression, meaningful dates survive |
| Dagster vendored cron (`dagster._utils.schedules`), no standalone `croniter` | Avoids a SUS-flagged dependency; engine already in-tree | ⚠ Revisit — private import, no stability guarantee across Dagster minors |
| Forward-only domain-scoped S3 keys (no backfill of existing raw objects) | Rewriting raw keys violates WORM immutability | ✓ Validated (v2.0) — `_unclassified` fallback, dedup/lineage preserved |
| `routed_search()` as plain function dispatch (not QueryRouter class) | Function-over-class convention; simpler, no class-based alias complexity | ✓ Validated (Phase 15) — 25 unit tests, all surfaces wired |
| Query router default `auto` (classifier-driven) not `chunk` | Auto routing ships silently; ops can pin to `chunk` via KLAKE_ROUTER__DEFAULT_ROUTE=chunk without code change | ✓ Validated (Phase 15) — cheap rollback lever confirmed |
| No `both`/`merge` route — only single-path dispatch | Avoids merged-result complexity; tree and chunk are mutually exclusive per query | ✓ Validated (Phase 15) — D-09 prohibition verified in code review |

## Evolution

**After each phase:** Move validated requirements, log decisions, update context.

**After each milestone:** Full review of all sections, Core Value check, Out of Scope audit.

---
*Last updated: 2026-07-14 after v2.5 Phase 16 (OpenKB Export) complete — all v2.5 phases shipped, milestone complete*
