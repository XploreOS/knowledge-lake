# Phase 10: Hybrid Retrieval - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-10
**Phase:** 10-hybrid-retrieval
**Mode:** `--auto --chain` (all gray areas auto-selected; recommended defaults chosen without prompts)
**Areas discussed:** Sparse encoder, Live-migration mechanics & safety, Search-mode surface & fail-loud contract, RRF fusion & prefetch/IDF tuning

---

## Sparse encoder — how BM25 sparse vectors are produced

| Option | Description | Selected |
|--------|-------------|----------|
| Add `fastembed` (Qdrant-native BM25 + `Modifier.IDF`) | Cleanest integration with qdrant-client 1.18; sparse construction stays inside the vector-store plugin; no self-owned IDF/vocab state | ✓ |
| Reuse installed `rank_bm25` | No new dependency, but forces us to own shared-vocabulary/IDF state — more moving parts | |
| GPU encoders (SPLADE / miniCOIL) | Higher quality but violates the CPU-droplet constraint; v2.1 upgrade path | |

**Auto choice:** Add `fastembed` (recommended default). **Notes:** `fastembed` is not yet installed; `rank_bm25` is present as the documented fallback. Decision must be re-confirmed during `--research-phase` (verify version pins + Qdrant-native BM25 path against the installed stack).

---

## Live-migration mechanics & safety (unnamed→named-vector recreate)

| Option | Description | Selected |
|--------|-------------|----------|
| Existing `reindex()` alias-swap + re-embedding `upsert_fn` + parity gate + keep-old rollback + server≥1.10 preflight, operator-triggered, validate on a copy first | Reuses purpose-built zero-downtime machinery; re-embeds every point so sparse covers the whole collection; reversible until parity holds | ✓ |
| In-place ALTER to add sparse to the existing unnamed collection | Impossible in Qdrant — dense+sparse coexistence requires named vectors (ARCHITECTURE Anti-Pattern 2) | |
| `copy_all_points` copy migration | Insufficient — copies dense but cannot synthesize sparse for old points, leaving a partial collection | |

**Auto choice:** reindex + re-embed + parity gate + alias-keep rollback + server-version preflight, operator-triggered (recommended default). **Notes:** `keep_old_collections=True` already default; `reindex()`/`ensure_aliased_collection()`/`get_collection_dim()` create-paths must move to the named-vector shape.

---

## Search-mode surface & fail-loud contract (RETR-03)

| Option | Description | Selected |
|--------|-------------|----------|
| New `SearchSettings.mode` (default `hybrid`) via `KLAKE_SEARCH__MODE`; per-request `--mode`/`?mode=` override; loud error when requested vectors absent | Mirrors the existing `IndexSettings` nested pattern; back-compat keyword-only `mode="dense"` defaults; never silently degrades | ✓ |
| Silent fallback to dense when sparse vectors are missing | Explicitly rejected by RETR-03 — must fail loudly | |
| Loose top-level `KLAKE_SEARCH_MODE` setting | Breaks the established nested `BaseModel` + `__` delimiter convention | |

**Auto choice:** new `SearchSettings.mode` default `hybrid` + per-request override + fail-loud error naming the missing vector and remediation (recommended default). **Notes:** `dense` mode keeps working on both old and migrated collections.

---

## RRF fusion & prefetch / IDF tuning

| Option | Description | Selected |
|--------|-------------|----------|
| Server-side RRF via `query_points` + `FusionQuery(Rrf)`; prefetch ≥ limit+offset (not 10×); `Modifier.IDF` at collection creation; named keys `dense`/`sparse` | Rank-based fusion is the only correct approach (dense/sparse scores are incomparable); tight prefetch avoids over-fetch | ✓ |
| Client-side or fixed-weight score fusion | Anti-feature (REQUIREMENTS.md) — incomparable score scales | |
| Leave prefetch at defaults | Risks empty/short hybrid results when prefetch < limit+offset | |

**Auto choice:** server-side RRF only + prefetch ≥ limit+offset headroom + `Modifier.IDF` on sparse config + reuse Phase 7 filter builder verbatim across all modes (recommended default).

---

## Claude's Discretion

- Exact `fastembed` model name / BM25 variant.
- Precise prefetch headroom multiplier within the `≥ limit+offset` (not 10×) bound.
- Whether the migration is a new CLI subcommand vs a `--hybrid` flag on the existing reindex path.
- Whether sparse construction lives in `qdrant_store.py` or a small new `plugins/builtin/sparse_embedder.py`.
- Exact fail-loud error type/message wording (must name the missing vector + remediation).

## Deferred Ideas

- Retrieval-quality eval (RAGAS/Promptfoo, recall@k, RRF-vs-dense A/B) — EVAL-01, v2.1.
- Quality-score-aware ranking/boosting — QUALITY-01, v2.1.
- GPU sparse encoders (SPLADE/miniCOIL) — documented upgrade path.
- OpenSearch full-text (old v1.0 RETR-02) — superseded by native sparse+RRF.
