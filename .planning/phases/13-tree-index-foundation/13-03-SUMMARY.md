---
phase: 13-tree-index-foundation
plan: "03"
subsystem: registry
tags: [tree-index, repo, artifact, registry-helper, tdd, wave-1]

# Dependency graph
requires:
  - phase: 13-01
    provides: Wave 0 test scaffold (RED stubs)
  - phase: 13-02
    provides: ids._PREFIX["tree_index"]="idx" — new_id("tree_index") returns idx_<uuidv7>
provides:
  - registry.repo.create_tree_index_artifact — persist a tree_index Artifact row with D-07 lineage
  - artifact_type="tree_index", mime_type="application/json", idx_-prefixed id
affects:
  - 13-04 (pipeline/tree_index.py — calls create_tree_index_artifact to register artifact after build)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - create_tree_index_artifact mirrors create_chunk_artifact — structural clone with tree_index substituted and mime_type default changed to application/json
    - TDD RED→GREEN flow with TestTreeIndexArtifactCreate in test_registry.py
    - _make_artifact wrapper contract honored — no direct Artifact() construction
    - No Alembic migration — artifact_type is free-form String column

key-files:
  created: []
  modified:
    - src/knowledge_lake/registry/repo.py
    - tests/unit/test_registry.py

key-decisions:
  - "create_tree_index_artifact uses mime_type='application/json' default (not None like chunks) — tree indexes are JSON, not plain text"
  - "No Alembic migration added — artifact_type is free-form String (plan prohibition honored)"
  - "Follows _make_artifact wrapper contract — no direct Artifact() construction (plan key_link honored)"
  - "parent_artifact_id = parsed_document artifact ID (D-07 lineage as specified)"

patterns-established:
  - "Registry helper function pattern: create_*_artifact wrapping _make_artifact with named kind + artifact_type + mime_type default"

requirements-completed:
  - TREE-01
  - TREE-02

coverage:
  - id: D1
    description: "create_tree_index_artifact importable from knowledge_lake.registry.repo"
    requirement: TREE-01
    verification:
      - kind: unit
        ref: "from knowledge_lake.registry.repo import create_tree_index_artifact"
        status: pass
    human_judgment: false
  - id: D2
    description: "Artifact row has artifact_type='tree_index' and idx_-prefixed id (new_id('tree_index'))"
    requirement: TREE-02
    verification:
      - kind: unit
        ref: "tests/unit/test_registry.py::TestTreeIndexArtifactCreate::test_tree_index_artifact_type + test_tree_index_id_prefixed_idx"
        status: pass
    human_judgment: false
  - id: D3
    description: "parent_artifact_id passes through to Artifact row (D-07 lineage)"
    requirement: TREE-01
    verification:
      - kind: unit
        ref: "tests/unit/test_registry.py::TestTreeIndexArtifactCreate::test_tree_index_parent_is_parsed"
        status: pass
    human_judgment: false
  - id: D4
    description: "get_artifact_by_hash returns the tree_index artifact after flush (dedup works)"
    requirement: TREE-02
    verification:
      - kind: unit
        ref: "tests/unit/test_registry.py::TestTreeIndexArtifactCreate::test_tree_index_dedup_by_hash"
        status: pass
    human_judgment: false
  - id: D5
    description: "create_chunk_artifact still works — no regression"
    requirement: TREE-01
    verification:
      - kind: unit
        ref: "tests/unit/test_registry.py::TestTreeIndexArtifactCreate::test_create_chunk_artifact_still_works"
        status: pass
    human_judgment: false

# Metrics
duration: 6min
completed: 2026-07-13
status: complete
---

# Phase 13 Plan 03: Wave 1 Registry Helper (create_tree_index_artifact) Summary

**One new function appended to repo.py — create_tree_index_artifact() mirrors create_chunk_artifact() with tree_index substituted and mime_type defaulting to application/json, enabling Plan 13-04's tree builder to register artifacts without bypassing the wrapper contract**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-07-13T14:05:00Z
- **Completed:** 2026-07-13T14:11:00Z
- **Tasks:** 1 of 1 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments

- Added `TestTreeIndexArtifactCreate` (8 tests) to `test_registry.py` in RED state — all fail with `ImportError` until the implementation is added
- Added `create_tree_index_artifact()` to `src/knowledge_lake/registry/repo.py` after `create_chunk_artifact` — exact structural clone with `"chunk"` replaced by `"tree_index"` and `mime_type` default changed to `"application/json"` (tree indexes are JSON, not plain text)
- All 8 new tests pass GREEN; 557 pre-existing tests unchanged; 2 expected RED stubs from Plan 13-01 remain (for `pageindex_indexer.py` which ships in Plan 13-05)

## Task Commits

1. **Task 1 RED: add failing tests for create_tree_index_artifact** — `66a4a11` (test)
2. **Task 1 GREEN: add create_tree_index_artifact() to repo.py** — `edc323a` (feat)

## Files Created/Modified

- `src/knowledge_lake/registry/repo.py` — added `create_tree_index_artifact()` function (36 lines) after `create_chunk_artifact`; `grep -c '_make_artifact' repo.py` increased by 1 (now 9 calls)
- `tests/unit/test_registry.py` — added `TestTreeIndexArtifactCreate` class (138 lines) with 8 tests covering importability, artifact_type, parent lineage, idx_ prefix, mime_type default, storage_uri passthrough, dedup-by-hash, chunk regression

## Decisions Made

- `mime_type` defaults to `"application/json"` (not `None` like `create_chunk_artifact`) — tree indexes are always JSON; chunks are plain text
- No `page_ref` or `section_path` parameters — tree indexes reference the whole document, not individual pages/sections; matches plan spec exactly
- No Alembic migration — `artifact_type` is a free-form `String` column (plan prohibition honored)
- `parent_artifact_id` is a required keyword argument (not optional) — `tree_index` parent must always be a `parsed_document` per D-07

## Deviations from Plan

None — plan executed exactly as written. The function signature, docstring, and body match the PATTERNS.md template exactly.

## Known Stubs

None — `create_tree_index_artifact()` is a complete, working function. The 2 failing tests in `test_builtin_plugins.py` are pre-existing RED stubs from Plan 13-01 for the `pageindex_indexer.py` plugin (Plan 13-05), not stubs introduced by this plan.

## Threat Flags

None — single function addition to existing file; no new network endpoints, auth paths, or trust boundary changes. T-13-05 and T-13-06 from the plan's threat register are accepted at ASVS L1 as documented (content_hash is SHA-256 generated internally; parent_artifact_id is internal pipeline state).

## Self-Check: PASSED

- `src/knowledge_lake/registry/repo.py` — FOUND: `def create_tree_index_artifact` (grep -c returns 1)
- `tests/unit/test_registry.py` — FOUND: `TestTreeIndexArtifactCreate` class with 8 tests
- Commit `66a4a11` (RED test) — confirmed in git log
- Commit `edc323a` (GREEN implementation) — confirmed in git log
- Import test: `from knowledge_lake.registry.repo import create_chunk_artifact, create_tree_index_artifact` — passes
- 557 pre-existing tests pass; 2 expected RED stubs from Plan 13-01 remain
