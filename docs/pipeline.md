# Pipeline

## Overview

The pipeline transforms raw source material into AI-ready artifacts through a sequence of distinct stages. Each stage is implemented as a plain Python function in `src/knowledge_lake/pipeline/`. Dagster assets in `src/knowledge_lake/dagster_defs/assets.py` wrap these same functions — no logic is duplicated. The CLI commands and API endpoints also call the same functions. This means there are three execution paths (CLI, API, Dagster) all backed by identical pipeline logic.

For data lake zone definitions and the registry data model, see [architecture.md](architecture.md).

## Stage Map

| Stage | Input | Output Artifact | Key Function(s) |
|-------|-------|----------------|----------------|
| Ingest | Source URL or local file | `raw_document` | `pipeline.ingest.ingest_url`, `pipeline.ingest.ingest_file` |
| Crawl | Source URL | `raw_document` + `bronze_document` per page | `pipeline.crawl.crawl_source` |
| Parse | `raw_document` | `parsed_document` | `pipeline.parse.parse` |
| Clean | `parsed_document` | `cleaned_document` | `pipeline.clean.clean` |
| Chunk | `parsed_document` (in-memory) | `chunk` (N per doc) | `pipeline.chunk.chunk` |
| Enrich | `cleaned_document` | `enriched_document` | `pipeline.enrich.enrich_document` |
| Curate | `cleaned_document` | `curated_document` | `pipeline.curate.curate_document` |
| Batch Dedup | Corpus-wide `cleaned_document` set | Updates `dedup_status` on `curated_document` children | `pipeline.curate.batch_dedup_corpus` |
| Embed | `chunk` artifacts (texts) | Dense vectors (in-memory, then indexed) | `pipeline.embed.embed` |
| Index | `chunk` artifacts + vectors | Qdrant points | `pipeline.index.index` |
| Search | Qdrant query | `Hit` list with citation fields | `pipeline.search.search` |
| Generate Dataset | `chunk` (qa) or `enriched_document` (instruction) | `DatasetExample` | `pipeline.datasets.generate_qa_example`, `pipeline.datasets.generate_instruction_example` |
| Export | `curated_document` + `DatasetExample` | Gold-zone Parquet / JSONL | `pipeline.export.export_rag_corpus`, `pipeline.export.export_pretrain_corpus`, `pipeline.export.export_finetune_dataset` |

## Stage Details

### Ingest

**Input:** Source URL (HTTP/HTTPS) or local file path.
**Output artifact:** `raw_document` stored at `raw/{sha256}` in S3.

The SHA256 of the raw bytes is computed before any S3 write. If the registry already contains a row with `(content_hash, artifact_type='raw_document')`, the existing IDs are returned immediately — no re-download, no duplicate S3 write. This makes ingest idempotent.

Registry fields stored: `source_id`, `content_hash`, `storage_uri` (`s3://bucket/raw/{sha256}`), `mime_type`, `pipeline_version`.

`ingest_url` performs an SSRF guard before downloading (private IP ranges, localhost, and link-local addresses are rejected). `ingest_file` validates the path is inside `KLAKE_UPLOAD_ROOT`.

### Crawl

**Input:** Source URL.
**Output artifacts:** `raw_document` (HTML bytes) + `bronze_document` (cleaned markdown) per successfully fetched page.

`crawl_source` spawns the configured `CrawlerPlugin`. For each URL in the crawl:

1. `start_crawl(source_url, config)` returns a `CrawlJob` with a `job_id`.
2. Per-URL state is tracked in `crawl_states` (status: `pending`, `complete`, `failed`, `robots_blocked`).
3. Robots.txt is respected per the crawl config (`robots_txt: true`). Blocked URLs get `robots_blocked` status and are not retried.
4. Rate limiting is applied per host using `rate_limit_rps` from the source's `crawl_config`.
5. The crawl is resume-safe: re-running for the same source URL skips all URLs already in `complete` status.

**Scrapy isolation:** The Scrapy adapter runs each crawl job as a subprocess (`python -m scrapy_spider`). The Twisted reactor lives and dies with the child process, preventing reactor-restart conflicts in long-running API/Dagster processes. The child writes base64-encoded HTML per page as JSONL to stdout; the parent parses the output after subprocess completion.

Two artifacts per page are created: one `raw_document` (HTML bytes in the raw zone) and one `bronze_document` (cleaned markdown in the bronze zone).

