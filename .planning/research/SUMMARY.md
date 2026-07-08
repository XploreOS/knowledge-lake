# Project Research Summary

**Project:** Knowledge Lake Framework (`klake`) — v2.0 "Agent-Ready Lake"
**Domain:** AI-ready knowledge-lake framework (Python data pipeline; additive milestone on shipped v1.0)
**Researched:** 2026-07-08
**Confidence:** HIGH

## Executive Summary

v2.0 turns a shipped, working knowledge lake into an *agent-ready* one without re-architecting it. The research is unusually high-confidence because every finding is grounded in direct reads of the shipped v1.0 source and by importing the exact pinned dependency versions. The dominant conclusion: **almost nothing here is new infrastructure — it is additive wiring onto proven seams.** Only two new runtime dependencies are required (`mcp` for the agent server, `fastembed` for client-side BM25 sparse vectors); everything else (hybrid RRF, adaptive rate limiting, the re-crawl sensor, OpenAPI/OpenAI tool export) reuses packages already pinned in `pyproject.toml`. The load-bearing invariant to preserve throughout is D-02: CLI, API, Dagster — and now MCP — are thin adapters over the same `pipeline/*.py` service functions. New behavior lands in `pipeline/`/`plugins/`, never in an adapter.

The recommended build approach is dependency-ordered, not theme-grouped. Payload enrichment must precede search filters (a filter can only match a field the payload carries). Crawl config/adaptive-limiting/PDF-routing must precede `crawl-all` (batch is a loop over a single-source crawl that must already honor per-source config). The sparse-vector collection migration must precede hybrid query mode. Schedule columns must precede the Dagster sensor. And **MCP must come last** — it is a thin wrapper, so wrapping functions that are still being reshaped (crawl_all added, process_crawled/list_sources extracted from CLI) would churn the tool registry. Phases A (metadata), B (crawl), C (storage) are mutually independent and can parallelize; D (hybrid) depends on A; E (scheduling) depends on B; F (agents) depends on B plus everything it wraps.

The risk profile is concentrated in two live-data migrations and a cluster of high-probability interaction bugs. The two migrations: (1) **RETR-01** requires recreating each Qdrant collection from unnamed→named vectors and *re-embedding* old points to synthesize sparse vectors (a pure copy is insufficient) — mitigated by the existing alias-swap reindex machinery; (2) **STORE-01** puts domain into the S3 key, which collides with content-addressed dedup and lineage anchoring unless the hash no-op stays ordered *before* key construction and the scheme is forward-only (never rewrite WORM raw objects). The highest-probability failure is mundane but fatal: structlog writes to **stdout**, which is exactly the MCP stdio JSON-RPC channel — so the stdio path needs a stdout-lockdown shim as its very first task. These, plus content-hash detection on normalized silver text (not raw bytes) and never caching partial-JSON enrichment, must become explicit phase acceptance criteria rather than incidental details.

## Key Findings

### Recommended Stack

v2.0 adds exactly two runtime dependencies and reuses the rest of the validated v1.0 stack. `mcp>=1.28,<2.0` bundles FastMCP and all three transports (stdio, SSE, streamable-HTTP) in one dependency — do **not** add the standalone `fastmcp` package. `fastembed>=0.8,<0.9` is Qdrant's companion library for client-side BM25 sparse vectors; paired with a collection-level `Modifier.IDF`, Qdrant computes corpus-global IDF server-side. Both are CPU-only (no GPU), matching the DigitalOcean droplet constraint, and BM25 is a pure lexical path so it does not touch the LiteLLM-only rule.

**Core technologies (additions only):**
- `mcp` 1.28.x: MCP server over stdio + streamable-HTTP — Anthropic reference SDK; one dep, one FastMCP instance, transport-agnostic tool registry.
- `fastembed` 0.8.x: client-side BM25 sparse vectors — Qdrant-native hybrid recipe; deterministic, no LLM call.
- `qdrant-client` 1.18.0 (reused): `FusionQuery`/`Prefetch`/`SparseVectorParams`/`Modifier` all verified present — hybrid RRF needs no client or server bump (server must be >=1.10).
- `crawl4ai` 0.9.0 + `tenacity` (reused): `RateLimiter` + `MemoryAdaptiveDispatcher` supply reactive 429/403 backoff; existing `PerHostLimiter` stays as the outer politeness layer.
- `dagster` 1.13.11, `fastapi` 0.139.0, `pydantic` 2.13.4, `orjson` (reused): sensor, OpenAPI export, and OpenAI tool-def generation all from existing pins.

### Expected Features

19 requirements across five capability areas. Full detail (priority matrix, when-each-search-mode-wins, agent tool contract) lives in `FEATURES.md`.

