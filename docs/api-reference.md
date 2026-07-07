# API Reference

Interactive documentation is available at runtime:
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

This document is a static reference capturing the same information for offline use. For pipeline stage semantics, see [pipeline.md](pipeline.md).

All endpoints use JSON bodies (where applicable) and return JSON responses. Query parameters are Pydantic-validated — out-of-range values return HTTP 422. All database queries use parameterized ORM — no raw SQL.

---

## ops

### `GET /health`

Service health check.

**Response:**
```json
{"status": "ok"}
```

---

## search

### `GET /search`

Semantic search over indexed chunks. Embeds the query and returns the top-k nearest Qdrant points with full citation payload.

**Query parameters:**

| Parameter | Type | Required | Default | Constraints | Description |
|-----------|------|----------|---------|-------------|-------------|
| `q` | string | Yes | — | — | Natural-language search query |
| `top_k` | int | No | `5` | 1–100 | Maximum results to return |
| `collection` | string | No | `klake_chunks` | `^[a-zA-Z0-9_-]{1,64}$` | Qdrant collection to search |
| `domain` | string | No | `null` | — | Filter: payload `domain` must match exactly |
| `document_type` | string | No | `null` | — | Filter: payload `document_type` must match exactly |
| `min_quality_score` | float | No | `null` | 0.0–1.0 | Filter: payload `quality_score` must be >= this |

**Response:** `list[SearchHit]`

```json
[
  {
    "id": "019f...",
    "score": 0.87,
    "document": "doc_019f...",
    "section_path": "§3.2 Administrative Safeguards",
    "page": 14,
    "chunk_id": "chk_019f...",
    "text": "The covered entity must...",
    "domain": "healthcare",
    "document_type": "regulation",
    "keywords": ["HIPAA", "administrative safeguards"],
    "quality_score": 0.92
  }
]
```

**Error codes:** `422` — invalid collection name format.

---

## pipeline

### `POST /reindex`

Zero-downtime alias reindex. Creates the next versioned physical collection, copies all existing points via `copy_all_points`, then atomically repoints the alias. The prior physical collection is retained.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `collection` | string | `klake_chunks` | Qdrant alias to reindex |

**Response:** `ReindexResponse`

```json
{
  "new_physical": "klake_chunks_v2",
  "old_physical": "klake_chunks_v1"
}
```

**Error codes:** `422` — invalid collection name format, or collection does not exist.

---

### `POST /parse`

Parse a `raw_document` artifact using the configured parser fallback chain.

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `raw_artifact_id` | string | Yes | Artifact ID of the `raw_document` to parse |
| `source_id` | string | Yes | Source registry ID |
| `mime_type` | string | Yes | MIME type of the document (e.g. `application/pdf`) |

**Response:** `ParseResponse`

```json
{
  "artifact_id": "doc_019f...",
  "quality_score": 0.85,
  "parser_used": "docling",
  "content_hash": "sha256:abc123..."
}
```

**Error codes:** `422` — artifact not found, or invalid artifact ID.

---

### `POST /clean`

Clean a `parsed_document` artifact: boilerplate removal, whitespace normalization, language detection, near-dup flagging.

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `parsed_artifact_id` | string | Yes | Artifact ID of the `parsed_document` to clean |
| `source_id` | string | Yes | Source registry ID |

**Response:** `CleanResponse`

```json
{
  "artifact_id": "doc_019f...",
  "language": "en",
  "dedup_status": "unique",
  "content_hash": "sha256:def456..."
}
```

**Error codes:** `422` — artifact not found.

---

### `POST /chunk`

Chunk a `parsed_document` artifact into token-aware chunks. The API endpoint reconstructs a minimal `ParsedDoc` from stored text (no section structure). For section-aware chunking, use the Dagster pipeline which passes `ParsedDoc` in-memory.

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `parsed_artifact_id` | string | Yes | Artifact ID of the `parsed_document` to chunk |
| `source_id` | string | Yes | Source registry ID |

**Response:** `ChunkResponse`

```json
{
  "chunk_count": 24,
  "chunk_ids": ["chk_019f...", "chk_019f...", "..."]
}
```

**Error codes:** `422` — artifact not found or has no storage URI.

---

### `POST /enrich`

