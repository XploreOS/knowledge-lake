---
phase: quick
plan: 260707-ieb
type: execute
wave: 1
depends_on: []
files_modified:
  - docs/architecture.md
  - docs/pipeline.md
  - docs/api-reference.md
  - docs/domain-packs.md
  - docs/configuration.md
autonomous: true
requirements: []
must_haves:
  truths:
    - "docs/ contains five focused reference documents, each covering a distinct concern"
    - "architecture.md explains data lake zones, registry data model, and plugin protocol contracts"
    - "pipeline.md traces each stage (ingest→parse→clean→chunk→enrich→curate→embed→index→export) with artifact types at every transition"
    - "api-reference.md lists every FastAPI endpoint grouped by tag with request/response shapes"
    - "domain-packs.md explains the directory convention and every file a new domain pack requires"
    - "configuration.md lists every env var, every settings field, and the LiteLLM model alias mapping"
    - "No doc duplicates README.md setup instructions — each cross-links to README instead"
  artifacts:
    - docs/architecture.md
    - docs/pipeline.md
    - docs/api-reference.md
    - docs/domain-packs.md
    - docs/configuration.md
  key_links:
    - "architecture.md links to pipeline.md for stage-by-stage details"
    - "api-reference.md links to pipeline.md for stage semantics"
    - "domain-packs.md links to configuration.md for KLAKE_DOMAIN__ env vars"
---

<objective>
Create five focused reference documents in docs/ that give depth beyond the README.

Purpose: README covers setup and quickstart. docs/ covers internals — architecture decisions,
the full API surface, domain pack conventions, pipeline stage contracts, and all configuration
knobs — so developers can extend, integrate, and operate the system without reading source code.

Output: docs/architecture.md, docs/pipeline.md, docs/api-reference.md, docs/domain-packs.md,
docs/configuration.md — each comprehensive within its concern, cross-linked to siblings.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md

# Source files — read for accurate doc content, not for modification
@src/knowledge_lake/plugins/protocols.py
@src/knowledge_lake/registry/models.py
@src/knowledge_lake/api/app.py
@src/knowledge_lake/dagster_defs/assets.py
@domains/healthcare/domain.yaml
@domains/healthcare/sources.yaml
@domains/healthcare/taxonomy.yaml
@domains/healthcare/prompts/enrich.j2
@domains/healthcare/validators/validate.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Write docs/architecture.md and docs/pipeline.md</name>
  <files>docs/architecture.md, docs/pipeline.md</files>
  <action>
Create the docs/ directory if it does not exist, then write two structural reference docs.

**docs/architecture.md** — covers the framework design, data lake zones, registry model, and plugin seam.

Sections to include:

1. **Overview** — One paragraph: domain-agnostic framework, tool-as-plugin philosophy, single source of truth in PostgreSQL registry, S3 for bytes, Qdrant for vectors. Point to README.md for setup.

2. **Data Lake Zones** — Four zones stored in S3 under distinct prefixes:
   - `raw/` — content-addressed by SHA256, WORM (four-layer: registry no-op + `s3://bucket/raw/{sha256}` key + `head_object` guard + bucket versioning/delete-deny policy). Never modified after first write.
   - `bronze/` — crawler markdown output (one file per crawled page), not WORM
   - `silver/` — parsed text, cleaned text, chunk text (one file per artifact)
   - `gold/` — exported Parquet, JSONL, chat-format fine-tuning datasets

   S3 key pattern: `{zone}/{artifact_id}` for silver/bronze; `raw/{sha256}` for the raw zone.

