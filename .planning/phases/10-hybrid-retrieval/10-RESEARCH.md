# Phase 10: Hybrid Retrieval - Research

**Researched:** 2026-07-10
**Domain:** Qdrant hybrid retrieval (named dense+sparse vectors, server-side RRF), fastembed BM25, live unnamed→named migration, pydantic-settings search-mode surface
**Confidence:** HIGH (every qdrant-client API claim introspected against the installed `qdrant-client==1.18.0` in `.venv`; fastembed pin read from the client's own extras metadata; BM25 model name cross-checked against official Qdrant docs)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Add `fastembed` as a new dependency; use Qdrant-native BM25 sparse embeddings with `Modifier.IDF` (not the installed `rank_bm25`). Biggest decision — re-confirm here. `rank_bm25` is the fallback only.
- **D-02:** BM25 is the CPU-friendly v2.0 default (DigitalOcean droplet). GPU encoders (SPLADE, miniCOIL) are deferred — do NOT pull them in.
- **D-03:** Sparse query-vector generation at search time uses the same `fastembed` BM25 path — no `rank_bm25` at query time. Server-side RRF replaces client-side BM25 scoring.
- **D-04:** Reuse the existing `reindex(alias, dim, upsert_fn)` alias-swap. Named-vector migration is a reindex, NOT an in-place ALTER — Qdrant cannot add sparse to an unnamed collection; dense+sparse coexistence requires the dense vector to be **named**.
- **D-05:** Migration `upsert_fn` must **re-embed**, not copy. Re-read chunk text and produce BOTH dense + sparse named vectors for every point. `reindex()`/`ensure_aliased_collection()` currently hard-code unnamed `vectors_config=VectorParams(...)`; both move to `vectors_config={"dense": VectorParams(...)}` + `sparse_vectors_config={"sparse": SparseVectorParams(modifier=Modifier.IDF)}`. `get_collection_dim()` must be updated for the named shape.
- **D-06:** Point-count parity gate — verify new physical collection point count == old collection **before** the alias swap. Mismatch aborts the swap. `keep_old_collections=True` keeps the old collection until an operator drops it.
- **D-07:** Qdrant server ≥ 1.10 preflight before migration and before any hybrid query. Abort with a clear error if too old. Migration is operator-triggered (explicit CLI step), not an automatic startup migration; validate on a collection copy first.
- **D-08:** New nested `SearchSettings` model (`settings.search`, env `KLAKE_SEARCH__MODE`), mirroring `IndexSettings`. `mode: Literal["hybrid","dense","sparse"] = "hybrid"`. No loose top-level settings.
- **D-09:** `mode` is a per-request override: `pipeline.search()` gains `mode` (default `settings.search.mode`) → `klake search --mode …` + API `?mode=`. `VectorStorePlugin.search` gains keyword-only `mode="dense"` + `sparse_query=None` defaults so existing callers/old points are unaffected until opt-in.
- **D-10:** Fail loudly, never silently degrade. `hybrid`/`sparse` against a collection with no sparse vectors raises a clear error naming the missing vector + remediation (run the hybrid reindex). Do NOT fall back to dense. `dense` mode keeps working against old and migrated collections.
- **D-11:** Server-side RRF only. `query_points` with two `prefetch` branches (dense + sparse) + `FusionQuery(fusion=Rrf)` — no client-side fusion. Named vector keys are `"dense"` and `"sparse"`.
- **D-12:** Prefetch limit ≥ main `limit + offset` on each branch. Keep tight (`limit + offset` headroom, NOT 10×). Exact multiplier is executor discretion within this bound.
- **D-13:** `Modifier.IDF` set on the sparse vector at collection-creation time (in `sparse_vectors_config`). Forgetting it silently drops BM25 weighting.
- **D-14:** Phase 7 payload filters must keep working in every mode. Reuse the `search.py:84–92` filter builder verbatim, applied identically across dense/sparse/hybrid. Confirm `ensure_payload_indexes()` survives the named-vector recreate.

### Claude's Discretion
- Exact `fastembed` model name / BM25 variant; precise prefetch headroom multiplier (within `≥ limit+offset`, not 10×); whether the migration is a new CLI subcommand vs a `--hybrid` flag on the existing reindex path.
- Whether sparse-vector construction lives in `qdrant_store.py` or a new `plugins/builtin/sparse_embedder.py` — as long as the plugin ethos (D-01) and `VectorPoint.sparse` optional field (default `None`, back-compat) hold.
- Precise error type/message wording for the fail-loud contract (D-10), as long as it names the missing vector + remediation.

### Deferred Ideas (OUT OF SCOPE)
- Retrieval-quality evaluation (RAGAS / Promptfoo, RRF-vs-dense A/B, recall@k) — EVAL-01, v2.1.
- Quality-score-aware ranking / boosting — QUALITY-01, v2.1. `quality_score` stays a payload filter only.
- GPU sparse encoders (SPLADE / miniCOIL) — documented upgrade path, not built here.
- Backfilling/re-keying — N/A. `dense` works on un-migrated collections; `hybrid`/`sparse` require the reindex.
- Second search engine (OpenSearch full-text) — superseded by native Qdrant sparse+RRF; not added.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RETR-01 | Hybrid BM25 + dense retrieval using Qdrant named sparse + dense vectors with server-side RRF, delivered via the existing alias-swap reindex (unnamed→named recreate + re-embedding upsert so all points get sparse vectors). | §Standard Stack (fastembed pin + BM25 model), §Code Examples (create/upsert/hybrid-query snippets, all verified against installed 1.18.0), §The Live Migration (re-embedding `upsert_fn`, parity gate, named-vector create-path changes). |
| RETR-03 | Search mode configurable via `KLAKE_SEARCH__MODE=hybrid\|dense\|sparse` (default `hybrid`); a mode whose vectors are absent fails loudly. | §Search-Mode Surface (SearchSettings, signature extension, sparse-presence detection, fail-loud error), §Code Examples (dense/sparse single-mode queries, sparse-presence probe). |
</phase_requirements>

## Summary

Every locked CONTEXT decision is **feasible as written** against the installed `qdrant-client==1.18.0`. I introspected the venv directly: `query_points`, `Prefetch`, `FusionQuery`, `Fusion.RRF`, `SparseVector`, `NamedSparseVector`, `SparseVectorParams`, `SparseIndexParams`, `Modifier.IDF`, `create_collection(sparse_vectors_config=…)`, `PointStruct(vector={named})`, `client.info()` (server version), `client.count()` (parity), and the `qdrant_fastembed` integration shim are all present with the exact shapes the plan needs. `fastembed` is declared by qdrant-client itself as the `fastembed` extra pinned to `>=0.8,<0.9` — CPU-only (onnxruntime, no torch/GPU), correct for the droplet. The BM25 model is `Qdrant/bm25`, which by design emits IDF-less values that **require** `Modifier.IDF` server-side.

The most important stack finding that *simplifies* CONTEXT D-05: **chunk text is already stored in every point's payload** (`payload["text"]`, written by `index.py:158` since Phase 1). The re-embedding migration should read text from `payload["text"]` during the scroll — no registry/silver-zone join, no session-boundary handling. Dense vectors can be **reused** from the scroll (they don't change); only the **sparse** vector must be synthesized. Re-embedding dense as well is safe but wasteful — reuse is correct and cheaper.

