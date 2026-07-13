---
phase: 13-tree-index-foundation
plan: "02"
subsystem: config
tags: [tree-index, protocols, settings, ids, dataclass, pydantic, plugin-protocol, wave-1-enabling-edits]

# Dependency graph
requires:
  - phase: 13-01
    provides: Wave 0 test scaffold (test_tree_index.py, test_tree_index_asset.py, test_builtin_plugins.py stubs) — these tests go from ImportError to assertion failures after this plan
provides:
  - ids._PREFIX["tree_index"] = "idx" — new_id("tree_index") returns idx_<uuidv7> without ValueError
  - protocols.TreeNode dataclass (8 fields) — schema contract for tree nodes per D-01/D-02
  - protocols.TreeIndex dataclass (6 fields) — artifact wrapper per D-02
  - protocols.IndexerPlugin @runtime_checkable Protocol — swap seam per D-05/FOUND-08
  - settings.TreeSettings BaseModel (6 fields) — tree-index config with Literal mode, budget, model_alias
  - Settings.tree: TreeSettings field — wired via env_nested_delimiter KLAKE_TREE__*
  - Settings.indexer: str = "pageindex" — swap key validated by ASVS V5 _validate_swap_key
affects:
  - 13-03 (repo.py — create_tree_index_artifact calls new_id("tree_index"))
  - 13-04 (pipeline/tree_index.py — imports TreeNode, TreeIndex, TreeSettings, get_settings)
  - 13-05 (pageindex_indexer.py — implements IndexerPlugin Protocol)
  - 13-06 (assets.py — uses Settings.tree and Settings.indexer)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Wave-1 enabling-edits pattern — three minimal targeted changes to existing files before any business logic
    - TreeNode.level and page_end are DERIVED by builder (Section has no level/page_end per Finding 1)
    - node_id derived from section_path (stable — never uuid/clock, Pitfall 3)
    - IndexerPlugin mirrors EmbedderPlugin shape (@runtime_checkable, name:str, method with ...)
    - TreeSettings mirrors EnrichSettings (budget_usd=5.0, model_alias="cheap_model", never a provider ID)
    - _validate_swap_key extended with "indexer" for ASVS V5 entry-point load security

key-files:
  created: []
  modified:
    - src/knowledge_lake/ids.py
    - src/knowledge_lake/plugins/protocols.py
    - src/knowledge_lake/config/settings.py

key-decisions:
  - "TreeNode.level and page_end are DERIVED by the builder — Section has no level or page_end (Finding 1 in 13-RESEARCH.md)"
  - "node_id derived from section_path for stability — never uuid/clock/randomness (Pitfall 3)"
  - "TreeIndex.mode defaults to 'deterministic' not 'llm' — deterministic-first per D-08"
  - "indexer added to _validate_swap_key ASVS V5 regex to prevent malicious entry-point names (T-13-03)"
  - "No Alembic migration added — artifact_type is free-form String (per plan prohibition)"

patterns-established:
  - "Enabling-edits wave: add minimal contract definitions (ids + protocols + settings) BEFORE any implementation wave"
  - "TreeSettings model pattern: same 6-field shape as EnrichSettings (budget_usd, model_alias=cheap_model, mode Literal, schema_version, prompt_version, max_tokens)"

requirements-completed:
  - TREE-01
  - TREE-02
  - TREE-03
  - TREE-04
  - TREE-05

coverage:
  - id: D1
    description: "new_id('tree_index') returns idx_-prefixed string without ValueError (ids._PREFIX['tree_index']='idx')"
    requirement: TREE-02
    verification:
      - kind: unit
        ref: "python -c \"from knowledge_lake.ids import new_id; v = new_id('tree_index'); assert v.startswith('idx_')\""
        status: pass
    human_judgment: false
  - id: D2
    description: "TreeNode dataclass (8 fields) and TreeIndex dataclass (6 fields) importable from protocols.py"
    requirement: TREE-01
    verification:
      - kind: unit
        ref: "python -c \"from knowledge_lake.plugins.protocols import TreeNode, TreeIndex; from dataclasses import fields; assert len(fields(TreeNode))==8 and len(fields(TreeIndex))==6\""
        status: pass
    human_judgment: false
  - id: D3
    description: "IndexerPlugin @runtime_checkable Protocol importable from protocols.py with build_index method"
    requirement: TREE-05
    verification:
      - kind: unit
        ref: "python -c \"from knowledge_lake.plugins.protocols import IndexerPlugin; isinstance(object(), IndexerPlugin)\""
        status: pass
    human_judgment: false
  - id: D4
    description: "TreeSettings BaseModel (6 fields) with deterministic default mode and cheap_model alias"
    requirement: TREE-01
    verification:
      - kind: unit
        ref: "python -c \"from knowledge_lake.config.settings import TreeSettings; t = TreeSettings(); assert t.mode=='deterministic' and t.model_alias=='cheap_model'\""
        status: pass
    human_judgment: false
  - id: D5
    description: "Settings.tree: TreeSettings and Settings.indexer='pageindex' with ASVS V5 swap-key validation"
    requirement: TREE-01
    verification:
      - kind: unit
        ref: "python -c \"from knowledge_lake.config.settings import Settings; s = Settings(_env_file=None); assert s.tree.mode=='deterministic' and s.indexer=='pageindex'\""
        status: pass
    human_judgment: false

