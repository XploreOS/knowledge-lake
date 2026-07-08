---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: — Agent-Ready Lake
current_phase: 07
current_phase_name: Metadata Foundation
status: verifying
stopped_at: Completed 07-04-PLAN.md
last_updated: "2026-07-08T07:56:22.220Z"
last_activity: 2026-07-08
last_activity_desc: Phase 07 execution started
progress:
  total_phases: 6
  completed_phases: 1
  total_plans: 4
  completed_plans: 4
  percent: 17
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-08)

**Core value:** Every domain resource ingested must be traceable from raw source through every transformation to its final AI-ready output — and the framework must remain tool-agnostic so any processor can be swapped without breaking lineage.
**Current focus:** Phase 07 — Metadata Foundation

## Current Position

Phase: 07 (Metadata Foundation) — EXECUTING
Plan: 4 of 4
Status: Phase complete — ready for verification
Last activity: 2026-07-08 — Phase 07 execution started

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**

- Total plans completed: 25 (v1.0)
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 6 | - | - |
| 02 | 6 | - | - |
| 03 | 3 | - | - |
| 04 | 3 | - | - |
| 5 | 3 | - | - |
| 6 | 4 | - | - |

**Recent Trend:**

- Last 5 plans: -
- Trend: -

*Updated after each plan completion*
| Phase 01 P01 | 59 | 3 tasks | 23 files |
| Phase 01 P04 | 35m | - tasks | - files |
| Phase 01 P02 | 45 | 3 tasks | 17 files |
| Phase 01 P03 | 12m | 2 tasks | 5 files |
| Phase 01 P05 | 109m | 3 tasks | 16 files |
| Phase 02 P04 | 6m | 3 tasks | 6 files |
| Phase 02 P05 | 25m | 3 tasks | 6 files |
| Phase 03 P02 | 8m | 2 tasks | 4 files |
| Phase 04 P01 | 8min | 2 tasks | 7 files |
| Phase 04 P02 | 8min+checkpoint | 4 tasks | 11 files |
| Phase 04 P03 | 35min | 3 tasks | 12 files |
| Phase 05 P01 | 10m | 3 tasks | 14 files |
| Phase 05 P02 | 8min | - tasks | - files |
| Phase 06 P01 | 6m | 3 tasks | 16 files |
| Phase 06 P02 | 4min | - tasks | - files |
| Phase 06 P03 | 4m | 3 tasks | 6 files |
| Phase 06 P04 | 7m | 4 tasks | 9 files |
| Phase 07 P01 | 2min | 1 tasks | 1 files |
| Phase 07 P02 | 4min | 2 tasks | 4 files |
| Phase 07 P03 | 3min | 2 tasks | 3 files |
| Phase 07 P04 | 3m | - tasks | - files |

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260707-ieb | create project documentation with full details on project overview, architecture, etc., in docs/ folder | 2026-07-07 | cad4e0b | [260707-ieb-create-project-documentation-with-full-d](.planning/quick/260707-ieb-create-project-documentation-with-full-d/) |
| 260707-hoh | add documentation for knowledge-lake (klake) local setup, and usage for multiple domains with full steps and commands | 2026-07-07 | 14ad3da | [260707-hoh-add-documentation-for-knowledge-lake-kla](.planning/quick/260707-hoh-add-documentation-for-knowledge-lake-kla/) |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap v2.0]: Adopted the research's dependency-ordered 6-phase structure (Phases 7-12) over theme grouping — each split is a hard code-level dependency (payload→filters, sparse-infra→hybrid, schedule-columns→sensor, crawl-config/PDF→crawl-all, MCP last). 6 phases sits at the top of the "standard" granularity band, justified because every boundary is load-bearing.
- [Roadmap v2.0]: Phases 7/8/9 are mutually independent and parallelizable; Phase 10 gates on 7, Phase 11 gates on 8, Phase 12 gates on 8 plus all service functions it wraps.
- [Roadmap v2.0]: Two phases carry LIVE-DATA MIGRATIONS flagged for `--research-phase` — Phase 10 (Qdrant unnamed→named-vector recreate + re-embed) and Phase 11 (additive Source schedule/hash columns). Phase 12 (Agents) also flagged for a Streamable-HTTP/stdout-isolation spike.
- [Roadmap]: Vertical MVP structure — Phase 1 is a thin end-to-end spike (one doc: ingest → parse → chunk → embed → index → search) to avoid over-engineering Dagster before proving flow (research Pitfall #1)
- [Roadmap]: IFACE-01/02/03 (full CLI/API/Dagster surface) mapped to Phase 6 — interfaces grow incrementally each phase but are only verifiable as complete once all stages exist
- [Roadmap]: SearXNG discovery (INGEST-07) kept in Phase 2 with ingestion rather than deferred to the domain pack phase
- [Roadmap]: REQUIREMENTS.md coverage count corrected from 47 to 55 (actual v1 requirement count)
- [Phase ?]: plain config-keyed resolver (no pluggy) for Phase 1 plugin seam — pluggy deferred to Phase 3 fallback chains (FOUND-08)
- [Phase ?]: SentenceTransformerEmbedder all-MiniLM-L6-v2 384-dim as default local embedder (D-13 zero-creds spike)
- [Phase ?]: LiteLLMEmbedder uses embedding_model task alias only — no hardcoded provider IDs anywhere in plugins/
- [Phase ?]: Single boto3 client per StorageBackend; endpoint_url toggle selects MinIO vs AWS S3 (FOUND-03)
- [Phase ?]: No S3 If-None-Match:'*' conditional-write; immutability enforced by app+bucket-policy layer (FOUND-04, MinIO gap)
- [Phase ?]: Four-layer WORM: registry no-op + content-addressed key + head_object guard + versioning/object-lock/delete-deny policy (FOUND-04)
- [Phase ?]: Plain-function pipeline for Phase 1 (no Dagster)
- [Phase ?]: Qdrant point ID = bare UUID (strip chk_ prefix); full prefixed ID in payload as chunk_id
- [Phase ?]: ID prefix expansion: full ID length >= 40 chars (type_prefix + _ + 36-char UUID)
- [Phase ?]: Subprocess isolation for Scrapy: each crawl job spawns python -m scrapy_spider child; reactor dies with child (T-02-14)
- [Phase ?]: JSONL IPC for Scrapy: child writes base64-encoded HTML per page; parent parses after subprocess completes
- [Phase ?]: D-04 sitemap branch: has_sitemap=True short-circuits to scrapy; probe_site detects via robots.txt Sitemap: directive and /sitemap.xml HTTP 200
- [Phase ?]: playwright==1.49.0 pinned for PlaywrightAdapter (1.61.0 unavailable on PyPI)
- [Phase ?]: ESCALATION_THRESHOLD_CHARS=200 tunable near-empty markdown escalation boundary (A2, D-04)
- [Phase 03]: Boilerplate removal runs before MinHash computation to prevent false near-dup matches from shared headers/footers (Pitfall 3, T-03-07)
- [Phase 03]: Transient LSH per clean() call (O(n)) accepted for Phase 3 MVP — Phase 5 DataTrove batch dedup replaces this (T-03-06)
- [Phase ?]: Artifact.quality_score mapped as a real ORM column (0006 already added the physical column); language/dedup_status remain metadata_-JSON-only, out of scope for Phase 4 Plan 1
- [Phase ?]: Single global llm_spend scope accepted for Phase 4 MVP; scope is a plain string key so finer-grained scopes can be added later without a schema change
- [Phase ?]: vector_collections uses an is_current boolean flip (not a separate active-alias pointer table) so reindex history is preserved and auditable via created_at
- [Phase 04-02]: Live Bedrock checkpoint resolved: enrich_document() live-verified against real Bedrock via LiteLLM proxy (status=enriched, then cached on re-run); six real gaps found and fixed in commit ac299e1 (openai/ provider prefix, litellm_storage DB, master_key env-var syntax, api_key field, real Bedrock model IDs, markdown-fence stripping)
- [Phase 04]: Alias swap is one atomic update_collection_aliases() call (delete-old + create-new) — verified live against the real docker-compose Qdrant server, not just mocked
- [Phase 04]: index()'s enrichment join (domain, document_type, keywords, quality_score) is looked up once per index() call via a single get_session() block, not once per chunk
- [Phase 04]: reindex_collection() resolves the alias's current dim via the new get_collection_dim() rather than requiring the caller to pass it, so klake reindex needs no --dim flag
- [Phase 05-01]: DataTrove filters called via .filter(doc) directly in a loop (never .run()) — records all heuristics' pass/fail regardless of failure order (CURATE-01, Pitfall 2)
- [Phase 05-01]: Composite quality score weights: parse*0.30 + enrich*0.40 + filter_pass_ratio*0.30 (CURATE-03, Claude's discretion)
- [Phase 05-01]: batch_dedup_corpus() builds ONE MinHashLSH over entire corpus (CURATE-02), resolving T-03-06 tech debt from Phase 3
- [Phase 05-01]: datatrove==0.9.0 and nltk>=3.9,<4 added as direct dependencies; curated_document artifact type added to ids.py _PREFIX
- [Phase ?]: QAPairResult excludes citation_chunk_id — caller assigns programmatically from chunk_id (T-05-05, AI-SPEC Pitfall 1)
- [Phase ?]: dataset_generation LlmSpend scope separate from enrich global scope (AI-SPEC Pitfall 2, DATA-01/02/03)
- [Phase ?]: dataset_examples cache key in payload _cache_key for idempotency (examples not Artifact nodes, D-08)
- [Phase ?]: DomainSettings nested config model under KLAKE_DOMAIN__ env prefix (DOMAIN-01)
- [Phase ?]: domain_system_prompt is Optional[str]=None kwarg in enrich.py — keeps enrichment side-effect-free (DOMAIN-03)
- [Phase ?]: domains_root parent resolution: DomainLoader expects project root but settings.domain.domains_root is the domains/ folder path; resolved in CLI and API
- [Phase ?]: RetryPolicy on all 12 Dagster assets, healthcare_e2e_job defined
- [Phase ?]: healthcare_e2e_job selects exactly 7 core pipeline assets — curate/generate_dataset excluded per Pitfall 6
- [Phase ?]: asset.node_def.retry_policy is the correct Dagster API for accessing retry policy on AssetsDefinition objects
- [Phase ?]: define_asset_job with AssetSelection.assets() using direct Python object references prevents rename breakage (Pitfall 6, RESEARCH.md A6)
- [Phase ?]: curate_document_asset and generate_dataset excluded from healthcare_e2e_job — they require separate source_artifact_id run config not part of ingest-to-index chain
- [Phase ?]: Phase 6 human verification checkpoint auto-approved — all 324 unit tests passed, DomainLoader loads 28 sources, CLI init/index commands work, 8 API routes present, RetryPolicy on all 12 Dagster assets confirmed
- [Phase ?]: mock_store fixture uses QdrantVectorStore.__new__ to bypass __init__; sets _client/_Distance/_PointStruct/_VectorParams as MagicMock — mirrors test_builtin_plugins.py style
- [Phase ?]: Source scalars extracted inside with get_session() block in index.py to prevent DetachedInstanceError (PAYLOAD-01)
- [Phase ?]: register_source() config_dict multi-step construction persists domain/tags/organization into Source.config (D-05, backward-compatible)
- [Phase ?]: ensure_payload_indexes uses lazy local import of PayloadSchemaType; tags filter uses MatchValue (single) or MatchAny (multiple tags, D-11)
- [Phase ?]: format kwarg in search() shadows Python builtin but is accepted — builtin not used in function scope, noqa A002 added
- [Phase ?]: SearchHit carries 7 new provenance fields (PAYLOAD-02)
- [Phase ?]: tags Query param per-element max_length=64 (T-07-04-01); --tag singular repeatable CLI convention (D-12)

### Pending Todos

None yet.

### Blockers/Concerns

**v2.0 (carry into planning):**

- [Phase 10 — Hybrid, LIVE MIGRATION]: Qdrant unnamed→named-vector collection recreate requires re-embedding old points to synthesize sparse vectors (pure copy insufficient). Verify `query_points`/`FusionQuery`/`SparseVectorParams`/`Modifier.IDF` against installed qdrant-client 1.18 and confirm running Qdrant server ≥ 1.10 before migrating. Validate the reindex on a collection copy first. → `--research-phase`.
- [Phase 11 — Scheduling, LIVE MIGRATION]: Additive Alembic 0009 (crawl_schedule/last_crawled_at/last_content_hash); change-gate must hash normalized silver text, not raw bytes (WORM/spend thrash). Sensor needs deterministic run_key + cursor watermark. → `--research-phase`.
- [Phase 12 — Agents]: structlog writes to stdout = the MCP stdio JSON-RPC channel; first-task stdout-lockdown shim + self-test (stdio-only) before any tool logic. Back `--sse` with MCP Streamable HTTP (legacy HTTP+SSE deprecated). Single shared tool registry across stdio/http/openapi/openai. Confirm `streamable_http_app()`/lifespan against installed mcp 1.28.x. → `--research-phase` (Streamable-HTTP/stdout-isolation spike).
- [Phase 8 — Crawl]: reconcile `crawl_config` key mismatch (`rate_limit_rps` stored vs `rate_limit_seconds` read); adaptive delay = `max(robots, backoff, config)`; SSRF guard + bounded frontier on every followed link.
- [Phase 9 — Storage]: keep `get_artifact_by_hash` no-op ordered before key construction; forward-only, never rewrite WORM raw keys; `_unclassified` must be a real routed segment.

**v1.0 (historical):**

- [Phase 3]: Parser quality on real healthcare PDFs unvalidated — torture-test corpus (PARSE-05) gates bulk ingestion; needs deeper research at planning time
- [Phase 4]: LiteLLM budget enforcement behavior under burst load unverified; Qdrant collection aliasing patterns need research
- [Phase 5 RESOLVED]: DataTrove integration pattern resolved — call .filter(doc) directly on in-memory Document objects; skip LocalPipelineExecutor/file I/O entirely (curate.py)

## Deferred Items

Items acknowledged and carried forward (v2.1+, out of v2.0 scope):

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Eval & Observability | EVAL-01 (RAGAS+Promptfoo), EVAL-02 (Langfuse/Arize) | Deferred | v2.0 planning |
| Client & Domain Packs | SDK-01 (klake-client), DOMAIN-05/06 (conflict resolution, pack registry) | Deferred | v2.0 planning |
| Discovery / UI / Versioning | DISCOVER-01 (auto-discovery scheduling), UI-02 (admin dashboard), VERSION-01 (lakeFS/DVC) | Deferred | v2.0 planning |
| Crawl & Retrieval | SITEMAP-01 (sitemap-first crawl), QUALITY-01 (quality-score search propagation) | Deferred | v2.0 planning |

## Session Continuity

**Stopped at:** Completed 07-04-PLAN.md

Last session: 2026-07-08T07:56:22.211Z
Resume file: None

## Operator Next Steps

- Plan the first v2.0 phase with `/gsd-plan-phase 7`