3. **Registry Data Model** — PostgreSQL schema managed by Alembic migrations. Describe each table:
   - `sources` — origin registrations; `normalized_url` enables URL-first dedup; `config` JSON holds domain, tags, crawl params
   - `artifacts` — self-referencing lineage tree (`parent_artifact_id` FK). Every byte written to S3 gets one row. Fields: `id` (prefixed UUIDv7), `artifact_type`, `content_hash` (SHA256), `pipeline_version`, `storage_uri` (s3:// URI), `quality_score`, `section_path`, `page_ref`, `mime_type`, `metadata_` (JSON). Unique constraint on `(content_hash, artifact_type)` prevents duplicate processing.
   - `lineage_events` — explicit labelled edges (ingested_from, parsed_from, chunked_from, etc.) complementing the implicit parent_artifact_id tree
   - `jobs` — crawl job records; `stats` JSON carries pages_fetched/errors/duration
   - `crawl_states` — per-URL state within a job (pending/complete/failed/robots_blocked); unique on `(job_id, normalized_url)`
   - `llm_spend` — accumulated cost per scope key; `scope="global"` is the Phase 4 MVP default
   - `vector_collections` — alias-to-physical-collection registry; `is_current` boolean enables auditable reindex history
   - `datasets` + `dataset_examples` — dataset registry and per-example lineage (not Artifact nodes — intentional, see D-08)

4. **ID Format** — Prefixed UUIDv7, always >= 40 chars: `src_`, `doc_`, `chk_`, `art_`, `dex_`, `cst_`, `job_`. Bare UUID (no prefix) is used for Qdrant point IDs; the full prefixed ID is stored in the Qdrant payload as `chunk_id`.

5. **Plugin System** — Five plugin protocols defined in `src/knowledge_lake/plugins/protocols.py`, each runtime-checkable:
   - `ParserPlugin` — `can_parse(mime_type) -> bool`, `parse(raw: bytes, mime_type) -> ParsedDoc`. Built-ins: DoclingParser (`docling`), UnstructuredParser (`unstructured`), TikaParser (`tika`), JsonXmlParser (`json_xml`). Selected via `KLAKE_PARSER` env var.
   - `EmbedderPlugin` — `embed(texts: list[str]) -> list[list[float]]`, exposes `name` and `dim`. Built-ins: SentenceTransformerEmbedder (`local`, dim=384, zero creds), LiteLLMEmbedder (`litellm`, routes through `embedding_model` alias). Selected via `KLAKE_EMBEDDER`.
   - `VectorStorePlugin` — full collection management + ANN search. Built-in: QdrantVectorStore (`qdrant`). Selected via `KLAKE_VECTORSTORE`.
   - `CrawlerPlugin` — `start_crawl`, `poll_status`, `get_results`. Built-ins: Crawl4AIAdapter (`crawl4ai`), ScrapyAdapter (`scrapy`), PlaywrightAdapter (`playwright`).
   - `DiscoveryPlugin` — `search(query, limit) -> list[DiscoveryResult]`. Built-in: SearXNGDiscovery (`searxng`). Selected via `settings.discovery`.

   Resolution: plain config-keyed resolver reads `KLAKE_PARSER` / `KLAKE_EMBEDDER` / `KLAKE_VECTORSTORE` and returns the matching built-in. No pluggy. New implementation = new class + register it in the resolver dict. No core code edits.

6. **Lineage Model** — Describe the ancestry walk: `lineage.resolve_ancestry(artifact_id)` executes a recursive CTE on `artifacts.parent_artifact_id` walking up to the raw_document root. Every node carries all six FOUND-06 fields. The `lineage_events` table adds explicit labelled edges for audit. Cross-link: see pipeline.md for artifact types at each stage.

7. **Key Architectural Constraints** — List verbatim from PROJECT.md: LiteLLM-only for LLM calls, task-based aliases (cheap_model/strong_model/eval_model/embedding_model), immutable raw zone, Dagster from day 1, deterministic before LLM.

---

**docs/pipeline.md** — traces every pipeline stage with artifact input/output types.

Sections to include:

1. **Overview** — The pipeline transforms raw source material into AI-ready artifacts. Each stage is a plain Python function in `src/knowledge_lake/pipeline/`. Dagster assets in `src/knowledge_lake/dagster_defs/assets.py` wrap these same functions — no logic duplication. CLI commands and API endpoints also call the same functions.

2. **Stage Map** — A table or numbered list showing the full sequence with artifact types:

   | Stage | Input Artifact | Output Artifact | Key Function |
   |-------|---------------|-----------------|--------------|
   | Ingest | (source URL or file) | `raw_document` | `pipeline.ingest.ingest_url` / `ingest_file` |
   | Crawl | (source URL) | `raw_document` + `bronze_document` per page | `pipeline.crawl.crawl_source` |
   | Parse | `raw_document` | `parsed_document` | `pipeline.parse.parse` |
   | Clean | `parsed_document` | `cleaned_document` | `pipeline.clean.clean` |
   | Chunk | `parsed_document` (+ `cleaned_document`) | `chunk` (N per doc) | `pipeline.chunk.chunk` |
   | Enrich | `cleaned_document` | `enriched_document` | `pipeline.enrich.enrich_document` |
   | Curate | `cleaned_document` | `curated_document` | `pipeline.curate.curate_document` |
   | Batch Dedup | corpus-wide | updates `dedup_status` on curated_documents | `pipeline.curate.batch_dedup_corpus` |
   | Index | `chunk` artifacts | Qdrant points | `pipeline.index.index` |
   | Search | Qdrant query | `Hit` list with citation fields | `pipeline.search.search` |
   | Generate Dataset | `chunk` or `enriched_document` | `DatasetExample` | `pipeline.datasets.generate_qa_example` / `generate_instruction_example` |
   | Export | `curated_document` + `DatasetExample` | gold-zone files | `pipeline.export.export_rag_corpus` / `export_pretrain_corpus` / `export_finetune_dataset` |

3. **Stage Details** — For each stage, explain:
   - **Ingest**: Single-URL download or local file upload. SHA256 computed, stored at `raw/{sha256}` in S3. Registry lookup: if same hash already exists → return existing IDs (no-op). Stores: source_id, content_hash, storage_uri, mime_type.
   - **Crawl**: Spawns the configured CrawlerPlugin. Scrapy runs in a subprocess (subprocess isolation) with JSONL IPC; Crawl4AI runs async. Per-URL state tracked in `crawl_states`. Respects robots.txt. Rate-limited per host. Resume-safe: re-running skips `complete` URLs. Two artifacts per page: `raw_document` (HTML bytes) + `bronze_document` (cleaned markdown).
   - **Parse**: Fallback chain: Docling → JSON/XML direct → Unstructured → Tika. Parser selected by `can_parse(mime_type)`. Quality score stored in `metadata_` JSON. If score < threshold, next parser in chain is tried. Returns `ParsedDoc` (full text + list of `Section` objects with heading, section_path, page).
   - **Clean**: Boilerplate removal (headers/footers stripped before MinHash to prevent false near-dups), whitespace normalization, language detection via lingua, exact-hash dedup check, transient MinHash near-dup check (O(n) per call — replaced by batch dedup in production). Output: `cleaned_document` artifact + `language` + `dedup_status`.
   - **Chunk**: Token-aware chunking respecting configurable max_tokens and overlap. Tables (`Section.is_table=True`) are atomic — never split even if oversized (tagged `oversized=True`). Section-aware: chunks inherit `section_path` and `page` from parent Section. Each chunk = one `chunk` artifact in registry + one point in Qdrant (after index stage).
   - **Enrich**: Deterministic extraction first (title from metadata_, headings, dates) — no LLM. Then single cached LiteLLM call using `strong_model` alias. Cache key = `(prompt_version, content_hash)`. Budget cap: if `llm_spend.total_cost_usd >= budget` → status `skipped_budget_exceeded`. Output fields: title, summary, document_type, organization, jurisdiction, keywords, entities, quality_score. Domain system prompt injected if `KLAKE_DOMAIN__DOMAIN_NAME` is set.
   - **Curate**: DataTrove-style quality filters run via `.filter(doc)` on in-memory `datatrove.Document` objects (never `.run()` / LocalPipelineExecutor). Filters: length, repetition, boilerplate heuristics, language, Gopher heuristics. Composite quality score = `parse_quality * 0.30 + enrich_quality * 0.40 + filter_pass_ratio * 0.30`. Output: `curated_document` artifact.
   - **Batch Dedup**: Builds ONE MinHash LSH index over all `cleaned_document` artifacts. Marks near-duplicates by updating `dedup_status` on their `curated_document` child. Run after bulk curation.
   - **Index**: `embed(chunk_texts)` via the configured EmbedderPlugin, then `upsert(collection, points)` into Qdrant. Each VectorPoint payload includes: document, section_path, page, chunk_id, domain, document_type, keywords, quality_score. Alias-managed collections via `ensure_aliased_collection`. Zero-downtime reindex via atomic alias swap.
   - **Export**: Three modes. `rag-corpus` → Parquet with chunk text + all payload metadata (silver zone). `pretrain` → JSONL with one `{"text": ...}` per curated_document. `finetune` → JSONL chat-format `[{"role": "user", "content": instruction}, {"role": "assistant", "content": output}]`. All write to `gold/` zone in S3.

4. **Dagster Assets** — Twelve registered assets: ingest_raw_document, parsed_document, clean_document, chunk_document, enrich_document, embed_chunks, index_chunks, curate_document_asset, generate_dataset, export_rag, export_pretrain, export_finetune. All carry `RetryPolicy(max_retries=2, delay=1, backoff=Backoff.EXPONENTIAL)` except export assets (max_retries=1, linear delay). `healthcare_e2e_job` selects the 7 core pipeline assets (curate and generate_dataset excluded — they require separate run config).

5. **Short-circuit: ingest-url** — `klake ingest-url URL` chains ingest → parse → chunk → embed → index in one call. Useful for quick ad-hoc ingestion; equivalent to running the Dagster pipeline steps manually.
  </action>
  <verify>
    <automated>ls /root/healthlake/docs/architecture.md /root/healthlake/docs/pipeline.md && wc -l /root/healthlake/docs/architecture.md /root/healthlake/docs/pipeline.md | awk 'NR==3{if($1<50){exit 1}}'</automated>
  </verify>
  <done>docs/architecture.md covers zones, registry model, plugin protocols, and ID format with concrete field names. docs/pipeline.md covers all 12 stages with input/output artifact types and key implementation notes. Both files exist and have substantive content (each > 150 lines).</done>
</task>

<task type="auto">
  <name>Task 2: Write docs/api-reference.md and docs/domain-packs.md</name>
  <files>docs/api-reference.md, docs/domain-packs.md</files>
  <action>
Write two reference docs.

**docs/api-reference.md** — complete REST API reference grouped by tag. Interactive docs available at `http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/redoc` (ReDoc). This doc captures the same information as a static reference.

Group endpoints exactly as they appear in the FastAPI app (tags): ops, search, pipeline, ingestion, discovery, crawl, registry, curation, datasets, export, lineage, domains.

For each endpoint include: method + path, short description, request schema (query params or JSON body with field names/types/constraints), response schema (field names/types), error codes.

**ops**
- `GET /health` — Returns `{"status": "ok"}`. No params.

**search**
- `GET /search` — Semantic search over indexed chunks. Query params: `q` (string, required), `top_k` (int, 1–100, default 5), `collection` (string, default `klake_chunks`), `domain` (string, optional), `document_type` (string, optional), `min_quality_score` (float 0.0–1.0, optional). Response: list of `SearchHit` — fields: `id`, `score` (float), `document`, `section_path`, `page`, `chunk_id`, `text`, `domain`, `document_type`, `keywords` (list[str]), `quality_score`.

**pipeline**
- `POST /reindex` — Zero-downtime alias reindex. Query param: `collection` (default `klake_chunks`). Response: `ReindexResponse` — fields: `new_physical`, `old_physical`.
- `POST /parse` — Parse a raw_document artifact. Body: `{"raw_artifact_id": str, "source_id": str, "mime_type": str}`. Response: `{"artifact_id", "quality_score", "parser_used", "content_hash"}`.
- `POST /clean` — Clean a parsed_document. Body: `{"parsed_artifact_id": str, "source_id": str}`. Response: `{"artifact_id", "language", "dedup_status", "content_hash"}`.
- `POST /chunk` — Chunk a parsed_document. Body: `{"parsed_artifact_id": str, "source_id": str}`. Response: `{"chunk_count": int, "chunk_ids": list[str]}`. Note: reconstructs a minimal ParsedDoc from stored text; Dagster pipeline uses in-memory ParsedDoc for section-aware chunking.
- `POST /enrich` — LLM-enrich a cleaned_document. Body: `{"cleaned_artifact_id": str, "source_id": str}`. Response: `{"artifact_id", "status": "enriched"|"cached"|"skipped_budget_exceeded"|"skipped_enrichment_failed", "cached": bool, "quality_score"}`.
- `GET /curated-documents` — List curated_document artifacts. Query param: `min_quality_score` (float 0.0–1.0, optional). Response: list of `{"artifact_id", "quality_score", "dedup_status", "created_at"}`.

**ingestion**
- `POST /sources` — Register a source URL. Body: `{"url": str (min_length=8), "name": str (optional), "domain": str (optional), "license_type": str (optional)}`. Response: `SourceOut` with `source_id`, `is_new` (bool). 201 even if existing (silent dedup).
- `POST /uploads` — Upload a file from server filesystem. Query params: `file_path` (absolute path, constrained to `KLAKE_UPLOAD_ROOT`), `source_name` (default `uploaded-file`), `license_type` (default `unknown`). Response: `{"artifact_id", "source_id", "is_new"}`. Security: path must be inside upload root.

**discovery**
- `POST /discover` — Run SearXNG discovery. Body: `{"query": str (1–500 chars), "limit": int (1–100)}`. Response: `{"query", "total", "results": list of {"url", "title", "source_id", "status": "registered"|"existing"|"skipped"}}`.

**crawl**
- `POST /crawl-jobs` — Start a crawl job. Body: `{"source_url": str (min_length=8), "crawler": str (optional, defaults to configured crawler), "max_pages": int (1–10000)}`. Response: `{"job_id", "source_id", "crawler", "status", "states": {"complete", "robots_blocked", "failed", "pending"}}`.
- `GET /crawl-jobs/{job_id}` — Get crawl job status. Path param: `job_id`. Response: same shape as POST. 404 if unknown.

**registry**
- `GET /sources` — List sources. Query params: `domain` (optional), `limit` (1–200, default 50), `offset` (default 0). Response: list of `SourceListItem`.
- `GET /sources/{source_id}` — Get source by ID. 404 if not found.
- `GET /documents` — List artifacts. Query params: `artifact_type` (optional), `source_id` (optional), `limit`, `offset`. Response: list of `ArtifactOut` — fields: `id`, `artifact_type`, `source_id`, `parent_artifact_id`, `content_hash`, `created_at`, `storage_uri`, `mime_type`.
- `GET /documents/{artifact_id}` — Get artifact by ID. 404 if not found.

**curation**
- `POST /curate` — Curate a cleaned_document. Body: `{"cleaned_artifact_id": str, "source_id": str}`. Response: `{"artifact_id", "status": "curated"|"cached", "cached": bool, "quality_score", "dedup_status"}`.
- `POST /curate/dedupe` — Corpus-wide MinHash dedup. No body. Response: `{"total", "unique", "near_dup", "skipped_no_curation"}`.

**datasets**
- `POST /datasets/examples` — Generate a dataset example. Body: `{"kind": "qa"|"instruction", "source_artifact_id": str, "dataset_name": str}`. `qa` requires a `chunk` artifact as source; `instruction` requires an `enriched_document`. Response: `{"status", "example_id", "dataset_id", "cost_usd"}`.
- `GET /datasets` — List datasets. Query params: `limit`, `offset`. Response: list of `{"dataset_id", "name", "created_at", "row_count"}`.
- `GET /datasets/{dataset_id}` — Get dataset by ID. 404 if not found.

**export**
- `POST /exports` — Export to gold zone. Body: `{"kind": "rag-corpus"|"pretrain"|"finetune", "dataset_name": str (required only for finetune)}`. Response: `{"dataset_id", "storage_uri", "row_count", "skipped_dangling_lineage"}`. 422 on train/eval contamination.

**lineage**
- `GET /lineage/{artifact_id}` — Full ancestry chain. Path param: `artifact_id`. Response: list of `LineageNode` ordered depth-first (leaf=0, root=last). Each node: `id`, `artifact_type`, `content_hash`, `created_at`, `pipeline_version`, `storage_uri`, `source_id`, `parent_artifact_id`, `depth`, `section_path`, `page`, `mime_type`. 404 if not found.

**domains**
- `POST /domains/load` — Load a domain pack and register its sources. Body: `{"name": str (letter-first, alphanumeric+hyphen/underscore, max 64)}`. Response: `{"name", "loaded_count", "skipped_count", "upload_required_count"}`. 404 if pack not found.
- `GET /domains/{name}/sources` — List sources.yaml entries for a domain pack. Returns raw SourceEntry dicts from sources.yaml. 404 if pack not found.

Add a section at the end: **Security Notes** — collection names validated against `^[a-zA-Z0-9_-]{1,64}$`; domain names against `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$`; upload file paths confined to KLAKE_UPLOAD_ROOT; all DB queries use parameterised ORM (no raw SQL).

---

**docs/domain-packs.md** — how domain packs work and how to create a new one.

Sections:

1. **What Is a Domain Pack** — A directory under `domains/<domain-name>/` loaded by convention by `DomainLoader.from_name(name)`. No core code changes needed to add a domain. Set `KLAKE_DOMAIN__DOMAIN_NAME=<name>` to activate it.

2. **Directory Structure** — Show the full tree:
   ```
   domains/
   └── mydomainname/
       ├── domain.yaml         # required — domain metadata
       ├── sources.yaml        # required — seed source list
       ├── taxonomy.yaml       # required — categories and codes
       ├── prompts/
       │   ├── enrich.j2       # required — LLM enrichment system prompt
       │   └── qa_generation.j2  # optional — used by generate-dataset qa
       └── validators/
           ├── __init__.py
           └── validate.py     # optional — domain-specific validation
   ```

3. **domain.yaml** — Fields: `name` (must match directory name), `version` (semver string), `description` (string). The healthcare example uses `name: healthcare`, `version: "1.0.0"`.

4. **sources.yaml** — A YAML list of source entries. Each entry fields:
   - `name` (str, required) — human-readable name for the source
   - `url` (str, required) — canonical URL
   - `source_type` (str) — `html`, `pdf`, `csv`, `xml`, `json`
   - `license` (str) — SPDX identifier or `public-domain`, `open`, `unknown`
   - `tags` (list[str]) — classification tags
   - `crawl_config` (dict) — `depth` (int), `rate_limit_rps` (float), `robots_txt` (bool), `max_pages` (int)
   - `ingest_type` (str) — `crawl` (auto-crawled by `klake init`) or `upload` (manual download required)

   Sources with `ingest_type: upload` are counted by `klake init` but not auto-registered — user must manually download and run `klake upload`. The healthcare pack has 28 total: 24 crawl-type, 4 upload-type (ICD-10-CM, NDC, LOINC, NPPES bulk files).

5. **taxonomy.yaml** — Domain-specific ontology (categories, codes, hierarchies). Content is loaded by `DomainLoader` and available to enrichment and validation logic. The healthcare taxonomy includes FHIR resource types, ICD chapters, CMS program categories, document types.

6. **Prompts** — Jinja2 templates rendered by `DomainLoader.render_prompt(template_name)`.
   - `enrich.j2` — **Required**. Injected as the system prompt for `pipeline.enrich.enrich_document()`. Template variable: `{{ domain_name }}`. The healthcare prompt instructs the LLM on FHIR, HIPAA, clinical terminology for better metadata extraction.
   - `qa_generation.j2` — Optional. Used by `pipeline.datasets.generate_qa_example()` when `KLAKE_DOMAIN__DOMAIN_NAME` is set. Template variable: `{{ domain_name }}`.
   - Custom prompts — any `.j2` file in `prompts/` can be loaded via `DomainLoader.render_prompt("custom.j2")`.

7. **validators/validate.py** — Optional Python module. Can contain domain-specific URL validation, source quality checks, or artifact validation logic. The healthcare validator checks for known healthcare domain URLs. Can be empty (just `pass` in the module body).

8. **DomainLoader API** — `DomainLoader.from_name(name, root=None)` class method. `root` defaults to the project root resolved from `settings.domain.domains_root`. Returns a loader with: `.domain` (domain.yaml dict), `.sources` (list of SourceEntry), `.taxonomy` (taxonomy.yaml dict), `.render_prompt(template_name)` (renders a Jinja2 template from `prompts/`).

9. **Registration** — `klake init --domain mydomainname` or `POST /domains/load {"name": "mydomainname"}` registers all crawl-type sources. Idempotent: existing sources (by normalized URL) are silently skipped.

10. **Healthcare Pack Reference** — Brief summary of the 28 healthcare sources: HL7 FHIR (hl7.org/fhir), US Core IG, CMS.gov, HHS/OCR (HIPAA Privacy, Security, Enforcement), ONC/HealthIT (USCDI), CDC, FDA (drug label, device), NIH NLM (MedlinePlus, DailyMed), NCI Thesaurus, ICD-10-CM (upload), HCPCS (CMS), LOINC (upload), RxNorm (NIH NLM), NDC (FDA, upload), NPPES (CMS, upload).

11. **Activating a Domain for Enrichment** — Set `KLAKE_DOMAIN__DOMAIN_NAME=mydomainname` before running `klake enrich` or `POST /enrich`. The enrichment pipeline will load `domains/mydomainname/prompts/enrich.j2` and inject it as the LLM system prompt. When unset, generic prompt is used.
  </action>
  <verify>
    <automated>ls /root/healthlake/docs/api-reference.md /root/healthlake/docs/domain-packs.md && grep -c "POST /domains/load" /root/healthlake/docs/api-reference.md</automated>
  </verify>
  <done>docs/api-reference.md lists all 24+ endpoints grouped by tag with request/response field names. docs/domain-packs.md covers all 5 required files, DomainLoader API, and the healthcare pack summary. Both files exist and api-reference.md contains the /domains/load endpoint.</done>
</task>

<task type="auto">
  <name>Task 3: Write docs/configuration.md</name>
  <files>docs/configuration.md</files>
  <action>
Write docs/configuration.md — the complete configuration reference.

Read `src/knowledge_lake/config/settings.py` and `docker-compose.yml` and `config.yaml` before writing (they contain the authoritative field lists).

Sections:

1. **Overview** — Configuration is loaded via pydantic-settings from environment variables. The settings class hierarchy uses nested models with `__` as the env prefix separator. Settings are accessed via `get_settings()` which is cached with `@lru_cache`. Point to README.md for initial `.env` setup.

2. **Settings Model Hierarchy** — Show the class tree:
   - `Settings` (top-level, env prefix `KLAKE_`)
     - `StorageSettings` (prefix `KLAKE_STORAGE__`) — S3/MinIO configuration
     - `DomainSettings` (prefix `KLAKE_DOMAIN__`) — active domain pack
   - Top-level scalar fields on `Settings`

3. **Storage Settings** (`KLAKE_STORAGE__*`) — Table:

   | Env Var | Field | Type | Default | Description |
   |---------|-------|------|---------|-------------|
   | `KLAKE_STORAGE__ACCESS_KEY_ID` | `access_key_id` | str | (required) | MinIO root user / AWS access key |
   | `KLAKE_STORAGE__SECRET_ACCESS_KEY` | `secret_access_key` | SecretStr | (required) | MinIO password / AWS secret key |
   | `KLAKE_STORAGE__ENDPOINT_URL` | `endpoint_url` | str | `http://minio:9000` | S3 endpoint; omit for AWS S3 |
   | `KLAKE_STORAGE__BUCKET` | `bucket` | str | `klake-data` | S3 bucket name |
   | `KLAKE_STORAGE__REGION` | `region` | str | `us-east-1` | AWS region |

   Note: When running `klake` locally (outside Docker), set `KLAKE_STORAGE__ENDPOINT_URL=http://localhost:9000`.

4. **Domain Settings** (`KLAKE_DOMAIN__*`) — Table:

   | Env Var | Field | Type | Default | Description |
   |---------|-------|------|---------|-------------|
   | `KLAKE_DOMAIN__DOMAIN_NAME` | `domain_name` | Optional[str] | None | Active domain pack (e.g. `healthcare`); controls enrichment prompt injection |
   | `KLAKE_DOMAIN__DOMAINS_ROOT` | `domains_root` | str | `domains` | Path to the domains/ directory |

5. **Top-Level Settings** (`KLAKE_*`) — Table:

   | Env Var | Field | Type | Default | Description |
   |---------|-------|------|---------|-------------|
   | `KLAKE_DATABASE_URL` | `database_url` | str | `postgresql+psycopg://klake:klake@localhost:5432/klake` | SQLAlchemy async URL |
   | `KLAKE_QDRANT_URL` | `qdrant_url` | str | `http://localhost:6333` | Qdrant HTTP endpoint |
   | `KLAKE_LITELLM_URL` | `litellm_url` | str | `http://localhost:4000` | LiteLLM proxy base URL |
   | `KLAKE_EMBEDDER` | `embedder` | str | `local` | Embedder plugin key: `local` or `litellm` |
   | `KLAKE_PARSER` | `parser` | str | `docling` | Parser plugin key |
   | `KLAKE_VECTORSTORE` | `vectorstore` | str | `qdrant` | Vector store plugin key |
   | `KLAKE_UPLOAD_ROOT` | `upload_root` | str | `/data/uploads` | Upload root directory (API path traversal guard) |
   | `KLAKE_PIPELINE_VERSION` | `pipeline_version` | str | auto from `importlib.metadata` | Version tag stamped on every artifact |

6. **Non-KLAKE Variables** — Other env vars read by the stack (not prefixed with KLAKE_):

   | Env Var | Service | Description |
   |---------|---------|-------------|
   | `POSTGRES_PASSWORD` | Docker Compose postgres | PostgreSQL password (default: `klake`) |
   | `AWS_BEDROCK_API_KEY` | LiteLLM | Bedrock bearer token; required for enrich/generate-dataset/export |
   | `LITELLM_MASTER_KEY` | LiteLLM | Proxy master key; leave empty for local dev |
   | `SEARXNG_SECRET_KEY` | SearXNG | SearXNG internal secret (auto-generated in compose) |

7. **Docker Compose Services** — Table of all nine services:

   | Service | Image | Port(s) | Purpose |
   |---------|-------|---------|---------|
   | `postgres` | `postgres:16` | `5432` | Registry PostgreSQL database |
   | `minio` | `minio/minio` | `9000` (API), `9001` (console) | S3-compatible object storage |
   | `minio-init` | `minio/mc` | — | One-shot bucket bootstrap; exits 0 when bucket created |
   | `qdrant` | `qdrant/qdrant` | `6333` (HTTP), `6334` (gRPC) | Vector database |
   | `litellm` | `ghcr.io/berriai/litellm` | `4000` | LiteLLM proxy; reads `config.yaml` |
   | `dagster-webserver` | (project image) | `3000` | Dagster asset graph and run history |
   | `dagster-daemon` | (project image) | — | Scheduler and sensor daemon |
   | `api` | (project image) | `8000` | Knowledge Lake FastAPI service |
   | `searxng` | `searxng/searxng` | `8888` | SearXNG meta-search for source discovery |

8. **LiteLLM Model Aliases** (`config.yaml`) — All LLM calls in business logic use task-based aliases, never hardcoded provider model IDs. The `config.yaml` at the project root maps aliases to Bedrock model IDs:

   | Alias | Bedrock Model | Purpose |
   |-------|--------------|---------|
   | `cheap_model` | `bedrock/anthropic.claude-instant-v1` or similar | Low-cost tasks, classification |
   | `strong_model` | `bedrock/anthropic.claude-3-5-sonnet-*` | Enrichment, instruction-tuning generation |
   | `eval_model` | `bedrock/anthropic.claude-3-5-sonnet-*` | QA pair generation, RAG eval |
   | `embedding_model` | `bedrock/amazon.titan-embed-text-v1` or `cohere.*` | LiteLLMEmbedder (when `KLAKE_EMBEDDER=litellm`) |

   To swap models: edit only `config.yaml`. No code changes.

   When `KLAKE_EMBEDDER=local`, the `SentenceTransformerEmbedder` uses `all-MiniLM-L6-v2` (384-dim) locally — no API calls, no credentials needed.

9. **Alembic Migrations** — Schema is managed by Alembic. Migrations live in `alembic/versions/`. Run `uv run alembic upgrade head` after any migration addition. Never run `Base.metadata.create_all()` in production.

10. **Runtime vs Docker** — Note the difference between in-container URLs (default settings, service names as hostnames) and local dev URLs. Provide a quick `.env.local-dev` snippet:
    ```
    KLAKE_DATABASE_URL=postgresql+psycopg://klake:klake@localhost:5432/klake
    KLAKE_STORAGE__ENDPOINT_URL=http://localhost:9000
    KLAKE_QDRANT_URL=http://localhost:6333
    KLAKE_LITELLM_URL=http://localhost:4000
    ```
  </action>
  <verify>
    <automated>ls /root/healthlake/docs/configuration.md && grep -c "KLAKE_STORAGE__" /root/healthlake/docs/configuration.md</automated>
  </verify>
  <done>docs/configuration.md exists and contains all KLAKE_ env vars, the StorageSettings and DomainSettings model tables, Docker Compose services table, LiteLLM alias mapping, and the local-dev note. grep for KLAKE_STORAGE__ returns at least 3 matches.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| doc author → docs/ | Documentation writing only; no production code or secrets modified |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation |
|-----------|----------|-----------|----------|-------------|------------|
| T-doc-01 | Information Disclosure | docs/ | low | accept | Docs describe public API contracts; no credentials or internal secrets included. Sensitive env vars documented by name/purpose only, never with values. |
</threat_model>

<verification>
All five docs exist:

```bash
ls -la /root/healthlake/docs/
```

Each doc has substantive content:

```bash
wc -l /root/healthlake/docs/*.md
```

No doc duplicates the README quickstart (setup steps, docker compose up, alembic upgrade head are not present in docs except as cross-references):

```bash
grep -l "docker compose up" /root/healthlake/docs/ || echo "No duplication found"
```
</verification>

<success_criteria>
- docs/ contains exactly 5 files: architecture.md, pipeline.md, api-reference.md, domain-packs.md, configuration.md
- Each file is > 100 lines with concrete content (no placeholder headings)
- architecture.md names all five plugin protocols, all registry table names, and the four data lake zones
- pipeline.md names the artifact type produced at each stage (raw_document, parsed_document, cleaned_document, chunk, enriched_document, curated_document)
- api-reference.md covers all 24+ endpoints with request/response field names
- domain-packs.md names all 5 required files and explains ingest_type crawl vs upload
- configuration.md covers all KLAKE_ prefixed env vars and the model alias table
</success_criteria>

<output>
Create `.planning/quick/260707-ieb-create-project-documentation-with-full-d/260707-ieb-SUMMARY.md` when done
</output>
