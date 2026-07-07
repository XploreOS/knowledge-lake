# Configuration

## Overview

Configuration is loaded via pydantic-settings from environment variables. The top-level settings class uses the `KLAKE_` prefix; nested models use `__` as the separator (e.g. `KLAKE_STORAGE__ENDPOINT_URL` maps to `settings.storage.endpoint_url`).

Settings are accessed via `get_settings()`, which is cached with `@lru_cache(maxsize=1)`. All application code calls `get_settings()` — no direct `os.getenv()` calls in business logic.

For initial `.env` setup and running the stack with Docker Compose, see [README.md](../README.md). For domain-pack-specific variables, see [domain-packs.md](domain-packs.md).

## Settings Model Hierarchy

```
Settings  (env prefix: KLAKE_)
├── StorageSettings    (prefix: KLAKE_STORAGE__)
├── CrawlSettings      (prefix: KLAKE_CRAWL__)
├── ParseSettings      (prefix: KLAKE_PARSE__)
├── CleanSettings      (prefix: KLAKE_CLEAN__)
├── ChunkSettings      (prefix: KLAKE_CHUNK__)
├── EnrichSettings     (prefix: KLAKE_ENRICH__)
├── CurateSettings     (prefix: KLAKE_CURATE__)
├── DatasetSettings    (prefix: KLAKE_DATASET__)
├── IndexSettings      (prefix: KLAKE_INDEX__)
├── ExportSettings     (prefix: KLAKE_EXPORT__)
└── DomainSettings     (prefix: KLAKE_DOMAIN__)
```

## Core Service URLs (`KLAKE_*`)

| Env Var | Field | Default | Description |
|---------|-------|---------|-------------|
| `KLAKE_DATABASE_URL` | `database_url` | `postgresql+psycopg://klake:klake@localhost:5432/klake` | SQLAlchemy async connection string |
| `KLAKE_QDRANT_URL` | `qdrant_url` | `http://localhost:6333` | Qdrant HTTP endpoint |
| `KLAKE_LITELLM_URL` | `litellm_url` | `http://localhost:4000` | LiteLLM proxy base URL |
| `KLAKE_LITELLM_API_KEY` | `litellm_api_key` | `sk-local-noauth` | API key sent to the LiteLLM proxy (required by the SDK even without proxy auth) |
| `KLAKE_SEARXNG_URL` | `searxng_url` | `http://localhost:8888` | SearXNG meta-search URL |
| `KLAKE_TIKA_SERVER_URL` | `tika_server_url` | `http://localhost:9998` | Apache Tika server URL (last-resort parser) |

When running inside the Docker Compose stack, service names are used as hostnames: `postgres`, `minio`, `qdrant`, `litellm`, `searxng`. See the **Runtime vs Docker** section below.

## Plugin Swap Keys (`KLAKE_*`)

| Env Var | Field | Default | Values | Description |
|---------|-------|---------|--------|-------------|
| `KLAKE_EMBEDDER` | `embedder` | `local` | `local`, `litellm` | Embedder plugin |
| `KLAKE_PARSER` | `parser` | `docling` | `docling`, `json_xml`, `unstructured`, `tika` | Initial parser in fallback chain |
| `KLAKE_VECTORSTORE` | `vectorstore` | `qdrant` | `qdrant` | Vector store plugin |
| `KLAKE_CRAWLER` | `crawler` | `crawl4ai` | `crawl4ai`, `scrapy`, `playwright` | Web crawler plugin |
| `KLAKE_DISCOVERY` | `discovery` | `searxng` | `searxng` | Source discovery plugin |
| `KLAKE_UPLOAD_ROOT` | `upload_root` | `/data/uploads` | Absolute path | Upload root directory (API path traversal guard) |
| `KLAKE_PIPELINE_VERSION` | *(auto)* | `importlib.metadata` | — | Version tag stamped on every artifact; auto-derived from package metadata |

Swap keys are validated against `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$` at settings load time.

## Storage Settings (`KLAKE_STORAGE__*`)

| Env Var | Field | Type | Default | Description |
|---------|-------|------|---------|-------------|
| `KLAKE_STORAGE__ACCESS_KEY_ID` | `access_key_id` | str | (required) | MinIO root user or AWS access key ID |
| `KLAKE_STORAGE__SECRET_ACCESS_KEY` | `secret_access_key` | str | (required) | MinIO root password or AWS secret access key |
| `KLAKE_STORAGE__ENDPOINT_URL` | `endpoint_url` | Optional[str] | `None` (AWS S3) | S3 endpoint URL; set to `http://minio:9000` (Docker) or `http://localhost:9000` (local dev) |
| `KLAKE_STORAGE__BUCKET` | `bucket` | str | `klake-data` | S3 bucket name |
| `KLAKE_STORAGE__REGION` | `region` | str | `us-east-1` | AWS region |

