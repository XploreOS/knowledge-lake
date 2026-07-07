# Milestone v1.0 — Knowledge Lake Framework

**Generated:** 2026-07-07
**Purpose:** Team onboarding and project review

---

## 1. Project Overview

The **Knowledge Lake Framework** is a reusable, domain-agnostic pipeline that turns public, private, and manually uploaded domain resources into AI-ready assets. It owns registries, lineage, domain packs, and export contracts while treating every external tool (parsers, crawlers, vector stores, LLM gateways) as a replaceable plugin.

**Core value:** Every domain resource ingested must be traceable from raw source through every transformation to its final AI-ready output — and the framework must remain tool-agnostic so any processor can be swapped without breaking lineage.

**What it produces:**
- A curated, deduplicated corpus ready for LLM pretraining (Parquet/JSONL via gold zone)
- Generated datasets for fine-tuning, RAG evaluation, and instruction tuning
- A semantic search index over enriched, chunked documents
- A healthcare domain pack as the first instance of the domain convention

**Who it's for:** AI/ML engineers and data scientists who need domain-specific training data and RAG corpora from authoritative public sources, with full provenance.

**Infrastructure:** Single-user/small-team deployment on DigitalOcean Ubuntu 24.04 with Docker Compose (Postgres, MinIO, Qdrant, LiteLLM, Dagster). AWS Bedrock models via LiteLLM.

---

## 2. Architecture & Technical Decisions

### Core Architectural Pattern

The framework is organized as a **data lake with four zones**:
- **Raw zone** — immutable WORM storage, SHA256-keyed, content-addressed (MinIO)
- **Bronze zone** — crawled/uploaded markdown, parsed output
- **Silver zone** — cleaned, deduplicated, chunked, enriched documents
- **Gold zone** — curated corpus, generated datasets, export-ready Parquet/JSONL

Every zone transition produces a new `Artifact` row in Postgres with full lineage — parent/child relationships are queryable at any depth.

### Key Decisions

| Decision | Rationale | Validated |
|----------|-----------|-----------|
| **Dagster** for orchestration | Asset-based model maps to lake zones; built-in lineage, retries, UI | Phase 1 — 12 assets, all retried |
| **Docling** as primary parser | Best open-source multi-format parser (PDF layout, tables, OCR) | Phase 1 — HIPAA PDF parsed with 4 sections |
| **S3-compatible storage only** | Production-portable; same code for MinIO dev and AWS S3 prod | Phase 1 — WORM policy + object lock verified |
| **Plugin architecture** (entry-point resolver) | Swap parsers/crawlers/vector stores without touching core | Phase 1 — 3 built-in plugins registered |
| **LiteLLM** as sole LLM gateway | One interface for Bedrock, OpenAI, Anthropic; cost tracking, fallbacks | Phase 1 — `embedding_model`/`strong_model` aliases only |
| **PostgreSQL** for metadata registry | Relational integrity for lineage graphs; Alembic migrations | Phase 1 — self-referencing artifact graph working |
| **DataTrove** for corpus curation | FineWeb-proven at scale; modular filter blocks, MinHash dedup | Phase 5 — batch MinHash + DataTrove filters validated |
| **No admin UI** | CLI + API sufficient for single user; avoids frontend complexity | All phases — `klake` CLI + FastAPI Swagger |
| **Healthcare as first domain pack** | Deeply familiar domain; rich public data; high RAG/fine-tuning value | Phase 6 — 28 sources, DomainLoader, 5-source E2E passed |
| **Task-based model aliases** | `cheap_model`, `strong_model`, `eval_model`, `embedding_model` — no hardcoded provider IDs | All phases — never a direct provider model ID in business logic |
| **Deterministic-first extraction** | Regex/heuristic before LLM enrichment | Phases 3–5 — quality scorer, dedup, chunker all deterministic first |

### Technology Stack Summary

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python 3.12 | — |
| Package management | uv | latest |
| Orchestration | Dagster | 1.13.x |
| Document parsing | Docling | 2.108.x |
| Web crawling | Crawl4AI + Scrapy + Playwright | 0.9.x / 2.16.x |
| Vector search | Qdrant | client 1.18.x |
| Object storage | MinIO (dev) / boto3 (prod) | 7.2.x / 1.43.x |
| Metadata registry | PostgreSQL + SQLAlchemy + Alembic | 16+ / 2.0.x |
| LLM gateway | LiteLLM | 1.90.x |
| Corpus curation | DataTrove | 0.9.x |
| Data export | Polars + PyArrow + DuckDB | 1.42.x / 24.0.x / 1.5.x |
| API | FastAPI + uvicorn | 0.139.x / 0.49.x |
| CLI | Typer (<0.25.0 due to docling dep conflict) | — |
| Embeddings | sentence-transformers | 5.6.x |
| Source discovery | SearXNG (Docker) | — |

