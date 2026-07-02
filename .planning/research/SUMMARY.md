# Project Research Summary

**Project:** Knowledge Lake Framework (HealthLake)
**Domain:** Document Processing Pipeline / Data Lake for AI
**Researched:** 2026-07-02
**Confidence:** MEDIUM

## Executive Summary

HealthLake is a knowledge lake framework that ingests documents from diverse sources (web crawls, file uploads, APIs), processes them through a medallion architecture (bronze/silver/gold zones), and produces AI-ready outputs for both RAG and pretraining. The expert approach is to build this as a Dagster-orchestrated pipeline with pluggable components (parsers, crawlers, vector stores, LLM gateway) behind protocol interfaces, using PostgreSQL as the metadata registry and S3-compatible storage for objects. The core differentiator versus existing tools (DataTrove, LlamaIndex, Haystack) is end-to-end lineage from source to AI output, with dual-mode output serving both RAG retrieval and pretraining corpus needs.

The recommended approach is registry-first development: build the metadata registries and storage abstraction before any pipeline logic. Every file written must have a corresponding registry entry with content hash for deduplication and lineage tracking. Dagster's software-defined assets map naturally to zone transitions (bronze -> silver -> gold), but the critical mistake to avoid is over-engineering the Dagster graph before proving a single document can flow end-to-end. Build a spike first, then wrap in Dagster.

The top risks are: (1) parser quality blindness on real healthcare PDFs (Docling fails silently on complex layouts), (2) LLM enrichment cost explosion at scale without budget guardrails, and (3) chunking strategies that destroy domain context by splitting tables and clinical guidelines. All three are mitigated by quality gates, cost caps, and structure-aware chunking -- but they must be addressed in the phases where they first appear, not retrofitted.

## Key Findings

### Recommended Stack

Python 3.12+ with uv for package management. The stack is modern, async-first, and avoids reinventing wheels by composing best-in-class tools behind plugin interfaces.

**Core technologies:**
- **Dagster 1.13.x**: Pipeline orchestration -- asset-based model maps perfectly to data lake zones with built-in lineage, retries, and scheduling
- **Docling 2.108.x**: Document parsing -- best open-source multi-format parser with layout analysis, table extraction, and OCR
- **Crawl4AI 0.9.x**: Web crawling -- async-first, LLM-ready markdown output, browser automation
- **Qdrant 1.18.x**: Vector search -- dense/sparse/hybrid search with payload filtering, single Docker container for dev
- **LiteLLM 1.90.x**: LLM gateway -- unified interface to 100+ providers with cost tracking and fallbacks
- **DataTrove 0.9.x**: Corpus curation -- HuggingFace's production tool for filtering, deduplication, quality scoring
- **PostgreSQL 16+**: Metadata registry -- source/document/artifact registries with lineage graph
- **MinIO/S3**: Object storage -- content-addressed, zone-partitioned, immutable raw zone
- **FastAPI 0.139.x + Typer 0.26.x**: API and CLI interfaces
- **Polars 1.42.x + DuckDB 1.5.x**: Data processing and analytics export

### Expected Features

**Must have (table stakes):**
- Multi-format document parsing (PDF, DOCX, HTML, Markdown)
- Source and document registries with full lineage
- Data lake zone management (bronze/silver/gold) with immutable raw storage
- Text chunking with configurable strategies (fixed, recursive, semantic, section-aware)
- Embedding generation and vector indexing
- Content deduplication (exact hash + MinHash fuzzy)
- Pipeline orchestration with DAG execution (Dagster)
- Export to Parquet/JSONL/DuckDB
- CLI and REST API interfaces
- Idempotent and resumable jobs

**Should have (differentiators):**
- Full end-to-end lineage from source to AI output
- Dual-mode output: RAG-ready AND pretraining corpus from same pipeline
- Domain pack extensibility (healthcare-first)
- LLM-based metadata enrichment with cost-aware task routing
- Quality scoring at document and source level
- Source discovery via SearXNG meta-search
- Dataset generation for fine-tuning

