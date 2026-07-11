# Roadmap: Knowledge Lake Framework

## Milestones

- ✅ **v1.0 MVP** — Phases 1-6 (shipped 2026-07-07)
- 🔨 **v2.0 Agent-Ready Lake** — Phases 7-12 (planning started 2026-07-08)

## Phases

### v2.0 — Agent-Ready Lake

- [x] **Phase 7: Metadata Foundation** - Expanded chunk payload + searchable metadata filters (CLI + API) (completed 2026-07-08)
- [x] **Phase 8: Crawl Maturation** - Per-source config, adaptive rate limiting, linked-doc ingest, `crawl-all`, partial-JSON recovery (completed 2026-07-09)
- [x] **Phase 9: Storage Segmentation** - Domain/source-scoped S3 keys, object tags, gold-zone sub-zones (forward-only) (completed 2026-07-10)
- [x] **Phase 10: Hybrid Retrieval** - BM25 + dense named vectors with server-side RRF, mode-switchable *(LIVE MIGRATION)* (completed 2026-07-11)
- [x] **Phase 11: Crawl Scheduling** - Dagster re-crawl sensor + normalized-text change gate *(LIVE MIGRATION)*
- [ ] **Phase 12: Agent Surfaces** - Curated MCP server (stdio + Streamable HTTP), OpenAPI/OpenAI tool defs, Claude Code skills

<details>
<summary>✅ v1.0 MVP (Phases 1-6) — SHIPPED 2026-07-07</summary>

Full archive: [.planning/milestones/v1.0-ROADMAP.md](.planning/milestones/v1.0-ROADMAP.md)

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 1 | Foundation & End-to-End Spike | 6/6 | ✅ Complete | 2026-07-03 |
| 2 | Ingestion | 6/6 | ✅ Complete | 2026-07-04 |
| 3 | Parse, Clean & Chunk | 3/3 | ✅ Complete | 2026-07-05 |
| 4 | Enrichment, Embedding & Search | 3/3 | ✅ Complete | 2026-07-06 |
| 5 | Curation, Datasets & Export | 3/3 | ✅ Complete | 2026-07-06 |
| 6 | Healthcare Domain Pack & Full-Surface Validation | 4/4 | ✅ Complete | 2026-07-07 |

**Total:** 6 phases, 25 plans, 259 commits, 303 files changed

</details>

## Phase Details

### Phase 7: Metadata Foundation

**Goal**: Users can find and filter knowledge by rich source metadata — every chunk carries its provenance and is filterable at search time.
**Depends on**: Nothing new (first v2.0 phase; builds on shipped v1.0 — independent of Phases 8 and 9, can run as a parallel workstream)
**Requirements**: PAYLOAD-01, PAYLOAD-02
**Success Criteria** (what must be TRUE):

  1. Every newly indexed chunk carries `source_id`, `source_name`, `source_url`, `format`, `tags`, `title`, and `organization` in its Qdrant payload, assembled at the index-time enrichment join and backward-compatible with existing points.
  2. A user can filter search results by `source_name`, `format`, `tags` (array-contains), and `source_id` from both the CLI and the REST API.
  3. Each filterable field is backed by a Qdrant keyword payload index (array-keyword for `tags`), so filtered search never triggers a full-collection scan.
  4. Filters are documented as only fully effective on points indexed after this phase (or after a reindex), matching the backward-compatibility contract.

**Plans**: 4/4 plans complete

Plans:
**Wave 1**

- [x] 07-01-PLAN.md — Wave 0 test scaffold: test_qdrant_payload_indexes.py (RED state)
- [x] 07-02-PLAN.md — Payload expansion: get_source() in repo.py, 7 new payload fields in index.py, register_source() tags fix (PAYLOAD-01)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 07-03-PLAN.md — Search backend: ensure_payload_indexes() in qdrant_store.py, search() 4 new filter kwargs + MatchAny (PAYLOAD-02)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 07-04-PLAN.md — CLI/API surface: SearchHit 7 new fields, search endpoint 4 new params, CLI 4 new flags (PAYLOAD-01, PAYLOAD-02)

