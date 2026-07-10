# Phase 10: Hybrid Retrieval - Context

**Gathered:** 2026-07-10
**Status:** Ready for planning
**Mode:** `--auto --chain` (gray areas auto-selected, recommended defaults chosen without prompts — every decision below is auditable and revisable before planning; chain auto-advances to plan-phase → execute-phase)

<domain>
## Phase Boundary

Deliver **hybrid lexical + semantic retrieval** with server-side fusion, mode-switchable and fail-loud. Two requirements:

- **RETR-01** — Search supports hybrid BM25 + dense retrieval using Qdrant **named** sparse + dense vectors with **server-side RRF fusion**, delivered via the existing alias-swap reindex (unnamed→named-vector collection recreate with a **re-embedding** upsert so all points get sparse vectors).
- **RETR-03** — Search mode is configurable via `KLAKE_SEARCH__MODE=hybrid|dense|sparse` (default `hybrid`); a request for a mode whose vectors are absent **fails loudly** rather than silently degrading.

**In scope:** named-vector (dense+sparse) collection creation, a re-embedding migration of existing collections via the existing `reindex()` alias-swap, sparse-vector generation at index time, server-side RRF hybrid query in `qdrant_store.search`, a `mode` param threaded through `pipeline/search.py` → CLI/API, a new `SearchSettings` config with the fail-loud contract, and a Qdrant-server-version preflight gate.

**Out of scope (own phases / deferred):** re-crawl scheduling & change detection (Phase 11 — SCHED-01/02), MCP/agent surfaces (Phase 12), retrieval-quality eval harness / RAGAS / Promptfoo (EVAL-01, v2.1), quality-score-aware ranking (QUALITY-01, v2.1), GPU sparse encoders SPLADE/miniCOIL (v2.1 documented upgrade path). This phase adds sparse+hybrid+mode; it does not change chunking, enrichment, or payload fields (Phase 7 already delivered those).

**LIVE DATA MIGRATION.** Unnamed→named-vector collection recreate + re-embedding upsert. Flagged for `--research-phase` at plan time (verify `query_points`/`FusionQuery`/`SparseVectorParams`/`Modifier.IDF` against installed qdrant-client 1.18, confirm running Qdrant **server ≥ 1.10**, validate the re-embedding reindex on a collection copy first). Rollback: alias keeps old collections until point-count parity is verified.
</domain>

<decisions>
## Implementation Decisions

### Sparse encoder — how BM25 sparse vectors are produced
- **D-01:** **Add `fastembed`** as a new dependency and use Qdrant-native BM25 sparse embeddings with `Modifier.IDF`, rather than the already-installed `rank_bm25`. Rationale: `fastembed` integrates cleanly with `qdrant-client` 1.18 (`qdrant_fastembed` support ships in the venv), keeps sparse-vector construction inside the vector-store plugin, and avoids owning corpus-IDF/vocabulary state ourselves. `rank_bm25` is present but is the fallback only if adding `fastembed` is rejected — it forces us to own shared-vocabulary/IDF state (more moving parts). This is the phase's biggest decision and must be **re-confirmed during `--research-phase`** (verify `fastembed` version pins cleanly and the Qdrant-native BM25 path works against the installed stack).
- **D-02:** BM25 is the correct **CPU-friendly** v2.0 default (DigitalOcean droplet constraint). GPU encoders (SPLADE, miniCOIL) are an explicit deferred upgrade path — do NOT pull them in here (REQUIREMENTS.md anti-pattern: "GPU-based sparse encoders for v2.0").
- **D-03:** Sparse query-vector generation at search time uses the same `fastembed` BM25 path — no `rank_bm25` at query time. Server-side RRF (D-08) replaces any need for client-side BM25 scoring.

