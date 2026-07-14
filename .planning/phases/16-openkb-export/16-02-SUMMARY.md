---
phase: 16-openkb-export
plan: "02"
subsystem: cli-api
tags: [wiki, cli, api, export, kb-05]
status: complete

dependency_graph:
  requires:
    - "16-01 (compile_wiki() pipeline entry point)"
    - "api/schemas.py ExportRequest/ExportResponse pattern"
    - "cli/app.py cmd_export pattern"
    - "api/app.py export_endpoint pattern"
  provides:
    - "CLI: klake export-wiki --domain X --force --dry-run --archive"
    - "API: POST /export-wiki with WikiExportRequest/WikiExportResponse"
    - "api/schemas.py: WikiExportRequest, WikiExportResponse"
    - "tests/unit/test_wiki.py: TestCliExportWiki (5 tests), TestApiExportWiki (3 tests)"
  affects:
    - "src/knowledge_lake/api/app.py (wiki_export_endpoint added)"
    - "src/knowledge_lake/api/schemas.py (WikiExportRequest, WikiExportResponse added)"
    - "src/knowledge_lake/cli/app.py (cmd_export_wiki added)"
    - "docs/openapi.json (regenerated with /export-wiki endpoint)"

tech_stack:
  added: []
  patterns:
    - "Lazy import pattern: compile_wiki imported inside endpoint/command body (consistent with export_endpoint)"
    - "ValueError-to-422 mapping (API): HTTPException(status_code=422) matching export_endpoint pattern"
    - "Typer.Exit(code=1) on ValueError (CLI): consistent with cmd_export pattern"
    - "Domain validation: min_length=1, max_length=100 at Pydantic boundary (T-16-06)"

key_files:
  created: []
  modified:
    - "src/knowledge_lake/api/schemas.py"
    - "src/knowledge_lake/cli/app.py"
    - "src/knowledge_lake/api/app.py"
    - "tests/unit/test_wiki.py"
    - "docs/openapi.json"

decisions:
  - "Lazy import compile_wiki inside endpoint/command body — consistent with existing export patterns; avoids circular imports at module load time"
  - "domain validated at Pydantic boundary (min_length=1, max_length=100); no additional slugify in endpoint since compile_wiki already sanitises via slugify()"
  - "docs/openapi.json regenerated as Rule 2 fix (test_openapi_export.py determinism gate required up-to-date file)"

metrics:
  duration: "~5m"
  completed: "2026-07-14"
  tasks_completed: 2
  files_changed: 5
---

# Phase 16 Plan 02: Wiki CLI and API Surface Summary

Wiki compilation pipeline wired to CLI (`klake export-wiki`) and API (`POST /export-wiki`) surfaces, delivering KB-05 and completing Phase 16 scope.

## What Was Built

### Task 1: WikiExportRequest/Response schemas + CLI and API endpoints

**`src/knowledge_lake/api/schemas.py`** — added two Pydantic models after `ExportResponse`:

- `WikiExportRequest`: `domain` (str, min_length=1, max_length=100, required) and `force` (bool, default False)
- `WikiExportResponse`: `pages_created`, `pages_updated`, `pages_unchanged`, `concept_pages` (int), `manifest_uri` (str), `archive_uri` (str | None)

**`src/knowledge_lake/cli/app.py`** — added `cmd_export_wiki` command:

- `@app.command(name="export-wiki")`
- Options: `--domain/-d` (required str), `--force/-f` (bool), `--dry-run` (bool), `--archive` (bool)
- Body: lazy import `compile_wiki`; prints result fields; catches `ValueError/LookupError` → exit 1
- Archive URI only printed if present in result

**`src/knowledge_lake/api/app.py`** — added `wiki_export_endpoint`:

- `@app.post("/export-wiki", response_model=WikiExportResponse, tags=["export"])`
- Imports `WikiExportRequest, WikiExportResponse` from `.schemas`
- Calls `compile_wiki(domain=body.domain, force=body.force)` via lazy import
- `ValueError` raised as `HTTPException(status_code=422)`
- Structured log on entry and completion

### Task 2: CLI and API surface tests

**`tests/unit/test_wiki.py`** — added two test classes:

`TestCliExportWiki` (5 tests):
- `test_cli_export_wiki_success` — exit 0, output contains `pages_created` and `manifest_uri`
- `test_cli_export_wiki_force` — `--force` passes `force=True` to `compile_wiki`
- `test_cli_export_wiki_dry_run` — `--dry-run` passes `dry_run=True` to `compile_wiki`
- `test_cli_export_wiki_error` — `ValueError` from `compile_wiki` → exit 1, `Error:` in output
- `test_cli_export_wiki_archive_uri_shown` — `archive_uri` in output when present

`TestApiExportWiki` (3 tests):
- `test_api_export_wiki_success` — 200 response with all `WikiExportResponse` fields
- `test_api_export_wiki_force` — `force=True` forwarded to `compile_wiki`
- `test_api_export_wiki_error` — `ValueError` from `compile_wiki` → 422

Patch target: `knowledge_lake.pipeline.wiki.compile_wiki` (the actual module path, matching lazy import resolution).

**`docs/openapi.json`** — regenerated to include `/export-wiki` endpoint schema (Rule 2 fix: `test_openapi_export.py` determinism gate requires the committed file to be byte-identical to a fresh dump).

## Verification

```
tests/unit/test_wiki.py  41 passed in 2.20s
tests/unit/ (full)       651 passed, 5 xfailed, 35 xpassed in 36.55s
```

CLI verification:
```
$ klake export-wiki --help        # shows --domain, --force, --dry-run, --archive
$ python -c "from knowledge_lake.api.app import app; routes = [r.path for r in app.routes]; assert '/export-wiki' in routes; print('OK')"
OK
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Regenerated docs/openapi.json**
- **Found during:** Task 2 verification (`uv run python -m pytest tests/unit/ -x -q`)
- **Issue:** `test_openapi_export.py::test_openapi_json_matches_deterministic_dump` failed because the committed `docs/openapi.json` did not include the new `/export-wiki` endpoint. This is a pre-existing determinism gate.
- **Fix:** Ran `klake openapi` to regenerate `docs/openapi.json` with the new endpoint.
- **Files modified:** `docs/openapi.json`
- **Commit:** 39355a6

**2. [Rule 1 - Bug] Fixed `CliRunner(mix_stderr=False)` incompatibility**
- **Found during:** First test run of `TestCliExportWiki.test_cli_export_wiki_error`
- **Issue:** Typer's `CliRunner` does not accept `mix_stderr` kwarg (unlike Click's); raised `TypeError`.
- **Fix:** Changed to `CliRunner()` (default) and checked `result.output` instead of `result.stderr`.
- **Files modified:** `tests/unit/test_wiki.py`
- **Commit:** 39355a6

## Security Mitigations Applied

| Threat ID | Status | Implementation |
|-----------|--------|----------------|
| T-16-06 | Mitigated | WikiExportRequest.domain: min_length=1, max_length=100 Pydantic validation; slugify() in wiki.py further sanitises before S3 key construction |
| T-16-07 | Mitigated | CLI --domain option validated by Typer as plain string; compile_wiki validates via domain_seg which uses only slugified chars |
| T-16-08 | Accepted | Operator-triggered batch operation; FastAPI default timeout applies; IDF threshold bounds concept page count |

T-16-02 (deferred from Plan 01) resolved: domain validation is now applied at CLI/API boundary via Pydantic min/max length and Typer type system.

## Self-Check: PASSED

- [x] `src/knowledge_lake/api/schemas.py` has WikiExportRequest and WikiExportResponse
- [x] `src/knowledge_lake/cli/app.py` has @app.command(name="export-wiki") on cmd_export_wiki
- [x] `src/knowledge_lake/api/app.py` has @app.post("/export-wiki") on wiki_export_endpoint
- [x] `tests/unit/test_wiki.py` has TestCliExportWiki (5 tests) and TestApiExportWiki (3 tests)
- [x] `docs/openapi.json` includes /export-wiki route
- [x] All 41 test_wiki.py tests pass
- [x] Full 651-test suite passes
- [x] Commits: ad9bc03 (Task 1), 39355a6 (Task 2)
