# Knowledge Lake Framework

## What This Is

A reusable, domain-agnostic framework that orchestrates best-in-class open-source tools to turn public, private, and manually uploaded domain resources into AI-ready assets. It owns registries, lineage, domain packs, and export contracts — external tools (parsers, crawlers, vector stores, LLM gateways) are treated as replaceable plugins. Healthcare is the first domain pack.

## Core Value

Every domain resource ingested must be traceable from raw source through every transformation to its final AI-ready output — and the framework must remain tool-agnostic so any processor can be swapped without breaking lineage.

## Current State (v2.6-in-progress, Phase 17 complete 2026-07-16)

- **Shipped:** v1.0 MVP (Phases 1–6) · v2.0 Agent-Ready Lake (Phases 7–12) · v2.5 PageIndex Plugin Integration (Phases 13–16 — Tree Index, Tree Retrieval, Query Router, OpenKB Export) · Phase 17 complete (Close the Bypass + Measurement)
- **Source lines:** ~26,000 Python (src) + ~24,300 (tests)
- **Tests:** 994 passing, 0 failed, 0 xpassed (`xfail_strict = true` active) plus integration/e2e suites (Qdrant/Postgres-gated)
- **Pipeline:** ingest → parse → **clean (now active on all paths)** → chunk/tree_index → enrich → embed → index → curate → generate-dataset → export → wiki
- **Agent surface:** MCP server (stdio + Streamable HTTP), 11 intent-level tools over one registry; OpenAPI + OpenAI tool defs from a single Pydantic schema source; 4 Claude Code skills
- **Retrieval:** hybrid BM25 + dense (RRF), mode-switchable (`hybrid|dense|sparse`); two-stage tree retrieval; query router dispatching between chunk and tree paths (`chunk|tree|two_stage|auto`)
- **Query routing:** `classify_route()` heuristic classifier (section/comparison/structural triggers) + `routed_search()` dispatcher with auto-fallback on empty tree results; KLAKE_ROUTER__DEFAULT_ROUTE env var
- **Wiki export:** `compile_wiki()` builds interlinked Markdown knowledge base from enrichment metadata — IDF-filtered entity cross-links, per-document summary pages, concept pages, root index; manifest-based incremental rebuild; archive export for Obsidian vault import
- **Scheduling:** Dagster re-crawl sensor with normalized silver-text change gate + tick-storm dedup
- **Storage:** domain/source-scoped S3 keys + object tags; gold zone segmented by domain × dataset type (including `wiki/` prefix)
- **CLI:** `klake` Typer app extended with `crawl-all`, `set-schedule`, `mcp`, `openapi`, `search --mode --route`, `reindex --hybrid`, `export-wiki`
- **API:** FastAPI (Swagger at /docs) extended with `/crawl-all`, mode-aware and route-aware search, `/export-wiki`
- **Domain packs:** 1 (healthcare, 28 curated sources)  ·  **Dagster assets:** 12+ with RetryPolicy
- **Quality gates:** all v2.5 phases verified `passed`, threat-secured, Nyquist-compliant; v2.5 milestone audit PASSED (19/19 requirements, 5/5 E2E flows); E2E gap analysis closed — all 19 findings resolved
- **Tech debt:** Typer <0.25.0 pin; MCP `_search_handler` crashes on non-empty results (needs `dataclasses.asdict(h)`); `mode` param dual semantics on tree path; domain path-traversal regex duplicated across 3 modules; `sources.config["domain"]` dual-write pending removal; domain packs cannot contribute Dagster jobs (KL-16); Dagster code-location reload needed for new sensors/assets
- **Phase 17 complete:** Clean-stage bypass closed on both Dagster and CLI paths; WR-05 content hash scoping applied; conservation invariant (`rejected+kept==sections_considered`) wired; `klake quality-audit` harness ships a reproducible per-source garbage-rate table. 25/25 must-haves verified passed 2026-07-16.
- **Phase 18 complete:** Re-crawl change gate decoupled from `BOILERPLATE_PATTERNS` — `_GATE_BOILERPLATE_PATTERNS` frozen in `crawl.py`, `_gate_normalize()` added, `remove_boilerplate` import removed, byte-stability pinning test ships. 5/5 must-haves verified passed 2026-07-16.

