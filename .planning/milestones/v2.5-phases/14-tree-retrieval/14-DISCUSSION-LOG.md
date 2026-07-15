# Phase 14: Tree Retrieval - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-13
**Phase:** 14-tree-retrieval
**Mode:** `--auto` (all gray areas auto-resolved to the recommended option)
**Areas discussed:** Result contract, Retriever seam, Traversal modes, Stage-1 shortlist, Parallel loading, Config surface, Surface exposure

---

## Result contract (RETR-08)

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse `Hit` + `citation_source` discriminator | One result type across chunk & tree; add `citation_source: str = "chunk"` field | ✓ |
| New `TreeHit` dataclass (per ARCHITECTURE.md §3) | Separate tree-specific result type with node_path/score | |

**Auto choice:** Reuse `Hit`. RETR-08 explicitly mandates "`Hit` objects … with a `citation_source: tree` discriminator", which overrides the research's `TreeHit` sketch. A single type keeps chunk+tree results mergeable for the Phase-15 router.
**Notes:** `citation_source` added as an additive-default field (mirrors `VectorPoint.sparse = None`). Tree payload carries page_start/page_end/section_path/node_id/node_path/document.

---

## Retriever seam

| Option | Description | Selected |
|--------|-------------|----------|
| New `RetrieverPlugin` protocol + builtin + resolver + entry-point group | Mirror Phase-13 `IndexerPlugin`; `knowledge_lake.retrievers` group | ✓ |
| Inline traversal in `pipeline/tree_search.py` (no plugin) | Simpler, but not swappable | |

**Auto choice:** Add `RetrieverPlugin`. Satisfies the tool-agnostic / swappability constraint (FOUND-08) and matches the Phase-13 precedent exactly.
**Notes:** Retriever consumes the shared `TreeIndex`/`TreeNode` contract, never PageIndex's internal schema (Anti-Pattern 5).

---

## Traversal modes (RETR-05, RETR-06)

| Option | Description | Selected |
|--------|-------------|----------|
| Heuristic default (keyword+DFS, no LLM) + opt-in LLM-guided | Deterministic-first; LLM via `mode="llm"`, budget-gated | ✓ |
| LLM-guided as the default path | Richer but costs money on every query | |

**Auto choice:** Heuristic default, LLM opt-in. Honors the deterministic-first constraint.
**Notes:** LLM mode reuses the enrich.py/tree_index.py budget-cap flow verbatim via `cheap_model`; spend isolated to `scope="tree_search"`; never raises on budget/LLM failure.

---

## Stage-1 shortlist mechanics (RETR-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse `search()`, group by `payload["document"]`, max-score agg, top `max_docs=3` | Cheap Qdrant narrowing; skip docs lacking a tree | ✓ |
| Mean-score aggregation across a doc's chunks | Smoother but dilutes a strong single-chunk match | |

**Auto choice:** Reuse `search()` unchanged with max-score aggregation, top `max_docs=3`.
**Notes:** Resolve tree via `get_child_artifact_by_type(session, parsed_id, "tree_index")`; documents without a tree_index artifact are skipped gracefully (Anti-Pattern 2: never load all trees).

---

## Parallel loading (RETR-07)

| Option | Description | Selected |
|--------|-------------|----------|
| `asyncio.gather` over `run_in_executor`, Semaphore-bounded | Wrap sync `get_object`; crawl.py precedent | ✓ |
| Sequential loads | Simpler but violates RETR-07 parallel requirement | |

**Auto choice:** asyncio parallel loading, Semaphore-bounded by configurable `concurrency`.
**Notes:** `tree_search()` stays sync for adapters; drives loads via a single `asyncio.run(...)`. `_dict_to_tree` inverts `tree_index.py:_tree_to_dict`.

---

## Config surface

| Option | Description | Selected |
|--------|-------------|----------|
| New `TreeSearchSettings` submodel + `retriever` swap key | Mirrors Phase-13 `TreeSettings`; additive | ✓ |
| Extend existing `SearchSettings` | Fewer models but couples chunk & tree config | |

**Auto choice:** New `TreeSearchSettings` (mode/shortlist_k/max_docs/top_k/concurrency/budget_usd) + top-level `retriever="pageindex"` swap key.
**Notes:** Env override `KLAKE_TREE_SEARCH__*`; existing chunk `search()` callers untouched.

---

## Surface exposure

| Option | Description | Selected |
|--------|-------------|----------|
| Thin `klake tree-search` CLI wrapper; defer `--route`/API/MCP to Phase 15 | Testable now, no scope creep | ✓ |
| Full `--route` param across CLI/API/MCP now | Pulls Phase-15 (Query Router) scope forward | |

**Auto choice:** Thin CLI wrapper only. The unified router surface is Phase 15's job (ROUTE-04) and would immediately refactor anything built here.
**Notes:** Same thin-wrapper rule as Phase-13 D-10 — CLI shim shares one `tree_search()` function, no duplicated logic.

---

## Claude's Discretion

- Exact heuristic scoring formula and tie-breaking; `node_path` string format; `_dict_to_tree` shape; whether cross-doc stage-2 results merge by score or interleave.
- LLM-nav prompt shape (single subtree vs ranked node list) and its JSON response/validation schema, provided it stays behind the budget cap and `scope="tree_search"`.
- Executor model pinned to `sonnet` via `.planning/config.json`.

## Deferred Ideas

- Unified query router + `--route`/`route` param (CLI/API/MCP) → Phase 15 (ROUTE-01…04).
- `both`/merge (chunk+tree dedup & re-rank) path → Phase 15.
- LLM-based routing + routing telemetry → ROUTE-05/06 (future).
- OpenKB wiki export → Phase 16 (KB-01…05).
- Corpus-level meta-tree (PageIndex File System, TREE-07) → v2.6+.