The one genuinely non-obvious risk the plan MUST solve (not in CONTEXT): once collections are named, `upsert()` and the dense `search()` path must **branch on the collection's vector shape** (named dict vs legacy unnamed). Writing a named `{"dense": …}` vector into a legacy unnamed collection — or querying a named collection with a bare vector and no `using="dense"` — both raise on the server. D-09 ("dense works on old AND migrated collections") therefore requires a small shape-detection helper. See Pitfall 1 and Open Question 1.

**Primary recommendation:** Add `fastembed>=0.8,<0.9` (via `qdrant-client[fastembed]==1.18.0` or a direct pin), model `Qdrant/bm25` with `Modifier.IDF`. Make all create-paths born-named (`{"dense": VectorParams}` + `sparse_vectors_config={"sparse": SparseVectorParams(modifier=Modifier.IDF)}`). Migrate legacy collections via a re-embedding `upsert_fn` that reads `payload["text"]`, reuses the scrolled dense vector, and synthesizes sparse; add a `count()`-based parity gate inside `reindex()` before the alias swap; gate everything behind a `client.info()` server ≥ 1.10 preflight; add a vector-shape branch to `upsert()`/`search()` for back-compat.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Sparse (BM25) vector generation | Vector-store plugin (`plugins/builtin/`) | fastembed (local ONNX inference) | D-01 plugin ethos: sparse construction lives inside the store boundary; keeps corpus-IDF state on the Qdrant server, not in our process. |
| Dense vector generation | Embedder plugin (`get_embedder`) | LiteLLM / sentence-transformers | Unchanged from today; dense embeddings already flow through the embedder seam. |
| RRF fusion | Qdrant server (Query API) | — | D-11: rank-based fusion of incomparable score scales must be server-side. |
| Named-vector collection lifecycle / migration | Vector-store plugin (`qdrant_store.py`) | Registry (`vector_collections` alias rows) | Reindex + alias swap + parity gate is store-owned; registry records alias→physical mapping (existing pattern). |
| Server-version preflight | Vector-store plugin (`client.info()`) | CLI (surfaces abort to operator) | Server capability check belongs next to the client that uses the capability. |
| Search-mode config + fail-loud contract | Config (`SearchSettings`) + pipeline (`search()`) | CLI/API surfaces | Mode is a request/config concern threaded down to the store, which enforces fail-loud based on collection introspection. |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| qdrant-client | 1.18.0 (installed, pinned) | Named dense+sparse collections, hybrid `query_points`, RRF, sparse params, server-version + count | Already the vector-store backend; all hybrid APIs present and verified. |
| fastembed | `>=0.8,<0.9` (NEW) | Local CPU BM25 sparse embeddings (`Qdrant/bm25`) | It is qdrant-client 1.18's **own** declared `fastembed` extra; official Qdrant project; ONNX/CPU, no torch/GPU. `[VERIFIED: qdrant-client 1.18.0 extras metadata]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rank_bm25 | installed | Fallback only (D-01) | Only if adding `fastembed` is rejected; forces us to own vocabulary/IDF state. Not recommended. |
| packaging | (transitive, present via many deps) | Robust server-version parse in the ≥1.10 preflight | Prefer `packaging.version.Version` over naive `str.split(".")` because `info.version` may carry suffixes (e.g. `1.15.1-rc`). |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `fastembed` `Qdrant/bm25` | `rank_bm25` (installed) | We'd own shared-vocabulary/IDF state and client-side scoring — more moving parts, breaks the "let the server compute IDF" model. D-01 already rejects this. |
| Direct `fastembed.SparseTextEmbedding` | qdrant-client `client.add()`/`SparseTextEmbedding` integration shim | The `client.add()` shim manages its own collection schema and hides the named-vector config we explicitly need to control (dense reuse, IDF modifier, alias/reindex). Prefer constructing `SparseVector` ourselves and using the explicit `create_collection`/`upsert`/`query_points` path. `[VERIFIED: qdrant_client.qdrant_fastembed shim present but too opinionated for the alias/reindex flow]` |
| BM25 sparse | SPLADE / miniCOIL | GPU-bound; explicitly deferred (D-02, REQUIREMENTS anti-pattern). |

**Installation:**
```bash
uv add 'fastembed>=0.8,<0.9'
# or, equivalently, pin the client extra:
# uv add 'qdrant-client[fastembed]==1.18.0'
```
`pyproject.toml`: add `fastembed>=0.8,<0.9` next to `qdrant-client==1.18.0` (line ~19).

