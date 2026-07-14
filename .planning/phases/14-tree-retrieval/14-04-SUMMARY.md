---
phase: 14-tree-retrieval
plan: "04"
subsystem: retrieval
tags: [pageindex, tree-search, asyncio, orjson, typer, s3, qdrant]

# Dependency graph
requires:
  - phase: 14-tree-retrieval (14-01/14-02/14-03)
    provides: Hit.citation_source contract, TreeSearchSettings/settings.retriever, PageIndexRetriever + get_retriever() resolver seam
provides:
  - "pipeline/tree_search.py — two-stage tree retrieval orchestrator (RETR-04/07/08)"
  - "_dict_to_tree / _dict_to_tree_index — inverse of tree_index.py's _tree_to_dict (D-11)"
  - "_load_all — Semaphore-bounded async S3 batch loader (RETR-07, D-10)"
  - "klake tree-search CLI command (D-13)"
affects: [15-query-router]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-stage retrieval: reuse existing chunk search() unchanged for stage-1 shortlist, dispatch stage-2 to a swappable RetrieverPlugin"
    - "Single non-nested asyncio.run() drives a bounded-concurrency async batch loader from a sync pipeline function (CR-02 precedent from crawl.py)"

key-files:
  created:
    - src/knowledge_lake/pipeline/tree_search.py
  modified:
    - src/knowledge_lake/cli/app.py

key-decisions:
  - "tree_search() accepts an additional max_docs kwarg (beyond the plan's literal top_k/mode/collection/settings signature) to satisfy test_two_stage_shortlist's call pattern and let callers override settings.tree_search.max_docs per-request, mirroring top_k/mode's override pattern"
  - "search() and StorageBackend are imported at module level (not deferred) in tree_search.py so tests can patch tree_search_module.search / tree_search_module.StorageBackend directly"
  - "registry.repo is imported as a module reference (registry_repo) and called via registry_repo.get_child_artifact_by_type(...) so tests patching knowledge_lake.registry.repo.get_child_artifact_by_type intercept the call"

patterns-established:
  - "Pattern: _dict_to_X deserializers read fields explicitly (never **spread) to bound malformed/oversized JSON before it reaches the typed contract (T-14-10, ASVS V5)"

requirements-completed: [RETR-04, RETR-07, RETR-08]

coverage:
  - id: D1
    description: "tree_search() two-stage orchestrator: Qdrant shortlist (search() reused unchanged) -> per-document tree traversal returning tree Hits"
    requirement: "RETR-04"
    verification:
      - kind: unit
        ref: "tests/unit/test_tree_search.py::TestTwoStageSearch::test_two_stage_shortlist"
        status: pass
    human_judgment: false
  - id: D2
    description: "Stage-1 grouping by payload[document] (max score per doc) with top max_docs shortlist selection, and graceful skip of documents with no tree_index artifact"
    requirement: "RETR-04"
    verification:
      - kind: unit
        ref: "tests/unit/test_tree_search.py::TestTwoStageSearch::test_two_stage_shortlist"
        status: pass
      - kind: unit
        ref: "tests/unit/test_tree_search.py::TestTwoStageSearch::test_parallel_load_and_skip"
        status: pass
    human_judgment: false
  - id: D3
    description: "Semaphore-bounded parallel S3 tree loading via a single non-nested asyncio.run + run_in_executor batch loader (_load_all)"
    requirement: "RETR-07"
    verification:
      - kind: unit
        ref: "tests/unit/test_tree_search.py::TestTwoStageSearch::test_parallel_load_and_skip"
        status: pass
    human_judgment: false
  - id: D4
    description: "_dict_to_tree/_dict_to_tree_index deserialize S3-loaded tree JSON into the typed TreeIndex/TreeNode contract, exact inverse of tree_index.py's _tree_to_dict"
    requirement: "RETR-08"
    verification:
      - kind: unit
        ref: "tests/unit/test_tree_search.py::TestDictToTree::test_dict_to_tree_roundtrip"
        status: pass
    human_judgment: false
  - id: D5
    description: "klake tree-search thin CLI shim: validates --mode against {heuristic, llm} and delegates to tree_search() with no duplicated orchestration logic"
    requirement: "RETR-04"
    verification:
      - kind: unit
        ref: "python -c CliRunner invoke tree-search --help / --mode bogus (plan acceptance_criteria, Task 2)"
        status: pass
    human_judgment: false

duration: 8min
completed: 2026-07-14
status: complete
---

# Phase 14 Plan 04: Tree Search Orchestrator + CLI Summary

**Two-stage tree retrieval orchestrator (`pipeline/tree_search.py`) that reuses the existing chunk `search()` unchanged for a Qdrant shortlist, then loads and traverses candidate PageIndex trees concurrently via a Semaphore-bounded async batch loader, exposed through a thin `klake tree-search` CLI command.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-14T02:40:14Z
- **Completed:** 2026-07-14T02:47:57Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 edited)

