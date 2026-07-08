# Domain Pitfalls

**Domain:** Knowledge Lake / Data Pipeline Framework
**Project:** HealthLake
**Researched:** 2026-07-02

## Critical Pitfalls

Mistakes that cause rewrites or major issues.

### Pitfall 1: Over-engineering Orchestration Before Proving Pipeline End-to-End

**What goes wrong:** Teams build elaborate Dagster asset graphs, custom IO managers, partition strategies, and resource abstractions before verifying that a single document can flow from crawl to vector store. Weeks pass refining orchestration scaffolding while the actual ingestion logic remains untested.

**Why it happens:** Dagster's asset model is seductive — it encourages thinking in terms of the full dependency graph from day one. The "Dagster from day 1" constraint amplifies this by making it feel like the orchestration layer must be production-grade before any pipeline runs.

**Consequences:** When you finally test real documents, you discover the parsers fail on your actual inputs, the chunking strategy is wrong for your domain, or the enrichment step costs 10x what you budgeted. All that orchestration work must be reworked around different pipeline shapes.

**Prevention:**
- Build a "spike pipeline" first: one Python script that crawls one URL, parses one PDF, chunks it, embeds it, and queries it. Prove the data path works end-to-end.
- Only THEN wrap in Dagster assets. Let the asset graph emerge from working code, not from design documents.
- Use `deps` (not IO managers) initially. IO managers are premature until storage patterns stabilize.

**Detection:** If your Dagster job definitions outnumber your working integration tests, you are over-engineering.

**Phase relevance:** Phase 1 (Foundation). Must resist the temptation to build the "beautiful graph" before proving data flows.

---

### Pitfall 2: Parser Quality Blindness (Docling/Unstructured Failure Modes)

**What goes wrong:** The framework treats document parsing as a solved problem — configure Docling, point it at PDFs, get clean text. In reality, healthcare PDFs contain complex tables (merged cells, multi-row headers), multi-column clinical layouts, scanned formularies, and regulatory documents with nested heading structures. Parsers silently produce garbage.

**Why it happens:** Docling demos work well on clean academic PDFs. But production healthcare documents (CMS manuals, hospital formularies, insurance policy PDFs, clinical guidelines) have pathological formatting. Known Docling issues include:
- `std::bad_alloc` memory crashes on large PDFs (100+ pages)
- TableFormer V1/V2 mishandles merged rows and columns regardless of `cell_matching` setting
- Headers/headings incorrectly classified as "page furniture" and silently removed
- OCR fails without explicit language configuration
- Metadata extraction (title, authors, references) is still incomplete

**Consequences:** Garbage parsing propagates through the entire pipeline: bad chunks, wrong embeddings, hallucinated RAG answers, unusable training datasets. The worst part is it fails silently — you only discover the quality issue when downstream consumers report bad results.

**Prevention:**
- Build a parser quality gate: sample N documents from each source, manually inspect parsed output, compute quality scores before bulk processing.
- Implement parser fallback chains: Docling -> Unstructured -> Tika, with quality comparison on each document.
- Store raw bytes in bronze zone ALWAYS. Never rely solely on parsed output.
- Create a "parser torture test" corpus: find the worst PDFs in your domain (scanned, multi-column, merged-cell tables, 500+ pages) and run them through every parser candidate during Phase 1.
- Set memory limits on parser processes and handle OOM gracefully with fallback.

**Detection:** Parse 50 random documents. Manually read 10 of the outputs. If more than 2 have structural errors (broken tables, lost headings, garbled text), your parser config is not ready for production.

**Phase relevance:** Phase 2 (Ingestion Pipeline). Must be addressed before any bulk processing begins.

---

### Pitfall 3: Chunking Strategy Destroys Domain Context

**What goes wrong:** Fixed-size chunking (e.g., 512 tokens with 50-token overlap) is applied uniformly across all document types. This breaks tables mid-row, splits clinical guidelines from their applicability criteria, separates drug names from their dosage information, and produces chunks that are meaningless without surrounding context.