LLM-enrich a `cleaned_document` artifact with metadata. Runs deterministic extraction first, then a single cached LiteLLM call using `strong_model`.

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `cleaned_artifact_id` | string | Yes | Artifact ID of the `cleaned_document` to enrich |
| `source_id` | string | Yes | Source registry ID |

**Response:** `EnrichResponse`

```json
{
  "artifact_id": "doc_019f...",
  "status": "enriched",
  "cached": false,
  "quality_score": 0.91
}
```

`status` values: `enriched`, `cached`, `skipped_budget_exceeded`, `skipped_enrichment_failed`.

**Error codes:** `422` — artifact not found.

---

### `GET /curated-documents`

List `curated_document` artifacts, ordered by `quality_score` descending.

**Query parameters:**

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `min_quality_score` | float | `null` | 0.0–1.0 | Include only documents with quality >= this |

**Response:** `list[CuratedDocumentOut]`

```json
[
  {
    "artifact_id": "art_019f...",
    "quality_score": 0.87,
    "dedup_status": "unique",
    "created_at": "2026-07-07T10:23:00+00:00"
  }
]
```

---

## ingestion

### `POST /sources`

Register a source URL. Returns HTTP 201 whether the URL is new or already exists (silent dedup on normalized URL).

**Request body:**

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `url` | string | Yes | min_length=8 | Source URL to register |
| `name` | string | No | — | Human-readable name (defaults to hostname) |
| `domain` | string | No | — | Domain classification (e.g. `healthcare`) |
| `license_type` | string | No | — | SPDX identifier |

**Response:** `SourceOut` (HTTP 201)

```json
{
  "source_id": "src_019f...",
  "is_new": true
}
```

**Error codes:** `422` — invalid URL.

---

### `POST /uploads`

Upload a file from the server filesystem into the raw zone. The file path must be inside `KLAKE_UPLOAD_ROOT` (path traversal guard).

**Query parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | Yes | — | Absolute server-side path inside the upload root |
| `source_name` | string | No | `uploaded-file` | Human-readable source name |
| `license_type` | string | No | `unknown` | SPDX license identifier |

**Response:** `UploadOut` (HTTP 201)

```json
{
  "artifact_id": "art_019f...",
  "source_id": "src_019f...",
  "is_new": true
}
```

**Error codes:** `400` — path outside upload root. `404` — file not found. `422` — invalid path.

---

## discovery

### `POST /discover`

Run a source discovery query via SearXNG. Each result URL is SSRF-validated and URL-deduped before registration.

**Request body:**

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `query` | string | Yes | 1–500 chars | Natural-language discovery query |
| `limit` | int | Yes | 1–100 | Maximum results |

**Response:** `DiscoverOut`

```json
{
  "query": "HIPAA security rule requirements",
  "total": 5,
  "results": [
    {
      "url": "https://www.hhs.gov/hipaa/...",
      "title": "HIPAA Security Rule",
      "source_id": "src_019f...",
      "status": "registered"
    }
  ]
}
```

`status` values: `registered` (newly added), `existing` (already in registry), `skipped` (SSRF-blocked or invalid).

**Error codes:** `502` — SearXNG unreachable.

---

## crawl

### `POST /crawl-jobs`

Start a crawl job for a source URL. Creates two artifacts per successfully fetched page: `raw_document` (HTML bytes) and `bronze_document` (cleaned markdown). Resume-safe: re-running for the same source URL skips completed URLs.

**Request body:**

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `source_url` | string | Yes | min_length=8 | Seed URL to crawl |
| `crawler` | string | No | — | Crawler override (defaults to configured crawler) |
| `max_pages` | int | No | 1–10000 | Maximum pages to fetch |

**Response:** `CrawlJobOut` (HTTP 201)

```json
{
  "job_id": "job_019f...",
  "source_id": "src_019f...",
  "crawler": "crawl4ai",
  "status": "complete",
  "states": {
    "complete": 42,
    "robots_blocked": 2,
    "failed": 0,
    "pending": 0
  }
}
```

**Error codes:** `422` — invalid URL or unknown crawler.

---

### `GET /crawl-jobs/{job_id}`

Get crawl job status and per-status page counts.

**Path parameters:** `job_id` (string) — Job registry ID.

**Response:** Same shape as `POST /crawl-jobs`.

**Error codes:** `404` — job not found.

---

## registry

### `GET /sources`

