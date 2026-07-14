---
phase: 14-tree-retrieval
plan: "03"
subsystem: retrieval
tags: [retriever-plugin, tree-search, litellm, entry-points, budget-cap, heuristic-scoring]

# Dependency graph
requires:
  - phase: 14-02
    provides: "Hit.citation_source field, RetrieverPlugin Protocol, TreeSearchSettings config surface"
provides:
  - "PageIndexRetriever builtin (name='pageindex') with heuristic keyword+DFS traversal (RETR-05) and opt-in budget-capped LLM-guided navigation (RETR-06), both emitting citation_source='tree' Hits (RETR-08)"
  - "knowledge_lake.retrievers entry-point group + resolver.get_retriever() seam (D-04)"
affects: [14-04, phase-15-query-router]

# Tech tracking
tech-stack:
  added: []
  patterns: [budget-capped-never-raising-llm-call, entry-point-plugin-seam, dfs-tree-scoring]

key-files:
  created:
    - src/knowledge_lake/plugins/builtin/pageindex_retriever.py
  modified:
    - src/knowledge_lake/plugins/resolver.py
    - pyproject.toml
    - src/knowledge_lake/plugins/builtin/__init__.py

key-decisions:
  - "Heuristic search computed first regardless of mode, so it always serves as the LLM-nav degrade fallback (A4)"
  - "LLM-nav spend isolated to scope='tree_search', distinct from Phase-13's tree_index and global scopes (D-07)"
  - "LLM-nav reorders heuristic Hits by validated node_ids rather than replacing them — invalid/unknown node_ids are discarded, unmentioned heuristic hits keep their place at the end"

patterns-established:
  - "Pattern: PageIndexRetriever mirrors PageIndexIndexer's constructor-injected litellm_url/api_key (CR-03, no os.environ reads)"
  - "Pattern: budget-capped LLM call wrapped in try/except Exception, degrading to a precomputed fallback result — mirrors enrich.py/tree_index.py"

requirements-completed: [RETR-05, RETR-06, RETR-08]

coverage:
  - id: D1
    description: "PageIndexRetriever satisfies RetrieverPlugin and returns deterministic heuristic Hits with citation_source='tree' and full page-level payload (node_id, section_path, page_start, page_end, node_path, document)"
    requirement: "RETR-05"
    verification:
      - kind: unit
        ref: "manual script mirroring tests/unit/test_tree_search.py::TestHeuristicRetriever (module import blocked until 14-04 ships pipeline/tree_search.py) — see Issues Encountered"
        status: pass
    human_judgment: false
  - id: D2
    description: "Opt-in LLM-nav mode is budget-gated at scope='tree_search' and degrades to the heuristic result on budget-exceeded or litellm.completion exception, never raising"
    requirement: "RETR-06"
    verification:
      - kind: unit
        ref: "manual script mirroring tests/unit/test_tree_search.py::TestLlmNav (same collection blocker) — see Issues Encountered"
        status: pass
    human_judgment: false
  - id: D3
    description: "citation_source='tree' discriminator and page-level payload on all tree-search Hits"
    requirement: "RETR-08"
    verification:
      - kind: unit
        ref: "manual script test_citation_source_tree equivalent"
        status: pass
    human_judgment: false
  - id: D4
    description: "knowledge_lake.retrievers entry-point group registers pageindex; resolver.get_retriever() resolves it after an editable reinstall; LookupError on unknown names"
    requirement: "D-04 (seam wiring, no dedicated REQ-ID)"
    verification:
      - kind: unit
        ref: "tests/unit/test_builtin_plugins.py::TestPageIndexRetriever"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-07-14
status: complete
---

# Phase 14 Plan 03: PageIndexRetriever + Resolver Seam Summary

**Built the swappable tree-retriever plugin: deterministic keyword+DFS heuristic traversal by default, an opt-in budget-capped LLM-guided navigation mode that never raises, and the `knowledge_lake.retrievers` entry-point seam mirroring Phase 13's indexer wiring.**

## Performance

- **Duration:** 25 min
- **Tasks:** 2 completed
- **Files modified:** 4 (1 new, 3 edited)

