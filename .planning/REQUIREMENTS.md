# Requirements: Knowledge Lake Framework

**Defined:** 2026-07-02
**Core Value:** Every domain resource ingested must be traceable from raw source through every transformation to its final AI-ready output — and the framework must remain tool-agnostic so any processor can be swapped without breaking lineage.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Foundation

- [x] **FOUND-01**: Operator can bring up the full stack (PostgreSQL, Qdrant, MinIO, LiteLLM, Dagster, API) with a single `docker compose up`
- [x] **FOUND-02**: All configuration loads from environment variables / .env via typed pydantic-settings with validated defaults
- [x] **FOUND-03**: Storage layer writes/reads objects to any S3-compatible backend (MinIO dev, AWS S3 prod) through one abstraction
- [x] **FOUND-04**: Raw zone objects are content-addressed (SHA256) and never modified or deleted after write
- [x] **FOUND-05**: PostgreSQL registry stores sources, documents, artifacts, chunks, jobs, datasets, and lineage events with stable IDs and content hashes
- [x] **FOUND-06**: Every artifact records source ID, parent artifact ID, content hash, timestamp, pipeline version, and storage URI
- [x] **FOUND-07**: Operator can query full lineage of any artifact back to its raw source via CLI/API
- [x] **FOUND-08**: Parsers, crawlers, embedders, and vector stores are pluggable behind protocol interfaces and swappable via configuration
- [x] **FOUND-09**: Registry schema is versioned with Alembic migrations from the first table

### Ingestion

- [x] **INGEST-01**: User can register a source URL with domain assignment via CLI and API
- [x] **INGEST-02**: User can download a single URL into the raw zone with SHA256, MIME type, source URL, timestamp, and license metadata recorded
- [x] **INGEST-03**: User can upload a local file into the raw zone with the same provenance metadata
- [x] **INGEST-04**: User can crawl a source with Crawl4AI producing LLM-ready markdown into the raw/bronze zones
- [x] **INGEST-05**: User can crawl structured sites with Scrapy as an alternative crawler plugin
- [x] **INGEST-06**: User can crawl dynamic pages with Playwright as an alternative crawler plugin
- [x] **INGEST-07**: User can discover candidate sources via SearXNG search query and store them in the source registry
- [x] **INGEST-08**: Ingestion deduplicates by normalized URL and content hash — re-ingesting identical content is a no-op
- [x] **INGEST-09**: Crawler respects robots.txt and applies per-host rate limits with retries and backoff

### Parsing

- [x] **PARSE-01**: User can parse PDF, HTML, DOCX, Markdown, CSV, XLSX, JSON, and XML documents to structured Markdown/tables via Docling
- [x] **PARSE-02**: Parsing falls back through a chain (Docling → Unstructured → Tika) when the primary parser fails or scores low
- [x] **PARSE-03**: Parsed output preserves page numbers, headings, sections, and table boundaries where the format allows
- [x] **PARSE-04**: Each parse result gets a quality score recorded in the registry; low scores flag documents for review
- [x] **PARSE-05**: A torture-test corpus of representative healthcare documents validates parser behavior before bulk ingestion

### Cleaning

- [x] **CLEAN-01**: Cleaning removes boilerplate and normalizes whitespace while preserving citations and provenance
- [x] **CLEAN-02**: Documents get language detection recorded in the registry
- [x] **CLEAN-03**: Exact duplicates (hash) and near-duplicates (MinHash) are detected and flagged across the corpus

### Chunking

- [x] **CHUNK-01**: User can chunk documents with section-aware strategy that respects heading hierarchy
- [x] **CHUNK-02**: Chunking is token-aware with configurable size/overlap per domain pack
- [x] **CHUNK-03**: Tables are chunked atomically — never split mid-table
- [x] **CHUNK-04**: Every chunk records parent document, section path, and page reference for citation traceability

### Enrichment

