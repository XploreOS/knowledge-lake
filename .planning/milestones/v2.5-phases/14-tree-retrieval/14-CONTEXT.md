# Phase 14: Tree Retrieval - Context

**Gathered:** 2026-07-13
**Status:** Ready for planning

> Captured in `--auto` mode: all gray areas auto-resolved to the recommended
> (deterministic-first, pattern-reuse, additive-default) option. Decisions are
> logged in `14-DISCUSSION-LOG.md`. Review before planning if any default is wrong.

<domain>
## Phase Boundary

Deliver **two-stage tree retrieval** that narrows from document selection to
precise page-level results, consuming the `tree_index` silver-zone artifacts
produced in Phase 13.

- **Stage 1 — document shortlist (Qdrant):** reuse the existing
  `pipeline/search.py:search()` with an expanded `shortlist_k`, group chunk hits
  by `payload["document"]` (= `parsed_artifact_id`), aggregate per-doc score,
  and take the top `max_docs` candidate documents (RETR-04).
- **Stage 2 — per-document tree traversal:** for each shortlisted document, load
  its `tree_index` artifact from S3 and traverse it to find relevant page ranges.
  **Heuristic mode (default):** keyword matching + DFS over the `TreeNode`
  contract, **zero LLM calls** (RETR-05). **LLM-guided mode (opt-in):** reasons
  through node summaries to select relevant subtrees, budget-gated (RETR-06).
- **Parallel loading:** candidate document trees load from S3 concurrently
  (asyncio) with a configurable concurrency limit (RETR-07).
- **Uniform results:** tree search produces `Hit` objects with page-level
  citations and a `citation_source: tree` discriminator distinguishing them from
  chunk hits (RETR-08).

**In scope:** `RetrieverPlugin` protocol + builtin + resolver seam;
`pipeline/tree_search.py` two-stage orchestrator; heuristic (keyword+DFS)
traversal; opt-in LLM-guided navigation behind the budget cap; S3 tree-load +
deserialization back into the `TreeIndex`/`TreeNode` contract; parallel
Semaphore-bounded loading; `citation_source` discriminator on `Hit`;
`TreeSearchSettings` config surface; a thin `klake tree-search` CLI wrapper for
testability.

**Out of scope (later phases / deferred):** the unified query router and
`--route`/`route` param across CLI/API/MCP (Phase 15, ROUTE-01…04); the
`both`/merge (chunk+tree dedup & re-rank) path (Phase 15); OpenKB wiki
(Phase 16); LLM-based routing and routing telemetry (ROUTE-05/06, future).

</domain>

<decisions>
## Implementation Decisions

### Result contract — reuse `Hit`, add a `citation_source` discriminator
- **D-01:** Tree search returns the **existing `Hit` dataclass**
  (`plugins/protocols.py:114`), **not** a separate `TreeHit`. This overrides the
  `TreeHit` sketch in `ARCHITECTURE.md §3` — RETR-08 explicitly mandates "`Hit`
  objects … with a `citation_source: tree` discriminator", and a single result
  type keeps chunk and tree results mergeable for the Phase-15 router.
- **D-02:** Add an optional field **`citation_source: str = "chunk"`** to the
  `Hit` dataclass (additive default, mirrors the `VectorPoint.sparse = None`
  back-compat convention). Chunk search continues to yield `"chunk"` unchanged;
  tree search sets `"tree"`. Tree `Hit.payload` carries page-level citation:
  `page_start`, `page_end`, `section_path`, `node_id`, `node_path` (the
  root→node title chain), and `document` (= `parsed_artifact_id`) so callers
  render "Document X, §Y, pages A–B" without a DB lookup.

### Retriever seam — new swappable `RetrieverPlugin` (mirror Phase-13 IndexerPlugin)
- **D-03:** Add a `@runtime_checkable` **`RetrieverPlugin` Protocol** to
  `plugins/protocols.py`, alongside `IndexerPlugin`. Contract:
  `name: str` + `search(tree_index: TreeIndex, query: str, *, top_k: int,
  mode: str, settings) -> list[Hit]`. The retriever **consumes the shared
  `TreeIndex`/`TreeNode` contract** (D-01/D-02 of Phase 13) — never PageIndex's
  internal schema (ARCHITECTURE.md Anti-Pattern 5: indexer↔retriever decoupled).
