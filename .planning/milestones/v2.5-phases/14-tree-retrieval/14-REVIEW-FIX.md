---
phase: 14-tree-retrieval
fixed_at: 2026-07-14T03:25:00Z
review_path: .planning/phases/14-tree-retrieval/14-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 14: Code Review Fix Report

**Fixed at:** 2026-07-14T03:25:00Z
**Source review:** .planning/phases/14-tree-retrieval/14-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 8 (2 critical, 6 warning; Info findings excluded per `fix_scope: critical_warning`)
- Fixed: 8
- Skipped: 0

## Fixed Issues

### CR-01: Unhandled exception on malformed/missing tree_index storage_uri crashes the entire query

**Files modified:** `src/knowledge_lake/pipeline/tree_search.py`
**Commit:** `9d912c6`
**Applied fix:** Wrapped the `uri_to_key(artifact.storage_uri)` call in stage-2 resolution with a `try/except (ValueError, AttributeError)` that logs `tree_search.bad_storage_uri` and `continue`s to the next document, matching the isolation pattern already used for the other per-document failure paths (missing artifact, S3 load failure, malformed tree JSON) in the same function.

### CR-02: The per-document `retriever.search()` dispatch has no exception isolation

**Files modified:** `src/knowledge_lake/pipeline/tree_search.py`
**Commit:** `a905c99`
**Applied fix:** Wrapped the `retriever.search(...)` call in the deserialize+dispatch loop with `try/except Exception`, logging `tree_search.retriever_failed` and `continue`-ing past the failing document instead of letting a plugin exception abort `results.extend(...)` for the whole batch.

### WR-01: LLM-nav cost extraction reimplements — and breaks — the project's shared cost helper

**Files modified:** `src/knowledge_lake/plugins/builtin/pageindex_retriever.py`
**Commit:** `92d867c`
**Applied fix:** Replaced the bespoke `usage.total_cost` / manual per-1k-token math in `PageIndexRetriever._extract_cost` with a delegating call to `knowledge_lake.llm.pricing.compute_call_cost(response, s)`, matching the project's other budget-gated LLM call sites (`enrich.py`, `tree_index.py`). Verified the module imports cleanly (no circular import — `pricing.py` only type-checks `Settings`).

### WR-02: LLM-nav mode can only reorder already-truncated top-k candidates

**Files modified:** `src/knowledge_lake/plugins/builtin/pageindex_retriever.py`
**Commit:** `fb23ba6`
**Applied fix:** `search()` now computes an untruncated `candidate_pool = self._heuristic_hits(tree_index, terms)`, slices it to `top_k` only for the returned/fallback `heuristic_hits`, and passes the *untruncated* pool into `_llm_nav_search(...)`, with the caller re-truncating the LLM-nav result to `top_k` afterward (`self._llm_nav_search(...)[:top_k]`). This lets the LLM select/reorder any node it judges relevant from its full-tree view, not just the nodes that already survived raw keyword-overlap truncation. Verified heuristic-mode behavior still respects `top_k` truncation with a manual functional test (10-node tree, `top_k=3` → 3 hits returned in score order).
**Note:** This is a logic/behavior change (not just syntax) — flagged for human verification per the logic-bug limitation in the verification strategy, despite passing syntax checks and a manual functional smoke test.

### WR-03: `asyncio.run()` in a sync function has no running-loop guard

**Files modified:** `src/knowledge_lake/pipeline/tree_search.py`
**Commit:** `348d62a` (bundled with WR-06 — both edits landed in the same working-tree state on `tree_search.py` before either was committed; see note below)
**Applied fix:** Added a defensive `asyncio.get_running_loop()` check immediately before `asyncio.run(_load_all(...))` that raises a clear `RuntimeError` with an actionable message if `tree_search()` is ever called from within a running event loop, instead of letting the low-level `asyncio.run()` `RuntimeError` propagate opaquely.

### WR-04: Unbounded node count/prompt size sent to the LLM in nav mode

**Files modified:** `src/knowledge_lake/plugins/builtin/pageindex_retriever.py`
**Commit:** `775e16b`
**Applied fix:** Added a new `_MAX_NAV_NODES = 300` module constant (mirroring the existing `_NODE_EXCERPT_CHARS`/`_MAX_NAV_NODE_IDS` caps) and capped `all_nodes = list(_iter_nodes(tree_index.roots))[:_MAX_NAV_NODES]` in `_llm_nav_search`, bounding both the prompt's request-side size and the `known_ids` validation set derived from it.

### WR-05: The LLM-nav budget pre-check runs outside the mode's own `try/except`

**Files modified:** `src/knowledge_lake/plugins/builtin/pageindex_retriever.py`
**Commit:** `90b1f13`
**Applied fix:** Moved the `get_session()`/`get_llm_spend()` budget read and the `current_spend >= budget_usd` check inside a `try/except Exception` block that logs `tree_search.budget_check_failed` and degrades to `heuristic_hits`, so a transient DB failure during the budget check now degrades exactly like an LLM failure does, instead of propagating out of `_llm_nav_search()` (and, via CR-02, out of `tree_search()` itself).

### WR-06: `TreeSearchSettings.concurrency` has no lower-bound validation and the parallel tree loader has no timeout

**Files modified:** `src/knowledge_lake/config/settings.py`, `src/knowledge_lake/pipeline/tree_search.py`
**Commit:** `348d62a`
**Applied fix:**
- `settings.py`: added a `field_validator("concurrency", "shortlist_k", "max_docs", "top_k", mode="after")` on `TreeSearchSettings` that rejects values `< 1`, preventing `asyncio.Semaphore(0)` misconfiguration at config-load time. Verified with a direct test: `TreeSearchSettings(concurrency=0)` now raises a `pydantic.ValidationError`, and the class's defaults still construct successfully.
- `tree_search.py`: wrapped the `storage.get_object` executor call in `_load_one` with `asyncio.wait_for(..., timeout=_TREE_LOAD_TIMEOUT_SECONDS)` (new constant, 30.0s), so one hung backend call now degrades that single document to `None` (logged as `tree_search.tree_load_failed`) instead of blocking the entire batch forever.

**Note on WR-03/WR-06 bundling:** Both findings touch adjacent regions of `tree_search.py` (the `_load_one` function and the `asyncio.run(...)` call site a few lines below it). WR-03's edit was applied first but not yet committed when WR-06's edits were applied to the same file; both landed in commit `348d62a`. Content-wise both fixes are present, verified (syntax + import + functional validator test), and correct — this is a commit-attribution artifact, not a code-quality issue.

## Skipped Issues

None — all 8 in-scope findings (2 critical, 6 warning) were fixed.

---

_Fixed: 2026-07-14T03:25:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
