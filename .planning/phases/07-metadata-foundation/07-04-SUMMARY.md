---
phase: 07-metadata-foundation
plan: "04"
subsystem: api-cli-surface
status: complete
tags:
  - payload
  - search
  - api
  - cli
  - filter
dependency_graph:
  requires:
    - "07-02"   # Source scalar extraction in index.py (PAYLOAD-01 — fields now in payload)
    - "07-03"   # search() filter kwargs (source_name, format, source_id, tags)
  provides:
    - SearchHit 7 new provenance fields exposed via GET /search JSON
    - GET /search accepts source_name, format, source_id, tags Query params
    - klake search CLI accepts --source-name, --format, --source-id, --tag (repeatable)
  affects:
    - src/knowledge_lake/api/schemas.py
    - src/knowledge_lake/api/app.py
    - src/knowledge_lake/cli/app.py
tech_stack:
  added: []
  patterns:
    - Pydantic Field(default=None / default_factory=list) on SearchHit for optional provenance fields
    - FastAPI Query(max_length=64) on tags per-element for DoS mitigation (T-07-04-01)
    - typer.Option list[str] with repeatable --tag flag (singular CLI convention per D-12)
    - tag → tags kwarg mapping at CLI→search() boundary
key_files:
  created: []
  modified:
    - src/knowledge_lake/api/schemas.py
    - src/knowledge_lake/api/app.py
    - src/knowledge_lake/cli/app.py
decisions:
  - "D-12: --tag (singular, repeatable) chosen over --tags (plural with comma-parsing) for CLI convention — typer list[str] handles repeated flags natively"
  - "D-13 backward-compat note added to both search_endpoint docstring and cmd_search docstring"
  - "tags Query param uses max_length=64 per-element (T-07-04-01) — existing top_k [1,100] bound prevents result-set explosion"
  - "format kwarg shadows Python builtin in search() and app.py but is accepted — builtin not used in function scope"
metrics:
  duration: "3 minutes"
  completed: "2026-07-08"
  tasks: 2
  files: 3
---

# Phase 07 Plan 04: API and CLI Surface (PAYLOAD-02) Summary

Delivers the user-facing surface of PAYLOAD-01 and PAYLOAD-02: 7 new provenance fields on SearchHit, 4 new filter params on GET /search, and 4 new filter flags on `klake search`.

## What Was Built

**Task 1: Extend SearchHit schema and search endpoint** (commit d8b5d92)

Extended `SearchHit` in `schemas.py` with 7 new optional fields after `quality_score`:
- `source_id: Optional[str]` — registry source ID (src_...)
- `source_name: Optional[str]` — human-readable source name
- `source_url: Optional[str]` — canonical source URL
- `format: Optional[str]` — source format label (html/pdf/csv from Source.source_type)
- `tags: list[str]` — curated source tags from Source.config
- `title: Optional[str]` — document title from enrichment metadata
- `organization: Optional[str]` — publishing organization from Source.config

Updated `search_endpoint()` in `app.py`:
- 4 new Query params: `source_name`, `format`, `source_id`, `tags` (with `max_length=64` per-element on `tags` for T-07-04-01)
- All 4 new params passed through to `search()` call
- All 7 new fields extracted from `hit.payload` in the SearchHit constructor
- D-13 backward-compat note in docstring
- Updated `logger.info` to include the 4 new filter kwargs

**Task 2: Extend CLI search command** (commit 334e83d)

Extended `cmd_search()` in `cli/app.py`:
- 4 new `typer.Option` flags: `--source-name`, `--format`, `--source-id`, `--tag` (repeatable)
- `tag: Optional[list[str]]` parameter named singular per D-12 convention; passed as `tags=tag` to `search()`
- Per-hit rendering block extended with 6 new lines: source_name, source_id, format, tags, organization, title
- Docstring updated with new filter flags and D-13 backward-compat note

## Verification Results

- `uv run pytest tests/unit/ -q` — 339 passed, 20 xpassed (all green)
- `uv run pytest tests/ -q -m "not integration"` — 514 passed, 1 skipped, 21 deselected (all green)
- `SearchHit.model_fields` contains all 7 new fields: source_id, source_name, source_url, format, tags, title, organization
- `klake search --help` shows all 4 new flags: --source-name, --format, --source-id, --tag

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes beyond what the plan's threat model covers. T-07-04-01 (tags DoS) mitigated via `max_length=64` on Query param. T-07-04-02, T-07-04-03, T-07-04-04 accepted per plan disposition.

## Self-Check: PASSED

- `/root/healthlake/src/knowledge_lake/api/schemas.py` — FOUND (modified)
- `/root/healthlake/src/knowledge_lake/api/app.py` — FOUND (modified)
- `/root/healthlake/src/knowledge_lake/cli/app.py` — FOUND (modified)
- Commit d8b5d92 — FOUND
- Commit 334e83d — FOUND
