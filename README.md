# Knowledge Lake (klake)

[![CI](https://github.com/XploreOS/knowledge-lake/actions/workflows/ci.yml/badge.svg)](https://github.com/XploreOS/knowledge-lake/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Code style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

A reusable, domain-agnostic framework that turns public, private, and manually uploaded domain resources into AI-ready assets — with full lineage from raw source to indexed chunk.

**Features:**

- S3-compatible storage (MinIO for development, AWS S3 for production)
- Dagster orchestration with asset-based lineage
- Docling document parsing (PDF layout analysis, table extraction, reading order)
- Qdrant hybrid vector search (dense + sparse + RRF fusion)
- LiteLLM gateway for all LLM calls (Bedrock, OpenAI, Anthropic — swappable)
- Per-domain prompt packs with pluggable enrichment context


## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — fast package manager (replaces pip + virtualenv)
- Docker and Docker Compose — Docker Desktop or the `docker-compose-plugin` package
- AWS Bedrock API key — **optional**; required only for LLM enrichment (`enrich`, `generate-dataset`, `export pretrain/finetune` commands). The stack boots healthy without it; local sentence-transformers embeddings are used by default.


## Local Setup

### 1. Clone and configure environment

```bash
git clone <repo-url>
cd healthlake

cp .env.example .env
```

Open `.env` and set the required variables. All other variables have defaults.

**Required:**

| Variable | Description |
|----------|-------------|
| `KLAKE_STORAGE__ACCESS_KEY_ID` | MinIO root user (any non-empty string, e.g. `klakeadmin`) |
| `KLAKE_STORAGE__SECRET_ACCESS_KEY` | MinIO root password (minimum 8 characters) |

These two have **no defaults** by design (WR-09): the compose stack fails at startup with an explicit error if they are missing. This prevents accidental deployment with the well-known `minioadmin` credentials.

**Optional:**

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_PASSWORD` | `klake` | Postgres password |
| `AWS_BEDROCK_API_KEY` | — | Bedrock bearer token; required for `klake enrich`, `klake generate-dataset`, and `klake export pretrain/finetune` |
| `LITELLM_MASTER_KEY` | — | LiteLLM proxy master key; leave empty for local dev |
| `KLAKE_STORAGE__BUCKET` | `klake-data` | S3 bucket name |

### 2. Start the stack

```bash
docker compose up -d
```

Wait for all services to become healthy:

```bash
docker compose ps
```

**Expected services and ports:**

| Service | Port(s) | Description |
|---------|---------|-------------|
| `postgres` | `localhost:5432` | Registry database (Alembic-managed schema) |
| `minio` | `localhost:9000` (API), `localhost:9001` (console UI) | S3-compatible object store |
| `minio-init` | — | One-shot bucket bootstrap; exits 0 when done |
| `qdrant` | `localhost:6333` (HTTP), `localhost:6334` (gRPC) | Vector database |
| `litellm` | `localhost:4000` | LiteLLM proxy (all model calls go through here) |
| `dagster-webserver` | `localhost:3000` | Dagster asset graph and run history UI |
| `dagster-daemon` | — | Background scheduler and sensor runner |
| `api` | `localhost:8000` | Knowledge Lake REST API |
| `searxng` | `localhost:8888` | Meta-search engine for source discovery |

Verify the API is up:

```bash
curl http://localhost:8000/health
# Expected: {"status":"ok","version":"0.1.0+<git_sha>"}
```

`version` reflects the code actually running inside the container (`0.0.0` if
git metadata isn't available), so a stale container is visible in one curl
instead of hiding behind a green healthcheck.

**Picking up code changes:** `docker compose up -d` alone does **not** rebuild
an existing image — the `api`, `dagster-webserver`, and `dagster-daemon`
services bind-mount `./src` into the container (read-only) so most source
edits are picked up with just a restart:

```bash
docker compose restart api dagster-webserver dagster-daemon
```

If you change `pyproject.toml`/`uv.lock` (new dependencies) or the
`Dockerfile` itself, the mount can't help — rebuild explicitly:

```bash
docker compose up -d --build
```

### 3. Install Python dependencies

```bash
uv sync
```

### 4. Run database migrations

```bash
uv run alembic upgrade head
```

### 5. Verify the CLI

```bash
uv run klake version
```


## Quick Demo (end-to-end smoke test)

Run the built-in demo that ingests the cached HIPAA Security Rule PDF fixture and searches it:

```bash
uv run klake demo
```

This runs: ingest fixture PDF → parse → chunk → embed → index into Qdrant (`klake_spike` collection) → search "what are administrative safeguards" → print lineage of the top hit.

For the live PDF download instead of the fixture:

```bash
uv run klake demo --live
```


## Full Pipeline Walkthrough

The pipeline stages are: **register source → crawl or ingest-url → parse → clean → chunk → enrich → curate → index → search → export**. Each stage produces a registry artifact with a stable ID and a lineage pointer to its parent artifact.

### Register a source

```bash
uv run klake add-source https://www.hhs.gov/hipaa/for-professionals/security/index.html \
  --name "HIPAA Security" \
  --domain healthcare \
  --license public-domain
```

Prints `source_id`. Re-registering the same URL is a no-op (returns the existing `source_id`).

### Crawl a website

```bash
uv run klake crawl https://www.hhs.gov/hipaa/for-professionals/security/index.html \
  --max-pages 50
```

Prints `job_id`, `pages_complete`, `pages_failed`. Resume-safe: re-running picks up where it left off.

### Ingest a single URL (full pipeline shortcut)

Downloads the document, parses it, chunks it, embeds it, and indexes it into Qdrant in one command:

```bash
uv run klake ingest-url https://www.hhs.gov/sites/default/files/ocr/privacy/hipaa/understanding/srsummary.pdf \
  --source "HIPAA Security Rule Summary" \
  --mime application/pdf \
  --collection klake_chunks
```

Prints `source_id`, `raw_artifact_id`, `parsed_artifact_id`, and chunk count.

### Upload a local file

```bash
uv run klake upload /path/to/document.pdf \
  --source "My Document" \
  --license unknown
```

### Parse a raw artifact

```bash
uv run klake parse <raw_artifact_id> <source_id> --mime application/pdf
```

Prints `artifact_id`, `quality_score`, `parser_used`. Parser fallback chain: Docling → JSON/XML → Unstructured → Tika.

### Clean a parsed artifact

```bash
uv run klake clean <parsed_artifact_id> <source_id>
```

Removes boilerplate, detects language, and flags near-duplicates. Prints `artifact_id`, `language`, `dedup_status`.

### Chunk a parsed artifact

```bash
uv run klake chunk <parsed_artifact_id> <source_id>
```

Produces token-aware chunk artifacts. Prints `chunk_count` and the first `chunk_id`.

Note: for production use, the Dagster pipeline passes `ParsedDoc` in-memory for section-aware chunking; this CLI command is for manual testing.

### Enrich a cleaned artifact

Requires `AWS_BEDROCK_API_KEY`.

```bash
uv run klake enrich <cleaned_artifact_id> <source_id>
```

Calls LiteLLM (`cheap_model` alias → Bedrock by default; override with `KLAKE_ENRICH__MODEL_ALIAS=strong_model` for domain prompts that need more output capacity or higher accuracy) to extract summary, `document_type`, organization, jurisdiction, keywords, entities, and `quality_score`. Prints `status`, `artifact_id`, `quality_score`, `cached`.

### Curate a cleaned artifact

```bash
uv run klake curate <cleaned_artifact_id> <source_id>
```

Runs DataTrove-style quality filters (length, repetition, language, Gopher heuristics) and computes a composite quality score. Prints the composite `quality_score`.

### Corpus-wide deduplication

```bash
uv run klake dedupe
```

Builds a single MinHash LSH index over all cleaned artifacts and marks near-duplicates. Run this after bulk curation.

### Search

```bash
uv run klake search "what are administrative safeguards" \
  --collection klake_chunks \
  --top-k 5 \
  --domain healthcare \
  --min-quality-score 0.5
```

Embeds the query and returns the top-K matching chunks with `score`, `section`, `page`, `chunk_id`, and a text snippet. All filter flags are optional.

### View lineage

```bash
uv run klake lineage <artifact_id>
uv run klake lineage <artifact_id> --json
```

Walks `parent_artifact_id` back to the source document. Prints a tree showing all six lineage fields: `id`, `type`, `content_hash`, `timestamp`, `pipeline_version`, `storage_uri`.

### Export

```bash
# Export curated corpus as Parquet (RAG-ready)
uv run klake export rag-corpus

# Export as pretraining JSONL
uv run klake export pretrain

# Export a fine-tuning dataset by name
uv run klake export finetune --dataset-name my_rag_eval_v1
```

Writes gold-zone files to S3 (MinIO in dev). Prints `dataset_id`, `storage_uri`, `row_count`.

### Reindex Qdrant (zero-downtime alias swap)

```bash
uv run klake index --collection klake_chunks
```

Creates a new versioned physical collection, copies all points, then atomically repoints the alias. The prior collection is retained (never auto-dropped).

### Source discovery via SearXNG

```bash
uv run klake discover "HIPAA security rule compliance" --limit 20
```

Queries SearXNG, SSRF-validates each URL, and registers new sources. Prints registered/existing/skipped counts.


## Healthcare Domain Pack

The healthcare domain pack ships with 28 curated sources covering HL7/FHIR, CMS, HHS, ONC, CDC, FDA, NIH/NLM, and clinical guidelines.

### Register all healthcare sources

```bash
uv run klake init --domain healthcare
```

Reads `domains/healthcare/sources.yaml` and bulk-registers all 24 crawl-type sources. The 4 upload-type sources (ICD-10-CM Code Set, FDA National Drug Code Database, LOINC Clinical Terminology, NPPES NPI Bulk Data File) require manual download — the command reports them but does not auto-register them.

Expected output:

```
Registered 24 sources from healthcare pack.
4 sources require manual upload — see domains/healthcare/sources.yaml.
```

Re-running is safe: existing sources are skipped (URL-first dedup).

### Enable the healthcare domain context for enrichment

```bash
export KLAKE_DOMAIN__DOMAIN_NAME=healthcare
```

When set, `klake enrich` loads the healthcare-specific prompt from `domains/healthcare/prompts/enrich.j2`, giving the LLM domain context (FHIR, HIPAA, clinical terminology) for better metadata extraction. When unset, enrichment uses the generic prompt.

### Crawl a healthcare source

```bash
uv run klake crawl https://www.hhs.gov/hipaa/for-professionals/security/laws-regulations/index.html \
  --max-pages 100
```

### Ingest a specific HIPAA PDF end-to-end

```bash
uv run klake ingest-url \
  https://www.hhs.gov/sites/default/files/ocr/privacy/hipaa/understanding/srsummary.pdf \
  --source "HIPAA Security Rule Summary" \
  --mime application/pdf \
  --collection klake_chunks
```

### Enrich with healthcare domain context

Requires `AWS_BEDROCK_API_KEY`.

```bash
export KLAKE_DOMAIN__DOMAIN_NAME=healthcare
uv run klake enrich <cleaned_artifact_id> <source_id>
```

### Search the healthcare corpus

```bash
uv run klake search "what are administrative safeguards for HIPAA" \
  --collection klake_chunks \
  --domain healthcare \
  --top-k 10
```

### Generate a QA dataset from a healthcare chunk

Requires `AWS_BEDROCK_API_KEY`.

```bash
uv run klake generate-dataset qa <chunk_artifact_id> \
  --dataset-name healthcare_rag_eval_v1
```

### Export the healthcare corpus

```bash
uv run klake export rag-corpus
```


## Adding a New Domain Pack

A domain pack is a directory under `domains/<domain-name>/` with four components.

### Create the directory structure

```bash
mkdir -p domains/mydomainname/prompts
mkdir -p domains/mydomainname/validators
```

### Write domain.yaml

```yaml
name: mydomainname
version: "1.0.0"
description: "My domain — brief description of what this pack covers"
```

### Write sources.yaml

Each entry defines one source. `ingest_type` is either `crawl` (auto-crawled) or `upload` (manual bulk file):

```yaml
- name: "My Source Name"
  url: "https://example.com/path"
  source_type: "html"          # html, pdf, csv, xml
  license: "public-domain"     # SPDX identifier or open/public-domain/CC/unknown
  tags: ["tag1", "tag2"]
  crawl_config:
    depth: 2
    rate_limit_rps: 0.5
    robots_txt: true
  ingest_type: "crawl"

- name: "Bulk CSV File"
  url: "https://example.com/bulk"
  source_type: "csv"
  license: "open"
  tags: ["bulk", "coding"]
  crawl_config: {}
  ingest_type: "upload"
  # Note: download manually, then run: klake upload /path/to/file.csv --source "Bulk CSV File"
```

### Write the enrichment prompt (required)

```bash
cat > domains/mydomainname/prompts/enrich.j2 << 'EOF'
You are an expert in {{ domain_name }} documentation.
Extract metadata from the following document.

Focus on:
- Document type (standard, regulation, guideline, reference, report)
- Relevant organizations and jurisdictions
- Key terminology and concepts specific to {{ domain_name }}
- Quality signals (completeness, authority, recency)
EOF
```

### Write a QA generation prompt (optional, for generate-dataset qa)

```bash
cat > domains/mydomainname/prompts/qa_generation.j2 << 'EOF'
You are an expert in {{ domain_name }}.
Generate a question-answer pair from the following passage.
The question should be answerable from the passage alone.
EOF
```

### Create an empty validators module

```bash
touch domains/mydomainname/validators/__init__.py
cat > domains/mydomainname/validators/validate.py << 'EOF'
"""Optional domain-specific validation logic."""
EOF
```

### Register and use the new domain pack

```bash
# Register all crawl-type sources
uv run klake init --domain mydomainname

# Enable domain context for enrichment
export KLAKE_DOMAIN__DOMAIN_NAME=mydomainname

# Crawl a source from the pack
uv run klake crawl https://example.com/path --max-pages 50

# Or ingest a specific document end-to-end
uv run klake ingest-url https://example.com/document.pdf \
  --source "My Document" \
  --mime application/pdf \
  --collection klake_chunks

# Enrich with domain context
uv run klake enrich <cleaned_artifact_id> <source_id>

# Search
uv run klake search "my query" --collection klake_chunks --domain mydomainname
```


## Dagster UI

The Dagster webserver is available at `http://localhost:3000`. It shows all registered assets (ingest, parse, clean, chunk, enrich, curate, generate_dataset, index), run history, and retry state for `core_pipeline_e2e_job`.

To trigger the full pipeline for a source via the Dagster CLI:

```bash
uv run dagster job execute -j core_pipeline_e2e_job \
  -c '{"ops": {"ingest_asset": {"config": {"source_id": "<source_id>"}}}}'
```


## CLI Reference

| Command | Description |
|---------|-------------|
| `klake version` | Print the package version |
| `klake add-source URL` | Register a source URL (URL-first dedup) |
| `klake upload FILE` | Upload a local file into the raw zone |
| `klake discover QUERY` | Discover and register sources via SearXNG meta-search |
| `klake crawl URL` | Crawl a website into the lake (resume-safe) |
| `klake ingest-url URL` | Full pipeline shortcut: download → parse → chunk → index |
| `klake parse RAW_ID SOURCE_ID` | Parse a raw artifact into `parsed_document` |
| `klake clean PARSED_ID SOURCE_ID` | Clean boilerplate, detect language, near-dup flag |
| `klake chunk PARSED_ID SOURCE_ID` | Chunk into token-aware artifacts |
| `klake enrich CLEANED_ID SOURCE_ID` | LLM enrichment via LiteLLM (requires `AWS_BEDROCK_API_KEY`) |
| `klake curate CLEANED_ID SOURCE_ID` | DataTrove quality filters and composite score |
| `klake dedupe` | Corpus-wide MinHash deduplication |
| `klake generate-dataset KIND ARTIFACT_ID` | Generate QA or instruction dataset examples |
| `klake search QUERY` | Vector search with optional filters |
| `klake lineage ARTIFACT_ID` | Print full lineage ancestry tree |
| `klake export KIND` | Export corpus to gold zone (`rag-corpus` / `pretrain` / `finetune`) |
| `klake index` | Zero-downtime Qdrant alias reindex (canonical name) |
| `klake reindex` | Alias for `klake index` (power-user name) |
| `klake init --domain NAME` | Bulk-register all sources for a domain pack |
| `klake demo` | Run end-to-end smoke test using the HIPAA fixture |


## Environment Variable Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `KLAKE_STORAGE__ACCESS_KEY_ID` | Yes | none | MinIO root user / AWS access key |
| `KLAKE_STORAGE__SECRET_ACCESS_KEY` | Yes | none | MinIO root password / AWS secret key |
| `KLAKE_STORAGE__ENDPOINT_URL` | No | `http://minio:9000` (in container) | S3 endpoint; omit for AWS S3 |
| `KLAKE_STORAGE__BUCKET` | No | `klake-data` | S3 bucket name |
| `KLAKE_DATABASE_URL` | No | `postgresql+psycopg://klake:klake@localhost:5432/klake` | Registry database |
| `KLAKE_QDRANT_URL` | No | `http://localhost:6333` | Qdrant HTTP endpoint |
| `KLAKE_LITELLM_URL` | No | `http://localhost:4000` | LiteLLM proxy base URL |
| `KLAKE_EMBEDDER` | No | `local` | Embedder plugin: `local` (sentence-transformers) or `litellm` |
| `KLAKE_PARSER` | No | `docling` | Parser plugin: `docling` |
| `KLAKE_VECTORSTORE` | No | `qdrant` | Vector store plugin: `qdrant` |
| `KLAKE_DOMAIN__DOMAIN_NAME` | No | none | Active domain pack name (e.g. `healthcare`) |
| `KLAKE_DOMAIN__DOMAINS_ROOT` | No | `domains` | Path to the `domains/` directory |
| `AWS_BEDROCK_API_KEY` | No | none | Bedrock bearer token for LLM enrichment |
| `LITELLM_MASTER_KEY` | No | none | LiteLLM proxy master key |
| `POSTGRES_PASSWORD` | No | `klake` | Postgres password |

**Note:** When running `klake` CLI commands locally (outside Docker), set `KLAKE_STORAGE__ENDPOINT_URL=http://localhost:9000` to reach MinIO, and `KLAKE_DATABASE_URL` pointing to `localhost:5432`.


## Documentation

Deeper documentation lives in [`docs/`](docs/):

- [Architecture](docs/architecture.md)
- [Pipeline](docs/pipeline.md)
- [Configuration](docs/configuration.md)
- [Domain packs](docs/domain-packs.md)
- [API reference](docs/api-reference.md)


## Contributing

Contributions are welcome! Please read the [Contributing Guide](CONTRIBUTING.md)
to set up your environment, understand the framework invariants, and learn our
workflow. All participants are expected to follow our
[Code of Conduct](CODE_OF_CONDUCT.md).

- 🐛 **Found a bug?** [Open an issue](https://github.com/XploreOS/knowledge-lake/issues/new/choose).
- 💡 **Have an idea?** Start a [discussion](https://github.com/XploreOS/knowledge-lake/discussions) or open a feature request.
- 🔒 **Security vulnerability?** Please follow our [Security Policy](SECURITY.md) — do not open a public issue.

A running changelog is kept in [CHANGELOG.md](CHANGELOG.md).


## License

Copyright © 2026 XploreOS.

Knowledge Lake is licensed under the [Apache License 2.0](LICENSE). See the
[NOTICE](NOTICE) file for attribution details. This project orchestrates a
number of third-party open-source tools, each distributed under its own license.
