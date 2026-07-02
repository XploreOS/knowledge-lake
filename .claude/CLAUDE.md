<!-- GSD:project-start source:PROJECT.md -->

## Project

**Knowledge Lake Framework**

A reusable, domain-agnostic framework that orchestrates best-in-class open-source tools to turn public, private, and manually uploaded domain resources into AI-ready assets. It owns registries, lineage, domain packs, and export contracts — external tools (parsers, crawlers, vector stores, LLM gateways) are treated as replaceable plugins. Healthcare is the first domain pack.

**Core Value:** Every domain resource ingested must be traceable from raw source through every transformation to its final AI-ready output — and the framework must remain tool-agnostic so any processor can be swapped without breaking lineage.

### Constraints

- **LLM Gateway**: All model calls through LiteLLM only — no direct provider SDK calls in business logic
- **Storage**: S3-compatible (MinIO for dev, AWS S3 for large-scale) — no local filesystem as production store
- **Orchestration**: Dagster from day 1 — no ad-hoc script pipelines
- **Immutability**: Raw zone must never be modified after write
- **Lineage**: Every artifact must trace back to source document with stable IDs, content hashes, and timestamps
- **Legal**: Respect robots.txt, track source licenses, no private/restricted scraping
- **Models**: Task-based aliases (cheap_model, strong_model, eval_model, embedding_model) — no hardcoded provider model IDs
- **Deterministic first**: Use regex/heuristic extraction before LLM enrichment

<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->

## Technology Stack

## Recommended Stack

### Language & Runtime

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | 3.12+ | Core language | Best ecosystem for data/ML pipelines; 3.12 has performance improvements and better typing |
| uv | latest | Package management | 10-100x faster than pip, proper lockfiles, replaces pip+virtualenv+pip-tools |
| Pydantic | 2.13.x | Data validation & settings | Industry standard for Python data models; v2 is 5-50x faster than v1 |

### Orchestration

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Dagster | 1.13.x | Pipeline orchestration | Asset-based model maps perfectly to data lake zones; built-in lineage, retries, scheduling, observability |

- **vs Prefect:** Dagster's software-defined assets model is purpose-built for data pipelines where you declare outputs (bronze/silver/gold tables). Prefect is task-centric (imperative) which forces you to build lineage yourself.
- **vs Airflow:** Airflow is DAG/task-centric and requires external tooling for asset lineage. The scheduler architecture is heavyweight. Dagster's dev experience (local testing, type-checked resources) is dramatically better.
- **vs Custom:** Custom orchestration always under-invests in retries, observability, scheduling, and lineage. Dagster gives all of these for free.

### Document Parsing

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Docling | 2.108.x | Primary document parser | Best open-source multi-format parser: PDF layout analysis, table extraction, reading order, OCR, formula detection. IBM Research quality, LF AI & Data Foundation hosted, MIT license |

