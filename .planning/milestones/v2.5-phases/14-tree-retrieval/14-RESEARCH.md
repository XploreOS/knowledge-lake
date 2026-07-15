# Phase 14: Tree Retrieval - Research

**Researched:** 2026-07-13
**Domain:** Two-stage RAG retrieval (Qdrant document shortlist → per-document tree traversal); plugin seam design; asyncio-bounded S3 I/O
**Confidence:** HIGH

## Summary

Phase 14 is a **near-1:1 pattern-mirroring phase**. CONTEXT.md locks 13 decisions (D-01..D-13) that specify exactly WHAT to build; every one maps to an existing, verified pattern already in the codebase from Phases 4–13. The work is almost entirely internal composition — no new external packages, no schema migration, no novel algorithm. The dominant risk is not "can it be done" but "does it faithfully mirror the established seam/budget/async conventions without drift."

The two-stage design is: reuse `pipeline/search.py:search()` verbatim as stage 1 (higher `top_k`, group hits by `payload["document"]`, aggregate max-score-per-doc, take top `max_docs`); for each shortlisted doc, resolve its `tree_index` artifact via `registry_repo.get_child_artifact_by_type(session, parsed_id, "tree_index")`, load the JSON from S3, deserialize back into the `TreeIndex`/`TreeNode` contract (inverting `tree_index.py:_tree_to_dict`), and run a new `RetrieverPlugin.search(tree_index, query, ...)` to produce page-level `Hit`s tagged `citation_source="tree"`. Heuristic keyword+DFS traversal is the default (pure Python, deterministic, free); LLM-guided navigation is opt-in behind the exact `enrich.py`/`tree_index.py` budget-cap flow but with `scope="tree_search"`. Parallel tree loading uses the `crawl.py` `run_in_executor` + `asyncio.Semaphore` precedent, driven by a single `asyncio.run()` inside an otherwise-synchronous `tree_search()`.

**Primary recommendation:** Build by mirroring, file-for-file, the Phase-13 IndexerPlugin wiring (protocol → builtin → resolver → pyproject entry-point → settings swap key) and the `enrich.py` budget flow. Add `citation_source` as an additive-default field on `Hit`. Keep `search()` untouched. Every deviation from an existing pattern is a smell — flag it.

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Tree search returns the **existing `Hit` dataclass** (`plugins/protocols.py:114`), **not** a separate `TreeHit`. Overrides the `TreeHit` sketch in `ARCHITECTURE.md §3`. A single result type keeps chunk and tree results mergeable for the Phase-15 router.
- **D-02:** Add optional field **`citation_source: str = "chunk"`** to `Hit` (additive default, mirrors `VectorPoint.sparse = None`). Chunk search yields `"chunk"` unchanged; tree search sets `"tree"`. Tree `Hit.payload` carries: `page_start`, `page_end`, `section_path`, `node_id`, `node_path` (root→node title chain), and `document` (= `parsed_artifact_id`).
- **D-03:** Add a `@runtime_checkable` **`RetrieverPlugin` Protocol** to `plugins/protocols.py`. Contract: `name: str` + `search(tree_index: TreeIndex, query: str, *, top_k: int, mode: str, settings) -> list[Hit]`. Consumes the shared `TreeIndex`/`TreeNode` contract — never PageIndex's internal schema (Anti-Pattern 5).
- **D-04:** Register builtin **`PageIndexRetriever`** (`name="pageindex"`) via a new `knowledge_lake.retrievers` entry-point group + `resolver.py` `get_retriever()`, mirroring `get_indexer()` / `knowledge_lake.indexers` and the `plugins/builtin/__init__.py` registration pattern (FOUND-08).
- **D-05:** **Heuristic mode is default and pure Python** — no network, no LLM, no clock/randomness. Score each `TreeNode` by keyword overlap of query terms against `title + summary + section_path`, traverse **DFS**, return top page ranges as `Hit`s. Deterministic and free (RETR-05).
- **D-06:** **LLM-guided mode is opt-in** (`mode="llm"`) and **reuses the `enrich.py` / `tree_index.py` budget-cap flow verbatim**: cache/spend-check → budget-check → `litellm.completion(cheap_model)` over node summaries → validate → return `Hit`s. **Never raises out of a budget/LLM failure** — degrades gracefully to heuristic result (or empty/partial with status), exactly like `enrich_document`. Model is the **`cheap_model` task alias**.
- **D-07:** **LLM-nav spend isolated to `scope="tree_search"`** in `get_llm_spend` — distinct from Phase-13's `tree_index` scope and from `global`.
- **D-08:** Reuse `pipeline/search.py:search()` **unchanged** for stage 1 (higher `shortlist_k`, e.g. 20). Group returned `Hit`s by `payload["document"]`, aggregate with **max chunk score per document**, take top **`max_docs` (default 3)** documents (Anti-Pattern 2: never load all trees).
- **D-09:** Resolve each shortlisted doc's tree via `registry_repo.get_child_artifact_by_type(session, parsed_artifact_id, "tree_index")`. **Documents with no `tree_index` artifact are skipped gracefully** (logged, no stage-2 result) — a missing tree never fails the whole query.
- **D-10:** Load candidate trees **concurrently via `asyncio`**. `StorageBackend.get_object` is synchronous → wrap each load in `loop.run_in_executor(None, …)` + `asyncio.gather`. Bound concurrency with `asyncio.Semaphore(concurrency_limit)`. Synchronous `tree_search()` drives this via a single `asyncio.run(...)` of the batch-load helper.
- **D-11:** Deserialize loaded JSON back into `TreeIndex`/`TreeNode` objects with a `_dict_to_tree` helper that **inverts `tree_index.py:_tree_to_dict`**. Retriever always operates on the typed contract, not raw dicts.
- **D-12:** Add a **`TreeSearchSettings`** submodel to `config/settings.py`: `mode: Literal["heuristic", "llm"] = "heuristic"`, `shortlist_k: int = 20`, `max_docs: int = 3`, `top_k: int = 5`, `concurrency: int = 5`, `budget_usd: float = 5.0`. Add top-level **`retriever: str = "pageindex"`** swap key. Env override via `KLAKE_TREE_SEARCH__*`. All additive.
- **D-13:** Primary deliverable is **`pipeline/tree_search.py` + the `RetrieverPlugin` seam**. Add only a **thin `klake tree-search` CLI wrapper** (a shim, no logic duplicated). Unified `--route`/`route` param and `both`/merge path are **deferred to Phase 15**.