### Phase 8: Crawl Maturation

**Goal**: Crawls honor per-source configuration, adapt politely to server pushback, harvest linked documents, run in batch, and survive truncated enrichment output.
**Depends on**: Nothing new (independent of Phases 7 and 9, parallelizable; unblocks Phases 11 and 12)
**Requirements**: CRAWL-01, CRAWL-02, CRAWL-03, ENRICH-07, INGEST-10
**Success Criteria** (what must be TRUE):

  1. A crawl reads each source's `crawl_config` (depth, rate limit) from stored config / `sources.yaml` instead of hard-coded defaults — fixing `crawl_source` passing `source_config=None` and reconciling the `rate_limit_rps` vs `rate_limit_seconds` key mismatch.
  2. A user can run `klake crawl-all` (with optional `--domain` filter) to batch-crawl every registered source, driven as a loop over the per-source crawl that honors each source's `crawl_config`.
  3. The crawler backs off exponentially on HTTP 429/403 and enforces a per-host cooldown, with the effective delay computed as `max(robots crawl-delay, backoff, configured delay)` so it never crawls faster than robots.txt allows.
  4. A crawl of an HTML page can follow links to `.pdf`/`.docx` assets and ingest them through the existing single-URL ingest path, with an SSRF guard on every followed link, a bounded link frontier, and dedup between an HTML page and its linked document.
  5. Truncated LLM enrichment is detected via the gateway `finish_reason` (not inferred from a parse error), a longest-valid-prefix is recovered and flagged partial, and an incomplete result is never cached under the normal content-hash key.

**Plans**: 6/6 plans complete

Plans:
**Wave 1**

- [x] 08-01-PLAN.md — Wave 0 test scaffold: xfail stubs for all 5 requirements (CRAWL-01/02/03, ENRICH-07, INGEST-10)
- [x] 08-02-PLAN.md — Infrastructure layer: repo.py helpers, ratelimit.py adaptive PerHostLimiter, CrawlPageResult http_status_code (CRAWL-01/03)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 08-03-PLAN.md — crawl.py core: fix source_config=None bug, adaptive backoff, crawl_all_sources() (CRAWL-01/02/03)
- [x] 08-04-PLAN.md — enrich.py: ENRICH-07 partial-JSON recovery via finish_reason + prefix extraction

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 08-05-PLAN.md — crawl.py INGEST-10: linked-doc post-bronze ingestion with SSRF guard and bounded frontier
- [x] 08-06-PLAN.md — CLI + API surface: klake crawl-all command, POST /crawl-all endpoint, CrawlAllOut schemas (CRAWL-02)

### Phase 9: Storage Segmentation

**Goal**: Objects are stored under domain/source-scoped keys with descriptive tags, without breaking content-addressed dedup or lineage, and without ever rewriting WORM raw objects.
**Depends on**: Nothing new (independent of Phases 7 and 8, parallelizable; forward-only, no data migration)
**Requirements**: STORE-01, STORE-02, STORE-03
**Success Criteria** (what must be TRUE):

  1. New objects are written under `{zone}/{domain}/{source_id}/{hash}.{ext}` keys with a real routed `_unclassified` fallback segment (no `//` or `None` segments); existing raw keys are never rewritten (forward-only, WORM-safe).
  2. Content-addressed dedup and lineage still hold — the `get_artifact_by_hash` no-op stays ordered before key construction, so identical content is not re-stored and lineage anchoring is preserved.
  3. Every object write applies S3 object tags — `domain`, `source_name`, `format`, `artifact_type` — within the S3 10-tag limit, as convenience metadata only (the registry remains the source of truth).
  4. The gold zone is segmented by domain and dataset type: `gold/{domain}/rag_corpus/`, `gold/{domain}/pretrain/`, `gold/{domain}/finetune/`.

