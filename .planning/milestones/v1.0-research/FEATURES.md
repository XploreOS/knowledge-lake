# Feature Landscape

**Domain:** Knowledge Lake / Document Processing Pipeline Framework
**Researched:** 2026-07-02
**Overall Confidence:** HIGH (based on official documentation of DataTrove, NeMo Curator, Haystack, LlamaIndex, Docling, Unstructured, RAGFlow, Crawl4AI, Dagster, Qdrant, SearXNG, distilabel, Argilla)

## Table Stakes

Features users expect. Missing = framework feels incomplete or unusable for its stated purpose.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Document ingestion from multiple sources | Every pipeline starts with data acquisition; DataTrove, Unstructured, LlamaIndex all provide readers/connectors | Medium | Must support local files, URLs, S3, and crawled content |
| Multi-format document parsing | All competitors (Docling, Unstructured, LlamaIndex) support PDF, DOCX, HTML, Markdown at minimum | High | Docling covers 20+ formats; wrap as plugin, do not reimplement |
| Content extraction and normalization | Raw documents must become clean text; Unstructured's partition, Docling's converter, DataTrove's extractors | Medium | Includes HTML stripping, encoding normalization, whitespace cleanup |
| Text chunking with configurable strategies | LlamaIndex, LangChain, Haystack, RAGFlow all provide multiple chunking methods as core | Medium | Must support fixed-size, recursive, semantic, and section-aware at minimum |
| Embedding generation | Haystack, LlamaIndex, RAGFlow all embed as a core pipeline stage | Low | Wrap sentence-transformers and LiteLLM API; model-agnostic interface |
| Vector indexing and semantic search | Qdrant, FAISS, Chroma are standard backends; every RAG framework expects this | Medium | Plugin interface to vector stores; Qdrant as default |
| Metadata extraction and attachment | Unstructured attaches element-level metadata; LlamaIndex stores node metadata | Medium | Source URL, dates, section headers, page numbers, content hashes |
| Export to standard formats | DataTrove writes JSONL/Parquet; NeMo Curator outputs datasets; all frameworks export | Low | Parquet, JSONL, DuckDB are the minimum trio |
| CLI interface | DataTrove, Unstructured, Crawl4AI all have CLIs; expected for developer tools | Medium | Typer-based; mirrors all API operations |
| REST API | RAGFlow, Haystack (Hayhooks), Dagster all expose HTTP APIs | Medium | FastAPI with OpenAPI spec; pipeline triggers, CRUD, status |
| Configuration management | All frameworks use YAML/JSON/Python configs for pipeline definition | Low | Pydantic settings with env var overrides |
| Logging and error reporting | Standard in all data tools; Dagster has built-in observability | Low | Structured logging with per-job context |
| Idempotent and resumable jobs | DataTrove's skip_completed, Crawl4AI's resume_state, Dagster's asset materialization | High | Content-hash-based deduplication of work; checkpoint/resume on failure |
| Content deduplication | DataTrove (MinHash, exact, substring), NeMo Curator (exact, fuzzy, semantic) both treat this as core | High | At minimum exact hash dedup; fuzzy (MinHash) for near-duplicates |
| Language detection | DataTrove and NeMo Curator include language identification as a standard filter | Low | FastText-based detection; filter or tag per document |
| Pipeline orchestration with DAG execution | Dagster's core value; Haystack pipelines; DataTrove executors | High | Dagster integration from day 1; asset-based model maps to zones |
| Source and document registries | Metadata catalog is what differentiates a "lake" from a "pile of files" | Medium | PostgreSQL-backed; source -> document -> artifact lineage |
| Immutable raw storage | Medallion architecture pattern; data lakes always preserve raw | Low | Write-once to S3; content-addressed paths |

## Differentiators