### Claude's Discretion

- Exact heuristic scoring formula (token-overlap vs substring, whether to weight `title` over `summary`, tie-breaking); the `node_path` string format; the `_dict_to_tree` helper's exact shape; whether stage-2 results across docs are merged by score or interleaved — provided the `Hit` + `citation_source` contract (D-01/D-02) and the `RetrieverPlugin` seam (D-03/D-04) stay stable.
- Whether the LLM-nav prompt asks for a single subtree or a ranked node list, and its exact JSON response schema/validation model — provided it stays behind the budget cap and `scope="tree_search"` (D-06/D-07).
- **Executor model:** sub-agent executors run on `sonnet` (already pinned via `model_overrides.gsd-executor` — no plan task).

### Deferred Ideas (OUT OF SCOPE)

- Unified query router + `--route`/`route` param (CLI/API/MCP) — Phase 15 (ROUTE-01…04).
- `both`/merge path (chunk+tree dedup & re-rank) — Phase 15.
- LLM-based routing for ambiguous queries; routing telemetry/feedback — ROUTE-05/06, future.
- OpenKB wiki export — Phase 16 (KB-01…05).
- Corpus-level meta-tree navigation (PageIndex File System, TREE-07) — v2.6+.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RETR-04 | Two-stage search composes Qdrant document-level shortlist (stage 1) with per-document tree traversal (stage 2) | `search()` reuse verbatim (`search.py`), group by `payload["document"]` set at `index.py:152`, `get_child_artifact_by_type` (`repo.py:765`) resolves tree per doc. Pattern: Two-Stage Search (ARCHITECTURE §4). |
| RETR-05 | Heuristic tree traversal (keyword matching + DFS) retrieves relevant page ranges without LLM calls | `_iter_nodes` DFS precedent (`tree_index.py:381`); `TreeNode` fields `title`/`summary`/`section_path`/`page_start`/`page_end` all present. Pure-Python scoring — no imports beyond stdlib. |
| RETR-06 | LLM-guided tree navigation reasons through node summaries to select subtrees (opt-in) | `_summarize_nodes_llm` (`tree_index.py:388`) + `_call_llm_for_enrichment` (`enrich.py:201`) give the verbatim `litellm.completion(model=f"openai/{alias}", api_base=..., temperature=0.0)` + Pydantic-validate + never-raise pattern. |
| RETR-07 | Tree search loads candidate document trees in parallel (asyncio) with configurable concurrency limit | `run_in_executor(None, fetch_robots, ...)` precedent (`crawl.py:354`); `asyncio.Semaphore` + `asyncio.gather`; `concurrency` in `TreeSearchSettings`. |
| RETR-08 | Tree search results produce Hit objects with page-level citations and a `citation_source: tree` discriminator | Additive `Hit.citation_source` field (D-02); payload carries page-level citation fields. |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Stage-1 document shortlist | Vector store (Qdrant) via `search()` | Registry (Postgres) | Qdrant owns ANN recall; existing `search()` already returns `payload["document"]`. |
| Doc→tree artifact resolution | Registry (Postgres) | — | `get_child_artifact_by_type` is an ORM one-hop; lineage lives in the registry. |
| Tree JSON load | Object storage (S3/MinIO) | — | Trees are silver-zone artifacts at `tree_index/{domain}/{source_id}/{hash}.json`. |
| Parallel load orchestration | Pipeline (`tree_search.py`) | asyncio event loop | Sync S3 client wrapped in executor; concurrency bounded in the pipeline layer. |
| Heuristic traversal | Retriever plugin (pure Python) | — | Deterministic scoring on the typed `TreeNode` contract — no I/O. |
| LLM-guided traversal | Retriever plugin → LiteLLM gateway | Registry (spend accounting) | Budget-capped `cheap_model` call, `scope="tree_search"`. |
| Result shaping (`Hit`) | Pipeline/plugin | — | Uniform `Hit` with `citation_source="tree"` for Phase-15 mergeability. |
| CLI surface | `cli/app.py` thin wrapper | — | Shim over `tree_search()`, no logic duplicated (D-13). |

## Standard Stack

### Core

No new external packages. Everything required is already a dependency and verified installed.