- [x] **ENRICH-01**: All LLM calls route through LiteLLM using task-based aliases (cheap_model, strong_model, eval_model, embedding_model) with no provider IDs in business logic
- [x] **ENRICH-02**: Deterministic extraction (title, dates, headings) runs before any LLM enrichment
- [x] **ENRICH-03**: LLM enrichment produces title, summary, document type, organization, jurisdiction, keywords, entities, and quality score per document
- [x] **ENRICH-04**: Enrichment results are cached by prompt version + input hash — re-running is a no-op unless prompts change
- [x] **ENRICH-05**: LLM spend is capped by configurable budget limits; jobs halt gracefully when exceeded
- [x] **ENRICH-06**: Embeddings are generated via configurable provider (local sentence-transformers or LiteLLM API)

### Indexing & Search

- [x] **INDEX-01**: Chunks with embeddings are indexed into Qdrant with payload metadata (domain, document, section, tags)
- [x] **INDEX-02**: Qdrant collections are managed via aliases and tracked in the registry, enabling reindexing without downtime
- [x] **INDEX-03**: User can run semantic search via CLI and API returning chunks with scores and source citations

### Curation & Datasets

- [x] **CURATE-01**: User can run DataTrove-style quality filters over the corpus (length, repetition, boilerplate heuristics)
- [x] **CURATE-02**: User can run corpus-wide deduplication producing a cleaned training corpus
- [x] **CURATE-03**: Documents and sources get composite quality scores queryable via CLI/API
- [x] **DATA-01**: User can generate citation-grounded Q&A / RAG-eval datasets from enriched chunks via LiteLLM
- [x] **DATA-02**: User can generate instruction-tuning datasets from enriched documents
- [x] **DATA-03**: Generated dataset examples record lineage to their source chunks/documents

### Export

- [x] **EXPORT-01**: User can export the RAG corpus (chunks + metadata) to Parquet queryable via DuckDB
- [x] **EXPORT-02**: User can export pretraining-style text corpus to JSONL
- [x] **EXPORT-03**: User can export fine-tuning datasets to JSONL in standard chat/instruction formats

### Interfaces

- [x] **IFACE-01**: `klake` CLI covers init, add-source, discover, crawl, upload, parse, clean, chunk, enrich, index, search, curate, dedupe, generate-dataset, and export
- [x] **IFACE-02**: FastAPI exposes sources, discover, crawl-jobs, uploads, documents, pipeline actions, search, curation, datasets, and exports endpoints with OpenAPI docs
- [x] **IFACE-03**: Pipeline stages run as Dagster assets/jobs with retries, observable from the Dagster UI

### Domain Packs

- [x] **DOMAIN-01**: Domain packs load from a directory convention (domain.yaml, sources.yaml, taxonomy.yaml, prompts/, validators/) without core code changes
- [x] **DOMAIN-02**: Healthcare pack ships with curated seed sources spanning HL7 FHIR, US Core, CMS, HIPAA/OCR, ONC/USCDI, CDC, FDA, NIH/NLM, ICD-10-CM, HCPCS, LOINC, RxNorm, NDC, NPPES, and related public resources
- [x] **DOMAIN-03**: Healthcare pack includes enrichment/QA prompts, taxonomy, and a validator module
- [x] **DOMAIN-04**: 5-10 healthcare sources across formats (HTML, PDF, CSV/JSON) flow end-to-end: ingest → parse → clean → chunk → enrich → index → search → export

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Retrieval

- **RETR-01**: Hybrid dense + sparse (BM25) search
- **RETR-02**: OpenSearch integration for full-text search

### Review & Governance

- **REVIEW-01**: Argilla integration for human feedback and preference data
- **REVIEW-02**: Label Studio integration for labeling workflows
- **GOV-01**: OpenMetadata/DataHub catalog integration
- **GOV-02**: lakeFS/DVC data versioning

### Knowledge Graph

- **KG-01**: Neo4j entity-relationship graph from extracted entities

### UI