**Why it happens:** Fixed-size chunking is the default in every tutorial and framework. It is simple to implement and produces consistent vector dimensions. Teams defer "smart chunking" to later and never get back to it.

**Consequences:**
- RAG retrieves chunks that answer the wrong question because context was severed
- Embedding quality degrades because chunks are not semantically coherent
- Training datasets contain incomplete examples
- Tables become rows of nonsense when split across chunks

**Prevention:**
- Implement structure-aware chunking from the start: parse documents into structural elements (headings, paragraphs, tables, lists) THEN apply size constraints within those boundaries.
- Tables are ATOMIC: never split a table across chunks. If a table exceeds token limit, serialize it as a separate artifact with metadata linking back to the surrounding context.
- Use the "human readability test": if a chunk does not make sense to a human reading it in isolation, it will not make sense to an embedding model.
- Attach parent section heading to every chunk as prefix metadata (e.g., "Section: Drug Interactions > Warfarin" prepended to a chunk about specific drug interactions).
- Healthcare-specific: clinical guidelines, formulary entries, and procedure codes must be chunked as complete semantic units, not arbitrary token windows.

**Detection:** Retrieve 20 random chunks from your vector store. Read them without context. If more than 5 are incomprehensible in isolation, your chunking strategy is broken.

**Phase relevance:** Phase 2-3 (Chunking and Embedding). This is the single highest-leverage quality improvement in the entire pipeline.

---

### Pitfall 4: LLM Enrichment Cost Explosion

**What goes wrong:** The pipeline calls an LLM for metadata extraction, summarization, or quality scoring on every document/chunk. With thousands of documents, each requiring multiple LLM calls, costs spiral from dollars to hundreds or thousands of dollars before anyone notices. A single bulk re-enrichment run after a prompt change can cost more than the entire monthly infrastructure budget.

**Why it happens:** LLM calls feel cheap in development (one document = pennies). At scale, the math is brutal: 10,000 documents x 5 enrichment calls each x $0.01/call = $500 per pipeline run. Healthcare corpora with 100K+ pages make this worse.

**Consequences:**
- Uncontrolled spend that exceeds budget
- Pipeline becomes too expensive to re-run after improvements
- Teams avoid re-processing, leading to stale enrichments
- Rate limiting from providers causes pipeline failures and partial results

**Prevention:**
- Implement hard budget caps per pipeline run using LiteLLM's `max_budget` and `budget_duration` before writing ANY enrichment code.
- Use the "deterministic first" constraint religiously: regex, heuristics, and rule-based extraction BEFORE any LLM call. Only use LLM for what cannot be done deterministically.
- Tag every LLM call with pipeline name, document ID, and enrichment type for cost attribution.
- Implement enrichment caching: hash(prompt_version + input_text) -> cached result. Never re-enrich identical content with the same prompt.
- Set RPM/TPM limits explicitly in LiteLLM router config (do NOT leave unset — router randomly picks deployments without limits).
- Use `cheap_model` alias for bulk enrichment, `strong_model` only for quality-critical tasks.
- Log estimated cost BEFORE starting a bulk enrichment run. Require manual approval above a threshold.

**Detection:** If you cannot answer "how much did the last pipeline run cost?" within 5 seconds, you lack cost observability. If the answer is "I don't know," stop and add tracking immediately.

**Phase relevance:** Phase 3 (Enrichment). Must implement budget guardrails BEFORE the first enrichment pipeline runs at scale.

---

### Pitfall 5: Vector Store Collection Sprawl and Embedding Model Lock-in

**What goes wrong:** Teams create multiple Qdrant collections as needs evolve — one per embedding model experiment, one per document type, one for "v2" after changing chunking. Collections accumulate, queries hit stale data, and switching embedding models requires rebuilding everything because vector dimensions are immutable after collection creation.

**Why it happens:** Qdrant's collection configuration (vector size, distance metric) is immutable after creation. When you change embedding models (different dimensions or distance metric requirements), you must create new collections. Without a naming/versioning strategy, you end up with `documents_v1`, `documents_v2`, `documents_test_384d`, etc.