**Plans**: 6/6 plans complete

Plans:
**Wave 0** *(parallel)*

- [x] 09-01-PLAN.md — Storage layer test scaffold: test_put_raw_domain.py, test_format_tags.py, test_put_object_tags.py, TestPutBronzeDomainKey (STORE-01/02 RED tests)
- [x] 09-02-PLAN.md — Pipeline test scaffold: test_parse_silver_key.py, test_clean_silver_key.py, TestGoldZone* in test_export.py (STORE-01/03 RED tests)

**Wave 1** *(depends on Wave 0)*

- [x] 09-03-PLAN.md — Storage layer: s3.py (_format_tags, put_object tags, put_raw/put_bronze domain-scoped keys) + test_raw_immutable.py assertion update (STORE-01/02)

**Wave 2** *(parallel, depends on Wave 1)*

- [x] 09-04-PLAN.md — Silver zone callers: parse.py + clean.py (move key inside session block, domain resolution, tags) (STORE-01/02)
- [x] 09-05-PLAN.md — Raw/bronze callers: ingest.py + crawl.py (domain resolution + tags on put_raw/put_bronze) (STORE-01/02)
- [x] 09-06-PLAN.md — Gold zone: export.py (domain kwarg on 3 export functions, domain-scoped gold keys, tags) (STORE-02/03)

### Phase 10: Hybrid Retrieval

**Goal**: Search combines lexical BM25 and dense semantic retrieval with server-side RRF fusion, is mode-switchable, and fails loudly rather than silently degrading.
**Depends on**: Phase 7 (payload filters must continue to work in hybrid mode)
**Requirements**: RETR-01, RETR-03
**Success Criteria** (what must be TRUE):

  1. Search runs hybrid BM25 + dense retrieval using Qdrant named sparse + dense vectors with server-side RRF fusion (`fastembed` BM25 + `Modifier.IDF`; prefetch limit ≥ main limit + offset).
  2. Existing collections are migrated unnamed→named via the existing alias-swap reindex with a **re-embedding** upsert so all points carry sparse vectors, with point-count parity verified (a pure copy is insufficient).
  3. A user can set `KLAKE_SEARCH__MODE=hybrid|dense|sparse` (default `hybrid`); a request for a mode whose vectors are absent fails loudly rather than silently degrading.
  4. Phase 7 payload filters continue to work in hybrid mode; the running Qdrant server is confirmed ≥ 1.10 before the migration runs.

**Plans**: 8/8 plans complete

Plans:
**Wave 1** *(parallel — RED test scaffolds + dependency)*

- [x] 10-01-PLAN.md — Store/migration RED tests: test_qdrant_hybrid.py + test_qdrant_hybrid_migration.py (RETR-01, D-07)
- [x] 10-02-PLAN.md — Mode-surface RED tests: settings/search-mode/CLI/API + extend test_search_filters.py (RETR-03, D-14)
- [x] 10-03-PLAN.md — fastembed>=0.8,<0.9 dependency + Qdrant/bm25 install checkpoint (RETR-01, D-01) *(checkpoint — autonomous:false)*

**Wave 2** *(parallel — contracts + sparse encoder)*

- [x] 10-04-PLAN.md — SearchSettings + settings.search; VectorPoint.sparse + VectorStorePlugin.search signature (RETR-03/01, D-08/D-09)
- [x] 10-05-PLAN.md — plugins/builtin/sparse_embedder.py fastembed Qdrant/bm25 wrapper (RETR-01, D-01/D-03)

**Wave 3** *(store core)*

- [x] 10-06-PLAN.md — qdrant_store.py: named create-paths, get_collection_dim, _is_named, server preflight, upsert shape branch, reembed helper, hybrid RRF search + fail-loud, reindex parity gate (RETR-01/03, D-05/D-06/D-07/D-10/D-11/D-12/D-13)

**Wave 4** *(pipeline wiring)*

