---
phase: 23-dataset-project-specification-foundation
fixed_at: 2026-07-21T11:28:56Z
review_path: .planning/phases/23-dataset-project-specification-foundation/23-REVIEW.md
iteration: 1
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 23: Code Review Fix Report

**Fixed at:** 2026-07-21T11:28:56Z
**Source review:** .planning/phases/23-dataset-project-specification-foundation/23-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 7 (WR-01..WR-07 — `fix_scope: critical_warning`; IN-01 excluded)
- Fixed: 7
- Skipped: 0

## Fixed Issues

### WR-01: POST /projects/{id}/specs returns 422 instead of 404 for an unknown project

**Files modified:** `src/knowledge_lake/pipeline/project.py`, `src/knowledge_lake/api/app.py`
**Commit:** a7fd7f2
**Applied fix:** Added a new `ProjectNotFoundError(ValueError)` exception class to `pipeline/project.py` (a `ValueError` subclass so every existing `except ValueError` catcher elsewhere in the codebase keeps working unchanged). `create_spec_version()` now raises `ProjectNotFoundError` instead of a plain `ValueError` when `project_id` doesn't resolve. `create_spec_version_endpoint` in `api/app.py` now catches `ProjectNotFoundError` before the broader `ValueError` and maps it to `404`, mirroring `get_project_endpoint`/`transition_project_endpoint`. Added a `404` entry to the route's `responses=` dict. Regenerated `docs/openapi.json` (bundled into the WR-04 commit below since that was the next commit to touch the generated file — see note there).

### WR-02: `get_latest_spec()` silently returns None for a nonexistent project, leaving a dead `except ValueError` in the CLI

**Files modified:** `src/knowledge_lake/pipeline/project.py`
**Commit:** 7c3b704
**Applied fix:** `get_latest_spec()` now checks project existence first (consistent with its siblings `get_project()`/`transition_project()`/`create_spec_version()`) and raises `ProjectNotFoundError` (a `ValueError` subclass) if the project doesn't exist. No CLI change was needed — `cmd_spec_validate`'s existing `except ValueError` block (previously dead code) now correctly catches this and prints "Error: Dataset Project not found: ...", distinct from the "no spec version exists for project ..." message shown when the project exists but has zero specs.

### WR-03: `klake dataset spec create` crashes with an unhandled TypeError on an empty/non-mapping YAML spec file

**Files modified:** `src/knowledge_lake/cli/app.py`
**Commit:** 8b3dc8f
**Applied fix:** Added an `isinstance(spec_dict, dict)` check in `cmd_spec_create` immediately after `yaml.safe_load()`, before the parsed value reaches `create_spec_version()`. A non-mapping result (e.g. `None` from an empty file, or a list/scalar from `- a`) now prints a clean `Error: {path} did not parse to a mapping (got {type})` message and exits with code 1, instead of raising a raw, unhandled `TypeError`. Verified interactively: `yaml.safe_load('')` returns `None`, `yaml.safe_load('- a\\n- b')` returns a list — both are now caught before crossing into `create_spec_version()`.

### WR-04: `ProjectOut` silently drops `created_at`/`updated_at` that `get_project()` returns