Features that set the Knowledge Lake Framework apart from existing tools. Not expected in any single competitor, but create unique value.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Full lineage from source to AI-ready output | No existing tool provides end-to-end provenance spanning crawl -> parse -> chunk -> enrich -> embed -> export. DataTrove handles corpus prep; RAGFlow handles RAG; nobody connects both with lineage | High | Stable IDs, content hashes, transformation timestamps at every stage; this is the core differentiator |
| Data lake zone management (raw/bronze/silver/gold) | Medallion architecture applied to document processing. Dagster supports this pattern but no document-focused framework implements it natively | Medium | Zone promotion rules, quality gates between zones, zone-specific storage policies |
| Domain pack extensibility | No competitor offers domain-specific source registries with curated seeds, domain ontologies, and specialized enrichment as pluggable packs | High | Healthcare-first; extensible to legal, finance, education; each pack defines sources, vocabularies, quality rules |
| Dual-mode output: RAG-ready AND pretraining corpus | Existing tools focus on ONE output. LlamaIndex/Haystack for RAG. DataTrove/NeMo Curator for pretraining. This framework serves both from the same pipeline | Medium | Same source material, different output branches: chunked+embedded for RAG, filtered+deduplicated for pretraining |
| Dataset generation for fine-tuning | distilabel exists but is standalone. Embedding dataset generation within the lake pipeline (using the same curated content) is novel | High | Instruction tuning pairs, Q&A generation, classification datasets, entity extraction training data from enriched documents |
| Quality scoring at document and source level | NeMo Curator has quality classifiers; DataTrove has statistics. No framework scores at both source-level (is this website reliable?) and document-level (is this content high quality?) | Medium | Composite score: freshness, authority, completeness, relevance, duplication ratio |
| Source discovery via meta-search | SearXNG integration for automated discovery of domain-relevant sources; no RAG framework does this | Low | Query expansion, result deduplication, candidate ranking before crawl |
| Plugin architecture with tool-agnostic core | Most frameworks tightly couple to their parsers/stores. This framework treats parsers (Docling/Unstructured), crawlers (Crawl4AI/Scrapy), stores (Qdrant/Chroma), LLMs (via LiteLLM) as replaceable plugins | High | Interface contracts per plugin type; swap without breaking registries or lineage |
| Corpus curation for pretraining | DataTrove-style filtering (quality, toxicity, repetition, language) applied to domain-specific corpora, with lineage back to sources | Medium | Heuristic filters + LLM-based classifiers; configurable filter chains per domain |
| LLM-based metadata enrichment with task aliases | Using LLMs to extract entities, classify topics, generate summaries -- routed through task-based model aliases (cheap_model for classification, strong_model for summarization) | Medium | Cost-aware routing; deterministic-first with LLM as fallback |
| Section-aware and table-aware chunking | RAGFlow mentions "template-based chunking" but most frameworks use generic splitters. Section structure and table boundaries as chunk boundaries is rare | Medium | Preserves semantic units: a table stays whole, a section header stays with its content |
| Automated crawling with compliance tracking | Crawl4AI has features but does not track robots.txt compliance, source licensing, or crawl freshness in a registry | Low | License field per source, robots.txt honor flag, last-crawl timestamp, recrawl schedules |

## Anti-Features

Features to explicitly NOT build. Each represents a trap that would dilute focus or duplicate existing tools.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Custom document parser | Docling and Unstructured are excellent, actively maintained, and handle 20+ formats each. Building a parser is a multi-year effort | Plugin interface wrapping Docling (primary) and Unstructured (fallback). Let them handle the hard parsing problems |
| Custom vector database | Qdrant, Milvus, Chroma are purpose-built with GPU indexing, quantization, distributed deployment | Plugin interface to vector stores; Qdrant as default, swappable via config |
| Custom LLM serving | LiteLLM already unifies 100+ providers with fallbacks, cost tracking, rate limiting | All LLM calls through LiteLLM with task-based model aliases |
| Web UI / dashboard for MVP | RAGFlow, Dify, AnythingLLM all have UIs. Building one diverts from core pipeline value | CLI + API + Swagger UI. Defer dashboard to Phase 3+; consider Dagster UI for pipeline monitoring |
| Real-time streaming ingestion | Adds massive complexity (Kafka, event sourcing, backpressure). Batch-first covers 95% of knowledge lake use cases | Batch pipelines with configurable schedules. Consider streaming only after batch is proven |
| Custom orchestrator | Dagster is purpose-built for asset-based data pipelines with observability, retry, scheduling | Dagster from day 1. Use assets for zone transitions, sensors for triggers |
| Custom web crawler | Crawl4AI, Scrapy, Playwright are mature with anti-bot, proxy, session management | Plugin interface wrapping Crawl4AI (primary) and Scrapy (complex sites) |
| Multi-tenant auth / RBAC | Massive scope creep for a single-user/small-team tool. Would need user management, permission models, data isolation | Single-user API keys for MVP. Defer multi-tenancy to productization phase |
| Knowledge graph / ontology engine | Neo4j integration is interesting but not core to the pipeline's value. Adds query language complexity | Defer to Phase 3. Focus on relational metadata + vector search first |
| Human annotation UI | Argilla and Label Studio are purpose-built for this with years of UX refinement | Export to Argilla format. Integrate via API when human review is needed |
| Custom embedding model training | Requires ML infrastructure, training data, evaluation -- a project unto itself | Use pre-trained models via sentence-transformers or API. Fine-tune only with external tools |
| Duplicate DataTrove's executor system | DataTrove's Slurm/Ray executors are battle-tested at trillion-token scale | Use Dagster for orchestration. For DataTrove-specific operations, call DataTrove as a library within Dagster assets |

## Feature Dependencies

```
Source Registry → Document Registry → Artifact Registry
       ↓                   ↓                    ↓
Source Discovery    Document Parsing      Chunking/Embedding
(SearXNG)          (Docling plugin)      (core logic)
       ↓                   ↓                    ↓
Automated Crawling  Content Extraction    Vector Indexing
(Crawl4AI plugin)  (normalization)       (Qdrant plugin)
       ↓                   ↓                    ↓
Raw Zone Storage   Bronze Zone (parsed)  Silver Zone (enriched)
(S3/MinIO)         (S3/MinIO)            (S3/MinIO + PG)
                                                ↓
                                         Gold Zone (AI-ready)
                                         (Parquet/JSONL/DuckDB)

Pipeline Orchestration (Dagster) ──── spans all zones ────

LLM Gateway (LiteLLM) ──── used by enrichment, dataset gen, quality scoring ────

Export to:
├── RAG (chunks + embeddings + metadata → Qdrant)
├── Pretraining Corpus (filtered + deduplicated → Parquet/JSONL)
├── Fine-tuning Datasets (generated pairs → JSONL/HF format)
└── Evaluation Sets (held-out Q&A → JSONL)
```

