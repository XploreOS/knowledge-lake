# Architecture Research — v2.0 Feature Integration

**Domain:** Knowledge Lake Framework (`klake`) — v2.0 "Agent-Ready Lake" integration into shipped v1.0
**Researched:** 2026-07-08
**Confidence:** HIGH (grounded in direct reads of the shipped v1.0 source, not inferred — every integration point cites a real file/function)

## Scope

This document answers: *how does each NEW v2.0 feature bolt onto the existing, shipped architecture?* For each feature: integration point, new-vs-modified components, data-flow changes, and migration/back-compat. It closes with a dependency-aware build order for the roadmapper.

It is **not** a from-scratch architecture (that lives in `v1.0-research/ARCHITECTURE.md`). The v1.0 layering is taken as fixed:

```
Typer CLI (cli/app.py)  ─┐
FastAPI (api/app.py)     ─┼─►  pipeline/*.py service functions  ─►  plugins (resolver-keyed)  ─►  Postgres registry + S3 + Qdrant
Dagster assets           ─┘        (ingest/parse/clean/chunk/            (parsers/crawlers/
  (dagster_defs/assets.py)          enrich/curate/index/search/           embedders/vectorstore/
                                    export/datasets)                      storage/discovery)
```

**The load-bearing invariant (D-02):** CLI, API, and Dagster are three thin adapters over the SAME `pipeline/*.py` functions. No adapter re-implements business logic. Every v2.0 feature MUST preserve this — new surfaces (MCP) wrap existing functions; new behavior lands in `pipeline/` or `plugins/`, never in an adapter.