| Library | Version (pinned) | Purpose | Why Standard |
|---------|------------------|---------|--------------|
| `litellm` | 1.90.x | LLM gateway for opt-in LLM-nav mode | CLAUDE.md constraint — all model calls via LiteLLM; already used in `enrich.py`/`tree_index.py`. [VERIFIED: pyproject/CLAUDE.md] |
| `qdrant-client` | 1.18.x | Stage-1 ANN shortlist (via existing `search()`) | `search.py` already imports `qdrant_client.models`; stage 1 is reuse-only. [VERIFIED: search.py:25] |
| `pydantic` | 2.13.x | Validate LLM-nav JSON response (bounded, ASVS V5) | Mirrors `NodeSummaryResult` / `EnrichmentResult`. [VERIFIED: tree_index.py:78] |
| `orjson` | latest | (De)serialize tree JSON | `tree_index.py` serializes with `orjson.dumps`; loader parses the same. [VERIFIED: tree_index.py:27] |
| `structlog` | latest | Structured logging | Codebase-wide convention. [VERIFIED: all pipeline modules] |
| `typer` | 0.26.x | Thin `tree-search` CLI wrapper | Mirrors `cmd_search`. [VERIFIED: cli/app.py:632] |
| `asyncio` (stdlib) | — | Parallel tree loading | `crawl.py` precedent. [VERIFIED: crawl.py:354] |

**Installation:** None. `uv sync` already provides all of the above.

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tenacity` | latest | Retry LLM call (as `enrich.py` does) | Only if LLM-nav wants `enrich.py`-style retry; `tree_index.py:_summarize_nodes_llm` chose NOT to retry (simpler per-node try/except). Prefer the simpler `tree_index.py` shape unless a plan requires retry. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Reuse `search()` for stage 1 | Bespoke Qdrant grouping query | D-08 forbids; reuse keeps chunk path untouched for Phase-15 router. |
| `run_in_executor` + `Semaphore` | `aioboto3` async S3 client | Adds a dependency; `StorageBackend` is sync by design. Executor-wrap is the established precedent (crawl.py). |
| Separate `TreeHit` type | — | D-01 explicitly forbids; reuse `Hit` for mergeability. |

**Version verification:** No new packages introduced this phase; the Package Legitimacy Audit is a no-op (see below).

## Package Legitimacy Audit

> Phase 14 installs **zero** external packages. All libraries used are pre-existing dependencies already pinned in `pyproject.toml` and verified in prior phases.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| (none — no new installs) | — | — | — | — | — | — |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*Note: `pageindex 0.3.0.dev3` remains flagged [SUS] (pre-release) from Phase 13 but is NOT imported by this phase — the `PageIndexRetriever` builtin operates on our `TreeNode` contract, never the PageIndex library (Anti-Pattern 5). No install required.*

## Architecture Patterns

### System Architecture Diagram

```
   query (str), mode ∈ {heuristic, llm}
            │
            ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  pipeline/tree_search.py : tree_search()   (synchronous)     │
  └─────────────────────────────────────────────────────────────┘
            │
            │ STAGE 1 — document shortlist
            ▼
  pipeline/search.py:search(query, top_k=shortlist_k)  ── unchanged ──▶ Qdrant
            │  returns list[Hit]  (each .payload["document"] = parsed_artifact_id)
            ▼
  group hits by payload["document"] → aggregate max score/doc → take top max_docs
            │  → [parsed_artifact_id_1 ... parsed_artifact_id_N]
            │
            │ STAGE 2 — resolve + parallel-load trees
            ▼
  for each parsed_id:  registry_repo.get_child_artifact_by_type(              ──▶ Postgres
                          session, parsed_id, "tree_index")  → artifact | None
            │  (None → log + skip, D-09)
            ▼
  asyncio.run( batch_load ):
     Semaphore(concurrency) guards
     loop.run_in_executor(None, storage.get_object, key)   ──▶ S3 / MinIO
            │  bytes → orjson.loads → _dict_to_tree() → TreeIndex
            ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  get_retriever(settings)  →  PageIndexRetriever              │
  │  .search(tree_index, query, top_k, mode, settings)          │
  │    ├─ mode="heuristic": keyword-overlap score + DFS (free)   │
  │    └─ mode="llm": budget-check(scope=tree_search)            │
  │         → litellm.completion(cheap_model) → validate         │
  │         → degrade to heuristic on any failure (D-06)         │
  └─────────────────────────────────────────────────────────────┘
            │  list[Hit]  (citation_source="tree", page-level payload)
            ▼
  merge across docs, rank by score, take top_k  ──▶  list[Hit]
```

### Recommended Project Structure

```
src/knowledge_lake/
├── pipeline/
│   └── tree_search.py              # NEW: two-stage orchestrator + _dict_to_tree + async batch-load helper
├── plugins/
│   ├── protocols.py                # EDIT: add citation_source to Hit; add RetrieverPlugin Protocol
│   ├── resolver.py                 # EDIT: add GROUP_RETRIEVERS + get_retriever()
│   └── builtin/
│       ├── __init__.py             # EDIT: docstring note for knowledge_lake.retrievers
│       └── pageindex_retriever.py  # NEW: PageIndexRetriever (heuristic + LLM-nav)
├── config/
│   └── settings.py                 # EDIT: add TreeSearchSettings + `retriever` swap key + validator
└── cli/
    └── app.py                      # EDIT: add cmd_tree_search (thin shim)
