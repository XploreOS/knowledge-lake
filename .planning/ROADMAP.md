# Roadmap: Knowledge Lake Framework

## Overview

Build a tool-agnostic knowledge lake framework by first proving a single document can flow end-to-end (ingest → parse → chunk → embed → index → search) on top of the foundation registries, lineage, and plugin interfaces. Then widen each stage of that proven pipe — ingestion breadth (crawlers, uploads, discovery), parsing/cleaning/chunking quality, LLM enrichment and semantic search, then curation/datasets/export — and finish by shipping the healthcare domain pack that exercises the entire surface with real public sources.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation & End-to-End Spike** - Registries, immutable storage, plugin interfaces, and one document flowing through the full pipe on a one-command dev stack (completed 2026-07-03)
- [x] **Phase 2: Ingestion** - Sources, downloads, uploads, three crawler plugins, SearXNG discovery, dedup, and polite crawling (completed 2026-07-04)
- [x] **Phase 3: Parse, Clean & Chunk** - Multi-format parsing with fallback chain, torture-test validation, cleaning/dedup, and structure-aware chunking (completed 2026-07-05)
- [x] **Phase 4: Enrichment, Embedding & Search** - LiteLLM enrichment with caching and budget caps, configurable embeddings, Qdrant indexing, semantic search with citations (completed 2026-07-06)
- [x] **Phase 5: Curation, Datasets & Export** - Corpus quality filtering, dataset generation with lineage, and Parquet/JSONL/DuckDB exports (completed 2026-07-06)
- [ ] **Phase 6: Healthcare Domain Pack & Full-Surface Validation** - Healthcare pack with seed sources, complete CLI/API/Dagster surface, and 5-10 real sources verified end-to-end

## Phase Details

### Phase 1: Foundation & End-to-End Spike

**Goal**: One real document flows ingest → parse → chunk → embed → index → search as a thin vertical slice, on top of the foundation everything else depends on: typed config, S3 storage abstraction, content-addressed immutable raw zone, PostgreSQL registries with lineage, and plugin protocol interfaces
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: FOUND-01, FOUND-02, FOUND-03, FOUND-04, FOUND-05, FOUND-06, FOUND-07, FOUND-08, FOUND-09
**Success Criteria** (what must be TRUE):

  1. Operator runs a single `docker compose up` and the full stack (PostgreSQL, Qdrant, MinIO, LiteLLM, Dagster, API) comes up healthy with configuration loaded from .env via typed pydantic-settings
  2. A single test document flows end-to-end — ingested to the raw zone, parsed, chunked, embedded, indexed — and comes back from a semantic search query (thin spike, one path, no breadth)
  3. Operator can query the full lineage of the spike's chunks back to the raw source via CLI/API, with source ID, parent artifact ID, content hash, timestamp, pipeline version, and storage URI on every artifact
  4. Raw zone objects are content-addressed by SHA256 and re-writing or deleting existing raw content is refused — re-ingesting identical content is a registry-level no-op
  5. The spike's parser, embedder, and vector store are invoked through plugin protocol interfaces and swappable via configuration without touching core code, with the registry schema managed by Alembic migrations from the first table

**Plans**: 6/6 plans complete

- [x] 01-01-PLAN.md — Scaffold, typed config, six-service compose stack, Wave 0 test infra (FOUND-01, FOUND-02)
- [x] 01-02-PLAN.md — Registry, Alembic migration #1, prefixed UUIDv7 IDs, pipeline_version (FOUND-05, FOUND-06, FOUND-09)
- [x] 01-03-PLAN.md — S3 storage abstraction + content-addressed immutable raw zone (FOUND-03, FOUND-04)
- [x] 01-04-PLAN.md — Plugin Protocols + config resolver + Docling/local-ST/Qdrant built-ins (FOUND-08)
- [x] 01-05-PLAN.md — Plain-function pipeline + recursive-CTE lineage + klake CLI + demo spike (FOUND-07)
- [x] 01-06-PLAN.md — FastAPI search/lineage endpoints + Dagster asset wrap (FOUND-07, FOUND-01)

