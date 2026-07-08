# Requirements: Knowledge Lake Framework — v2.0 Agent-Ready Lake

**Defined:** 2026-07-08
**Core Value:** Every domain resource ingested must be traceable from raw source through every transformation to its final AI-ready output — and the framework must remain tool-agnostic so any processor can be swapped without breaking lineage.

> **REQ-ID numbering:** Global (unique across all milestones). Three v2.0 requirements were renumbered off the labels used in the milestone request to avoid colliding with shipped v1.0 IDs: partial-JSON recovery `ENRICH-01→ENRICH-07`, linked-doc ingest `INGEST-01→INGEST-10`, search-mode `RETR-02→RETR-03`. `RETR-01` is retained deliberately — it is v1.0's deferred "hybrid dense+sparse search" requirement now being implemented, not a new ID. Deferred items `DOMAIN-01/02→DOMAIN-05/06` and `UI-01→UI-02` were likewise continued. Archived v1.0 IDs live in `.planning/milestones/v1.0-REQUIREMENTS.md`.

## v2.0 Requirements

Scoped for this milestone. Each maps to exactly one roadmap phase (see Traceability). Phases continue from v1.0's last phase — v2.0 begins at **Phase 7**.

### Metadata & Crawl Maturation

- [x] **PAYLOAD-01**: Every indexed chunk carries an expanded Qdrant payload — `source_id`, `source_name`, `source_url`, `format`, `tags`, `title`, `organization` — assembled at the index-time enrichment join, backward-compatible with existing points.
- [x] **PAYLOAD-02**: A user can filter search results by `source_name`, `format`, `tags` (array-contains), and `source_id` across both the CLI and the REST API, backed by Qdrant keyword payload indexes on each filterable field.
- [x] **CRAWL-01**: A crawl reads per-source `crawl_config` (depth, rate limit) from the source's stored config / `sources.yaml` instead of hard-coded defaults (fixes `crawl_source` passing `source_config=None`; reconciles the `rate_limit_rps` vs `rate_limit_seconds` key mismatch).
- [x] **CRAWL-02**: A user can run `klake crawl-all` to batch-crawl every registered source, with an optional `--domain` filter, driven as a loop over the per-source crawl that honors each source's `crawl_config`.
- [x] **CRAWL-03**: The crawler applies adaptive rate limiting — exponential backoff on HTTP 429/403 responses and a per-host cooldown — composed as `max(robots crawl-delay, backoff, configured delay)` so it never crawls faster than robots.txt allows.
- [x] **ENRICH-07**: LLM enrichment recovers from truncated model output — truncation is detected via the gateway `finish_reason` (not inferred from a parse error), a longest-valid-prefix is extracted, partial results are flagged, and an incomplete result is never cached under the normal content-hash key.
- [x] **INGEST-10**: A crawl of an HTML page can follow links to `.pdf`/`.docx` assets and ingest them through the existing single-URL ingest path — with an SSRF guard on every followed link, a bounded link frontier, and dedup between an HTML page and its linked document.

### MinIO Domain Segmentation

- [ ] **STORE-01**: Objects are written under domain/source-scoped S3 keys `{zone}/{domain}/{source_id}/{hash}.{ext}` with an `_unclassified` fallback segment, while preserving content-addressed dedup and lineage (the `get_artifact_by_hash` no-op stays ordered before key construction; forward-only — existing raw keys are never rewritten).
- [ ] **STORE-02**: Every object write applies S3 object tags — `domain`, `source_name`, `format`, `artifact_type` — within the S3 10-tag limit, as convenience metadata only (the registry remains the source of truth).
- [ ] **STORE-03**: The gold zone is segmented by domain and dataset type — `gold/{domain}/rag_corpus/`, `gold/{domain}/pretrain/`, `gold/{domain}/finetune/`.

### AI Agent Skills

- [ ] **MCP-01**: An MCP server exposes lake operations as curated, intent-level tools — `search`, `ingest_url`, `crawl`, `crawl_all`, `process_crawled`, `add_source`, `list_sources`, `lineage`, `export`, `init_domain`, `stats` — implemented as thin shims over the existing `pipeline/*.py` service functions (never proxying the REST API), sharing one tool registry across all transports.
- [ ] **MCP-02**: A user can start the MCP server over stdio with `klake mcp` and over HTTP with `klake mcp --sse --port 3001`. The stdio path guarantees a clean JSON-RPC stream (structlog and all library output redirected off stdout). *Note (research): the `--sse` HTTP transport is implemented via MCP **Streamable HTTP**, since the legacy HTTP+SSE transport is deprecated in the current MCP spec; `--sse` is retained as the flag name.*
- [ ] **SKILL-01**: The repo ships Claude Code skills — `build-corpus.md`, `search-knowledge.md`, `add-source.md`, `export-dataset.md` — that drive the lake through the stabilized MCP tools.
- [ ] **SKILL-02**: A user can run `klake openapi` to export the API's OpenAPI schema, and a generated `docs/openapi.json` is committed to the repo.
- [ ] **SKILL-03**: OpenAI-format tool definitions are auto-generated from the Pydantic schemas, sharing a single schema source of truth with the OpenAPI export and the MCP tool registry (no drift between surfaces).

### Crawl Scheduling & Hybrid Search