**Defer (v2+):**
- Knowledge graph / Neo4j integration
- Web UI dashboard
- Human annotation UI (use Argilla export)
- Multi-tenant auth / RBAC
- Real-time streaming ingestion
- Custom embedding model training

### Architecture Approach

The architecture follows a pluggy-based plugin system with Dagster orchestration, PostgreSQL metadata registry, and S3-compatible zone storage. Components communicate through well-defined hook specifications, and all external dependencies are injected as Dagster resources enabling test mocking and environment switching.

**Major components:**
1. **Plugin Manager (pluggy)** -- Hook specs for parsers, crawlers, vector stores, embeddings; entry_point discovery for third-party plugins
2. **Registry (PostgreSQL)** -- Sources, documents, sections, chunks, artifacts, lineage_edges tables; content-hash deduplication
3. **Storage Abstraction (boto3)** -- Zone-aware S3 operations with immutability enforcement on bronze
4. **Dagster Definitions** -- Software-defined assets per zone transition; asset checks as quality gates
5. **API/CLI Layer** -- FastAPI REST + Typer CLI, both triggering Dagster runs via GraphQL client
6. **Domain Packs** -- pip-installable bundles with source seeds, schemas, enrichment prompts, quality rules

### Critical Pitfalls

1. **Over-engineering Dagster before proving end-to-end flow** -- Build a spike pipeline first (one URL -> parse -> chunk -> embed -> query), THEN wrap in Dagster assets
2. **Parser quality blindness on healthcare PDFs** -- Create a parser torture test corpus; implement fallback chains (Docling -> Unstructured -> Tika); quality gates before bulk processing
3. **Chunking destroys domain context** -- Structure-aware chunking from the start; tables are atomic; attach parent section heading to every chunk
4. **LLM enrichment cost explosion** -- Hard budget caps via LiteLLM, deterministic-first approach, enrichment caching by prompt_version + input hash
5. **Immutable raw zone violations** -- Content-addressed storage from day 1; disable deletes on raw bucket; content hash in every registry entry

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Foundation and Spike
**Rationale:** Everything depends on config, storage, registry, and plugin interfaces. But must also prove end-to-end data flow to avoid over-engineering.
**Delivers:** Working spike (one doc flows through all zones), core config, storage abstraction, PostgreSQL registry schema, plugin manager skeleton, Docker Compose dev environment
**Addresses:** Source/document registries, immutable raw storage, plugin interface contracts, configuration management
**Avoids:** Over-engineering Dagster (Pitfall 1), mutable raw zone (Pitfall 6), schema over-normalization (Pitfall 8)

### Phase 2: Ingest Pipeline
**Rationale:** Cannot process documents without ingesting them. Crawling and file upload are the entry points.
**Delivers:** Crawl4AI plugin, file upload, bronze zone population, basic CLI (source add/list, document upload), basic API endpoints, Dagster ingest assets
**Uses:** Crawl4AI, boto3/MinIO, Dagster, Typer, FastAPI
**Avoids:** Rate limit violations (Pitfall 9), SearXNG dedup issues (Pitfall 18)

### Phase 3: Parse and Chunk Pipeline
**Rationale:** Depends on bronze zone having documents. Parsing and chunking are tightly coupled (chunking depends on parser output structure).
**Delivers:** Docling parser plugin, section extraction, structure-aware chunking strategies, silver zone, lineage edge recording
**Uses:** Docling, Polars for transforms
**Avoids:** Parser quality blindness (Pitfall 2), context-destroying chunking (Pitfall 3)

### Phase 4: Enrichment and Embedding
**Rationale:** Requires chunks to exist in silver zone. LLM enrichment and embedding are the bridge to gold zone.
**Delivers:** LiteLLM integration, metadata enrichment, embedding generation, Qdrant vector indexing, gold zone population
**Uses:** LiteLLM, sentence-transformers, Qdrant
**Avoids:** Cost explosion (Pitfall 4), collection sprawl (Pitfall 5), prompt instability (Pitfall 12), cooldown cascade (Pitfall 16)

