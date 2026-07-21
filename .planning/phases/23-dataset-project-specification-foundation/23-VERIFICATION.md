---
phase: 23-dataset-project-specification-foundation
verified: 2026-07-21T11:38:27Z
status: passed
score: 9/9 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 23: Dataset Project / Specification Foundation Verification Report

**Phase Goal:** Users can create and version-manage Dataset Projects and their declarative Specifications, with the existing dataset export identity contract preserved across all four call sites, and the CLI/API/MCP surface convention for this milestone established.
**Verified:** 2026-07-21T11:38:27Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `dataset_projects`/`dataset_specs` tables exist in Postgres, migration 0012 applied, unique/insert-only design in place | ✓ VERIFIED | `alembic current` → `0012 (head)`; live query against dev Postgres confirms both tables exist, `uq_dataset_projects_name` constraint present, `datasets.dataset_project_id`/`dataset_spec_id` are nullable |
| 2 | `DatasetProject`/`DatasetSpec` ORM models + `ids.py` prefixes (`dpj`/`dsp`) match migration column-for-column | ✓ VERIFIED | Read `registry/models.py:568-700` — field set, types, docstrings match migration exactly; `ids.py:47-48` has `"dataset_project": "dpj"`, `"dataset_spec": "dsp"` |
| 3 | `create_project()`/`get_project()`/`list_projects()`/`transition_project()` implement PROJ-01/02 with the guarded 11-state lifecycle, duplicate-name rejection, deterministic ordering | ✓ VERIFIED | Read `pipeline/project.py:180-346`; live check: `LIFECYCLE_STATES` has exactly 11 states, no self-transitions, `archived` is the only dead end; `tests/unit/test_project.py` (25 tests, all pass) exercises create/duplicate/race/transition/ordering |
| 4 | `DatasetSpecFields`/`create_spec_version()`/`get_latest_spec()`/`validate_spec()` implement SPEC-01/02/03 — allow-list schema, canonical-hash no-op dedup, immutable parent chain, referential validation | ✓ VERIFIED | Read `pipeline/project.py:47-514`; `tests/unit/test_project.py::TestSpecFields/TestSpecVersioning/TestValidateSpec` (all pass) cover minimal-field defaults, extra-field rejection, hash stability across key order, no-op re-save, parent-chain immutability, referential integrity |
| 5 | D-02 export identity fix: `get_latest_released_dataset_by_name()` resolves a project's released Dataset; all 4 existing `export_finetune_dataset()` call sites (CLI, API, MCP, Dagster) remain unchanged | ✓ VERIFIED | Read `registry/repo.py:1361-1399`, `pipeline/export.py:585-587` (one-line swap only); confirmed all 4 call sites (`cli/app.py:1280`, `api/app.py:1248`, `agent/registry.py:140`, `dagster_defs/assets.py:1004→1019` internal call) unchanged; `tests/integration/test_export_project_resolution.py` (2 tests) pass |
| 6 | API surface: `POST/GET /projects`, `GET /projects/{id}`, `POST /projects/{id}/transition`, `POST /projects/{id}/specs`, `POST /specs/{id}/validate` — 404/409/422 semantics correct, routes call pipeline functions directly (SURFACE-02) | ✓ VERIFIED | Read `api/app.py:1683-1909`; live TestClient calls confirm 404 for unknown project on spec-create (WR-01 fix), 422 for unknown lifecycle state (WR-05 fix), 422 for oversized spec field (WR-06 fix); `tests/integration/test_api_project.py` (9 tests) pass |
| 7 | CLI surface: `klake project new/list/show/transition`, `klake dataset spec create/validate` mirror the `domain_app` pattern, no name collisions, clean error handling (SURFACE-01) | ✓ VERIFIED | Read `cli/app.py:1636-1838`; `klake --help` lists `project`/`dataset` groups exactly once each; live check confirms `create_project(name="")` raises `ValueError` (WR-07 fix); `tests/integration/test_project_cli.py` (8 tests) pass |
| 8 | MCP surface: 3 new read-only tools (`project_list`, `project_show`, `spec_validate`), `TOOLS` count bumped to exactly 14, no mutating tools shipped (SURFACE-03/D-05) | ✓ VERIFIED | Live import: `len(TOOLS) == 14`, `len({t.name for t in TOOLS}) == 14`, `registered_tools(readonly=True)` returns exactly 7 names including the 3 new ones; `tests/unit/test_tool_registry.py`, `tests/integration/test_mcp_http.py`, `tests/unit/test_readonly.py` all pass |
| 9 | All 7 code-review warnings (WR-01..WR-07) are fixed and landed on HEAD without regression | ✓ VERIFIED | All 7 fix commits present in `git log` (a7fd7f2..101c60b); each fix independently re-verified by reading the current source (not the REVIEW-FIX.md narrative) plus 3 live runtime spot-checks (WR-01 404, WR-05 422, WR-06 422); full test suite: 1230 passed, 3 skipped, 6 xfailed, 0 failed |