### Live migration — unnamed→named-vector recreate with re-embedding
- **D-04:** Reuse the **existing `reindex(alias, dim, upsert_fn)` alias-swap machinery** (`qdrant_store.py`, driven by `index.py:reindex_collection`). The named-vector migration is a reindex, **not** an in-place ALTER — Qdrant cannot add sparse to an existing unnamed collection; dense+sparse coexistence requires the dense vector to be **named**. (ARCHITECTURE Anti-Pattern 2.)
- **D-05:** The migration `upsert_fn` must **re-embed**, not copy. `copy_all_points` copies dense vectors but cannot synthesize sparse vectors for old points → a pure copy leaves a partial collection. The migration re-reads chunk text (registry / silver zone) and produces **both** the dense and sparse named vectors for every point. Note: `reindex()` and `ensure_aliased_collection()` currently hard-code an **unnamed** `vectors_config=VectorParams(...)`; both create-paths must move to `vectors_config={"dense": VectorParams(...)}` + `sparse_vectors_config={"sparse": SparseVectorParams(modifier=Modifier.IDF)}`. `get_collection_dim()` (reads `params.vectors.size`) must also be updated for the named-vector shape.
- **D-06:** **Point-count parity gate** — verify the new physical collection's point count matches the old collection's **before** the alias swap. A count mismatch aborts the swap (do not repoint the alias). This is the safety contract that makes the migration reversible; the alias keeps pointing at the old collection until parity holds (`keep_old_collections` is already `True` by default — operator drops the old collection after confirming the swap).
- **D-07:** **Qdrant server ≥ 1.10 preflight** — before the migration (and before any hybrid query) runs, confirm the running Qdrant **server** version is ≥ 1.10 (client 1.18 has the API, but the Query API / IDF / sparse vectors need server ≥ 1.10). If the server is too old, **abort with a clear error** rather than creating a broken collection. Migration is **operator-triggered** (an explicit CLI step, e.g. extend the existing reindex command path) — not an automatic startup migration — so the live data migration stays under operator control; validate on a **collection copy first** per the research flag.

### Search-mode config surface + fail-loud contract (RETR-03)
- **D-08:** Add a new nested **`SearchSettings`** model (`settings.search`, env `KLAKE_SEARCH__MODE`), mirroring the existing `IndexSettings` (`settings.index`) pattern — `mode: Literal["hybrid","dense","sparse"] = "hybrid"`. Default is **`hybrid`** per RETR-03. Do NOT add loose top-level settings; follow the nested `BaseModel` + `env_nested_delimiter="__"` convention already established.
- **D-09:** `mode` is a **per-request override** as well: `pipeline.search()` gains `mode` (defaulting to `settings.search.mode`), surfaced as `klake search --mode hybrid|dense|sparse` and the API `?mode=` query param. The `VectorStorePlugin.search` signature gains keyword-only `mode="dense"` + `sparse_query=None` defaults so **existing callers and old points are unaffected until they opt in** (back-compat convention from Phases 4/7/9).
- **D-10:** **Fail loudly, never silently degrade.** When a request asks for `hybrid` or `sparse` but the target collection has no sparse vectors (e.g. it is still an old unnamed-vector collection, pre-migration), raise a **clear, explicit error** that names the missing vector and the required action (run the hybrid reindex) — do NOT fall back to dense. The error must make the actually-attempted mode unambiguous. `dense` mode continues to work against both old and migrated collections.

### Server-side RRF fusion + prefetch / IDF tuning
- **D-11:** **Server-side RRF only.** Hybrid queries use Qdrant's `query_points` with two `prefetch` branches (dense + sparse) and `FusionQuery(fusion=Rrf)` — no client-side score fusion. Dense and sparse scores are on incomparable scales; rank-based RRF on the server is the only correct fusion (REQUIREMENTS.md anti-pattern: "Client-side or fixed-weight score fusion"). Named vector keys are `"dense"` and `"sparse"`.
- **D-12:** **Prefetch limit ≥ main `limit + offset`** on each branch (Pitfall: prefetch < limit+offset → empty/short hybrid results). Keep it tight — `limit + offset` headroom, **not** 10× (over-fetch = slow/high-memory queries as the collection grows). Exact multiplier is planner/executor discretion within this bound.
- **D-13:** **`Modifier.IDF` set on the sparse vector at collection-creation time** (in `sparse_vectors_config`). Forgetting it silently drops BM25-style weighting. This is part of the D-05 create-path change.
- **D-14:** **Phase 7 payload filters must keep working in every mode.** The existing filter-builder block (`search.py:84–92`) is reused **verbatim** and applied identically across dense/sparse/hybrid. Confirm keyword payload indexes (`ensure_payload_indexes`, already called inside `reindex()`) survive the named-vector recreate so filtered hybrid search never full-scans.

