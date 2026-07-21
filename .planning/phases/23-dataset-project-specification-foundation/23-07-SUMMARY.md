---
phase: 23-dataset-project-specification-foundation
plan: 07
subsystem: agent
tags: [mcp, tool-registry, dataset-project, dataset-spec, surface-parity]

# Dependency graph
requires:
  - "pipeline.project.list_projects()/get_project()/validate_spec() — Plan 23-02/23-03"
  - "ProjectListInput/ProjectShowInput/SpecValidateInput MCP-only input models in api/schemas.py — Plan 23-05"
provides:
  - "agent/registry.py TOOLS list extended to 14 entries: project_list, project_show, spec_validate ToolDefs"
  - "registered_tools(readonly=True) now exposes 7 read tools (4 pre-existing + 3 new)"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "MCP read-tool shims are one-line bodies calling straight into pipeline.project.*, mirroring _lineage_handler's exact shape — no business logic in agent/registry.py"

key-files:
  created: []
  modified:
    - src/knowledge_lake/agent/registry.py
    - tests/integration/test_mcp_http.py
    - tests/unit/test_readonly.py
    - tests/unit/test_tool_registry.py
    - tests/unit/test_surface_parity.py

key-decisions:
  - "Fixed 3 stale Wave-0/Phase-12 test files (test_readonly.py, test_tool_registry.py, test_surface_parity.py) hardcoding the old 11/4 tool counts — not in this plan's files_modified list, but directly broken by the TOOLS count bump and blocking the plan's own required regression pass; treated as Rule 1 auto-fixes since they're in-scope (directly caused by this task's change)"

requirements-completed: [SURFACE-03]

coverage:
  - id: D1
    description: "TOOLS has exactly 14 entries (11 pre-existing + project_list/project_show/spec_validate), no duplicate names, module docstring and registered_tools() docstring updated to match"
    requirement: "SURFACE-03"
    verification:
      - kind: unit
        ref: "python -c import-and-assert one-liner (Task 1 verify block); tests/unit/test_tool_registry.py::test_tools_count_is_fourteen, test_tool_names_match_expected_set"
        status: pass
    human_judgment: false
  - id: D2
    description: "project_list, project_show, spec_validate are all access='read' — registered_tools(readonly=True) returns exactly the 7 read tools; no mutating project/spec MCP tool exists (D-05)"
    requirement: "SURFACE-03"
    verification:
      - kind: unit
        ref: "tests/unit/test_tool_registry.py::test_read_only_tools_subset, test_registered_tools_all_returns_all; tests/unit/test_readonly.py::test_readonly_returns_seven_tools"
      - kind: integration
        ref: "tests/integration/test_mcp_http.py::test_readonly_lists_only_read_tools_over_http"
        status: pass
    human_judgment: false
  - id: D3
    description: "Each new handler is a one-line thin shim over pipeline.project.* (list_projects/get_project/validate_spec); agent/server.py untouched — none of the 3 tools can raise IllegalProjectTransitionError"
    requirement: "SURFACE-03"
    verification:
      - kind: unit
        ref: "Direct source read of agent/registry.py's _project_list_handler/_project_show_handler/_spec_validate_handler; git diff confirms zero changes to agent/server.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "Surface-parity gate (stdio == http == openai == model_json_schema) holds for all 14 tools including the 3 new ones"
    requirement: "SURFACE-03"
    verification:
      - kind: unit
        ref: "tests/unit/test_surface_parity.py::test_all_fourteen_tools_present, test_three_way_parity_all_tools, test_readonly_posture_is_identical_across_transports"
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-07-21
status: complete
---

# Phase 23 Plan 07: Dataset Project/Specification MCP Read Tools Summary

**`agent/registry.py`'s `TOOLS` list grows from 11 to 14 entries with three new read-only MCP tool shims (`project_list`, `project_show`, `spec_validate`) over `pipeline.project.*`, completing SURFACE-03's read-tools-first convention for this phase**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-07-21T10:52:00Z
- **Completed:** 2026-07-21T11:04:00Z
- **Tasks:** 2
- **Files modified:** 5 (2 planned + 3 deviation fixes)

## Accomplishments