pyproject.toml                      # EDIT: add [project.entry-points."knowledge_lake.retrievers"]
```

### Pattern 1: Plugin seam (protocol → builtin → resolver → entry-point → swap key)

**What:** The exact 5-touchpoint wiring Phase 13 used for `IndexerPlugin`.
**When to use:** For `RetrieverPlugin` (D-03/D-04).
**Example (mirror `get_indexer`):**
```python
# resolver.py — Source: existing get_indexer, resolver.py:335
GROUP_RETRIEVERS = "knowledge_lake.retrievers"

def get_retriever(settings: Settings) -> Any:
    """Return the RetrieverPlugin named by settings.retriever (D-04)."""
    name = settings.retriever
    kwargs = (
        {"litellm_url": settings.litellm_url, "litellm_api_key": settings.litellm_api_key}
        if name == "pageindex"
        else {}
    )
    return _resolve_with_kwargs(GROUP_RETRIEVERS, name, **kwargs)
```
```toml
# pyproject.toml — Source: existing indexers group, pyproject.toml:110
[project.entry-points."knowledge_lake.retrievers"]
pageindex = "knowledge_lake.plugins.builtin.pageindex_retriever:PageIndexRetriever"
```
```python
# settings.py — mirror the indexer swap key (settings.py:480) + validator (settings.py:513)
retriever: str = "pageindex"
# Add "retriever" to the @field_validator("crawler", "discovery", ...) tuple so
# malicious entry-point names are rejected (ASVS V5, mirrors T-13-03 mitigation).
```

### Pattern 2: Budget-capped LLM call that never raises (D-06)

**What:** cache/spend-check → budget-check → single `litellm.completion` over node summaries → Pydantic-validate → return; any failure degrades to heuristic.
**When to use:** LLM-nav mode only.
**Example (mirror `tree_index.py:_summarize_nodes_llm` + `enrich.py` budget gate):**
```python
# Source: tree_index.py:405 + enrich.py:356
with get_session() as session:
    current_spend = registry_repo.get_llm_spend(session, scope="tree_search")  # D-07 scope
    if current_spend >= settings.tree_search.budget_usd:
        log.warning("tree_search.budget_exceeded", ...)
        return heuristic_hits          # degrade, never raise (D-06)

import litellm  # lazy import — avoids proxy dep in unit tests (tree_index.py:398)
response = litellm.completion(
    model=f"openai/{settings.tree_search.model_alias}",   # cheap_model alias, NOT a provider ID
    messages=[{"role": "system", "content": _NAV_SYSTEM_PROMPT},
              {"role": "user", "content": node_summaries_blob}],
    api_base=settings.litellm_url, api_key=settings.litellm_api_key,
    temperature=0.0,
)
# validate via a bounded Pydantic model (mirror NodeSummaryResult) BEFORE use
# record spend inside a registry session: record_llm_spend(session, scope="tree_search", cost_usd=...)
```
> Note: `TreeSearchSettings` in D-12 does not list `model_alias`. Add `model_alias: str = "cheap_model"` to the submodel (mirrors `TreeSettings.model_alias`, `settings.py:210`) — required by D-06's "cheap_model task alias" and consistent with the additive-default rule. Flag to the planner as a small necessary addition beyond D-12's literal list.

### Pattern 3: Async-wrap-sync parallel load with Semaphore (D-10)

**What:** Bounded concurrent S3 reads against a synchronous client.
**When to use:** Loading N shortlisted trees.
**Example (mirror `crawl.py:354`):**
```python
# Source: crawl.py:354 run_in_executor precedent
async def _load_all(keys: list[str], storage, concurrency: int) -> list[bytes | None]:
    sem = asyncio.Semaphore(concurrency)
    loop = asyncio.get_running_loop()
    async def _one(key: str):
        async with sem:
            try:
                return await loop.run_in_executor(None, storage.get_object, key)
            except Exception as exc:          # missing/failed tree → skip (D-09)
                log.warning("tree_search.tree_load_failed", key=key, error=str(exc))
                return None
    return await asyncio.gather(*[_one(k) for k in keys])

# tree_search() stays synchronous; drive with a single asyncio.run(...) (D-10):
raw_trees = asyncio.run(_load_all(keys, storage, s.tree_search.concurrency))
```
> Caution: `asyncio.run()` fails with `RuntimeError` if a loop is already running (e.g. called from within an async API handler). Phase 14's only caller is the sync CLI, so `asyncio.run` is safe now — but leave a comment; the Phase-15 router / API path must call the async helper directly (the same "no nested asyncio.run — CR-02" note exists at `crawl.py:365`).

### Pattern 4: Inverse deserializer `_dict_to_tree` (D-11)

**What:** Exact inverse of `tree_index.py:_tree_to_dict` (`tree_index.py:184`).
**Example:**
```python
# Inverts _tree_to_dict (tree_index.py:184). Top-level wrapper mirrors the
# tree_dict built at tree_index.py:313 (parsed_artifact_id, source_id, mode,
# schema_version, content_hash, roots).
def _dict_to_tree(d: dict) -> TreeNode:
    return TreeNode(
        node_id=d["node_id"], title=d["title"], summary=d["summary"],
        page_start=d["page_start"], page_end=d["page_end"],
        level=d["level"], section_path=d["section_path"],
        children=[_dict_to_tree(c) for c in d.get("children", [])],
    )

