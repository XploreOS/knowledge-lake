---
phase: 14-tree-retrieval
plan: "01"
subsystem: testing
tags: [pytest, tdd, retriever-plugin, tree-search, wave-0-scaffold]

# Dependency graph
requires:
  - phase: 13-tree-index-foundation
    provides: TreeIndex/TreeNode contract, IndexerPlugin seam pattern, tree_index.py serialization (_tree_to_dict)
provides:
  - Wave 0 RED-state test scaffold for Phase 14 (RETR-04..08 + D-11)
  - Concrete automated verify targets for every Wave 1-3 implementation task
affects: [14-02-protocols-settings, 14-03-retriever-builtin, 14-04-orchestrator-cli]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Wave 0 test scaffold (Nyquist compliance) — tests written before implementation, RED via ImportError"
    - "In-memory SQLite (StaticPool) + _patch_engine autouse fixture, mirrored verbatim from test_tree_index.py"
    - "hand-built TreeIndex fixture (no S3, no LLM) for deterministic heuristic-scoring and round-trip tests"

key-files:
  created: [tests/unit/test_tree_search.py]
  modified: [tests/unit/test_builtin_plugins.py]

key-decisions:
  - "Reused test_tree_index.py's engine/_patch_engine/session/seeded fixtures verbatim rather than inventing new DB fixtures"
  - "Patched knowledge_lake.registry.repo.get_child_artifact_by_type at module level (not via tree_search_module.registry_repo) since the eventual implementation is expected to reference registry_repo.<fn> from the shared repo module object"
  - "hand_tree fixture titles/summaries chosen so query 'budget cap' matches §1/§1.1 but not §2, to exercise keyword-overlap scoring deterministically"

patterns-established:
  - "Wave 0 scaffold pattern for Phase 14 mirrors Phase 13: tests import the not-yet-existing module at top level so the whole file fails collection with ImportError (correct RED state) until implementation ships"

requirements-completed: [RETR-04, RETR-05, RETR-06, RETR-07, RETR-08]

coverage:
  - id: D1
    description: "tests/unit/test_tree_search.py created with 8 test functions covering RETR-04..08 and the D-11 _dict_to_tree_index round-trip, all failing with ImportError (Wave 0 RED state)"
    verification:
      - kind: unit
        ref: "pytest tests/unit/test_tree_search.py --collect-only (asserts ImportError)"
        status: pass
    human_judgment: false
  - id: D2
    description: "tests/unit/test_builtin_plugins.py extended with TestPageIndexRetriever (entry-point registration + isinstance(RetrieverPlugin) conformance), failing with ImportError (Wave 0 RED state), existing 31 tests unaffected"
    verification:
      - kind: unit
        ref: "pytest tests/unit/test_builtin_plugins.py --collect-only (asserts ImportError); grep -c 'def test_' confirms count == 31 + 2"
        status: pass
    human_judgment: false

duration: 15min
completed: 2026-07-14
status: complete
---

# Phase 14 Plan 01: Wave 0 Test Scaffold Summary

**Wave 0 RED-state pytest scaffold for two-stage tree retrieval (RETR-04..08 + D-11 round-trip), giving every Wave 1-3 implementation task a concrete automated verify target before code is written.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 2 completed
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- Created `tests/unit/test_tree_search.py` with 8 test functions across 6 classes (`TestHitContract`, `TestDictToTree`, `TestHeuristicRetriever`, `TestLlmNav`, `TestTwoStageSearch`), plus a hand-built 2-level `TreeIndex` fixture (`hand_tree`) and its serialized-dict counterpart (`hand_tree_dict`) for S3-free heuristic scoring and `_dict_to_tree_index` round-trip verification.
- Extended `tests/unit/test_builtin_plugins.py` with a `RetrieverPlugin` import and a `TestPageIndexRetriever` conformance class (entry-point registration in `knowledge_lake.retrievers` + `isinstance(..., RetrieverPlugin)`), mirroring the existing `TestIndexerPluginBuiltin` pattern.
- Verified both files produce the correct Wave 0 RED state: `pytest --collect-only` fails with `ImportError`/`ModuleNotFoundError` for the not-yet-existing `knowledge_lake.pipeline.tree_search` module and `RetrieverPlugin` symbol.
- Confirmed no regression: full `tests/unit` suite still shows 536 passed, 1 xfailed, 39 xpassed (matching the pre-existing v2.5 baseline) with `--continue-on-collection-errors`, isolating the 2 expected new collection errors to the Wave 0 scaffold files only.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create tests/unit/test_tree_search.py — RETR-04..08 + D-11 scaffold** - `3c29ae0` (test)
2. **Task 2: Extend tests/unit/test_builtin_plugins.py with RetrieverPlugin conformance stub (D-04)** - `93fcf33` (test)