## Accomplishments
- `PageIndexRetriever` (`name="pageindex"`) satisfies `RetrieverPlugin` and implements `search(tree_index, query, *, top_k, mode, settings) -> list[Hit]`
- Heuristic mode: pure-Python keyword-overlap scoring over `title + summary + section_path`, DFS traversal threading a `node_path` ancestor chain, stable `(-score, section_path)` tie-break — zero LLM calls, deterministic across repeated calls
- LLM-nav mode (`mode="llm"`): budget-gated at `scope="tree_search"` (isolated from Phase-13's `tree_index` scope and `global`), calls `litellm.completion(model=f"openai/{model_alias}")` with an injection-resistant system prompt over bounded node excerpts, validates the response via a bounded `NavResult` Pydantic model, reorders the heuristic Hits by validated `node_ids`, and degrades to the heuristic result on budget-exceeded or ANY exception — never raises
- `knowledge_lake.retrievers` entry-point group registered in `pyproject.toml`; `resolver.get_retriever(settings)` resolves it (mirrors `get_indexer`), injecting `litellm_url`/`litellm_api_key` for the `pageindex` name; `LookupError` on unknown names via the existing `_resolve_with_kwargs`

## Task Commits

1. **Task 1: Create pageindex_retriever.py — heuristic DFS + LLM-nav** - `709f21f` (feat)
2. **Task 2: Wire the retriever seam — get_retriever + entry-point group + editable reinstall** - `d46c811` (feat)

**Plan metadata:** (this commit)

## Files Created/Modified
- `src/knowledge_lake/plugins/builtin/pageindex_retriever.py` - New: `PageIndexRetriever`, `_score_node`, `_dfs_score`, `_iter_nodes`, `NavResult`, `_NAV_SYSTEM_PROMPT`
- `src/knowledge_lake/plugins/resolver.py` - `GROUP_RETRIEVERS` constant + `get_retriever(settings)`
- `pyproject.toml` - `[project.entry-points."knowledge_lake.retrievers"]` → `pageindex`
- `src/knowledge_lake/plugins/builtin/__init__.py` - Registration note for the new retrievers group

## Decisions Made
- Heuristic Hits are always computed first (before checking `mode`), so the exact same computation serves both the default heuristic return path and the LLM-nav fallback — guarantees byte-identical degrade behavior (A4).
- LLM-nav's `NavResult.node_ids` list is bounded (`max_length=50`) and any `node_id` not present in the tree is discarded before use, per ASVS V5.
- LLM-nav reorders (not replaces) heuristic Hits: hits matching a validated `node_id` are promoted to the front in the LLM's order; any heuristic hit not mentioned by the LLM is appended afterward so a partial/bad LLM response never silently drops a valid keyword match.

## Deviations from Plan

None — plan executed exactly as written. Both tasks' actions matched the plan's `<action>` blocks verbatim; no Rule 1-4 auto-fixes were needed.

## Issues Encountered

**Known Wave-ordering gap in `<verify>` command (not a code defect):** Task 1's specified verify command, `pytest tests/unit/test_tree_search.py::TestHeuristicRetriever tests/unit/test_tree_search.py::TestLlmNav -q`, cannot pass in this plan's scope because `tests/unit/test_tree_search.py` has a module-level `import knowledge_lake.pipeline.tree_search as tree_search_module` at line 28, and `pipeline/tree_search.py` is Plan 14-04's deliverable (confirmed via `14-04-PLAN.md` frontmatter: `depends_on: ["14-03"]`, wave 3 vs. this plan's wave 2). Running the command today produces a `ModuleNotFoundError` collection error for the whole file — this matches the Phase-13 precedent explicitly documented in `14-RESEARCH.md`'s Validation Architecture section: *"RED-state expectation matches Phase 13: tests fail with ImportError until the implementation ships — correct Nyquist scaffold."*

To verify `PageIndexRetriever`'s actual behavior against the exact same fixtures and assertions used by `TestHeuristicRetriever`/`TestLlmNav` (hand-built 2-level `TreeIndex`, in-memory SQLite via `StaticPool`, `litellm.completion` mocked), a standalone script reproducing those test bodies verbatim (without the blocked top-level import) was run and all assertions passed:
- `test_heuristic_no_llm` equivalent: PASS (zero `litellm.completion` calls in heuristic mode, deterministic repeat-call ordering, empty-query/empty-tree guards return `[]`)
- `test_citation_source_tree` equivalent: PASS (`citation_source == "tree"` + full payload key set + non-empty `node_path`)
- `test_no_hardcoded_provider_model_ids` equivalent: PASS (no `anthropic/`/`claude-`/`gpt-`/`bedrock/`/`amazon.titan`/`text-embedding-` fragments; `openai/` present)
- `test_llm_nav_degrades` equivalent: PASS (budget-at-cap degrade with zero `litellm.completion` calls; exception-path degrade with identical Hit ordering to the heuristic result)

This will resolve automatically once Plan 14-04 creates `pipeline/tree_search.py` — at that point `tests/unit/test_tree_search.py` will collect successfully and the exact commands in this plan's `<verify>`/`<verification>` blocks will pass unmodified. No code change to `pageindex_retriever.py` is needed or was made to work around this; creating `pipeline/tree_search.py` here would duplicate Plan 14-04's scope (Rule 4 architectural boundary — the two-stage orchestrator is a separate, larger deliverable that this plan's `files_modified` list explicitly excludes).

Task 2's verify command (`uv pip install -e . -q && pytest tests/unit/test_builtin_plugins.py::TestPageIndexRetriever -q`) has no such dependency and ran successfully as specified: entry-point registration confirmed, `isinstance(PageIndexRetriever(), RetrieverPlugin)` confirmed, `get_retriever(Settings()).name == "pageindex"` confirmed, `LookupError` on an unknown retriever name confirmed.

Full regression check: `uv run pytest tests/unit -q --ignore=tests/unit/test_tree_search.py` → 569 passed, 1 xfailed, 39 xpassed (matches the pre-existing baseline in STATE.md/PROJECT.md; no regressions introduced).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `get_retriever(settings)` and `PageIndexRetriever` are ready for Plan 14-04's `pipeline/tree_search.py` two-stage orchestrator to call `.search(tree_index, query, top_k=..., mode=..., settings=...)` per shortlisted document tree.
- Once 14-04 lands, `tests/unit/test_tree_search.py` will collect successfully; no further changes to this plan's files are anticipated to make those existing tests pass (verified via the equivalent standalone script above).
- Blocker carried forward (unchanged from STATE.md): tree traversal / LLM-nav prompt quality remains unvalidated against a healthcare ground-truth benchmark — noted for future tuning, out of this plan's scope.

---
*Phase: 14-tree-retrieval*
*Completed: 2026-07-14*