### Critical Path Dependencies

1. **Source Registry** must exist before crawling (tracks what to crawl, when, compliance)
2. **Document Registry** must exist before parsing (tracks document lifecycle through zones)
3. **Raw zone immutable storage** must exist before any ingestion (write-once guarantee)
4. **Plugin interface contracts** must be defined before implementing any plugin (parser, crawler, vector store, LLM)
5. **Dagster integration** must be in place before building pipelines (do not build ad-hoc scripts then migrate)
6. **LiteLLM gateway** must be configured before any LLM-based enrichment or dataset generation
7. **Chunking** depends on parsing being complete (cannot chunk unparsed documents)
8. **Embedding** depends on chunking (embeds chunks, not raw documents)
9. **Quality scoring** depends on metadata enrichment (uses metadata signals as scoring inputs)
10. **Dataset generation** depends on silver/gold zone content (needs enriched, deduplicated material)

## MVP Recommendation

### Phase 1 Priority: Foundation (build the lake, not the ocean)

1. **Source and document registries with lineage** -- This IS the product. Without registries and lineage, it is just another script collection.
2. **Raw/bronze zone management with immutable storage** -- Data lake identity requires zone discipline from day 1.
3. **Plugin interface contracts** (parser, crawler, vector store, LLM gateway) -- Define the interfaces before implementing. This locks in architecture.
4. **Dagster pipeline orchestration** -- Build on Dagster assets from the start; never write ad-hoc pipeline scripts.
5. **Document parsing via Docling plugin** -- First concrete capability; proves the plugin architecture works.
6. **CLI and API scaffold** -- Developer ergonomics; every feature must be operable via both CLI and API.

### Phase 2 Priority: Processing Pipeline

7. **Chunking strategies** (fixed, recursive, section-aware, table-aware)
8. **Content deduplication** (exact hash + MinHash fuzzy)
9. **LLM-based metadata enrichment** through LiteLLM
10. **Embedding generation** (sentence-transformers + API)
11. **Vector indexing via Qdrant plugin**
12. **Silver zone promotion** with quality gates

### Phase 3 Priority: AI-Ready Outputs

13. **Export to Parquet/JSONL/DuckDB** (gold zone)
14. **Corpus curation filters** (DataTrove-style quality, language, dedup)
15. **Dataset generation** (instruction tuning, Q&A, classification)
16. **Quality scoring** (document + source level)
17. **Source discovery** (SearXNG integration)
18. **Automated crawling** (Crawl4AI plugin)

### Defer: Beyond MVP

- **Knowledge graph** (Neo4j) -- Phase 4+
- **Human review integration** (Argilla) -- Phase 4+
- **Web dashboard** -- Phase 4+
- **Hybrid BM25 search** -- Phase 3+
- **Data versioning** (lakeFS/DVC) -- Phase 4+
- **Catalog integration** (OpenMetadata) -- Phase 4+

**Rationale for ordering:** The framework's unique value is registries + lineage + zone management. Without these, adding features just creates another untracked pipeline. Build the "lake management" layer first, then prove it works with one complete flow (ingest -> parse -> chunk -> embed -> query), then expand to pretraining corpus and dataset generation.

## Sources

- DataTrove GitHub (huggingface/datatrove) -- Pipeline architecture, readers, filters, dedup, writers, executors
- NeMo Curator GitHub (NVIDIA/NeMo-Curator) -- Curation stages, GPU-accelerated filtering, multi-modal support
- Haystack GitHub (deepset-ai/haystack) -- Component pipeline architecture, integrations, RAG patterns
- LlamaIndex GitHub (run-llama/llama_index) -- Data connectors, index types, query engines, integrations
- Docling GitHub (DS4SD/docling) -- Document parsing, 20+ formats, table extraction, OCR, output formats
- Unstructured GitHub (Unstructured-IO/unstructured) -- Partitioning, element types, metadata, batch ingest
- RAGFlow GitHub (infiniflow/ragflow) -- Deep document understanding, template chunking, retrieval
- Crawl4AI GitHub (unclecode/crawl4ai) -- Async crawling, extraction strategies, batch processing
- Dagster docs (docs.dagster.io) -- Assets, ops, schedules, sensors, resources, partitions, IO managers
- Qdrant GitHub (qdrant/qdrant) -- Dense/sparse vectors, hybrid search, filtering, multitenancy
- SearXNG GitHub (SearXNG/searxng) -- Metasearch aggregation, API, self-hosted deployment
- distilabel GitHub (argilla-io/distilabel) -- Synthetic data generation, LLM pipelines, structured output
- Argilla GitHub (argilla-io/argilla) -- Data labeling, AI feedback, human-in-the-loop curation