## Standard Architecture (v2.0 target)

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                          ADAPTER LAYER (thin)                          │
│  ┌──────────┐  ┌──────────┐  ┌────────────────┐  ┌─────────────────┐  │
│  │ Typer CLI│  │ FastAPI  │  │  MCP server    │  │ Dagster assets  │  │
│  │  +crawl- │  │ +filters │  │  (NEW)         │  │ +recrawl sensor │  │
│  │  all,mcp,│  │ +openapi │  │  stdio + SSE   │  │  (NEW)          │  │
│  │  openapi │  │  export  │  │  11 tools      │  │                 │  │
│  └────┬─────┘  └────┬─────┘  └───────┬────────┘  └───────┬─────────┘  │
│       └─────────────┴───────┬────────┴───────────────────┘            │
├──────────────────────────────┼────────────────────────────────────────┤
│                    pipeline/*.py  SERVICE FUNCTIONS                     │
│  ingest  crawl  parse  clean  chunk  enrich  curate  index  search     │
│  export  datasets   crawl_all(NEW)   (all reused unchanged by MCP)     │
├──────────────────────────────┬─────────────────────────────────────────┤
│                       PLUGINS (resolver-keyed)                          │
│  parsers │ crawlers(+adaptive) │ embedders(+sparse) │ qdrant(+hybrid)  │
│                    │ storage (+domain keys +tags)                       │
├──────┬────────────┬───────────┬──────────────────────┬─────────────────┤
│ Postgres registry │  S3/MinIO  │      Qdrant          │   LiteLLM       │
│ (+crawl_schedule) │(+domain seg│(+sparse named vector)│                 │
│                   │ +obj tags) │                      │                 │
└───────────────────┴────────────┴──────────────────────┴─────────────────┘
```

Legend: `(NEW)` = net-new component; `+x` = additive change to an existing component.

### Component Responsibilities (v2.0 deltas only)

| Component | v2.0 responsibility change | New / Modified |
|-----------|----------------------------|----------------|
| `mcp/` package (NEW) | Expose 11 lake ops as MCP tools over stdio + SSE; each tool is a shim onto a `pipeline/` function | **New** |
| `pipeline/search.py` | Add `mode=hybrid\|dense\|sparse` + new filter kwargs; build sparse query vector | Modified (additive) |
| `pipeline/index.py` | Assemble expanded payload; upsert dense + sparse named vectors | Modified (additive) |
| `plugins/builtin/qdrant_store.py` | Named-vector collections (dense+sparse), RRF/prefetch hybrid query, sparse in copy/reindex | Modified (additive) |
| `plugins/protocols.py` | Extend `VectorStorePlugin.search` signature (mode, sparse); embedder gains sparse capability | Modified (additive) |
| `storage/s3.py` | Domain-segmented keys, object tags on every write, gold sub-zones | Modified |
| `pipeline/crawl.py` + `crawl/ratelimit.py` | Read `Source.config['crawl_config']`; adaptive backoff on 429/403; route PDF links to ingest | Modified |
| `pipeline/crawl_all.py` (NEW) | Batch driver over registered sources with `--domain` filter | **New** |
| `dagster_defs/sensors.py` (NEW) | Schedule-driven re-crawl sensor + content-hash change gate | **New** |
| Registry (`models.py`/migration) | `crawl_schedule`, `last_crawled_at`, `last_content_hash` on Source (or in `config`) | Modified (migration) |
| `cli/app.py` `openapi` cmd (NEW) | Dump `app.openapi()` + generate OpenAI tool defs from Pydantic | **New** |

## Feature-by-Feature Integration

### 1. MCP server (MCP-01/02, SKILL-01)

**Where it sits:** MCP is a **fourth adapter**, a *sibling* of CLI/FastAPI/Dagster — never above or below them. It calls `pipeline/*.py` functions directly (in-process), exactly as the CLI does. It does NOT proxy the FastAPI HTTP layer (that would add a network hop, a second serialization, and couple two adapters).

```
MCP tool  ──►  pipeline function  ──►  plugins/registry/storage
(thin shim)    (e.g. search(), crawl_source(), ingest_url())
```

**New components:**
- `knowledge_lake/mcp/__init__.py`, `server.py` (tool registry + transports), `tools.py` (11 tool definitions).
- New dependency: the official **`mcp` Python SDK** (FastMCP). It is NOT currently installed (verified — no `mcp`/`fastmcp` package in the venv). Pin it; it is the reference implementation and supports both stdio and SSE from one `FastMCP` instance.
- `klake mcp` Typer command in `cli/app.py` (stdio default; `--sse --port 3001` for SSE).

**One tool registry, two transports:** Define tools **once** with `@mcp.tool()` on a single `FastMCP` instance. Transport is a runtime choice at `mcp.run(transport="stdio")` vs `transport="sse")` — the tool set is transport-agnostic. Do NOT maintain two registries. `klake mcp` selects the transport from a flag.

**The 11 tools → existing functions (all pure shims, D-02):**

| MCP tool | Backing function (exists today) | Notes |
|----------|--------------------------------|-------|
| `search` | `pipeline.search.search()` | Add mode + filters (feature 2/4) |
| `ingest_url` | `pipeline.run.run_document(url=...)` | Full ingest→index path already wired by `cmd_ingest_url` |
| `crawl` | `pipeline.crawl.crawl_source()` | `async` — MCP tool can be async |
| `crawl_all` | `pipeline.crawl_all.crawl_all()` (NEW, feature 6) | Depends on feature 6 |
| `process_crawled` | Refactor `cmd_process_crawled` body → `pipeline.run.process_crawled()` | **Currently the loop lives in the CLI command** (cli/app.py:539) — extract it to `pipeline/` so MCP + CLI share it (D-02 fix) |
| `add_source` | `pipeline.ingest.register_source()` | Direct |
| `list_sources` | `registry.repo` list query (see `list_sources_endpoint`) | Extract shared helper into `pipeline`/`registry` |
| `lineage` | `lineage.resolve_ancestry()` | Direct |
| `export` | `pipeline.export.export_*()` | Direct (3 kinds) |
| `init_domain` | `api.app._register_domain_sources()` | **Already extracted** as a shared helper — reuse verbatim |
| `stats` | NEW small `registry.repo` aggregate query | Counts by artifact_type/source/domain |

**Data-flow change:** none to the pipeline. MCP adds an inbound edge only. Tool inputs/outputs should reuse the **same Pydantic schemas** as FastAPI (`api/schemas.py`) so shapes stay identical across surfaces (this also feeds feature 7).

**Refactors this forces (do them first):** two CLI-embedded behaviors must move down into `pipeline/` so MCP can reuse them without duplicating logic: `process_crawled` (cli/app.py:539–630) and the `list_sources` query (api/app.py:1097). This is the only structural debt MCP introduces.

**Claude Code skills (SKILL-01):** thin markdown/skill wrappers that call the MCP tools (build-corpus, search-knowledge, add-source, export-dataset). No code integration beyond the MCP server; they are packaging.

### 2. Sparse / hybrid search (RETR-01/02)

**The critical migration fact:** v1.0 collections use a **single unnamed dense vector** — `qdrant_store.py` calls `create_collection(vectors_config=VectorParams(size=dim, distance=Cosine))`. Qdrant cannot add a sparse vector to an existing unnamed-vector collection in place; sparse vectors live under `sparse_vectors_config`, and coexisting dense+sparse requires the dense vector to be **named**. Therefore:

> **Adding sparse REQUIRES recreating each collection with named-vector config and re-populating it. It is a reindex, not an ALTER.**

Good news: the **alias-swap reindex machinery already exists and is purpose-built for exactly this.** `qdrant_store.reindex(alias, dim, upsert_fn)` builds a new physical collection, populates via `upsert_fn`, and atomically repoints the alias (index.py:143 `reindex_collection`). Migration path:

1. Modify the create path (`ensure_aliased_collection`) to build **named** vectors: `vectors_config={"dense": VectorParams(size=dim, distance=Cosine)}` + `sparse_vectors_config={"sparse": SparseVectorParams()}`.
2. Migration = call `reindex()` per alias, but `upsert_fn` must **re-embed**: `copy_all_points` copies dense vectors but cannot synthesize sparse vectors for old points. The migration `upsert_fn` re-reads chunk text (registry/silver zone) and produces both vectors. A pure copy is insufficient for the sparse backfill.
3. Old physical collection retained (`keep_old_collections=True` default, settings.py:293) — instant rollback.

**Sparse vector generation — decision:** neither `fastembed` nor a SPLADE model is installed; **`rank_bm25` IS present**. Two options:
- **(Recommended) Add `fastembed`** and use Qdrant-native BM25/SPLADE sparse embeddings. Cleanest integration with `qdrant-client` 1.18 (which ships `qdrant_fastembed` support — verified present in the venv), keeps sparse-vector construction inside the vector-store plugin, and matches the tool-agnostic plugin ethos.
- **(Fallback) Compute sparse vectors from IDF/BM25 manually** via `rank_bm25` in a new embedder. Avoids a dependency but forces us to own corpus-IDF/vocabulary state (sparse vectors need a shared vocabulary) — more moving parts. Prefer only if adding `fastembed` is rejected.

**Plugin interface change (additive, non-breaking):**
- `VectorStorePlugin.search(collection, query, top_k, query_filter, *, mode="dense", sparse_query=None)` — new keyword-only params default to today's behavior. Nothing passes `mode` today → existing callers unaffected.
- Hybrid query uses Qdrant's `query_points` with `prefetch` (dense + sparse branches) and `FusionQuery(fusion=RRF)` — server-side RRF, no client fusion code, the 1.18-native path. Replaces any need for `rank_bm25` at query time.

**`pipeline/search.py` change:** add `mode` param; when sparse is needed, compute the sparse query vector and pass `sparse_query`; dense path unchanged. The existing filter-building block (search.py:84–92) is reused verbatim. `search()` gains `mode="dense"` default → **CLI/API/MCP callers unaffected until they opt in** (`klake search --mode hybrid`, `?mode=hybrid`).

**`pipeline/index.py` change:** produce sparse vectors alongside dense at upsert; `VectorPoint` gains an optional `sparse` field (dataclass default `None` → back-compat). `qdrant_store.upsert` writes both named vectors.

### 3. Domain-segmented S3 keys + tags + gold sub-zones (STORE-01/02/03)

**Current keys (storage/s3.py):**
- `put_raw`:    `raw/{source_id}/{sha256}.{ext}` (s3.py:219)
- `put_bronze`: `bronze/{source_id}/{sha256}.{ext}` (s3.py:323)
- gold: `export.py` writes under `gold/...`

**Target (STORE-01):** `{zone}/{domain}/{source_id}/{sha256}.{ext}`, with `_unclassified` when domain is absent.

**Coexistence with content-addressing + WORM + lineage — all preserved:**
- The **SHA256 is still in the key**, so identity==content and overwrite is still structurally impossible. Domain is a *prefix* segment, not part of identity.
- **Lineage is unaffected:** ancestry traces via `parent_artifact_id` + `Artifact.storage_uri` in the registry, NOT via key structure. The recursive-CTE ancestry walk never parses keys. The key shape can change freely as long as the registry records the actual URI.
- **WORM unaffected:** bucket-level versioning/object-lock/delete-deny is prefix-independent.
- **The one subtlety:** the same content hash under two domains would produce two different keys. The registry no-op (`get_artifact_by_hash`) fires BEFORE key construction (s3.py:209/313), so identical content is still a single artifact — it keeps whatever domain it was first written under. This is correct and must be preserved: **domain is resolved, but the hash no-op still short-circuits first.** Call this ordering out explicitly in the plan.

**Where domain comes from at write time:** `Source.config['domain']` (already populated by `klake init` and `register_source`). `put_raw`/`put_bronze` receive `source_id` today; add the domain — pass it in from the caller, or look it up via `registry.repo.get_domain_for_source(session, source_id)` which **already exists** (repo.py:820). Prefer passing it in to avoid an extra hot-path query; fall back to the lookup.

**Object tags (STORE-02):** `put_object` currently calls `put_object(Bucket, Key, Body)` with no `Tagging` (s3.py:81). Add a `tags: dict` param and pass `Tagging=urlencode(tags)` (S3 and MinIO both support object tagging). Tags: `domain, source_name, format, artifact_type`. Single-site change in `storage/s3.py`, threaded through `put_raw`/`put_bronze` and the gold writers. Additive.

**Gold sub-zones (STORE-03):** `export.py` gold writers get sub-prefixes `gold/{domain}/rag_corpus|pretrain|finetune/...`. `ExportSettings.gold_prefix` already exists (settings.py:246) — extend the key builders in `pipeline/export.py`. The three export kinds already map cleanly to the three sub-zones (`cmd_export` kinds rag-corpus/pretrain/finetune).

**Migration story:** existing objects live at the old flat keys. Options, in preference order:
1. **Forward-only (recommended):** new writes use the new scheme; old objects stay put; the registry's `storage_uri` already points at the real location so reads never break. No data movement, zero risk to WORM/immutability. Segmentation applies to net-new ingestion.
2. **Backfill copy (optional, later):** a one-off job copies old→new keys and updates `Artifact.storage_uri`. Because raw is WORM/immutable, this is a copy (not move) and must update the registry transactionally. Only needed if a uniform layout is required for S3 lifecycle policies — not for v2.0 functionality.

Recommend option 1 for v2.0; note option 2 as deferred ops tooling.

### 4. Expanded chunk payload + filters (PAYLOAD-01/02)

The **most self-contained, lowest-risk** feature — and **foundational for feature 2's filtering value**.

**Payload assembly point:** `pipeline/index.py` lines 106–133 build the `payload` dict per chunk. v1.0 already joins enrichment once per `index()` call (domain via `get_domain_for_source`; document_type/keywords/quality_score via `get_enriched_artifact_for_parsed`). PAYLOAD-01 adds `source_id, source_name, source_url, format, title, organization, tags` to that same dict. Source-level fields come from the `Source` row (fetch once per `index()` call alongside the existing `get_domain_for_source` — same session, negligible cost). `title`/`organization` come from enrichment metadata already fetched. `tags` come from `Source.config['tags']` (populated by `klake init`). **Purely additive** — existing payload keys unchanged, existing search results keep working.

**Filter build point:** `pipeline/search.py` lines 84–92 build the Qdrant `Filter.must` list. PAYLOAD-02 adds `source_name, format, tags, source_id` conditions with the same `FieldCondition`/`MatchValue` idiom (tags → `MatchAny`). The function already demonstrates the exact pattern for `domain`/`document_type`. Add matching optional kwargs to `search()`, then thread them through the three adapters (CLI options, API query params, MCP tool args) — each a mechanical mirror of the existing `--domain`/`domain=` wiring (cli/app.py:640, api/app.py:165).

**Back-compat:** every new kwarg defaults to `None` → no-filter behavior identical to today. New payload fields exist only on newly-indexed points; **old points lack them** → filtering on a new field excludes old points. If that matters, a `reindex_collection` re-populates payloads. Note this coupling in the plan: *filters are only fully effective on points indexed after PAYLOAD-01, or after a reindex.*

### 5. Dagster re-crawl sensor + content-hash change detection (SCHED-01/02)

**New component:** `dagster_defs/sensors.py` with a `@sensor`, registered via `Definitions(sensors=[...])` in `definitions.py` (currently assets + one job + resources).

**How the sensor drives crawl:** on each tick the sensor queries the registry for sources whose `crawl_schedule` is due (`now − last_crawled_at ≥ interval`) and yields a `RunRequest` per due source. Reuse `crawl_source()` — wrap it as a thin `crawl` asset/job (crawl is CLI/API-triggered today, not a Dagster asset), mirroring how `ingest_raw_document` wraps `ingest_*`.

**Schema change:** Source has no schedule/timestamp/hash columns (verified — Source is id/name/source_type/url/normalized_url/license/robots_checked/config/created_at only). Two options:
- Store schedule + timestamps in `Source.config` JSONB (no migration, but the sensor scans+filters in Python — fine at 28-source scale, weak at 10k).
- **(Recommended) Add columns** `crawl_schedule TEXT`, `last_crawled_at TIMESTAMPTZ`, `last_content_hash TEXT` via a new Alembic migration (`0009`, continuing the 0001–0008 chain). Enables an indexed "due sources" query — the clean long-term shape.

**Where "skip unchanged" lives (SCHED-02):** two complementary layers, both partly present:
- **Artifact layer (already works):** `put_raw` computes SHA256 and no-ops if the hash exists (s3.py:206–216). Re-crawling an unchanged page already avoids a duplicate raw artifact and all downstream reprocessing — content-hash dedup is intrinsic.
- **Source/sensor layer (new):** to skip the *fetch* entirely (not just the write), compare a freshly-fetched page hash against `Source.last_content_hash` (or per-URL `CrawlState`) and short-circuit. Put this in `pipeline/crawl.py` (it already computes per-URL state and has the hash via `put_raw`). Registry = source of truth for "last seen hash" (queryable by the sensor); storage's hash no-op remains the write-level guard.

**Data-flow change:** adds a scheduled inbound trigger. Sensor → RunRequest → crawl asset → `crawl_source()` → existing raw/bronze writes. The crawl pipeline itself is unchanged.

### 6. Crawl config + crawl-all + adaptive rate limiting + PDF-from-crawl (CRAWL-01/02/03, INGEST-01)

**CRAWL-01 (per-source crawl_config):** the config is **already stored** — `klake init` writes `Source.config['crawl_config'] = {depth, rate_limit_rps, robots_txt}` (cli/app.py:1013; sources.yaml confirms the shape). But `crawl_source` **ignores it**: crawl.py:296 hard-codes `source_config = None` before `resolve_delay`. Integration = load `Source.config['crawl_config']` at crawl start and (a) pass it as `source_config` to `resolve_delay` (the three-tier resolver already honors `source_config['rate_limit_seconds']` — **note the key mismatch:** config stores `rate_limit_rps`, resolver reads `rate_limit_seconds`; reconcile by converting rps→seconds or adding an rps tier), and (b) use `crawl_config['depth']` as the `max_depth`/`max_pages` override. Localized change in `pipeline/crawl.py` + `crawl/ratelimit.py`.

**CRAWL-02 (`klake crawl-all`):** new `pipeline/crawl_all.py` querying registered crawl-type sources (optionally filtered by `Source.config['domain'] == --domain`), looping `crawl_source()` per source. Resume-safety is already built in (`_find_or_create_job` reuses incomplete jobs, crawl.py:142). New thin `cmd_crawl_all` CLI command + an MCP `crawl_all` tool both call it. No change to `crawl_source` itself.

**CRAWL-03 (adaptive rate limiting):** `PerHostLimiter` (ratelimit.py) tracks last-fetch per host but has **no backoff on 429/403**. Extend it: on a 429/403 (surfaced from the crawler adapter via `CrawlPageResult`), multiply the per-host delay (exponential) and set a per-host cooldown that `wait()` respects. State is per-host in the existing `_last_fetch` dict → add a parallel `_cooldown_until`/`_penalty` dict. The crawl loop already branches on result status (crawl.py:300–322); add a `rate_limited` branch feeding the limiter. Localized to `crawl/ratelimit.py` + the loop.

**INGEST-01 (PDF-from-crawl):** `_extract_links` (crawl.py:360) follows in-domain links and does NOT skip `.pdf` (it skips images/css/js/media only). But those links are handed to the crawler adapter's `fetch_page`, which yields HTML/markdown — wrong for a PDF. Integration: in the crawl loop, when a queued link is a document type (`.pdf`, `.docx`, …), route it to **`pipeline.ingest.ingest_url()`** (proper `raw_document` with correct MIME, SSRF guard, size cap, content-hash dedup — all already implemented) instead of the HTML crawler path. The branch point is the loop's per-URL dispatch; keep same-domain + robots checks before dispatch. PDF links then become first-class raw artifacts that `process_crawled` parses.

**ENRICH-01 (partial-JSON recovery):** localized to `pipeline/enrich.py` — salvage a truncated LLM JSON response (repair/parse-partial) before falling back to skip. Independent of every other feature; no cross-component integration.

### 7. OpenAPI / OpenAI tool-def generation (SKILL-02/03)

**OpenAPI (SKILL-02) — runtime-derived, build-time-emitted:** FastAPI already generates the spec (`app.openapi()`); `/docs` works today. New `klake openapi` command imports `knowledge_lake.api.app:app`, calls `app.openapi()`, writes `docs/openapi.json`. Pure derivation — no hand-maintained spec. Run in CI to keep it fresh. Zero pipeline impact.

**OpenAI tool defs (SKILL-03) — derived from Pydantic:** the request schemas in `api/schemas.py` already define every operation's input shape. Emit OpenAI function-tool JSON as `{name, description, parameters: <Model>.model_json_schema()}` per operation, at build time (`klake openapi --openai-tools` → static `docs/openai_tools.json`). This is exactly why feature 1 should reuse `api/schemas.py` for MCP tool I/O — **one schema set feeds MCP tools, OpenAPI, and OpenAI tool defs.** Keep a single mapping table (operation → Pydantic request model → backing pipeline fn) as the shared source for MCP registration AND tool-def generation, so the three agent surfaces never drift.

## Data Flow — What Changes

1. **Search (dense→hybrid):** `search(mode=hybrid)` → embed dense query + build sparse query → `qdrant.search` issues one `query_points` with dense+sparse `prefetch` + RRF fusion → hits. Filters (feature 4) apply identically in all modes.
2. **Index (dense→dense+sparse+rich payload):** `index()` joins Source + enrichment (already done) → builds expanded payload → produces dense **and** sparse vectors → `upsert` writes both named vectors.
3. **Ingest write (flat→domain-segmented+tagged):** caller resolves domain from `Source.config` → `put_raw/put_bronze` write `{zone}/{domain}/{source_id}/{hash}.{ext}` with object tags → registry records the real `storage_uri` (lineage unaffected).
4. **Scheduled crawl (new inbound trigger):** sensor tick → due-source query → RunRequest → crawl asset → `crawl_source()` → hash-gated writes.
5. **Agent access (new inbound surface):** MCP tool call → pipeline function → same registry/storage/Qdrant path as CLI.

## Anti-Patterns to Avoid

### Anti-Pattern 1: MCP re-implementing or HTTP-proxying pipeline logic
**Mistake:** MCP tools call the FastAPI endpoints over HTTP, or re-code the crawl/search flow. **Why wrong:** double serialization, a network hop, two divergent code paths — violates D-02. **Instead:** MCP tools are in-process shims onto `pipeline/*.py`, sharing `api/schemas.py` shapes.

### Anti-Pattern 2: Trying to ALTER an unnamed-vector collection to add sparse
**Mistake:** attempting an in-place add of a sparse vector to existing `klake_chunks`. **Why wrong:** Qdrant requires named vectors for dense+sparse coexistence; there is no in-place migration. **Instead:** use the existing `reindex()` alias-swap with a **re-embedding** `upsert_fn` (copy alone can't synthesize sparse vectors for old points).

### Anti-Pattern 3: Encoding domain into content-hash identity
**Mistake:** folding domain into the hash, or dropping the registry no-op so "same doc in two domains" makes two artifacts. **Why wrong:** breaks content-addressed dedup and WORM guarantees. **Instead:** domain is a key *prefix* only; the `get_artifact_by_hash` no-op still short-circuits before key construction.

### Anti-Pattern 4: Making new search filters or payload fields required
**Mistake:** required kwargs / non-defaulted `VectorPoint.sparse` / mandatory `mode`. **Why wrong:** breaks the many existing callers and old indexed points. **Instead:** every addition defaults to today's behavior (`mode="dense"`, filters `None`, `sparse=None`).

### Anti-Pattern 5: Putting new behavior in the CLI/API adapter
**Mistake:** implementing `crawl_all`/`process_crawled`/`stats` inside a Typer command (as `process_crawled` is today). **Why wrong:** MCP/Dagster can't reuse it → duplication. **Instead:** land logic in `pipeline/`, adapters stay thin.

## Integration Points Summary

| Feature | Primary file(s) to modify | New file(s) | Migration? |
|---------|---------------------------|-------------|------------|
| MCP server | `cli/app.py` (+`mcp` cmd) | `mcp/server.py`, `mcp/tools.py`; extract `pipeline/run.process_crawled`, `registry` list/stats helpers | No (new dep: `mcp` SDK) |
| Sparse/hybrid | `plugins/builtin/qdrant_store.py`, `pipeline/index.py`, `pipeline/search.py`, `plugins/protocols.py` | maybe `plugins/builtin/sparse_embedder.py` | **Qdrant reindex (re-embed)**; new dep `fastembed` (recommended) |
| Domain S3 keys + tags | `storage/s3.py`, `pipeline/export.py` | — | Forward-only (backfill deferred) |
| Payload + filters | `pipeline/index.py`, `pipeline/search.py`, `cli/app.py`, `api/app.py`, `api/schemas.py` | — | Reindex to backfill old points (optional) |
| Re-crawl sensor + hash | `dagster_defs/definitions.py`, `pipeline/crawl.py`, `registry/models.py` | `dagster_defs/sensors.py`, Alembic `0009_source_crawl_schedule` | **Yes (Source columns)** |
| Crawl config/all/adaptive/PDF | `pipeline/crawl.py`, `crawl/ratelimit.py`, `cli/app.py`, `pipeline/enrich.py` | `pipeline/crawl_all.py` | No |
| OpenAPI/OpenAI tools | `cli/app.py` (+`openapi` cmd), `api/schemas.py` | `docs/openapi.json`, `docs/openai_tools.json` (generated) | No |

## Dependency-Aware Build Order

Ordering is driven by real coupling found in the code, not theme grouping:

```
Phase A — Metadata foundation (no new deps, lowest risk)
  1. PAYLOAD-01  Expanded chunk payload (index.py join point)          ← foundational
  2. PAYLOAD-02  Search filters (search.py filter builder)             ← needs payload fields to filter on
     Rationale: filters are worthless without the payload fields; payload lands first.

Phase B — Crawl maturation (independent of A; unblocks crawl-all + sensor)
  3. CRAWL-01    Wire Source.config['crawl_config'] into crawl_source  ← fixes source_config=None
  4. CRAWL-03    Adaptive rate limiting (PerHostLimiter backoff)
  5. INGEST-01   PDF-from-crawl routing to ingest_url
  6. CRAWL-02    crawl-all batch driver (pipeline/crawl_all.py)        ← builds on 3–5
  7. ENRICH-01   Partial-JSON recovery (localized to enrich.py; independent)

Phase C — Storage segmentation (independent; touches write path)
  8. STORE-01    Domain-segmented keys (needs domain at write time)
  9. STORE-02    Object tags on every write (same put_object change site as 8)
 10. STORE-03    Gold sub-zones (export.py key builders)
     Rationale: 8 and 9 are the same storage.s3 change; do together. Forward-only, no migration.

Phase D — Hybrid retrieval (highest technical risk; needs reindex machinery)
 11. RETR-01    Sparse named vector: named-vector collections + re-embed reindex + fastembed
 12. RETR-02    mode=hybrid|dense|sparse in search() + RRF query
     Rationale: sparse infra (named collections, migration) must exist before hybrid query mode.
     Depends on Phase A payload (filters must work in hybrid mode too).

Phase E — Scheduling (needs a runnable crawl trigger + registry columns)
 13. SCHED-schema  Alembic migration: Source.crawl_schedule/last_crawled_at/last_content_hash
 14. SCHED-02      Content-hash change gate in crawl.py (registry-backed)
 15. SCHED-01      Dagster re-crawl sensor + crawl asset
     Rationale: sensor needs the schedule columns and a crawl asset to target; hash gate needs the column.

Phase F — Agent surfaces (LAST — wrap stabilized functions)
 16. Refactor: extract process_crawled + list_sources/stats into pipeline/registry
 17. SKILL-02   klake openapi (app.openapi() dump)
 18. SKILL-03   OpenAI tool defs from Pydantic (shared schema/mapping table)
 19. MCP-01/02  MCP server (stdio+SSE), klake mcp — maps 11 tools to now-stable functions
 20. SKILL-01   Claude Code skills over the MCP tools
     Rationale (explicit): MCP comes AFTER CLI/API stabilize and after crawl_all (tool #4)
     and process_crawled extraction exist — otherwise the 11-tool mapping targets moving/duplicated code.
```

**Why this order (the load-bearing dependencies):**
- **Payload before filters** — a filter can only match a field the payload carries.
- **Crawl-config/adaptive/PDF before crawl-all** — crawl-all is a loop over a single-source crawl that must already honor per-source config and route PDFs.
- **Sparse infra before hybrid mode** — hybrid `query_points` needs named dense+sparse collections to exist (the reindex migration is the gate).
- **Schedule columns before the sensor** — the sensor's "due sources" query and the hash gate both read new Source columns.
- **MCP last** — it is a thin wrapper; wrapping functions still being reshaped (crawl_all added, process_crawled/list_sources extracted) would churn the tool registry. Stabilize the service layer, then expose it.

Phases A/B/C are mutually independent and can parallelize across workstreams; D depends on A; E depends on B; F depends on B (crawl_all) plus everything it wraps.

## Sources

- Direct reads of shipped v1.0 source (2026-07-08): `pipeline/{search,index,ingest,crawl,export}.py`, `plugins/{protocols,builtin/qdrant_store}.py`, `storage/s3.py`, `crawl/ratelimit.py`, `cli/app.py`, `api/app.py`, `config/settings.py`, `dagster_defs/{assets,definitions}.py`, `registry/{models,repo}.py`, `domains/healthcare/sources.yaml` — HIGH confidence (primary artifacts).
- Dependency probe: `mcp`/`fastembed` absent, `rank_bm25` present, `qdrant-client` 1.18 with `qdrant_fastembed` present — HIGH confidence (venv inspection).
- v1.0 architecture research: `.planning/milestones/v1.0-research/ARCHITECTURE.md` (pattern continuity) — MEDIUM confidence (prior research doc).
- Qdrant named-vector / sparse-vector / RRF-fusion model and MCP dual-transport pattern — MEDIUM confidence (established product behavior; verify the exact `query_points` prefetch/`FusionQuery` API against qdrant-client 1.18 during Phase D planning).

---
*Architecture research for: Knowledge Lake Framework v2.0 feature integration*
*Researched: 2026-07-08*