**Consequences:**
- Queries return results from stale collections with outdated embeddings
- Dimension mismatches cause hard errors when embedding model changes
- Wrong distance metric (e.g., Euclidean on cosine-optimized embeddings) silently degrades quality without errors
- Storage grows unbounded with orphaned collections
- No clear "source of truth" collection for production queries

**Prevention:**
- Use collection aliasing: production always queries via alias (e.g., `documents_current`), not direct collection name. Rebuild into new collection, atomically swap alias.
- Encode embedding model info in collection metadata: model name, version, dimensions, distance metric.
- Use deterministic point IDs (content_hash based) so upserts naturally deduplicate.
- Create a collection registry in PostgreSQL that tracks: collection name, embedding model, creation date, document count, status (active/deprecated/pending-deletion).
- Automate stale collection cleanup: if a collection is not aliased and older than N days, schedule for deletion.
- Choose distance metric to match embedding model training (almost always Cosine for sentence-transformers).

**Detection:** Run `GET /collections` on your Qdrant instance. If there are more than 3 collections and you cannot explain what each one is for, you have sprawl.

**Phase relevance:** Phase 3 (Vector Search). Must establish collection naming and aliasing conventions before first production collection.

---

### Pitfall 6: Immutable Raw Zone Violations and Missing Content Hashing

**What goes wrong:** The "immutable raw zone" principle is violated in subtle ways: documents are re-crawled and overwritten (losing the original version), parsers write intermediate results into the raw bucket, or file paths change between runs making lineage impossible to trace backward.

**Why it happens:** S3/MinIO makes it easy to overwrite objects. Without explicit versioning or content-addressed storage, a `PUT` silently replaces the previous version. Teams also confuse "raw zone" (original bytes as received) with "landing zone" (whatever the crawler outputs).

**Consequences:**
- Lineage breaks: you cannot reproduce how a derived artifact was created because the source changed
- Deduplication fails: same content re-ingested gets new IDs because there is no content hash to detect duplicates
- Audit trail gaps: cannot prove what was processed or when
- Re-processing produces different results because inputs changed underneath

**Prevention:**
- Content-addressed storage in raw zone: object key includes content hash (e.g., `raw/{source_id}/{sha256_first16}.{ext}`). Same content = same path = natural dedup.
- NEVER overwrite in raw zone. New version = new object with new content hash. Keep both.
- Compute content hash (SHA-256) on ingest, store in PostgreSQL registry alongside object path, source URL, crawl timestamp.
- MinIO bucket policy: disable `DeleteObject` on raw zone bucket for non-admin roles.
- Every downstream artifact references parent content hash, not just object path.

**Detection:** Crawl the same URL twice, one week apart. If the raw zone contains only one copy, your immutability is broken. If it contains two copies with no content hash comparison, your dedup is broken.

**Phase relevance:** Phase 1 (Storage Layer). Must be correct from the first write. Retrofitting content-addressed storage is a data migration nightmare.

---

## Moderate Pitfalls

### Pitfall 7: Dagster IO Manager Misuse for Data Lake Workloads

**What goes wrong:** Teams adopt Dagster IO managers to handle reading/writing from S3/MinIO because it feels like the "Dagster way." But IO managers assume data fits in memory, use implicit naming conventions tied to asset keys, and hide storage logic behind abstractions that do not match data lake patterns (large files, streaming, append-only zones).

**Prevention:**
- Use `deps` parameter for asset dependencies instead of IO managers for the raw/bronze/silver pipeline. IO managers are for in-memory DataFrames, not multi-GB object storage blobs.
- Handle S3 I/O explicitly in asset functions using a shared MinIO resource (connection pool, bucket references).
- Reserve IO managers only for small metadata tables or export artifacts where the convenience outweighs the opacity.

**Detection:** If your IO manager code has workarounds for large files, streaming uploads, or custom path logic, it is the wrong abstraction.

**Phase relevance:** Phase 1 (Dagster Setup). Decide early: explicit I/O vs IO managers.

---

### Pitfall 8: PostgreSQL Registry Over-Normalization