- [x] 10-07-PLAN.md — index.py (sparse build + live re-embed migration + preflight) + search.py (mode + sparse_query) (RETR-01/03, D-03/D-05/D-09)

**Wave 5** *(interface surface)*

- [x] 10-08-PLAN.md — cli/app.py (search --mode, reindex --hybrid) + api/app.py + api/schemas.py (?mode= with fail-closed validation) (RETR-01/03, D-04/D-09)

**Migration note**: LIVE DATA MIGRATION (Qdrant unnamed→named-vector collection recreate + re-embedding upsert). Flag for `--research-phase` at plan time — verify `query_points`/`FusionQuery`/`SparseVectorParams`/`Modifier.IDF` against installed qdrant-client 1.18, confirm Qdrant server ≥ 1.10, and validate the re-embedding reindex on a collection copy first. Rollback: alias keeps old collections until parity is verified.

### Phase 11: Crawl Scheduling

**Goal**: The lake re-crawls sources on schedule and only re-ingests genuinely changed content, so it stays fresh without thrashing the immutable raw zone.
**Depends on**: Phase 8 (needs a runnable per-source crawl trigger that honors `crawl_config`)
**Requirements**: SCHED-01, SCHED-02
**Success Criteria** (what must be TRUE):

  1. New Source columns (`crawl_schedule`, `last_crawled_at`, `last_content_hash`) are added via an additive, forward-only Alembic `0009` migration.
  2. On re-crawl, a content-change comparison over the **normalized silver-stage text** (not raw bytes) decides whether to re-ingest, so dynamic timestamps/nonces don't trigger a new immutable raw write every tick.
  3. A max-staleness threshold forces an occasional refresh to catch change-detection false negatives.
  4. A Dagster `@sensor` triggers periodic re-crawl of a source based on its `crawl_schedule`, using a deterministic `run_key` and a cursor watermark (plus per-source concurrency) to avoid duplicate runs and tick storms.

**Plans**: 6/6 plans complete (5 original + gap-closure 11-06); verified 9/9

Plans:
**Wave 0**

- [x] 11-01-PLAN.md — RED test scaffold: test_recrawl_gate.py, test_recrawl_sensor.py, test_set_schedule_cli.py + migration test extension (SCHED-01/02)

**Wave 1** *(depends on Wave 0)*

- [x] 11-02-PLAN.md — Schema layer: Alembic 0009 + 3 nullable Source columns, repo helpers (touch_source_crawl/list_scheduled_sources/set_source_schedule/create_source kwarg), CrawlSettings.max_staleness_days (SCHED-01/02)

**Wave 2** *(parallel, depends on Wave 1)*

- [x] 11-03-PLAN.md — Change gate: recrawl_source() normalized-text SHA256 gate before put_raw + staleness override + SSRF probe (SCHED-02)
- [x] 11-04-PLAN.md — CLI surface: SourceEntry.crawl_schedule, domain-init persistence, klake set-schedule verb with is_valid_cron_string validation (SCHED-01)

**Wave 3** *(depends on Wave 2)*

- [x] 11-05-PLAN.md — Dagster: sensors.py (recrawl_sensor + recrawl_op + recrawl_source_job + RecrawlConfig), Definitions registration, dagster.yaml QueuedRunCoordinator swap (SCHED-01)

**Wave 4** *(gap closure — verification human-item resolution)*