List registered sources with pagination and optional domain filter.

**Query parameters:**

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `domain` | string | `null` | max_length=64 | Filter by domain (matched against `config['domain']`) |
| `limit` | int | `50` | 1–200 | Maximum results |
| `offset` | int | `0` | >= 0 | Pagination offset |

**Response:** `list[SourceListItem]`

```json
[
  {
    "source_id": "src_019f...",
    "name": "HIPAA Security Rule",
    "url": "https://www.hhs.gov/hipaa/...",
    "source_type": "web",
    "license_type": "public-domain",
    "domain": "healthcare",
    "created_at": "2026-07-07T10:00:00+00:00"
  }
]
```

---

### `GET /sources/{source_id}`

Get a single source by registry ID.

**Path parameters:** `source_id` (string) — Source registry ID.

**Response:** `SourceListItem` (same shape as list item above).

**Error codes:** `404` — source not found.

---

### `GET /documents`

List artifact documents with optional type and source filters.

**Query parameters:**

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `artifact_type` | string | `null` | max_length=64 | Filter by type (e.g. `raw_document`, `chunk`) |
| `source_id` | string | `null` | max_length=64 | Filter by source registry ID |
| `limit` | int | `50` | 1–200 | Maximum results |
| `offset` | int | `0` | >= 0 | Pagination offset |

**Response:** `list[ArtifactOut]`

```json
[
  {
    "id": "doc_019f...",
    "artifact_type": "parsed_document",
    "source_id": "src_019f...",
    "parent_artifact_id": "art_019f...",
    "content_hash": "sha256:abc123...",
    "created_at": "2026-07-07T10:05:00+00:00",
    "storage_uri": "s3://klake-data/silver/doc_019f...",
    "mime_type": "application/pdf"
  }
]
```

---

### `GET /documents/{artifact_id}`

Get a single artifact by registry ID.

**Path parameters:** `artifact_id` (string) — Artifact registry ID.

**Response:** `ArtifactOut` (same shape as list item above).

**Error codes:** `404` — artifact not found.

---

## curation

### `POST /curate`

Run DataTrove-style quality filters on a `cleaned_document` artifact and compute a composite quality score.

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `cleaned_artifact_id` | string | Yes | Artifact ID of the `cleaned_document` to curate |
| `source_id` | string | Yes | Source registry ID |

**Response:** `CurateResponse`

```json
{
  "artifact_id": "art_019f...",
  "status": "curated",
  "cached": false,
  "quality_score": 0.84,
  "dedup_status": "unique"
}
```

`status` values: `curated`, `cached`.

**Error codes:** `422` — artifact not found.

---

### `POST /curate/dedupe`

Run corpus-wide MinHash batch deduplication over all `cleaned_document` artifacts. Builds one MinHashLSH index over the entire corpus in a single pass and updates `dedup_status` on each artifact's `curated_document` child.

**Request body:** None.

**Response:** `DedupeResponse`

```json
{
  "total": 350,
  "unique": 310,
  "near_dup": 35,
  "skipped_no_curation": 5
}
```

---

## datasets

### `POST /datasets/examples`

Generate a dataset training/eval example. Routes to `generate_qa_example` (kind `qa`) or `generate_instruction_example` (kind `instruction`).

**Request body:**

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `kind` | string | Yes | `^(qa\|instruction)$` | Example type |
| `source_artifact_id` | string | Yes | min_length=1 | `chunk` artifact ID for `qa`; `enriched_document` ID for `instruction` |
| `dataset_name` | string | Yes | min_length=1 | Logical dataset name (get-or-create) |

**Response:** `GenerateDatasetResponse`

```json
{
  "status": "generated",
  "example_id": "dex_019f...",
  "dataset_id": "019f...",
  "cost_usd": 0.0023
}
```

**Error codes:** `422` — artifact not found, wrong artifact type, or invalid kind.

---

### `GET /datasets`

List curated datasets with pagination.

**Query parameters:**

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `limit` | int | `50` | 1–200 | Maximum results |
| `offset` | int | `0` | >= 0 | Pagination offset |

**Response:** `list[DatasetOut]`

```json
[
  {
    "dataset_id": "019f...",
    "name": "healthcare-qa-v1",
    "created_at": "2026-07-07T12:00:00+00:00",
    "row_count": 142
  }
]
```

