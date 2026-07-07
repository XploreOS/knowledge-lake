# Architecture

Knowledge Lake is a domain-agnostic framework that orchestrates best-in-class open-source tools to turn public, private, and manually uploaded domain resources into AI-ready assets. It treats every external tool — parsers, crawlers, vector stores, LLM gateways — as a replaceable plugin. The single source of truth for metadata and lineage is a PostgreSQL registry; raw bytes live in S3-compatible object storage; and dense vectors live in Qdrant. For initial setup and running the stack, see [README.md](../README.md).

## Data Lake Zones

All artifacts are stored in S3 under four distinct key prefixes:

| Zone | S3 Prefix | Purpose | WORM? |
|------|-----------|---------|-------|
| Raw | `raw/` | Original source bytes, content-addressed | Yes (four-layer) |
| Bronze | `bronze/` | Crawler-produced markdown, one file per page | No |
| Silver | `silver/` | Parsed text, cleaned text, chunk text | No |
| Gold | `gold/` | Exported Parquet, JSONL, fine-tuning datasets | No |

**S3 key patterns:**

- Raw zone: `raw/{sha256}` — content-addressed by the SHA256 of the original bytes.
- Bronze/Silver: `{zone}/{artifact_id}` — keyed by the registry artifact ID.
- Gold: `gold/{export_name}.parquet` or `gold/{export_name}.jsonl`.

**Raw zone WORM enforcement (four layers):**

1. **Registry no-op**: `ingest_url` / `ingest_file` check the `artifacts` table for an existing row with the same `content_hash` and `artifact_type='raw_document'`. If found, the existing IDs are returned — no new S3 write happens.
2. **Content-addressed key**: `raw/{sha256}` means a second write of identical bytes hits the same key. No duplicate storage occurs.
3. **`head_object` guard**: Before uploading, the storage layer checks whether the key already exists in S3. An existing object causes the upload to be skipped.
4. **Bucket versioning + object-lock + delete-deny policy**: The `minio-init` service creates the bucket with `--with-lock` and enables versioning, so even if application-layer guards fail, S3/MinIO policy prevents object deletion.

## Registry Data Model

The registry is a PostgreSQL 16 database managed exclusively by Alembic migrations (never `create_all()` in production). The schema lives in `src/knowledge_lake/registry/models.py`.

### `sources`

Registry of document sources. Each source represents a logical origin — a website, an S3 upload batch, a file upload.

| Column | Type | Notes |
|--------|------|-------|
| `id` | String(64) PK | Prefixed UUIDv7: `src_<uuid>` |
| `name` | String(255) | Human-readable name |
| `source_type` | String(64) | `web`, `upload`, `api`, `crawler` |
| `url` | Text | Canonical URL |
| `normalized_url` | Text (indexed) | Lowercased scheme+host, no fragment — URL-first dedup |
| `license_type` | String(64) | SPDX identifier or `public_domain`, `proprietary`, etc. |
| `license_url` | Text | URL to license text |
| `robots_checked` | Boolean | Whether robots.txt was checked before crawling |
| `config` | JSON | Domain, tags, crawl params |
| `created_at` | DateTime UTC | Registration timestamp |

### `artifacts`

Unified self-referencing lineage tree. Every byte written to S3 gets one row. The `parent_artifact_id` self-FK enables recursive CTE ancestry walks.