**Version verification performed:**
- `importlib.metadata.version("qdrant-client")` → `1.18.0` (matches pin). `[VERIFIED: venv introspection]`
- qdrant-client declares `fastembed (>=0.8,<0.9) ; extra == "fastembed"` and `fastembed-gpu (>=0.8,<0.9) ; extra == "fastembed-gpu"`. Use the CPU `fastembed`, never `fastembed-gpu`. `[VERIFIED: importlib.metadata.requires("qdrant-client")]`
- `fastembed` is NOT yet installed in the venv; `rank_bm25` IS installed. `[VERIFIED: import probe]`

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| fastembed | PyPI | mature (Qdrant official, 2023+) | multi-million/mo | github.com/qdrant/fastembed | OK | Approved — it is qdrant-client's own declared extra; publisher == Qdrant (same org as the already-trusted qdrant-client). |
| qdrant-client | PyPI | mature | multi-million/mo | github.com/qdrant/qdrant-client | OK | Already installed/pinned; unchanged. |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none.

> `fastembed` was not discovered via WebSearch/training guesswork — it is named directly by the installed `qdrant-client==1.18.0` package metadata as its own optional extra, which is the strongest possible provenance. `[VERIFIED: qdrant-client extras metadata]` The BM25 model identifier `Qdrant/bm25` is `[CITED: huggingface.co/Qdrant/bm25, qdrant.tech BM25 docs]` and cross-confirmed against the `qdrant_client.qdrant_fastembed` shim's `IDF_EMBEDDING_MODELS` handling.

## Architecture Patterns

### System Architecture Diagram

```
                          KLAKE_SEARCH__MODE (hybrid|dense|sparse, default hybrid)
                                       │
 CLI  klake search --mode ─┐          │        ┌─ API  GET /search?mode=
                            └──────────┼────────┘
                                       ▼
                           pipeline/search.py :: search(mode=…)
                             │  1. embed query (dense)         ← get_embedder (unchanged)
                             │  2. build sparse query vector   ← fastembed Qdrant/bm25 .query_embed()  [mode in {hybrid,sparse}]
                             │  3. build payload Filter         ← search.py:84–92 (reused verbatim, D-14)
                             ▼
             QdrantVectorStore.search(collection, query, top_k, query_filter,
                                      *, mode="dense", sparse_query=None)
                             │
                             │  preflight: client.info().version ≥ 1.10  (D-07)
                             │  introspect: params.vectors (named?) + params.sparse_vectors (present?)  (D-10)
                             │     └─ mode∈{hybrid,sparse} & no sparse  ─────► RAISE (fail loud, name missing vector)
                             ▼
   ┌──────────────── client.query_points(collection, …) ────────────────┐
   │  mode=dense   : query=dense_vec, using="dense"          (named) OR bare vector (legacy unnamed)
   │  mode=sparse  : query=SparseVector(idx,vals), using="sparse"
   │  mode=hybrid  : prefetch=[ Prefetch(dense,  using="dense",  filter=F, limit=k+off),
   │                            Prefetch(sparse, using="sparse", filter=F, limit=k+off) ],
   │                 query=FusionQuery(fusion=Fusion.RRF), limit=k, offset=off   ← server-side RRF (D-11)
   └────────────────────────────────────────────────────────────────────┘
                             ▼
                     list[Hit] (score, payload with citation fields)

  ─────────────────────── LIVE MIGRATION (operator-triggered, RETR-01) ───────────────────────
   klake reindex --hybrid  (or a new subcommand)
        └─ reindex_collection() → vstore.reindex(alias, dim, upsert_fn=re_embed_fn)
              1. create next_physical: {"dense": VectorParams(dim)} + sparse_vectors_config{ "sparse": IDF }
              2. re_embed_fn(next_physical): scroll old_physical (with_vectors+with_payload)
                     per point → reuse scrolled dense vec; sparse = bm25(payload["text"]); upsert NAMED
              3. ensure_payload_indexes(next_physical)   ← keyword indexes survive recreate (D-14)
              4. PARITY GATE: count(old) == count(new)?  no → RAISE, DO NOT swap alias (D-06)
              5. atomic update_collection_aliases(delete old-alias + create new-alias)
              6. old_physical retained (keep_old_collections=True) — operator drops after verifying
```

### Recommended Project Structure
```
src/knowledge_lake/
├── plugins/builtin/
│   ├── qdrant_store.py        # named create-paths, hybrid search, parity gate, server preflight
│   └── sparse_embedder.py     # NEW (optional, Claude's discretion) — fastembed Qdrant/bm25 wrapper
├── plugins/protocols.py       # VectorPoint.sparse (Optional), VectorStorePlugin.search(mode, sparse_query)
├── pipeline/
│   ├── index.py               # upsert path builds dense+sparse; migration re-embed upsert_fn
│   └── search.py              # thread mode + sparse_query; reuse filter builder verbatim
├── config/settings.py         # SearchSettings nested model (mirror IndexSettings)
├── cli/app.py                 # search --mode ; reindex --hybrid (or new subcommand)
└── api/{app.py,schemas.py}    # ?mode= query param; SearchParams.mode
```

### Pattern 1: Born-named collections (fresh deployments never unnamed)
**What:** All create-paths (`ensure_collection`, `ensure_aliased_collection`, `reindex`) create named dense + sparse from the start.
**When to use:** Every collection created after Phase 10 ships.
**Why:** Eliminates the "unnamed collection can't take a named upsert" failure for new deployments; only legacy pre-Phase-10 collections need the migration.

### Pattern 2: Vector-shape branch for back-compat (D-09)
**What:** `upsert()` and the dense `search()` path detect whether the target collection uses named vectors (via `get_collection(...).config.params.vectors` being a `dict`) and build the point/query accordingly.
**When to use:** Any store method that writes or queries vectors, so `dense` mode keeps working against legacy unnamed collections until they are migrated.