# Metrics
duration: 4min
completed: 2026-07-13
status: complete
---

# Phase 13 Plan 02: Wave 1 Enabling Edits Summary

**Three minimal targeted changes — ids._PREFIX["tree_index"]="idx", TreeNode/TreeIndex/IndexerPlugin dataclasses in protocols.py, and TreeSettings+indexer in settings.py — that unblock all Wave 2 implementation tasks without adding any business logic**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-07-13T13:45:51Z
- **Completed:** 2026-07-13T13:50:08Z
- **Tasks:** 3 of 3
- **Files modified:** 3

## Accomplishments

- Added `"tree_index": "idx"` to `_PREFIX` dict in `ids.py` — `new_id("tree_index")` now returns `idx_<uuidv7>` without `ValueError`; required by `create_tree_index_artifact()` in `registry/repo.py`
- Added `TreeNode` (8 fields), `TreeIndex` (6 fields), and `IndexerPlugin` `@runtime_checkable` Protocol to `protocols.py` — shared schema contract locked per D-01/D-02 before any builder or plugin implementation
- Added `TreeSettings` BaseModel (6 fields), `tree: TreeSettings` and `indexer: str = "pageindex"` fields to `Settings`, and extended `_validate_swap_key` field_validator to include `"indexer"` (ASVS V5 security)

## Task Commits

1. **Task 1: ids.py — add "tree_index" to _PREFIX** — `b9caa57` (feat)
2. **Task 2: protocols.py — add TreeNode, TreeIndex, IndexerPlugin** — `b8e1c28` (feat)
3. **Task 3: settings.py — add TreeSettings, tree, indexer fields** — `be30ca3` (feat)

## Files Created/Modified

- `src/knowledge_lake/ids.py` — Added `"tree_index": "idx"` to `_PREFIX` dict (line 45); single-line addition after `"dataset_example": "dex"`
- `src/knowledge_lake/plugins/protocols.py` — Appended `TreeNode` dataclass (8 fields), `TreeIndex` dataclass (6 fields), and `IndexerPlugin` `@runtime_checkable` Protocol at end of file (+114 lines)
- `src/knowledge_lake/config/settings.py` — Added `TreeSettings` BaseModel class (20 lines), `tree` and `indexer` fields on `Settings`, and added `"indexer"` to `_validate_swap_key` field_validator tuple (+31 lines total)

## Decisions Made

- `TreeNode.level` and `page_end` are derived by the builder — `Section` has no `level` or `page_end` fields (Finding 1 in 13-RESEARCH.md). Documented in `TreeNode` docstring.
- `node_id` derived from `section_path` for stability — never uuid/clock/randomness per Pitfall 3
- `TreeIndex.mode` defaults to `"deterministic"` not `"llm"` — deterministic-first per D-08
- `IndexerPlugin` mirrors `EmbedderPlugin` shape exactly: `@runtime_checkable`, `name: str` class attr, method body `...`
- `"indexer"` added to `_validate_swap_key` to block malicious entry-point names reaching `importlib.metadata.entry_points` (T-13-03 mitigated)
- No Alembic migration added — `artifact_type` is free-form `String` column (plan prohibition honored)

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None. All three additions followed exact analogs from the same files (pattern map had 100% coverage). The only pre-existing test failures are the two Wave-0 RED stubs from Plan 13-01 (`test_pageindex_indexer_entry_point_registered` and `test_pageindex_indexer_satisfies_protocol`) which require `pageindex_indexer.py` from Plan 13-05 — these are expected RED state, not regressions.

## Known Stubs

None — all additions are complete contract definitions. `TreeSettings` fields have real defaults, not placeholders. `IndexerPlugin` uses `...` (ellipsis) for its method body, which is the correct Python Protocol pattern (not a stub).

## Threat Flags

None — changes are contract-only (dataclasses, settings model, validator extension). The T-13-03 threat (malicious indexer swap key) is mitigated by adding `"indexer"` to the existing `_validate_swap_key` ASVS V5 regex validator in Task 3.

## Self-Check: PASSED

- `src/knowledge_lake/ids.py` — FOUND: `"tree_index": "idx"` in `_PREFIX`
- `src/knowledge_lake/plugins/protocols.py` — FOUND: `TreeNode` (8 fields), `TreeIndex` (6 fields), `IndexerPlugin` Protocol
- `src/knowledge_lake/config/settings.py` — FOUND: `TreeSettings` class, `tree` field, `indexer` field, `"indexer"` in `_validate_swap_key`
- Commits `b9caa57`, `b8e1c28`, `be30ca3` — all confirmed in git log
- 549 pre-existing tests pass; 2 expected RED stubs from Plan 13-01 still failing (correct)

## Next Phase Readiness

- Wave 1 enabling edits complete: all Wave 2 implementation plans (`13-03` through `13-06`) can now execute
- `13-03` (repo.py): `new_id("tree_index")` works — `create_tree_index_artifact()` can be added
- `13-04` (pipeline/tree_index.py): `TreeNode`, `TreeIndex`, `TreeSettings`, `get_settings()` all importable
- `13-05` (pageindex_indexer.py): `IndexerPlugin` Protocol defined — plugin implementation can conform to it
- `13-06` (assets.py): `Settings.tree` and `Settings.indexer` exist — Dagster asset can wire them

---
*Phase: 13-tree-index-foundation*
*Completed: 2026-07-13*
