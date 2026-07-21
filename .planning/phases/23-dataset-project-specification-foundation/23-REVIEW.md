---
phase: 23-dataset-project-specification-foundation
reviewed: 2026-07-21T00:00:00Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - docs/openapi.json
  - src/knowledge_lake/agent/registry.py
  - src/knowledge_lake/api/app.py
  - src/knowledge_lake/api/schemas.py
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/ids.py
  - src/knowledge_lake/pipeline/export.py
  - src/knowledge_lake/pipeline/project.py
  - src/knowledge_lake/registry/alembic/versions/0012_dataset_project_and_spec.py
  - src/knowledge_lake/registry/models.py
  - src/knowledge_lake/registry/repo.py
  - tests/integration/test_api_project.py
  - tests/integration/test_export_project_resolution.py
  - tests/integration/test_mcp_http.py
  - tests/integration/test_project_cli.py
  - tests/unit/test_export.py
  - tests/unit/test_project.py
  - tests/unit/test_readonly.py
  - tests/unit/test_surface_parity.py
  - tests/unit/test_tool_registry.py
findings:
  critical: 0
  warning: 7
  info: 1
  total: 8
status: issues_found
---

# Phase 23: Code Review Report

**Reviewed:** 2026-07-21T00:00:00Z
**Depth:** standard
**Files Reviewed:** 19 (source) — plus supporting tests/spec for cross-reference
**Status:** issues_found

## Summary

Reviewed the Dataset Project / Dataset Specification foundation (`pipeline/project.py`, its registry models/repo layer, migration 0012, and the API/CLI/MCP surfaces built on top). The core lifecycle guard (`_TRANSITIONS`), content-hash-based spec versioning, and the `DatasetSpecFields` allow-list are all sound and match their own docstrings and the accompanying unit tests. The Alembic migration matches the ORM model column-for-column (no drift found).

The defects found are all in the surface-layer glue (API status codes, CLI error handling, schema field parity) rather than in the core lifecycle/versioning logic itself — none is a security vulnerability or data-loss risk, but several produce incorrect HTTP semantics or unhandled crashes on realistic bad input, and are unguarded by any existing test in this phase's test files.

## Warnings

### WR-01: POST /projects/{id}/specs returns 422 instead of 404 for an unknown project

**File:** `src/knowledge_lake/api/app.py:1837-1855` (endpoint), `src/knowledge_lake/pipeline/project.py:373-406` (source of the ambiguity)

**Issue:** `pipeline.project.create_spec_version()` raises a plain `ValueError` for two entirely different failure modes: (1) the incoming spec dict fails `DatasetSpecFields` validation, and (2) `project_id` does not resolve to any `DatasetProject` row (`raise ValueError(f"Dataset Project not found: {project_id!r}")` at line 387). `create_spec_version_endpoint` catches only `ValueError` and always maps it to `422` (api/app.py:1850-1852). Every sibling endpoint in this same file (`get_project_endpoint`, `transition_project_endpoint`) distinguishes "not found" (404) from "bad input" (422/409). A client calling `POST /projects/dpj_does_not_exist/specs` with an otherwise-perfectly-valid spec body gets `422 Validation Error`-shaped semantics for what is actually a missing resource. This is confirmed by `docs/openapi.json`'s generated spec for this route (lines 3189-3240), which — correctly reflecting the code — declares no `404` response at all, unlike `/projects/{project_id}` and `/projects/{project_id}/transition`, which both document `404`. No test in `tests/integration/test_api_project.py` exercises this path.

**Fix:** Give `create_spec_version()` a distinct exception for "project not found" (or re-check project existence in the endpoint before calling it) so the endpoint can map it to 404, mirroring `get_project_endpoint`/`transition_project_endpoint`:
```python
try:
    result = create_spec_version(project_id, body.spec, author=body.author)
except ProjectNotFoundError as exc:
    raise HTTPException(status_code=404, detail=str(exc)) from exc
except ValueError as exc:
    raise HTTPException(status_code=422, detail=str(exc)) from exc
```

### WR-02: `get_latest_spec()` silently returns None for a nonexistent project, leaving a dead `except ValueError` in the CLI

**File:** `src/knowledge_lake/pipeline/project.py:409-425`, `src/knowledge_lake/cli/app.py:1805-1820`