### Anti-Patterns to Avoid
- **Client-side / fixed-weight score fusion** — dense & sparse scores are incomparable; use server-side `FusionQuery(Fusion.RRF)` (D-11, REQUIREMENTS anti-pattern).
- **Pure `copy_all_points` for the migration** — copies dense but cannot synthesize sparse → partial collection (D-05). Re-embed sparse.
- **Bare-vector query against a named collection** — must pass `using="dense"`; otherwise the server rejects it on a multi-vector collection.
- **Silent dense fallback** — asking for `hybrid`/`sparse` on a sparse-less collection MUST raise (D-10).
- **Forgetting `Modifier.IDF`** — `Qdrant/bm25` values are intentionally IDF-less; without the modifier, BM25 weighting silently degrades (D-13).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| BM25 sparse vectors | Custom TF/IDF vocabulary + scorer over `rank_bm25` | `fastembed` `Qdrant/bm25` + server `Modifier.IDF` | IDF is computed & kept current server-side; no shared-vocabulary state to own (D-01/D-03). |
| Score fusion | Weighted dense/sparse blend | `FusionQuery(fusion=Fusion.RRF)` | Rank-based, scale-free, server-side (D-11). |
| Server version compare | `float(version)` or naive split | `packaging.version.Version(info.version)` | Handles multi-part + suffixed versions robustly (D-07). |
| Zero-downtime migration | New bespoke swap logic | Existing `reindex()` alias-swap + `keep_old_collections` | Purpose-built primitive; only needs a named create-path, a re-embed `upsert_fn`, and a parity gate (D-04/D-06). |

**Key insight:** The two hardest sub-problems (IDF-correct BM25 and correct rank fusion) are both solved by pushing them onto the Qdrant server. Our code only assembles `SparseVector(indices, values)` and declares `Modifier.IDF` at create time.

## Runtime State Inventory

> Rename/refactor/migration phase — LIVE DATA MIGRATION (Qdrant unnamed→named recreate + re-embedding upsert).

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **Qdrant collections behind the `klake_chunks` alias** (e.g. `klake_chunks_v1/_v2`), currently **unnamed** `VectorParams`. Every point carries `payload["text"]` (from `index.py:158`), `payload["chunk_id"]`, and citation/provenance fields. | **Data migration (re-embed):** recreate as named dense+sparse and re-upsert every point with a synthesized sparse vector. `payload["text"]` is the re-embed source — no external join needed. |
| Live service config | Qdrant server runs via docker-compose (`settings.qdrant_url`, default `http://localhost:6333`). **Server version is runtime state not in git** — must be probed with `client.info()` (D-07). Alias→physical mapping is also recorded in Postgres `vector_collections` rows (registry). | **Preflight:** assert server ≥ 1.10 before migrate/query. **Registry:** `reindex_collection()` already registers the new alias row — keep that call. |
| OS-registered state | None — no OS-level task/service embeds vector-shape assumptions. | None (verified: migration is operator-triggered CLI, not a scheduled/registered job). |
| Secrets/env vars | New env var **`KLAKE_SEARCH__MODE`** (additive, default `hybrid`). No secret material. `KLAKE_INDEX__KEEP_OLD_COLLECTIONS` already exists and governs rollback. | Code adds `SearchSettings`; no secret rotation. |
| Build artifacts / installed packages | `fastembed` not yet installed; adding it downloads the `Qdrant/bm25` ONNX model from HuggingFace on first use (network + local cache under `~/.cache/fastembed` or HF cache). | `uv add fastembed>=0.8,<0.9`; ensure first-run model download is available on the droplet (or pre-warm the cache). Flag for the Environment Availability section. |

**The canonical question — after every file is updated, what runtime state still has the old shape?** The **physical Qdrant collections** remain unnamed until the operator runs the hybrid reindex. Code must therefore tolerate both shapes (Pitfall 1) and fail loud when a sparse-requiring mode hits an un-migrated collection (D-10).

## Common Pitfalls

### Pitfall 1: Named upsert into a legacy unnamed collection (and bare query into a named one)
**What goes wrong:** After Phase 10, `upsert()` builds `vector={"dense": …}` and the dense `search()` uses `using="dense"`. Against a **not-yet-migrated** unnamed collection, the named upsert is rejected; against a **migrated** named collection, a bare-vector query (no `using`) is rejected. Either breaks the D-09 promise that `dense` works on both.
**Why it happens:** The unnamed→named shape is a per-collection runtime fact; the alias hides which shape is live.
**How to avoid:** Add a tiny cached helper, e.g. `_is_named(collection) -> bool` reading `get_collection(collection).config.params.vectors` (`dict` ⇒ named). `upsert()` writes `{"dense": v}`(+`"sparse"` when present) for named, bare `v` for unnamed. Dense `search()` passes `using="dense"` only for named collections. Fresh collections are born-named (Pattern 1), so this branch is only exercised by legacy collections pre-migration.
**Warning signs:** Qdrant `400`/`Wrong input` errors on upsert or query after deploy but before running the hybrid reindex.

### Pitfall 2: `get_collection_dim()` crashes on named collections
**What goes wrong:** Current code returns `info.config.params.vectors.size`. For a named collection, `params.vectors` is a `Dict[str, VectorParams]` — `.size` raises `AttributeError`. `reindex_collection()` calls this to resolve `dim`, so the migration itself would crash.
**Why it happens:** The annotation is `Union[VectorParams, Dict[str, VectorParams], None]`. `[VERIFIED: CollectionParams.model_fields introspection]`
**How to avoid:**
```python
def get_collection_dim(self, alias: str) -> int:
    vectors = self._client.get_collection(alias).config.params.vectors
    if isinstance(vectors, dict):          # named
        return vectors["dense"].size
    return vectors.size                    # legacy unnamed
```