- [ ] **SCHED-01**: A Dagster sensor triggers periodic re-crawl of a source based on its `crawl_schedule`, using a deterministic `run_key` and a cursor watermark to avoid duplicate runs and tick storms.
- [ ] **SCHED-02**: On re-crawl, a content-change comparison over the **normalized silver-stage text** (not raw bytes) decides whether to re-ingest, so dynamic timestamps/nonces don't thrash the immutable raw zone; a max-staleness threshold forces an occasional refresh to catch false negatives.
- [ ] **RETR-01**: Search supports hybrid BM25 + dense retrieval using Qdrant named sparse + dense vectors with server-side RRF fusion, delivered via the existing alias-swap reindex (unnamed→named-vector collection recreate with a re-embedding upsert so all points get sparse vectors).
- [ ] **RETR-03**: The search mode is configurable via `KLAKE_SEARCH__MODE=hybrid|dense|sparse` (default `hybrid`), and a request for a mode whose vectors are absent fails loudly rather than silently degrading.

## Deferred Requirements (v2.1+)

Acknowledged and tracked, but out of this milestone's scope.

### Evaluation & Observability

- **EVAL-01**: RAGAS + Promptfoo eval harness for retrieval-quality measurement.
- **EVAL-02**: Langfuse/Arize observability integration for production monitoring.

### Client & Domain Packs

- **SDK-01**: Lightweight client SDK package (`klake-client`) wrapping the REST API.
- **DOMAIN-05**: Multi-domain pack conflict resolution (overlapping sources across packs).
- **DOMAIN-06**: Domain pack registry/catalog with versioning and publishing.

### Discovery, UI & Versioning

- **DISCOVER-01**: SearXNG auto-discovery scheduling (periodic source expansion).
- **UI-02**: Admin UI / crawl analytics dashboard (coverage per source, freshness, failure rates).
- **VERSION-01**: lakeFS / DVC data versioning for the raw zone.

### Crawl & Retrieval Enhancements

- **SITEMAP-01**: Sitemap-first crawl strategy (detect and use sitemaps for URL discovery).
- **QUALITY-01**: Quality-score propagation to search (Qdrant payload filtering to prefer high-quality chunks).

## Out of Scope

Explicitly excluded from v2.0. Documented to prevent scope creep and re-litigation.

| Feature | Reason |
|---------|--------|
| OpenSearch full-text integration (old v1.0 `RETR-02`) | Superseded by Qdrant native sparse vectors + RRF hybrid (RETR-01/03); adding a second search engine is redundant operational weight. |
| Client-side or fixed-weight score fusion | Anti-feature — dense and sparse scores are on incomparable scales; use Qdrant server-side rank-based RRF only. |
| 1:1 dump of all 26 REST endpoints as MCP tools | Anti-feature — the top documented cause of failing agents; expose ~11 curated intent-level tools instead. |
| Eager backfill / re-keying of existing raw objects | Violates raw-zone WORM immutability; STORE-01 is forward-only. A copy-forward backfill is deferred ops tooling, only if uniform S3 lifecycle policies are later required. |
| Direct provider SDKs (incl. `openai`) for tool-def generation | Violates the LiteLLM-only constraint; OpenAI tool defs are generated from Pydantic schemas, not the OpenAI SDK. |
| Raw-bytes hashing for re-crawl change detection | Anti-feature — thrashes on dynamic HTML, bloating the WORM raw zone and burning LLM spend; SCHED-02 gates on a normalized signature. |
| GPU-based sparse encoders (SPLADE/miniCOIL) for v2.0 | CPU droplet constraint; BM25 via `fastembed` is the correct v2.0 default. Documented upgrade path for later. |

## Traceability

Which phase covers which requirement. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PAYLOAD-01 | Phase 7 | Complete |
| PAYLOAD-02 | Phase 7 | Complete |
| CRAWL-01 | Phase 8 | Complete |
| CRAWL-02 | Phase 8 | Complete |
| CRAWL-03 | Phase 8 | Complete |
| ENRICH-07 | Phase 8 | Complete |
| INGEST-10 | Phase 8 | Complete |
| STORE-01 | Phase 9 | Pending |
| STORE-02 | Phase 9 | Pending |
| STORE-03 | Phase 9 | Pending |
| RETR-01 | Phase 10 | Pending |
| RETR-03 | Phase 10 | Pending |
| SCHED-01 | Phase 11 | Pending |
| SCHED-02 | Phase 11 | Pending |
| MCP-01 | Phase 12 | Pending |
| MCP-02 | Phase 12 | Pending |
| SKILL-01 | Phase 12 | Pending |
| SKILL-02 | Phase 12 | Pending |
| SKILL-03 | Phase 12 | Pending |

**Coverage:**

- v2.0 requirements: 19 total
- Mapped to phases: 19 ✓
- Unmapped: 0 ✓

**Phase distribution:**

- Phase 7 (Metadata Foundation): PAYLOAD-01, PAYLOAD-02 — 2
- Phase 8 (Crawl Maturation): CRAWL-01, CRAWL-02, CRAWL-03, ENRICH-07, INGEST-10 — 5
- Phase 9 (Storage Segmentation): STORE-01, STORE-02, STORE-03 — 3
- Phase 10 (Hybrid Retrieval): RETR-01, RETR-03 — 2 *(live migration)*
- Phase 11 (Crawl Scheduling): SCHED-01, SCHED-02 — 2 *(live migration)*
- Phase 12 (Agent Surfaces): MCP-01, MCP-02, SKILL-01, SKILL-02, SKILL-03 — 5

---
*Requirements defined: 2026-07-08*
*Last updated: 2026-07-08 after v2.0 roadmap creation (Phases 7-12 mapped, 19/19 coverage)*
