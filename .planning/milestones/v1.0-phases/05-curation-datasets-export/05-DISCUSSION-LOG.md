# Phase 5: Curation, Datasets & Export - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-06
**Phase:** 5-Curation, Datasets & Export
**Mode:** `--auto` (fully autonomous — no interactive AskUserQuestion turns; all gray areas auto-resolved to the recommended option in a single pass)
**Areas discussed:** Curation artifact shape & dedup scope, DataTrove/Dagster integration, Composite quality scoring, Dataset generation model & call shape, Dataset lineage & registry shape, Export mechanics & storage zone

---

## Curation artifact shape & dedup scope (CURATE-01, CURATE-02)

| Option | Description | Selected |
|--------|-------------|----------|
| New `curated_document` artifact node (parent = `cleaned_document`), batch-wide MinHash replacing Phase 3's transient per-call LSH | Registry-first, mirrors Phase 4's D-01 precedent; directly resolves Phase 3's T-03-06 known-defect comment | ✓ |
| Decorate `cleaned_document.metadata_` in place, no new artifact type | Simpler but breaks the "every transformation is a node" invariant established since Phase 1 | |

**Claude's choice (auto-selected):** New `curated_document` node; batch dedup replaces transient LSH.
**Notes:** `pipeline/clean.py`'s own header comment explicitly forecasts this ("Phase 5 DataTrove pipeline replaces this with batch dedup") — treated as a literal commitment, not a suggestion.

---

## DataTrove adoption & Dagster integration (CURATE-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Real DataTrove library, `LocalPipelineExecutor` inside a thin Dagster `@asset` | Matches the approved stack choice (CLAUDE.md rationale); mirrors existing thin-`@asset`-wrapping-plain-function pattern | ✓ |
| Hand-rolled heuristics only, no DataTrove dependency | Avoids the undocumented integration pattern but contradicts the explicit stack decision and PROJECT.md's pending Key Decision row | |

**Claude's choice (auto-selected):** Real DataTrove + `LocalPipelineExecutor` in a single-node Dagster asset.
**Notes:** Flagged as the researcher's top priority — STATE.md's Phase 5 blocker ("no documented pattern for running DataTrove pipeline blocks inside Dagster assets") is a genuine open technical question, not a Claude's-discretion item.

---

## Composite quality scoring (CURATE-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Combine parse-quality heuristic + enrichment LLM quality_score + new curation heuristics into one composite, stored on `curated_document` | Reuses all existing quality signals rather than recomputing; queryable via CLI/API per success criterion | ✓ |
| Curation-only score, ignore Phase 3/4 scores | Simpler but wastes existing signal and produces a less meaningful "composite" | |

**Claude's choice (auto-selected):** Combine all three signals into one composite score.
**Notes:** Exact weighting formula left to Claude/planner discretion.

---

## Dataset generation model & call shape (DATA-01, DATA-02)

| Option | Description | Selected |
|--------|-------------|----------|
| `strong_model`/`eval_model` aliases, one call per chunk (Q&A) or per document (instruction), reusing `enrich.py`'s LLM-call helper shape | Phase 4's own CONTEXT.md explicitly reserved these aliases for this exact use case; avoids a second parallel LLM-call implementation | ✓ |
| `cheap_model`, matching enrichment's model choice | Cheaper but contradicts Phase 4's explicit forward-looking reservation of strong/eval aliases for dataset generation | |

**Claude's choice (auto-selected):** strong_model/eval_model aliases; reuse `_call_llm_for_enrichment`-style helper.
**Notes:** Direct precedent from `04-CONTEXT.md` D-03: "strong_model/eval_model stay reserved for heavier synthesis and evaluation work (Phase 5 dataset generation ...)".

---

## Dataset lineage & registry shape (DATA-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Extend the existing empty `Dataset` model with real columns + per-example source-ID tracking (join table or JSON array) | Reuses the migration-#1 placeholder; avoids exploding `artifacts` table with per-example granularity | ✓ |
| Each generated example becomes its own `Artifact` lineage node | Consistent with the artifact-per-transformation pattern but at QA-pair granularity would massively inflate the artifacts table | |

**Claude's choice (auto-selected):** Extend `Dataset` model; join-table vs JSON-array left to planner.

---

## Export mechanics & storage zone (EXPORT-01, EXPORT-02, EXPORT-03)

| Option | Description | Selected |
|--------|-------------|----------|
| New gold zone in existing `StorageBackend`; Polars/PyArrow write Parquet/JSONL, DuckDB used for query/verification | Matches zone-based storage progression (raw→bronze→silver→gold) and CLAUDE.md's stated DuckDB/Polars role split | ✓ |
| New standalone export service/backend | Unnecessary complexity; contradicts "no new storage backend" constraint | |

**Claude's choice (auto-selected):** Gold zone in existing StorageBackend; Polars/PyArrow write, DuckDB queries.
**Notes:** None of `datatrove`, `polars`, `pyarrow`, `duckdb` are yet pyproject dependencies — planner must add them; this is a dependency gap, not an open design question.

---

## Claude's Discretion

- DataTrove filter block selection/thresholds (length, repetition, boilerplate ratio)
- Composite quality score weighting formula
- Join-table vs JSON-array for per-example dataset lineage
- CLI/API/Dagster command and endpoint naming for curate/dedupe/generate-dataset/export
- Budget-cap settings naming/granularity for dataset generation
- Gate vs flag-only for low composite-quality documents at export time
- Fine-tuning JSONL format specifics (OpenAI chat-messages vs Alpaca-style)

## Deferred Ideas

- Full `klake` CLI/API surface completeness (IFACE-01/02) — Phase 6 territory
- Healthcare-specific dataset content/taxonomy — Phase 6 (DOMAIN-02/03) territory