---

### `GET /datasets/{dataset_id}`

Get a single dataset by registry ID.

**Path parameters:** `dataset_id` (string) — Dataset registry ID.

**Response:** `DatasetOut` (same shape as list item above).

**Error codes:** `404` — dataset not found.

---

## export

### `POST /exports`

Export the corpus or a dataset to the gold zone.

**Request body:**

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `kind` | string | Yes | `^(rag-corpus\|pretrain\|finetune)$` | Export type |
| `dataset_name` | string | No (required for `finetune`) | max_length=255 | Dataset name for fine-tune export |

**Response:** `ExportResponse`

```json
{
  "dataset_id": "019f...",
  "storage_uri": "s3://klake-data/gold/rag-corpus-20260707.parquet",
  "row_count": 2840,
  "skipped_dangling_lineage": 3
}
```

**Error codes:** `422` — train/eval contamination detected, missing `dataset_name` for finetune, or dataset not found.

---

## lineage

### `GET /lineage/{artifact_id}`

Resolve the full ancestry chain of an artifact. Walks from the given artifact up to the `raw_document` root via a recursive CTE on `artifacts.parent_artifact_id`.

**Path parameters:** `artifact_id` (string) — Full artifact ID (e.g. `chk_019f...`).

**Response:** `list[LineageNode]` ordered by depth (depth 0 = queried artifact, last = raw_document root).

```json
[
  {
    "id": "chk_019f...",
    "artifact_type": "chunk",
    "content_hash": "sha256:abc...",
    "created_at": "2026-07-07T10:20:00+00:00",
    "pipeline_version": "0.1.0+g1a2b3c4",
    "storage_uri": "s3://klake-data/silver/chk_019f...",
    "source_id": "src_019f...",
    "parent_artifact_id": "doc_019f...",
    "depth": 0,
    "section_path": "§3.2 Administrative Safeguards",
    "page": 14,
    "mime_type": "text/plain"
  },
  {
    "id": "doc_019f...",
    "artifact_type": "parsed_document",
    "depth": 1,
    "...": "..."
  },
  {
    "id": "art_019f...",
    "artifact_type": "raw_document",
    "depth": 2,
    "parent_artifact_id": null,
    "...": "..."
  }
]
```

**Error codes:** `404` — artifact not found.

---

## domains

### `POST /domains/load`

Load a domain pack by name and bulk-register its `crawl`-type sources. Upload-type sources are counted but not auto-registered. Existing sources (by normalized URL) are silently skipped. Idempotent.

**Request body:**

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `name` | string | Yes | `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$` | Domain pack name (must match a `domains/` directory) |

**Response:** `DomainLoadResponse`

```json
{
  "name": "healthcare",
  "loaded_count": 24,
  "skipped_count": 0,
  "upload_required_count": 4
}
```

**Error codes:** `404` — domain pack directory not found. `422` — invalid domain name format.

---

### `GET /domains/{name}/sources`

List `sources.yaml` entries for a domain pack. Reads the pack's `sources.yaml` directly — no DB access.

**Path parameters:** `name` (string) — Domain pack name.

**Response:** `list[dict]` — raw `SourceEntry` dicts from `sources.yaml` (see [domain-packs.md](domain-packs.md) for field definitions).

**Error codes:** `404` — domain pack not found. `422` — invalid domain name format.

---

## Security Notes

- **Collection names** are validated against `^[a-zA-Z0-9_-]{1,64}$` before being passed to Qdrant. Invalid names return 422.
- **Domain names** are validated against `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$` at both the Pydantic schema level and with a defence-in-depth check in the handler. Path traversal via domain name is blocked at schema validation.
- **Upload file paths** are confined to `KLAKE_UPLOAD_ROOT` by `_safe_upload_path()`. Any path that resolves outside the configured root returns 400.
- **All DB queries** use parameterized SQLAlchemy ORM `select()` calls — no raw SQL string interpolation anywhere in the API.
- **Input bounds** — `top_k` (1–100), `min_quality_score` (0.0–1.0), `limit` (1–200), `max_pages` (1–10000), `query` (1–500 chars) are all enforced by Pydantic `ge`/`le` constraints before the handler runs.
- **Structured logging** — all log calls use structlog with structured key-value fields; no credential values are ever logged (database URLs are logged with the credential portion stripped).
