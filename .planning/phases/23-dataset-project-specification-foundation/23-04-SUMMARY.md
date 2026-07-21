---
phase: 23-dataset-project-specification-foundation
plan: 04
subsystem: pipeline
tags: [export, dataset-project, versioning, identity-resolution, tdd]

# Dependency graph
requires:
  - phase: 23-02
    provides: "pipeline.project.create_project()/transition_project()/DatasetProject.status 11-state lifecycle"
  - phase: 23-03
    provides: "pipeline.project.create_spec_version() — used only to exercise the real 2-spec-version lifecycle in this plan's integration test, never read by get_latest_released_dataset_by_name() itself"
provides:
  - "registry.repo.get_latest_released_dataset_by_name() — the D-02 export-identity-ambiguity resolution rule"
  - "export_finetune_dataset() internally resolved via get_latest_released_dataset_by_name(), zero call-site changes at CLI/API/MCP/Dagster"
affects: [23-05, 23-06, 23-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "get_latest_released_dataset_by_name() sits alongside get_dataset_by_name() (never modifies it) — legacy path (dataset_project_id IS NULL) falls back byte-identically; project-scoped path re-queries by dataset_project_id + DatasetProject.status == 'released' only, NOT re-filtered by name"

key-files:
  created:
    - tests/integration/test_export_project_resolution.py
  modified:
    - src/knowledge_lake/registry/repo.py
    - src/knowledge_lake/pipeline/export.py
    - tests/unit/test_export.py

key-decisions:
  - "Task 1 (implementation + integration test) committed before Task 2 (unit-suite legacy-fallback regression test), mirroring the same feat-before-test task-boundary precedent established in 23-02-SUMMARY.md/23-03-SUMMARY.md"
  - "Integration test's two Dataset rows use DISTINCT names (dataset_name / dataset_name_v2), not the plan's literal 'same name' instruction — datasets.name carries a real uq_datasets_name UNIQUE constraint (migration 0008) that makes two same-named rows impossible. This does not weaken what's proven: per the plan's own <action> spec, get_latest_released_dataset_by_name()'s second query resolves purely on Dataset.dataset_project_id (not name again) once the by-name lookup identifies the project, so querying by the EARLIER row's name still correctly resolves to the LATER row for the same project."

requirements-completed: [SPEC-02, PROJ-02]

coverage:
  - id: D1
    description: "get_latest_released_dataset_by_name() resolves a Dataset row FK'd to a released Dataset Project via DatasetProject.status alone (never DatasetSpec.status, which does not exist), ordered created_at DESC / id DESC"
    requirement: "SPEC-02"
    verification:
      - kind: integration
        ref: "tests/integration/test_export_project_resolution.py::TestLatestReleasedDatasetResolution::test_latest_released_resolution"
        status: pass
    human_judgment: false
  - id: D2
    description: "A Dataset Project whose status has not yet reached 'released' yields None from get_latest_released_dataset_by_name(), even though a Dataset row physically exists and is FK'd to the project"
    requirement: "PROJ-02"
    verification:
      - kind: integration
        ref: "tests/integration/test_export_project_resolution.py::TestLatestReleasedDatasetResolution::test_pre_release_project_yields_no_released_dataset"
        status: pass
    human_judgment: false
  - id: D3
    description: "get_latest_released_dataset_by_name() falls back byte-identically to get_dataset_by_name() for a pre-v2.7 legacy Dataset (dataset_project_id IS NULL) — zero regression across the full existing tests/unit/test_export.py suite"
    requirement: "SPEC-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_export.py::TestFinetune::test_export_finetune_legacy_dataset_resolution_unchanged"
        status: pass
      - kind: unit
        ref: "uv run pytest tests/unit/test_export.py -x (23 passed)"
        status: pass
    human_judgment: false
  - id: D4
    description: "export_finetune_dataset()'s internal resolution swap is the ONLY code change required for D-02 — all four existing call sites (CLI, API, agent/registry MCP shim, Dagster asset) remain byte-identical"
    requirement: "SPEC-02"
    verification:
      - kind: other
        ref: "git diff --stat HEAD -- src/knowledge_lake/cli/app.py src/knowledge_lake/api/app.py src/knowledge_lake/agent/registry.py src/knowledge_lake/dagster_defs/assets.py src/knowledge_lake/dagster_defs/definitions.py (empty output)"
        status: pass
    human_judgment: false

duration: ~10min
completed: 2026-07-21
status: complete
---

# Phase 23 Plan 04: Export Identity Resolution (D-02) Summary

**`registry.repo.get_latest_released_dataset_by_name()` closes the `Dataset.name`/`export_finetune_dataset()` versioning-identity ambiguity (Pitfall 2) by joining on `DatasetProject.status == "released"` alone — a one-line internal swap inside `export_finetune_dataset()` propagates the fix to all four existing call sites (CLI/API/MCP/Dagster) with zero signature changes**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-07-21
- **Tasks:** 2
- **Files modified:** 3 (+1 new)

## Accomplishments

- `get_latest_released_dataset_by_name(session, name)` added to `registry/repo.py` immediately after `get_dataset_by_name()` (which it never modifies): for a legacy Dataset with `dataset_project_id IS NULL`, falls back byte-identically to `get_dataset_by_name()`'s exact behavior; otherwise joins `Dataset -> DatasetProject` on `dataset_project_id`, filters `DatasetProject.status == "released"` (never any `DatasetSpec` field — that table carries no status column, Plan 23-01's single-source-of-truth decision), orders `Dataset.created_at DESC, Dataset.id DESC` as an explicit deterministic tiebreak
- `pipeline/export.py`'s `export_finetune_dataset()` changed exactly one line — `get_dataset_by_name` → `get_latest_released_dataset_by_name` — plus a one-line comment citing D-02/Pitfall 2. Confirmed via `git diff --stat`: zero diff in `cli/app.py`, `api/app.py`, `agent/registry.py`, `dagster_defs/assets.py`, `dagster_defs/definitions.py` — all four existing call sites route through the new resolution automatically with no code changes
- `tests/integration/test_export_project_resolution.py` created (new file, `pytestmark = pytest.mark.integration`, mirrors `test_dedup_cli_dagster_parity.py`'s real-Postgres-stack + `uuid4()`-suffixed-naming + best-effort-teardown conventions): proves the 2-spec-version, released-project resolution rule end-to-end (`test_latest_released_resolution`) and the pre-release no-op case (`test_pre_release_project_yields_no_released_dataset`) — both pass against the live dev Postgres stack
- `tests/unit/test_export.py`'s `TestFinetune` class gained `test_export_finetune_legacy_dataset_resolution_unchanged`, explicitly asserting the resolved row's `dataset_project_id is None` to prove the legacy-fallback branch (not the project-scoped branch) is what ran — full 23-test file passes unmodified alongside it
- Full unit suite (`uv run pytest tests/unit -x -q`): 998 passed, 1 xfailed, zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: get_latest_released_dataset_by_name() + export_finetune_dataset() internal swap** - `1e1ff8e` (feat)
2. **Task 2: Legacy-path regression proof in the existing unit suite** - `d980880` (test)

**Plan metadata:** committed via final commit step (see completion output)

## Files Created/Modified

- `src/knowledge_lake/registry/repo.py` - Added `get_latest_released_dataset_by_name()` immediately after `get_dataset_by_name()`; updated module docstring's function list
- `src/knowledge_lake/pipeline/export.py` - `export_finetune_dataset()`'s single internal resolution-call swap (line 585 → `get_latest_released_dataset_by_name`), plus a D-02-citing comment
- `tests/integration/test_export_project_resolution.py` - New file: `TestLatestReleasedDatasetResolution` (2 tests, live-Postgres-gated)
- `tests/unit/test_export.py` - `TestFinetune` gained one new legacy-fallback regression test

## Decisions Made

- Task 1 (implementation + integration test) committed before Task 2 (unit-suite regression test), mirroring the exact `feat`-before-`test` task-boundary precedent set by `23-02-SUMMARY.md`/`23-03-SUMMARY.md`. Task 1's implementation was hand-verified against the live Postgres stack (both new integration tests passing) before commit — not a stale/no-op test suite.
- The integration test's two Dataset rows use distinct names (`dataset_name` and `dataset_name_v2`) instead of the plan's literal "same name" instruction, because `datasets.name` carries a real `uq_datasets_name` UNIQUE constraint (migration 0008) that makes two identically-named rows impossible to insert. This is a Rule-1 auto-fix of an infeasible test instruction, not a weakening of the proof: per the plan's own `<action>` text, `get_latest_released_dataset_by_name()`'s second query resolves purely on `Dataset.dataset_project_id` (not `name` again) once the initial by-name lookup has identified the project — so querying with the EARLIER row's name still correctly resolves to the LATER row for the same project, proving the exact "latest wins" rule the plan specifies.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Integration test's "same name for both Dataset rows" instruction is infeasible against the real schema**
- **Found during:** Task 1 (writing `tests/integration/test_export_project_resolution.py`)
- **Issue:** The plan's `<action>` text instructs setting both seeded Dataset rows to the identical `name` value. `datasets.name` has a `uq_datasets_name` UNIQUE constraint (pre-existing, migration 0008) — the second insert fails with `IntegrityError: duplicate key value violates unique constraint "uq_datasets_name"`.
- **Fix:** Gave the two rows distinct names (`dataset_name`, `dataset_name + "_v2"`), and query `get_latest_released_dataset_by_name()` using the EARLIER row's name. Since the function's own specified second-query logic filters strictly on `Dataset.dataset_project_id` (not `name`) once the project is identified, this still exercises and proves the exact "latest wins" behavior the plan's `must_haves.truths` describe.
- **Files modified:** `tests/integration/test_export_project_resolution.py`
- **Verification:** Both integration tests pass against the live dev Postgres stack (`uv run pytest tests/integration/test_export_project_resolution.py -x -m integration` → 2 passed)
- **Committed in:** `1e1ff8e` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — plan instruction incompatible with a pre-existing DB constraint)
**Impact on plan:** No scope creep; the deviation is a mechanical test-authoring adjustment required by a real schema constraint the plan's test-authorship text didn't account for. The behavior proven is identical to what the plan specifies.

