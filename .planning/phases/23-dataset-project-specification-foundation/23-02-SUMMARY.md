---
phase: 23-dataset-project-specification-foundation
plan: 02
subsystem: pipeline
tags: [dataset-project, lifecycle, state-machine, tdd]

# Dependency graph
requires:
  - "dataset_projects table (11-state lifecycle project record, PROJ-01..03) — Plan 23-01"
provides:
  - "pipeline.project.create_project()/get_project()/list_projects()/transition_project()"
  - "pipeline.project.IllegalProjectTransitionError, _TRANSITIONS (11-state guarded lifecycle graph)"
  - "registry.repo.create_project/get_project_by_id/get_project_by_name/list_projects (CRUD)"
affects: [23-03, 23-04, 23-05, 23-06, 23-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "pipeline/project.py mirrors pipeline/curate.py's exact house style: function-shaped (not class-shaped), deferred imports at function scope where convention calls for it, Settings-driven config via settings kwarg, get_session() context-manager usage per DB interaction"
    - "IllegalProjectTransitionError mirrors TrainEvalContaminationError's shape: a RuntimeError subclass, NOT a ValueError subclass, NOT auto-caught by agent/server.py's _EXPECTED_ERRORS tuple"
    - "State-machine validation via a plain dict[str, set[str]] adjacency map + one lookup — no state-machine library dependency"

key-files:
  created:
    - src/knowledge_lake/pipeline/project.py
    - tests/unit/test_project.py
  modified:
    - src/knowledge_lake/registry/repo.py

key-decisions:
  - "create_project()/transition_project() keep an unused `_settings = settings or get_settings()` local (underscore-prefixed to satisfy ruff F841) for Settings-driven-convention parity with the rest of pipeline/*.py, even though no sub-config is read yet this phase"
  - "Task 1 (implementation) committed before Task 2 (full test authorship) per this plan's literal task boundaries — the git log shows feat(...) before test(...), inverted from canonical RED-then-GREEN ordering; this mirrors an established precedent in this codebase (17-02-SUMMARY.md's TDD Gate Compliance note) where a later task's tests prove behavior an earlier task already implemented, by deliberate plan design, not a stale/no-op test"

requirements-completed: [PROJ-01, PROJ-02]

coverage:
  - id: T1
    description: "create_project() persists a new DatasetProject row in status='draft', all omitted optional fields stored as NULL"
    requirement: "PROJ-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_project.py::TestCreateProject::test_create_project_draft_state, test_create_project_optional_fields_omitted"
        status: pass
    human_judgment: false
  - id: T2
    description: "dataset_projects.name uniqueness enforced via Postgres byte-string equality, no normalization"
    requirement: "PROJ-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_project.py::TestCreateProject::test_create_project_name_byte_equality_no_normalization (NFC vs NFD unicode both persist as distinct rows)"
        status: pass
    human_judgment: false
  - id: T3
    description: "create_project() called twice with identical name raises ValueError on the second call, not silently merging"
    requirement: "PROJ-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_project.py::TestCreateProject::test_create_project_duplicate_name_raises_valueerror"
        status: pass
    human_judgment: false
  - id: T4
    description: "Duplicate-name race resolved by the DB UNIQUE constraint alone — no application-level pre-check"
    requirement: "PROJ-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_project.py::TestCreateProject::test_create_project_duplicate_name_simulated_race"
        status: pass
    human_judgment: false
  - id: T5
    description: "Every _TRANSITIONS state has a non-empty legal-next set except the terminal 'archived' state"
    requirement: "PROJ-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_project.py::TestTransitions::test_transitions_graph_no_dead_ends (imports the ACTUAL _TRANSITIONS dict)"
        status: pass
    human_judgment: false
  - id: T6
    description: "Self-transition (to_state == current status) is never legal — raises IllegalProjectTransitionError like any other illegal edge"
    requirement: "PROJ-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_project.py::TestTransitions::test_self_transition_rejected"
        status: pass
    human_judgment: false
  - id: T7
    description: "transition_project() on a legal edge updates status; on an illegal edge raises IllegalProjectTransitionError carrying from_state/to_state/legal_next_states without mutating status"
    requirement: "PROJ-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_project.py::TestTransitions::test_legal_transition_succeeds, test_illegal_transition_rejected"
        status: pass
    human_judgment: false
  - id: T8
    description: "list_projects() orders by created_at DESC, id DESC as a deterministic tiebreak"
    requirement: "PROJ-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_project.py::TestListProjects::test_list_projects_empty, test_list_projects_ordering_tiebreak"
        status: pass
    human_judgment: false
  - id: T9
    description: "IllegalProjectTransitionError is a RuntimeError subclass, not a ValueError subclass"
    requirement: "PROJ-02"
    verification:
      - kind: unit
        ref: "uv run python -c \"from knowledge_lake.pipeline.project import IllegalProjectTransitionError; assert not issubclass(IllegalProjectTransitionError, ValueError); assert issubclass(IllegalProjectTransitionError, RuntimeError)\""
        status: pass
    human_judgment: false
  - id: T10
    description: "No regression in existing unit suite from the new module/functions"
    verification:
      - kind: unit
        ref: "uv run pytest tests/unit -x -q"
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-07-21
status: complete
---

# Phase 23 Plan 02: Dataset Project Lifecycle Core Summary

**`pipeline/project.py` implements create/get/list/transition for the 11-state Dataset Project lifecycle (PROJ-01/PROJ-02), backed by new `registry/repo.py` CRUD functions, proven by 11 new SQLite-harness unit tests covering every probe-derived edge case**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-07-21T05:22:29Z
- **Completed:** 2026-07-21T05:30:50Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- `pipeline/project.py` created as a new module, structurally mirroring `pipeline/curate.py`'s exact house style: function-shaped, `Settings`-driven, `get_session()`-scoped
- `create_project()` persists a new `DatasetProject` row in `status='draft'`, translating the underlying `IntegrityError` on `uq_dataset_projects_name` into a `ValueError` for duplicate names — no application-level pre-check race window
- `get_project()`/`list_projects()` provide read access; `list_projects()` orders `created_at DESC, id DESC` with an explicit deterministic tiebreak
- `transition_project()` guards the 11-state lifecycle via a `_TRANSITIONS: dict[str, set[str]]` adjacency map; illegal edges (including self-transitions) raise `IllegalProjectTransitionError` — a `RuntimeError` subclass mirroring `TrainEvalContaminationError`'s shape, deliberately NOT a `ValueError` subclass and NOT auto-caught by `agent/server.py`'s `_EXPECTED_ERRORS` tuple
- `registry/repo.py` gained four new CRUD functions (`create_project`, `get_project_by_id`, `get_project_by_name`, `list_projects`) in a new `# ── Dataset Project (PROJ-01..03) ──` section, ORM-only (no raw SQL)
- `tests/unit/test_project.py` created with 11 tests across `TestCreateProject`, `TestTransitions`, `TestListProjects`, covering the happy path plus every probe-derived edge case from the plan's `must_haves.truths`: empty-optional-fields, unicode byte-equality (NFC vs NFD, no normalization), duplicate-name/simulated-race rejection, state-graph reachability (no dead ends besides `archived`), self-transition rejection, and the `created_at`/`id` ordering tiebreak

## Task Commits

Each task was committed atomically:

1. **Task 1: pipeline/project.py core + repo.py CRUD — create/get/list/transition** - `8c1e9e0` (feat)
2. **Task 2: Edge-case proof — state-graph reachability, self-transition, duplicate-name race, ordering tiebreak** - `e695af0` (test)

**Plan metadata:** committed via final commit step (see completion output)

## Files Created/Modified

- `src/knowledge_lake/pipeline/project.py` - New module: `IllegalProjectTransitionError`, `_TRANSITIONS`, `create_project()`, `get_project()`, `list_projects()`, `transition_project()`
- `src/knowledge_lake/registry/repo.py` - Added `DatasetProject` to the models import block; new `# ── Dataset Project (PROJ-01..03) ──` section with `create_project`, `get_project_by_id`, `get_project_by_name`, `list_projects`; module docstring function list updated
- `tests/unit/test_project.py` - New file: `TestCreateProject` (5 tests), `TestTransitions` (4 tests), `TestListProjects` (2 tests)

## Decisions Made

- `create_project()`/`transition_project()` keep an unused `_settings = settings or get_settings()` local, underscore-prefixed to satisfy ruff's `F841` unused-variable check, preserving the `settings`-driven convention's shape for parity with the rest of `pipeline/*.py` even though no sub-config is read this phase
- Task 1 (implementation) committed before Task 2 (full test authorship), per this plan's literal task boundaries — the git log shows `feat(...)` before `test(...)`, inverted from canonical RED-then-GREEN ordering. This mirrors an established precedent in this codebase (see `17-02-SUMMARY.md`'s TDD Gate Compliance note): a later task's tests prove behavior an earlier task already implemented, by deliberate plan design, not a stale/no-op test — see "TDD Gate Compliance" below

