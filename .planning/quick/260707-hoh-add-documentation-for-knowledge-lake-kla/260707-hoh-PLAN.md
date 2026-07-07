---
phase: 260707-hoh
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - README.md
autonomous: true
requirements:
  - IFACE-01
must_haves:
  truths:
    - README.md exists at repo root with all four sections populated
    - Every shell command block is copy-paste ready with no placeholders requiring inference
    - Healthcare domain pack walkthrough covers init, crawl, ingest-url, enrich, search, export
    - New domain pack section covers the full directory structure and all required files
  artifacts:
    - README.md
  key_links:
    - README.md references docker-compose.yml service names and port numbers correctly
    - CLI commands match exactly what is implemented in src/knowledge_lake/cli/app.py
---

<objective>
Write the root README.md for the Knowledge Lake (klake) framework covering local setup,
the full pipeline, the healthcare domain pack, and how to add a new domain pack.

Purpose: Developers new to the project need a single document they can follow from
zero to a running system without reading source code.

Output: README.md at repo root (replaces the current empty file).
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@docker-compose.yml
@src/knowledge_lake/cli/app.py
@domains/healthcare/domain.yaml
@domains/healthcare/sources.yaml
@infra/litellm/config.yaml
</context>

<tasks>

<task type="auto">
  <name>Task 1: Write README.md with local setup, pipeline, healthcare domain, and new domain guide</name>
  <files>README.md</files>
  <action>
Write a comprehensive README.md at the repo root. The file is currently empty (1 line). Replace its entire content. Use plain Markdown — no emojis.

---

## README structure (write exactly these sections in order)

### 1. Header
Title: "Knowledge Lake (klake)" followed by a one-sentence description: "A reusable, domain-agnostic framework that turns public, private, and manually uploaded domain resources into AI-ready assets — with full lineage from raw source to indexed chunk."

Include a short feature bullet list: S3-compatible storage (MinIO/AWS), Dagster orchestration, Docling parsing, Qdrant hybrid search, LiteLLM gateway, per-domain prompt packs.

---

### 2. Prerequisites
List the following prerequisites with versions:

- Python 3.12+
- uv (https://docs.astral.sh/uv/getting-started/installation/)
- Docker and Docker Compose (Docker Desktop or docker-compose-plugin)
- AWS Bedrock API key — optional; required only for LLM enrichment (enrich/generate-dataset commands). The stack boots healthy without it; local sentence-transformers embeddings are used by default.

---

### 3. Local Setup

#### 3a. Clone and configure environment
```bash
git clone <repo-url>
cd healthlake

cp .env.example .env
```

Then explain that the user must edit `.env` and set the two required variables plus any optional ones. Provide the full annotated list:

Required:
- KLAKE_STORAGE__ACCESS_KEY_ID — MinIO root user (any non-empty string, e.g. "klakeadmin")
- KLAKE_STORAGE__SECRET_ACCESS_KEY — MinIO root password (min 8 characters)

Optional:
- POSTGRES_PASSWORD — Postgres password (default: klake)
- AWS_BEDROCK_API_KEY — Bedrock bearer token; required for klake enrich, klake generate-dataset, and klake export pretrain/finetune
- LITELLM_MASTER_KEY — LiteLLM proxy master key; leave empty for local dev
- KLAKE_STORAGE__BUCKET — S3 bucket name (default: klake-data)

#### 3b. Start the stack
```bash
docker compose up -d
```

Wait for all services to become healthy:
```bash
docker compose ps
```

Expected services and ports:
- postgres — localhost:5432
- minio — localhost:9000 (API), localhost:9001 (console UI)
- minio-init — one-shot bucket bootstrap (exits 0 when done)
- qdrant — localhost:6333 (HTTP), localhost:6334 (gRPC)
- litellm — localhost:4000
- dagster-webserver — localhost:3000
- dagster-daemon — background runner
- api — localhost:8000
- searxng — localhost:8888

Verify the API is up:
```bash
curl http://localhost:8000/health
# Expected: {"status":"ok"}
```

#### 3c. Install Python dependencies
```bash
uv sync
```

#### 3d. Run database migrations
```bash
uv run alembic upgrade head
```

#### 3e. Verify the CLI
```bash
uv run klake version
```

---

### 4. Quick Demo (end-to-end smoke test)

Run the built-in demo that ingests the cached HIPAA Security Rule PDF fixture and searches it:

```bash
uv run klake demo
```

This runs: ingest fixture PDF → parse → chunk → embed → index into Qdrant → search "what are administrative safeguards" → print lineage of top hit.

For the live PDF download instead of the fixture:
```bash
uv run klake demo --live
```

---

### 5. Full Pipeline Walkthrough

Explain that the pipeline has these stages: register source → crawl or ingest-url → parse → clean → chunk → enrich → curate → index → search → export. Each stage produces a registry artifact with a stable ID and lineage pointer.

#### 5a. Register a source
```bash
uv run klake add-source https://www.hhs.gov/hipaa/for-professionals/security/index.html \
  --name "HIPAA Security" \
  --domain healthcare \
  --license public-domain
```
Prints source_id. Re-running the same URL is a no-op (returns existing source_id).

#### 5b. Crawl a website
```bash
uv run klake crawl https://www.hhs.gov/hipaa/for-professionals/security/index.html \
  --max-pages 50
```
Prints job_id, pages_complete, pages_failed. Resume-safe: re-running picks up where it left off.

#### 5c. Ingest a single URL (full pipeline shortcut: ingest → parse → chunk → index)
```bash
uv run klake ingest-url https://www.hhs.gov/sites/default/files/ocr/privacy/hipaa/understanding/srsummary.pdf \
  --source "HIPAA Security Rule Summary" \
  --mime application/pdf \
  --collection klake_chunks
```
Prints source_id, raw_artifact_id, parsed_artifact_id, chunk count.

#### 5d. Upload a local file
```bash
uv run klake upload /path/to/document.pdf \
  --source "My Document" \
  --license unknown
```

#### 5e. Parse a raw artifact
```bash
uv run klake parse <raw_artifact_id> <source_id> --mime application/pdf
```
Prints parsed artifact_id, quality_score, parser_used. Parser fallback chain: Docling → JSON/XML → Unstructured → Tika.

#### 5f. Clean a parsed artifact
```bash
uv run klake clean <parsed_artifact_id> <source_id>
```
Removes boilerplate, detects language, flags near-duplicates. Prints cleaned artifact_id, language, dedup_status.

#### 5g. Chunk a parsed artifact
```bash
uv run klake chunk <parsed_artifact_id> <source_id>
```
Produces token-aware chunk artifacts. Prints chunk_count and first chunk_id. Note: for production use, the Dagster pipeline passes ParsedDoc in-memory for section-aware chunking; this CLI command is for manual testing.

#### 5h. Enrich a cleaned artifact (requires AWS_BEDROCK_API_KEY)
```bash
uv run klake enrich <cleaned_artifact_id> <source_id>
```
Calls LiteLLM (strong_model alias → Bedrock) to extract summary, document_type, organization, jurisdiction, keywords, entities, quality_score. Prints status, artifact_id, quality_score, cached.

#### 5i. Curate a cleaned artifact
```bash
uv run klake curate <cleaned_artifact_id> <source_id>
```
Runs DataTrove-style quality filters (length, repetition, language, gopher heuristics). Prints composite quality_score.

#### 5j. Corpus-wide deduplication
```bash
uv run klake dedupe
```
Builds a single MinHash LSH index over all cleaned artifacts and marks near-duplicates. Run this after bulk curation.

#### 5k. Search
```bash
uv run klake search "what are administrative safeguards" \
  --collection klake_chunks \
  --top-k 5 \
  --domain healthcare \
  --min-quality-score 0.5
```
Embeds the query and returns the top-K matching chunks with score, section, page, chunk_id, and text snippet. All filter flags are optional.

#### 5l. View lineage
```bash
uv run klake lineage <artifact_id>
uv run klake lineage <artifact_id> --json
```
Walks parent_artifact_id back to the source document. Prints a tree showing all six lineage fields (id, type, content_hash, timestamp, pipeline_version, storage_uri).

#### 5m. Export
```bash
# Export curated corpus as Parquet (RAG-ready)
uv run klake export rag-corpus

# Export as pretraining JSONL
uv run klake export pretrain

# Export a fine-tuning dataset by name
uv run klake export finetune --dataset-name my_rag_eval_v1
```
Writes gold-zone files to S3 (MinIO in dev). Prints dataset_id, storage_uri, row_count.

#### 5n. Reindex Qdrant (zero-downtime alias swap)
```bash
uv run klake index --collection klake_chunks
```
Creates a new versioned physical collection, copies all points, then atomically repoints the alias. The prior collection is retained (never auto-dropped).

#### 5o. Source discovery via SearXNG
```bash
uv run klake discover "HIPAA security rule compliance" --limit 20
```
Queries SearXNG, SSRF-validates each URL, and registers new sources. Prints registered/existing/skipped counts.

---

### 6. Healthcare Domain Pack

The healthcare domain pack ships with 28 curated sources covering HL7/FHIR, CMS, HHS, ONC, CDC, FDA, NIH/NLM, and clinical guidelines.

#### 6a. Register all healthcare sources
```bash
uv run klake init --domain healthcare
```
Reads domains/healthcare/sources.yaml and bulk-registers all crawl-type sources. Upload-type sources (ICD-10-CM, FDA NDC, LOINC, NPPES NPI) require manual bulk file download — the command reports them but does not auto-register.

Expected output:
```
Registered 24 sources from healthcare pack.
4 sources require manual upload — see domains/healthcare/sources.yaml.
```

Re-running is safe (URL-first dedup; existing sources are skipped).

#### 6b. Enable the healthcare domain context for enrichment
```bash
export KLAKE_DOMAIN__DOMAIN_NAME=healthcare
```
When set, klake enrich loads the healthcare-specific prompt from domains/healthcare/prompts/enrich.j2, giving the LLM domain context (FHIR, HIPAA, clinical terminology) for better metadata extraction. When unset, enrichment uses the generic prompt.

#### 6c. Crawl a healthcare source
```bash
uv run klake crawl https://www.hhs.gov/hipaa/for-professionals/security/laws-regulations/index.html \
  --max-pages 100
```

#### 6d. Ingest a specific HIPAA PDF end-to-end
```bash
uv run klake ingest-url \
  https://www.hhs.gov/sites/default/files/ocr/privacy/hipaa/understanding/srsummary.pdf \
  --source "HIPAA Security Rule Summary" \
  --mime application/pdf \
  --collection klake_chunks
```

#### 6e. Enrich with healthcare domain context (requires AWS_BEDROCK_API_KEY)
```bash
export KLAKE_DOMAIN__DOMAIN_NAME=healthcare
uv run klake enrich <cleaned_artifact_id> <source_id>
```

#### 6f. Search the healthcare corpus
```bash
uv run klake search "what are administrative safeguards for HIPAA" \
  --collection klake_chunks \
  --domain healthcare \
  --top-k 10
```

#### 6g. Generate a QA dataset from a healthcare chunk (requires AWS_BEDROCK_API_KEY)
```bash
uv run klake generate-dataset qa <chunk_artifact_id> \
  --dataset-name healthcare_rag_eval_v1
```

#### 6h. Export the healthcare corpus
```bash
uv run klake export rag-corpus
```

---

### 7. Adding a New Domain Pack

A domain pack is a directory under domains/<domain-name>/ with four components.

#### 7a. Create the directory structure
```bash
mkdir -p domains/mydomainname/prompts
mkdir -p domains/mydomainname/validators
```

#### 7b. Write domain.yaml
```yaml
name: mydomainname
version: "1.0.0"
description: "My domain — brief description of what this pack covers"
```

#### 7c. Write sources.yaml
Each entry defines one source. The ingest_type is either "crawl" (auto-crawled) or "upload" (manual bulk file):

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

#### 7d. Write the enrichment prompt (required)
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

#### 7e. Write a QA generation prompt (optional, for generate-dataset qa)
```bash
cat > domains/mydomainname/prompts/qa_generation.j2 << 'EOF'
You are an expert in {{ domain_name }}.
Generate a question-answer pair from the following passage.
The question should be answerable from the passage alone.
EOF
```

#### 7f. Create an empty validators module
```bash
touch domains/mydomainname/validators/__init__.py
cat > domains/mydomainname/validators/validate.py << 'EOF'
"""Optional domain-specific validation logic."""
EOF
```

#### 7g. Register and use the new domain pack
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

---

### 8. Dagster UI

The Dagster webserver is available at http://localhost:3000. It shows all registered assets (ingest, parse, clean, chunk, enrich, curate, generate_dataset, index), run history, and retry state for the healthcare_e2e_job.

To trigger the full pipeline for a source asset via Dagster, use the Launchpad in the UI or the Dagster CLI:
```bash
uv run dagster job execute -j healthcare_e2e_job \
  -c '{"ops": {"ingest_asset": {"config": {"source_id": "<source_id>"}}}}'
```

---

### 9. CLI Reference

Provide a table covering all commands with a one-line description:

| Command | Description |
|---------|-------------|
| klake version | Print the package version |
| klake add-source URL | Register a source URL (URL-first dedup) |
| klake upload FILE | Upload a local file into the raw zone |
| klake discover QUERY | Discover and register sources via SearXNG meta-search |
| klake crawl URL | Crawl a website into the lake (resume-safe) |
| klake ingest-url URL | Full pipeline shortcut: download → parse → chunk → index |
| klake parse RAW_ID SOURCE_ID | Parse a raw artifact into parsed_document |
| klake clean PARSED_ID SOURCE_ID | Clean boilerplate, detect language, near-dup flag |
| klake chunk PARSED_ID SOURCE_ID | Chunk into token-aware artifacts |
| klake enrich CLEANED_ID SOURCE_ID | LLM enrichment via LiteLLM (requires AWS_BEDROCK_API_KEY) |
| klake curate CLEANED_ID SOURCE_ID | DataTrove quality filters and composite score |
| klake dedupe | Corpus-wide MinHash deduplication |
| klake generate-dataset KIND ARTIFACT_ID | Generate QA or instruction dataset examples |
| klake search QUERY | Vector search with optional filters |
| klake lineage ARTIFACT_ID | Print full lineage ancestry tree |
| klake export KIND | Export corpus to gold zone (rag-corpus / pretrain / finetune) |
| klake index | Zero-downtime Qdrant alias reindex |
| klake reindex | Alias for klake index (power-user name) |
| klake init --domain NAME | Bulk-register all sources for a domain pack |
| klake demo | Run end-to-end smoke test using the HIPAA fixture |

---

### 10. Environment Variable Reference

Provide a table of all environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| KLAKE_STORAGE__ACCESS_KEY_ID | Yes | none | MinIO root user / AWS access key |
| KLAKE_STORAGE__SECRET_ACCESS_KEY | Yes | none | MinIO root password / AWS secret key |
| KLAKE_STORAGE__ENDPOINT_URL | No | http://minio:9000 (in container) | S3 endpoint; omit for AWS S3 |
| KLAKE_STORAGE__BUCKET | No | klake-data | S3 bucket name |
| KLAKE_DATABASE_URL | No | postgresql+psycopg://klake:klake@localhost:5432/klake | Registry database |
| KLAKE_QDRANT_URL | No | http://localhost:6333 | Qdrant HTTP endpoint |
| KLAKE_LITELLM_URL | No | http://localhost:4000 | LiteLLM proxy base URL |
| KLAKE_EMBEDDER | No | local | Embedder plugin: local (sentence-transformers) or litellm |
| KLAKE_PARSER | No | docling | Parser plugin: docling |
| KLAKE_VECTORSTORE | No | qdrant | Vector store plugin: qdrant |
| KLAKE_DOMAIN__DOMAIN_NAME | No | none | Active domain pack name (e.g. healthcare) |
| KLAKE_DOMAIN__DOMAINS_ROOT | No | domains | Path to the domains/ directory |
| AWS_BEDROCK_API_KEY | No | none | Bedrock bearer token for LLM enrichment |
| LITELLM_MASTER_KEY | No | none | LiteLLM proxy master key |
| POSTGRES_PASSWORD | No | klake | Postgres password |

Note: When running klake CLI commands locally (outside Docker), set KLAKE_STORAGE__ENDPOINT_URL=http://localhost:9000 to reach MinIO, and KLAKE_DATABASE_URL pointing to localhost:5432.

---

## Implementation notes for the executor

- Write the full README.md content using the Write tool in a single call. Do not truncate.
- Use fenced code blocks with the bash language tag for all shell commands.
- Keep the tone direct and reference-oriented — no marketing language.
- The .env.example file contains the canonical list of variables; reference it in the setup section.
- The docker-compose.yml comment block already documents the MinIO credentials requirement; echo it in the README setup section so readers understand why those two variables have no defaults.
  </action>
  <verify>
    <automated>test -f README.md && wc -l README.md | awk '{if ($1 > 100) print "PASS: README has " $1 " lines"; else {print "FAIL: README too short (" $1 " lines)"; exit 1}}'</automated>
  </verify>
  <done>README.md exists at repo root with all ten sections present: header, prerequisites, local setup, quick demo, full pipeline walkthrough (all 15 sub-commands), healthcare domain pack, adding a new domain pack, Dagster UI, CLI reference table, and environment variable table. All shell commands are copy-paste ready with no placeholders that require inference.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Documentation only | No code changes; no trust boundary crossings |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation |
|-----------|----------|-----------|----------|-------------|------------|
| T-doc-01 | Information Disclosure | README env var table | low | accept | README documents that KLAKE_STORAGE__ACCESS_KEY_ID has no default — this is intentional (WR-09). No actual credentials appear in documentation. |
</threat_model>

<verification>
After writing README.md:
- Open README.md and confirm all ten sections are present
- Check that port numbers match docker-compose.yml (5432, 9000, 9001, 6333, 6334, 4000, 3000, 8000, 8888)
- Check that CLI command names match src/knowledge_lake/cli/app.py (add-source, upload, discover, crawl, ingest-url, parse, clean, chunk, enrich, curate, dedupe, generate-dataset, search, lineage, export, index, reindex, init, demo, version)
- Confirm the healthcare domain pack section references 28 sources and 4 upload-type sources
</verification>

<success_criteria>
- README.md exists at the repo root with more than 100 lines
- All four constraint sections are present: prerequisites/setup, full pipeline, healthcare domain pack, adding a new domain pack
- Every shell command in the README uses the exact CLI command names from app.py
- The env var table matches the variables found in docker-compose.yml and settings.py
</success_criteria>

<output>
Create `.planning/quick/260707-hoh-add-documentation-for-knowledge-lake-kla/260707-hoh-SUMMARY.md` when done
</output>