### Pitfall 3: Prefetch limit < limit + offset → short/empty hybrid results
**What goes wrong:** Each prefetch branch is fused; if a branch fetched fewer than `limit + offset` candidates, RRF has too few to page through, yielding short or empty results at non-zero offset.
**How to avoid:** Set each `Prefetch(limit=top_k + offset)` (D-12). Keep it tight — not 10×.
**Warning signs:** Correct results at offset 0, empty at offset>0; hybrid returns fewer than `top_k` on well-populated collections.

### Pitfall 4: Client version ≠ server version
**What goes wrong:** `qdrant-client==1.18.0` has all the Query-API classes, but the **running server** may predate 1.10 (Query API / IDF sparse). The migration would create a broken collection or queries would fail obscurely.
**How to avoid:** `client.info()` returns `VersionInfo(title, version, commit)` — the **server** version. Parse with `packaging.version.Version` and assert ≥ `1.10` before migrate/query; raise a clear operator-facing error otherwise (D-07). `[VERIFIED: QdrantClient.info() → VersionInfo]`

### Pitfall 5: Parity gate placed after the alias swap
**What goes wrong:** The existing `reindex()` calls `upsert_fn`, `ensure_payload_indexes`, then **immediately** swaps the alias. A parity check added *after* the swap can't prevent a bad swap.
**How to avoid:** Insert the `count(old) == count(new)` gate **inside `reindex()` between `upsert_fn`/`ensure_payload_indexes` and `update_collection_aliases`**; raise before building the alias ops so the alias stays on the old collection (D-06). Skip the gate when `old_physical is None` (first reindex). Use `client.count(name, exact=True)`. `[VERIFIED: QdrantClient.count present]`

### Pitfall 6: Reusing `SparseTextEmbedding.embed()` for queries
**What goes wrong:** For BM25, document embeddings and query embeddings differ. Using the document method at query time yields wrong sparse weights.
**How to avoid:** Use `.embed(texts)` (or `.passage_embed`) at index time and `.query_embed(text)` at query time. Both return objects with `.indices` / `.values` arrays → wrap in `models.SparseVector(indices=…, values=…)`. `[CITED: qdrant.tech BM25 docs]`

## Code Examples

> All snippets below use symbols confirmed present in the installed `qdrant-client==1.18.0`. `[VERIFIED: venv introspection]`

### (a) Create a named dense + sparse collection with IDF (D-05, D-13)
```python
from qdrant_client.models import (
    VectorParams, Distance, SparseVectorParams, SparseIndexParams, Modifier,
)

client.create_collection(
    collection_name=physical,                       # e.g. "klake_chunks_v2"
    vectors_config={"dense": VectorParams(size=dim, distance=Distance.COSINE)},
    sparse_vectors_config={
        "sparse": SparseVectorParams(modifier=Modifier.IDF)   # IDF computed server-side
    },
)
# then, unchanged: self.ensure_payload_indexes(physical)  ← D-14 keyword indexes survive
```

### (b) Build a BM25 sparse vector with fastembed (index + query)
```python
from fastembed import SparseTextEmbedding
from qdrant_client.models import SparseVector

_bm25 = SparseTextEmbedding(model_name="Qdrant/bm25")   # CPU ONNX; downloads once

def sparse_doc(text: str) -> SparseVector:
    e = next(iter(_bm25.embed([text])))        # SparseEmbedding(.indices, .values)
    return SparseVector(indices=e.indices.tolist(), values=e.values.tolist())

def sparse_query(text: str) -> SparseVector:
    e = next(iter(_bm25.query_embed(text)))    # query-side embedding (Pitfall 6)
    return SparseVector(indices=e.indices.tolist(), values=e.values.tolist())
```

### (c) Upsert a point carrying BOTH named vectors (D-05; Pitfall 1 for legacy shape)
```python
from qdrant_client.models import PointStruct, SparseVector

point = PointStruct(
    id=qdrant_point_id,
    vector={
        "dense":  dense_vec,                            # list[float]
        "sparse": SparseVector(indices=idx, values=vals),
    },
    payload=payload,                                    # unchanged citation/provenance fields
)
client.upsert(collection_name=named_collection, points=[point])
# Legacy unnamed collection (pre-migration): vector=dense_vec (bare), no sparse — see Pitfall 1.
```

### (d) Hybrid query: two prefetch branches + RRF + Phase-7 filter (D-11, D-12, D-14)
```python
from qdrant_client.models import Prefetch, FusionQuery, Fusion, SparseVector

branch_limit = top_k + offset                           # D-12: ≥ limit + offset, tight
resp = client.query_points(
    collection_name=collection,
    prefetch=[
        Prefetch(query=dense_vec, using="dense",
                 filter=query_filter, limit=branch_limit),          # Prefetch field is `filter`
        Prefetch(query=SparseVector(indices=idx, values=vals), using="sparse",
                 filter=query_filter, limit=branch_limit),
    ],
    query=FusionQuery(fusion=Fusion.RRF),               # server-side rank fusion
    query_filter=query_filter,                          # also apply at top level (belt-and-suspenders)
    limit=top_k,
    offset=offset,
    with_payload=True,
)
hits = resp.points   # each: .id, .score, .payload
```
> NOTE: `Prefetch`'s payload-filter field is named `filter` (not `query_filter`). `[VERIFIED: Prefetch.model_fields → ['prefetch','query','using','filter','params','score_threshold','limit','lookup_from']]` The top-level call uses `query_filter`. The same reused `Filter` object (search.py:84–92) attaches to **both** branches and the top level — apply it on each prefetch branch so each pre-fused candidate set is already narrowed (avoids full-scan and keeps semantics identical across modes, D-14).