- [x] 11-06-PLAN.md — Gate-local volatile-token suppression (ISO timestamps/UUIDs/hex nonces) closing SCHED-02 anti-thrash clause + unconditional nonce test; durable per-source concurrency regression/config-drift guard (SCHED-02, human items #1+#2)

**Migration note**: LIVE DATA MIGRATION (additive `crawl_schedule` / `last_crawled_at` / `last_content_hash` columns on the Source registry). Flag for `--research-phase` at plan time. Rollback: forward-only additive columns; the sensor can be disabled independently of the schema change.

### Phase 12: Agent Surfaces

**Goal**: AI agents can drive the whole lake through a curated, intent-level MCP tool surface plus static schema exports — all sharing one schema source of truth.
**Depends on**: Phase 8 (needs `crawl_all` plus `process_crawled` / `list_sources` extracted into `pipeline`/`registry`) and the stabilized service functions from Phases 7, 9, 10, 11 that it wraps — sequenced LAST
**Requirements**: MCP-01, MCP-02, SKILL-01, SKILL-02, SKILL-03
**Success Criteria** (what must be TRUE):

  1. An MCP server exposes ~11 curated intent-level tools (`search`, `ingest_url`, `crawl`, `crawl_all`, `process_crawled`, `add_source`, `list_sources`, `lineage`, `export`, `init_domain`, `stats`) as thin shims over the existing `pipeline/*.py` service functions (never proxying the REST API), sharing one tool registry across all transports.
  2. A user can start the server over stdio with `klake mcp` — with a guaranteed clean JSON-RPC stream (structlog and all library output redirected off stdout) — and over HTTP with `klake mcp --sse --port 3001`, backed by MCP **Streamable HTTP** (the deprecated HTTP+SSE transport is not used; `--sse` is retained as the flag name).
  3. A user can run `klake openapi` to export the API's OpenAPI schema, and a generated `docs/openapi.json` is committed to the repo.
  4. OpenAI-format tool definitions are auto-generated from the Pydantic schemas, sharing a single schema source of truth with the OpenAPI export and the MCP tool registry (assert stdio == http == openapi == openai; no drift between surfaces).
  5. The repo ships Claude Code skills — `build-corpus.md`, `search-knowledge.md`, `add-source.md`, `export-dataset.md` — that drive the lake through the stabilized MCP tools.

**Plans**: 8 plans
**Wave 1**

- [ ] 12-01-PLAN.md — mcp==1.28.1 dependency + Wave 0 RED test scaffold (normalize helper)

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 12-02-PLAN.md — extract process_crawled/list_sources/stats/load_domain + count_points; refactor CLI/API callers
- [ ] 12-03-PLAN.md — schema source-of-truth: extend SearchParams + new tool input models
- [ ] 12-04-PLAN.md — fd-level stdout-lockdown shim + self-test (first-task gate, stdio only)

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 12-05-PLAN.md — McpSettings + tool registry (ToolDef/TOOLS) + low-level MCP server core

**Wave 4** *(blocked on Wave 3 completion)*

- [ ] 12-06-PLAN.md — Streamable-HTTP transport: localhost bind, Host guard, closed CORS, optional bearer, read-only posture

**Wave 5** *(blocked on Wave 4 completion)*

- [ ] 12-07-PLAN.md — klake mcp (stdio/--sse) + klake openapi + OpenAI tool defs; committed docs/openapi.json & docs/openai_tools.json

**Wave 6** *(blocked on Wave 5 completion)*

- [ ] 12-08-PLAN.md — surface parity test (stdio==http==openapi==openai) + four Claude Code skills

**Research note**: Flag for `--research-phase` at plan time (stdout-isolation / Streamable-HTTP spike) — confirm `streamable_http_app()`/lifespan wiring against installed `mcp` 1.28.x, nail the `--sse`→Streamable HTTP substitution, and settle the localhost/auth/CORS + read/write tool-separation model before coding. First-task gate: stdout-lockdown shim + self-test (stdio mode only) before any tool logic.

## Progress

### v2.0 — Agent-Ready Lake

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 7. Metadata Foundation | 4/4 | Complete    | 2026-07-08 |
| 8. Crawl Maturation | 6/6 | Complete    | 2026-07-08 |
| 9. Storage Segmentation | 6/6 | Complete    | 2026-07-09 |
| 10. Hybrid Retrieval | 8/8 | Complete    | 2026-07-10 |
| 11. Crawl Scheduling | 6/6 | Complete    | 2026-07-10 |
| 12. Agent Surfaces | 0/? | Not started | - |