def _dict_to_tree_index(d: dict) -> TreeIndex:
    return TreeIndex(
        parsed_artifact_id=d["parsed_artifact_id"], source_id=d["source_id"],
        roots=[_dict_to_tree(r) for r in d.get("roots", [])],
        mode=d.get("mode", "deterministic"),
        schema_version=d.get("schema_version", "1"),
        content_hash=d.get("content_hash", ""),
    )
```

### Anti-Patterns to Avoid

- **Load all trees (Anti-Pattern 2):** Never traverse every indexed document. Stage 1 must narrow to `max_docs` first. [CITED: ARCHITECTURE.md §4]
- **Couple retriever to PageIndex's internal schema (Anti-Pattern 5):** The retriever consumes only `TreeNode`/`TreeIndex`. Do NOT import the `pageindex` library. [CITED: ARCHITECTURE.md, pageindex_indexer.py:6]
- **Raise on LLM/budget failure:** LLM-nav must degrade to heuristic — mirror `enrich.py` D-05 / `tree_index.py` D-09. [VERIFIED: tree_index.py:443]
- **Hardcode a provider model ID:** Always `f"openai/{alias}"` with `cheap_model`. [VERIFIED: tree_index.py:409, CLAUDE.md]
- **Mutate `search()`:** Stage 1 is call-only. Changing it risks the chunk path the Phase-15 router composes. [VERIFIED: CONTEXT D-08]
- **Non-determinism in heuristic mode:** No `time`, no `random`, no set-iteration-order dependence in scoring/tie-breaking (sort by a stable key). [VERIFIED: CONTEXT D-05]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Query→document narrowing | Custom Qdrant grouping/scan | `pipeline/search.py:search()` (D-08) | Already returns `payload["document"]`; reuse keeps chunk path intact. |
| Doc→tree lookup | New SQL / ancestor walk | `registry_repo.get_child_artifact_by_type` (`repo.py:765`) | ORM one-hop already exists and is tested. |
| Tree JSON round-trip | New schema/serializer | Invert `_tree_to_dict` (`tree_index.py:184`) via `_dict_to_tree` | Guarantees load matches write byte-for-field. |
| Spend accounting | New counter table | `get_llm_spend`/`record_llm_spend` with `scope="tree_search"` (`repo.py:793`) | UNIQUE(scope) row already handles get-or-create. |
| LLM JSON safety | Trust raw model output | Bounded Pydantic model (mirror `NodeSummaryResult`, `tree_index.py:78`) | ASVS V5 — reject oversized/attacker output before use. |
| Concurrency limiting | Manual thread pool | `asyncio.Semaphore` + `run_in_executor` (`crawl.py:354`) | Established idiom; sync client stays sync. |
| Config plumbing | `os.getenv` reads | `TreeSearchSettings` submodel + `KLAKE_TREE_SEARCH__*` | Single source of truth; no os.environ in builtins (CR-03). |

**Key insight:** Every stage-2 building block already exists as a tested helper. Phase 14 is composition, not construction. The only genuinely new logic is the heuristic scoring function and the (optional) LLM-nav prompt — both small and bounded.

## Runtime State Inventory

> Phase 14 is **greenfield feature addition** (read-only consumer of Phase-13 artifacts), not a rename/refactor/migration. This section is included for completeness because it touches storage and config.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Reads existing `tree_index/{domain}/{source_id}/{hash}.json` S3 objects and `tree_index` registry artifacts (write path from Phase 13). No writes, no new keys. | None — read-only consumer. |
| Live service config | New `KLAKE_TREE_SEARCH__*` and `KLAKE_RETRIEVER` env vars — additive, defaulted, no existing deployment breaks if unset. | Document new env vars; no migration. |
| OS-registered state | None — no scheduled tasks, no daemons added. Dagster assets unchanged (retrieval is a query path, not an asset). | None — verified: no `definitions.py` change needed. |
| Secrets/env vars | Reuses `litellm_api_key` / `litellm_url` already in Settings. No new secrets. | None. |
| Build artifacts | New `knowledge_lake.retrievers` entry-point group requires **`uv pip install -e .` (editable reinstall)** so the entry point is discoverable by `importlib.metadata.entry_points`. | Plan must include an editable reinstall step + a resolver conformance test (mirrors Phase-13 indexer wiring). |

**Nothing found requiring data migration.** Zero Alembic migrations (CONTEXT confirms — no schema change).

## Common Pitfalls

### Pitfall 1: New entry-point group not discoverable without editable reinstall
**What goes wrong:** `get_retriever()` raises `LookupError: No plugin 'pageindex' registered in knowledge_lake.retrievers` even though `pyproject.toml` declares it.
**Why it happens:** `importlib.metadata.entry_points` reads installed distribution metadata, not the live source tree. Adding an entry-point group requires re-running `uv pip install -e .` (or `uv sync`) to refresh `*.dist-info/entry_points.txt`.
**How to avoid:** Add an explicit reinstall task before the resolver conformance test. Phase 13 hit this exact issue for `knowledge_lake.indexers`.
**Warning signs:** Resolver test passes locally after a manual reinstall but fails in a clean CI checkout.

### Pitfall 2: `payload["document"]` missing on pre-Phase-7 points
**What goes wrong:** Grouping stage-1 hits by `payload["document"]` yields `None`/`KeyError` for old chunks.
**Why it happens:** `payload["document"] = parsed_artifact_id` was set at `index.py:152`; points indexed before that (or before a reindex) lack it — the same D-13 back-compat caveat `search.py` documents for filter fields.
**How to avoid:** Use `hit.payload.get("document")` and skip hits with no document key (log a debug). Never `[]`-index the payload.
**Warning signs:** Empty shortlist against a corpus that clearly has matching chunks.

### Pitfall 3: `asyncio.run()` inside an already-running loop
**What goes wrong:** `RuntimeError: asyncio.run() cannot be called from a running event loop`.
**Why it happens:** Fine for the sync CLI now, but Phase-15's API/MCP handlers run inside an event loop. `crawl.py:365` explicitly notes "no asyncio.run — CR-02" for exactly this reason.
**How to avoid:** Keep the batch-load helper as a plain `async def`; call `asyncio.run()` only in the sync `tree_search()`. Leave a comment that async callers must await the helper directly.
**Warning signs:** Works via CLI, explodes when the Phase-15 router calls `tree_search()` from FastAPI.

### Pitfall 4: LLM-nav budget scope collision
**What goes wrong:** Tree-search LLM spend counts against Phase-13's `tree_index` budget (or `global`), tripping caps unexpectedly.
**Why it happens:** Copy-pasting `tree_index.py`'s `scope="tree_index"` verbatim.
**How to avoid:** Use `scope="tree_search"` in BOTH `get_llm_spend` and `record_llm_spend` (D-07). This mirrors the recent WR-01 fix that isolated tree-index spend.
**Warning signs:** LLM-nav returns `skipped_budget_exceeded` immediately after a Phase-13 LLM-mode indexing run.

### Pitfall 5: Non-deterministic heuristic tie-breaking
**What goes wrong:** Same `(TreeIndex, query)` yields different `Hit` order across runs → flaky tests, breaks RETR-05's "reproducible and free" guarantee.
**Why it happens:** Sorting nodes by score alone with dict/set iteration order deciding ties.
**How to avoid:** Sort by a stable composite key, e.g. `(-score, node.section_path)`. No `random`, no `time`.
**Warning signs:** A test asserting result order fails intermittently.

### Pitfall 6: Empty/whitespace query and empty-tree edge cases
**What goes wrong:** Unhandled empty query or a doc whose tree has zero roots.
**Why it happens:** `search()` already guards empty query (`search.py:87`) but the tree traversal is new.
**How to avoid:** Mirror `search()`'s empty-query early return; guard `if not tree_index.roots: return []` in the retriever.
**Warning signs:** `IndexError`/`ValueError` on a document with a single no-sections fallback root.

## Code Examples

### RetrieverPlugin protocol (mirror IndexerPlugin, protocols.py:665)
```python
# Source: protocols.py:665 IndexerPlugin template + CONTEXT D-03
@runtime_checkable
class RetrieverPlugin(Protocol):
    """Swap-capable tree retriever plugin (D-03/D-04, FOUND-08).

    Swap via settings.retriever entry-point group 'knowledge_lake.retrievers'.
    Consumes the shared TreeIndex/TreeNode contract — never PageIndex internals.
    """
    name: str

    def search(
        self,
        tree_index: TreeIndex,
        query: str,
        *,
        top_k: int = 5,
        mode: str = "heuristic",
        settings: Any | None = None,
    ) -> list[Hit]:
        """Return page-level Hits (citation_source='tree') for query over one tree."""
        ...
