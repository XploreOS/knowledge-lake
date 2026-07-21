---
phase: 23-dataset-project-specification-foundation
plan: 05
subsystem: api
tags: [fastapi, pydantic, dataset-project, dataset-spec, openapi, http-409]

# Dependency graph
requires:
  - "pipeline.project.create_project()/get_project()/list_projects()/transition_project()/IllegalProjectTransitionError — Plan 23-02"
  - "pipeline.project.create_spec_version()/get_latest_spec()/validate_spec()/DatasetSpecFields — Plan 23-03"
provides:
  - "POST/GET /projects, GET /projects/{id}, POST /projects/{id}/transition, POST /projects/{id}/specs, POST /specs/{id}/validate routes in api/app.py"
  - "ProjectCreate/ProjectOut/ProjectTransitionRequest/SpecVersionCreate/SpecVersionOut/SpecValidateResponse schemas in api/schemas.py"
  - "ProjectListInput/ProjectShowInput/SpecValidateInput MCP-only input models in api/schemas.py, for Plan 23-07 to import"
  - "docs/openapi.json regenerated with the five new routes"
affects: [23-06, 23-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SURFACE-02 established: new API routes call pipeline.project.* functions directly inside a deferred import, zero business logic in the route handler body — first proof of this convention for every later v2.7 phase to replicate"
    - "HTTP 409 introduced for the first time in this codebase (RESEARCH.md Pattern 4) — IllegalProjectTransitionError maps to a structured 409 detail body {error, from_state, to_state, legal_next_states}, distinct from the codebase's prior 422/404-only vocabulary"
    - "Validation-failure-as-200-report pattern (QCON-02): POST /specs/{id}/validate returns 200 with valid=false for a genuine validation failure — only an unknown spec_id raises 404"

key-files:
  created:
    - tests/integration/test_api_project.py
  modified:
    - src/knowledge_lake/api/schemas.py
    - src/knowledge_lake/api/app.py
    - docs/openapi.json

key-decisions:
  - "ProjectOut is constructed via ProjectOut(**result) from pipeline.project's dict returns, which include extra keys (created_at, updated_at from get_project()) not declared on ProjectOut — relies on Pydantic v2's default extra='ignore' behavior on BaseModel(**kwargs), confirmed via direct test rather than assumed"
  - "transition_project_endpoint calls transition_project() then a follow-up get_project() to build the full ProjectOut response, since transition_project()'s own return dict is intentionally narrow ({id, status} only, per pipeline/project.py's docstring) — avoids inventing a new pipeline function or duplicating field-mapping logic in the route"

requirements-completed: [PROJ-03, SPEC-03, SURFACE-02]

coverage:
  - id: D1
    description: "POST /projects creates a project in draft state (200 + ProjectOut); duplicate name returns 422 with the ValueError message"
    requirement: "PROJ-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_api_project.py::test_create_project_returns_draft, test_create_project_duplicate_name_returns_422"
        status: pass
    human_judgment: false
  - id: D2
    description: "GET /projects/{id} returns 200 + ProjectOut for a known id, 404 for unknown; GET /projects lists all projects"
    requirement: "PROJ-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_api_project.py::test_get_project_unknown_returns_404, test_list_projects_returns_200_list"
        status: pass
    human_judgment: false
  - id: D3
    description: "POST /projects/{id}/transition on an illegal edge returns 409 with the full structured detail body {error, from_state, to_state, legal_next_states} — the first use of HTTP 409 in this codebase; a legal edge returns 200"
    requirement: "PROJ-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_api_project.py::test_transition_illegal_edge_returns_409_with_detail, test_transition_legal_edge_returns_200"
        status: pass
    human_judgment: false
  - id: D4
    description: "POST /projects/{id}/specs creates a new immutable spec version, returns 200 + SpecVersionOut with content_hash and parent_spec_id=None for the first version"
    requirement: "SPEC-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_api_project.py::test_create_spec_version_returns_200_and_hash"
        status: pass
    human_judgment: false
  - id: D5
    description: "POST /specs/{id}/validate returns 200 + SpecValidateResponse{valid, errors} for both an unresolvable-source (valid=false) and an all-refs-resolve (valid=true) spec — a validation failure is never an HTTP error status"
    requirement: "SPEC-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_api_project.py::test_spec_validate_unknown_source_returns_200_invalid, test_spec_validate_all_refs_resolve_returns_200_valid"
        status: pass
    human_judgment: false
  - id: D6
    description: "docs/openapi.json is regenerated after the new routes are added and stays byte-identical to a fresh deterministic dump"
    requirement: "SURFACE-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_openapi_export.py::test_openapi_json_matches_deterministic_dump"
        status: pass
    human_judgment: false
  - id: D7
    description: "Every new route calls pipeline.project.* directly with a deferred import and zero duplicated business logic (SURFACE-02) — no loops, conditionals, or DB queries in any of the five handler bodies beyond input-shape checks"
    requirement: "SURFACE-02"
    verification:
      - kind: manual_procedural
        ref: "Direct source read of src/knowledge_lake/api/app.py's five new route handlers"
        status: pass
    human_judgment: false

duration: 2min
completed: 2026-07-21
status: complete
---

# Phase 23 Plan 05: Dataset Project/Specification API Surface Summary

**Five new FastAPI routes (POST/GET /projects, GET /projects/{id}, POST /projects/{id}/transition, POST /projects/{id}/specs, POST /specs/{id}/validate) calling `pipeline.project.*` directly, introducing this codebase's first HTTP 409 for illegal lifecycle transitions and proving the validation-failure-as-200-report pattern for spec validation**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-07-21T10:41:00Z
- **Completed:** 2026-07-21T10:43:31Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- `api/schemas.py` gained six new Pydantic schemas (`ProjectCreate`, `ProjectOut`, `ProjectTransitionRequest`, `SpecVersionCreate`, `SpecVersionOut`, `SpecValidateResponse`) in a new `# ── Dataset Project / Specification schemas ──` section, following `ExportRequest`/`ExportResponse`'s exact `Field(..., pattern=..., max_length=..., description=...)` allow-list-first style
- Three MCP-only input models (`ProjectListInput`, `ProjectShowInput`, `SpecValidateInput`) added near `ListSourcesInput`/`LineageInput`, mirroring their exact docstring convention — landed now so Plan 23-07's `agent/registry.py` MCP tool definitions can import them without touching `api/schemas.py` again
- `api/app.py` gained five new routes at the end of the file, each following `export_endpoint`'s exact convention: deferred import from `pipeline.project` inside the handler body, `logger.info` before/after dispatch, typed-exception-first `except` ordering, D-02-compliance docstring note
- `POST /projects/{id}/transition` introduces HTTP 409 for the first time in this codebase (RESEARCH.md Pattern 4) — `IllegalProjectTransitionError` maps to a structured `{error, from_state, to_state, legal_next_states}` detail body, with an inline comment flagging the deliberate first-of-its-kind status code
- `POST /specs/{id}/validate` proves the validation-failure-as-200-report pattern (QCON-02): a `valid: false` result is a normal 200, only an unknown `spec_id` raises 404
- `docs/openapi.json` regenerated via `uv run klake openapi`; `tests/unit/test_openapi_export.py`'s determinism check passes with the five new routes included
- `tests/integration/test_api_project.py` created with 9 tests proving all five routes' happy-path and error-path behavior against the live FastAPI `TestClient` + Postgres stack, reusing `test_api_new_endpoints.py`'s import-guard + module-scoped `TestClient` fixture verbatim

## Task Commits

Each task was committed atomically:

1. **Task 1: api/schemas.py schemas + api/app.py routes + openapi regen** - `027b310` (feat)
2. **Task 2: tests/integration/test_api_project.py — full route round-trip coverage** - `9e508b3` (test)

**Plan metadata:** committed via final commit step (see completion output)

## Files Created/Modified

- `src/knowledge_lake/api/schemas.py` - Added `ProjectCreate`, `ProjectOut`, `ProjectTransitionRequest`, `SpecVersionCreate`, `SpecVersionOut`, `SpecValidateResponse`, `ProjectListInput`, `ProjectShowInput`, `SpecValidateInput`
- `src/knowledge_lake/api/app.py` - Added `create_project_endpoint`, `list_projects_endpoint`, `get_project_endpoint`, `transition_project_endpoint`, `create_spec_version_endpoint`, `validate_spec_endpoint`; extended the `api.schemas` import block
- `docs/openapi.json` - Regenerated via `uv run klake openapi`, adding the five new route entries (additive-only diff, sorted-key JSON)
- `tests/integration/test_api_project.py` - New file: 9 integration tests covering all five routes' happy-path and error-path behavior

## Decisions Made

- `ProjectOut(**result)` relies on Pydantic v2's default `extra='ignore'` behavior to silently drop `get_project()`'s extra `created_at`/`updated_at` keys (not declared on `ProjectOut` per the plan's literal field list) — verified directly with a Python REPL check rather than assumed, since a wrong assumption here would have caused a `ValidationError` on every `GET /projects/{id}` call
- `transition_project_endpoint` calls `transition_project()` (which intentionally returns only `{id, status}`) followed by `get_project()` to build the full `ProjectOut` response — avoids inventing a new pipeline function or duplicating field-mapping logic inside the route handler

## Deviations from Plan

None - plan executed exactly as written. All six API schemas, three MCP-only input models, five routes, and the `docs/openapi.json` regeneration match the plan's `<action>`/`<behavior>` blocks verbatim, including the exact 409 detail body shape and the `POST /specs/{id}/validate` 200-report behavior.

## Issues Encountered

None. No auth gates, no architectural deviations, no fix-attempt escalations. `ruff check` and `mypy` on the two modified source files reported only pre-existing findings (confirmed by line-number and by cross-checking against `test_api_new_endpoints.py`'s identical `I001` import-guard finding, which the plan explicitly instructs this file to mirror verbatim) — zero new findings introduced by this plan's diff. Full unit suite (998 passed, 1 xfailed) and the new 9-test integration suite both passed clean against the live dev Postgres stack.

## User Setup Required

None - no external service configuration required. Integration tests ran against the already-running dev Postgres stack (no new service, no new schema — Plan 23-01 already applied `dataset_projects`/`dataset_specs`).

## Next Phase Readiness

- All five routes are ready for Plan 23-06's CLI commands (`klake project create/list/show/transition`, `klake dataset spec create/validate`) to build thin shims calling the exact same `pipeline.project.*` functions (D-02, SURFACE-02)
- `ProjectListInput`/`ProjectShowInput`/`SpecValidateInput` are already landed in `api/schemas.py` so Plan 23-07's MCP tool registry can import them directly without touching this file again
- The HTTP 409 pattern and the validation-failure-as-200 pattern are both proven and documented for every later v2.7 phase (Policy, Quality Contract, Release) to replicate without re-litigation
- No blockers. Full unit suite (998 passed, 1 xfailed) and the new integration suite (9 passed) pass with zero regressions

---
*Phase: 23-dataset-project-specification-foundation*
*Completed: 2026-07-21*

## Self-Check: PASSED

- FOUND: src/knowledge_lake/api/schemas.py
- FOUND: src/knowledge_lake/api/app.py
- FOUND: docs/openapi.json
- FOUND: tests/integration/test_api_project.py
- FOUND: .planning/phases/23-dataset-project-specification-foundation/23-05-SUMMARY.md
- FOUND commit: 027b310
- FOUND commit: 9e508b3