## Deviations from Plan

None - plan executed exactly as written. Both tasks' exact function signatures, `_TRANSITIONS` graph, docstrings, and test class/method structure matched the plan's `<action>`/`<behavior>` blocks. The only adjustment (the `_settings` underscore-prefix naming) is a mechanical ruff-lint accommodation of the plan's own literal `s = settings or get_settings()` instruction, not a behavioral deviation.

## TDD Gate Compliance

This plan's frontmatter is `type: tdd`. Git log shows:
1. `8c1e9e0 feat(23-02): pipeline/project.py core + repo.py CRUD...` (implementation)
2. `e695af0 test(23-02): edge-case proof...` (tests)

This is `feat` before `test`, not the canonical RED-then-GREEN `test` before `feat` sequence the plan-level TDD gate checks for. This is a deliberate plan-authoring choice, not an executor deviation: the plan's Task 1 delivers `pipeline/project.py`'s core implementation (mirroring `pipeline/curate.py`'s established structure), and Task 2 is explicitly scoped as "the FULL authorship of the file's initial classes... matching this codebase's `21-04-PLAN.md`-established precedent of one task landing core behavior tests and a second task extending the same file with edge cases." All 11 tests in `tests/unit/test_project.py` passed on first run against the Task-1 implementation — proving the implementation is correct, not a stale/no-op test suite (mirrors the `17-02-SUMMARY.md` precedent cited in `STATE.md`'s Decisions log).

