---
phase: 13-tree-index-foundation
plan: "05"
subsystem: plugins
tags: [tree-index, plugin-builtin, entry-point, resolver, indexer-plugin, tdd-green, asvs-v5]

# Dependency graph
requires:
  - 13-02 (protocols.py — IndexerPlugin @runtime_checkable Protocol)
  - 13-04 (pipeline/tree_index.py — _build_deterministic_tree reused by build_index)
provides:
  - src/knowledge_lake/plugins/builtin/pageindex_indexer.py — PageIndexIndexer class
  - knowledge_lake.plugins.resolver.GROUP_INDEXERS constant
  - knowledge_lake.plugins.resolver.get_indexer(settings) function
  - pyproject.toml [project.entry-points."knowledge_lake.indexers"] group with pageindex entry
affects:
  - 13-06 (Dagster asset — can now call get_indexer(settings) via resolver)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Entry-point plugin registration — pageindex registered under knowledge_lake.indexers group; mirrors knowledge_lake.vectorstores pattern exactly
    - Deferred import — _build_deterministic_tree imported inside build_index() to avoid circular-import at class-definition time (mirrors st_embedder.py lazy litellm import)
    - Constructor injection — litellm_url/api_key injected from Settings; no os.environ reads in builtin (CR-03)
    - get_indexer mirrors get_vectorstore — _resolve_with_kwargs with litellm kwargs for pageindex, empty kwargs for others

key-files:
  created:
    - src/knowledge_lake/plugins/builtin/pageindex_indexer.py
  modified:
    - src/knowledge_lake/plugins/resolver.py
    - src/knowledge_lake/plugins/builtin/__init__.py
    - pyproject.toml

key-decisions:
  - "PageIndexIndexer.build_index delegates to _build_deterministic_tree from pipeline/tree_index.py — no duplicate nesting algorithm, no re-parse"
  - "pageindex==0.3.0.dev3 NOT imported — [SUS] pre-release deferred per RESEARCH.md Open Question 1"
  - "get_indexer injects litellm_url/api_key only when name=='pageindex'; other names get empty kwargs (extensibility for future plugins)"
  - "editable reinstall required after pyproject.toml entry-point addition — run once per environment"

requirements-completed:
  - TREE-01
  - TREE-04
  - TREE-05

# Metrics
duration: 4min
completed: 2026-07-13
status: complete
---

# Phase 13 Plan 05: PageIndexIndexer Builtin + Resolver + Entry-Point Registration Summary

**PageIndexIndexer builtin satisfying IndexerPlugin Protocol via deterministic section-tree construction — get_indexer(settings) resolver wired, knowledge_lake.indexers entry-point group registered**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-07-13T14:13:17Z
- **Completed:** 2026-07-13T14:16:56Z
- **Tasks:** 1 of 1
- **Files created:** 1 (`src/knowledge_lake/plugins/builtin/pageindex_indexer.py`)
- **Files modified:** 3 (`resolver.py`, `builtin/__init__.py`, `pyproject.toml`)
- **Commit:** e11a4c8

## Accomplishments

- Created `src/knowledge_lake/plugins/builtin/pageindex_indexer.py` — `PageIndexIndexer` class with:
  - `name: str = "pageindex"` class attribute
  - `__init__(litellm_url, litellm_api_key)` injected via constructor (CR-03, no os.environ)
  - `build_index(parsed_doc, *, mode, metadata)` delegates to `_build_deterministic_tree` from `pipeline/tree_index.py` via deferred import
  - Returns `TreeIndex(parsed_artifact_id, source_id, roots, mode, schema_version="1", content_hash="")`
  - Zero imports of `pageindex`, `PyPDF2`, or `pymupdf` (RESEARCH.md Open Question 1 deferred)