## Issues Encountered

None beyond the one documented deviation above. No auth gates, no architectural decisions required.

## User Setup Required

None - no external service configuration required. The new integration test requires the live dev Postgres stack (already running via `docker compose`); no new services or credentials introduced.

## Next Phase Readiness

- `export_finetune_dataset()` now resolves the correct, released-state Dataset for any project-scoped name across all four surfaces (CLI, API, agent/registry MCP shim, Dagster asset) with zero call-site changes — Plan 23-05 (API routes) and Plan 23-06 (CLI commands) can build project/spec-management surfaces on top without touching export resolution again
- `get_latest_released_dataset_by_name()` is the last piece of D-02's identity-ambiguity fix (RESEARCH.md Pattern 5 / PITFALLS.md Pitfall 2) — the standing gotcha entry in `STATE.md`'s "Blockers/Concerns" section about `Dataset.name`/`export_finetune_dataset()` versioning ambiguity is now resolved and can be removed from the carried-forward list
- No blockers. Full unit suite (998 passed, 1 xfailed) and both new integration tests pass with zero regressions

---
*Phase: 23-dataset-project-specification-foundation*
*Completed: 2026-07-21*

## Self-Check: PASSED

- FOUND: tests/integration/test_export_project_resolution.py
- FOUND: get_latest_released_dataset_by_name in src/knowledge_lake/registry/repo.py
- FOUND: internal swap in src/knowledge_lake/pipeline/export.py
- FOUND commit: 1e1ff8e
- FOUND commit: d980880