### Parse

**Input artifact:** `raw_document`.
**Output artifact:** `parsed_document` stored in `silver/{artifact_id}`.

The parse stage runs a fallback chain defined in `KLAKE_PARSE__CHAIN` (default: `["docling", "json_xml", "unstructured", "tika"]`). For each parser:

1. `can_parse(mime_type)` — if True, the parser is called.
2. The returned `ParsedDoc.metadata` carries a `quality_score` (float 0.0–1.0).
3. If `quality_score < KLAKE_PARSE__QUALITY_THRESHOLD` (default 0.4), the next parser in the chain is tried.
4. The first parser that meets the quality threshold wins; its output is stored.

Scores in the "gray zone" (`KLAKE_PARSE__QUALITY_GRAY_ZONE`, default 0.3–0.6) can trigger an optional LLM coherence spot-check (`KLAKE_PARSE__LLM_SPOT_CHECK=true`).

The `ParsedDoc` returned by the parser contains:
- `text: str` — full document text (markdown or plain).
- `sections: list[Section]` — per-section metadata: `heading`, `section_path` (e.g. `§3.2`), `page` (1-indexed), `text`, `is_table`.
- `metadata: dict` — document-level metadata (page count, title, etc.).

### Clean

**Input artifact:** `parsed_document`.
**Output artifact:** `cleaned_document` stored in `silver/{artifact_id}`.

The clean stage performs:

1. **Boilerplate removal** — repeated headers, footers, and navigation elements are stripped. This runs _before_ MinHash computation to prevent false near-duplicate matches caused by shared boilerplate (decision from Phase 3).
2. **Whitespace normalization** — consecutive whitespace collapsed, Unicode normalized.
3. **Language detection** — `lingua-language-detector` identifies the primary language. Stored in `metadata_['language']`.
4. **Exact-hash dedup check** — SHA256 of cleaned text checked against existing `cleaned_document` rows. Exact duplicate → `dedup_status='exact_dup'`.
5. **Transient MinHash near-dup check** — a per-call MinHash LSH index built over previously seen hashes in this session. Near-duplicate → `dedup_status='near_dup'`. This is O(n) per call and is replaced by `batch_dedup_corpus` for production use.

Output fields stored: `artifact_id`, `language`, `dedup_status` (`unique`, `exact_dup`, `near_dup`), `content_hash`.

### Chunk

