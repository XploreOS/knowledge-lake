# Knowledge Lake Framework

## What This Is

A reusable, domain-agnostic framework that orchestrates best-in-class open-source tools to turn public, private, and manually uploaded domain resources into AI-ready assets. It owns registries, lineage, domain packs, and export contracts — external tools (parsers, crawlers, vector stores, LLM gateways) are treated as replaceable plugins. Healthcare is the first domain pack.

## Core Value

Every domain resource ingested must be traceable from raw source through every transformation to its final AI-ready output — and the framework must remain tool-agnostic so any processor can be swapped without breaking lineage.

## Requirements

### Validated

- ✓ Source registry, document registry, artifact registry with full lineage — Phase 1
- ✓ Raw/bronze zone with immutable raw storage (SHA256-keyed, WORM policy) — Phase 1
- ✓ Document parsing via Docling as plugin — Phase 1
- ✓ Configurable embeddings (local sentence-transformers) — Phase 1
- ✓ Vector search via Qdrant as a plugin — Phase 1
- ✓ FastAPI service with health + search + lineage endpoints — Phase 1
- ✓ Typer CLI (`klake`) for core operations — Phase 1
- ✓ Dagster pipeline orchestration (assets + resources wired) — Phase 1
- ✓ S3-compatible object storage (MinIO dev) — Phase 1
- ✓ PostgreSQL metadata registry — Phase 1
- ✓ All LLM calls routed through LiteLLM with task-based model aliases — Phase 1
- ✓ Automated crawling via Crawl4AI, Scrapy, Playwright as swappable plugins — Phase 2
- ✓ Manual file upload + single-URL ingest with provenance and SHA256 dedup — Phase 2
- ✓ SearXNG-based source discovery with auto-registration — Phase 2
- ✓ Robots.txt, rate-limit, SSRF guard, resumable crawl jobs — Phase 2

### Active

- [ ] Domain-agnostic core with pluggable domain packs
- [ ] Source registry, document registry, artifact registry with full lineage
- [ ] Raw/bronze/silver/gold data lake zones with immutable raw storage
- [ ] Automated crawling via Crawl4AI, Scrapy, Playwright as plugins
- [ ] Manual file upload into the knowledge lake
- [ ] Document parsing via Docling/Unstructured/Tika as plugins
- [ ] Cleaning, normalization, deduplication pipeline
- [ ] Section-aware, token-aware, table-aware chunking
- [ ] LLM-based metadata enrichment through LiteLLM gateway
- [ ] Configurable embeddings (local sentence-transformers or LiteLLM API)
- [ ] Vector search via Qdrant as a plugin
- [ ] Corpus curation for pretraining (DataTrove/NeMo Curator-style filtering)
- [ ] Dataset generation (fine-tuning, RAG eval, instruction tuning, classification, entity extraction)
- [ ] Export to Parquet, JSONL, DuckDB
- [ ] FastAPI service with full CRUD and pipeline trigger endpoints
- [ ] Typer CLI (`klake`) for all operations
- [ ] Dagster pipeline orchestration from day 1
- [ ] S3-compatible object storage (MinIO dev, AWS S3 production)
- [ ] PostgreSQL metadata registry
- [ ] Healthcare domain pack with 25+ authoritative source seeds
- [ ] All LLM calls routed through LiteLLM with task-based model aliases
- [ ] SearXNG-based source discovery
- [ ] Quality scoring at document and source level
- [ ] Language detection
- [ ] Resumable, idempotent jobs with retries and rate limits

### Out of Scope

- Real-time streaming ingestion — batch-first for MVP
- Multi-tenant auth / RBAC — single user/small team for now
- Admin UI / web dashboard — CLI + API + Swagger only for MVP
- Neo4j knowledge graph — deferred to Phase 3
- Argilla/Label Studio human review — deferred to Phase 2-3
- OpenMetadata/DataHub catalog integration — deferred to Phase 3
- lakeFS/DVC data versioning — deferred to Phase 3
- RAGFlow/Dify/AnythingLLM demo UI — deferred to Phase 3
- Hybrid BM25/OpenSearch retrieval — deferred to Phase 2
- PHI/PII handling — only in explicitly controlled test environments
- Mobile or desktop clients

## Context

- Running on DigitalOcean Ubuntu 24.04 droplet with Docker
- Using AWS Bedrock models through LiteLLM
- Healthcare domain is deeply familiar (HL7 FHIR, CMS, HIPAA, ONC, etc.)
- Closest analogues: DataTrove (pretraining corpus), RAGFlow (RAG), Dagster (orchestration), Docling (parsing)
- This framework orchestrates those tools rather than competing with them
- Plugin architecture: every external tool is replaceable without breaking core registries or lineage

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
| Dagster over Prefect for orchestration | Better asset-based model for data pipelines, built-in lineage concepts | Validated Phase 1 — 5 SDAs materialize cleanly |
| Docling as primary parser | Best balance of format support, quality, and open-source maturity | Validated Phase 1 — parses HIPAA Security Rule PDF with section extraction |
| S3-compatible storage (not local filesystem) | Production-portable, supports MinIO dev and AWS S3 prod | Validated Phase 1 — content-addressed put_raw + WORM policy working |
| Plugin architecture for all external tools | Avoid lock-in, enable swapping parsers/crawlers/vector stores | Validated Phase 1 — entry-point resolver + 3 built-ins registered |
| LiteLLM as sole model gateway | Unified interface for Bedrock, OpenAI, Anthropic, local models | Validated Phase 1 — LiteLLMEmbedder uses embedding_model alias only |
| PostgreSQL for metadata registry (not OpenMetadata yet) | Simpler for MVP, migrate to catalog tool later | Validated Phase 1 — Alembic migration #1 + self-referencing artifacts node table |
| DataTrove-style curation over custom filters | Proven at scale for pretraining corpus preparation | — Pending (Phase 5) |
| No UI for MVP | CLI + API is sufficient for single user, avoids frontend complexity | Validated Phase 1 — klake CLI + FastAPI /search /lineage working |
| Healthcare first domain pack | Deeply familiar domain, rich public data, high value for RAG/fine-tuning | — Pending (Phase 6) |
| Typer downgraded to <0.25.0 | docling-core has a conflicting dependency on typer | Phase 1 deviation — RESEARCH had 0.26.8 pinned; uv resolved to <0.25.0 |
| uuid-utils approved (not uuid6) | PyPI legitimacy verified by human gate — github.com/aminalaee/uuid-utils v0.16.2 | Phase 1 — isolated to ids.py for easy stdlib swap in Python 3.14 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-04 after Phase 2 — Ingestion*