**Plan metadata:** committed separately after this SUMMARY.

## Files Created/Modified
- `tests/unit/test_tree_search.py` - New Wave 0 scaffold: `TestHitContract.test_hit_citation_source_default`, `TestDictToTree.test_dict_to_tree_roundtrip`, `TestHeuristicRetriever.{test_heuristic_no_llm,test_citation_source_tree,test_no_hardcoded_provider_model_ids}`, `TestLlmNav.test_llm_nav_degrades`, `TestTwoStageSearch.{test_two_stage_shortlist,test_parallel_load_and_skip}`
- `tests/unit/test_builtin_plugins.py` - Added `RetrieverPlugin` import and `TestPageIndexRetriever` class (`test_pageindex_retriever_entry_point_registered`, `test_pageindex_retriever_satisfies_protocol`)

## Decisions Made
- Reused `test_tree_index.py`'s `engine`/`_patch_engine`/`session`/`seeded` fixtures verbatim (in-memory SQLite via `StaticPool`, `registry_db.get_engine` monkeypatched) rather than inventing new DB scaffolding — keeps Wave 0 fixtures consistent with the Phase 13 precedent.
- Patched `knowledge_lake.registry.repo.get_child_artifact_by_type` as a module-level attribute (via `patch("knowledge_lake.registry.repo.get_child_artifact_by_type", ...)`) rather than `tree_search_module.registry_repo.get_child_artifact_by_type`, since the eventual `tree_search.py` is expected to do `from knowledge_lake.registry import repo as registry_repo` and call `registry_repo.get_child_artifact_by_type(...)` — patching the shared module object's attribute is robust regardless of that import style.
- `hand_tree` fixture titles/summaries were deliberately chosen ("Budget Overview" / "Budget Cap Details" vs. "Unrelated Topic") so the fixed query `"budget cap"` matches §1/§1.1 and not §2, giving the heuristic-scoring tests a deterministic, human-verifiable ground truth.

## Deviations from Plan

None - plan executed exactly as written. Both tasks' acceptance criteria (file existence, `def test_` counts, load-bearing identifier greps, fixture-wiring greps, and the `ImportError` collection check) were verified directly via `grep` and `uv run pytest --collect-only` and all pass exactly as specified.

## Issues Encountered

None - `orjson` (used in the `hand_tree_dict` fixture and the two-stage orchestrator test mocks) is available in the project's `.venv` even though it is absent from the bare system `python3`; running tests via `uv run pytest` resolved this without any code change.

## User Setup Required

None - no external service configuration required. This plan wrote test files only; no packages were installed (Package Legitimacy Audit in the plan's threat model was a no-op, as expected).

## Next Phase Readiness

- Wave 0 scaffold is complete and in the correct RED state: `tests/unit/test_tree_search.py` fails collection with `ModuleNotFoundError: No module named 'knowledge_lake.pipeline.tree_search'`, and `tests/unit/test_builtin_plugins.py` fails collection with `ImportError: cannot import name 'RetrieverPlugin'`.
- Plan 14-02 (protocols + settings) can now proceed: adding `citation_source` to `Hit`, the `RetrieverPlugin` Protocol, and `TreeSearchSettings` will turn `test_builtin_plugins.py`'s new class collectible (though it will still fail at the `PageIndexRetriever` import until 14-03).
- Plan 14-03 (retriever builtin) and Plan 14-04 (orchestrator + CLI) each have concrete, named pytest targets to drive their RED→GREEN transition (e.g. `pytest tests/unit/test_tree_search.py::TestHeuristicRetriever::test_heuristic_no_llm -x`).
- No blockers identified for Wave 1.

---
*Phase: 14-tree-retrieval*
*Completed: 2026-07-14*

## Self-Check: PASSED

- FOUND: tests/unit/test_tree_search.py
- FOUND: tests/unit/test_builtin_plugins.py
- FOUND: .planning/phases/14-tree-retrieval/14-01-SUMMARY.md
- FOUND commit: 3c29ae0
- FOUND commit: 93fcf33