**What goes wrong:** The metadata registry schema is designed with heavy normalization: separate tables for sources, documents, versions, artifacts, lineage edges, quality scores, tags, processing status, etc., all joined through foreign keys. Queries require 5-table JOINs for simple "show me this document's status" lookups.

**Prevention:**
- Start with 3-4 core tables: `sources`, `documents`, `artifacts`, `pipeline_runs`. Use JSONB columns for flexible metadata rather than creating new tables for every attribute.
- Add indexes on: content_hash, source_id, status, created_at. Skip indexes on columns you do not filter on.
- Denormalize status and latest quality score into the documents table. Normalize only when you have proven write-contention issues.
- Use PostgreSQL's `GENERATED ALWAYS AS` for computed columns (e.g., `document_age`) rather than materialized views initially.

**Detection:** If a simple status dashboard query requires more than 2 JOINs, your schema is over-normalized for the current scale.

**Phase relevance:** Phase 1 (Registry Design). Schema mistakes compound over time; get the core right early.

---

### Pitfall 9: Crawling Without Rate Limiting, Backoff, and Legal Compliance

**What goes wrong:** Crawlers are configured for maximum throughput. They hit healthcare websites (CMS.gov, FDA.gov, medical journals) at high concurrency, get IP-banned, violate robots.txt directives, or trigger legal notices. Some healthcare sources have strict ToS prohibiting automated access.

**Prevention:**
- Default to conservative rate limits: 1 request/second per domain, with exponential backoff on 429/503 responses.
- Parse and obey robots.txt before first request to any domain. Store crawl-delay directives in source registry.
- Track source licensing in the registry: `license_type` (public domain, Creative Commons, copyrighted, unknown). Flag "unknown" for manual review.
- Healthcare-specific: CMS.gov, FDA.gov are public domain. Medical journals (NEJM, Lancet, JAMA) are copyrighted — only crawl abstracts or open-access content.
- Implement `User-Agent` header identifying your crawler with contact info. Stealth crawling invites legal trouble.
- Log every crawl request with timestamp, response code, and bytes downloaded for audit trail.

**Detection:** Check your source registry. If any source lacks a `robots_txt_checked` flag or `license_type`, your legal compliance is incomplete.

**Phase relevance:** Phase 2 (Crawling). Must be correct before scaling beyond test sources.

---

### Pitfall 10: Schema Evolution Without Migration Strategy

**What goes wrong:** The PostgreSQL registry schema evolves as new features are added (new columns, changed types, additional tables). Without a migration tool, changes are applied manually or via ad-hoc ALTER TABLE statements. Old data is not backfilled. Code assumes columns exist that were added after initial data was inserted.

**Prevention:**
- Use Alembic (SQLAlchemy migrations) from day 1. Every schema change is a versioned migration file.
- Make all new columns NULLABLE or provide DEFAULT values. Never add NOT NULL columns without a backfill migration.
- Test migrations on a copy of production data before applying. PostgreSQL ALTER TABLE on large tables can lock for extended periods.
- Store schema version in a `_meta` table. Pipeline startup checks schema version matches code expectation.
- Plan for JSONB column evolution: document the expected keys, but do not enforce via CHECK constraints until schema stabilizes.

**Detection:** If you have ever run a raw `ALTER TABLE` in production without a corresponding migration file, your schema management is broken.

**Phase relevance:** Phase 1 (Foundation). Must establish migration discipline from first table creation.

---

### Pitfall 11: MinIO/S3 Multipart Upload and Large File Handling

**What goes wrong:** Large files (100MB+ PDFs, bulk exports) fail silently during upload because multipart upload configuration is wrong, network interruptions leave incomplete uploads consuming storage, or presigned URLs expire mid-transfer for large uploads.

**Prevention:**
- Set `part_size` in MinIO client to at least 64MB for files over 500MB. Default 5MB creates too many parts and is slow.
- Implement lifecycle policies to abort incomplete multipart uploads after 24 hours (they consume storage invisibly).
- For presigned upload URLs: calculate expected upload duration and set expiry accordingly (minimum 1 hour for large files, not the default 7 days which is a security risk).
- Wrap all S3 operations in retry logic with exponential backoff. Network blips are common on DigitalOcean.
- Use `fput_object` for file-based uploads (handles multipart automatically) rather than manual `put_object` with stream data for large files.