- `agent/registry.py` gained three thin-shim handlers (`_project_list_handler`, `_project_show_handler`, `_spec_validate_handler`), each a one-line body calling `list_projects()`/`get_project()`/`validate_spec()` respectively, mirroring `_lineage_handler`'s exact shape
- Three new `ToolDef` entries wired into `TOOLS` under the `# ── Read tools ──` section, all `access="read"`, importing `ProjectListInput`/`ProjectShowInput`/`SpecValidateInput` from `api/schemas.py` (Plan 23-05's exact MCP-only models, zero new Pydantic models added)
- `TOOLS` count assertion bumped `11 -> 14`; module docstring, `# Order:` comment, and `registered_tools()`'s docstring all updated in the same change to prevent the drift Threat T-23-20 explicitly warns against
- `agent/server.py` left untouched — confirmed via `git diff` — since none of the 3 new read-only tools can raise `IllegalProjectTransitionError` (they never call `transition_project()`); a one-line comment above the new `ToolDef` entries documents this explicitly for a future `project_transition` MCP tool
- `tests/integration/test_mcp_http.py`'s `_READ_TOOLS` set extended from 4 to 7 entries; `test_readonly_lists_only_read_tools_over_http` now proves the 7-tool read-only HTTP surface
- Surface-parity gate (`test_surface_parity.py`) re-verified green for all 14 tools — MCP inputSchema, OpenAI parameters, and `model_json_schema()` stay in sync for the 3 new tools with zero manual schema authoring

## Task Commits

Each task was committed atomically:

1. **Task 1: project_list/project_show/spec_validate ToolDefs + TOOLS count bump** - `8be8298` (feat)
2. **Task 2: Extend test_mcp_http.py's read-only-surface proof to the 3 new tools** - `546df75` (test)

Deviation fix commits (Rule 1, see below):
3. **Fix stale Wave-0 readonly-count test** - `c886723` (fix)
4. **Fix stale hardcoded tool-count tests (test_tool_registry.py, test_surface_parity.py)** - `053eef1` (fix)

**Plan metadata:** committed via final commit step (see completion output)

## Files Created/Modified

- `src/knowledge_lake/agent/registry.py` - Added `_project_list_handler`, `_project_show_handler`, `_spec_validate_handler`, three new `ToolDef` entries, `TOOLS` assertion bumped 11 → 14, docstrings updated
- `tests/integration/test_mcp_http.py` - `_READ_TOOLS` extended to 7 entries, module/test docstrings updated
- `tests/unit/test_readonly.py` - Stale Wave-0 scaffold hardcoding 4/11 tool counts updated to 7/14 (Rule 1 fix)
- `tests/unit/test_tool_registry.py` - Stale Wave-0 scaffold hardcoding 11/4 tool counts updated to 14/7 (Rule 1 fix)
- `tests/unit/test_surface_parity.py` - Stale surface-parity gate hardcoding 11/4 tool counts updated to 14/7 (Rule 1 fix)

## Decisions Made

- Three pre-existing Phase-12-era test files (`test_readonly.py`, `test_tool_registry.py`, `test_surface_parity.py`) hardcode the old `TOOLS==11` / `read_tools==4` counts from Wave 0. These are not in this plan's `files_modified` list, but this plan's own `<verification>` block explicitly requires `uv run pytest tests/unit tests/integration -x -q -m "not integration"` to pass — and these three files fail deterministically the moment `TOOLS` grows past 11. Fixed under deviation Rule 1 (auto-fix bugs directly caused by this task's changes) rather than treated as out-of-scope drift, since the breakage is a direct, mechanical consequence of the plan's own literal action text (bumping the assertion to 14).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Stale Wave-0 readonly-count test broken by TOOLS bump**
- **Found during:** Task 1 verification (running the broader regression pass per plan's `<verification>` block)
- **Issue:** `tests/unit/test_readonly.py` hardcoded `registered_tools(readonly=True)` returning exactly 4 tools and `registered_tools(readonly=False)` returning exactly 11 — both directly falsified by this plan's TOOLS count bump to 14/7
- **Fix:** Extended `_EXPECTED_READ_TOOLS` to the 7-tool set, renamed `test_readonly_returns_four_tools` → `test_readonly_returns_seven_tools`, updated the "all 11 tools" docstring/assertion to 14
- **Files modified:** `tests/unit/test_readonly.py`
- **Verification:** `uv run pytest tests/unit/test_readonly.py -x -q` — 9 passed
- **Committed in:** `c886723`

**2. [Rule 1 - Bug] Stale hardcoded tool-count assertions in registry/parity test files**
- **Found during:** Task 1 verification (broader regression pass)
- **Issue:** `tests/unit/test_tool_registry.py` (`test_tools_count_is_eleven`, `test_read_only_tools_subset`, `test_registered_tools_all_returns_all`, `test_tool_names_match_expected_set`) and `tests/unit/test_surface_parity.py` (`test_all_eleven_tools_present`, `test_readonly_posture_is_identical_across_transports`) all hardcoded the pre-Phase-23 11/4 tool counts and tool-name sets
- **Fix:** Updated `_EXPECTED_TOOL_NAMES`/`_READ_TOOLS` sets to include `project_list`/`project_show`/`spec_validate`, renamed `test_tools_count_is_eleven` → `test_tools_count_is_fourteen` and `test_all_eleven_tools_present` → `test_all_fourteen_tools_present`, updated all count assertions and docstrings to 14/7
- **Files modified:** `tests/unit/test_tool_registry.py`, `tests/unit/test_surface_parity.py`
- **Verification:** `uv run pytest tests/unit/test_tool_registry.py tests/unit/test_surface_parity.py -q` — 21 passed, including the three-way MCP/OpenAI/model_json_schema parity gate for all 14 tools
- **Committed in:** `053eef1`

---

**Total deviations:** 2 auto-fixed (both Rule 1 — bugs directly caused by this plan's own TOOLS count change)
**Impact on plan:** Both fixes were mechanical count/name-set updates in test files, not behavioral changes to the plan's own deliverables. No scope creep — fixes were strictly required to make the plan's own mandated regression command pass.

## Issues Encountered

None beyond the two Rule-1 deviations above. No auth gates, no architectural deviations, no fix-attempt escalations. `ruff check` and `mypy` on `src/knowledge_lake/agent/registry.py` both passed clean (ruff auto-fixed one `I001` import-sort finding on the new `pipeline.project` import block — mechanical reordering, no behavior change). Full unit + non-integration-marked suite (1173 passed, 3 skipped, 1 xfailed) and the full `tests/integration/test_mcp_http.py -m integration` suite (7 passed) both green.

## User Setup Required

None - no external service configuration required. `docs/openapi.json` was not regenerated since this plan adds zero new FastAPI routes (MCP-only surface change) — verified the existing `test_openapi_export.py` determinism gate still passes unchanged.

## Next Phase Readiness

- SURFACE-03 is fully delivered: Phase 23 now exposes `project_list`/`project_show`/`spec_validate` as thin, read-only MCP tool shims over `pipeline/project.py`, completing the CLI (23-06) / API (23-05) / MCP (23-07) triad over the same underlying pipeline functions
- D-05 holds: zero mutating project/spec MCP tool exists in this codebase after Phase 23 — `project_new`/`project_transition`/`spec_create` are deliberately withheld until a later phase's human-approval-gate pattern exists
- This is the final plan (Wave 5) of Phase 23 — all 7 plans (23-01 through 23-07) are now complete
- No blockers. Full unit suite (1173 passed, 3 skipped, 1 xfailed) plus MCP HTTP integration suite (7 passed) pass with zero regressions

---
*Phase: 23-dataset-project-specification-foundation*
*Completed: 2026-07-21*

## Self-Check: PASSED

- FOUND: src/knowledge_lake/agent/registry.py
- FOUND: tests/integration/test_mcp_http.py
- FOUND: tests/unit/test_readonly.py
- FOUND: tests/unit/test_tool_registry.py
- FOUND: tests/unit/test_surface_parity.py
- FOUND: .planning/phases/23-dataset-project-specification-foundation/23-07-SUMMARY.md
- FOUND commit: 8be8298
- FOUND commit: 546df75
- FOUND commit: c886723
- FOUND commit: 053eef1
