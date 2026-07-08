# Phase 7: Metadata Foundation - Context

**Gathered:** 2026-07-08
**Status:** Ready for planning
**Mode:** `--auto` (gray areas auto-selected, recommended defaults chosen without prompts — every decision below is auditable and revisable before planning)

<domain>
## Phase Boundary

Deliver **searchable, filterable source metadata** on every indexed chunk. Two requirements:

- **PAYLOAD-01** — every newly indexed chunk carries `source_id`, `source_name`, `source_url`, `format`, `tags`, `title`, `organization` in its Qdrant payload, assembled at the index-time enrichment join, backward-compatible with existing points.
- **PAYLOAD-02** — a user can filter search by `source_name`, `format`, `tags` (array-contains), and `source_id` from both CLI and REST API, backed by Qdrant keyword payload indexes on each filterable field (no full-collection scans).

**In scope:** payload assembly (`index.py`), filter building (`search.py`), payload-index creation (`qdrant_store.py`), the minimal registry change needed to make `tags` available, and the CLI/API surface for the four new filters.

**Out of scope (own phases):** sparse/hybrid vectors and RRF (Phase 10 — RETR-01/03), any storage-key or object-tag change (Phase 9 — STORE-01/02/03), crawl-config wiring (Phase 8). This phase is dense-search payload + filters only.
</domain>

<decisions>
## Implementation Decisions

### Field provenance — where each of the 7 payload fields comes from
- **D-01:** Resolve all source-derived fields in the **single `get_session()` block already present in `index.py` (lines ~90–104)**, once per `index()` call — not once per chunk. Extend it to also fetch the `Source` row (today it only calls `get_domain_for_source`). Mirrors the existing domain/enrichment join pattern.
- **D-02:** Field → source mapping:
  | Payload field | Source | Fallback |
  |---|---|---|
  | `source_id` | `parsed_artifact.source_id` (Artifact column) | — (always present) |
  | `source_name` | `Source.name` (column) | — |
  | `source_url` | `Source.url` (column) | `None` |
  | `format` | **`Source.source_type`** (column — already `"html"`/`"pdf"`/`"csv"`) | `None` |
  | `tags` | `Source.config["tags"]` (list[str]) | `[]` |
  | `organization` | `Source.config.get("organization")` | `None` |
  | `title` | `enriched.metadata_["title"]` (set at enrich.py:340) | `None` |
- **D-03:** **Graceful degradation** — every field except `source_id` degrades to `None`/`[]` when unavailable, exactly like today's `document_type`/`quality_score`/`keywords`. Enrichment/registration is **never** a hard blocker to indexing (preserves the existing D-01 additive convention from Phase 4).
- **D-04:** `format` is deliberately sourced from `Source.source_type` (not `Artifact.mime_type`) — it is already the clean short format label used at registration; no mime→format mapping table needed.

### Source-metadata persistence (the `tags` gap)
- **D-05:** `register_source` (`pipeline/ingest.py:277`) currently persists only `config = {"domain": domain}`, **dropping the `tags` list** that `sources.yaml` carries. Extend registration (and the domain-init path that bulk-registers sources) to persist `tags` — and `organization` if present — into `Source.config` alongside `domain`. Additive, backward-compatible (existing sources without tags → `[]`).
- **D-06:** Keep this change **minimal and data-only** — persist the metadata already present in `sources.yaml`; do NOT add new crawl/enrich behavior. `organization` is not currently a `sources.yaml` field; carrying it is opportunistic (degrades to `None`). Adding an `organization:` key to the healthcare pack is a nice-to-have, not required for this phase to pass.

### Payload index strategy (PAYLOAD-02 — avoid full scans)
- **D-07:** No payload indexes exist today (`qdrant_store.py` never calls `create_payload_index`); filters currently work only via unindexed scan. Add an **idempotent `ensure_payload_indexes()`** to `QdrantVectorStore` that creates **keyword** indexes on `source_name`, `format`, `source_id`, and `tags`, and also (backfill) `domain` + `document_type` so the existing filters are indexed too.
- **D-08:** Call `ensure_payload_indexes()` from `ensure_aliased_collection()` (bootstrap) **and** on the physical collection produced by `reindex()`, so both fresh and reindexed collections are indexed. Idempotent — safe to call every `index()`.
- **D-09:** `tags` uses a **keyword index over the array field**; Qdrant keyword indexes match array-contains natively, so no special config beyond `field_schema="keyword"`.

### Filter semantics + CLI/API surface
- **D-10:** Extend `search()` with four additive optional kwargs — `source_name`, `format`, `tags`, `source_id` — appended to the existing `must` list in the `search.py` filter builder (lines ~84–92), alongside `domain`/`document_type`/`min_quality_score`. Fully backward-compatible: calling with none behaves exactly as today.
- **D-11:** `tags` filter = **array-contains**. Single tag → `FieldCondition(key="tags", match=MatchValue(value=tag))` (matches if the chunk's `tags` array contains it). Multiple tags → `MatchAny(any=[...])` (chunk has ANY of the given tags). Default when a user passes several `--tag` flags: match-any (OR).
- **D-12:** CLI flags: `--source-name`, `--format`, `--source-id`, `--tag` (repeatable). API query params: `source_name`, `format`, `source_id`, `tags` (repeatable / CSV). Mirror the existing `--domain`/`--document-type` flag style already in the CLI/API search surface.

### Backward-compatibility contract for existing points
- **D-13:** New fields populate **only on chunks indexed after this phase** (or after a full re-index *from source chunks*). A plain alias-reindex (`copy_all_points`) copies existing payloads verbatim and will NOT synthesize the new fields — so it is not a backfill path. Document this contract explicitly in the `search()` docstring and CLI/API help: filters on new fields simply don't match pre-Phase-7 points. No forced backfill in this phase (consistent with the research's "filters only fully effective on points indexed after this phase" note).