| Column | Type | Notes |
|--------|------|-------|
| `id` | String(64) PK | Prefixed UUIDv7: prefix encodes type (`doc_`, `chk_`, `art_`) |
| `source_id` | String(64) FK → sources | Originating source (FOUND-06) |
| `parent_artifact_id` | String(64) FK → artifacts | NULL for raw_document root nodes (FOUND-06/07) |
| `artifact_type` | String(64) | `raw_document`, `parsed_document`, `cleaned_document`, `chunk`, `enriched_document`, `curated_document`, `bronze_document` |
| `content_hash` | String(64) (indexed) | SHA256 of content bytes |
| `pipeline_version` | String(64) | Package version + git SHA that produced this artifact |
| `storage_uri` | Text | `s3://bucket/zone/key` |
| `mime_type` | String(128) | `application/pdf`, `text/html`, `text/plain`, etc. |
| `page_ref` | Integer | Source page number (for parsed/chunk nodes — citation) |
| `section_path` | Text | Heading path, e.g. `§3.2 Administrative Safeguards` |
| `quality_score` | Float | LLM-judged quality for enriched_document rows |
| `metadata_` | JSON | Arbitrary extra metadata |
| `created_at` | DateTime UTC | Creation timestamp (FOUND-06) |

**Unique constraint:** `(content_hash, artifact_type)` — prevents duplicate processing of identical content at the same pipeline stage.

### `lineage_events`

Explicit labelled edges complementing the implicit `parent_artifact_id` tree. Records every transformation relationship between artifact nodes for audit and replay.

| Column | Type | Notes |
|--------|------|-------|
| `id` | String(64) PK | Prefixed UUIDv7 |
| `artifact_id` | String(64) FK → artifacts | Output artifact of the transformation |
| `parent_artifact_id` | String(64) FK → artifacts | Input artifact; NULL for ingest events |
| `edge_type` | String(64) | Named relationship: `ingested_from`, `parsed_from`, `chunked_from`, etc. |
| `pipeline_version` | String(64) | Version that produced this edge |
| `created_at` | DateTime UTC | |

### `jobs`

Pipeline job records, extended for crawl job tracking.

| Column | Type | Notes |
|--------|------|-------|
| `id` | String(64) PK | Prefixed UUIDv7 |
| `status` | String(32) | `pending`, `running`, `complete`, `failed` |
| `source_id` | String(64) FK → sources | Source being crawled |
| `job_type` | String(32) | `crawl` (default) |
| `crawler` | String(64) | Crawler adapter name (e.g. `crawl4ai`) |
| `config` | JSON | Job-specific configuration |
| `stats` | JSON | `pages_fetched`, `errors`, `duration`, etc. |
| `created_at` / `updated_at` | DateTime UTC | |

### `crawl_states`

Per-URL state within a crawl job. Unique on `(job_id, normalized_url)` — not on `content_hash` — so identical content at different URLs has separate state rows.

| Column | Type | Notes |
|--------|------|-------|
| `id` | String(64) PK | Prefixed UUIDv7: `cst_<uuid>` |
| `job_id` | String(64) FK → jobs | Parent crawl job |
| `url` | Text | Original discovered URL |
| `normalized_url` | Text | Normalized for dedup within job |
| `status` | String(32) | `pending`, `complete`, `failed`, `robots_blocked` |
| `raw_artifact_id` | String(64) FK → artifacts | Raw artifact from this page |
| `bronze_artifact_id` | String(64) FK → artifacts | Bronze artifact from this page |
| `error_msg` | Text | Error message for failed states |
| `fetched_at` | DateTime UTC | Successful fetch timestamp |

### `llm_spend`

Accumulated LLM call cost per scope key. Unique on `scope`. The `"global"` scope is the Phase 4 MVP default; finer-grained scopes can be added without a schema change.

| Column | Type | Notes |
|--------|------|-------|
| `id` | String(64) PK | Prefixed UUIDv7 |
| `scope` | String(64) unique | Budget scope key (e.g. `"global"`, `"dataset_generation"`) |
| `total_cost_usd` | Float | Cumulative cost in USD |
| `updated_at` | DateTime UTC | Last spend update |

### `vector_collections`

Alias-to-physical-collection registry. Tracks which physical Qdrant collection each alias currently resolves to, enabling auditable reindex history.

| Column | Type | Notes |
|--------|------|-------|
| `id` | String(64) PK | Prefixed UUIDv7 |
| `alias_name` | String(128) (indexed) | Stable alias (e.g. `klake_chunks`) |
| `physical_collection` | String(128) unique | Versioned collection (e.g. `klake_chunks_v1`) |
| `dim` | Integer | Vector dimension |
| `is_current` | Boolean | One True row per alias; reindex flips old to False, inserts new True |
| `created_at` | DateTime UTC | Registration timestamp |