---

## 3. Phases Delivered

| Phase | Name | Status | What Was Built |
|-------|------|--------|----------------|
| 1 | Foundation & End-to-End Spike | ✅ Complete | IDs, storage, plugin system, Dagster assets, parse/embed/index/search spike, FastAPI, CLI |
| 2 | Ingestion | ✅ Complete | Crawl4AI/Scrapy/Playwright crawlers, manual upload, SearXNG source discovery, SSRF guard, robots.txt, rate limiting |
| 3 | Parse, Clean & Chunk | ✅ Complete | Docling multi-format fallback chain, quality scoring, language detection, MinHash dedup, token-aware chunker |
| 4 | Enrichment, Embedding & Search | ✅ Complete | LiteLLM enrichment with budget cap, sentence-transformers embeddings, Qdrant alias-based reindex, semantic search |
| 5 | Curation, Datasets & Export | ✅ Complete | DataTrove curation pipeline, Q&A/instruction dataset generation, Parquet/JSONL export, DuckDB query, gold zone |
| 6 | Healthcare Domain Pack & Full-Surface Validation | ✅ Complete | Domain pack loader, 28-source healthcare pack, CLI/API surface completion, Dagster retry policies, 5-source E2E |

### Phase Details

**Phase 1 — Foundation (6 plans):** Established the core architecture — content-addressed raw storage with WORM policy, UUIDv7 stable IDs, Alembic migrations, plugin entry-point resolver, Dagster software-defined assets wired to all four resources (Postgres, MinIO, Qdrant, LiteLLM), FastAPI with health/search/lineage endpoints, `klake` CLI.

**Phase 2 — Ingestion (6 plans):** Three crawler plugins (Crawl4AI, Scrapy, Playwright) with async job management, manual file upload with SHA256 dedup, SearXNG meta-search source discovery, robots.txt/rate-limit/SSRF safety guards, resumable crawl jobs.

**Phase 3 — Parse, Clean & Chunk (3 plans):** Docling primary parser with Tika/JSON/XML/Unstructured fallbacks, heuristic quality scoring (layout, density, language), lingua language detection, SHA256 exact dedup, transient MinHash near-dup flagging, tiktoken token-aware chunker with table atomicity.

**Phase 4 — Enrichment, Embedding & Search (3 plans):** Single-call LiteLLM structured-output enrichment with content-hash caching and budget cap (`LlmSpend` table), sentence-transformers local embeddings, Qdrant collection alias management for zero-downtime reindex, filterable semantic search with citation payload.

**Phase 5 — Curation, Datasets & Export (3 plans):** DataTrove `LocalPipelineExecutor` inside Dagster assets for corpus-wide quality filtering and MinHash batch dedup, Q&A RAG-eval generation from chunks (`strong_model`), instruction-tuning generation from documents (`eval_model`), Polars/PyArrow Parquet export to gold zone, DuckDB query interface.

**Phase 6 — Healthcare Domain Pack & Validation (4 plans):** `DomainLoader.from_name()` reads `domains/{name}/` convention (YAML + Jinja2 prompts + importlib validator), 28-source `sources.yaml` with HL7 FHIR/CMS/HIPAA/ONC/CDC/FDA/NLM/NPPES/LOINC/RxNorm entries, `HealthcareValidator` with PHI heuristic gate, `DomainSettings` + `domain_system_prompt` kwarg for additive enrich override, `klake init --domain`/`klake index` commands, 8 new API endpoints (`/sources`, `/documents`, `/datasets`, `/domains/load`…), `RetryPolicy` on all 12 Dagster assets, `healthcare_e2e_job` Dagster job, 5-source E2E test (4/4 passed with live MinIO+Postgres+Qdrant).

---

## 4. Requirements Coverage

All 55 v1.0 requirements validated. Coverage by category:

**Foundation (FOUND-01..11):** ✅ All — IDs, raw zone, Alembic, plugin resolver, Dagster resources, lineage, S3 storage, parse/embed/index/search spike, FastAPI, CLI, LiteLLM gateway

