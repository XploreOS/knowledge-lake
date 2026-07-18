---
phase: 21-index-time-dedup
plan: 07
subsystem: dagster
tags: [dagster, dedup, asset-ordering, kl-06-regression-guard]

# Dependency graph
requires:
  - phase: 21-index-time-dedup (Plan 04)
    provides: pipeline.dedup.dedup_chunks(chunks, parsed_artifact_id, source_id, *, collection, settings) -> dict
  - phase: 21-index-time-dedup (Plan 05)
    provides: index()'s duplicate_chunks kwarg
provides:
  - "dedup_chunks Dagster asset between chunk_document and embed_chunks"
  - "embed_chunks/index_chunks rewired to consume dedup_chunks' output; core_pipeline_e2e_job selection updated"
affects: [21-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "New asset's parameter renamed to match upstream asset function name (Dagster's own wiring mechanism) — embed_chunks' parameter chunk_document -> dedup_chunks IS the new dependency edge, matching this file's existing chunk_document(clean_document)/index_chunks(embed_chunks) convention"
    - "Output-dict field forwarding (duplicates) avoids adding a second Dagster parameter to index_chunks, keeping its sole data input as embed_chunks"

key-files:
  created: []
  modified:
    - src/knowledge_lake/dagster_defs/assets.py
    - src/knowledge_lake/dagster_defs/definitions.py
    - tests/unit/test_asset_ordering.py

key-decisions:
  - "definitions.py (not in the plan's files_modified list) was added/registered with the new dedup_chunks asset — without this, Dagster's Definitions object fails to load with DagsterInvalidDefinitionError since assets.py alone does not register a new asset with the code location (Rule 3 blocking fix)"
  - "dedup_chunks asset positioned physically between tree_index_document and embed_chunks in assets.py (not immediately after chunk_document) to minimize diff churn around enrich_document/tree_index_document, while still satisfying the plan's 'between chunk_document and embed_chunks' asset-graph requirement (dependency-edge position, not file position, is what Dagster enforces)"

requirements-completed: [DEDUP-01]

coverage:
  - id: D1
    description: "dedup_chunks asset exists, calls pipeline.dedup.dedup_chunks, and sits in the asset graph between chunk_document and embed_chunks"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "python -c \"from knowledge_lake.dagster_defs.definitions import defs; defs.resolve_job_def('core_pipeline_e2e_job')\" — OK"
        status: pass
    human_judgment: false
  - id: D2
    description: "embed_chunks' parameter renamed chunk_document -> dedup_chunks; reads chunks from dedup_chunks['new'], forwards duplicates"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "grep confirms no remaining chunk_document reference in embed_chunks; full unit suite green"
        status: pass
    human_judgment: false
  - id: D3
    description: "index_chunks reads duplicate_chunks from embed_chunks['duplicates'] and passes duplicate_chunks=... into pipeline.index.index()"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_asset_ordering.py::TestCorePipelineE2eJobSelectionPreservesOrdering::test_embed_chunks_ordering_edge_survives_inside_the_job"
        status: pass
    human_judgment: false
  - id: D4
    description: "core_pipeline_e2e_job's AssetSelection.assets(...) includes dedup_chunks between chunk_document and embed_chunks (Pitfall 1 guard)"
    requirement: "DEDUP-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_asset_ordering.py::TestCorePipelineE2eJobSelectionPreservesOrdering::test_job_selection_contains_dedup_chunks"
        status: pass
      - kind: unit
        ref: "tests/unit/test_asset_ordering.py::TestCorePipelineE2eJobSelectionPreservesOrdering::test_dedup_chunks_is_ancestor_and_executable_for_index_chunks"
        status: pass
    human_judgment: false
  - id: D5
    description: "Guard is non-vacuous — manually removing dedup_chunks from the selection tuple fails at least one of the three new tests"
    requirement: "DEDUP-01"
    verification:
      - kind: manual
        ref: "Manual sanity check: sed-removed the dedup_chunks entry from the selection tuple, ran the suite, confirmed 2 of the 3 new tests failed with the expected assertion messages, then restored the file via git checkout"
        status: pass
    human_judgment: true

# Metrics
duration: 7min
completed: 2026-07-17
status: complete
---

# Phase 21 Plan 07: dedup_chunks Dagster Asset + Call-Site Wiring Summary

**New `dedup_chunks` Dagster asset added between `chunk_document` and `embed_chunks`, calling `pipeline.dedup.dedup_chunks` unchanged; `embed_chunks`/`index_chunks` rewired to consume its `new`/`duplicates` output; `core_pipeline_e2e_job`'s selection extended with a Pitfall-1 (KL-06-shaped) regression guard proven non-vacuous.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-07-17T13:28:47Z
- **Completed:** 2026-07-17T13:35:00Z
- **Tasks:** 2 completed
- **Files modified:** 3 (all modified, no new files)

## Accomplishments
- `dedup_chunks` asset added to `assets.py`, positioned in the asset graph between `chunk_document` and `embed_chunks`; calls `pipeline.dedup.dedup_chunks()` unchanged, mirroring the file's `_env_file=None` Settings-construction idiom and the `enrich_fn`-style aliased import convention
- `embed_chunks`' parameter renamed `chunk_document` -> `dedup_chunks` (Dagster's parameter-name-to-upstream-function-name wiring mechanism — this rename IS the new dependency edge); reads `chunks = dedup_chunks["new"]` and forwards `duplicates` in its own output dict
- `index_chunks` reads `duplicate_chunks = embed_chunks["duplicates"]` and passes `duplicate_chunks=duplicate_chunks` into `pipeline.index.index()`
- `core_pipeline_e2e_job`'s `AssetSelection.assets(...)` tuple extended with `dedup_chunks` between `chunk_document` and `embed_chunks`, with an explanatory comment mirroring the job's existing KL-06 comment style
- `tests/unit/test_asset_ordering.py`'s `TestCorePipelineE2eJobSelectionPreservesOrdering` gained 3 new tests proving `dedup_chunks` is present, executable, and correctly ordered within the job — manually verified non-vacuous by temporarily removing it from the selection and confirming 2 of the 3 new tests fail
- Full unit suite (962 passed, 1 xfailed) green after all changes; `ruff check` and `mypy` clean on every modified file