### Claude's Discretion
- Exact `fastembed` model name / BM25 variant, the precise prefetch headroom multiplier (within D-12's `≥ limit+offset`, not 10× bound), and whether the migration is a new CLI subcommand vs a `--hybrid` flag on the existing reindex path — planner/executor discretion.
- Whether sparse-vector construction lives directly in `qdrant_store.py` or in a small new `plugins/builtin/sparse_embedder.py` — implementation detail, as long as the plugin ethos (D-01) and the `VectorPoint.sparse` optional field (default `None`, back-compat) hold.
- Precise error type/message wording for the fail-loud contract (D-10), as long as it names the missing vector and the remediation.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 10: Hybrid Retrieval" — goal + 4 success criteria + the LIVE MIGRATION note (verify `query_points`/`FusionQuery`/`SparseVectorParams`/`Modifier.IDF` vs qdrant-client 1.18; server ≥ 1.10; validate reindex on a copy first; alias-keep rollback).
- `.planning/REQUIREMENTS.md` — RETR-01, RETR-03 (full acceptance text) + Out-of-Scope anti-patterns (client/fixed-weight fusion; GPU sparse encoders; OpenSearch superseded by native sparse+RRF).

### Research (v2.0, HIGH confidence)
- `.planning/research/SUMMARY.md` §"Phase 10 — Hybrid Retrieval" + "Research Flags" (lines ~91–95, 112–139) — reindex+re-embed; fastembed BM25 + Modifier.IDF; prefetch ≥ limit+offset; server ≥ 1.10; sparse-encoder decision to confirm in discussion; `fastembed` absent / `rank_bm25` present.
- `.planning/research/ARCHITECTURE.md` §"2. Sparse / hybrid search (RETR-01/02)" (lines ~110–132, 207–208, 218–237, 265–301) — the critical migration fact (named vectors required); `reindex()` alias-swap is purpose-built; `query_points` + `prefetch` + `FusionQuery(RRF)`; `VectorPoint.sparse` optional; per-file change table.
- `.planning/research/PITFALLS.md` (lines ~257–260, 269, 274, 292, 308, 321, 340, 347–349) — client↔server version gap; prefetch limit; IDF modifier; partial-collection/parity; over-fetch; silent-fallback fail-loud; official Qdrant 1.10 hybrid-query docs.

### Prior-phase context (patterns to mirror)
- `.planning/phases/07-metadata-foundation/07-CONTEXT.md` — additive/back-compat signature convention; `search.py:84–92` filter builder; `ensure_payload_indexes()`; filters "only effective on points indexed after PAYLOAD-01, or after a reindex" (D-14 relies on this).
- `.planning/phases/09-storage-segmentation/09-CONTEXT.md` — session-boundary rule; additive-kwarg default convention; silver-zone key layout the re-embedding migration reads chunk text from.

### Code touch points
- `src/knowledge_lake/plugins/builtin/qdrant_store.py` — `ensure_aliased_collection` (line 103), `reindex` (line 235, currently unnamed `vectors_config`), `search` (line 324, `query_points` at 348), `upsert` (298), `copy_all_points` (198), `ensure_payload_indexes` (143), `get_collection_dim` (293, reads `params.vectors.size`).
- `src/knowledge_lake/pipeline/search.py` — `search()` (line 34), filter builder (lines 84–92, reuse verbatim), qdrant model imports (line 25); add `mode`/`sparse_query`.
- `src/knowledge_lake/pipeline/index.py` — `index()` (52) upsert path + `VectorPoint` build (143–182); `reindex_collection()` (189, drives migration `upsert_fn`).
- `src/knowledge_lake/plugins/protocols.py` — `VectorPoint` (line 83, add optional `sparse`); `EmbedderPlugin` (128); `VectorStorePlugin.search` signature (add keyword-only `mode`/`sparse_query`).
- `src/knowledge_lake/config/settings.py` — add `SearchSettings` nested `BaseModel` (mirror `IndexSettings` at line 282) + a `search: SearchSettings` field on `Settings` (line 302); env `KLAKE_SEARCH__MODE` via `env_nested_delimiter="__"`.
- `src/knowledge_lake/cli/app.py` — `cmd_search` (line 672) — add `--mode`.
- `src/knowledge_lake/api/app.py` (search endpoint, line 155) + `src/knowledge_lake/api/schemas.py` (`SearchParams` line 30, `SearchHit` line 57) — add `mode` param.
- `pyproject.toml` — `qdrant-client==1.18.0` (line 19), `sentence-transformers==5.6.0` (line 18); add `fastembed` (D-01).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`reindex(alias, dim, upsert_fn)` alias-swap (qdrant_store.py:235):** zero-downtime create→populate→atomic-alias-repoint is exactly the migration primitive needed. It already calls `ensure_payload_indexes()` on the new physical collection before the swap (preserves D-14 filters). The only changes: named-vector create config + a re-embedding `upsert_fn` + a parity gate before the alias operation.
- **`reindex_collection()` (index.py:189):** the existing driver that resolves dim and calls `vstore.reindex(...)` with a `_copy_fn`. The hybrid migration swaps `_copy_fn` for a re-embedding function.
- **`ensure_payload_indexes()` (qdrant_store.py:143):** already recreates keyword indexes on every reindexed collection — Phase 7 filters keep working through the named-vector recreate for free.
- **`search.py:84–92` filter builder:** the `must` condition list is mode-agnostic — reuse it verbatim for dense/sparse/hybrid (D-14).
- **`IndexSettings` (settings.py:282):** the exact nested-`BaseModel` + `settings.index` pattern to copy for `SearchSettings` / `settings.search`.
- **`rank_bm25` is already installed** (fallback per D-01); `fastembed` is **not** installed yet (must be added); `qdrant-client==1.18.0` pinned in pyproject.

### Established Patterns
- **Additive, back-compat signatures (Phases 4/7/9):** new kwargs default to today's behavior (`mode="dense"`, `sparse_query=None`, `VectorPoint.sparse=None`) so existing callers and old indexed points keep working until they opt in.
- **Alias-keep rollback (`keep_old_collections=True`, settings.py):** `reindex()` never auto-drops the prior collection; an operator drops it after confirming the swap. This IS the migration rollback path — combine with the D-06 parity gate.
- **Session-boundary rule (Phase 9):** the re-embedding migration reads chunk text within a `get_session()` block; do not carry ORM objects across session boundaries.
- **Nested settings via `KLAKE_*__*` (settings.py:314):** `KLAKE_SEARCH__MODE` resolves to `settings.search.mode` through `env_nested_delimiter="__"` — no custom parsing.

### Integration Points
- `qdrant_store.ensure_aliased_collection` / `reindex` create-paths ← named `vectors_config={"dense":...}` + `sparse_vectors_config={"sparse": SparseVectorParams(modifier=Modifier.IDF)}`; `get_collection_dim` updated for named shape.
- `index()` upsert ← produces dense **and** sparse named vectors per `VectorPoint`.
- `qdrant_store.search` ← `query_points` with dense+sparse `prefetch` (limit ≥ limit+offset) + `FusionQuery(Rrf)` when `mode=hybrid`; single-branch for `dense`/`sparse`; fail-loud when requested vectors absent.
- `pipeline.search()` ← `mode` (default `settings.search.mode`) → CLI `--mode` + API `?mode=`.
- `settings.search.mode` ← new `SearchSettings`; server-version preflight gate ahead of migration + hybrid queries.
</code_context>

<specifics>
## Specific Ideas

- **Named vector keys are literally `"dense"` and `"sparse"`** — the dense named vector preserves the current `klake_chunks` dimensionality; sparse is BM25 with `Modifier.IDF`.
- **A pure `copy_all_points` is explicitly insufficient** for this migration — it cannot synthesize sparse vectors for old points, leaving a partial collection that only covers new chunks. Re-embedding every point is mandatory (D-05).
- **Fail-loud beats silent dense fallback** — RETR-03's whole point is that asking for `sparse`/`hybrid` on a collection without sparse vectors must error clearly (name the missing vector + remediation), never quietly return dense results the user didn't ask for.
- **Validate the reindex on a copy first** (research flag) — the live migration should be dry-run/validated against a collection copy before touching the aliased production collection; the parity gate + alias-keep make the real run reversible.
</specifics>

<deferred>
## Deferred Ideas

- **Retrieval-quality evaluation (RAGAS / Promptfoo, RRF-vs-dense A/B, recall@k)** — EVAL-01, deferred to v2.1. Phase 10 ships hybrid + mode switch; it does not measure retrieval quality.
- **Quality-score-aware ranking / boosting** — QUALITY-01, deferred to v2.1. `quality_score` stays a payload filter only; RRF fusion is rank-based, not quality-weighted.
- **GPU sparse encoders (SPLADE / miniCOIL)** — documented upgrade path beyond v2.0's CPU-BM25 default; not built here (REQUIREMENTS.md anti-pattern).
- **Backfilling/re-keying is N/A here** — but the same "old points lack the new capability until reindexed" coupling from Phase 7 applies: `dense` mode works on un-migrated collections; `hybrid`/`sparse` require the reindex.
- **Second search engine (OpenSearch full-text)** — superseded by native Qdrant sparse+RRF (old v1.0 RETR-02); explicitly not added.

None of the above were requested as scope — captured so they aren't lost.

</deferred>

---

*Phase: 10-hybrid-retrieval*
*Context gathered: 2026-07-10*