## Issues Encountered

None. The only friction was mechanical: `s = settings or get_settings()` (the plan's literal action text) tripped ruff's `F841` unused-variable check since neither function reads a sub-config from `Settings` yet — resolved by renaming to `_settings` (ruff's default dummy-variable pattern), with no behavior change.

## User Setup Required

None - no external service configuration required. All verification ran against the SQLite in-memory test harness (mirrors `test_curate.py`'s fixture pattern); no live Postgres interaction needed for this plan (the schema was already applied to dev Postgres in Plan 23-01).

## Next Phase Readiness

- `pipeline.project.create_project()`/`get_project()`/`list_projects()`/`transition_project()` and `IllegalProjectTransitionError` are ready for Plan 23-03 to extend with spec versioning in the same file (Wave 3, after this plan's Wave 2)
- Ready for Plan 23-05 (API routes, catching `IllegalProjectTransitionError` as a 409) and Plan 23-06 (CLI commands, catching it as an exit-1) to build their thin-shim surfaces on top
- Plan 23-07's MCP `project_list`/`project_show` read tools can call `list_projects()`/`get_project()` directly — `IllegalProjectTransitionError` deliberately does NOT cross Plan 23-07's `call_tool` boundary this phase (D-05 ships read-only tools only), per the one-line comment left in `pipeline/project.py` next to the exception class
- Plan 23-04's `get_latest_released_dataset_by_name()` (D-02's export-identity-ambiguity fix) will read `DatasetProject.status == 'released'` rows — this plan's `transition_project()` is the only path that can ever set that status, so the invariant is already correctly guarded
- No blockers. Full unit suite (983 tests, 1 xfailed) passes with zero regressions

---
*Phase: 23-dataset-project-specification-foundation*
*Completed: 2026-07-21*
