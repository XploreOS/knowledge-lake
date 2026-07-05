# Phase 4: Enrichment, Embedding & Search - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-05
**Phase:** 04-Enrichment, Embedding & Search
**Mode:** `--auto` (fully autonomous — no interactive prompts; Claude selected the recommended option for every gray area and logged it here for audit)
**Areas discussed:** Enrichment pipeline shape, Deterministic-first extraction, LLM extraction strategy & model assignment, Caching, Budget enforcement, Qdrant collection aliasing, Qdrant payload metadata scope, Embedding provider default

---

## Enrichment pipeline shape

| Option | Description | Selected |
|--------|-------------|----------|
| New `enriched_document` artifact, parent = `cleaned_document`, parallel to chunking | Follows the established registry-first, every-transformation-is-a-node pattern; fields in `metadata_` JSON | ✓ |
| Decorate existing `cleaned_document` metadata in place (no new artifact/lineage node) | Cheaper, but breaks the "every transformation is traceable" lineage pattern used since Phase 1 | |

**Selected:** New `enriched_document` artifact type (recommended default — consistent with FOUND-06/07 and the parsed/cleaned/chunk precedent).
**Notes:** Runs parallel to `chunk_document` (both descend from `clean_document`) so enrichment and chunking don't block each other.

---

## Deterministic-first extraction (ENRICH-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse already-computed `ParsedDoc`/`Section` data (title, headings) + regex dates, pass as LLM context | No re-parsing; LLM only asked for judgment fields | ✓ |
| Re-derive everything via LLM, deterministic pass only as a fallback | Simpler LLM prompt but wastes tokens on fields already known | |

**Selected:** Reuse existing parsed/section metadata as deterministic hints.
**Notes:** Keeps LLM calls focused on summary, document type, organization, jurisdiction, keywords, entities, quality score.

---

## LLM extraction strategy & model assignment (ENRICH-01, ENRICH-03)

| Option | Description | Selected |
|--------|-------------|----------|
| One structured-output call per document via `cheap_model` | Minimizes cost/latency, single cache entry per document | ✓ |
| N separate calls per field, mixing cheap/strong models | More granular but multiplies cost, latency, and cache complexity | |

**Selected:** Single structured JSON call via `cheap_model`, direct `litellm.completion()` (same pattern as `LiteLLMEmbedder`).
**Notes:** `strong_model`/`eval_model` stay reserved for Phase 5 dataset generation and the existing PARSE quality-gray-zone spot-check.

---

## Caching (ENRICH-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse `UNIQUE(content_hash, artifact_type)` with a synthetic hash of (cleaned content_hash + prompt_version) | No new table; mirrors existing parse/clean dedup pattern | ✓ |
| New dedicated enrichment-cache table (prompt_version, input_hash, result) | More explicit but duplicates a mechanism the registry already has | |

**Selected:** Reuse the existing Artifact dedup constraint with a synthetic content hash.

---

## Budget enforcement (ENRICH-05)

| Option | Description | Selected |
|--------|-------------|----------|
| Use LiteLLM's own cost accounting (`completion_cost()`), accumulate in Postgres against a configurable cap | Avoids reimplementing per-model pricing; graceful halt on cap hit | ✓ |
| Build a custom per-model pricing table and track spend independently | More control but duplicates data LiteLLM already tracks, drifts as prices change | |

**Selected:** LiteLLM cost accounting + Postgres accumulation; halt gracefully (mark remaining docs `skipped_budget_exceeded`), never crash.
**Notes:** Flagged as a research priority — STATE.md already lists "LiteLLM budget enforcement behavior under burst load unverified" as a Phase 4 blocker.

---

## Qdrant collection aliasing (INDEX-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Versioned physical collections behind a stable alias (Qdrant native alias swap) | Zero-downtime reindex; industry-standard pattern | ✓ |
| In-place collection updates (no versioning/alias) | Simpler but reindex causes visible downtime/inconsistency | |

**Selected:** Versioned collections (`klake_chunks_v1`, `v2`, ...) behind alias `klake_chunks`, mapping tracked in the registry.
**Notes:** Flagged as a research priority — STATE.md already lists "Qdrant collection aliasing patterns need research."

---

## Qdrant payload metadata scope (INDEX-01, INDEX-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Extend payload with domain, document_type, keywords, quality_score (from sibling `enriched_document`) | Enables the payload filtering already named in PROJECT.md's stack rationale | ✓ |
| Keep payload limited to current citation fields only | Simpler but blocks filtered search entirely | |

**Selected:** Extended payload, sourced at index time from the sibling `enriched_document` artifact when available; indexing does not block on enrichment being complete.

---

## Embedding provider default (ENRICH-06 continuation)

| Option | Description | Selected |
|--------|-------------|----------|
| Keep `local` (sentence-transformers) as default | Zero-credential, consistent with Phase 1 D-13 | ✓ |
| Switch default to `litellm` now that bulk documents are flowing | Higher quality vectors but adds cost/budget surface this phase doesn't need | |

**Selected:** Keep `local` as the default; `litellm` remains a pure config switch.

---

## Claude's Discretion

- Exact JSON schema/field names for the structured LLM enrichment output.
- Flat string list vs typed `(entity, type)` pairs for extracted entities (healthcare taxonomy is Phase 6).
- Whether `document_type` (or other fields) get a dedicated indexed Postgres column vs staying in `metadata_` JSON.
- Retry/backoff behavior for transient LiteLLM failures (reuse existing `tenacity` pattern).
- Budget cap granularity (global vs per-job vs per-source) — global default acceptable for MVP.
- CLI/API command naming for enrich/reindex/filtered-search.
- Dagster asset wiring for `enrich_document` and the reindex job.
- Whether low quality_score gates search visibility now vs deferring to Phase 5's composite curation scoring (CURATE-03) — deferring is the safer default.

## Deferred Ideas

- Healthcare-specific entity taxonomy and enrichment prompts — Phase 6 (DOMAIN-03).
- Composite quality scoring across documents/sources (CURATE-03) — Phase 5.

## Flagged for Planner/Researcher Attention

- **Pre-existing discrepancy found during codebase scout:** Alembic migration `0006_parse_clean_chunk_columns.py` added dedicated `quality_score`/`language`/`dedup_status` columns to `artifacts`, but `registry/models.py` never maps them as ORM columns, and `pipeline/clean.py`/`pipeline/parse.py` write this data into the `metadata_` JSON column instead. Planner should explicitly decide how Phase 4's enrichment fields relate to this split rather than silently extending it further.