## Accomplishments
- `tree_search(query, *, top_k, mode, max_docs, collection, settings)` — stage-1 Qdrant shortlist (via unmodified `pipeline.search.search()`) grouped by `payload["document"]` (max score per doc, top `max_docs` candidates), stage-2 per-document tree traversal via the resolved `RetrieverPlugin`
- `_dict_to_tree` / `_dict_to_tree_index` — exact inverse of `tree_index.py`'s `_tree_to_dict` + tree_dict wrapper, verified by a full round-trip test
- `_load_all` — `asyncio.Semaphore(settings.tree_search.concurrency)` + `run_in_executor` batch loader, driven by exactly one non-nested `asyncio.run()` call in the sync `tree_search()` entry point (CR-02)
- Graceful skip: a document whose `get_child_artifact_by_type(..., "tree_index")` returns `None` (missing tree) or whose loaded JSON fails to parse is skipped without failing the query (D-09)
- `klake tree-search` — thin CLI shim mirroring `cmd_search`'s validation/rendering pattern, delegating all orchestration to `tree_search()` (D-13)
- Full Wave-0 test suite for the phase is now GREEN: `pytest tests/unit/test_tree_search.py` — 8/8 passed (previously blocked by `ModuleNotFoundError`)

## Task Commits

1. **Task 1: Create pipeline/tree_search.py — two-stage orchestrator + _dict_to_tree + async loader (RETR-04/07/08, D-08..D-11)** - `59eeba1` (feat)
2. **Task 2: Add thin klake tree-search CLI shim (D-13)** - `d5380b1` (feat)

**Plan metadata:** (recorded below, this commit)

## Files Created/Modified
- `src/knowledge_lake/pipeline/tree_search.py` - New two-stage orchestrator: stage-1 chunk shortlist (search() reused unchanged), stage-2 tree resolution/parallel-load/deserialize/dispatch, deterministic cross-document merge
- `src/knowledge_lake/cli/app.py` - Added `cmd_tree_search` (`klake tree-search`) command, a thin shim over `tree_search()`

## Decisions Made
- Added a `max_docs` keyword parameter to `tree_search()` beyond the plan's literal `top_k`/`mode`/`collection`/`settings` signature list — `test_two_stage_shortlist` and `test_parallel_load_and_skip` both call `tree_search(..., max_docs=2)`, and this mirrors the existing `top_k`/`mode` per-request-override-of-settings pattern already established for those two parameters. Defaults to `settings.tree_search.max_docs` when omitted (Rule 1 — the plan's own behavior spec ties max_docs shortlisting to a settings-configurable value, and the test suite requires a call-site override to exercise it deterministically).
- `search` and `StorageBackend` are imported at module level in `tree_search.py` (not lazily inside the function) so `patch.object(tree_search_module, "search", ...)` / `patch.object(tree_search_module, "StorageBackend", ...)` in the test suite intercept the calls — required for the tests to pass as written, and consistent with `tree_index.py`'s own module-level `StorageBackend` import.
- `registry.repo` is imported as `registry_repo` (module reference, not a direct function import) so `patch("knowledge_lake.registry.repo.get_child_artifact_by_type", ...)` intercepts calls made via `registry_repo.get_child_artifact_by_type(...)` — mirrors the existing `tree_index.py` import style.

## Deviations from Plan

None - plan executed exactly as written (the `max_docs` parameter addition above is an implementation detail required to satisfy the plan's own `<behavior>` spec and test suite, not a deviation from the plan's intent).

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 14 (tree-retrieval) is functionally complete: `tree_search()` delivers the full two-stage flow (Qdrant shortlist -> graceful per-document tree traversal -> Semaphore-bounded parallel loading -> typed deserialization -> deterministic merge), exposed via `klake tree-search`.
- `pytest tests/unit/test_tree_search.py -q` — 8/8 passed. `pytest tests/unit/test_builtin_plugins.py -q` — 33/33 passed (no regression to retriever conformance / chunk / indexer paths).
- `git diff --quiet src/knowledge_lake/pipeline/search.py` confirms the chunk stage-1 path is byte-identical (D-08) — the Phase-15 query router can compose `search()` and `tree_search()` side-by-side without any chunk-path behavior change.
- Full unit suite: 577 passed, 1 xfailed, 39 xpassed — no regressions introduced.
- Blocker carried forward (already logged in STATE.md at Phase 14 start): tree traversal prompt quality is unvalidated against ground-truth healthcare benchmarks, and two-stage search latency (3-15s without parallelization) is mitigated here by the concurrency-bounded loader but not benchmarked end-to-end against a live Qdrant/S3 stack in this environment.

---
*Phase: 14-tree-retrieval*
*Completed: 2026-07-14*

## Self-Check: PASSED

- FOUND: src/knowledge_lake/pipeline/tree_search.py
- FOUND: .planning/phases/14-tree-retrieval/14-04-SUMMARY.md
- FOUND: commit 59eeba1
- FOUND: commit d5380b1