**Ingestion (INGEST-01..08):** ✅ All — crawl job management, Crawl4AI/Scrapy/Playwright plugins, manual upload, SHA256 dedup, SearXNG discovery, robots.txt/rate-limit/SSRF, resumable jobs, MIME type detection

**Parse/Clean/Chunk (PARSE-01..06):** ✅ All — multi-format Docling chain, quality scoring, language detection, dedup, chunking, bronze/silver zone writes

**Enrichment (ENRICH-01..06):** ✅ All — LiteLLM structured enrichment, entity extraction, quality scores, caching, budget cap, Dagster asset

**Embedding/Search (EMBED-01..04, SRCH-01..04):** ✅ All — sentence-transformers embedding, Qdrant upsert/alias, semantic search, lineage-aware results

**Curation/Dataset/Export (CURATE-01..03, DATA-01..03, EXPORT-01..03):** ✅ All — DataTrove filters, MinHash batch dedup, composite quality score, Q&A generation, instruction-tuning generation, Parquet/JSONL/DuckDB export

**Interface (IFACE-01..03):** ✅ All — complete `klake` CLI (16 commands), full FastAPI surface (all endpoint groups), Dagster assets with retries observable from UI

**Domain (DOMAIN-01..04):** ✅ All — domain pack loader convention, 28-source healthcare pack, enrichment prompts/taxonomy/validator, 5-source E2E validation

---

## 5. Key Decisions Log

| ID | Decision | Phase | Rationale |
|----|----------|-------|-----------|
| D-01 | Registry-first writes — every transformation is an Artifact node | 1 | Full lineage traceability; audit any artifact's ancestry |
| D-02 | Plugin protocol via Python entry-points | 1 | Swap parsers/crawlers without touching core; no import-time coupling |
| D-03 | Content-addressed raw storage with WORM policy | 1 | Immutability guarantee; SHA256 as content identity |
| D-04 | Single `@asset` wraps a plain pipeline function | 1 | Independently testable; Dagster wraps, not owns, the logic |
| D-05 | Task-based model aliases only | 1 | Provider portability; no hardcoded `amazon.titan-*` or `gpt-4` in business logic |
| D-06 | Deterministic quality scoring before optional LLM spot-check | 3 | Speed and reproducibility; LLM only for gray-zone documents |
| D-07 | Single enrichment call per document (not per-field) | 4 | Cost efficiency; structured JSON output covers all fields at once |
| D-08 | Content-hash caching for enrichment | 4 | Idempotent re-runs; same document content never re-billed |
| D-09 | Budget cap with graceful halt (`LlmSpend` table) | 4 | No surprise runaway costs; fail-closed on budget exhaustion |
| D-10 | `AssetSelection.assets()` with Python object refs (not string names) | 6 | Rename-safe; avoids silent selection failures on refactor |
| D-11 | Domain packs load from `domains/{name}/` by convention only | 6 | Zero core code changes per new domain; convention over configuration |
| D-12 | E2E validation against live docker-compose stack (no mocks) | 6 | Catches container/network/config integration bugs that unit tests miss |

---

## 6. Tech Debt & Deferred Items

### Known Tech Debt

| Item | Location | Notes |
|------|----------|-------|
| Typer <0.25.0 (docling dep conflict) | `pyproject.toml` | Upgrade when docling-core drops the Typer pin |
| Transient per-call MinHash in `clean.py` | `pipeline/clean.py` | Replaced by Phase 5 batch dedup but old code still references it; prune in v2 |
| `contamination_override_artifact_ids` in E2E test | `tests/e2e/test_e2e_healthcare.py` | Phase 5 dataset artifacts in shared dev DB trigger contamination check; proper test isolation (separate DB) would remove the need |
| Dagster webserver requires container rebuild | `docker-compose.yml` | No hot-reload; code changes require `docker compose build` + restart |

### Deferred to v2.0

| Item | Why Deferred |
|------|-------------|
| **RAGAS + Promptfoo + Arize eval harness** | Phase 5 AI-SPEC classified as Offline/Flywheel — not a blocking guardrail for v1.0 |
| **Multi-domain pack support** | v1.0 proves the convention with one pack; conflict resolution is a v2 design question |
| **Domain pack registry/catalog** | Versioning and publishing belong in a catalog tool (OpenMetadata/DataHub deferred) |
| **Hybrid BM25 + dense search (RETR-01)** | v2 requirement; Qdrant sparse vectors ready when needed |
| **Admin UI / web dashboard** | Out of scope for single-user MVP; CLI + API + Swagger sufficient |
| **OpenMetadata / DataHub integration** | Phase 1 decision: Postgres registry is simpler for MVP; migrate when catalog features needed |
| **lakeFS / DVC data versioning** | Deferred Phase 1; raw zone immutability covers the core need for now |