- Added `GROUP_INDEXERS = "knowledge_lake.indexers"` constant to `resolver.py`
- Added `get_indexer(settings)` function to `resolver.py` — mirrors `get_vectorstore` pattern; uses `_resolve_with_kwargs` with litellm URL injection for pageindex
- Updated `builtin/__init__.py` docstring to include `knowledge_lake.indexers — pageindex` group line
- Registered `[project.entry-points."knowledge_lake.indexers"]` with `pageindex = "knowledge_lake.plugins.builtin.pageindex_indexer:PageIndexIndexer"` in `pyproject.toml`
- Ran `uv pip install -e .` to activate entry-point group — `importlib.metadata.entry_points(group='knowledge_lake.indexers')` returns `{'pageindex'}`
- Both RED-state conformance tests from Plan 13-01 turned GREEN: `test_pageindex_indexer_entry_point_registered` and `test_pageindex_indexer_satisfies_protocol`

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| T1 | Create PageIndexIndexer builtin + resolver + pyproject.toml | e11a4c8 | pageindex_indexer.py, resolver.py, builtin/__init__.py, pyproject.toml |

## Verification

```
uv run python -c "from knowledge_lake.plugins.builtin.pageindex_indexer import PageIndexIndexer; from knowledge_lake.plugins.protocols import IndexerPlugin; p = PageIndexIndexer(); assert isinstance(p, IndexerPlugin); assert p.name == 'pageindex'; print('OK')"
→ OK

uv run python -c "import importlib.metadata; eps = importlib.metadata.entry_points(group='knowledge_lake.indexers'); names = {e.name for e in eps}; assert 'pageindex' in names; print('Entry-point registered:', names)"
→ Entry-point registered: {'pageindex'}

uv run python -c "from knowledge_lake.plugins.resolver import GROUP_INDEXERS, get_indexer; from knowledge_lake.config.settings import Settings; s = Settings(_env_file=None); idx = get_indexer(s); print(type(idx).__name__)"
→ PageIndexIndexer

uv run pytest tests/unit/test_builtin_plugins.py::TestIndexerPluginBuiltin -x -v → 2 passed
uv run pytest tests/unit/ --ignore=tests/unit/test_tree_index_asset.py -q → 565 passed, 1 xfailed, 39 xpassed (no regressions)
```

Note: `tests/unit/test_tree_index_asset.py` errors at import collection (not a regression — it requires `tree_index_document` from Plan 13-06 which is the next plan). This was the pre-existing RED state from Plan 13-01.

## Deviations from Plan

None — plan executed exactly as written.

The acceptance criterion `grep -c 'knowledge_lake.indexers' pyproject.toml returns 2` is a minor spec discrepancy: only 1 line contains the literal string `knowledge_lake.indexers` (the section header). The `pageindex = "...pageindex_indexer:PageIndexIndexer"` entry does not repeat the group name inline — this is correct TOML syntax. The functional requirement is fully met: entry-point discovery returns `{'pageindex'}`.

## Known Stubs

None — `build_index()` is fully wired to `_build_deterministic_tree` from Plan 13-04. No placeholder values flow to callers.

## Threat Surface Scan

| Mitigation | Implementation |
|-----------|---------------|
| T-13-11 (entry-point swap-key injection) | `settings.indexer` passes `_validate_swap_key` ASVS V5 field_validator (added Plan 13-02 T3) before reaching `get_indexer → _resolve_with_kwargs` |
| T-13-12 ([SUS] pageindex package) | `pageindex==0.3.0.dev3` not imported; no `pip install pageindex/PyPDF2/pymupdf` in this plan |
| T-13-SC (no new packages) | Only editable reinstall of existing package; zero new dependencies added |

## Self-Check: PASSED

- `src/knowledge_lake/plugins/builtin/pageindex_indexer.py` — FOUND: created at correct path
- `GROUP_INDEXERS` in `resolver.py` — FOUND: line 43
- `get_indexer` in `resolver.py` — FOUND: line 335
- `knowledge_lake.indexers` in `builtin/__init__.py` — FOUND: docstring line 11
- `[project.entry-points."knowledge_lake.indexers"]` in `pyproject.toml` — FOUND: line 110
- Commit e11a4c8 — FOUND in git log
- `isinstance(PageIndexIndexer(), IndexerPlugin)` → True
- 2 TestIndexerPluginBuiltin tests — PASSED GREEN
- 565 unit tests (excluding test_tree_index_asset.py pre-existing collection error) — PASSED, no regressions
- No `import pageindex`, `import PyPDF2`, `import pymupdf` in pageindex_indexer.py — CONFIRMED

---
*Phase: 13-tree-index-foundation*
*Completed: 2026-07-13*