### Phase 5: Export and Dataset Generation
**Rationale:** Gold zone must be populated before export makes sense. This is the payoff phase delivering AI-ready outputs.
**Delivers:** Parquet/JSONL/DuckDB export, corpus curation (DataTrove filters), dataset generation (Q&A, instruction tuning), quality scoring
**Uses:** DuckDB, PyArrow, DataTrove, LiteLLM
**Avoids:** Garbage-in-garbage-out datasets (Pitfall 13)

### Phase 6: Domain Packs and Discovery
**Rationale:** Core pipeline must be proven before adding domain-specific customization. Healthcare pack builds on working infrastructure.
**Delivers:** Healthcare domain pack, SearXNG source discovery, domain-specific enrichment prompts, automated crawl scheduling
**Uses:** SearXNG, pluggy entry_points, domain-specific quality rules

### Phase Ordering Rationale

- Foundation must come first because every other component depends on config, storage, and registry
- The spike in Phase 1 prevents the over-engineering trap identified as the #1 critical pitfall
- Ingest before parse (need documents before you can parse them)
- Parse before enrich (need chunks before you can embed them)
- Export after enrichment (gold zone requires enriched content)
- Domain packs last because they are a customization layer on top of proven core

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3:** Parser fallback chain implementation details; Docling memory limits on large PDFs; structure-aware chunking algorithms for healthcare documents
- **Phase 4:** LiteLLM budget configuration specifics; Qdrant collection aliasing patterns; embedding model selection for healthcare domain
- **Phase 5:** DataTrove integration within Dagster assets; dataset generation prompt engineering

Phases with standard patterns (skip research-phase):
- **Phase 1:** Well-documented patterns for pydantic-settings, SQLAlchemy/Alembic, boto3, Docker Compose
- **Phase 2:** Crawl4AI and FastAPI have excellent documentation; standard CRUD patterns

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | All versions verified from PyPI on 2026-07-02; rationale based on cross-referencing official docs |
| Features | HIGH | Based on analysis of 13+ competing tools' official documentation |
| Architecture | MEDIUM | Patterns from official Dagster/FastAPI/pluggy docs; medallion architecture from Databricks reference |
| Pitfalls | MEDIUM | Mix of official docs, GitHub issues, and domain knowledge; healthcare-specific pitfalls from community reports |

**Overall confidence:** MEDIUM

### Gaps to Address

- **Healthcare PDF corpus quality**: No testing yet on actual target documents; parser quality assumptions need validation in Phase 3
- **Dagster + DataTrove integration**: No documented pattern for running DataTrove pipeline blocks inside Dagster assets; needs experimentation in Phase 5
- **LiteLLM budget enforcement reliability**: Documentation suggests budget features exist but real-world behavior under burst load is unverified
- **Qdrant hybrid search tuning**: RRF fusion parameters for healthcare domain retrieval quality unknown; needs evaluation dataset
- **DigitalOcean deployment constraints**: Stack assumes Docker availability but production deployment patterns (managed services vs self-hosted) not yet researched

## Sources

### Primary (HIGH confidence)
- Dagster official docs (docs.dagster.io) -- assets, resources, IO managers, scheduling
- FastAPI official docs (fastapi.tiangolo.com) -- dependency injection, background tasks
- Qdrant documentation (qdrant.tech/documentation) -- collections, hybrid search, filtering
- PyPI version verification for all packages (2026-07-02)

### Secondary (MEDIUM confidence)
- Docling GitHub issues (#3671, #3698, #3693) -- parser failure modes on complex PDFs
- LiteLLM documentation (docs.litellm.ai) -- routing, cost tracking, budget enforcement
- DataTrove GitHub (huggingface/datatrove) -- pipeline architecture, executor patterns
- pluggy documentation (pluggy.readthedocs.io) -- hook specs, entry points
- Databricks medallion architecture reference

### Tertiary (LOW confidence)
- Healthcare PDF complexity assumptions -- based on domain knowledge, not tested against actual corpus
- DigitalOcean deployment constraints -- mentioned in PROJECT.md but not researched in detail

---
*Research completed: 2026-07-02*
*Ready for roadmap: yes*