### `datasets` + `dataset_examples`

Dataset registry and per-example lineage. `DatasetExample` is intentionally NOT a lineage-tree `Artifact` node — keeping it in its own table avoids exploding the artifacts table at QA-pair granularity (decision D-08).

`datasets` columns: `id`, `name` (unique), `dataset_type` (`rag_eval`, `instruction_tuning`, `pretraining`), `format` (`jsonl`, `parquet`), `example_count`, `storage_uri`, `created_at`.

`dataset_examples` columns: `id` (`dex_<uuid>`), `dataset_id` FK, `source_artifact_id` FK (nullable — SET NULL on artifact delete), `example_index`, `payload` JSON (QA or instruction pair + `_cache_key`), `created_at`.

## ID Format

All IDs are prefixed UUIDv7 with a minimum length of 40 characters (type prefix + `_` + 36-char UUID):

| Prefix | Table / Purpose |
|--------|----------------|
| `src_` | sources |
| `doc_` | artifacts (parsed/cleaned/enriched documents) |
| `chk_` | artifacts (chunks) |
| `art_` | artifacts (raw documents, generic) |
| `dex_` | dataset_examples |
| `cst_` | crawl_states |
| `job_` | jobs |

**Qdrant point IDs:** Bare UUID without prefix (the `chk_` prefix is stripped). The full prefixed ID is stored in the Qdrant point payload as `chunk_id`, preserving the link back to the registry.

## Plugin System

Five plugin protocols are defined in `src/knowledge_lake/plugins/protocols.py`. All are `@runtime_checkable` Python Protocols — swap any implementation by changing a single settings value; no core code edits required.

### `ParserPlugin`

Converts raw document bytes into a structured `ParsedDoc`.

- `can_parse(mime_type: str) -> bool` — return True if this parser handles the given MIME type.
- `parse(raw: bytes, mime_type: str) -> ParsedDoc` — extract full text and per-section metadata.

Built-in implementations (selected via `KLAKE_PARSER` env var):

| Key | Class | Handles |
|-----|-------|---------|
| `docling` | `DoclingParser` | PDF, DOCX, HTML, Markdown, images via Docling |
| `json_xml` | `JsonXmlParser` | `application/json`, `application/xml`, `text/xml` |
| `unstructured` | `UnstructuredParser` | Fallback for many formats |
| `tika` | `TikaParser` | Last-resort via Apache Tika server |

The parse stage runs a fallback chain: Docling → JSON/XML → Unstructured → Tika. Each parser's quality score is checked against `KLAKE_PARSE__QUALITY_THRESHOLD` (default 0.4); if below threshold, the next parser in the chain is tried.

### `EmbedderPlugin`

Embeds text strings into dense float vectors.

- `name: str` — stable identifier.
- `dim: int` — output vector dimension; must match the Qdrant collection vector size.
- `embed(texts: list[str]) -> list[list[float]]` — batch-embed strings.

Built-in implementations (selected via `KLAKE_EMBEDDER` env var):

| Key | Class | Dim | Credentials |
|-----|-------|-----|-------------|
| `local` | `SentenceTransformerEmbedder` | 384 | None (runs locally) |
| `litellm` | `LiteLLMEmbedder` | Model-dependent | Routes through `embedding_model` alias |

The `local` embedder uses `all-MiniLM-L6-v2` from sentence-transformers. The `litellm` embedder never contains a hardcoded provider model ID — it always calls through the `embedding_model` task alias defined in `infra/litellm/config.yaml`.

### `VectorStorePlugin`

Manages a Qdrant collection and performs similarity search.

Key methods: `ensure_collection`, `ensure_aliased_collection`, `reindex`, `copy_all_points`, `get_collection_dim`, `upsert`, `search`.