### Claude's Discretion
- Exact CLI flag naming nuances (`--tag` vs `--tags`), whether the API takes repeated `tags=` vs a CSV string, and the precise ordering of `must` conditions — planner/executor discretion, as long as behavior matches D-10..D-12.
- Whether `ensure_payload_indexes()` lives as a new method or folds into the existing `ensure_*` methods — implementation detail, as long as D-07/D-08 hold.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 7: Metadata Foundation" — goal + 4 success criteria (payload assembly, CLI+API filters, keyword indexes, backward-compat contract).
- `.planning/REQUIREMENTS.md` — PAYLOAD-01, PAYLOAD-02 (full acceptance text).

### Research (v2.0, HIGH confidence)
- `.planning/research/SUMMARY.md` §"Phase 7 — Metadata Foundation" — foundational, no new deps; payload-before-filters ordering; Qdrant keyword-index idiom.
- `.planning/research/ARCHITECTURE.md` — payload assembled at `index.py:106-133`; filters at `search.py:84-92`; "additive, keyword-only defaults"; filters only effective on points indexed after this phase.
- `.planning/research/FEATURES.md` — searchable-metadata as the foundation the agent surface + hybrid retrieval build on.
- `.planning/research/PITFALLS.md` — missing-payload-index full scans; create keyword index on every new filterable field (array-keyword for `tags`).

### Code touch points
- `src/knowledge_lake/pipeline/index.py` — payload dict (lines 115–126) and the single-session domain/enrichment join (lines 90–104) to extend.
- `src/knowledge_lake/pipeline/search.py` — `_build`-style `must` filter list (lines 84–92) and `search()` kwargs to extend.
- `src/knowledge_lake/plugins/builtin/qdrant_store.py` — `upsert()`/`search()` (payload passthrough) and where `ensure_payload_indexes()` must be added; `ensure_aliased_collection()` (line 99) + `reindex()` (line 190) call sites.
- `src/knowledge_lake/registry/repo.py` — `get_domain_for_source` (line 820) pattern; add/extend a `get_source`-style getter returning name/url/source_type/config.
- `src/knowledge_lake/registry/models.py` — `Source` (line 58: name, url, source_type, config) and `Artifact` (line 129: source_id, metadata_) columns.
- `src/knowledge_lake/pipeline/ingest.py` — `register_source` (line 273–286) `config = {"domain": domain}` — extend to persist `tags`/`organization`.
- `src/knowledge_lake/pipeline/enrich.py` — line 340, `title` written into `enriched_metadata`.
- `src/knowledge_lake/domains/*/sources.yaml` — per-source `name`, `url`, `source_type`, `tags` (no `organization` key today).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Single-session join in `index.py` (90–104):** already resolves `domain` + sibling enrichment once per call — extend the same block to fetch the `Source` row (name/url/source_type/config). No new per-chunk queries.
- **`get_domain_for_source` (repo.py:820):** the exact pattern for reading `Source.config` safely (None-guards). A sibling `get_source`/`get_source_metadata` getter follows the same shape.
- **`search.py` `must` filter list (84–92):** four new conditions append cleanly next to the existing `domain`/`document_type`/`quality_score` conditions.
- **`enrich.py:340`:** `title` already computed deterministically and stored in enriched metadata — just read it in the join.

### Established Patterns
- **Additive, backward-compatible signatures (D-01, Phase 4):** new payload fields and filter kwargs default to null/None so old callers and old points keep working. Match it exactly.
- **`Source.config` JSON for non-columnar metadata (RESEARCH.md Pitfall 4):** domain lives in `config`, never a dedicated column. `tags`/`organization` follow the same convention — do NOT add Source columns.
- **Alias-backed collections (D-06):** payload indexes must be (re)created on both `ensure_aliased_collection` bootstrap and `reindex` output.

### Integration Points
- `index()` payload dict ← extended Source join (new fields).
- `qdrant_store.ensure_aliased_collection` / `reindex` ← new `ensure_payload_indexes()`.
- `search()` kwargs ← CLI (`cli/app.py` search command) + API (`api/` search route) new params.
- `register_source` ← persist `tags`/`organization` into `Source.config`.
</code_context>

<specifics>
## Specific Ideas

- `format` should be the short label already registered (`Source.source_type`: `"html"`/`"pdf"`/`"csv"`), not a mime type — this is what a user/agent will actually filter on.
- `tags` are the **curated** source tags from `sources.yaml` (e.g. `["ifm","functional-medicine","protocols"]`) — distinct from the LLM-extracted `keywords` field already in the payload. Both are kept; they are different things.
</specifics>

<deferred>
## Deferred Ideas

- **Quality-score-aware ranking / filtering to prefer high-quality chunks** — that is QUALITY-01, deferred to v2.1. Phase 7 only carries `quality_score` in the payload (already does) and adds the four named filters; it does not change ranking.
- **Object tags / domain-scoped storage keys** — Phase 9 (STORE-01/02/03). Do not touch storage keys here.
- **Sparse/hybrid filtering interplay** — filters must keep working under hybrid mode, but that is verified in Phase 10 (RETR), not built here.
- **Adding an `organization:` field to the healthcare `sources.yaml`** — small data enhancement; optional, can ride this phase or a later domain-pack update. `organization` degrades to `None` until populated.

None of the above were requested as scope — captured so they aren't lost.
</deferred>

---

*Phase: 7-metadata-foundation*
*Context gathered: 2026-07-08*
