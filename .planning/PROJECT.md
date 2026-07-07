# Knowledge Lake Framework

## What This Is

A reusable, domain-agnostic framework that orchestrates best-in-class open-source tools to turn public, private, and manually uploaded domain resources into AI-ready assets. It owns registries, lineage, domain packs, and export contracts — external tools (parsers, crawlers, vector stores, LLM gateways) are treated as replaceable plugins. Healthcare is the first domain pack.

## Core Value

Every domain resource ingested must be traceable from raw source through every transformation to its final AI-ready output — and the framework must remain tool-agnostic so any processor can be swapped without breaking lineage.

## Current State (v1.0 — shipped 2026-07-07)

- **Version:** v1.0 — Knowledge Lake Framework MVP
- **Source lines:** ~17,150 Python
- **Tests:** 324 unit + integration + e2e
- **Pipeline:** ingest → parse → clean → chunk → enrich → embed → index → curate → generate-dataset → export
- **CLI commands:** 20 (`klake` Typer app)
- **API endpoints:** 26 (FastAPI, Swagger at /docs)
- **Domain packs:** 1 (healthcare, 28 curated sources)
- **Dagster assets:** 12, all with RetryPolicy
- **Tech debt:** Typer <0.25.0 pin; E2E test contamination workaround; Dagster requires container rebuild

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

### Active (v2.0 candidates)

- [ ] RAGAS + Promptfoo + Arize eval harness — deferred from Phase 5
- [ ] Multi-domain pack support (conflict resolution) — deferred from Phase 6
- [ ] Hybrid BM25 + dense search (RETR-01) — v2 requirement
- [ ] Domain pack registry/catalog (versioning, publishing) — future milestone
- [ ] OpenMetadata/DataHub catalog integration — when catalog features needed

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

## Evolution

**After each phase:** Move validated requirements, log decisions, update context.

**After each milestone:** Full review of all sections, Core Value check, Out of Scope audit.

---
*Last updated: 2026-07-07 after v1.0 milestone*