**Must have (P1 — core v2.0 value / low-risk enablers):**
- PAYLOAD-01/02 — richer chunk payload + search filters (the searchable-metadata foundation everything cites).
- RETR-01/02 — hybrid BM25+dense with RRF, mode-switchable (the correctness upgrade for codes/acronyms; default hybrid).
- MCP-01/02 — curated MCP server (~5-8 intent tools, not 26 endpoints 1:1) over stdio + streamable-HTTP.
- SKILL-02/03 — OpenAPI export + OpenAI tool defs (near-free from FastAPI + Pydantic; one schema source of truth).
- CRAWL-01/02/03 — per-source config, `crawl-all` batch, adaptive rate limiting.
- STORE-01 — domain-scoped S3 keys (needed before storage grows further).

**Should have (P2 — builds on P1):**
- SKILL-01 — Claude Code skills over stable MCP tools.
- SCHED-01/02 — self-maintaining re-crawl sensor + content-hash change detection.
- INGEST-01 — linked PDF/doc harvesting (bounded).
- STORE-02/03 — object tags + gold-zone segmentation.
- ENRICH-01 — partial-JSON recovery (independent; low coupling; ships anytime).

**Defer (v2.1+, per PROJECT.md):**
- Eval harness (RAGAS/Promptfoo), observability (Langfuse/Arize), klake-client SDK, pack registry/versioning, admin UI, lakeFS/DVC versioning.

### Architecture Approach

v2.0 preserves the v1.0 four-layer shape (thin adapters -> `pipeline/*.py` service functions -> resolver-keyed plugins -> Postgres/S3/Qdrant/LiteLLM). MCP joins as a **fourth adapter, sibling to CLI/FastAPI/Dagster** — calling pipeline functions in-process, never proxying FastAPI over HTTP. Almost every change is additive (`+x` on an existing component) with defaults preserving today's behavior; the only structural debt MCP forces is extracting two CLI-embedded behaviors (`process_crawled`, `list_sources`/`stats`) down into `pipeline/`/`registry` so all surfaces share them.

**Major components (v2.0 deltas):**
1. `mcp/` package (NEW) — 11 tools as pure shims onto pipeline functions; one registry, two transports.
2. `pipeline/search.py` + `pipeline/index.py` + `qdrant_store.py` — expanded payload, dense+sparse named vectors, RRF hybrid query (all additive, keyword-only defaults).
3. `storage/s3.py` + `pipeline/export.py` — domain-segmented keys, object tags, gold sub-zones (forward-only).
4. `dagster_defs/sensors.py` (NEW) + Alembic `0009` — re-crawl sensor + Source schedule/hash columns.
5. `pipeline/crawl.py` + `crawl/ratelimit.py` + `pipeline/crawl_all.py` (NEW) — per-source config wiring, adaptive backoff, PDF-from-crawl routing, batch driver.

### Critical Pitfalls

1. **structlog on stdout corrupts the MCP stdio JSON-RPC stream** — the single highest-probability failure; the existing logging default actively fights the new transport. First-task gate for the MCP phase: write a stdout-isolation shim (route structlog + LiteLLM/Docling/Crawl4AI output to stderr) plus a self-test, gated on stdio mode only, *before* any tool logic.
2. **Building on the deprecated SSE transport** — the requirement says "SSE" but the spec deprecated HTTP+SSE in favor of Streamable HTTP. Back the `--sse` flag with `streamable_http_app()`; record the substitution as an intentional deviation. This is a requirement-vs-spec conflict to resolve up front.
3. **Domain-scoped S3 keys break dedup + lineage** — the key *is* the dedup identity and lineage anchor in a WORM store. Keep the `get_artifact_by_hash` no-op ordered *before* key construction; forward-only writes; never rewrite existing raw keys; make `_unclassified` a real routed value (no `//`/`None` segments).
4. **Content-hash re-crawl detection thrashes on dynamic HTML** — hash the **normalized silver-stage text, not raw bytes**, or nonces/timestamps trigger a new immutable raw write every tick (WORM bloat + LiteLLM spend). Keep raw-bytes SHA256 for storage identity; gate re-ingest on the normalized signature; add a max-staleness forced refresh to catch false negatives.
5. **Partial-JSON recovery poisons the enrichment cache** — a repaired partial cached under the normal key permanently poisons the corpus (one call per doc, cached by content hash). Detect truncation via LiteLLM `finish_reason=length` (do not infer from parse failure); retry-with-more-tokens first; flag partials and **never cache them under the normal key**; parse longest-valid-prefix rather than blind brace-appending.

Additional high-value pitfalls to carry as acceptance criteria: single tool registry (stdio == http == openapi == openai defs), Dagster sensor deterministic `run_key` + cursor watermark, adaptive delay = `max(robots, backoff, config)` never faster than robots, followed-link SSRF guard + bounded frontier for INGEST-01, Qdrant prefetch limit >= main limit+offset with IDF modifier set and sparse on ALL points.

