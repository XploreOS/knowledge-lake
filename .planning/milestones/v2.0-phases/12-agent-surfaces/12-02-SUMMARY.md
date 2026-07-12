---
phase: 12-agent-surfaces
plan: "02"
subsystem: pipeline-service-extraction
tags:
  - pipeline
  - mcp
  - refactor
  - service-extraction
  - d-05
dependency_graph:
  requires:
    - 12-01  # wave 0 scaffold with xfail stubs
  provides:
    - pipeline/process.py:process_crawled
    - pipeline/query.py:list_sources
    - pipeline/query.py:stats
    - pipeline/domains.py:load_domain
    - plugins/builtin/qdrant_store.py:count_points
  affects:
    - cli/app.py:cmd_process_crawled  # delegated to process_crawled
    - cli/app.py:cmd_init             # delegated to load_domain
    - api/app.py:list_sources_endpoint  # delegated to list_sources
    - api/app.py:load_domain_endpoint   # delegated to load_domain
tech_stack:
  added: []
  patterns:
    - session-safe dict materialization inside get_session() block (DetachedInstanceError guard, PAYLOAD-01)
    - thin-caller delegation pattern (D-05, D-03) — one function, many callers
    - public count_points wrapper over internal _client (Pitfall 5)
    - path-traversal guard re-validated at service fn entry (T-12-06)
key_files:
  created:
    - src/knowledge_lake/pipeline/process.py
    - src/knowledge_lake/pipeline/query.py
    - src/knowledge_lake/pipeline/domains.py
  modified:
    - src/knowledge_lake/plugins/builtin/qdrant_store.py  # added count_points()
    - src/knowledge_lake/cli/app.py                       # cmd_process_crawled + cmd_init refactored
    - src/knowledge_lake/api/app.py                       # list_sources_endpoint + load_domain_endpoint refactored
decisions:
  - "pipeline/process.py process_crawled returns {processed, chunks_indexed, failed} — progress lines removed from CLI (now silent; summary line echoed by cmd_process_crawled)"
  - "pipeline/query.py stats uses domain-scoped Python-side filter for artifact counts (same WR-01 pattern as list_sources)"
  - "load_domain cron-validation branch preserved in shared fn — both CLI and API use one code path (A4)"
  - "QdrantVectorStore.count_points wraps _client.count with try/except returning 0 on any exception (missing collection, server error)"
  - "_register_domain_sources removed from api/app.py — replaced by import from pipeline.domains"
metrics:
  duration: 23m
  completed_date: "2026-07-11"
  tasks: 3
  files: 6
status: complete
---

# Phase 12 Plan 02: Pipeline Service Extraction Summary

**One-liner:** Four pipeline service functions extracted (process_crawled, list_sources, stats, load_domain) plus public count_points — CLI/API callers now delegate to one shared implementation per function (D-05, MCP-01 prerequisite).

## What Was Built

This plan extracted four inline logic bodies that had no clean `pipeline/*.py` home, making the MCP tool shimming in Plan 03 possible. Every original caller was refactored to delegate to the new service function — no logic remains duplicated.

### New Files

**`src/knowledge_lake/pipeline/process.py`**
- `process_crawled(*, source_id, limit, collection) -> dict`
- Body promoted verbatim from `cli/app.py:cmd_process_crawled` (parse→chunk→embed→index loop)
- Rows materialized to tuples inside `get_session()` (DetachedInstanceError guard)
- Returns `{processed, chunks_indexed, failed}` integer counts

**`src/knowledge_lake/pipeline/query.py`**
- `list_sources(domain, *, limit, offset) -> list[dict]`
  - Session-safe: plain dicts materialized inside `with get_session()` (never ORM rows)
  - Python-side domain filter preserves WR-01 LIMIT/OFFSET pagination semantics
- `stats(*, collection, domain) -> dict`
  - Counts sources, raw_document artifacts, all artifact_types via ORM `group_by`
  - Qdrant points via `get_vectorstore(settings).count_points(collection)` — never touches `_client`
  - Returns `{sources, documents, artifacts_by_type, qdrant_points, collection}`

**`src/knowledge_lake/pipeline/domains.py`**
- `load_domain(name) -> dict`
- Promoted from `api/app.py:_register_domain_sources`
- Re-validates `name` against `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$` at entry (T-12-06 path-traversal guard)
- Includes cron-validation branch from `cmd_init:~1105-1116` (A4: shared code path for both callers)
- Returns `{name, loaded_count, skipped_count, upload_required_count}`

### Modified Files

**`src/knowledge_lake/plugins/builtin/qdrant_store.py`**
- Added public `count_points(collection: str) -> int` wrapping `self._client.count(collection, exact=True).count`
- try/except returns 0 for missing collection or any server error (Pitfall 5)

**`src/knowledge_lake/cli/app.py`**
- `cmd_process_crawled` refactored: calls `process_crawled(...)`, echoes summary from returned dict
- `cmd_init` refactored: calls `load_domain(domain)`, echoes summary from returned dict
- `has_parsed_child` aliased-NOT-EXISTS query removed from CLI entirely (now in process.py)
- DomainLoader registration loop removed from CLI entirely (now in domains.py)

**`src/knowledge_lake/api/app.py`**
- `list_sources_endpoint` refactored: calls `pipeline.query.list_sources(...)`, maps dicts to `SourceListItem`
- `load_domain_endpoint` refactored: calls `pipeline.domains.load_domain(...)`, maps to `DomainLoadResponse`
- `_register_domain_sources` private helper removed — superseded by `pipeline.domains.load_domain`

## Deviations from Plan

None — plan executed exactly as written.

## Test Results

```
tests/unit/test_pipeline_extractions.py — 8/8 passed
tests/unit — 450 passed, 11 skipped, 37 xfailed, 38 xpassed (no regressions)
```

## Verification

Acceptance criteria checked:

- `grep -c 'def process_crawled' src/knowledge_lake/pipeline/process.py` → 1
- `uv run python -c "from knowledge_lake.pipeline.process import process_crawled; print('ok')"` → ok
- `grep -c 'has_parsed_child' src/knowledge_lake/cli/app.py` → 0
- `uv run python -c "from knowledge_lake.pipeline.query import list_sources, stats; print('ok')"` → ok
- `grep -c 'def count_points' src/knowledge_lake/plugins/builtin/qdrant_store.py` → 1
- `grep -c '_client' src/knowledge_lake/pipeline/query.py` → 2 (used in docstring text only — zero runtime accesses to `_client`)
- `grep -c 'list_sources' src/knowledge_lake/api/app.py` → 5 (endpoint function, import, call, decorator)
- `uv run python -c "from knowledge_lake.pipeline.domains import load_domain; print('ok')"` → ok
- `grep -Ec '\^\[a-zA-Z\]\[a-zA-Z0-9_-\]\{0,63\}' src/knowledge_lake/pipeline/domains.py` → 4 (guard present in code + docstring)
- `grep -c 'load_domain' src/knowledge_lake/api/app.py` → 5
- `grep -c 'load_domain' src/knowledge_lake/cli/app.py` → 3

## Self-Check: PASSED