- **D-04:** Register the builtin **`PageIndexRetriever`** (`name="pageindex"`)
  via a new `knowledge_lake.retrievers` entry-point group + `resolver.py`
  `get_retriever()`, exactly mirroring the Phase-13 `get_indexer()` /
  `knowledge_lake.indexers` wiring and the `plugins/builtin/__init__.py`
  registration pattern. Satisfies the tool-agnostic / swappability constraint
  (FOUND-08).

### Traversal modes — heuristic default, LLM-guided opt-in
- **D-05:** **Heuristic mode is the default and is pure Python** — no network, no
  LLM, no clock/randomness. Score each `TreeNode` by keyword overlap of query
  terms against `title + summary + section_path`, traverse **DFS**, and return
  the top page ranges as `Hit`s. Deterministic and free (RETR-05,
  deterministic-first constraint).
- **D-06:** **LLM-guided mode is opt-in** (`mode="llm"`) and **reuses the
  `enrich.py` / `tree_index.py` budget-cap flow verbatim**: cache/spend-check →
  budget-check → `litellm.completion(model="cheap_model")` over node summaries to
  select subtrees → validate → return `Hit`s. It **never raises out of a
  budget/LLM failure** — it degrades gracefully to the heuristic result (or an
  empty/partial result with a status), exactly like `enrich_document`. Model is
  the **`cheap_model` task alias** (never a hardcoded provider ID).
- **D-07:** **LLM-nav spend is isolated to `scope="tree_search"`** in
  `get_llm_spend` — a distinct scope from Phase-13's `tree_index` scope (see the
  recent WR-01 fix that isolated tree-index spend) and from `global`, so tree
  search's budget is independently tracked and capped.

### Stage-1 shortlist mechanics
- **D-08:** Reuse `pipeline/search.py:search()` **unchanged** for stage 1
  (higher `shortlist_k`, e.g. 20). Group returned `Hit`s by
  `payload["document"]` (`parsed_artifact_id`, set at index time —
  `pipeline/index.py:152`), aggregate with **max chunk score per document**
  (a document is as relevant as its best chunk; simple and standard), and take
  the top **`max_docs` (default 3)** documents (ARCHITECTURE.md Anti-Pattern 2:
  never load all trees).
- **D-09:** Resolve each shortlisted document's tree via
  `registry_repo.get_child_artifact_by_type(session, parsed_artifact_id,
  "tree_index")` (`registry/repo.py:765`). **Documents with no `tree_index`
  artifact are skipped gracefully** (logged, no stage-2 result for that doc) —
  a missing tree never fails the whole query.

### Parallel tree loading (RETR-07)
- **D-10:** Load candidate trees **concurrently via `asyncio`**. Because
  `StorageBackend.get_object` (`storage/s3.py:136`) is synchronous, wrap each
  load in `loop.run_in_executor(None, …)` and `asyncio.gather` them — the exact
  async-wrap-sync precedent already used in `pipeline/crawl.py:354,667`. Bound
  concurrency with an **`asyncio.Semaphore(concurrency_limit)`**. The otherwise
  synchronous `tree_search()` drives this via a single `asyncio.run(...)` of the
  batch-load helper (adapters stay sync).
- **D-11:** Deserialize loaded JSON back into `TreeIndex`/`TreeNode` objects with
  a `_dict_to_tree` helper that **inverts `tree_index.py:_tree_to_dict`** — the
  retriever always operates on the typed contract, not raw dicts.

### Config surface
- **D-12:** Add a **`TreeSearchSettings`** submodel to `config/settings.py`
  (mirrors Phase-13 `TreeSettings` and the existing `SearchSettings`):
  `mode: Literal["heuristic", "llm"] = "heuristic"`, `shortlist_k: int = 20`,
  `max_docs: int = 3`, `top_k: int = 5`, `concurrency: int = 5`,
  `budget_usd: float = 5.0`. Add a top-level **`retriever: str = "pageindex"`**
  swap key (mirrors the `indexer` swap key). Env override via
  `KLAKE_TREE_SEARCH__*`. All additive — existing chunk `search()` callers are
  untouched.

