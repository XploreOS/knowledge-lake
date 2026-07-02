# Technology Stack

**Project:** Knowledge Lake Framework (HealthLake)
**Researched:** 2026-07-02
**Overall Confidence:** MEDIUM (cross-verified from PyPI + GitHub official sources)

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

**Why Dagster over alternatives:**
- **vs Prefect:** Dagster's software-defined assets model is purpose-built for data pipelines where you declare outputs (bronze/silver/gold tables). Prefect is task-centric (imperative) which forces you to build lineage yourself.
- **vs Airflow:** Airflow is DAG/task-centric and requires external tooling for asset lineage. The scheduler architecture is heavyweight. Dagster's dev experience (local testing, type-checked resources) is dramatically better.
- **vs Custom:** Custom orchestration always under-invests in retries, observability, scheduling, and lineage. Dagster gives all of these for free.

### Document Parsing

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Docling | 2.108.x | Primary document parser | Best open-source multi-format parser: PDF layout analysis, table extraction, reading order, OCR, formula detection. IBM Research quality, LF AI & Data Foundation hosted, MIT license |

**Why Docling over alternatives:**
- **vs Unstructured (0.23.x):** Unstructured moved to a SaaS-first model with the open-source version lagging behind. Docling is fully open, faster iteration (190 releases vs Unstructured's slower cadence), and better structured output (DoclingDocument format with lossless JSON export).
- **vs Apache Tika:** Tika is Java-based (JVM dependency), focuses on text extraction without layout understanding. No table structure recognition, no reading order detection, no formula parsing. Legacy tool for simple text extraction only.

**Plugin strategy:** Docling is the primary parser, but the framework should define a `DocumentParser` protocol that allows swapping in Unstructured or Tika for specific use cases (e.g., Tika for email/archive formats if needed).

### Web Crawling

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Crawl4AI | 0.9.x | Primary web crawler | Async-first, LLM-ready markdown output, structured extraction, browser automation, anti-bot detection, deep crawl strategies (BFS/DFS/Best-First) |
| Scrapy | 2.16.x | Secondary/bulk crawler | Best for high-volume structured scraping with mature middleware ecosystem |

**Why Crawl4AI as primary:**
- **vs Scrapy:** Crawl4AI is purpose-built for AI pipelines: outputs clean markdown, handles JavaScript-rendered pages natively, supports LLM-based structured extraction. Scrapy excels at volume but requires more work to produce AI-ready output.
- **vs Custom (requests+BeautifulSoup):** Missing async pooling, browser automation, anti-bot detection, crash recovery, and deep crawl strategies.

**Plugin strategy:** Crawl4AI for AI-focused crawling (markdown, structured extraction). Scrapy as an alternative plugin for bulk/sitemap crawling. Both behind a `WebCrawler` protocol.

### Vector Search

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Qdrant | client 1.18.x | Vector database | Best balance of features (dense/sparse/hybrid/multivector), performance, filtering, and deployment flexibility. Rust-based server, Docker-first |

**Why Qdrant over alternatives:**
- **vs Milvus:** Milvus is more complex (requires etcd, MinIO, Pulsar for distributed mode). Qdrant runs standalone in a single Docker container for dev and scales horizontally for production. Simpler operational model.
- **vs Weaviate:** Weaviate has good features but is less performant on filtered searches and has a more complex schema model. Qdrant's payload-based filtering with query planning is more flexible.
- **vs pgvector:** pgvector is convenient (same DB as metadata) but significantly slower for large collections, lacks hybrid search, no multivector support, and scaling requires PostgreSQL scaling which is expensive.

**Key capabilities used:**
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

**Strategy:** Use `boto3` as the single S3 client library everywhere. Point it at MinIO endpoint for local dev, AWS S3 for production. The MinIO Python SDK is only needed for MinIO admin operations (bucket policies, etc.) — not for regular object operations.

### Corpus Curation

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| DataTrove | 0.9.x | Text corpus filtering, deduplication, quality scoring | HuggingFace's production tool for FineWeb dataset. Modular pipeline architecture, MinHash dedup, quality filters, multi-executor support (local/Slurm/Ray) |

**Why DataTrove over alternatives:**
- **vs NeMo Curator (1.2.x):** NeMo Curator is GPU-first (requires NVIDIA RAPIDS, H100-class hardware). Overkill for our scale. DataTrove runs efficiently on CPU, which matches the DigitalOcean deployment constraint. NeMo Curator is for trillion-token scale.
- **vs Dolma:** Dolma (Allen AI) is less actively maintained and has fewer built-in filters. DataTrove has proven its pipeline at the FineWeb scale and integrates with HuggingFace Hub natively.
- **vs Custom filters:** DataTrove's pipeline block architecture (`Document` in, `Document` out) lets us write custom filters that compose with built-in ones. No reason to reinvent MinHash dedup or language detection.

**Integration approach:** Use DataTrove's pipeline blocks as the curation engine within Dagster assets. Dagster manages scheduling/retries/lineage; DataTrove does the actual filtering/dedup work.

### LLM Gateway

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| LiteLLM | 1.90.x | Unified LLM API gateway | Single interface to 100+ providers; handles Bedrock, OpenAI, Anthropic. Cost tracking, fallbacks, rate limiting, caching |

**Deployment mode:** Use LiteLLM as a Python library (not proxy server) for MVP. The proxy adds operational complexity. Direct library usage gives the same routing/fallback/cost-tracking benefits with simpler deployment.

**Model alias strategy (from PROJECT.md constraints):**
```python
# config.yaml
models:
  cheap_model: "bedrock/anthropic.claude-3-haiku-20240307-v1:0"
  strong_model: "bedrock/anthropic.claude-sonnet-4-20250514-v1:0"
  eval_model: "bedrock/anthropic.claude-sonnet-4-20250514-v1:0"
  embedding_model: "bedrock/amazon.titan-embed-text-v2:0"
```

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

**Why Polars over pandas:**
- Lazy evaluation enables query optimization
- Native multithreading (no GIL issues)
- Predictable memory usage with streaming
- Same Arrow foundation as DuckDB/PyArrow (zero-copy interop)

### Embeddings

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| sentence-transformers | 5.6.x | Local embedding models | Run embeddings locally without API costs; supports all MTEB models |

**Strategy:** Default to local sentence-transformers for development/small scale. Route through LiteLLM embedding endpoint for production (Bedrock Titan, OpenAI ada-003, etc.) via task alias `embedding_model`.

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

**Note:** The PyPI `searxng` package (0.0.0.dev0) is an MCP wrapper, not the actual search engine. Deploy SearXNG via its official Docker image only.

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

```bash
# Core framework
pip install dagster dagster-webserver dagster-postgres dagster-docker

# Document processing
pip install docling sentence-transformers

# Web crawling
pip install crawl4ai scrapy

# Database & API
pip install fastapi uvicorn typer sqlalchemy[asyncio] psycopg[binary] alembic pydantic

# Vector search
pip install qdrant-client

# LLM gateway
pip install litellm

# Data processing & export
pip install duckdb pyarrow polars

# Corpus curation
pip install datatrove

# Object storage
pip install boto3

# Utilities
pip install lingua-language-detector structlog tenacity httpx xxhash orjson

# Dev dependencies
pip install pytest pytest-asyncio pytest-cov ruff mypy pre-commit
```

## Docker Compose Services (Development)

```yaml
services:
  postgres:
    image: postgres:16
    ports: ["5432:5432"]
  
  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    ports: ["9000:9000", "9001:9001"]
  
  qdrant:
    image: qdrant/qdrant
    ports: ["6333:6333", "6334:6334"]
  
  searxng:
    image: searxng/searxng
    ports: ["8888:8080"]
  
  dagster-webserver:
    build: .
    ports: ["3000:3000"]
    depends_on: [postgres]
```

## Version Pinning Strategy

Pin **major.minor** in pyproject.toml, allow patch updates:
```toml
[project]
dependencies = [
    "dagster>=1.13,<1.14",
    "docling>=2.108,<3.0",
    "crawl4ai>=0.9,<1.0",
    "qdrant-client>=1.18,<2.0",
    "litellm>=1.90,<2.0",
    "datatrove>=0.9,<1.0",
    "duckdb>=1.5,<2.0",
    "fastapi>=0.139,<1.0",
    "sqlalchemy>=2.0,<2.1",
    "pydantic>=2.13,<3.0",
    "polars>=1.42,<2.0",
]
```

Use `uv lock` for reproducible lockfile.

## Architecture Notes

### Plugin Protocol Pattern

Every external tool should be behind a Python Protocol:

```python
from typing import Protocol, AsyncIterator
from dataclasses import dataclass

class DocumentParser(Protocol):
    async def parse(self, source: bytes, mime_type: str) -> ParsedDocument: ...

class WebCrawler(Protocol):
    async def crawl(self, url: str, config: CrawlConfig) -> AsyncIterator[CrawlResult]: ...

class VectorStore(Protocol):
    async def upsert(self, collection: str, points: list[VectorPoint]) -> None: ...
    async def search(self, collection: str, query: list[float], limit: int) -> list[SearchResult]: ...

class ObjectStore(Protocol):
    async def put(self, bucket: str, key: str, data: bytes) -> str: ...
    async def get(self, bucket: str, key: str) -> bytes: ...
```

### Dagster Resource System

Map plugins to Dagster resources for dependency injection:

```python
import dagster as dg

@dg.resource
def docling_parser() -> DocumentParser:
    from klake.parsers.docling import DoclingParser
    return DoclingParser()

@dg.resource  
def qdrant_store(context) -> VectorStore:
    from klake.vectorstores.qdrant import QdrantVectorStore
    return QdrantVectorStore(url=context.resource_config["url"])
```

## Sources

All version numbers verified from PyPI (pypi.org) and GitHub releases pages on 2026-07-02:
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