---

## 7. Getting Started

### Prerequisites

```bash
# Start all services
docker compose up -d

# Install dependencies
uv sync
```

### Running the Project

```bash
# Full pipeline on a document
uv run klake add-source --name "HIPAA Security Rule" --url "https://hhs.gov/hipaa" --source-type html
uv run klake discover --source-id <id>        # SearXNG source discovery
uv run klake crawl --source-id <id>           # Crawl + ingest raw
uv run klake parse --document-id <id>         # Docling parse → silver zone
uv run klake clean --document-id <id>         # Clean + dedup
uv run klake chunk --document-id <id>         # Token-aware chunk
uv run klake enrich --document-id <id>        # LiteLLM enrichment
uv run klake index --collection knowledge     # Embed + Qdrant upsert
uv run klake search "what are HIPAA requirements for encryption?"

# Healthcare domain pack
uv run klake init --domain healthcare         # Register 28 curated sources

# Export
uv run klake export --format parquet          # Gold zone Parquet
```

### Key Directories

```
src/knowledge_lake/
├── api/            # FastAPI app + Pydantic schemas
├── cli/            # Typer CLI (app.py — all 16 klake commands)
├── config/         # Pydantic settings (KLAKE_* env vars)
├── dagster_defs/   # Dagster assets, resources, definitions
├── domains/        # DomainLoader + domain pack convention
├── llm/            # LiteLLM pricing + cost tracking
├── pipeline/       # Pure pipeline functions (parse, clean, chunk, enrich, export…)
├── plugins/        # Protocol contracts + entry-point resolver + built-in adapters
├── quality/        # Quality scorer (heuristic + optional LLM spot-check)
├── registry/       # SQLAlchemy ORM models + repo functions
└── storage/        # S3/MinIO backend abstraction + zone constants

domains/healthcare/ # Healthcare domain pack (sources, prompts, taxonomy, validator)
tests/
├── unit/           # 324 unit tests (fast, no docker required)
├── integration/    # Integration tests (requires docker-compose)
└── e2e/            # End-to-end tests (requires full stack)
```

### API

FastAPI at `http://localhost:8000` — Swagger UI at `/docs`

Key endpoints: `GET /health`, `GET /sources`, `GET /documents`, `POST /parse`, `POST /clean`, `POST /chunk`, `POST /enrich`, `POST /search`, `POST /export`, `GET /lineage/{artifact_id}`, `POST /domains/load`

### Dagster UI

`http://localhost:3000` — observe 12 pipeline assets and `healthcare_e2e_job`

### Tests

```bash
uv run pytest tests/unit/ -q          # 324 tests, ~25s, no docker
uv run pytest tests/integration/ -m integration   # requires docker-compose
uv run pytest tests/e2e/ -m integration           # requires full stack
```

### Environment Variables

Key settings (all prefixed `KLAKE_`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `KLAKE_DATABASE_URL` | `postgresql+psycopg://klake:klake@localhost:5432/klake` | Postgres connection |
| `KLAKE_QDRANT_URL` | `http://localhost:6333` | Qdrant vector DB |
| `KLAKE_STORAGE__ENDPOINT_URL` | `http://localhost:9000` | MinIO/S3 endpoint |
| `KLAKE_LITELLM_PROXY_URL` | `http://localhost:4000` | LiteLLM gateway |
| `KLAKE_DOMAIN__DOMAIN_NAME` | `None` | Active domain pack name |
| `KLAKE_ENRICH__BUDGET_USD` | `10.0` | Per-session LLM spend cap |

---

## Stats

- **Timeline:** 2026-07-02 → 2026-07-07 (5 days)
- **Phases:** 6 / 6 complete
- **Plans:** 25 / 25 complete
- **Commits:** 258
- **Files changed:** 292 (+62,951 / -183)
- **Source lines:** ~17,150 (Python)
- **Tests:** 344 collected (324 unit + integration + e2e)
- **Requirements:** 55 / 55 validated
- **Contributors:** Jeevan J