- **vs Unstructured (0.23.x):** Unstructured moved to a SaaS-first model with the open-source version lagging behind. Docling is fully open, faster iteration (190 releases vs Unstructured's slower cadence), and better structured output (DoclingDocument format with lossless JSON export).
- **vs Apache Tika:** Tika is Java-based (JVM dependency), focuses on text extraction without layout understanding. No table structure recognition, no reading order detection, no formula parsing. Legacy tool for simple text extraction only.

### Web Crawling

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Crawl4AI | 0.9.x | Primary web crawler | Async-first, LLM-ready markdown output, structured extraction, browser automation, anti-bot detection, deep crawl strategies (BFS/DFS/Best-First) |
| Scrapy | 2.16.x | Secondary/bulk crawler | Best for high-volume structured scraping with mature middleware ecosystem |

- **vs Scrapy:** Crawl4AI is purpose-built for AI pipelines: outputs clean markdown, handles JavaScript-rendered pages natively, supports LLM-based structured extraction. Scrapy excels at volume but requires more work to produce AI-ready output.
- **vs Custom (requests+BeautifulSoup):** Missing async pooling, browser automation, anti-bot detection, crash recovery, and deep crawl strategies.

### Vector Search

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Qdrant | client 1.18.x | Vector database | Best balance of features (dense/sparse/hybrid/multivector), performance, filtering, and deployment flexibility. Rust-based server, Docker-first |

- **vs Milvus:** Milvus is more complex (requires etcd, MinIO, Pulsar for distributed mode). Qdrant runs standalone in a single Docker container for dev and scales horizontally for production. Simpler operational model.
- **vs Weaviate:** Weaviate has good features but is less performant on filtered searches and has a more complex schema model. Qdrant's payload-based filtering with query planning is more flexible.
- **vs pgvector:** pgvector is convenient (same DB as metadata) but significantly slower for large collections, lacks hybrid search, no multivector support, and scaling requires PostgreSQL scaling which is expensive.
- Dense vectors for semantic search
- Sparse vectors for keyword/BM25-style retrieval
- Hybrid search with RRF fusion
- Payload filtering (source_id, domain, quality_score, etc.)
- Named vectors (multiple embedding models per document)
- Quantization for cost reduction at scale

### Object Storage

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| MinIO | Python SDK 7.2.x | S3-compatible object storage (dev) | Drop-in S3 replacement, runs locally in Docker, zero AWS costs during development |
| boto3 | 1.43.x | S3 client (production) | Direct AWS S3 access for production; MinIO is S3-compatible so same code works |

### Corpus Curation

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| DataTrove | 0.9.x | Text corpus filtering, deduplication, quality scoring | HuggingFace's production tool for FineWeb dataset. Modular pipeline architecture, MinHash dedup, quality filters, multi-executor support (local/Slurm/Ray) |

- **vs NeMo Curator (1.2.x):** NeMo Curator is GPU-first (requires NVIDIA RAPIDS, H100-class hardware). Overkill for our scale. DataTrove runs efficiently on CPU, which matches the DigitalOcean deployment constraint. NeMo Curator is for trillion-token scale.
- **vs Dolma:** Dolma (Allen AI) is less actively maintained and has fewer built-in filters. DataTrove has proven its pipeline at the FineWeb scale and integrates with HuggingFace Hub natively.
- **vs Custom filters:** DataTrove's pipeline block architecture (`Document` in, `Document` out) lets us write custom filters that compose with built-in ones. No reason to reinvent MinHash dedup or language detection.

### LLM Gateway

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| LiteLLM | 1.90.x | Unified LLM API gateway | Single interface to 100+ providers; handles Bedrock, OpenAI, Anthropic. Cost tracking, fallbacks, rate limiting, caching |

# config.yaml

### Metadata & Registry

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| PostgreSQL | 16+ | Metadata registry, source/document/artifact registries | Robust, well-understood, handles complex queries for lineage tracing |
| SQLAlchemy | 2.0.x | ORM & query builder | Industry standard Python ORM; async support, excellent migration tooling via Alembic |
| Alembic | latest | Database migrations | Paired with SQLAlchemy; auto-generates migration scripts from model changes |
| psycopg | 3.3.x | PostgreSQL driver | Modern async-capable PostgreSQL driver (replaces psycopg2) |

### API & CLI

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| FastAPI | 0.139.x | REST API framework | Async, auto-generated OpenAPI docs, Pydantic integration, dependency injection |
| Typer | 0.26.x | CLI framework | Same author as FastAPI, Pydantic-style CLI with auto-generated help |
| uvicorn | 0.49.x | ASGI server | Production ASGI server for FastAPI |

### Data Processing & Export

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| DuckDB | 1.5.x | Analytics queries & Parquet export | In-process analytical database, reads/writes Parquet natively, SQL interface over data lake files |
| PyArrow | 24.0.x | Arrow/Parquet format handling | Foundation for columnar data; DuckDB, Polars, and pandas all use it |
| Polars | 1.42.x | DataFrame operations | 10-100x faster than pandas for ETL transforms; native Parquet/Arrow support, lazy evaluation |

- Lazy evaluation enables query optimization
- Native multithreading (no GIL issues)
- Predictable memory usage with streaming
- Same Arrow foundation as DuckDB/PyArrow (zero-copy interop)

### Embeddings

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| sentence-transformers | 5.6.x | Local embedding models | Run embeddings locally without API costs; supports all MTEB models |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| lingua-language-detector | 2.2.x | Language detection | Every document ingestion; more accurate than langdetect (rule-based + ML hybrid) |
| structlog | latest | Structured logging | All application logging; JSON-structured logs for observability |
| tenacity | latest | Retry logic | HTTP calls, LLM calls, external service interactions |
| httpx | latest | Async HTTP client | All outbound HTTP (replaces requests for async contexts) |
| xxhash | latest | Fast content hashing | Document deduplication, content-addressable storage keys |
| orjson | latest | Fast JSON serialization | High-throughput JSON for JSONL export and API responses |

### Infrastructure

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Docker + Compose | latest | Local development environment | Run Postgres, MinIO, Qdrant, SearXNG as services |
| SearXNG | Docker image | Source discovery | Meta-search engine for finding domain sources; self-hosted, privacy-respecting |

### Source Discovery

| Technology | Deployment | Purpose | Why |
|------------|-----------|---------|-----|
| SearXNG | Docker (searxng/searxng) | Automated source discovery | Self-hosted meta-search engine; no API keys needed, aggregates multiple search engines, configurable per-domain |

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Orchestration | Dagster | Prefect 3.x | Task-centric model requires building lineage yourself; less natural for data lake zones |
| Orchestration | Dagster | Airflow 2.x | Heavyweight scheduler, DAG-centric, poor dev experience, no native asset concepts |
| Document Parsing | Docling | Unstructured | SaaS-first direction, slower OSS iteration, less structured output format |
| Document Parsing | Docling | Apache Tika | Java dependency, no layout understanding, no table/formula parsing |
| Web Crawling | Crawl4AI | Scrapy alone | Not AI-focused, no browser automation, requires more code for markdown output |
| Vector DB | Qdrant | Milvus | Operational complexity (etcd, MinIO, Pulsar dependencies for distributed) |
| Vector DB | Qdrant | pgvector | Slow at scale, no hybrid search, no multivector, scaling = scaling PG |
| Vector DB | Qdrant | Weaviate | Less performant filtered search, more complex schema model |
| Object Storage | boto3 + MinIO | MinIO SDK only | boto3 is the standard S3 client; works with both MinIO and AWS |
| Corpus Curation | DataTrove | NeMo Curator | Requires NVIDIA GPUs; overkill for non-trillion-token scale |
| Corpus Curation | DataTrove | Dolma | Less maintained, fewer built-in blocks |
| LLM Gateway | LiteLLM | Direct SDKs | Vendor lock-in, no unified cost tracking, no fallback routing |
| DataFrame | Polars | pandas | Slower, higher memory usage, no lazy evaluation, GIL-bound |
| Language Detection | lingua | langdetect | langdetect is unmaintained (last release 2021), less accurate on short text |
| Metadata | PostgreSQL | OpenMetadata | Adds operational complexity for MVP; migrate later when catalog features needed |
| Metadata | PostgreSQL | DataHub | LinkedIn's tool; complex Java/Kafka stack, overkill for MVP |

## Installation

# Core framework

# Document processing

# Web crawling

# Database & API

# Vector search

# LLM gateway

# Data processing & export

# Corpus curation

# Object storage

# Utilities

# Dev dependencies

## Docker Compose Services (Development)

## Version Pinning Strategy

## Architecture Notes

### Plugin Protocol Pattern

### Dagster Resource System

## Sources

- Dagster 1.13.11: https://pypi.org/project/dagster/ (released 2026-06-25)
- Docling 2.108.0: https://github.com/docling-project/docling/releases (released 2025-07-01)
- Crawl4AI 0.9.0: https://pypi.org/project/crawl4ai/ (released 2026-06-18)
- Qdrant Client 1.18.0: https://pypi.org/project/qdrant-client/ (released 2026-05-11)
- LiteLLM 1.90.2: https://pypi.org/project/litellm/ (released 2026-07-01)
- DataTrove 0.9.0: https://pypi.org/project/datatrove/ (released 2026-03-04)
- DuckDB 1.5.4: https://pypi.org/project/duckdb/ (released 2026-06-17)
- FastAPI 0.139.0: https://pypi.org/project/fastapi/ (released 2026-07-01)
- Typer 0.26.8: https://pypi.org/project/typer/ (released 2026-06-26)
- SQLAlchemy 2.0.51: https://pypi.org/project/sqlalchemy/ (released 2026-06-15)
- Pydantic 2.13.4: https://pypi.org/project/pydantic/ (released 2026-05-06)
- psycopg 3.3.4: https://pypi.org/project/psycopg/ (released 2026-05-01)
- PyArrow 24.0.0: https://pypi.org/project/pyarrow/ (released 2026-04-21)
- Polars 1.42.1: https://pypi.org/project/polars/ (released 2026-06-30)
- sentence-transformers 5.6.0: https://pypi.org/project/sentence-transformers/ (released 2026-06-16)
- Scrapy 2.16.0: https://pypi.org/project/scrapy/ (released 2026-05-19)
- MinIO Python SDK 7.2.20: https://github.com/minio/minio-py/releases
- boto3 1.43.39: https://pypi.org/project/boto3/ (released 2026-07-01)
- NeMo Curator 1.2.0: https://github.com/NVIDIA/NeMo-Curator (released 2026-05-14)
- Unstructured 0.23.1: https://github.com/Unstructured-IO/unstructured/releases (released 2026-06-11)
- lingua-language-detector 2.2.0: https://pypi.org/project/lingua-language-detector/ (released 2026-03-09)
- uvicorn 0.49.0: https://pypi.org/project/uvicorn/ (released 2026-06-03)

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