### Surface exposure (kept minimal — router is Phase 15)
- **D-13:** Phase 14's primary deliverable is the **`pipeline/tree_search.py`
  function + the `RetrieverPlugin` seam**. Add only a **thin `klake tree-search`
  CLI wrapper** (a shim over `tree_search()`, no logic duplicated — same
  thin-wrapper rule as Phase-13 D-10) so the phase is independently testable and
  demoable. The unified `--route`/`route` param across CLI, API, and MCP, and the
  `both`/merge path, are **deferred to Phase 15** to avoid scope creep and a
  surface the router will immediately refactor.

### Claude's Discretion
- Exact heuristic scoring formula (token-overlap vs simple substring, whether to
  weight `title` over `summary`, tie-breaking), the `node_path` string format,
  the `_dict_to_tree` helper's exact shape, and whether stage-2 results across
  docs are merged by score or interleaved — left to planner/executor, provided
  the `Hit` + `citation_source` contract (D-01/D-02) and the `RetrieverPlugin`
  seam (D-03/D-04) stay stable.
- Whether the LLM-nav prompt asks for a single subtree or a ranked node list, and
  its exact JSON response schema/validation model — executor's choice, provided
  it stays behind the budget cap and `scope="tree_search"` (D-06/D-07).
- **Executor model:** sub-agent executors run on `sonnet` (already pinned via
  `model_overrides.gsd-executor` in `.planning/config.json` — no plan task).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### v2.5 project research (read first — this phase is a near-1:1 blueprint match)
- `.planning/research/ARCHITECTURE.md` §3 (IndexerPlugin/**RetrieverPlugin**/
  TreeHit), §4 (**Two-Stage Search** — the core design), §7 (assets/resources),
  Anti-Patterns 2/3/5, Patterns 2/4/5. **Primary reference for this phase.**
  Note D-01: RETR-08 overrides the `TreeHit` sketch → reuse `Hit`.
- `.planning/research/PITFALLS.md` — LLM budget burn (→ heuristic-first + budget
  cap) and indexer↔retriever coupling.
- `.planning/research/STACK.md` — `pageindex 0.3.0.dev3` pin + vendoring fallback
  (only relevant if the LLM-nav builtin uses PageIndex reasoning).
- `.planning/research/FEATURES.md` — heuristic vs LLM retrieval expectations.

### Requirements & roadmap
- `.planning/ROADMAP.md` § "Phase 14: Tree Retrieval" — goal + 5 success criteria.
- `.planning/REQUIREMENTS.md` § "Tree Retrieval" — RETR-04…RETR-08.

### Upstream contract this phase consumes (Phase 13)
- `.planning/phases/13-tree-index-foundation/13-CONTEXT.md` — D-01/D-02
  (`TreeNode`/`TreeIndex` schema), D-05 (`IndexerPlugin` seam to mirror), D-07
  (`tree_index/{domain}/{source_id}/{content_hash}.json` storage key this phase
  loads from).

### Source files to mirror / integrate (existing patterns)
- `src/knowledge_lake/pipeline/search.py` — stage-1 reuse: `search()` stays
  **unchanged**; call with higher `shortlist_k`, group by `payload["document"]`.
- `src/knowledge_lake/pipeline/tree_index.py` — `_TREE_PREFIX`, `_tree_to_dict`
  (L184) serialization; **the load path inverts this** (`_dict_to_tree`, D-11).
- `src/knowledge_lake/pipeline/enrich.py` — LLM budget-cap flow (cache→budget→
  `litellm.completion(cheap_model)`→validate; never raises). LLM-nav mirrors this
  (D-06).
- `src/knowledge_lake/plugins/protocols.py` — `Hit` (L114, add `citation_source`
  D-02); `TreeNode` (L598) / `TreeIndex` (L633) contracts consumed as-is;
  `IndexerPlugin` (L666) is the exact template for the new `RetrieverPlugin`
  (D-03).
- `src/knowledge_lake/plugins/resolver.py`, `plugins/builtin/__init__.py`,
  `pyproject.toml` — `get_indexer()` / `knowledge_lake.indexers` entry-point
  wiring to mirror for `get_retriever()` / `knowledge_lake.retrievers` (D-04).