**Issue:** Unlike every other project-scoped function in this module (`get_project`, `transition_project`, `create_spec_version`), `get_latest_spec()` never checks whether `project_id` resolves to a real `DatasetProject` row — it only queries `dataset_specs` and returns `None` on zero matches (line 422-425). Its own docstring documents this ("Returns: ... None if the project has zero spec versions"), but `cmd_spec_validate` in the CLI wraps the call in `except ValueError as exc: ...` (cli/app.py:1812-1816) expecting the same not-found signalling every other project function in this module uses. That except clause is unreachable dead code, and the practical effect is that `klake dataset spec validate dpj_totally_bogus_id` prints the same message as a real project with zero specs ("Error: no spec version exists for project ...") instead of a "project not found" error — misleading operators debugging a typo'd ID. Not covered by `tests/integration/test_project_cli.py` (only the "zero specs on a real project" case is tested).

**Fix:** Either have `get_latest_spec()` raise `ValueError` for a genuinely missing project (consistent with its siblings), or drop the dead `except ValueError` block in `cmd_spec_validate` and phrase the "no spec version exists" message to explicitly cover both cases.

### WR-03: `klake dataset spec create` crashes with an unhandled TypeError on an empty/non-mapping YAML spec file

**File:** `src/knowledge_lake/cli/app.py:1770-1802`, `src/knowledge_lake/pipeline/project.py:376-380`

**Issue:** `cmd_spec_create` only catches `(yaml.YAMLError, OSError)` around `yaml.safe_load()` (cli/app.py:1786-1789). An empty YAML file (or one containing just a scalar/list, e.g. `- a`) parses successfully to `None` (or a list/str) with no exception raised. That value is then passed straight into `create_spec_version(project_id, spec_dict, author=author)`, which does `DatasetSpecFields(**spec)` (pipeline/project.py:378) — `**None` (or `**a_list`) raises a bare `TypeError: argument after ** must be a mapping, not NoneType`, which is neither a `ValidationError` (so `create_spec_version`'s own `except ValidationError` at line 379 doesn't catch it) nor a `ValueError` (so the CLI's `except ValueError` at line 1795 doesn't catch it either). The result is a raw Python traceback surfaced to the CLI user instead of the clean `typer.Exit(code=1)` error path every other failure mode in this command uses. Not covered by any test in `tests/integration/test_project_cli.py`.

**Fix:** Validate the parsed YAML is a `dict` before calling `create_spec_version()`, and/or broaden `create_spec_version()`'s guard to catch non-mapping input explicitly:
```python
spec_dict = yaml.safe_load(spec_path.read_text())
if not isinstance(spec_dict, dict):
    typer.echo(f"Error: {spec_path} did not parse to a mapping (got {type(spec_dict).__name__})", err=True)
    raise typer.Exit(code=1)
```

### WR-04: `ProjectOut` silently drops `created_at`/`updated_at` that `get_project()` returns

**File:** `src/knowledge_lake/api/schemas.py:908-920`, `src/knowledge_lake/pipeline/project.py:222-253`

**Issue:** `pipeline.project.get_project()`'s docstring and implementation explicitly return `created_at`/`updated_at` (project.py:222-253), and `get_project_endpoint` calls it directly per the file's own "D-02 compliance: no behavior re-implemented" convention (app.py:1750-1768). But `ProjectOut` (api/schemas.py:908-920) declares no `created_at`/`updated_at` fields, and since it uses Pydantic's default (`extra` not set to `"forbid"`), `ProjectOut(**result)` silently discards those two keys rather than erroring. `GET /projects/{project_id}` can therefore never surface a project's creation/update timestamps over the API, even though `get_project()` computes them and the MCP `project_show` tool (which returns the raw dict, not through `ProjectOut`) does surface them — an inconsistency between the two "same pipeline function" surfaces this phase explicitly designed to keep in parity (D-02). Confirmed in `docs/openapi.json`'s generated `ProjectOut` schema (lines 1292-1365), which lists no `created_at`/`updated_at` properties.