**Files modified:** `src/knowledge_lake/pipeline/project.py`, `src/knowledge_lake/api/schemas.py`, `docs/openapi.json`
**Commit:** c299799
**Applied fix:** `get_project()` now returns `created_at`/`updated_at` as `.isoformat()` strings (mirroring `_spec_version_to_dict`'s existing convention) rather than raw `datetime.datetime` objects. `ProjectOut` gained `created_at: str | None = None` / `updated_at: str | None = None` fields — made optional (not required `str`) because `create_project()`/`list_projects()`'s return dicts don't include these keys, so `create_project_endpoint`/`list_projects_endpoint`'s `ProjectOut(**result)` calls would otherwise fail with a missing-required-field validation error. Regenerated `docs/openapi.json` via a direct FastAPI `app.openapi()` dump (`klake openapi`'s underlying logic); the diff also picked up WR-01's `404` response addition to the specs-create route, since `openapi.json` hadn't been regenerated since that earlier commit — confirmed the resulting diff contains exactly the two expected changes (new `ProjectOut` fields + WR-01's `404` response) and nothing else.

### WR-05: `ProjectTransitionRequest`'s state-name regex duplicates `_TRANSITIONS`'s keys as a second source of truth

**Files modified:** `src/knowledge_lake/pipeline/project.py`, `src/knowledge_lake/api/schemas.py`, `src/knowledge_lake/api/app.py`, `docs/openapi.json`
**Commit:** de56479
**Applied fix:** Added a public `LIFECYCLE_STATES: frozenset[str] = frozenset(_TRANSITIONS)` constant to `pipeline/project.py`, derived directly from the existing `_TRANSITIONS` adjacency map (avoids reaching into the leading-underscore `_TRANSITIONS` name from another module). Removed the hand-maintained 11-state regex from `ProjectTransitionRequest.to_state` in `api/schemas.py`, replacing it with a plain `min_length=1, max_length=64` bound. `transition_project_endpoint` now validates `body.to_state` against `LIFECYCLE_STATES` before calling `transition_project()`, returning `422` for a totally unknown state name (added to the route's `responses=` dict) while `transition_project()`'s own `_TRANSITIONS`-based guard still handles the "known state, illegal edge" case as `409`. Regenerated `docs/openapi.json`; verified the diff contains exactly the expected changes (dropped `pattern`, added `minLength`/`maxLength`, updated docstrings, new `422` response description) and is valid JSON.

### WR-06: `DatasetSpecFields` and `SpecVersionCreate.spec` place no size bound on any field, unlike the equivalent `ProjectCreate` fields

**Files modified:** `src/knowledge_lake/pipeline/project.py`, `src/knowledge_lake/api/schemas.py`
**Commit:** 84e8eda
**Applied fix:** Added `max_length` bounds to `DatasetSpecFields`'s free-text string fields — `purpose` (4000, mirrors `ProjectCreate.purpose`), `dataset_type` (64, mirrors `ProjectCreate.dataset_type`), `domain` (100, mirrors `ProjectCreate.domain`), and `usage_policy_ref`/`quality_contract_ref`/`curation_engine` (255 each, reasonable bound for ref/id-like fields). Added a `field_validator` to `SpecVersionCreate.spec` in `api/schemas.py` that rejects a payload whose serialized JSON exceeds 1,000,000 bytes, capping the overall untyped `spec: dict` body size at the API boundary before it reaches `DatasetSpecFields` validation. Verified interactively: an over-length `purpose` and an oversized `spec` dict both now raise `ValidationError`; valid payloads still pass. `docs/openapi.json` was checked and found unchanged (a `field_validator` doesn't add JSON Schema-level constraint annotations), so it was not touched in this commit.

### WR-07: `klake project new ""` bypasses the API's `min_length=1` name validation

**Files modified:** `src/knowledge_lake/pipeline/project.py`
**Commit:** 101c60b
**Applied fix:** Chose the review's second suggested option (single source of truth) over a CLI-only patch: added an empty/whitespace-only `name` guard directly to `create_project()` — `if not name or not name.strip(): raise ValueError(...)` — checked before the DB session opens. This closes the gap for both the CLI surface (`klake project new ""`) and any other current/future direct caller of `create_project()`, rather than duplicating the `min_length=1` check separately in the CLI layer. The existing `except ValueError` blocks in both `cmd_project_new` (CLI) and `create_project_endpoint` (API, though API already rejects this via `ProjectCreate.name`'s `min_length=1` before reaching the pipeline function) handle the new error uniformly. Verified interactively: `create_project(name="", ...)` and `create_project(name="   ", ...)` both now raise `ValueError` before any DB interaction.

## Skipped Issues

None — all 7 in-scope findings (WR-01 through WR-07) were fixed. IN-01 was out of scope for this run (`fix_scope: critical_warning` excludes Info-tier findings).

---

_Fixed: 2026-07-21T11:28:56Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