**Detection:** Check MinIO console for incomplete multipart uploads. If any exist older than 24 hours, your lifecycle policies are missing.

**Phase relevance:** Phase 1 (Storage). Configure lifecycle policies when creating buckets, not after discovering storage leaks.

---

### Pitfall 12: Prompt Instability in Batch Enrichment

**What goes wrong:** LLM enrichment prompts are tweaked iteratively during development. Each change produces different outputs for the same input. Documents enriched with prompt v1 have different metadata structure/quality than those enriched with prompt v2. The corpus becomes inconsistent.

**Prevention:**
- Version every prompt. Store prompt text with SHA-256 hash. Record prompt version in every enrichment artifact's lineage.
- When prompt changes, re-enrich ALL affected documents (or accept and document the inconsistency boundary).
- Use structured output (JSON mode) with explicit schema validation. Reject LLM outputs that don't conform to expected schema.
- Test prompt changes on a fixed evaluation set of 50 documents before bulk application. Compare outputs for regressions.
- Store enrichment results with prompt_version_hash so you can query "all documents enriched with prompt v3."

**Detection:** Query your artifact registry for documents enriched in the last month. If `prompt_version` field is missing or has more than 2 distinct values without an intentional migration, your prompt management is ad-hoc.

**Phase relevance:** Phase 3 (Enrichment). Must version prompts from first enrichment call.

---

### Pitfall 13: Dataset Generation Garbage-In-Garbage-Out

**What goes wrong:** Fine-tuning datasets and RAG evaluation sets are generated from the knowledge lake without quality filtering. If upstream parsing was poor, chunks were bad, or enrichment was inconsistent, the generated datasets inherit and amplify those quality issues. Models trained on garbage data perform poorly, but the cause is non-obvious — teams blame the model or training hyperparameters instead of the data.

**Prevention:**
- Implement quality scoring at document and chunk level BEFORE dataset generation. Only chunks above quality threshold enter dataset generation pipeline.
- Build a "gold standard" evaluation set of 100 manually verified examples. Use this to validate generated datasets against known-good answers.
- Track data lineage into datasets: every training example must trace back to specific chunks, documents, and sources. When a source is flagged as low-quality, automatically flag all derived dataset entries.
- Implement automated quality checks: exact-match dedup within datasets, answer extractability verification, question diversity scoring.
- Healthcare-specific: clinical accuracy must be verified by domain experts for at least a sample of generated QA pairs before using in fine-tuning.

**Detection:** Sample 20 random entries from a generated dataset. If more than 3 contain obviously wrong, incomplete, or nonsensical content, your upstream quality filtering is insufficient.

**Phase relevance:** Phase 4 (Dataset Generation). Quality must be validated before any model training.

---

## Minor Pitfalls

### Pitfall 14: Dagster Resource Configuration Drift Between Environments

**What goes wrong:** Resources (MinIO client, PostgreSQL connection, LiteLLM gateway URL) are configured differently in dev vs. production, but the differences are not captured in Dagster's resource system. Hard-coded URLs slip into asset code.

**Prevention:** Define all external connections as Dagster resources with environment-specific configuration. Use `EnvVar` for secrets. Test that assets work with a mock resource before deploying.

**Phase relevance:** Phase 1 (Foundation). Establish resource pattern from first external connection.

---

### Pitfall 15: Qdrant Payload Index Neglect

**What goes wrong:** Queries with payload filters (e.g., "find chunks from source X with quality > 0.8") perform full scans because payload indexes were never created. Performance degrades as collection grows.

**Prevention:** Create payload indexes for any field you filter on: `source_id`, `document_id`, `quality_score`, `created_at`, `document_type`. Do this at collection creation time, not after performance problems appear.

**Phase relevance:** Phase 3 (Vector Search). Configure indexes when creating collections.

---

### Pitfall 16: LiteLLM Cooldown Cascade Under Load