**Fix:** Add `created_at: str` / `updated_at: str` to `ProjectOut` (mirroring `SpecVersionOut.created_at`'s `.isoformat()` string convention already used elsewhere in this file).

### WR-05: `ProjectTransitionRequest`'s state-name regex duplicates `_TRANSITIONS`'s keys as a second source of truth

**File:** `src/knowledge_lake/api/schemas.py:923-930`, `src/knowledge_lake/pipeline/project.py:114-127`

**Issue:** `ProjectTransitionRequest.to_state` validates against a hardcoded regex enumerating all 11 lifecycle state names (`^(draft|configured|sources_pending|ready|processing|validating|review_required|releasable|released|failed|archived)$`). `pipeline.project._TRANSITIONS` is the actual single source of truth for the state set. If a future change adds, removes, or renames a state in `_TRANSITIONS` without updating this regex in lockstep, the API will reject a legal state name with `422` before the request ever reaches `transition_project()`'s own guard — a silent drift risk with no test enforcing the two stay in sync.

**Fix:** Derive the pattern from `_TRANSITIONS` at import time (or validate `to_state` against `set(_TRANSITIONS)` in the endpoint instead of a hand-maintained regex), so there is exactly one place the state set is enumerated.

### WR-06: `DatasetSpecFields` and `SpecVersionCreate.spec` place no size bound on any field, unlike the equivalent `ProjectCreate` fields

**File:** `src/knowledge_lake/pipeline/project.py:47-112`, `src/knowledge_lake/api/schemas.py:933-948`

**Issue:** `ProjectCreate.purpose`/`description` are capped (`max_length=4000`), and `ProjectCreate.domain` is capped (`max_length=100`) — consistent with this codebase's stated ASVS V5 input-validation convention used throughout `api/schemas.py`. `DatasetSpecFields.purpose`/`dataset_type`/`domain` (the equivalent free-text fields for a Dataset Specification, reachable via `POST /projects/{id}/specs`'s untyped `spec: dict` body) have no length bound at all, nor does `SpecVersionCreate.spec` itself cap payload size. An arbitrarily large `purpose` string (or `generation_strategy`/`validation_requirements`/etc. dict) can be stored via this endpoint with no server-side limit, unlike every other free-text field this phase introduces.

**Fix:** Add reasonable `max_length` bounds to `DatasetSpecFields`'s string fields (mirroring `ProjectCreate`'s), and/or cap the overall serialized size of `spec` in `SpecVersionCreate`.

### WR-07: `klake project new ""` bypasses the API's `min_length=1` name validation

**File:** `src/knowledge_lake/cli/app.py:1644-1687`, `src/knowledge_lake/api/schemas.py:895-905`

**Issue:** `ProjectCreate.name` enforces `min_length=1` at the API boundary (schemas.py:898). `cmd_project_new`'s `name` argument (cli/app.py:1646) is a bare `typer.Argument(..., help=...)` with no equivalent length check, and `create_project()` itself (pipeline/project.py:154-219) performs no validation on `name` beyond the DB's `uq_dataset_projects_name` uniqueness constraint. `klake project new "" --dataset-type rag_eval` therefore successfully creates a Dataset Project with an empty-string name — a state the API surface explicitly rejects for the same underlying function. This is an input-validation gap unique to the CLI surface for an otherwise API/CLI-parity-focused phase.

**Fix:** Add a CLI-side `callback=`/manual check rejecting an empty/whitespace-only `name`, or move minimal validation (`min_length=1`) into `create_project()` itself so both surfaces share the same guarantee.

## Info

### IN-01: API/CLI default `intended_uses`/`prohibited_uses`/`owners` to `[]`, pipeline-level default is `None`

**File:** `src/knowledge_lake/api/schemas.py:895-905`, `src/knowledge_lake/cli/app.py:1659-1667`, `src/knowledge_lake/pipeline/project.py:154-165`

**Issue:** `ProjectCreate` and the CLI's `typer.Option([], ...)` both default these three fields to `[]`, while calling `create_project()` directly (as `tests/unit/test_project.py::test_create_project_optional_fields_omitted` does) leaves them `None`. This means "field never specified" is indistinguishable from "field explicitly set to empty" for every project created through the API or CLI — `NULL` vs `[]` is a real DB-level distinction (`DatasetProject.intended_uses: Mapped[list | None]`) that only the direct pipeline-function call path can ever produce.

**Fix:** Not a functional bug, but worth a one-line note in `create_project()`'s docstring that API/CLI callers will never observe the `None` branch in practice — or normalize `[]` to `None` for these three fields the same way `description`/`purpose` already treat "not provided" as `None`.

---

_Reviewed: 2026-07-21T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