### Phase 2: Ingestion

**Goal**: As a domain researcher, I want to ingest any public resource (URL, file, or crawl) into the lake with provenance and dedup, so that I have a traceable raw zone of source material to build AI datasets from.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: INGEST-01, INGEST-02, INGEST-03, INGEST-04, INGEST-05, INGEST-06, INGEST-07, INGEST-08, INGEST-09
**Success Criteria** (what must be TRUE):

  1. User can register a source with domain assignment, download a URL, or upload a local file via CLI and API — each landing in the raw zone with SHA256, MIME type, source URL, timestamp, and license metadata recorded
  2. User can crawl a source with Crawl4AI producing LLM-ready markdown into raw/bronze, and can switch to Scrapy (structured sites) or Playwright (dynamic pages) as alternative crawler plugins via configuration
  3. Re-ingesting identical content (by normalized URL or content hash) is a no-op — no duplicate raw objects or registry entries
  4. Crawls respect robots.txt and apply per-host rate limits with retries and backoff; interrupted crawl jobs resume without re-fetching completed pages
  5. User can run a SearXNG discovery query and see candidate sources stored in the source registry for review

**Plans**: 6/6 plans complete
**Wave 1**

- [x] 02-01-PLAN.md — Source registration + single-URL/file ingest + dedup foundation; shared validate_public_url + normalize_url (INGEST-01, 02, 03, 08) [Wave 1]

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 02-02-PLAN.md — Crawler substrate: CrawlerPlugin protocol, crawl_states schema, put_bronze, robots + 3-tier rate-limit primitives (INGEST-04, 09) [Wave 2]

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 02-03-PLAN.md — Crawl4AI adapter + orchestrator (two-artifact lineage, resume, robots_blocked) + crawl CLI/API (INGEST-04, 08, 09) [Wave 3]

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 02-04-PLAN.md — Scrapy subprocess adapter + sitemap auto-selection (INGEST-05) [Wave 4]

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 02-05-PLAN.md — Playwright adapter + SPA selection/escalation + browser binaries (INGEST-06) [Wave 5]

**Wave 6** *(blocked on Wave 5 completion)*

- [x] 02-06-PLAN.md — SearXNG discovery: DiscoveryPlugin + auto-register + compose service (INGEST-07) [Wave 6]

### Phase 3: Parse, Clean & Chunk

**Goal**: Raw documents of any supported format become clean, structure-preserving, citation-traceable chunks — with parser quality proven against real healthcare documents before bulk processing
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: PARSE-01, PARSE-02, PARSE-03, PARSE-04, PARSE-05, CLEAN-01, CLEAN-02, CLEAN-03, CHUNK-01, CHUNK-02, CHUNK-03, CHUNK-04
**Success Criteria** (what must be TRUE):

  1. User can parse PDF, HTML, DOCX, Markdown, CSV, XLSX, JSON, and XML documents to structured Markdown/tables via Docling, preserving page numbers, headings, sections, and table boundaries where the format allows
  2. When Docling fails or scores low, parsing falls back through Unstructured then Tika automatically, and every parse result gets a quality score in the registry with low scores flagged for review
  3. A torture-test corpus of representative healthcare documents runs through the parser chain and passes quality gates before any bulk ingestion
  4. Cleaned documents have boilerplate removed and whitespace normalized (citations preserved), language detected and recorded, and exact (hash) plus near-duplicates (MinHash) flagged across the corpus
  5. Chunks respect heading hierarchy and configurable token size/overlap, never split tables mid-table, and each records parent document, section path, and page reference

**Plans**: 3/3 plans complete

Plans:
**Wave 1**

