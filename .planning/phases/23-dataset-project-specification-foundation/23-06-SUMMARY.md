---
phase: 23-dataset-project-specification-foundation
plan: 06
subsystem: cli
tags: [typer, cli, dataset-project, dataset-spec, yaml]

# Dependency graph
requires:
  - phase: 23-02
    provides: "pipeline.project.create_project()/get_project()/list_projects()/transition_project(), IllegalProjectTransitionError"
  - phase: 23-03
    provides: "pipeline.project.create_spec_version()/get_latest_spec()/validate_spec()"
provides:
  - "klake project new/list/show/transition CLI commands (PROJ-03)"
  - "klake dataset spec create/validate CLI commands (SPEC-01, SPEC-03)"
  - "dataset_app scaffolding (empty top-level group + nested spec_app) for Phases 27/30/31's future release/diff/curate-run subcommands"
affects: [23-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "project_app/dataset_app mirror domain_app's exact typer.Typer(name=..., help=..., add_completion=False) + app.add_typer(...) registration pattern"
    - "cmd_project_transition catches IllegalProjectTransitionError before the generic ValueError fallback (specific-exception-first, matching cmd_domain_new's except (ValueError, FileExistsError) convention)"
    - "cmd_spec_create uses yaml.safe_load exclusively (never yaml.load/yaml.unsafe_load) — T-23-17 mitigation, matching domains/loader.py's established convention"

key-files:
  created:
    - tests/integration/test_project_cli.py
  modified:
    - src/knowledge_lake/cli/app.py

key-decisions:
  - "All six CLI commands are thin shims calling pipeline.project.* directly with zero duplicated business logic — the SAME functions Plan 23-05's API routes call, per SURFACE-02's shared-pipeline-function convention extended to the CLI surface"
  - "dataset_app scaffolded now as an otherwise-empty group (just spec_app nested) per RESEARCH.md Open Question 2, so future phases add release/diff/curate-run subcommands without retrofitting a new top-level group"

requirements-completed: [PROJ-03, SPEC-01, SPEC-03, SURFACE-01]

coverage:
  - id: D1
    description: "klake project new/list/show/transition round-trip against the live registry (ROADMAP Success Criterion 1)"
    requirement: "PROJ-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_project_cli.py::test_project_new_creates_draft, test_project_list_empty_or_populated_exits_0, test_project_show_unknown_exits_1"
        status: pass
    human_judgment: false
  - id: D2
    description: "klake project transition <id> <illegal-state> exits non-zero with a clear error naming the invalid transition and legal next states (ROADMAP Success Criterion 2)"
    requirement: "PROJ-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_project_cli.py::test_project_transition_illegal_exits_1_with_message"
        status: pass
    human_judgment: false
  - id: D3
    description: "klake dataset spec create parses YAML via yaml.safe_load only and calls create_spec_version()"
    requirement: "SPEC-01"
    verification:
      - kind: integration
        ref: "tests/integration/test_project_cli.py::test_dataset_spec_create_and_validate_round_trip"
        status: pass
    human_judgment: false
  - id: D4
    description: "klake dataset spec validate resolves the project's latest spec version; zero-spec-version projects print a clear error and exit non-zero"
    requirement: "SPEC-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_project_cli.py::test_dataset_spec_validate_no_spec_exits_1, test_dataset_spec_validate_missing_argument_exits_nonzero"
        status: pass
    human_judgment: false
  - id: D5
    description: "project/dataset top-level Typer groups do not collide with any pre-existing command name; full pre-existing CLI test suite passes unchanged (SURFACE-01)"
    verification:
      - kind: unit
        ref: "uv run pytest tests/unit -x -q (998 passed, 1 xfailed)"
        status: pass
    human_judgment: false

duration: ~10min
completed: 2026-07-21
status: complete
---

# Phase 23 Plan 06: Dataset Project + Specification CLI Surface Summary

**`klake project new/list/show/transition` and `klake dataset spec create/validate` land as thin Typer shims mirroring `domain_app`'s exact registration pattern, calling `pipeline.project.*` directly and using `yaml.safe_load` exclusively for spec authoring**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-07-21T10:45:00Z
- **Completed:** 2026-07-21T10:49:59Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `project_app` sub-Typer group added to `cli/app.py` with `new`/`list`/`show`/`transition` commands, registered via `app.add_typer(project_app, name="project")` immediately after the existing `domain_app` block — mirrors its `typer.Typer(name=..., help=..., add_completion=False)` shape exactly
- `cmd_project_new` calls `create_project()`, translating its `ValueError` (duplicate name) into exit code 1; `cmd_project_list` prints `list_projects()`'s return in its own deterministic `created_at DESC, id DESC` order with no re-sorting, and prints "No projects found." (exit 0) on an empty registry; `cmd_project_show` translates a not-found `ValueError` into exit 1; `cmd_project_transition` catches `IllegalProjectTransitionError` before the generic `ValueError` fallback (specific-exception-first), surfacing from-state/to-state/legal-next-states in its error output
- `dataset_app` sub-Typer group added, scaffolded per RESEARCH.md Open Question 2 as an otherwise-empty group with a nested `spec_app` (`dataset_app.add_typer(spec_app, name="spec")`) — so Phases 27/30/31 can add `release`/`diff`/`curate-run` subcommands directly to `dataset_app` without retrofitting a new top-level group
- `cmd_spec_create` reads a YAML file via `yaml.safe_load` exclusively (never `yaml.load`/`yaml.unsafe_load` — T-23-17 mitigation), then calls `create_spec_version()`; `cmd_spec_validate` resolves `get_latest_spec()` first, printing a clear "no spec version exists" message and exiting 1 when the project has zero spec versions, otherwise calling `validate_spec()` and printing `valid`/itemized `errors`, exiting 1 when invalid
- `tests/integration/test_project_cli.py` created with 8 `CliRunner` tests against the live dev registry, mirroring `test_domain_init.py`'s import-guard pattern and `test_api_project.py`'s `uuid4()`-suffixed-name convention — proves every `<behavior>` block truth including the illegal-transition error detail, the empty-registry message, and Typer's own missing-argument handling for `dataset spec validate` with no project_id

## Task Commits

Each task was committed atomically:

1. **Task 1: project_app + dataset_app/spec_app CLI groups** - `20096cf` (feat)
2. **Task 2: tests/integration/test_project_cli.py — full CLI round-trip coverage** - `bcb41ca` (test)

**Plan metadata:** committed via final commit step (see completion output)

## Files Created/Modified

- `src/knowledge_lake/cli/app.py` - Added `project_app` (`cmd_project_new/list/show/transition`) and `dataset_app`/`spec_app` (`cmd_spec_create`, `cmd_spec_validate`), inserted between `domain_app`'s block and `if __name__ == "__main__":`
- `tests/integration/test_project_cli.py` - New file: 8 `CliRunner` tests covering the full happy path and every probe-derived edge case from the plan's `must_haves.truths`

## Decisions Made

- All six commands are thin shims calling `pipeline.project.*` directly with zero duplicated business logic — same functions Plan 23-05's API routes call (SURFACE-02 extended to the CLI surface)
- `dataset_app` scaffolded now as an empty group except for `spec_app`, matching RESEARCH.md Open Question 2's explicit recommendation for future phases

## Deviations from Plan

None - plan executed exactly as written. All six command signatures, the specific-exception-first ordering in `cmd_project_transition`, the `yaml.safe_load`-only convention in `cmd_spec_create`, and the test file's 8 test cases all match the plan's `<action>`/`<behavior>` blocks verbatim.

## Issues Encountered

None. `ruff check` on `cli/app.py` passed clean; `ruff format --check` reported pre-existing (not newly introduced) formatting drift in the file predating this plan's diff, confirmed via `git stash` comparison — out of scope. `tests/integration/test_project_cli.py`'s import-block ordering triggers the same `ruff I001` finding as `test_domain_init.py` (its copied precedent) — confirmed this is the established `tests/`-scope-excluded pattern per `CI-LINT-01` (STATE.md), not a regression. `mypy` flagged one `no-any-return` in the new test file's helper (fixed with an explicit `str(...)` cast).

## User Setup Required

None - no external service configuration required. All verification ran against the live dev PostgreSQL/compose stack already running.

## Next Phase Readiness

- `klake project new/list/show/transition` and `klake dataset spec create/validate` fully deliver PROJ-03/SPEC-01/SPEC-03's CLI requirements with zero regression to any existing command (`uv run pytest tests/unit -x -q`: 998 passed, 1 xfailed)
- `dataset_app`'s empty-except-`spec_app` scaffolding is ready for Phase 27/30/31 to extend with `release`/`diff`/`curate-run` subcommands
- Plan 23-07's MCP tools (Wave 4's final plan, if scheduled) can call `pipeline.project.*` read functions directly, matching this plan's and Plan 23-05's shared-function convention
- No blockers.

---
*Phase: 23-dataset-project-specification-foundation*
*Completed: 2026-07-21*

## Self-Check: PASSED

- FOUND: src/knowledge_lake/cli/app.py
- FOUND: tests/integration/test_project_cli.py
- FOUND: .planning/phases/23-dataset-project-specification-foundation/23-06-SUMMARY.md
- FOUND commit: 20096cf
- FOUND commit: bcb41ca
