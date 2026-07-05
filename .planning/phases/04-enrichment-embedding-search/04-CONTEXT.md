# Phase 4: Enrichment, Embedding & Search - Context

**Gathered:** 2026-07-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 4 turns cleaned documents into enriched, embedded, and semantically searchable knowledge. Deterministic extraction (title, dates, headings — already available from Phase 3's `ParsedDoc`/`Section` metadata) runs before any LLM call. LLM enrichment (via LiteLLM task aliases only) adds summary, document type, organization, jurisdiction, keywords, entities, and a quality score — cached by prompt version + input hash, and budget-capped so cost cannot explode. Embeddings remain provider-configurable (local sentence-transformers ↔ LiteLLM), and chunks are indexed into Qdrant with citation + enrichment payload, behind aliased collections so a full reindex never causes search downtime.

Requirements: ENRICH-01 through ENRICH-06, INDEX-01 through INDEX-03.

**Note:** This phase widens work that already exists as a thin spike from Phase 1 (`pipeline/embed.py`, `pipeline/index.py`, `pipeline/search.py`, `LiteLLMEmbedder`, `QdrantVectorStore`) — it is not greenfield. The enrichment half (LLM metadata extraction, caching, budget caps) is entirely new.

</domain>

<decisions>
## Implementation Decisions

### Enrichment pipeline shape
- **D-01 (auto-selected):** Enrichment produces a **new `artifact_type='enriched_document'`** row — parent is the `cleaned_document` artifact (the actual text the LLM reads), not `parsed_document`. This follows the established registry-first, every-transformation-is-a-node pattern (FOUND-06/07) rather than decorating an existing artifact's metadata in place. It runs as a branch parallel to `chunk_document` (both descend from `clean_document`) — chunking does not block on enrichment, and vice versa.
- Enrichment fields (title, summary, document_type, organization, jurisdiction, keywords, entities) live in the existing `metadata_` JSON column rather than new dedicated columns — they're a variable, document-shaped bundle, consistent with how Phase 3 already stores `language`/`dedup_status` in `metadata_` (see Specifics note below on the quality_score/language column discrepancy).
- The `quality_score` concept for `enriched_document` rows is a **distinct LLM-judged metric** from Phase 3's parse-quality heuristic — no collision risk since each Artifact row is scoped to its own `artifact_type`.

### Deterministic-first extraction (ENRICH-02)
- **D-02 (auto-selected):** The deterministic pass reuses **already-computed data** — title from `ParsedDoc.metadata`/first heading, dates via regex over the cleaned text, headings from the existing `Section` list — rather than re-parsing. These deterministic fields are passed to the LLM call as context/hints (not re-derived by the model); the LLM is only asked to produce the judgment fields it's actually needed for: summary, document type, organization, jurisdiction, keywords, entities, quality score.

### LLM extraction strategy & model assignment (ENRICH-01, ENRICH-03)
- **D-03 (auto-selected):** **One structured-output call per document** requesting all judgment fields as JSON (not N separate calls per field) — minimizes cost/latency and keeps caching simple (one cache entry per document per prompt version). Uses **`cheap_model`** (extraction/classification-style task, matches the alias's stated purpose in `infra/litellm/config.yaml`). `strong_model`/`eval_model` stay reserved for heavier synthesis and evaluation work (Phase 5 dataset generation, Phase 3's existing quality-gray-zone spot-check). Calls go through plain `litellm.completion()` with `api_base=settings.litellm_url` — same direct-call pattern as `LiteLLMEmbedder`, never a provider SDK.

### Caching (ENRICH-04)
- **D-04 (auto-selected):** Cache key = **hash of (cleaned-document content_hash + prompt_version)**, reusing the existing `UNIQUE(content_hash, artifact_type)` constraint already on `Artifact` — no new cache table. Before calling the LLM, check for an existing `enriched_document` artifact whose synthetic content_hash matches; if found, it's a no-op (re-running enrichment on unchanged content + unchanged prompt is free), mirroring the exact-dedup pattern `parse()`/`clean()` already use.

### Budget enforcement (ENRICH-05)
- **D-05 (auto-selected):** Track spend using **LiteLLM's own cost accounting** (`completion_cost()` / response hidden params) rather than reimplementing per-model pricing tables. Accumulate spend in Postgres against a configurable cap (new `EnrichSettings.budget_usd`). When the cap is hit, halt **gracefully**: stop starting new enrichment calls in the current job, mark remaining documents `skipped_budget_exceeded`, and return partial results with a clear status — never raise/crash mid-job.
  - **Flagged for research:** STATE.md already notes LiteLLM budget-enforcement behavior under burst load is unverified — this is the researcher's top priority for this decision.

### Qdrant collection aliasing (INDEX-02)
- **D-06 (auto-selected):** Use **versioned physical collections** (`klake_chunks_v1`, `klake_chunks_v2`, ...) behind a stable **alias** (`klake_chunks`) that all app code reads/writes through — Qdrant's native alias feature, tracked in the registry so the current alias→collection mapping is queryable. Reindex = create new versioned collection → bulk upsert → atomically repoint alias → retain old collection until confirmed, then drop. The existing `collection: str = "klake_chunks"` parameter in `embed()`/`index()`/`search()` keeps its name; only the resolution layer underneath changes.
  - **Flagged for research:** STATE.md already notes Qdrant collection-aliasing patterns need research — pair with `qdrant-client` 1.18's alias API.

### Qdrant payload metadata scope (INDEX-01, INDEX-03)
- **D-07 (auto-selected):** Extend the `VectorPoint`/`Hit` payload beyond the current citation fields (`document`, `section_path`, `page`, `chunk_id`, `text`) to add **domain, document_type, keywords/tags, quality_score** — sourced from the sibling `enriched_document` artifact at index time. If enrichment hasn't run yet for a document, indexing proceeds with citation-only payload (enrichment is not a hard blocker for indexing — the two stages stay decoupled per D-01).

### Embedding provider default (ENRICH-06 continuation)
- **D-08 (auto-selected):** Keep **`local`** (sentence-transformers) as the Phase 4 default — same zero-credential rationale as Phase 1's D-13. The LiteLLM embedding path remains a pure config switch; Phase 4 doesn't flip the default just because bulk documents are now flowing, since that would add embedding-cost/budget complexity this phase doesn't need. Bedrock embeddings become more relevant once the healthcare pack (Phase 6) wants higher-quality vectors.

### Claude's Discretion
- Exact JSON schema/field names for the structured LLM enrichment output — Claude decides based on LiteLLM structured-output support.
- Whether extracted entities are a flat string list or typed `(entity, type)` pairs — Claude decides for MVP; a healthcare-specific taxonomy is explicitly a Phase 6 (DOMAIN-03) concern, not this phase's.
- Whether `document_type` (or any other enrichment field) warrants a dedicated indexed Postgres column vs staying in `metadata_` JSON — Claude/planner decides based on the filtering/query patterns INDEX-01 actually needs.
- Retry/backoff behavior for transient LiteLLM failures — reuse the existing `tenacity` pattern from `pipeline/ingest.py`.
- Budget cap granularity (global vs per-job vs per-source) — Claude decides for MVP; a single global default is acceptable.
- CLI/API command naming for enrich/reindex/filtered-search — Claude decides, consistent with existing `klake parse/clean/chunk` naming.
- Dagster asset wiring for `enrich_document` (parallel branch off `clean_document`) and the reindex job — Claude decides.
- Whether low `quality_score` enrichment results gate search visibility now or wait for Phase 5's composite curation scoring (CURATE-03) — Claude decides; deferring to Phase 5 is the safer default.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project planning docs
- `.planning/PROJECT.md` — Constraints table (LLM-gateway-only, deterministic-first, task-based aliases, no hardcoded provider IDs), Key Decisions (plugin architecture, LiteLLMEmbedder pattern validated Phase 1)
- `.planning/REQUIREMENTS.md` — ENRICH-01..06, INDEX-01..03 definitions this phase must satisfy
- `.planning/ROADMAP.md` — Phase 4 goal and 5 success criteria (the scope anchor)
- `.planning/STATE.md` — Phase 4 blockers/concerns already flagged: "LiteLLM budget enforcement behavior under burst load unverified" and "Qdrant collection aliasing patterns need research" (directly map to D-05, D-06)

### Prior phase context (decisions that carry forward)
- `.planning/phases/01-foundation-end-to-end-spike/01-CONTEXT.md` — D-12 (LiteLLM dev alias mapping: cheap/strong/eval/embedding_model), D-13 (local embedder default, zero AWS creds), D-14 (lineage tree rendering)
- `.planning/phases/03-parse-clean-chunk/03-CONTEXT.md` — D-04 (heuristics + optional LLM spot-check quality-scoring pattern — the template to mirror for enrichment's quality_score)

### Existing implementation (extend, don't rewrite)
- `src/knowledge_lake/plugins/protocols.py` — `EmbedderPlugin`, `VectorStorePlugin` protocols; enrichment itself does NOT need a new swappable-plugin protocol — LiteLLM is already the single gateway/swap point for model calls
- `src/knowledge_lake/plugins/builtin/st_embedder.py` — `LiteLLMEmbedder` — the exact pattern to follow for the enrichment LLM call (direct `litellm.*()` call, task alias only, `api_base` injected from Settings, no provider SDK, wraps errors in `RuntimeError`)
- `src/knowledge_lake/pipeline/embed.py`, `pipeline/index.py`, `pipeline/search.py` — existing Phase 1 spike versions to extend (index.py needs alias resolution + enrichment payload fields; search.py needs payload filter params)
- `src/knowledge_lake/plugins/builtin/qdrant_store.py` — `QdrantVectorStore.ensure_collection/upsert/search` — extend for alias-based collection resolution rather than replace
- `src/knowledge_lake/registry/models.py` — `Artifact` model (`artifact_type` discriminator pattern, `metadata_` JSON column, `UNIQUE(content_hash, artifact_type)` constraint to reuse for caching)
- `src/knowledge_lake/registry/repo.py` — `create_*_document()` functions (parsed/cleaned/chunk patterns, lines ~148-373) — mirror for a new `create_enriched_document()`
- `src/knowledge_lake/config/settings.py` — `ParseSettings`/`CleanSettings`/`ChunkSettings` nested-model pattern to follow for new `EnrichSettings` (budget_usd, prompt_version, cache toggle) and an index/vectorstore alias config
- `src/knowledge_lake/dagster_defs/assets.py` — asset chain to extend with `enrich_document` (parallel to `chunk_document`, both depend on `clean_document`) and a new reindex asset/job
- `infra/litellm/config.yaml` — existing `cheap_model`/`strong_model`/`eval_model`/`embedding_model` alias mappings (D-12) — enrichment must use these aliases only, never a hardcoded Bedrock model ID

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `LiteLLMEmbedder` (`plugins/builtin/st_embedder.py`) — direct `litellm` call pattern (api_base injection, no provider SDK, dimension/error validation) — template for the new enrichment call helper
- `clean()`/`chunk()` (`pipeline/clean.py`, `pipeline/chunk.py`) — registry-write + lineage-event pattern for a new pipeline stage; both currently parent off `parsed_document` (not `cleaned_document`) — enrichment should parent off `cleaned_document` instead since it's the actual text consumed (see D-01)
- `QdrantVectorStore` — collection/upsert/search already implemented; needs an alias-resolution layer, not a rewrite
- Existing `collection: str = "klake_chunks"` parameter threaded through `embed()`/`index()`/`search()`/Dagster assets — keep as the alias name

### Established Patterns
- Plugin Protocol + entry-point resolution for swappable tools (embedder, parser, vectorstore, crawler, discovery) — NOT needed for enrichment itself; LiteLLM is already the swap point for model calls
- Settings: nested `BaseModel` per pipeline stage (`ParseSettings`, `CleanSettings`, `ChunkSettings`) under `KLAKE_<STAGE>__*` env vars — follow for `EnrichSettings`
- Registry-first writes: every stage creates `Artifact` + `LineageEvent` rows in the same session
- Content-hash dedup via `UNIQUE(content_hash, artifact_type)` — the mechanism to reuse for ENRICH-04 caching (synthetic hash of cleaned-content-hash + prompt_version)

### Integration Points
- New Alembic migration only if a specific enrichment field needs a dedicated indexed column (planner's call — default is `metadata_` JSON, per D-01/Discretion)
- New settings: `EnrichSettings` (budget_usd, prompt_version, cache toggle), collection-alias config extension
- CLI expansion: `klake enrich`, `klake reindex` (or extend `klake index`) commands
- API expansion: enrich trigger endpoint; search filter params (domain, document_type, quality_score)
- Dagster: `enrich_document` asset (parallel branch off `clean_document`), reindex job/asset

</code_context>

<specifics>
## Specific Ideas

- **Discrepancy found and worth resolving at planning time:** Alembic migration `0006_parse_clean_chunk_columns.py` added dedicated `quality_score` (FLOAT), `language` (VARCHAR), and `dedup_status` (VARCHAR) columns to `artifacts` — but `registry/models.py`'s `Artifact` class never declares them as `Mapped` columns, and `pipeline/clean.py`/`pipeline/parse.py` actually write this data into the `metadata_` JSON dict instead (e.g. `metadata={"quality_score": ..., "parser_used": ...}`). The real DB columns from migration 0006 appear to be dead/unused. Phase 4 adds its own enrichment `quality_score` — planner should explicitly decide whether to (a) finally wire up the existing dedicated columns, (b) keep everything in `metadata_` JSON and treat the 0006 columns as legacy/unused, or (c) drop the unused columns. Don't silently perpetuate the split without a decision.
- STATE.md's two Phase 4 blockers ("LiteLLM budget enforcement under burst load unverified", "Qdrant collection aliasing patterns need research") map directly onto D-05 and D-06 — these should be the researcher's top priorities, not open-ended exploration.
- The existing search response shape (citation-only: document, section_path, page, chunk_id, text, score) must stay backward compatible — Phase 4 additions (domain/document_type/quality_score filters and payload fields) are additive, not breaking.

</specifics>

<deferred>
## Deferred Ideas

- Healthcare-specific entity taxonomy and enrichment prompts — explicitly Phase 6 (DOMAIN-03), not decided here.
- Composite quality scoring across documents/sources (CURATE-03) — Phase 5 territory; Phase 4's enrichment quality_score is a single-document LLM judgment, not the corpus-wide composite score.

</deferred>

---

*Phase: 4-Enrichment, Embedding & Search*
*Context gathered: 2026-07-05*