**Security note:** `KLAKE_STORAGE__ACCESS_KEY_ID` and `KLAKE_STORAGE__SECRET_ACCESS_KEY` have no defaults. The Docker Compose stack will fail at startup with a clear error if they are not set in `.env`.

## Domain Settings (`KLAKE_DOMAIN__*`)

| Env Var | Field | Type | Default | Description |
|---------|-------|------|---------|-------------|
| `KLAKE_DOMAIN__DOMAIN_NAME` | `domain_name` | Optional[str] | `None` | Active domain pack (e.g. `healthcare`); controls enrichment prompt injection |
| `KLAKE_DOMAIN__DOMAINS_ROOT` | `domains_root` | str | `domains` | Path to the `domains/` directory |

## Crawl Settings (`KLAKE_CRAWL__*`)

Global crawl defaults; per-source overrides live in the source's `crawl_config`.

| Env Var | Field | Type | Default | Description |
|---------|-------|------|---------|-------------|
| `KLAKE_CRAWL__MAX_PAGES` | `max_pages` | int | `50` | Maximum pages per crawl job |
| `KLAKE_CRAWL__MAX_DEPTH` | `max_depth` | int | `2` | Maximum link-follow depth from seed URL |
| `KLAKE_CRAWL__RATE_LIMIT_SECONDS` | `rate_limit_seconds` | float | `1.0` | Delay between requests to the same host (seconds) |
| `KLAKE_CRAWL__SAME_DOMAIN_ONLY` | `same_domain_only` | bool | `True` | Only follow links on the same registrable domain as the seed |

## Parse Settings (`KLAKE_PARSE__*`)

| Env Var | Field | Type | Default | Description |
|---------|-------|------|---------|-------------|
| `KLAKE_PARSE__CHAIN` | `chain` | list[str] | `["docling","json_xml","unstructured","tika"]` | Ordered fallback chain |
| `KLAKE_PARSE__QUALITY_THRESHOLD` | `quality_threshold` | float | `0.4` | Minimum quality score before trying the next parser |
| `KLAKE_PARSE__QUALITY_GRAY_ZONE` | `quality_gray_zone` | tuple[float,float] | `(0.3, 0.6)` | Score band that triggers optional LLM spot-check |
| `KLAKE_PARSE__LLM_SPOT_CHECK` | `llm_spot_check` | bool | `True` | Enable LLM quality spot-check in gray zone |
| `KLAKE_PARSE__MAX_FILE_BYTES` | `max_file_bytes` | int | `104857600` (100 MiB) | Hard file-size limit before parsing |

## Clean Settings (`KLAKE_CLEAN__*`)

| Env Var | Field | Type | Default | Description |
|---------|-------|------|---------|-------------|
| `KLAKE_CLEAN__MINHASH_NUM_PERM` | `minhash_num_perm` | int | `128` | MinHash permutations |
| `KLAKE_CLEAN__MINHASH_THRESHOLD` | `minhash_threshold` | float | `0.8` | Jaccard similarity threshold for near-dup flagging |
| `KLAKE_CLEAN__MINHASH_SHINGLE_SIZE` | `minhash_shingle_size` | int | `5` | Word-level shingle size for MinHash signatures |

## Chunk Settings (`KLAKE_CHUNK__*`)

| Env Var | Field | Type | Default | Description |
|---------|-------|------|---------|-------------|
| `KLAKE_CHUNK__MAX_TOKENS` | `max_tokens` | int | `512` | Maximum tokens per chunk (cl100k_base encoding) |
| `KLAKE_CHUNK__OVERLAP_TOKENS` | `overlap_tokens` | int | `64` | Token overlap between adjacent chunks |
| `KLAKE_CHUNK__TOKENIZER` | `tokenizer` | str | `cl100k_base` | tiktoken encoding name |
| `KLAKE_CHUNK__HEADING_BREADCRUMB_DEPTH` | `heading_breadcrumb_depth` | int | `2` | Max heading levels to prepend as context prefix |

## Enrich Settings (`KLAKE_ENRICH__*`)