### (e) Dense-only and sparse-only single-mode queries (D-09)
```python
# dense-only (named collection):
client.query_points(collection_name=c, query=dense_vec, using="dense",
                    query_filter=query_filter, limit=top_k, offset=offset, with_payload=True)

# dense-only (legacy unnamed collection — Pitfall 1): omit `using`
client.query_points(collection_name=c, query=dense_vec,
                    query_filter=query_filter, limit=top_k, offset=offset, with_payload=True)

# sparse-only:
from qdrant_client.models import SparseVector
client.query_points(collection_name=c,
                    query=SparseVector(indices=idx, values=vals), using="sparse",
                    query_filter=query_filter, limit=top_k, offset=offset, with_payload=True)
```

### (f) Server-version preflight (D-07)
```python
from packaging.version import Version

def assert_server_supports_hybrid(client) -> None:
    info = client.info()                    # VersionInfo(title, version, commit)  ← SERVER version
    if Version(info.version) < Version("1.10"):
        raise RuntimeError(
            f"Qdrant server {info.version} is too old for hybrid retrieval; "
            f"the Query API + IDF sparse vectors require server >= 1.10. "
            f"Upgrade the Qdrant server (client is 1.18)."
        )
```

### (g) Sparse-presence probe for the fail-loud contract (D-10)
```python
def _collection_has_sparse(client, collection: str) -> bool:
    params = client.get_collection(collection).config.params
    sparse = params.sparse_vectors            # Optional[Dict[str, SparseVectorParams]]
    return bool(sparse and "sparse" in sparse)

# in search(), before querying:
if mode in ("hybrid", "sparse") and not _collection_has_sparse(client, collection):
    raise <ClearError>(
        f"mode={mode!r} requires a 'sparse' vector, but collection {collection!r} has none. "
        f"Run the hybrid reindex (klake reindex --hybrid) to migrate this collection. "
        f"(dense mode still works against it.)"
    )
```
> `[VERIFIED: CollectionParams.sparse_vectors is Optional[Dict[str, SparseVectorParams]]]`

### (h) Migration re-embedding upsert_fn (reads payload["text"], reuses dense) (D-05, D-06)
```python
def re_embed_fn(new_physical: str) -> None:
    next_offset = None
    while True:
        records, next_offset = client.scroll(
            collection_name=old_physical, limit=256, offset=next_offset,
            with_vectors=True, with_payload=True,
        )
        if not records:
            break
        pts = []
        for r in records:
            text = (r.payload or {}).get("text", "")
            dense = r.vector if isinstance(r.vector, list) else r.vector.get("dense")  # reuse scrolled dense
            pts.append(PointStruct(
                id=r.id,
                vector={"dense": dense, "sparse": sparse_doc(text)},   # only sparse is synthesized
                payload=r.payload,
            ))
        client.upsert(collection_name=new_physical, points=pts)
        if next_offset is None:
            break
# Parity gate then runs inside reindex(): count(old_physical) == count(new_physical) before alias swap.
```
> If `payload["text"]` is empty for some legacy point (shouldn't happen post-Phase-1, but guard it), that point cannot get a meaningful sparse vector — either re-embed dense from the registry chunk text or skip+log. This is a rare edge; count parity will flag any drops.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `search()` / `search_batch()` legacy methods | `query_points()` with `prefetch` + `FusionQuery` | Qdrant server 1.10 (2024) / client Query API | Server-side hybrid + RRF in one round-trip; no client fusion. |
| Unnamed single `VectorParams` | Named `{"dense": …}` + `sparse_vectors_config` | Sparse vectors GA | Dense+sparse coexistence requires named dense (D-04). |
| Client-side BM25 (`rank_bm25`) | `fastembed Qdrant/bm25` + server `Modifier.IDF` | fastembed sparse models | IDF maintained server-side; no vocabulary state to own. |

**Deprecated/outdated:**
- Client-side/fixed-weight fusion — superseded by server RRF.
- `rank_bm25` for this pipeline — retained only as the D-01 fallback.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `Qdrant/bm25` is the correct fastembed BM25 model name and requires `Modifier.IDF`. | Standard Stack, Code Examples (b) | Wrong model name → runtime download error. Mitigated: `[CITED: huggingface.co/Qdrant/bm25 + qdrant.tech BM25 docs]` and the `qdrant_fastembed` shim's `IDF_EMBEDDING_MODELS` path corroborates. Executor should confirm on first `fastembed` install (the venv doesn't yet have fastembed to introspect the live model registry). |
| A2 | Qdrant server ≥ 1.10 is the exact floor for Query-API hybrid + IDF sparse. | D-07 preflight | If the running server is older, migration/query fail — but the preflight (example f) catches this loudly before any damage. Low risk. |
| A3 | Every legacy point carries a usable `payload["text"]` to re-embed from. | Migration | If some pre-Phase-1 point lacks text, its sparse vector is empty; parity gate + a guard (example h) surface it. Low risk (text stored since Phase 1). |
| A4 | fastembed 0.8.x installs cleanly CPU-only on the droplet (onnxruntime, no torch). | Environment Availability | If a heavy/conflicting dep appears, fall back to `rank_bm25` (D-01 fallback). Must be verified at install time — fastembed isn't in the venv yet. Flagged in Environment Availability + Validation. |

## Open Questions

1. **Back-compat for `dense` mode against un-migrated collections (Pitfall 1).**
   - What we know: fresh collections should be born-named; legacy collections stay unnamed until the operator reindexes. D-09 requires `dense` to work on both.
   - What's unclear: whether the planner wants a shape-detection branch in `upsert()`/`search()` (recommended) or to require migration before any further indexing (simpler but breaks continued indexing into a legacy collection).
   - Recommendation: implement the cached `_is_named(collection)` branch — it fully honors D-09 and is ~10 lines. Cover it with a unit test.
2. **fastembed install footprint on the droplet.**
   - What we know: it's qdrant-client's own CPU extra (onnxruntime), and the model downloads on first use.
   - What's unclear: exact transitive size and whether outbound HF access is available at runtime on the droplet.
   - Recommendation: a `checkpoint:human-verify` after `uv add fastembed` — install, import `SparseTextEmbedding("Qdrant/bm25")`, embed one string, confirm no torch/GPU pulled and the model caches. If it fails, D-01 fallback to `rank_bm25`.
