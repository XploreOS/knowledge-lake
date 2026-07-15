---
phase: 14-tree-retrieval
plan: "02"
subsystem: api
tags: [pydantic, protocol, plugin-seam, settings, retrieval]

# Dependency graph
requires:
  - phase: 13-tree-index-foundation
    provides: TreeNode/TreeIndex contract, IndexerPlugin seam pattern (D-05), TreeSettings + _validate_swap_key precedent
  - phase: 14-tree-retrieval (14-01)
    provides: Wave 0 RED-state test scaffold (test_tree_search.py, TestPageIndexRetriever stub) with concrete verify targets
provides:
  - "Hit.citation_source discriminator (default 'chunk', additive) — D-02"
  - "RetrieverPlugin @runtime_checkable Protocol (name + search signature) — D-03"
  - "TreeSearchSettings submodel (mode/shortlist_k/max_docs/top_k/concurrency/budget_usd/model_alias) — D-12, A1"
  - "Settings.retriever swap key defaulting to 'pageindex', validated by _validate_swap_key — D-12, A2"
affects: [14-03-retriever-builtin, 14-04-orchestrator-cli]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Additive-default back-compat field (Hit.citation_source, mirrors VectorPoint.sparse)"
    - "Protocol mirroring: RetrieverPlugin copied verbatim from IndexerPlugin's @runtime_checkable + name:str + single-method shape"
    - "Config submodel mirroring: TreeSearchSettings copied from TreeSettings shape, wired via Field(default_factory=...)"
    - "ASVS V5 swap-key validation: new swap keys must be added to the _validate_swap_key field_validator tuple (mirrors T-13-03)"

key-files:
  created: []
  modified:
    - src/knowledge_lake/plugins/protocols.py
    - src/knowledge_lake/config/settings.py

key-decisions:
  - "No separate TreeHit type added — Hit reused directly per D-01, overriding the ARCHITECTURE.md TreeHit sketch"
  - "model_alias field added to TreeSearchSettings beyond the D-12 literal list per Assumption A1 (required for D-06 LLM-nav's cheap_model alias)"
  - "retriever added to _validate_swap_key tuple in alphabetical order (crawler, discovery, embedder, indexer, parser, retriever, vectorstore) per Assumption A2"

patterns-established:
  - "RetrieverPlugin Protocol consumes only the shared TreeIndex/TreeNode contract, never PageIndex's internal schema (ARCHITECTURE.md Anti-Pattern 5)"

requirements-completed: [RETR-04, RETR-06, RETR-07, RETR-08]

coverage:
  - id: D1
    description: "Hit dataclass gains citation_source: str = 'chunk' additive-default field; chunk search callers unchanged"
    requirement: "RETR-08"
    verification:
      - kind: unit
        ref: "python -c import check: Hit(id='x',score=1.0).citation_source == 'chunk'"
        status: pass
      - kind: unit
        ref: "tests/unit/test_tree_search.py::TestHitContract::test_hit_citation_source_default (blocked by module-level ImportError until Plan 14-03/14-04 create pipeline/tree_search.py — expected Wave 0 RED state per 14-01-SUMMARY.md)"
        status: unknown
    human_judgment: false
  - id: D2
    description: "RetrieverPlugin @runtime_checkable Protocol added to plugins/protocols.py with name:str + search(tree_index, query, *, top_k, mode, settings) -> list[Hit] signature (D-03); no TreeHit type added (D-01)"
    requirement: "RETR-04"
    verification:
      - kind: unit
        ref: "python -c import check: getattr(RetrieverPlugin, '_is_runtime_protocol', False) is True"
        status: pass
      - kind: unit
        ref: "grep -c 'class RetrieverPlugin' == 1; grep -c 'class TreeHit' == 0"
        status: pass
      - kind: unit
        ref: "tests/unit/test_builtin_plugins.py::TestPageIndexRetriever (collects now; fails on PageIndexRetriever import — expected, Plan 14-03 territory)"
        status: unknown
    human_judgment: false
  - id: D3
    description: "TreeSearchSettings submodel added to config/settings.py with mode/shortlist_k/max_docs/top_k/concurrency/budget_usd/model_alias fields and correct D-12/A1 defaults"
    requirement: "RETR-06"
    verification:
      - kind: unit
        ref: "python -c import check: Settings().tree_search fields == ('heuristic',20,3,5,5,5.0,'cheap_model')"
        status: pass
      - kind: unit
        ref: "KLAKE_TREE_SEARCH__MODE=llm env override resolves Settings().tree_search.mode == 'llm'"
        status: pass
    human_judgment: false
  - id: D4
    description: "Settings.retriever swap key added, default 'pageindex', validated by _validate_swap_key ASVS V5 regex (A2, mirrors T-13-03)"
    requirement: "RETR-07"
    verification:
      - kind: unit
        ref: "python -c import check: Settings().retriever == 'pageindex'; Settings(retriever='bad name') raises pydantic.ValidationError"
        status: pass
      - kind: unit
        ref: "grep -Eq 'field_validator\\(.*\"retriever\".*mode=\"after\"\\)' src/knowledge_lake/config/settings.py"
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-07-14
status: complete
---

# Phase 14 Plan 02: Tree Retrieval Contracts Summary