| Env Var | Field | Type | Default | Description |
|---------|-------|------|---------|-------------|
| `KLAKE_ENRICH__BUDGET_USD` | `budget_usd` | float | `5.0` | Global LLM spend cap in USD before enrichment halts |
| `KLAKE_ENRICH__PROMPT_VERSION` | `prompt_version` | str | `v1` | Bumping this invalidates the enrichment cache |
| `KLAKE_ENRICH__CACHE_ENABLED` | `cache_enabled` | bool | `True` | Enable/disable enrichment result caching |
| `KLAKE_ENRICH__EXCERPT_CHARS` | `excerpt_chars` | int | `4000` | Maximum document excerpt characters sent to LLM |

## Curate Settings (`KLAKE_CURATE__*`)

| Env Var | Field | Type | Default | Description |
|---------|-------|------|---------|-------------|
| `KLAKE_CURATE__GOPHER_MIN_DOC_WORDS` | `gopher_min_doc_words` | int | `50` | Minimum word count (GopherQualityFilter) |
| `KLAKE_CURATE__GOPHER_MAX_DOC_WORDS` | `gopher_max_doc_words` | int | `100000` | Maximum word count (GopherQualityFilter) |
| `KLAKE_CURATE__FILTER_NO_TERMINAL_PUNCT` | `filter_no_terminal_punct` | bool | `False` | If True, reject lines without terminal punctuation |
| `KLAKE_CURATE__FILTER_CONFIG_VERSION` | `filter_config_version` | str | `v1` | Bumping this invalidates the curation cache |

## Dataset Settings (`KLAKE_DATASET__*`)

| Env Var | Field | Type | Default | Description |
|---------|-------|------|---------|-------------|
| `KLAKE_DATASET__BUDGET_USD` | `budget_usd` | float | `5.0` | Dataset generation LLM spend cap in USD |
| `KLAKE_DATASET__PROMPT_VERSION` | `prompt_version` | str | `v1` | Bumping this invalidates the dataset generation cache |
| `KLAKE_DATASET__CACHE_ENABLED` | `cache_enabled` | bool | `True` | Enable/disable dataset generation caching |
| `KLAKE_DATASET__QA_EXCERPT_CHARS` | `qa_excerpt_chars` | int | `512` | Max chunk text characters for QA generation |
| `KLAKE_DATASET__INSTRUCTION_EXCERPT_CHARS` | `instruction_excerpt_chars` | int | `6000` | Max document excerpt for instruction-tuning generation |

## Index Settings (`KLAKE_INDEX__*`)

| Env Var | Field | Type | Default | Description |
|---------|-------|------|---------|-------------|
| `KLAKE_INDEX__COLLECTION_ALIAS` | `collection_alias` | str | `klake_chunks` | Stable alias name for the Qdrant chunk collection |
| `KLAKE_INDEX__KEEP_OLD_COLLECTIONS` | `keep_old_collections` | bool | `True` | If True, reindex never auto-drops the prior physical collection |

## Export Settings (`KLAKE_EXPORT__*`)

| Env Var | Field | Type | Default | Description |
|---------|-------|------|---------|-------------|
| `KLAKE_EXPORT__GOLD_PREFIX` | `gold_prefix` | str | `gold` | S3 key prefix for gold-zone exports |
| `KLAKE_EXPORT__DEFAULT_FINETUNE_FORMAT` | `default_finetune_format` | str | `openai_chat` | Fine-tuning JSONL format |
| `KLAKE_EXPORT__MIN_QUALITY_SCORE_FOR_PRETRAIN` | `min_quality_score_for_pretrain` | float | `0.4` | Minimum composite quality score for pretraining corpus export |
| `KLAKE_EXPORT__CONTAMINATION_OVERRIDE_ARTIFACT_IDS` | `contamination_override_artifact_ids` | list[str] | `[]` | Artifact IDs for accepted, documented train/eval overlaps |

## Non-KLAKE Variables

Other environment variables read by the Docker Compose stack (not prefixed with `KLAKE_`):

| Env Var | Service | Description |
|---------|---------|-------------|
| `POSTGRES_PASSWORD` | `postgres` | PostgreSQL password (default: `klake`) |
| `AWS_BEDROCK_API_KEY` | `litellm` | AWS Bedrock bearer token; required for enrichment, dataset generation, and export |
| `AWS_DEFAULT_REGION` | `litellm` | AWS region for Bedrock (default: `us-east-1`) |
| `LITELLM_MASTER_KEY` | `litellm` | LiteLLM proxy master key; leave empty for local dev |
| `DAGSTER_PG_URL` | `dagster-webserver`, `dagster-daemon` | Dagster's own PostgreSQL URL (separate DB from the klake registry) |

## Docker Compose Services

The development stack defined in `docker-compose.yml` has nine services:

| Service | Image | Port(s) | Purpose |
|---------|-------|---------|---------|
| `postgres` | `postgres:16-alpine` | `5432` | Registry PostgreSQL database |
| `minio` | `minio/minio:latest` | `9000` (API), `9001` (console) | S3-compatible object storage |
| `minio-init` | `minio/mc:latest` | — | One-shot bucket bootstrap; creates `klake-data` with versioning + object-lock |
| `qdrant` | `qdrant/qdrant:v1.13.6` | `6333` (HTTP), `6334` (gRPC) | Vector database |
| `litellm` | `ghcr.io/berriai/litellm:main-latest` | `4000` | LiteLLM proxy; reads `infra/litellm/config.yaml` |
| `dagster-webserver` | Project image (Dockerfile) | `3000` | Dagster asset graph UI and run history |
| `dagster-daemon` | Project image (Dockerfile) | — | Scheduler and sensor daemon |
| `api` | Project image (Dockerfile) | `8000` | Knowledge Lake FastAPI service |
| `searxng` | `searxng/searxng:latest` | `8888` | SearXNG meta-search for source discovery |

**Port overrides:** All ports can be changed via env vars: `POSTGRES_PORT`, `MINIO_PORT`, `MINIO_CONSOLE_PORT`, `QDRANT_HTTP_PORT`, `QDRANT_GRPC_PORT`, `LITELLM_PORT`, `DAGSTER_PORT`, `API_PORT`, `SEARXNG_PORT`.

The `postgres` service also creates a separate `dagster_storage` database and `litellm_storage` database via `infra/postgres/init.sql`, keeping Dagster's and LiteLLM's internal tables out of the klake registry schema.

## LiteLLM Model Aliases

All LLM calls in business logic use task-based aliases — never hardcoded provider model IDs. The mapping lives in `infra/litellm/config.yaml`.

| Alias | Bedrock Model | Purpose |
|-------|--------------|---------|
| `cheap_model` | `bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0` | Classification, short prompts, low-cost tasks |
| `strong_model` | `bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0` | Document enrichment, instruction-tuning generation |
| `eval_model` | `bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0` | QA pair generation, RAG evaluation |
| `embedding_model` | `bedrock/amazon.titan-embed-text-v2:0` | Embeddings when `KLAKE_EMBEDDER=litellm` |

**To swap models:** Edit only `infra/litellm/config.yaml`. No code changes. The proxy must be restarted after config changes.

**Note on `cheap_model` swap keys:** `EnrichSettings.cheap_model_bedrock_id` and `strong_model_bedrock_id` exist only to register cost metadata for `litellm.completion_cost()` — they are never used as the `model=` argument in actual LLM calls, which always use the alias names above.

**When `KLAKE_EMBEDDER=local`:** The `SentenceTransformerEmbedder` uses `all-MiniLM-L6-v2` (384-dim) locally via sentence-transformers — no API calls, no AWS credentials needed. This is the default for development.

## Alembic Migrations

The registry schema is managed exclusively by Alembic. Migrations live in `alembic/versions/`.

```bash
# Apply all pending migrations
uv run alembic upgrade head

# Check current revision
uv run alembic current

# Generate a new migration after model changes
uv run alembic revision --autogenerate -m "add my_column to artifacts"
```

**Never** call `Base.metadata.create_all()` in production. That method is only used in tests running against ephemeral in-memory SQLite databases.

## Runtime vs Docker

Inside the Docker Compose stack, service names are used as hostnames (set in `x-common-env`). When running the `klake` CLI or the API outside Docker (connecting to Docker Compose services), use `localhost` addresses.

**`.env.local-dev` snippet for running outside Docker:**

```env
KLAKE_DATABASE_URL=postgresql+psycopg://klake:klake@localhost:5432/klake
KLAKE_STORAGE__ENDPOINT_URL=http://localhost:9000
KLAKE_STORAGE__ACCESS_KEY_ID=<your-minio-user>
KLAKE_STORAGE__SECRET_ACCESS_KEY=<your-minio-password>
KLAKE_QDRANT_URL=http://localhost:6333
KLAKE_LITELLM_URL=http://localhost:4000
KLAKE_SEARXNG_URL=http://localhost:8888
```

Inside Docker Compose, the `x-common-env` block sets:
```env
KLAKE_DATABASE_URL=postgresql+psycopg://klake:${POSTGRES_PASSWORD:-klake}@postgres:5432/klake
KLAKE_STORAGE__ENDPOINT_URL=http://minio:9000
KLAKE_QDRANT_URL=http://qdrant:6333
KLAKE_LITELLM_URL=http://litellm:4000
```

These are injected automatically into all services — no manual override needed when running the full stack.