```

### Hit additive field (protocols.py:114)
```python
# Source: protocols.py:114 + VectorPoint.sparse additive-default precedent (protocols.py:102)
@dataclass
class Hit:
    id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)
    citation_source: str = "chunk"   # NEW (D-02): tree search sets "tree"
```

### Stage-1 grouping (D-08)
```python
# Source: ARCHITECTURE §4 + search.py reuse
hits = search(query, collection=collection, top_k=s.tree_search.shortlist_k, settings=s)
doc_scores: dict[str, float] = {}
for h in hits:
    doc = h.payload.get("document")           # Pitfall 2: .get, not []
    if not doc:
        continue
    doc_scores[doc] = max(doc_scores.get(doc, float("-inf")), h.score)  # max per doc
top_docs = [d for d, _ in sorted(doc_scores.items(), key=lambda kv: (-kv[1], kv[0]))[: s.tree_search.max_docs]]
```

### node_path construction (Claude's discretion — recommended)
```python
# Build the root→node title chain during DFS by threading an ancestor-title list.
def _dfs(node, ancestors, query_terms, out):
    path = ancestors + [node.title]
    score = _score_node(node, query_terms)     # keyword overlap over title+summary+section_path
    if score > 0:
        out.append(Hit(
            id=node.node_id, score=score, citation_source="tree",
            payload={
                "document": parsed_artifact_id, "node_id": node.node_id,
                "section_path": node.section_path, "page_start": node.page_start,
                "page_end": node.page_end, "node_path": " > ".join(path),
            },
        ))
    for child in node.children:
        _dfs(child, path, query_terms, out)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Chunk-only RAG (`search()`) | Two-stage: doc shortlist → structural tree traversal | v2.5 (this phase) | Adds precision (page ranges) on top of vector recall. |