## Implications for Roadmap

Suggested phases continue from Phase 7 (v1.0 ended at Phase 6/milestone). Ordering is driven by real code coupling, not theme grouping. Phases A/B/C are mutually independent and parallelizable; D depends on A; E depends on B; F depends on B plus everything it wraps.

### Phase 7 — Metadata Foundation (PAYLOAD-01, PAYLOAD-02)
**Rationale:** Lowest risk, no new deps, foundational. A filter can only match a field the payload carries, so payload lands before filters.
**Delivers:** Expanded chunk payload (source_id/name/url/format/title/organization/tags) at `index.py` join point; search filters at `search.py` filter builder, mirrored across CLI/API.
**Avoids:** Missing-payload-index full scans (create Qdrant keyword indexes on every new filterable field; array-keyword for tags). Note filters only fully effective on points indexed after this phase, or after a reindex.

### Phase 8 — Crawl Maturation (CRAWL-01, CRAWL-03, INGEST-01, CRAWL-02, ENRICH-01)
**Rationale:** Independent of Phase 7; unblocks both crawl-all and the scheduler. Per-source config + adaptive limiting + PDF-routing must exist before crawl-all loops over them.
**Delivers:** Wire `Source.config['crawl_config']` into `crawl_source` (fixes `source_config=None`; reconcile the rps<->seconds key mismatch); adaptive 429/403 backoff in `PerHostLimiter`; PDF-from-crawl routed to `ingest_url`; `pipeline/crawl_all.py` batch driver with `--domain`; partial-JSON recovery in `enrich.py`.
**Avoids:** Adaptive-limiter host starvation and robots override (Pitfall 7 — `max()` composition, host-partitioned scheduler); followed-link SSRF/explosion (Pitfall 9 — SSRF guard on every followed link, bounded frontier, HTML<->PDF dedup); partial-JSON cache poisoning (Pitfall 8 — flag, do not cache).

### Phase 9 — Storage Segmentation (STORE-01, STORE-02, STORE-03)
**Rationale:** Independent; STORE-01/02 are the same `put_object` change site. Forward-only, no migration.
**Delivers:** `{zone}/{domain}/{source_id}/{hash}.{ext}` keys with `_unclassified` fallback; object tags (domain/source_name/format/artifact_type, capped to AWS 10-tag limits); gold sub-zones (rag_corpus/pretrain/finetune).
**Avoids:** Dedup/lineage break (Pitfall 4 — hash no-op ordered before key construction; forward-only; registry stays source of truth, tags are convenience only).

### Phase 10 — Hybrid Retrieval (RETR-01, RETR-02) — LIVE MIGRATION
**Rationale:** Highest technical risk; needs the reindex machinery. Sparse infra (named collections, migration) must exist before hybrid query mode. Depends on Phase 7 payload (filters must work in hybrid mode too).
**Delivers:** Named-vector collections (dense+sparse) via the existing alias-swap reindex with a **re-embedding** `upsert_fn`; `fastembed` BM25 + `Modifier.IDF`; `mode=hybrid|dense|sparse` in `search()` with server-side RRF.
**Avoids:** In-place ALTER of unnamed-vector collection (impossible — recreate + re-embed); partial-collection problem (sparse on ALL points, verify count parity); prefetch limit >= limit+offset; verify Qdrant server >=1.10; fail loudly when requested mode's vectors are absent.

### Phase 11 — Crawl Scheduling (SCHED-schema, SCHED-02, SCHED-01) — LIVE MIGRATION
**Rationale:** Needs a runnable crawl trigger + registry columns. Sensor's due-query and hash gate both read new Source columns.
**Delivers:** Alembic `0009` (crawl_schedule, last_crawled_at, last_content_hash); normalized-signature change gate in `crawl.py`; Dagster `@sensor` + crawl asset.
**Avoids:** Raw-bytes thrashing (Pitfall 5 — hash normalized silver text; max-staleness refresh); sensor duplicate runs/tick storms (Pitfall 6 — deterministic `run_key`, cursor watermark, per-source concurrency, cheap evaluation).

### Phase 12 — Agent Surfaces (refactor, SKILL-02, SKILL-03, MCP-01/02, SKILL-01) — LAST
**Rationale:** MCP is a thin wrapper; wrapping functions still being reshaped churns the registry. Comes after crawl_all exists and process_crawled/list_sources are extracted.
**Delivers:** Extract `process_crawled` + `list_sources`/`stats` into `pipeline`/`registry`; `klake openapi` dump + OpenAI tool defs from one shared schema/mapping table; MCP server (stdio + streamable-HTTP, 11 shim tools); Claude Code skills.
**Avoids:** stdout pollution (Pitfall 1 — first-task stdout shim + self-test, stdio-only); deprecated SSE (Pitfall 2 — back `--sse` with streamable-HTTP); registry drift (Pitfall 3 — single registry, assert stdio==http==openapi==openai); MCP HTTP auth/CORS (localhost default, auth token, read/write tool separation).