**Input:** `parsed_document` artifact ID + in-memory `ParsedDoc` (forwarded through Dagster's dep chain).
**Output artifacts:** N `chunk` artifacts stored in `silver/{artifact_id}`, one per chunk.

Token-aware chunking using `cl100k_base` tiktoken encoding:

- Maximum `KLAKE_CHUNK__MAX_TOKENS` (default 512) tokens per chunk.
- `KLAKE_CHUNK__OVERLAP_TOKENS` (default 64) token overlap between adjacent chunks from the same section.
- **Tables are atomic** — a `Section` with `is_table=True` is never split across chunks, even if it exceeds `max_tokens`. An oversized table emits as a single chunk with `oversized=True` in its metadata.
- **Section-aware** — each chunk inherits `section_path` and `page` from its parent `Section`, enabling exact citation without re-reading the document.

Each chunk is registered as a `chunk` artifact in the registry with its `parent_artifact_id` pointing to the `parsed_document`.

### Enrich

**Input artifact:** `cleaned_document`.
**Output artifact:** `enriched_document` stored in `silver/{artifact_id}`.

**Two-phase extraction:**

1. **Deterministic first** — title extracted from `metadata_`, headings, and date patterns via regex. No LLM call. Sets `title`, `headings`, `dates` fields passed to the LLM prompt as structured context.
2. **LLM call** — a single cached LiteLLM call using the `strong_model` alias. Cache key is `(prompt_version, content_hash)`. The document excerpt is capped at `KLAKE_ENRICH__EXCERPT_CHARS` (default 4000) characters to control cost and prompt-injection surface.

**Budget cap:** If `llm_spend.total_cost_usd >= KLAKE_ENRICH__BUDGET_USD` (default $5.00), the enrichment is skipped with `status='skipped_budget_exceeded'`.

**Domain injection:** If `KLAKE_DOMAIN__DOMAIN_NAME` is set, the domain pack's `prompts/enrich.j2` is loaded and injected as the LLM system prompt, improving extraction quality for domain-specific terminology.

Output fields: `title`, `summary`, `document_type`, `organization`, `jurisdiction`, `keywords`, `entities`, `quality_score` (LLM-judged confidence 0.0–1.0).

Return statuses: `enriched`, `cached`, `skipped_budget_exceeded`, `skipped_enrichment_failed`.

### Curate

**Input artifact:** `cleaned_document`.
**Output artifact:** `curated_document` stored in `silver/{artifact_id}`.

DataTrove-style quality filters run by calling `.filter(doc)` on in-memory `datatrove.Document` objects (never `.run()` or `LocalPipelineExecutor` — no file I/O). Each filter returns pass/fail:

- `LengthFilter` — minimum/maximum word count (Gopher defaults).
- `RepetitionFilter` — repetition fraction heuristics.
- `BoilerplateFilter` — known boilerplate patterns.
- `LanguageFilter` — language confidence check.
- `GopherQualityFilter` — multiple Gopher quality heuristics.

All filters run regardless of order; pass/fail is recorded for every filter.

**Composite quality score:**

```
quality_score = parse_quality * 0.30 + enrich_quality * 0.40 + filter_pass_ratio * 0.30
```

where `filter_pass_ratio` is the fraction of filters that passed. This score is stored on the `curated_document` artifact's `quality_score` column and can be queried via `GET /curated-documents?min_quality_score=...`.

Return statuses: `curated`, `cached`.

### Batch Dedup

**Input:** All `cleaned_document` artifacts in the corpus.
**Output:** Updates `dedup_status` field in the `metadata_` JSON of `curated_document` children.

`batch_dedup_corpus()` builds ONE MinHashLSH index over the entire corpus in a single pass, resolving the O(n) scaling issue of the per-call transient near-dup check. Near-duplicate artifacts have their `curated_document` child updated with `dedup_status='near_dup'`. Unique artifacts are marked `dedup_status='unique'`.

Run after bulk curation to identify redundant content before export.

### Embed

**Input:** List of `chunk` artifact dicts (with `text` fields).
**Output:** Dense float vectors (list of lists) + `dim` integer.

`embed(chunks)` extracts texts from the chunk dicts, calls the configured `EmbedderPlugin.embed(texts)`, and returns `(vectors, dim)`. No storage at this stage — vectors are passed in-memory to the index stage.

### Index

**Input:** `chunk` artifact dicts + their dense vectors + `dim` + the target Qdrant collection alias.
**Output:** Indexed Qdrant point IDs.

`index(chunks, vectors, dim, parsed_artifact_id, collection)`:

1. Calls `ensure_aliased_collection(alias, dim)` to idempotently bootstrap the first versioned physical collection behind the alias.
2. Fetches enrichment metadata for the `parsed_artifact_id` from the registry (domain, document_type, keywords, quality_score) in a single DB query.
3. Constructs `VectorPoint` objects with citation payload: `document`, `section_path`, `page`, `chunk_id`, plus enrichment fields.
4. Calls `vectorstore.upsert(physical_collection, points)` to write all points to Qdrant.

Each Qdrant point ID is a bare UUID (the `chk_` prefix stripped); the full prefixed ID is stored in the payload as `chunk_id`.

### Search

**Input:** Natural-language query string + optional filters.
**Output:** `list[Hit]` with citation fields.

`search(q, collection, top_k, domain, document_type, min_quality_score)`:

1. Embeds the query using the configured embedder.
2. Builds a Qdrant `Filter` from the optional payload filter fields.
3. Calls `vectorstore.search(collection, query_vector, top_k, filter)`.
4. Returns `Hit` objects with: `id`, `score`, `document`, `section_path`, `page`, `chunk_id`, `text`, `domain`, `document_type`, `keywords`, `quality_score`.

### Generate Dataset

**Input:** Source artifact (`chunk` for qa, `enriched_document` for instruction) + dataset name.
**Output:** `DatasetExample` row in the registry.

Two modes:

- **`generate_qa_example`** — takes a `chunk` artifact, sends the chunk text to the `eval_model` alias, returns a `QAPairResult` with `question`, `answer`, and `citation_chunk_id`.
- **`generate_instruction_example`** — takes an `enriched_document` artifact, sends the document text to the `strong_model` alias, returns an `InstructionPairResult` with `instruction`, `input`, `output`.

Cache key is `(prompt_version, content_hash)` stored in the `DatasetExample.payload` as `_cache_key`. Budget cap via a separate `dataset_generation` LLM spend scope (distinct from the global enrichment scope).

### Export

Three export modes, all writing to the `gold/` zone in S3:

**`rag-corpus`** (`export_rag_corpus`):
Joins all `chunk` artifacts with their enrichment metadata. Writes a Parquet file using Polars for columnar output. Columns include chunk text, `section_path`, `page`, `chunk_id`, `domain`, `document_type`, `keywords`, `quality_score`.

**`pretrain`** (`export_pretrain_corpus`):
Exports `curated_document` artifacts as JSONL, one `{"text": "..."}` object per document. Only includes documents with `quality_score >= KLAKE_EXPORT__MIN_QUALITY_SCORE_FOR_PRETRAIN` (default 0.4).

**`finetune`** (`export_finetune_dataset`):
Exports `DatasetExample` rows from the named dataset as OpenAI chat-messages JSONL:
```json
[{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
```
Skips examples with dangling `source_artifact_id` (SET NULL after artifact deletion).

**Train/eval contamination guard:** All three export functions check for undocumented overlap between training and evaluation artifacts. If contamination is found and the artifact ID is not listed in `KLAKE_EXPORT__CONTAMINATION_OVERRIDE_ARTIFACT_IDS`, the export raises `TrainEvalContaminationError` (HTTP 422). This is a hard gate — no partial export on contaminated corpora.

## Dagster Assets

The twelve registered Dagster software-defined assets wrap the plain pipeline functions with retry policies and resource injection.

### Core pipeline assets (7)

All carry `RetryPolicy(max_retries=2, delay=1, backoff=Backoff.EXPONENTIAL)`:

| Asset | Wraps | Group |
|-------|-------|-------|
| `ingest_raw_document` | `pipeline.ingest.ingest_file` / `ingest_url` | `pipeline` |
| `parsed_document` | `pipeline.parse.parse` | `pipeline` |
| `clean_document` | `pipeline.clean.clean` | `pipeline` |
| `chunk_document` | `pipeline.chunk.chunk` | `pipeline` |
| `enrich_document` | `pipeline.enrich.enrich_document` | `pipeline` |
| `embed_chunks` | `pipeline.embed.embed` | `pipeline` |
| `index_chunks` | `pipeline.index.index` | `pipeline` |

**Dependency chain:** `ingest_raw_document → parsed_document → clean_document → {chunk_document, enrich_document} → embed_chunks → index_chunks`

`clean_document` fans out into two parallel branches — `chunk_document` and `enrich_document` both depend on `clean_document`; neither blocks the other.

The in-memory `ParsedDoc` is forwarded from `parsed_document` through `clean_document` to `chunk_document` via the Dagster output dict — no re-fetch from S3 (explicit-storage pattern: no IO managers for bytes).

### Additional assets (5)

| Asset | RetryPolicy | Notes |
|-------|------------|-------|
| `curate_document_asset` | `max_retries=2, exponential` | Parallel branch off `clean_document`; excluded from `core_pipeline_e2e_job` |
| `generate_dataset` | `max_retries=2, exponential` | Requires separate `source_artifact_id` run config; excluded from `core_pipeline_e2e_job` |
| `export_rag_corpus` | `max_retries=1, delay=2 (linear)` | Export group |
| `export_pretrain_corpus` | `max_retries=1, delay=2 (linear)` | Export group |
| `export_finetune_dataset` | `max_retries=1, delay=2 (linear)` | Export group; requires `dataset_name` run config |

Export assets use linear delay with only 1 retry because `TrainEvalContaminationError` is a business-logic failure, not a transient error — exponential backoff would mask a persistent problem.

### `core_pipeline_e2e_job`

Selects exactly the 7 core pipeline assets (ingest through index). `curate_document_asset` and `generate_dataset` are deliberately excluded — they require separate `source_artifact_id` run config that is not part of the ingest-to-index pipeline chain. (Renamed from `healthcare_e2e_job` — KL-16: the asset selection is domain-agnostic, so a domain-specific name in framework core was misleading.)

## Short-Circuit: `klake ingest-url`

`klake ingest-url <URL>` chains ingest → parse → chunk → embed → index in a single CLI call. Equivalent to running the Dagster pipeline steps manually but useful for quick ad-hoc ingestion of a single document without starting the Dagster UI.