## Task Commits

1. **Task 1: New dedup_chunks asset + embed_chunks/index_chunks rewiring + job selection update** - `8a1a204` (feat)
2. **Task 2 (tdd=true): Extend test_asset_ordering.py with the dedup_chunks selection-membership guard** - `b341dba` (test)

**Plan metadata:** (this commit)

## Files Created/Modified
- `src/knowledge_lake/dagster_defs/assets.py` — new `dedup_chunks` asset; `embed_chunks` parameter renamed and rewired; `index_chunks` passes `duplicate_chunks=...`; `core_pipeline_e2e_job` selection extended; module docstring/job description updated to reflect the new chain
- `src/knowledge_lake/dagster_defs/definitions.py` — imports and registers the new `dedup_chunks` asset in `Definitions(assets=[...])` (required for the code location to load — see Deviations)
- `tests/unit/test_asset_ordering.py` — 3 new tests in `TestCorePipelineE2eJobSelectionPreservesOrdering`: `test_job_selection_contains_dedup_chunks`, `test_dedup_chunks_is_ancestor_and_executable_for_index_chunks`, `test_embed_chunks_ordering_edge_survives_inside_the_job`

## Decisions Made
- `dedup_chunks` was placed physically between `tree_index_document` and `embed_chunks` in the file (rather than immediately after `chunk_document`) to avoid churning the diff around `enrich_document`/`tree_index_document`. Dagster resolves the asset graph by parameter-name-to-function-name matching, not source-file order, so this has no effect on the dependency edge the plan requires (`dedup_chunks` sits between `chunk_document` and `embed_chunks` in the *graph*, which is what all four `must_haves.truths` and the tests actually verify).
- `definitions.py` was modified even though it was not listed in the plan's `files_modified` — see Deviations below.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Registered the new `dedup_chunks` asset in `definitions.py`**
- **Found during:** Task 1 acceptance-criteria verification (`python -c "from knowledge_lake.dagster_defs.definitions import defs; ..."`)
- **Issue:** The plan's `files_modified` list only names `assets.py` and `test_asset_ordering.py`. Defining a new `@asset`-decorated function in `assets.py` does not automatically register it with the Dagster code location — `definitions.py`'s `Definitions(assets=[...])` list must import and include it explicitly, or `AssetGraph.from_assets()` raises `DagsterInvalidDefinitionError: Input asset "['dedup_chunks']" is not produced by any of the provided asset ops` the moment any other asset (`embed_chunks`) declares a data dependency on it.
- **Fix:** Added `dedup_chunks` to `definitions.py`'s import list and to `Definitions(assets=[...])`, positioned between `generate_dataset` and `embed_chunks`; also updated the module docstring's asset-chain comment for accuracy.
- **Files modified:** src/knowledge_lake/dagster_defs/definitions.py
- **Verification:** `python -c "from knowledge_lake.dagster_defs.definitions import defs; print('loads')"` — loads; `defs.resolve_job_def('core_pipeline_e2e_job')` — OK.
- **Committed in:** 8a1a204 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking fix, required for the plan's own acceptance criteria to pass)
**Impact on plan:** Purely additive registration; no behavior change beyond what the plan specified. No scope creep.

## Issues Encountered

None beyond the one auto-fixed blocking issue described above.

## User Setup Required

None — no external service configuration required. Note: per the project's standing gotcha, a live Dagster daemon/webserver container will need a code-location reload to pick up this new asset (not required for this plan's own verification, which runs against the module directly).

## Deferred / Out-of-scope note

`tests/unit/test_dagster_retry_policies.py`'s `_get_pipeline_assets()` list (9 assets) was not extended to include `dedup_chunks`. This is out of scope for this plan (not in `files_modified`, and the existing test still passes — it only asserts retry_policy on the assets it already names, it does not assert completeness of the pipeline-asset roster). `dedup_chunks` does carry `retry_policy=_PIPELINE_RETRY` (mirroring every other pipeline asset in the file), so the actual RetryPolicy coverage is correct; only the *test's* asset enumeration is now one asset short of the full pipeline. Logged here rather than fixed, per the scope-boundary rule.

## Next Phase Readiness

- Dagster-orchestrated `core_pipeline_e2e_job` now dedupes chunk text at index time, matching Plan 21-06's CLI/API/MCP path behavior — DEDUP-01's second (and final) required call site is wired
- Full unit test suite (962 passed, 1 xfailed) green after this plan's changes — no regressions
- No blockers identified

---
*Phase: 21-index-time-dedup*
*Completed: 2026-07-17*

## Self-Check: PASSED

All modified files confirmed present on disk; both commit hashes (8a1a204, b341dba) confirmed present in git log.