- [x] 03-01-PLAN.md — Multi-format parser chain, quality scorer, Alembic 0006 migration, torture corpus fixtures and test suite (PARSE-01..05)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 03-02-PLAN.md — Boilerplate removal, language detection, MinHash near-dup flagging, cleaned_document artifact (CLEAN-01..03)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 03-03-PLAN.md — Token-aware chunking with table atomicity, Dagster clean/chunk assets, CLI/API parse-clean-chunk commands (CHUNK-01..04)

### Phase 4: Enrichment, Embedding & Search

**Goal**: Chunks become enriched, embedded, and semantically searchable — with all LLM traffic routed through LiteLLM task aliases, cached, and budget-capped so enrichment cost can never explode
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: ENRICH-01, ENRICH-02, ENRICH-03, ENRICH-04, ENRICH-05, ENRICH-06, INDEX-01, INDEX-02, INDEX-03
**Success Criteria** (what must be TRUE):

  1. Enriched documents show title, summary, document type, organization, jurisdiction, keywords, entities, and quality score — with deterministic extraction (title, dates, headings) running before any LLM call, and all LLM calls routed through LiteLLM task aliases (cheap_model, strong_model, eval_model, embedding_model) with no provider IDs in business logic
  2. Re-running enrichment on unchanged content is a no-op (cached by prompt version + input hash), and enrichment jobs halt gracefully with clear status when the configurable LLM budget cap is hit
  3. User can switch embedding providers (local sentence-transformers ↔ LiteLLM API) via configuration and chunks are indexed into Qdrant with payload metadata (domain, document, section, tags)
  4. User can run semantic search via CLI and API returning chunks with scores and source citations that trace back to document, section, and page
  5. Qdrant collections are managed via aliases tracked in the registry, and a full reindex completes without search downtime

**Plans**: 3/3 plans complete

Plans:
**Wave 1**

- [x] 04-01-PLAN.md — Registry schema (llm_spend, vector_collections, quality_score mapping), EnrichSettings/IndexSettings, repo.py foundation (ENRICH-05, INDEX-02) [Wave 1]

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 04-02-PLAN.md — Enrichment vertical slice: deterministic extraction, cached/budget-capped LiteLLM call, CLI/API/Dagster (ENRICH-01..06) [Wave 2]

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 04-03-PLAN.md — Index/search vertical slice: Qdrant alias + zero-downtime reindex, payload extension, filtered search (INDEX-01..03) [Wave 3]

### Phase 5: Curation, Datasets & Export

**Goal**: The enriched corpus becomes AI-ready deliverables — curated pretraining corpus, generated fine-tuning and RAG-eval datasets with full lineage, and standard export formats consumable by downstream tools
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: CURATE-01, CURATE-02, CURATE-03, DATA-01, DATA-02, DATA-03, EXPORT-01, EXPORT-02, EXPORT-03
**Success Criteria** (what must be TRUE):

  1. User can run DataTrove-style quality filters (length, repetition, boilerplate heuristics) and corpus-wide deduplication producing a cleaned training corpus, with composite quality scores per document and source queryable via CLI/API
  2. User can generate citation-grounded Q&A / RAG-eval datasets from enriched chunks and instruction-tuning datasets from enriched documents via LiteLLM, and every generated example records lineage to its source chunks/documents
  3. User can export the RAG corpus (chunks + metadata) to Parquet and query it via DuckDB
  4. User can export a pretraining-style text corpus to JSONL and fine-tuning datasets to JSONL in standard chat/instruction formats

**Plans**: 3/3 plans complete

Plans:
**Wave 1**

- [x] 05-01-PLAN.md — Curation: DataTrove quality filters, corpus-wide MinHash dedup, composite quality score, CLI/API/Dagster (CURATE-01, 02, 03) [Wave 1]

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 05-02-PLAN.md — Dataset generation: per-chunk Q&A (eval_model) + per-document instruction-tuning (strong_model), dataset_examples lineage, CLI/API/Dagster (DATA-01, 02, 03) [Wave 2]

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 05-03-PLAN.md — Export: RAG corpus Parquet + DuckDB query, pretrain JSONL, fine-tune chat-format JSONL, CLI/API/Dagster (EXPORT-01, 02, 03) [Wave 3]

