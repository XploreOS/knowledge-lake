# Phase 5: Curation, Datasets & Export - Context

**Gathered:** 2026-07-06
**Status:** Ready for planning
**Mode:** `--auto` — all gray areas auto-resolved with recommended defaults (no interactive session). Every decision below is tagged `(auto-selected)` and logged with rationale so the user can audit/override before planning.

<domain>
## Phase Boundary

Phase 5 turns the enriched corpus (Phase 4's `enriched_document`/`chunk` artifacts) into AI-ready deliverables: a curated, deduplicated pretraining-quality corpus (DataTrove-style quality filters + corpus-wide dedup), generated datasets with full lineage (citation-grounded RAG-eval Q&A from chunks, instruction-tuning examples from documents), and standard export formats (Parquet queryable via DuckDB, JSONL pretraining corpus, JSONL chat/instruction fine-tuning format).

Requirements: CURATE-01 through CURATE-03, DATA-01 through DATA-03, EXPORT-01 through EXPORT-03.

**Note:** This phase is not greenfield on curation — Phase 3's `clean()` already does a *transient, per-call* MinHash near-dup check (`pipeline/clean.py`, flagged as tech debt T-03-06: "O(n) per call ... Phase 5 DataTrove pipeline replaces this with batch dedup"). Phase 5's corpus-wide dedup (CURATE-02) is that promised replacement, not a new parallel mechanism.

</domain>

<decisions>
## Implementation Decisions

### Curation artifact shape & scope (CURATE-01, CURATE-02)
- **D-01 (auto-selected):** Curation produces a new `artifact_type='curated_document'` row — parent is the `cleaned_document` artifact, mirroring the established registry-first pattern (every transformation is its own node, per FOUND-06/07 and Phase 4's D-01 precedent). Quality-filter results (per-heuristic pass/fail, filter reasons) live in `metadata_` JSON, consistent with how `parsed_document`/`cleaned_document` already store their heuristic data.
- **D-02 (auto-selected):** Corpus-wide dedup (CURATE-02) replaces, not duplicates, Phase 3's transient per-call LSH (`pipeline/clean.py` T-03-06 comment). A batch job builds one MinHash LSH index over ALL `cleaned_document` artifacts at once and flags/links near-duplicates in a single pass — this is the fix STATE.md's Phase 3 blocker already anticipated. The existing `dedup_status` field on `cleaned_document.metadata_` may be corrected/superseded by this batch pass; planner decides whether to overwrite in place or record the batch result on the new `curated_document` node instead.

### DataTrove adoption & Dagster integration (CURATE-01)
- **D-03 (auto-selected):** Adopt the real DataTrove library (already the approved stack choice — see CLAUDE.md's "DataTrove ... vs Custom filters" rationale) rather than hand-rolled heuristics-only filters. **Not currently a pyproject dependency** — planner must add it.
- **D-04 (auto-selected):** Run DataTrove's `LocalPipelineExecutor` synchronously inside a single Dagster `@asset` function — the same "plain function wrapped by a thin `@asset`" shape already used for `enrich_document`/`chunk_document` (`dagster_defs/assets.py`). No Slurm/Ray executor (single-node MVP scale, matches DigitalOcean droplet constraint).
  - **Flagged for research (highest priority):** STATE.md's Phase 5 blocker — *"No documented pattern for running DataTrove pipeline blocks inside Dagster assets"* — is the researcher's top priority. Specifically: how to adapt DataTrove's own `Document`-streaming model (which natively reads/writes local files or its own readers) to source from the Postgres registry + S3 silver zone and write results back as registry rows, rather than fighting DataTrove's native file-based I/O model.

### Composite quality scoring (CURATE-03)
- **D-05 (auto-selected):** The composite score combines three existing/new signals: Phase 3's parse-quality heuristic (currently in `parsed_document.metadata_`), Phase 4's enrichment LLM `quality_score` (real column on `enriched_document`), and Phase 5's new curation heuristics (length, repetition, boilerplate ratio). Stored as a new field on `curated_document` (metadata_ JSON, consistent with D-01) and surfaced via a CLI/API query that joins across the artifact lineage tree per document — satisfying the "queryable via CLI/API" success criterion. Exact weighting formula is Claude/planner's call.

### Dataset generation model & call shape (DATA-01, DATA-02)
- **D-06 (auto-selected):** Use the **`strong_model`**/**`eval_model`** task aliases (not `cheap_model`) for dataset generation — Phase 4's own CONTEXT.md (D-03) explicitly reserved these aliases for "heavier synthesis and evaluation work (Phase 5 dataset generation ...)". Q&A/RAG-eval generation reads from `chunk` artifacts (citation-grounded, DATA-01); instruction-tuning generation reads from `enriched_document` artifacts (document-level, DATA-02). One structured-output LLM call per unit (per chunk for Q&A, per document for instruction pairs) — mirrors Phase 4's D-03 "one call per unit, not per-field" pattern, not N calls per example.
- **D-07 (auto-selected):** Reuse the established LLM-call helper shape from `pipeline/enrich.py::_call_llm_for_enrichment` (the `openai/` provider-prefix routing quirk, `_strip_json_fences` markdown-fence defense, `tenacity` retry policy, `compute_call_cost`/`llm/pricing.py` cost tracking against the existing `LlmSpend` budget table) rather than writing a second, parallel LLM-call implementation from scratch. `EnrichSettings.budget_usd` precedent implies a new `CurateSettings`/`DatasetSettings.budget_usd` cap following the same graceful-halt behavior as ENRICH-05.

### Dataset lineage & registry shape (DATA-03)
- **D-08 (auto-selected):** Generated dataset examples are **not** individual `Artifact`/lineage-tree nodes (that would explode `artifacts` with per-QA-pair granularity, breaking the "artifact = pipeline transformation" invariant). Instead, extend the existing (currently empty, migration-#1-placeholder) `Dataset` model with real columns (`name`, `dataset_type`, `format`, `example_count`, `storage_uri`) plus a mechanism recording per-example source chunk/document IDs for DATA-03 traceability. Claude/planner decides join-table (queryable, more tables) vs JSON-array-per-example (simpler, matches `metadata_` precedent) — either satisfies "record lineage to source chunks/documents."

### Export mechanics & storage zone (EXPORT-01, EXPORT-02, EXPORT-03)
- **D-09 (auto-selected):** Exports write to a new **gold zone** in the existing S3 storage abstraction (`storage/s3.py`'s `StorageBackend`) — not a new storage backend, following the raw→bronze→silver zone progression already established in Phases 1-3. Matches PROJECT.md's Constraints ("Storage: S3-compatible... no local filesystem as production store").
- **D-10 (auto-selected):** Role split per CLAUDE.md's stack rationale: **Polars or PyArrow** writes the actual Parquet/JSONL files (native Arrow/Parquet support); **DuckDB** is the query/export-verification engine exposed to the user ("SQL interface over data lake files") — not a second independent export writer. EXPORT-01's "queryable via DuckDB" acceptance criterion is satisfied by DuckDB reading the Parquet files DuckDB itself doesn't need to have written.
  - **Dependency gap:** none of `datatrove`, `polars`, `pyarrow`, or `duckdb` currently appear in `pyproject.toml` despite being the documented, approved stack choices (CLAUDE.md Technology Stack table) — planner must add them as real dependencies, not treat this as an open design question.

### Claude's Discretion
- Exact DataTrove filter block selection/thresholds (length, repetition, boilerplate ratio cutoffs) for CURATE-01 — Claude/planner decides defaults, informed by DataTrove's FineWeb-proven production values (same precedent as Phase 3's MinHash `num_perm`/`threshold` defaults).
- Composite quality score weighting formula (D-05) — Claude decides.
- Join-table vs JSON-array for per-example dataset lineage (D-08) — Claude/planner decides based on whether CURATE/DATA CLI/API needs to query "which datasets does chunk X appear in" efficiently.
- CLI/API/Dagster command and endpoint naming for curate/dedupe/generate-dataset/export (IFACE-01/02 groundwork, even though those requirements formally belong to Phase 6) — Claude decides, consistent with existing `klake parse/clean/chunk/enrich` naming.
- Budget-cap settings naming/granularity for dataset generation (D-07) — Claude decides; a single global cap mirroring `EnrichSettings.budget_usd` is acceptable for MVP.
- Whether low composite-quality documents are excluded from exports (gate) or merely annotated (flag-only, filterable) — Claude decides based on the batch-first architecture precedent from Phase 3.
- Fine-tuning JSONL chat/instruction format specifics (e.g., OpenAI chat-messages shape vs Alpaca-style instruction/input/output) — Claude decides a standard, well-documented format for EXPORT-03.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project planning docs
- `.planning/PROJECT.md` — Constraints table (LLM-gateway-only, S3-only storage, deterministic-first), Key Decisions ("DataTrove-style curation over custom filters — Pending (Phase 5)"), Technology Stack table (DataTrove, DuckDB, PyArrow, Polars rationale — none yet installed)
- `.planning/REQUIREMENTS.md` — CURATE-01..03, DATA-01..03, EXPORT-01..03 definitions this phase must satisfy
- `.planning/ROADMAP.md` — Phase 5 goal and 4 success criteria (the scope anchor)
- `.planning/STATE.md` — Phase 5 blocker already flagged: "No documented pattern for running DataTrove pipeline blocks inside Dagster assets — needs experimentation" (directly maps to D-04); Phase 3 blocker "transient LSH corpus scan" (T-03-06) that D-02 resolves

### Prior phase context (decisions that carry forward)
- `.planning/phases/04-enrichment-embedding-search/04-CONTEXT.md` — D-01 (registry-first "every transformation is a node" pattern — the template D-01 here follows), D-03 (model-alias reservation: cheap_model for enrichment, strong/eval reserved for Phase 5 — the template D-06 here follows), D-04 (caching-by-content-hash pattern, reusable for dataset-generation caching if planner wants it), D-05 (budget-cap graceful-halt pattern — the template D-07 here follows)
- `.planning/phases/03-parse-clean-chunk/03-CONTEXT.md` — D-04 (heuristics + optional LLM spot-check quality-scoring pattern — precedent for D-05's composite score), MinHash near-dup discussion (num_perm/threshold defaults — precedent for D-02's batch dedup config)

### Existing implementation (extend, don't rewrite)
- `src/knowledge_lake/pipeline/clean.py` — `compute_minhash()`, transient `MinHashLSH` near-dup check (lines ~128-278) and its own T-03-06 comment explicitly deferring corpus-wide dedup to this phase — the exact code path D-02 replaces
- `src/knowledge_lake/pipeline/enrich.py` — `_call_llm_for_enrichment()`, `_strip_json_fences()`, `_enrichment_cache_key()`, `enrich_document()` — the LLM-call/caching/budget shape D-06/D-07 reuse for dataset generation
- `src/knowledge_lake/llm/pricing.py` — `bootstrap_llm_pricing()`, `compute_call_cost()` — cost accounting to reuse (not reimplement) for dataset-generation budget tracking
- `src/knowledge_lake/quality/scorer.py` — `compute_quality_score()`, `maybe_llm_spot_check()` — the heuristics-first + optional-LLM-refinement pattern to mirror for CURATE-01's quality filters and D-05's composite score
- `src/knowledge_lake/registry/models.py` — `Artifact` model (`artifact_type` discriminator, `metadata_` JSON, `UNIQUE(content_hash, artifact_type)`) to extend with `curated_document`; `Dataset` model (currently empty placeholder from migration #1) to extend for DATA-03
- `src/knowledge_lake/registry/repo.py` — `create_*_document()` functions to mirror for a new `create_curated_artifact()`
- `src/knowledge_lake/config/settings.py` — `EnrichSettings`/`IndexSettings` nested-model pattern to follow for new `CurateSettings`/`DatasetSettings`/`ExportSettings` (budget_usd, filter thresholds, gold-zone prefix)
- `src/knowledge_lake/dagster_defs/assets.py` — asset chain (`clean_document` → `chunk_document`/`enrich_document` → `embed_chunks`/`index_chunks`) to extend with `curate_document`, `generate_dataset`, and export assets
- `src/knowledge_lake/storage/s3.py` — `StorageBackend` — extend with a gold-zone prefix constant (mirrors `_SILVER_PREFIX` in `pipeline/clean.py`), not a new backend
- `src/knowledge_lake/cli/app.py` — single-file Typer app pattern (`@app.command(name=...)`) to extend with `curate`, `dedupe`, `generate-dataset`, `export` commands

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `compute_minhash()` / `MinHashLSH` usage in `pipeline/clean.py` — signature computation is reusable as-is; only the "transient per-call, in-memory" scan pattern needs replacing with a batch pass over all `cleaned_document` artifacts
- `_call_llm_for_enrichment()` pattern (`pipeline/enrich.py`) — provider-prefix routing, JSON-fence stripping, tenacity retry, cost accumulation — template for a new dataset-generation LLM helper
- `compute_quality_score()` (`quality/scorer.py`) — weighted-heuristic pattern (weights summing to 1.0) — template for CURATE-01's length/repetition/boilerplate filters and D-05's composite score
- `LlmSpend` model + budget-cap-and-halt pattern from `EnrichSettings.budget_usd` (ENRICH-05) — template for dataset-generation's own budget cap

### Established Patterns
- Registry-first writes: every pipeline stage creates `Artifact` + `LineageEvent` rows in the same session (`get_session()` context manager)
- Settings: nested `BaseModel` per pipeline stage under `KLAKE_<STAGE>__*` env vars
- Zone-based S3 storage: raw (immutable) → bronze (crawled markdown) → silver (parsed/cleaned) — gold zone for exports is the natural next step, same `StorageBackend.put_object()`/prefix-constant pattern
- Single-file Typer CLI (`cli/app.py`) with one `@app.command()` per pipeline stage — no per-command file split
- Dagster: thin `@asset` wrapping a plain, independently-testable pipeline function — every prior phase (parse/clean/chunk/enrich/index) follows this shape

### Integration Points
- New Alembic migration(s): `curated_document` artifact_type needs no new columns (reuses `metadata_`) unless D-05's composite score gets a dedicated column; `Dataset` model needs real columns added (currently just `id`/`name`/`created_at` placeholders from migration #1); possibly a new `dataset_examples` join table for DATA-03 lineage
- New settings: `CurateSettings` (filter thresholds, dedup batch size), `DatasetSettings`/budget cap, `ExportSettings` (gold-zone prefix, default formats)
- New pyproject.toml dependencies: `datatrove`, `polars` or `pyarrow`, `duckdb` — none currently installed despite being the documented stack choice
- CLI expansion: `klake curate`, `klake dedupe`, `klake generate-dataset`, `klake export` commands
- API expansion: curation trigger, dataset-generation trigger, export trigger + download/query endpoints
- Dagster: `curate_document` asset (parallel or sequential after `clean_document`), `generate_dataset` job, export asset(s)

</code_context>

<specifics>
## Specific Ideas

- The Phase 3 `clean.py` module header comment is itself a forward-reference to this phase — treat "Phase 5 DataTrove pipeline replaces this with batch dedup" as a literal commitment, not just background color.
- STATE.md's Phase 5 blocker ("No documented pattern for running DataTrove pipeline blocks inside Dagster assets") should be the researcher's #1 priority — this is a genuinely unresolved integration question, not a Claude's-discretion item.
- Keep the existing `search()` response shape and Qdrant payload additive-only if curation/export touch indexing at all (unlikely — Phase 5 is corpus/dataset/export focused, not search-focused) — no expected overlap, noted only for safety.
- `.planning/PROJECT.md`'s Key Decisions table already has a placeholder row — "DataTrove-style curation over custom filters | Proven at scale... | — Pending (Phase 5)" — this phase's execution is what resolves that pending decision to Validated.

</specifics>

<deferred>
## Deferred Ideas

- Full `klake` CLI surface completeness (IFACE-01) and FastAPI OpenAPI completeness (IFACE-02) — formally Phase 6 requirements; this phase adds only the commands/endpoints its own requirements need, not a full audit.
- Healthcare-specific dataset content/taxonomy — Phase 6 (DOMAIN-02/03) territory; Phase 5's dataset generation is domain-agnostic.

</deferred>

---

*Phase: 5-Curation, Datasets & Export*
*Context gathered: 2026-07-06*