| Flat citations (chunk_id) | Hierarchical citations (`node_path`, page range) | v2.5 | Callers render "Document X, §Y, pages A–B" without a DB lookup. |
| LLM-per-node (Phase 13 indexing) | Heuristic-first traversal, LLM opt-in | v2.5 | Deterministic-first constraint — free default, paid only on demand. |

**Deprecated/outdated:**
- `TreeHit` sketch in ARCHITECTURE.md §3 — superseded by D-01 (reuse `Hit`). Do not implement `TreeHit`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `TreeSearchSettings` needs an added `model_alias: str = "cheap_model"` field (not in D-12's literal list) for LLM-nav's `cheap_model` requirement | Pattern 2 / Config | Low — additive; if planner prefers reusing `s.tree.model_alias` that also satisfies "cheap_model alias". Flag for planner. |
| A2 | `retriever` must be added to the `_validate_swap_key` field-validator tuple (`settings.py:513`) | Standard Stack / Pattern 1 | Low — omission is a security gap (ASVS V5), not a functional break; mirrors T-13-03. |
| A3 | New entry-point group requires an editable reinstall step in the plan | Runtime State / Pitfall 1 | Medium — if omitted, resolver conformance test fails in clean checkout. |
| A4 | LLM-nav degrade path returns the already-computed heuristic result (compute heuristic first, then optionally refine with LLM) | Pattern 2 / D-06 | Low — D-06 explicitly allows "degrade to heuristic result (or empty/partial)"; exact shape is executor discretion. |

**Note:** All package/version claims are `[VERIFIED]` against the installed tree and `pyproject.toml`; no unverified external package is introduced.

## Open Questions

1. **LLM-nav prompt shape (single subtree vs ranked node list)?**
   - What we know: D-06 leaves this to executor discretion; must stay budget-capped, `scope="tree_search"`, bounded Pydantic validation.
   - What's unclear: Which yields better healthcare retrieval (no ground-truth benchmark — STATE.md Blocker: "Tree traversal prompt quality unvalidated").
   - Recommendation: Start with a single LLM call passing the flattened node-summary list, asking for a ranked list of relevant `node_id`s; validate against a bounded Pydantic model listing known node_ids. Keep it a thin refinement over the heuristic result so a bad prompt degrades gracefully.

2. **Cross-document stage-2 merge: by score or interleaved?**
   - What we know: Claude's discretion (D-13/discretion).
   - What's unclear: Whether raw heuristic scores are comparable across documents (they are keyword-overlap counts, so roughly comparable).
   - Recommendation: Merge by score with a stable `(-score, document, section_path)` tie-break, then take global `top_k`. Simple and deterministic; the Phase-15 router will re-rank anyway.

3. **LLM-nav result caching?**
   - What we know: `enrich.py`/`tree_index.py` cache LLM results by synthetic hash; D-06 says "reuse the budget-cap flow" but tree search is a query (per-query input), not an artifact build.
   - Recommendation: Do NOT add a cache in Phase 14 (queries are unbounded/unique). Spend-accounting via `scope="tree_search"` is the cost control. Note explicitly so a reviewer doesn't expect a cache.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Qdrant | Stage-1 shortlist (`search()`) | ✓ (Docker compose service) | client 1.18.x | — (required) |
| MinIO / S3 | Tree JSON load | ✓ (Docker compose service) | SDK 7.2.x / boto3 1.43.x | — (required) |
| PostgreSQL | Artifact/spend lookup | ✓ (Docker compose service) | 16+ | — (required) |
| LiteLLM proxy | LLM-nav mode only | ✓ (Docker compose service) | 1.90.x | Heuristic mode needs no LLM (default) |

**Missing dependencies with no fallback:** none (all are existing compose services from prior phases).
**Missing dependencies with fallback:** LiteLLM is only needed for opt-in `mode="llm"`; the default heuristic path is fully offline.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.24 (`asyncio_mode = "auto"`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`) |
| Quick run command | `uv run pytest tests/unit/test_tree_search.py -x -q` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RETR-04 | Two-stage: shortlist groups by `payload["document"]`, resolves tree per doc | unit | `uv run pytest tests/unit/test_tree_search.py::test_two_stage_shortlist -x` | ❌ Wave 0 |
| RETR-05 | Heuristic keyword+DFS is deterministic and makes zero LLM calls | unit | `uv run pytest tests/unit/test_tree_search.py::test_heuristic_no_llm -x` | ❌ Wave 0 |
| RETR-06 | LLM-nav opt-in, budget-gated, degrades to heuristic on failure | unit (mock litellm) | `uv run pytest tests/unit/test_tree_search.py::test_llm_nav_degrades -x` | ❌ Wave 0 |
| RETR-07 | Parallel load bounded by Semaphore; missing tree skipped | unit | `uv run pytest tests/unit/test_tree_search.py::test_parallel_load_and_skip -x` | ❌ Wave 0 |
| RETR-08 | Hits carry `citation_source="tree"` + page-level payload | unit | `uv run pytest tests/unit/test_tree_search.py::test_citation_source_tree -x` | ❌ Wave 0 |
| D-04 | `PageIndexRetriever` satisfies `RetrieverPlugin`; resolvable via entry point | unit (conformance) | `uv run pytest tests/unit/test_builtin_plugins.py -k retriever -x` | ❌ Wave 0 (extend existing file) |
| D-02 | `Hit.citation_source` defaults to `"chunk"`; chunk search unchanged | unit | `uv run pytest tests/unit/test_search_filters.py -x` (regression) | ✅ existing |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/unit/test_tree_search.py -x -q`
- **Per wave merge:** `uv run pytest tests/unit -q`
- **Phase gate:** `uv run pytest -q` full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_tree_search.py` — covers RETR-04..08. Mirror `test_tree_index.py` fixtures: in-memory SQLite via `StaticPool` + `monkeypatch.setattr(registry_db, "get_engine", ...)`; patch `StorageBackend` at the `pipeline.tree_search` module level; mock `litellm.completion` via `unittest.mock.patch` for LLM-nav tests.
- [ ] Extend `tests/unit/test_builtin_plugins.py` — add a `TestPageIndexRetriever` class asserting `isinstance(retriever, RetrieverPlugin)` and entry-point resolution (mirror the `IndexerPlugin` conformance tests).
- [ ] Shared fixture: a small hand-built `TreeIndex` (2–3 levels) + its serialized dict, to test `_dict_to_tree` round-trip and heuristic scoring without S3.
- [ ] Framework install: none — pytest + pytest-asyncio already present.

*RED-state expectation matches Phase 13: tests fail with `ImportError` until the implementation ships — correct Nyquist scaffold.*

## Security Domain

`security_enforcement: true`, `security_asvs_level: 1`, `security_block_on: high`.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Query path; no new auth surface (CLI is local). |
| V3 Session Management | no | Stateless query. |
| V4 Access Control | no | No new access boundary; reads existing artifacts the operator owns. |
| V5 Input Validation | **yes** | (a) `retriever` swap key → add to `_validate_swap_key` regex (`settings.py:513`), preventing malicious entry-point names (mirrors T-13-03). (b) LLM-nav response → bounded Pydantic model (mirror `NodeSummaryResult`, `tree_index.py:78`) rejecting oversized/injected output before use. (c) Bound the node-summary text sent to the LLM (mirror `_NODE_EXCERPT_CHARS`, `tree_index.py:48`) to limit prompt-injection surface. |
| V6 Cryptography | no | No crypto introduced. Content hashing reuses existing helpers. |

### Known Threat Patterns for {Python / LiteLLM / plugin-resolver stack}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malicious `retriever` swap-key value (arbitrary entry-point load / path traversal) | Elevation of Privilege | `_SWAP_KEY_RE` validation — add `retriever` to the validator tuple (`settings.py:513`). |
| Prompt injection via node `title`/`summary` (attacker-controlled document content reaches LLM-nav) | Tampering | Injection-resistant system prompt (mirror `_SUMMARY_SYSTEM_PROMPT`, `tree_index.py:52`) treating node text as content-not-instructions; bound excerpt length; `temperature=0.0`. |
| Oversized/malformed LLM JSON reaching downstream | Tampering | `model_validate_json` against a `Field(max_length=...)`-bounded model before constructing any `Hit`. |
| Budget exhaustion / cost DoS via repeated LLM-nav queries | Denial of Service | `scope="tree_search"` spend cap (`get_llm_spend`/`record_llm_spend`); heuristic default makes LLM strictly opt-in. |
| Unbounded fan-out load (memory/connection exhaustion) | Denial of Service | `asyncio.Semaphore(concurrency)` + `max_docs` cap (Anti-Pattern 2). |

## Sources

### Primary (HIGH confidence)
- Codebase (verified by direct read this session): `plugins/protocols.py` (Hit:114, TreeNode:598, TreeIndex:633, IndexerPlugin:665), `pipeline/tree_index.py` (_tree_to_dict:184, _summarize_nodes_llm:388, budget gate:293), `pipeline/enrich.py` (budget flow:356, LLM call:201), `pipeline/search.py` (search:35), `plugins/resolver.py` (get_indexer:335, _resolve_with_kwargs:215), `config/settings.py` (TreeSettings:199, SearchSettings:359, swap-key validator:513), `registry/repo.py` (get_child_artifact_by_type:765, get_llm_spend:793), `storage/s3.py` (get_object:136), `pipeline/crawl.py` (run_in_executor:354), `cli/app.py` (cmd_search:632), `pyproject.toml` (entry-points:89–111, pytest cfg:117).
- `.planning/research/ARCHITECTURE.md` §4 (Two-Stage Search), Anti-Patterns 2/5.
- `.planning/phases/14-tree-retrieval/14-CONTEXT.md` — locked decisions D-01..D-13.

### Secondary (MEDIUM confidence)
- `.planning/STATE.md` — Phase-14 blockers (prompt quality unvalidated; latency without parallelization).
- `.planning/REQUIREMENTS.md` — RETR-04..08 definitions and traceability.

### Tertiary (LOW confidence)
- None — no web research required; phase is internal-composition against a verified codebase.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new packages; all libraries verified installed and already used by sibling modules.
- Architecture: HIGH — every stage maps to an existing, tested pattern (search reuse, registry helper, budget flow, executor-wrap).
- Pitfalls: HIGH — five of six are documented in-repo precedents (entry-point reinstall, payload back-compat, no-nested-asyncio.run, scope isolation, determinism).
- Security: HIGH — ASVS V5 controls mirror the exact Phase-13 mitigations (swap-key regex, bounded Pydantic, injection-resistant prompt).

**Research date:** 2026-07-13
**Valid until:** 2026-08-12 (30 days — stable internal-composition phase; no fast-moving external deps).