**Additive `citation_source` discriminator on `Hit`, a `RetrieverPlugin` Protocol mirroring `IndexerPlugin`, and a `TreeSearchSettings` config submodel + validated `retriever` swap key — the typed seams Waves 2-3 build on.**

## Performance

- **Duration:** ~12 min
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments
- `Hit` gains `citation_source: str = "chunk"` as a trailing defaulted dataclass field (D-02) — existing chunk search stays byte-identical; tree search (Plan 14-03) will set `"tree"`.
- New `@runtime_checkable RetrieverPlugin` Protocol added immediately after `IndexerPlugin` in `plugins/protocols.py`, with `name: str` and `search(tree_index: TreeIndex, query: str, *, top_k: int = 5, mode: str = "heuristic", settings: Any | None = None) -> list[Hit]` (D-03). No separate `TreeHit` type added (D-01).
- New `TreeSearchSettings` submodel added to `config/settings.py` mirroring `TreeSettings`'s shape: `mode`, `shortlist_k`, `max_docs`, `top_k`, `concurrency`, `budget_usd`, and `model_alias` (the last added beyond the D-12 literal list per Assumption A1, required for D-06's LLM-nav `cheap_model` alias).
- `Settings.tree_search` (default_factory-wired) and `Settings.retriever` (default `"pageindex"`) added as additive fields; `retriever` added to the `_validate_swap_key` field_validator tuple (alphabetically ordered) so malicious entry-point names are rejected per ASVS V5 (A2, mirrors T-13-03).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add Hit.citation_source and RetrieverPlugin to protocols.py (D-02, D-03)** - `437bd4a` (feat)
2. **Task 2: Add TreeSearchSettings submodel + retriever swap key + validator entry to settings.py (D-12, A1, A2)** - `e719736` (feat)

**Plan metadata:** committed separately after this SUMMARY.

## Files Created/Modified
- `src/knowledge_lake/plugins/protocols.py` - `Hit` gains `citation_source` field; new `RetrieverPlugin` Protocol after `IndexerPlugin`
- `src/knowledge_lake/config/settings.py` - new `TreeSearchSettings` submodel; `Settings.tree_search` + `Settings.retriever` fields; `retriever` added to `_validate_swap_key` tuple

## Decisions Made
- No `TreeHit` type — reused `Hit` directly per D-01 (overrides the `ARCHITECTURE.md` `TreeHit` sketch); keeps chunk and tree results mergeable for the Phase-15 router.
- `model_alias` added to `TreeSearchSettings` beyond the D-12 literal field list per Assumption A1 — the D-06 LLM-nav path needs the `cheap_model` task alias and there was no other field carrying it.
- `retriever` inserted into the `_validate_swap_key` tuple in alphabetical order (`crawler, discovery, embedder, indexer, parser, retriever, vectorstore`) per Assumption A2, mirroring the T-13-03 `indexer` hardening.

## Deviations from Plan

None - plan executed exactly as written. Both tasks' acceptance criteria (direct Python import/assert checks, `grep` counts, and the env-override check) all pass exactly as specified.

One nuance worth recording (not a deviation, no fix required): Task 1's `<verify>` command also lists `pytest tests/unit/test_tree_search.py::TestHitContract::test_hit_citation_source_default -q` as a regression target. That whole test file unconditionally imports `knowledge_lake.pipeline.tree_search` at module scope (Wave 0 scaffold design, `test_tree_search.py:28`), so it fails collection with `ModuleNotFoundError` until Plan 14-03/14-04 create that module — this is the documented Wave 0 RED state (see 14-01-SUMMARY.md "Next Phase Readiness": *"Plan 14-02 ... will turn test_builtin_plugins.py's new class collectible (though it will still fail at the PageIndexRetriever import until 14-03)"* — it makes no equivalent claim for `test_tree_search.py`, which requires the pipeline module itself). Verified the underlying behavior directly via `python -c` import assertions instead (all pass). `tests/unit/test_builtin_plugins.py::TestPageIndexRetriever` **does** now collect successfully (was blocked by `ImportError: cannot import name 'RetrieverPlugin'` before this plan) and fails only on the still-missing `PageIndexRetriever` class, exactly as anticipated for Wave 2 (Plan 14-03).

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. Zero new imports/packages (protocols.py and settings.py edits only); Package Legitimacy Audit is a no-op per the plan's threat model.

## Next Phase Readiness

- `RetrieverPlugin`, `TreeSearchSettings`, and the `retriever` swap key are all in place; Plan 14-03 (`PageIndexRetriever` builtin + `get_retriever()` resolver + entry-point group) can implement against a stable, tested contract.
- Regression suite confirmed clean: `pytest tests/unit/test_builtin_plugins.py -q -k "not PageIndexRetriever"` → 31 passed; full `tests/unit` run with `--continue-on-collection-errors` shows only the two expected pre-existing-scaffold failures (`TestPageIndexRetriever`'s two tests) and the one expected collection error (`test_tree_search.py`), no other regressions.
- No blockers identified for Wave 2 (Plan 14-03).

---
*Phase: 14-tree-retrieval*
*Completed: 2026-07-14*

## Self-Check: PASSED

- FOUND: src/knowledge_lake/plugins/protocols.py (citation_source, RetrieverPlugin)
- FOUND: src/knowledge_lake/config/settings.py (TreeSearchSettings, retriever)
- FOUND commit: 437bd4a
- FOUND commit: e719736