## Next Milestone: v2.6 Data Quality & Enrichment

**Goal:** Stop garbage content from reaching the silver zone, chunking, tree index, and gold export — so the RAG corpus is trustworthy rather than merely populated.

**Target features:**
- Close the clean-stage bypass (both Dagster and `klake process` paths)
- Section-level boilerplate classification with substance annotations
- Minimum-substance gate at chunk (with domain-pack allowlists)
- Quality predicate module (pure, deterministic, no I/O)
- Index-time deduplication (one vector per unique text, lineage preserved per WR-05)
- Quality gate on gold RAG export (chunk-level, not document-level)
- Re-runnable quality audit harness + must-not-reject CI fixtures

**Scope decisions:** Crawler extraction DEFERRED (no-op today; section classifier covers superset) · forward-only CONFIRMED (test data wiped before production via `docker compose down -v`) · dedup at index time (after substance gate) · research complete. Full context: `.planning/MILESTONE-CONTEXT.md`, requirements: `.planning/REQUIREMENTS.md`. Phase numbering continues at **Phase 17**.

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

### Validated (v2.5 — PageIndex Plugin Integration, milestone complete 2026-07-15)

**Tree Indexing**
- [x] TREE-01: Hierarchical tree index (JSON) from any parsed document's sections, silver-zone artifact with full lineage — Phase 13
- [x] TREE-02: Tree index skipped on content-hash match (no redundant LLM calls) — Phase 13
- [x] TREE-03: Each node carries title, summary, page range, children; deterministic mode uses heading text — Phase 13
- [x] TREE-04: LLM-generated node summaries as opt-in mode, gated by LlmSpend budget cap — Phase 13
- [x] TREE-05: Tree index runs as a Dagster asset parallel to chunking (fan-out from clean_document) — Phase 13

**Tree Retrieval**
- [x] RETR-04: Two-stage search — Qdrant document shortlist (stage 1) + per-document tree traversal (stage 2) — Phase 14
- [x] RETR-05: Heuristic tree traversal (keyword matching + DFS) with no LLM calls — Phase 14
- [x] RETR-06: LLM-guided tree navigation over node summaries (opt-in mode) — Phase 14
- [x] RETR-07: Candidate trees loaded in parallel (asyncio) with configurable concurrency limit — Phase 14
- [x] RETR-08: Hits carry page-level citations and a `citation_source: tree` discriminator — Phase 14

**Query Routing**
- [x] ROUTE-01: `routed_search()` dispatcher with per-call override → settings.router.default_route fallthrough — Phase 15
- [x] ROUTE-02: `classify_route()` heuristic classifier (section_page_ref, comparison_multihop, structural_breadth) — Phase 15
- [x] ROUTE-03: chunk/tree/two_stage/auto dispatch with D-05 auto-fallback semantics — Phase 15
- [x] ROUTE-04: route param wired to REST (`?route=`), CLI (`--route`), MCP, and OpenAPI spec — Phase 15

**OpenKB Export**
- [x] KB-01: Interlinked wiki of Markdown pages with `[[wikilinks]]` in the gold zone — Phase 16
- [x] KB-02: Per-document summary pages, cross-document concept pages, and a root index — Phase 16
- [x] KB-03: Entity cross-linking on IDF-filtered enrichment entities (only specific terms link) — Phase 16
- [x] KB-04: Incremental wiki compilation — manifest diff rebuilds only affected pages — Phase 16
- [x] KB-05: Wiki export via CLI (`klake export-wiki`) and API (`POST /export-wiki`) — Phase 16

### Active (v2.6 — Data Quality & Enrichment)

Requirements are defined by `/gsd-new-milestone` (research → requirements → roadmap). Target areas:

- [ ] Cleaned text consumed by chunk/tree/enrich (close the clean-stage bypass)
- [ ] Crawler-level boilerplate stripping (forward-only; raw zone immutability preserved)
- [ ] Section-level boilerplate classification (deterministic-first)
- [ ] Minimum-substance gate at chunk (no floor exists today — `ChunkSettings` has only max/overlap/tokenizer)
- [ ] Index-time dedup preserving per-document chunk lineage (WR-05)
- [ ] Quality gate on gold RAG corpus export