Built-in implementation (selected via `KLAKE_VECTORSTORE` env var): `QdrantVectorStore` (`qdrant`).

Zero-downtime reindex works by creating the next versioned physical collection (e.g. `klake_chunks_v2`), populating it via `copy_all_points`, then issuing a single atomic `update_collection_aliases()` call that deletes the old alias binding and creates the new one simultaneously — the alias never resolves to nothing mid-swap.

### `CrawlerPlugin`

Fetches pages from a seed URL.

- `name: str`
- `start_crawl(source_url, config) -> CrawlJob` — initiate a crawl.
- `poll_status(job_id) -> str` — check job status.
- `get_results(job_id) -> list[CrawlPageResult]` — retrieve per-page results.

Built-in implementations (selected via `KLAKE_CRAWLER` env var):

| Key | Class | Notes |
|-----|-------|-------|
| `crawl4ai` | `Crawl4AIAdapter` | Async-first, JavaScript-rendered pages, markdown output |
| `scrapy` | `ScrapyAdapter` | Subprocess isolation (separate process per crawl); JSONL IPC |
| `playwright` | `PlaywrightAdapter` | Browser automation for heavily JS-rendered sites |

Scrapy runs in a subprocess to avoid Twisted reactor conflicts. The child writes base64-encoded HTML per page over JSONL stdout; the parent parses after subprocess completion.

### `DiscoveryPlugin`

Finds candidate source URLs via a meta-search engine.

- `name: str`
- `search(query: str, limit: int) -> list[DiscoveryResult]` — return URL + title pairs.

Built-in implementation (selected via `KLAKE_DISCOVERY` env var): `SearXNGDiscovery` (`searxng`). Self-hosted meta-search, no API keys required, aggregates multiple search engines.

### Plugin Resolution

Resolution uses a plain config-keyed dict (no pluggy framework). Each plugin type has a resolver dict mapping string keys to built-in classes. `KLAKE_PARSER`, `KLAKE_EMBEDDER`, `KLAKE_VECTORSTORE`, `KLAKE_CRAWLER`, and `KLAKE_DISCOVERY` select the active implementation. Adding a new implementation means creating a new class and registering it in the resolver dict — no core framework changes.

## Lineage Model

Every artifact's ancestry can be resolved via a recursive CTE walking `artifacts.parent_artifact_id` up to the `raw_document` root. The `lineage.resolve_ancestry(artifact_id)` function executes this CTE and returns every ancestor node with all six FOUND-06 fields:

- `source_id` — originating source
- `parent_artifact_id` — immediate parent
- `content_hash` — SHA256 of content bytes
- `pipeline_version` — package version + git SHA
- `storage_uri` — S3 URI
- `created_at` — UTC creation timestamp

The `lineage_events` table adds explicit labelled edges (`ingested_from`, `parsed_from`, `chunked_from`, etc.) for audit, complementing the implicit tree structure.

See [pipeline.md](pipeline.md) for the artifact types produced at each stage.

## Key Architectural Constraints

These constraints are hard requirements, not guidelines:

- **LLM Gateway**: All model calls go through LiteLLM only — no direct provider SDK calls in business logic.
- **Task-based aliases**: Model identifiers in code are always task-based aliases (`cheap_model`, `strong_model`, `eval_model`, `embedding_model`) — never hardcoded provider model IDs. The mapping lives exclusively in `infra/litellm/config.yaml`.
- **Storage**: S3-compatible (MinIO for dev, AWS S3 for production) — no local filesystem as a production store.
- **Orchestration**: Dagster from day 1 — no ad-hoc script pipelines.
- **Immutability**: The raw zone must never be modified after first write (four-layer WORM).
- **Lineage**: Every artifact must trace back to its source document with stable IDs, content hashes, and timestamps.
- **Legal**: Respect robots.txt, track source licenses, no private/restricted scraping.
- **Deterministic first**: Use regex/heuristic extraction before LLM enrichment.