3. **Migration surface: `klake reindex --hybrid` flag vs new subcommand (Claude's discretion, D-04).**
   - Recommendation: a `--hybrid` flag on the existing `reindex` command path is lowest-surface and reuses `reindex_collection()`; the flag swaps `_copy_fn` → `re_embed_fn` and asserts the server preflight first.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Qdrant **server** ≥ 1.10 | Hybrid Query API, IDF sparse (D-07) | Probe at runtime via `client.info()` | — (docker-compose managed) | None — hard block; preflight aborts loudly if too old. |
| `qdrant-client` | All store ops | ✓ (installed) | 1.18.0 | — |
| `fastembed` | BM25 sparse (D-01) | ✗ (not installed) | target `>=0.8,<0.9` | `rank_bm25` (installed) if install/CPU-fit fails |
| `Qdrant/bm25` ONNX model | Sparse inference | ✗ (downloads on first use) | via fastembed | Pre-warm HF cache on the droplet |
| `packaging` | Version preflight parse | ✓ (transitive) | — | Manual tuple parse |

**Missing dependencies with no fallback:**
- Qdrant server ≥ 1.10 — must be running; the preflight (example f) turns "too old" into a clear operator error rather than a broken collection.

**Missing dependencies with fallback:**
- `fastembed` — not yet installed; `rank_bm25` (already present) is the D-01 fallback if the CPU install conflicts. Verify at install time (Open Question 2).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x (`pytest>=8.0`, `pytest-asyncio`, `pytest-cov`) `[VERIFIED: pyproject]` |
| Config file | `pyproject.toml [tool.pytest.ini_options]` — `testpaths=["tests"]`, `asyncio_mode="auto"`, markers `integration`, `browser` |
| Quick run command | `uv run pytest tests/unit -q` |
| Full suite command | `uv run pytest -q` (integration needs a live Qdrant ≥ 1.10) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RETR-01 | Named create-path builds `{"dense": VectorParams}` + `sparse_vectors_config{"sparse": IDF}` | unit (mock client) | `pytest tests/unit/test_qdrant_hybrid.py::test_named_create_config -x` | ❌ Wave 0 |
| RETR-01 | Migration re-embeds sparse for ALL points; **count parity** old==new before swap | integration (live Qdrant) | `pytest tests/integration/test_qdrant_hybrid_migration.py::test_reembed_parity -m integration -x` | ❌ Wave 0 |
| RETR-01 | Every migrated point has a non-empty `sparse` vector (scroll `with_vectors`, assert `"sparse"` present) | integration | `pytest tests/integration/test_qdrant_hybrid_migration.py::test_all_points_have_sparse -m integration -x` | ❌ Wave 0 |
| RETR-01 | `Modifier.IDF` present in the created collection's `sparse_vectors` config | integration | `pytest .../test_qdrant_hybrid_migration.py::test_idf_modifier_set -m integration -x` | ❌ Wave 0 |
| RETR-01 | Hybrid `query_points` uses two prefetch branches + `Fusion.RRF`; prefetch limit == `top_k+offset` | unit (mock) | `pytest tests/unit/test_qdrant_hybrid.py::test_hybrid_prefetch_limits -x` | ❌ Wave 0 |
| RETR-01 | `get_collection_dim()` returns dense dim for named collections | unit | `pytest tests/unit/test_qdrant_hybrid.py::test_get_dim_named -x` | ❌ Wave 0 |
| RETR-01 | Payload keyword indexes survive the named recreate; filtered hybrid doesn't full-scan | integration | `pytest .../test_qdrant_hybrid_migration.py::test_payload_indexes_survive -m integration -x` | ❌ Wave 0 |
| RETR-03 | `KLAKE_SEARCH__MODE` resolves to `settings.search.mode`; default `hybrid` | unit | `pytest tests/unit/test_settings_search.py::test_search_mode_env -x` | ❌ Wave 0 |
| RETR-03 | `hybrid`/`sparse` on a sparse-less collection **raises** (fail loud, no dense fallback) | unit + integration | `pytest tests/unit/test_search_mode.py::test_fail_loud_missing_sparse -x` | ❌ Wave 0 |
| RETR-03 | `dense` mode works on BOTH legacy unnamed and migrated named collections | integration | `pytest .../test_qdrant_hybrid_migration.py::test_dense_both_shapes -m integration -x` | ❌ Wave 0 |
| RETR-03 | `--mode` (CLI) and `?mode=` (API) thread through to `pipeline.search()` | unit | `pytest tests/unit/test_cli_search_mode.py -x` / `pytest tests/unit/test_api_search_mode.py -x` | ❌ Wave 0 |
| RETR-01/03 | Phase-7 payload filters work identically in dense/sparse/hybrid | unit + integration | `pytest tests/unit/test_search_filters.py -x` (extend existing) | ⚠️ extend existing |
| D-07 | Server-version preflight raises on server < 1.10 | unit (mock `info()`) | `pytest tests/unit/test_qdrant_hybrid.py::test_server_preflight -x` | ❌ Wave 0 |

**Live-Qdrant (integration) vs unit-mockable:**
- **Unit-mockable** (MagicMock client, mirror `tests/unit/test_search_filters.py` + `QdrantVectorStore.__new__` style): create-config shape, prefetch/limit/RRF argument assembly, `get_collection_dim` branch, sparse-presence probe, server-preflight compare, mode threading through CLI/API, settings env resolution, fail-loud raise.
- **Requires a live Qdrant ≥ 1.10** (mirror `tests/integration/test_qdrant_alias_reindex.py`, `pytestmark = pytest.mark.integration`): end-to-end re-embed migration, **count parity**, all-points-have-sparse, IDF-actually-applied, payload-index survival, dense-on-both-shapes, real RRF ordering.

### Sampling Rate
- **Per task commit:** `uv run pytest tests/unit -q`
- **Per wave merge:** `uv run pytest -q` (with live Qdrant for `-m integration`)
- **Phase gate:** full suite green (incl. integration against a ≥1.10 server) before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/unit/test_qdrant_hybrid.py` — named create-config, prefetch/RRF assembly, `get_collection_dim` branch, server-preflight, sparse-presence probe (RETR-01, D-07).
- [ ] `tests/unit/test_settings_search.py` — `SearchSettings` env resolution + default `hybrid` (RETR-03).
- [ ] `tests/unit/test_search_mode.py` — fail-loud on missing sparse (RETR-03, D-10).
- [ ] `tests/unit/test_cli_search_mode.py` + `tests/unit/test_api_search_mode.py` — `--mode` / `?mode=` threading.
- [ ] `tests/integration/test_qdrant_hybrid_migration.py` — re-embed parity, all-sparse, IDF set, payload-index survival, dense-on-both-shapes (RETR-01).
- [ ] Extend `tests/unit/test_search_filters.py` — assert the reused filter attaches on each prefetch branch (D-14).
- [ ] Framework install: none needed (pytest present). `fastembed` install verification is a `checkpoint:human-verify`, not a test.

## Security Domain

> `security_enforcement: true` (config). This phase adds a search-mode surface and a live migration; no new authN/authZ or crypto.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No new auth surface. |
| V3 Session Management | no | Migration reads within a `get_session()` block if it touches the registry — but the recommended path reads `payload["text"]` and needs NO registry session. |
| V4 Access Control | no | No new access surface (search endpoint already exists). |
| V5 Input Validation | **yes** | `mode` constrained to `Literal["hybrid","dense","sparse"]` at the pydantic boundary (settings + API `?mode=` + CLI). Reject unknown modes at validation, not at the store. Existing `top_k`/`tags`/`min_quality_score` bounds unchanged. |
| V6 Cryptography | no | None. |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unbounded/over-fetch prefetch (memory DoS) | Denial of Service | D-12: prefetch limit == `top_k+offset`, not 10×; existing `top_k ∈ [1,100]` cap. |
| Invalid `mode` value | Tampering | `Literal` validation at the API/CLI/settings boundary; fail-closed. |
| Silent capability degradation (returns dense when sparse asked) | Repudiation / integrity of results | D-10 fail-loud — never substitute a different retrieval mode without telling the caller. |
| Destructive migration (data loss on bad swap) | Denial of Service / integrity | D-06 parity gate before swap + `keep_old_collections=True` rollback; validate on a copy first (D-07). |
| First-use model download over the network (supply chain) | Tampering | `fastembed` is Qdrant-official; pin `>=0.8,<0.9`; model `Qdrant/bm25` from the Qdrant HF org. Pre-warm/verify cache (Open Question 2). |

## Sources

### Primary (HIGH confidence)
- **Installed `qdrant-client==1.18.0` venv introspection** — confirmed presence/shape of: `query_points` (incl. `using`, `prefetch`, `offset`), `Prefetch` (fields incl. `filter`), `FusionQuery`, `Fusion.RRF`/`Fusion.DBSF`, `SparseVector`, `NamedSparseVector`, `SparseVectorParams` (`index`,`modifier`), `SparseIndexParams`, `Modifier.IDF`/`Modifier.NONE`, `create_collection(sparse_vectors_config=…)`, `PointStruct(vector={named})`, `client.info()`→`VersionInfo(title,version,commit)`, `client.count()`, `CollectionParams.vectors: Union[VectorParams, Dict[str,VectorParams], None]`, `CollectionParams.sparse_vectors: Optional[Dict[str,SparseVectorParams]]`, `qdrant_client.qdrant_fastembed` shim + `IDF_EMBEDDING_MODELS`.
- **`importlib.metadata.requires("qdrant-client")`** — `fastembed (>=0.8,<0.9) ; extra == "fastembed"`.
- **Codebase** — `qdrant_store.py`, `pipeline/index.py`, `pipeline/search.py`, `plugins/protocols.py`, `config/settings.py`, `cli/app.py`, `api/{app.py,schemas.py}`, existing tests (`test_qdrant_alias_reindex.py`, `test_search_filters.py`).

### Secondary (MEDIUM confidence)
- [Qdrant/bm25 · Hugging Face](https://huggingface.co/Qdrant/bm25) — BM25 sparse model; requires `Modifier.IDF`.
- [BM25 — Qdrant docs](https://qdrant.tech/documentation/edge/edge-bm25/) — IDF-less values, server-side IDF, `query_points`+`Prefetch`+`FusionQuery(RRF)`.
- [fastembed/sparse/bm25.py — qdrant/fastembed](https://github.com/qdrant/fastembed/blob/main/fastembed/sparse/bm25.py) — `embed`/`query_embed` distinction.

### Tertiary (LOW confidence)
- Exact fastembed transitive install footprint on the droplet (verify at `uv add` time — Open Question 2).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — fastembed pin comes from qdrant-client's own metadata; model name cross-cited.
- qdrant-client hybrid API (create/upsert/query/RRF/sparse/info/count): HIGH — every symbol introspected in the installed venv.
- Migration mechanics (named create-path, `get_collection_dim` fix, parity gate placement, re-embed from `payload["text"]`): HIGH — grounded in the actual `qdrant_store.py`/`index.py` source.
- Back-compat vector-shape branch (Pitfall 1): HIGH on the failure mode, MEDIUM on the chosen fix (planner discretion, Open Question 1).
- fastembed runtime install/model download on droplet: MEDIUM — needs an install-time checkpoint.

**Research date:** 2026-07-10
**Valid until:** 2026-08-09 (30 days — stack is pinned; qdrant-client/fastembed are stable within the pinned ranges)