**What goes wrong:** Under bursty batch enrichment load, a provider returns a few 429 errors. LiteLLM's default cooldown (3 failures = 5 second cooldown) cascades: deployments are rapidly pulled offline, remaining deployments get overloaded, they fail too, and the entire router enters a death spiral.

**Prevention:** Increase `allowed_fails` to 10+ for batch workloads. Set `cooldown_time` to 30-60 seconds (not 5). Use `simple-shuffle` routing (not usage-based, which adds Redis latency). Pre-calculate batch concurrency to stay under provider rate limits rather than relying on reactive cooldown.

**Phase relevance:** Phase 3 (Enrichment). Configure before first batch enrichment run.

---

### Pitfall 17: Lineage Over-Tracking vs Under-Tracking

**What goes wrong:** Either lineage captures every intermediate transformation (creating a lineage graph too complex to query or understand), or lineage only tracks source -> final output (making it impossible to debug which intermediate step introduced an error).

**Prevention:** Track lineage at zone boundaries (raw -> bronze -> silver -> gold) and at LLM enrichment steps. Skip lineage for pure mechanical transforms (encoding changes, format normalization). Every lineage edge should answer: "if this input changes, what outputs are affected?"

**Phase relevance:** Phase 1-2 (Registry and Pipeline). Define lineage granularity in schema design.

---

### Pitfall 18: SearXNG Source Discovery Without Deduplication

**What goes wrong:** SearXNG discovers URLs that point to the same content (mirrors, cached versions, different URL parameters). Without URL normalization and content-hash deduplication, the pipeline processes the same document multiple times, wasting compute and creating duplicate entries.

**Prevention:** Normalize URLs before storing (strip tracking params, canonicalize). After download, compute content hash. If hash exists in registry, skip processing and link to existing document.

**Phase relevance:** Phase 2 (Discovery and Crawling). Implement dedup at the earliest point in the pipeline.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Phase 1: Foundation | Over-engineering Dagster graph before proving data flow | Build spike pipeline first, wrap in Dagster second |
| Phase 1: Storage | Mutable raw zone, missing content hashing | Content-addressed storage from day 1, disable deletes on raw bucket |
| Phase 1: Registry | Over-normalized schema, no migration tool | Start with 3-4 tables + JSONB, use Alembic from first migration |
| Phase 2: Parsing | Silent parser failures on real healthcare PDFs | Parser torture test corpus, quality gates, fallback chains |
| Phase 2: Chunking | Fixed-size splitting destroys tables and context | Structure-aware chunking, atomic tables, parent heading context |
| Phase 2: Crawling | Rate limit violations, legal issues | Conservative defaults, robots.txt compliance, license tracking |
| Phase 3: Enrichment | LLM cost explosion, prompt instability | Budget caps, deterministic-first, prompt versioning, enrichment caching |
| Phase 3: Vector Search | Collection sprawl, wrong distance metric, no payload indexes | Aliasing, model-matched metrics, indexes at creation time |
| Phase 3: LiteLLM | Cooldown cascade, silent misconfig | Higher allowed_fails, explicit RPM/TPM, simple-shuffle routing |
| Phase 4: Datasets | Quality propagation from bad upstream data | Quality scoring gates, gold standard eval set, lineage tracing |

## Sources

- Dagster official documentation: assets, IO managers, resources, external pipelines (docs.dagster.io) [MEDIUM confidence - official docs via WebFetch]
- Docling GitHub issues: #3671, #3698, #3693, #3699, #3685 (github.com/docling-project/docling) [MEDIUM confidence - verified community reports]
- Qdrant documentation: collections, optimization (qdrant.tech/documentation) [MEDIUM confidence - official docs via WebFetch]
- LiteLLM documentation: routing, cost tracking (docs.litellm.ai) [MEDIUM confidence - official docs via WebFetch]
- Pinecone chunking strategies guide (pinecone.io/learn/chunking-strategies) [MEDIUM confidence - cross-referenced with domain knowledge]
- MinIO Python SDK repository and documentation (github.com/minio/minio-py) [MEDIUM confidence - official repo via WebFetch]