### Phase 6: Healthcare Domain Pack & Full-Surface Validation

**Goal**: Healthcare ships as the first domain pack loaded purely by convention, and the complete framework surface (CLI, API, Dagster) is proven by running 5-10 real healthcare sources end-to-end through every pipeline stage
**Mode:** mvp
**Depends on**: Phase 5
**Requirements**: DOMAIN-01, DOMAIN-02, DOMAIN-03, DOMAIN-04, IFACE-01, IFACE-02, IFACE-03
**Success Criteria** (what must be TRUE):

  1. Domain packs load from a directory convention (domain.yaml, sources.yaml, taxonomy.yaml, prompts/, validators/) with no core code changes — verified by loading the healthcare pack
  2. The healthcare pack ships with 25+ curated seed sources (HL7 FHIR, US Core, CMS, HIPAA/OCR, ONC/USCDI, CDC, FDA, NIH/NLM, ICD-10-CM, HCPCS, LOINC, RxNorm, NDC, NPPES, and related), plus enrichment/QA prompts, taxonomy, and a validator module
  3. 5-10 healthcare sources spanning HTML, PDF, and CSV/JSON flow end-to-end — ingest → parse → clean → chunk → enrich → index → search → export — with lineage intact at every step
  4. The `klake` CLI covers init, add-source, discover, crawl, upload, parse, clean, chunk, enrich, index, search, curate, dedupe, generate-dataset, and export; FastAPI exposes sources, discover, crawl-jobs, uploads, documents, pipeline actions, search, curation, datasets, and exports endpoints with OpenAPI docs
  5. All pipeline stages run as Dagster assets/jobs with retries and are observable from the Dagster UI

**Plans**: 3/4 plans executed

Plans:
**Wave 1**

- [x] 06-01-PLAN.md — DomainLoader class + healthcare pack content (domain.yaml, sources.yaml, taxonomy.yaml, prompts, validator) (DOMAIN-01, DOMAIN-02, DOMAIN-03)
- [x] 06-02-PLAN.md — Domain prompt override in pipeline/enrich.py + DomainSettings (DOMAIN-01, DOMAIN-03)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 06-03-PLAN.md — klake init + klake index CLI, 8 new API endpoints (IFACE-01, IFACE-02, DOMAIN-01)

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 06-04-PLAN.md — RetryPolicy on 12 Dagster assets, healthcare_e2e_job, 5-source E2E test (IFACE-03, DOMAIN-04)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation & End-to-End Spike | 6/6 | Complete    | 2026-07-03 |
| 2. Ingestion | 6/6 | Complete    | 2026-07-04 |
| 3. Parse, Clean & Chunk | 3/3 | Complete    | 2026-07-05 |
| 4. Enrichment, Embedding & Search | 3/3 | Complete    | 2026-07-06 |
| 5. Curation, Datasets & Export | 3/3 | Complete    | 2026-07-06 |
| 6. Healthcare Domain Pack & Full-Surface Validation | 3/4 | In Progress|  |

## Coverage

All 55 v1 requirements mapped to exactly one phase:

| Phase | Requirements | Count |
|-------|--------------|-------|
| 1 | FOUND-01..09 | 9 |
| 2 | INGEST-01..09 | 9 |
| 3 | PARSE-01..05, CLEAN-01..03, CHUNK-01..04 | 12 |
| 4 | ENRICH-01..06, INDEX-01..03 | 9 |
| 5 | CURATE-01..03, DATA-01..03, EXPORT-01..03 | 9 |
| 6 | DOMAIN-01..04, IFACE-01..03 | 7 |

---
*Roadmap created: 2026-07-02*