### Phase Ordering Rationale

- **Payload before filters; sparse infra before hybrid mode; schedule columns before sensor; crawl-config/PDF before crawl-all; MCP last** — each is a hard code-level dependency, not a preference.
- Phases 7/8/9 are independent and can run as parallel workstreams; 10 gates on 7, 11 gates on 8, 12 gates on 8 + everything it wraps.
- Two phases (10, 11) carry live-data migrations and should get the most careful planning + explicit rollback (alias keep-old-collections; forward-only additive columns).

### Research Flags

Phases likely needing `--research-phase` during planning:
- **Phase 10 (Hybrid):** verify the exact `query_points` prefetch/`FusionQuery` API and `SparseVectorParams`/`Modifier.IDF` config against the installed qdrant-client 1.18 and confirm running Qdrant **server >=1.10**; validate the re-embedding reindex on a copy first.
- **Phase 12 (Agents):** confirm the exact `streamable_http_app()`/lifespan wiring against the installed `mcp` 1.28.x; nail the transport substitution and auth/CORS model before coding.

Phases with well-documented patterns (skip research-phase):
- **Phase 7 (Payload/filters):** established Qdrant payload-index idiom; pattern already demonstrated in-code for domain/document_type.
- **Phase 9 (Storage):** single-site `put_object`/key-builder change; forward-only.
- **Phase 8 (Crawl):** Crawl4AI primitives verified present; localized changes with existing seams.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Versions cross-checked against installed `.venv` + PyPI on 2026-07-08; Qdrant/Crawl4AI APIs confirmed by import. |
| Features | HIGH | MCP + hybrid grounded in current official docs; crawl/storage grounded in shipped v1.0 stack. |
| Architecture | HIGH | Every integration point cites a real shipped file/function via direct read. |
| Pitfalls | HIGH | Verified against MCP spec 2025-06-18/2025-11-25, Qdrant 1.10+ Query API docs, and v1.0 constraints. |

**Overall confidence:** HIGH

### Gaps to Address

- **MCP streamable-HTTP lifespan wiring** (MEDIUM in STACK/ARCH): confirm the exact `streamable_http_app()` + FastAPI lifespan API against installed `mcp` 1.28.x during Phase 12 planning; prefer standalone uvicorn to avoid the lifespan wiring unless single-port is a hard requirement.
- **Qdrant server version:** client 1.18 has the API, but Query API/IDF/sparse need **server >=1.10** — verify the running container version at startup before Phase 10.
- **Sparse encoder choice:** `fastembed` recommended over the present `rank_bm25` (owns corpus-IDF/vocab state); confirm the decision in Phase 10 discussion. miniCOIL/SPLADE are documented deferred upgrade paths.
- **crawl_config key mismatch:** config stores `rate_limit_rps`, resolver reads `rate_limit_seconds` — reconcile in Phase 8 (convert rps->seconds or add an rps tier).
- **Storage backfill:** forward-only is recommended for v2.0; a copy-forward backfill of old keys is deferred ops tooling only, needed only if uniform S3 lifecycle policies are later required.

## Sources

### Primary (HIGH confidence)
- Installed `.venv` introspection + direct reads of shipped v1.0 source (2026-07-08) — `pipeline/{search,index,ingest,crawl,export}.py`, `plugins/{protocols,builtin/qdrant_store}.py`, `storage/s3.py`, `crawl/ratelimit.py`, `cli/app.py`, `api/app.py`, `config/settings.py`, `dagster_defs/*`, `registry/*`, `domains/healthcare/sources.yaml`.
- PyPI JSON API (2026-07-08) — `mcp` 1.28.1, `fastembed` 0.8.0.
- MCP Transports spec revisions 2025-03-26 / 2025-06-18 / 2025-11-25 (HTTP+SSE deprecated -> Streamable HTTP).
- Qdrant 1.10 Universal Query API, IDF, sparse vectors, prefetch/RRF — official docs.

### Secondary (MEDIUM confidence)
- MCP best-practice writeups (Merge, Workato, The New Stack, philschmid, DEV) — tool naming, arg shape, pagination, curated toolsets.
- Dagster sensors docs — `run_key` idempotency, cursor persistence.
- AWS S3 object tagging limits vs MinIO parity.
- v1.0 research artifacts (`.planning/milestones/v1.0-research/*`).

---
*Research completed: 2026-07-08*
*Ready for roadmap: yes*