**Score:** 9/9 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/knowledge_lake/registry/models.py` | `DatasetProject`/`DatasetSpec` classes, `Dataset` FK columns | ✓ VERIFIED | Present, matches migration, wired into `repo.py` |
| `src/knowledge_lake/registry/alembic/versions/0012_dataset_project_and_spec.py` | Migration, revision 0012 | ✓ VERIFIED | Applied to dev Postgres (`alembic current` = `0012 (head)`) |
| `src/knowledge_lake/ids.py` | `dpj`/`dsp` prefixes | ✓ VERIFIED | Present, additive-only |
| `src/knowledge_lake/pipeline/project.py` | Full lifecycle + spec-versioning mechanism | ✓ VERIFIED | 515 lines, all documented functions present and wired |
| `src/knowledge_lake/registry/repo.py` | CRUD + `get_latest_released_dataset_by_name()` | ✓ VERIFIED | All functions present, called by `pipeline/project.py`/`pipeline/export.py` |
| `src/knowledge_lake/pipeline/export.py` | One-line internal resolution swap | ✓ VERIFIED | Only line 587 changed; 4 call sites unchanged |
| `src/knowledge_lake/api/schemas.py` | 6 project/spec schemas + 3 MCP-only input models | ✓ VERIFIED | All 9 classes present with WR-04/05/06 fixes applied |
| `src/knowledge_lake/api/app.py` | 5 new routes | ✓ VERIFIED | All present, call `pipeline.project.*` directly, correct status-code mapping |
| `docs/openapi.json` | Regenerated with new routes | ✓ VERIFIED | Contains `/projects`, `/projects/{project_id}`, `/projects/{project_id}/specs`, `/projects/{project_id}/transition`, `/specs/{spec_id}/validate` |
| `src/knowledge_lake/cli/app.py` | `project_app`/`dataset_app`/`spec_app` | ✓ VERIFIED | Present, no name collisions with existing groups |
| `src/knowledge_lake/agent/registry.py` | 3 new `ToolDef` entries, `TOOLS` count 14 | ✓ VERIFIED | Live-confirmed 14 total, 7 read-only |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `DatasetProject.status` | `pipeline/project.py::transition_project()` | Read/written | ✓ WIRED | Direct ORM read/write confirmed |
| `DatasetSpec.content_hash`/`parent_spec_id` | `create_spec_version()` | Written | ✓ WIRED | Confirmed in `create_spec_version()` body |
| `Dataset.dataset_project_id` (nullable) | `get_latest_released_dataset_by_name()` | Read | ✓ WIRED | Confirmed join condition, legacy fallback path |
| `api/app.py` routes | `pipeline.project.*` functions | Deferred import inside handler | ✓ WIRED | Confirmed for all 5 routes — zero business logic in handlers |
| `cli/app.py` `project_app`/`dataset_app` | `pipeline.project.*` functions | Deferred import | ✓ WIRED | Confirmed for all 6 commands |
| `agent/registry.py` handlers | `pipeline.project.list_projects/get_project/validate_spec` | Thin shim | ✓ WIRED | Confirmed one-line-body shims |
| `api/schemas.py` `ProjectListInput`/`ProjectShowInput`/`SpecValidateInput` | `agent/registry.py` | Import | ✓ WIRED | Confirmed imported and used to build `ToolDef` entries |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Empty project name rejected (WR-07) | `create_project(name="", dataset_type="rag_eval")` | Raised `ValueError: Dataset Project name must not be empty` | ✓ PASS |
| Unknown project → 404 on spec create (WR-01) | `POST /projects/dpj_does_not_exist/specs` | `404 {"detail": "Dataset Project not found: 'dpj_does_not_exist'"}` | ✓ PASS |
| Unknown lifecycle state → 422 (WR-05) | `POST /projects/{id}/transition {"to_state":"bogus_state"}` | `422 {"detail": "Unknown lifecycle state: 'bogus_state'"}` | ✓ PASS |
| Oversized spec field rejected (WR-06) | `POST /projects/{id}/specs` with 5000-char `purpose` | `422` (Pydantic `string_too_long`) | ✓ PASS |
| 11-state lifecycle graph, no dead ends but `archived` | `LIFECYCLE_STATES` import | 11 states, `archived` only terminal state | ✓ PASS |
| MCP tool count exactly 14, 7 read-only | `TOOLS`/`registered_tools(readonly=True)` import | 14 total, 7 read-only incl. 3 new | ✓ PASS |
| Migration applied to real Postgres | `alembic current` | `0012 (head)` | ✓ PASS |
| `klake --help` no name collisions | CLI invocation | `project`/`dataset` each listed once | ✓ PASS |
| Full test suite | `uv run pytest -q` (run once) | `1230 passed, 3 skipped, 6 xfailed, 0 failed` | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| PROJ-01 | 23-01, 23-02 | Create Dataset Project | ✓ SATISFIED | `create_project()`, CLI/API routes, MCP `project_list`/`project_show` |
| PROJ-02 | 23-02, 23-04 | 11-state guarded lifecycle | ✓ SATISFIED | `_TRANSITIONS`/`transition_project()`/`IllegalProjectTransitionError` |
| PROJ-03 | 23-05, 23-06 | List/show/transition via CLI + API | ✓ SATISFIED | `klake project new/list/show/transition`, matching API routes |
| SPEC-01 | 23-03, 23-06 | Declarative Dataset Specification | ✓ SATISFIED | `DatasetSpecFields` covers full SPEC-01 field list |
| SPEC-02 | 23-01, 23-03, 23-04 | Immutable versioned spec w/ content hash | ✓ SATISFIED | Insert-only table, `_spec_content_hash()`, parent chain |
| SPEC-03 | 23-03, 23-05, 23-06 | `klake dataset spec validate` | ✓ SATISFIED | `validate_spec()`, CLI command, `POST /specs/{id}/validate` |
| SURFACE-01 | 23-06 | New CLI groups mirror `domain_app` pattern | ✓ SATISFIED | `project_app`/`dataset_app`/`spec_app` structurally identical pattern |
| SURFACE-02 | 23-05 | Routes reuse schemas, call pipeline functions | ✓ SATISFIED | Confirmed zero duplicated business logic in route handlers |
| SURFACE-03 | 23-07 | Thin MCP shims, read tools prioritized, count assertion updated | ✓ SATISFIED | 3 read-only shims, `assert len(TOOLS) == 14` |

No orphaned requirements — all 9 IDs mapped to Phase 23 in REQUIREMENTS.md appear in at least one plan's `requirements:` frontmatter.

### Anti-Patterns Found

None. Scanned all 9 modified source files (`models.py`, `repo.py`, `project.py`, `export.py`, `schemas.py`, `app.py`, `cli/app.py`, `agent/registry.py`, `ids.py`) for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER`/"not yet implemented" — zero matches.

### Human Verification Required

None. This phase is entirely backend/CLI/API/MCP surface work with deterministic, database-verifiable behavior — no visual, real-time, or external-service-dependent truths.

### Gaps Summary

No gaps. All 9 must-have truths (aggregated across the 7 plans' frontmatter) are verified against the live codebase and a live Postgres instance, not merely against SUMMARY.md claims. The 7 code-review warnings (WR-01..WR-07) found in `23-REVIEW.md` were confirmed fixed on HEAD by direct source reading plus 3 independent runtime spot-checks (not by trusting `23-REVIEW-FIX.md`'s narrative). The full test suite passes clean (1230 passed, 0 failed) when run once at the end of this verification.

---

_Verified: 2026-07-21T11:38:27Z_
_Verifier: Claude (gsd-verifier)_