### Deferred to a future milestone

- EVAL-01/02 (RAGAS/Promptfoo eval harness; Langfuse/Arize observability), SDK-01 (klake-client SDK), DOMAIN-05/06 (multi-domain conflict resolution; pack registry + versioning), DISCOVER-01 (SearXNG auto-discovery scheduling), UI-02 (admin/crawl analytics dashboard), VERSION-01 (lakeFS/DVC data versioning), SITEMAP-01 (sitemap-first crawl strategy)
- Deferred at v2.5: ROUTE-05/06 (LLM-based routing for ambiguous queries; routing telemetry + feedback loop), KB-06/07/08 (watch mode; wiki lint for contradictions/orphans/staleness; multi-turn chat grounded in wiki), TREE-06/07 (tree schema versioning + migration; PageIndex File System meta-tree over the corpus)
- **QUALITY-01** (quality-score search propagation) — deferred since v2.0; overlaps v2.6 scope and should be reconsidered during v2.6 requirements rather than carried forward blindly

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
- v2.0 shipped 2026-07-12 (6 phases, 38 plans, 252 commits)
- v2.5 shipped 2026-07-15 (4 phases, 14 plans, 190 commits, 243 files changed, +32,060/−2,377)
- First end-to-end run on real healthcare data (34 sources, 4,499 chunks) proved the pipeline works mechanically but produces ~28% garbage content — mechanical correctness and data quality are separate problems, and only the former was being tested
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
| Tree index as a new artifact type behind `IndexerPlugin`, not a chunker replacement | Trees and chunks are complementary; plugin seam keeps PageIndex swappable like every other external tool | ✓ Validated (v2.5) — entry-point group + Dagster fan-out, chunking untouched |
| Deterministic tree building first, LLM summaries opt-in | Project "deterministic first" constraint; heading text is a serviceable summary at zero cost | ✓ Validated (v2.5) — same pattern held for traversal (heuristic DFS default, LLM-nav opt-in) |
| Heuristic hits always computed before LLM-nav, never replaced by it | LLM navigation must never be able to produce a worse result than the deterministic path | ✓ Validated (Phase 14) — invalid node_ids discarded, unmentioned hits retained; LLM-nav cannot raise |
| Two-stage retrieval reuses chunk `search()` unchanged for stage 1 | Avoids forking retrieval logic; the shortlist is exactly the existing search | ✓ Validated (Phase 14) — no changes to `search()` |
| PageIndex pinned to pre-release `0.3.0.dev3` | No stable release available; vendoring fallback planned | ⚠ Revisit — pre-release API may change; vendoring fallback still untested |
| Wiki cross-links gated by IDF, not raw entity match | Linking on common terms produces a hairball; IDF keeps links meaningful | ✓ Validated (Phase 16) — threshold still needs empirical tuning for link density |
| `xfail_strict = true` enabled repo-wide | A stale xfail marker hid two API endpoints returning 500s for months | ✓ Validated (2026-07-15) — a test that passes while marked xfail now fails the build |
| Docker base pinned to `.python-version` (`python:3.12-slim`) | An unbuildable `python:3.14-slim` base silently kept a 13-day-old container alive, masking real bugs | ✓ Validated (2026-07-15) — CI now builds the api image; `/health` reports running version |
| Chunk dedup key includes parent (`{parsed_artifact_id}:{text}`) — WR-05 | Prevents lineage corruption when identical text appears in different documents | ⚠ Revisit — directly causes 653 duplicate embeddings (14% of corpus); v2.6 resolves via index-time dedup rather than overturning this |
| Clean stage writes `cleaned_document` but chunk/tree/enrich read `parsed_doc` | Not a decision — an unintended bypass found 2026-07-15 | ✗ Defect — boilerplate removal reaches only the pretrain path; primary driver of v2.6 |

## Evolution

**After each phase:** Move validated requirements, log decisions, update context.

**After each milestone:** Full review of all sections, Core Value check, Out of Scope audit.

---
*Last updated: 2026-07-16 after Phase 18 (Gate Decouple) verified passed*