- `src/knowledge_lake/registry/repo.py` — `get_child_artifact_by_type` (L765,
  loads a doc's `tree_index`, D-09); `get_artifact_by_hash` (L342).
- `src/knowledge_lake/pipeline/index.py` — L152 `payload["document"] =
  parsed_artifact_id` (the stage-1 grouping key, D-08).
- `src/knowledge_lake/storage/s3.py` — `get_object` (L136) to fetch tree JSON;
  `object_uri`.
- `src/knowledge_lake/pipeline/crawl.py` — L354, L667 `run_in_executor`
  async-wrap-sync precedent for RETR-07 parallel loads (D-10).
- `src/knowledge_lake/config/settings.py` — `TreeSettings` / `SearchSettings`
  as the template for `TreeSearchSettings` + `retriever` swap key (D-12).
- `src/knowledge_lake/cli/app.py` — `cmd_search` (L633) as the template for the
  thin `tree-search` CLI wrapper (D-13).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`pipeline/search.py:search()`** — stage 1 verbatim: a chunk search with a
  larger `top_k`; results already carry `payload["document"]` for grouping. No
  change to this function.
- **`enrich.py` budget flow** — the LLM-nav mode (D-06) reuses the
  global-spend-check → per-stage `budget_usd` → single `litellm.completion` →
  status-dict-on-exceed pattern; only the scope changes to `tree_search`.
- **`tree_index.py:_tree_to_dict` + `TreeIndex`/`TreeNode`** — the tree contract
  and its JSON serializer are already in place; Phase 14 only needs the inverse
  loader (`_dict_to_tree`) and a per-node traversal.
- **`registry_repo.get_child_artifact_by_type`** — resolves parsed_id →
  tree_index artifact for stage 2 (D-09).
- **`crawl.py` `run_in_executor`** — the established async-wrap-sync idiom for
  bounding concurrent I/O against sync clients (D-10).

### Established Patterns
- **Plugin via entry-point group + resolver** — `RetrieverPlugin` /
  `knowledge_lake.retrievers` / `get_retriever()` slot in exactly as
  `IndexerPlugin` did in Phase 13.
- **Additive defaults for back-compat** — `Hit.citation_source = "chunk"`,
  new `TreeSearchSettings`, `retriever="pageindex"` — no existing caller changes.
- **Pipeline function called by thin adapters** — `tree_search()` lives in
  `pipeline/`; CLI is a shim (API/MCP `route` param deferred to Phase 15).
- **Deterministic-first** — free heuristic keyword+DFS traversal before any
  paid LLM navigation.

### Integration Points
- New module `src/knowledge_lake/pipeline/tree_search.py` (two-stage orchestrator).
- New builtin `src/knowledge_lake/plugins/builtin/pageindex_retriever.py`.
- New `RetrieverPlugin` in `plugins/protocols.py`; `get_retriever()` in
  `resolver.py`; `knowledge_lake.retrievers` group in `pyproject.toml`.
- `Hit` gains `citation_source` in `plugins/protocols.py`.
- New `TreeSearchSettings` + `retriever` key in `config/settings.py`.
- New `klake tree-search` command in `cli/app.py`.
- **Zero Alembic migrations** (research-confirmed — no schema change; loads
  existing `tree_index` artifacts).

</code_context>

<specifics>
## Specific Ideas

- The retriever must stay **decoupled from PageIndex's internal tree schema** —
  it operates only on our `TreeNode` contract (Anti-Pattern 5). If the LLM-nav
  builtin uses PageIndex reasoning at all, isolate it behind the plugin exactly
  as Phase-13 isolated PageIndex behind the LLM-mode indexer.
- Heuristic traversal must be **reproducible and free** for a given
  `(TreeIndex, query)` — no network, no LLM, no randomness.
- Keep `search()` (chunk path) untouched so the Phase-15 router can compose both
  paths without regressions.

</specifics>

<deferred>
## Deferred Ideas

- **Unified query router + `--route`/`route` param (CLI/API/MCP)** — Phase 15
  (ROUTE-01…04). Phase 14 exposes only a thin `klake tree-search` CLI wrapper.
- **`both`/merge path (chunk+tree dedup & re-rank)** — Phase 15.
- **LLM-based routing for ambiguous queries; routing telemetry/feedback**
  — ROUTE-05/06, deferred to future release.
- **OpenKB wiki export** — Phase 16 (KB-01…05).
- **Corpus-level meta-tree navigation (PageIndex File System, TREE-07)** — v2.6+.

### Reviewed Todos (not folded)
None — `todo.match-phase 14` returned zero matches.

</deferred>

---

*Phase: 14-tree-retrieval*
*Context gathered: 2026-07-13*
