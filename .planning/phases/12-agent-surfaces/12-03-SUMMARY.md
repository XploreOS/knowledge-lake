---
phase: 12-agent-surfaces
plan: "03"
subsystem: api/schemas
tags: [pydantic, input-models, search-params, mcp, d-02, skill-03]
status: complete
requires: [12-01, 12-02]
provides: [SearchParams-extended, StatsInput, ProcessCrawledInput, ListSourcesInput, LineageInput, IngestUrlInput, CrawlAllInput]
affects: [agent/registry.py, agent/server.py, api/app.py, cli/app.py]
tech_stack:
  added: []
  patterns: [pydantic-v2-field, model-dump-unpack, tdd-red-green]
key_files:
  modified:
    - src/knowledge_lake/api/schemas.py
    - tests/unit/test_input_models.py
decisions:
  - "SearchParams extended (not replaced) to share one model between GET /search and the MCP search tool — q maps to query positional arg, handler must pass search(query=params.q, **rest)"
  - "IngestUrlInput uses source_name (not source_id) — source_id is an output of ingest_url(), not an input"
  - "CrawlAllInput exposes only domain (not settings) — settings is internal infrastructure not exposed via tool interface"
  - "SSRF/URL-scheme guard kept in ingest_url() service function, not duplicated in IngestUrlInput (DRY, plan prohibition)"
metrics:
  duration: "11m"
  completed: "2026-07-11"
  tasks: 2
  files_modified: 2
---

# Phase 12 Plan 03: Input Model Pydantic Layer Summary

**One-liner:** Extended SearchParams with all 7 search() filter kwargs and added 6 new input models (StatsInput, ProcessCrawledInput, ListSourcesInput, LineageInput, IngestUrlInput, CrawlAllInput) field-aligned to pipeline service functions.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Extend SearchParams to cover all search() filters | c063dc5 | schemas.py |
| 2 | Add input models for tools without an existing request schema | 31f39d4 | schemas.py, tests/unit/test_input_models.py |

## What Was Built

### Task 1: SearchParams Extension

`SearchParams` was missing 7 filter fields that `search()` accepts (Pitfall 4). Extended with:

- `domain: Optional[str]` — payload filter: restrict results to a domain
- `document_type: Optional[str]` — payload filter: restrict by document type
- `min_quality_score: Optional[float]` — bounded [0.0, 1.0] with ge/le validation
- `source_name: Optional[str]` — payload filter: restrict by source name
- `format: Optional[str]` — payload filter: restrict by source format (noqa A003 — shadows builtin)
- `tags: Optional[list[str]]` — payload filter: tags list (MatchValue/MatchAny per D-11)
- `source_id: Optional[str]` — payload filter: restrict by source registry ID

Handler note documented in docstring: `q` maps to the `query` positional arg of `search()` — callers pass `search(query=params.q, **rest)`.

### Task 2: New Input Models

Six new `BaseModel` classes added to `api/schemas.py`, all field-aligned to their target pipeline function kwargs:

| Model | Target Function | Key Fields |
|-------|----------------|------------|
| `StatsInput` | `pipeline.query.stats()` | collection, domain |
| `ProcessCrawledInput` | `pipeline.process.process_crawled()` | source_id, limit, collection |
| `ListSourcesInput` | `pipeline.query.list_sources()` | domain, limit, offset |
| `LineageInput` | `lineage.resolve_ancestry()` | artifact_id (required) |
| `IngestUrlInput` | `pipeline.ingest.ingest_url()` | url, source_name, mime_type, license_type, robots_checked |
| `CrawlAllInput` | `pipeline.crawl.crawl_all_sources()` | domain |

Existing schemas reused (not duplicated — D-01/D-02):
- `CrawlJobCreate` for the `crawl` tool
- `SourceCreate` for the `add_source` tool
- `ExportRequest` for the `export` tool
- `DomainLoadRequest` for the `init_domain` tool

## Verification

```
uv run python -c "from knowledge_lake.api.schemas import SearchParams; f=set(SearchParams.model_fields); need={'domain','document_type','min_quality_score','source_name','format','tags','source_id'}; assert need<=f, need-f; print('ok')"
# → ok

uv run pytest tests/unit/test_input_models.py -q
# → 9 passed, 1 xpassed in 0.60s

uv run pytest tests/unit -q
# → 458 passed, 11 skipped, 28 xfailed, 39 xpassed, 2 warnings
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Wave 0 test scaffold used wrong field name for IngestUrlInput**
- **Found during:** Task 2 — test `test_ingest_url_input_has_url_and_source_id` failed
- **Issue:** Scaffold asserted `source_id` field but `ingest_url()` signature takes `source_name` (a human-readable label). `source_id` is an *output* of `ingest_url()`, not an input.
- **Fix:** Renamed test to `test_ingest_url_input_has_url_and_source_name`, updated assertion. `IngestUrlInput` correctly has `source_name`.
- **Files modified:** `tests/unit/test_input_models.py`
- **Commit:** 31f39d4

## Known Stubs

None — all models are complete Pydantic definitions with full field coverage.

## Threat Flags

No new network endpoints, auth paths, or schema changes at trust boundaries introduced.
T-12-07 (Pydantic validation of tool args) is implemented: all models use Pydantic v2 field validators.
T-12-06 (init_domain input guard) is satisfied by DomainLoadRequest reuse (pattern `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$`).

## Self-Check: PASSED

- `src/knowledge_lake/api/schemas.py` — modified with 7 SearchParams filter fields + 6 new models
- `tests/unit/test_input_models.py` — updated test name to match actual signature
- Commits c063dc5 and 31f39d4 both present in git log
- All 458 unit tests pass, 0 regressions