- **UI-01**: Demo/admin UI (RAGFlow/Dify or custom dashboard)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Real-time streaming ingestion | Batch-first architecture; streaming adds complexity without MVP value |
| Multi-tenant auth / RBAC | Single user/small team; LiteLLM key is the only secret |
| Custom parser/vector DB/crawler implementations | Orchestrate mature tools, never reinvent them |
| PHI/PII ingestion | Only public data; PHI restricted to controlled test environments |
| Crawling private/restricted resources | Legal guardrail — robots.txt and licenses respected |
| Custom embedding model training | Use off-the-shelf models; training is a downstream consumer concern |
| Mobile/desktop clients | Server-side framework only |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FOUND-01 | Phase 1 | Complete |
| FOUND-02 | Phase 1 | Complete |
| FOUND-03 | Phase 1 | Complete |
| FOUND-04 | Phase 1 | Complete |
| FOUND-05 | Phase 1 | Complete |
| FOUND-06 | Phase 1 | Complete |
| FOUND-07 | Phase 1 | Complete |
| FOUND-08 | Phase 1 | Complete |
| FOUND-09 | Phase 1 | Complete |
| INGEST-01 | Phase 2 | Complete |
| INGEST-02 | Phase 2 | Complete |
| INGEST-03 | Phase 2 | Complete |
| INGEST-04 | Phase 2 | Complete |
| INGEST-05 | Phase 2 | Complete |
| INGEST-06 | Phase 2 | Complete |
| INGEST-07 | Phase 2 | Complete |
| INGEST-08 | Phase 2 | Complete |
| INGEST-09 | Phase 2 | Complete |
| PARSE-01 | Phase 3 | Complete |
| PARSE-02 | Phase 3 | Complete |
| PARSE-03 | Phase 3 | Complete |
| PARSE-04 | Phase 3 | Complete |
| PARSE-05 | Phase 3 | Complete |
| CLEAN-01 | Phase 3 | Complete |
| CLEAN-02 | Phase 3 | Complete |
| CLEAN-03 | Phase 3 | Complete |
| CHUNK-01 | Phase 3 | Complete |
| CHUNK-02 | Phase 3 | Complete |
| CHUNK-03 | Phase 3 | Complete |
| CHUNK-04 | Phase 3 | Complete |
| ENRICH-01 | Phase 4 | Complete |
| ENRICH-02 | Phase 4 | Complete |
| ENRICH-03 | Phase 4 | Complete |
| ENRICH-04 | Phase 4 | Complete |
| ENRICH-05 | Phase 4 | Complete |
| ENRICH-06 | Phase 4 | Complete |
| INDEX-01 | Phase 4 | Complete |
| INDEX-02 | Phase 4 | Complete |
| INDEX-03 | Phase 4 | Complete |
| CURATE-01 | Phase 5 | Complete |
| CURATE-02 | Phase 5 | Complete |
| CURATE-03 | Phase 5 | Complete |
| DATA-01 | Phase 5 | Complete |
| DATA-02 | Phase 5 | Complete |
| DATA-03 | Phase 5 | Complete |
| EXPORT-01 | Phase 5 | Complete |
| EXPORT-02 | Phase 5 | Complete |
| EXPORT-03 | Phase 5 | Complete |
| DOMAIN-01 | Phase 6 | Complete |
| DOMAIN-02 | Phase 6 | Complete |
| DOMAIN-03 | Phase 6 | Complete |
| DOMAIN-04 | Phase 6 | Complete |
| IFACE-01 | Phase 6 | Complete |
| IFACE-02 | Phase 6 | Complete |
| IFACE-03 | Phase 6 | Complete |

**Coverage:**

- v1 requirements: 55 total (count corrected from 47 during roadmap creation)
- Mapped to phases: 55
- Unmapped: 0 ✓

---
*Requirements defined: 2026-07-02*
*Last updated: 2026-07-02 after roadmap creation (traceability populated)*
