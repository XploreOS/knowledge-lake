---
phase: 07-metadata-foundation
plan: "02"
subsystem: pipeline
tags: [payload, registry, tdd, unit-test, pytest, ingest, index]

requires:
  - phase: 07-metadata-foundation
    plan: "01"
    provides: RED-state test scaffold for ensure_payload_indexes (independent — ran in parallel)

provides:
  - get_source(session, source_id) -> Optional[Source] in repo.py
  - index() payload dict carries 7 new source-metadata fields (PAYLOAD-01)
  - register_source() persists tags and organization into Source.config (D-05)
  - TestPayloadSourceFields with 4 passing GREEN tests in test_index_payload.py

affects:
  - 07-03-PLAN.md (ensure_payload_indexes implementation — independent, not blocked by this plan)
  - 07-04-PLAN.md (search filter extension will use format/source_name/tags/source_id from payload)

tech-stack:
  added: []
  patterns:
    - "get_source() follows exact get_artifact() PK-lookup pattern: session.get(Source, source_id)"
    - "Source scalar values extracted inside session block to avoid DetachedInstanceError"
    - "register_source() config_dict multi-step construction: domain/tags/organization as optional keys"
    - "TestPayloadSourceFields test class: reuses _patch_engine autouse fixture for register_source() isolation"

key-files:
  created: []
  modified:
    - src/knowledge_lake/registry/repo.py
    - src/knowledge_lake/pipeline/index.py
    - src/knowledge_lake/pipeline/ingest.py
    - tests/unit/test_index_payload.py

key-decisions:
  - "Source scalars (name, url, source_type, config) extracted inside the with get_session() block — not after — to prevent DetachedInstanceError on lazy-loaded attributes"
  - "TestPayloadNewFieldsStub (RED scaffold from Task 1 TDD) retained alongside TestPayloadSourceFields for documentation of TDD flow"
  - "test_payload_source_fields_degrade_gracefully_when_no_source asserts source_name returns 'NoMeta' and format returns 'web' — source row exists, only config=None, so name/source_type are still available"

requirements-completed:
  - PAYLOAD-01

coverage:
  - id: D1
    description: "get_source() added to repo.py — returns Optional[Source] via session.get() PK-lookup"
    requirement: PAYLOAD-01
    verification:
      - kind: unit
        ref: "tests/unit/test_index_payload.py::TestPayloadSourceFields (4 tests GREEN)"
        status: pass
    human_judgment: false
  - id: D2
    description: "index() payload dict carries source_id, source_name, source_url, format, tags, title, organization"
    requirement: PAYLOAD-01
    verification:
      - kind: unit
        ref: "tests/unit/test_index_payload.py::TestPayloadSourceFields::test_payload_includes_all_7_new_fields_when_source_has_metadata"
        status: pass
    human_judgment: false
  - id: D3
    description: "All 7 new fields degrade to None/[] when source config absent (D-03)"
    requirement: PAYLOAD-01
    verification:
      - kind: unit
        ref: "tests/unit/test_index_payload.py::TestPayloadSourceFields::test_payload_source_fields_degrade_gracefully_when_no_source"
        status: pass
    human_judgment: false
  - id: D4
    description: "register_source() persists tags and organization into Source.config (D-05)"
    requirement: PAYLOAD-01
    verification:
      - kind: unit
        ref: "tests/unit/test_index_payload.py::TestPayloadSourceFields::test_register_source_persists_tags_into_config"
        status: pass
    human_judgment: false

duration: 4min
completed: 2026-07-08
status: complete
---

# Phase 07 Plan 02: Metadata Foundation — Payload Expansion Summary

**PAYLOAD-01 payload expansion: get_source() added to repo.py, index() payload carries 7 new source-metadata fields, register_source() persists tags/organization into Source.config, 4 new TestPayloadSourceFields tests pass GREEN**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-07-08T07:36:07Z
- **Completed:** 2026-07-08T07:40:30Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added `get_source(session, source_id) -> Optional[Source]` to `repo.py` after `get_domain_for_source()`, following the exact `get_artifact()` PK-lookup pattern
- Extended `index()` session block to fetch the Source row and extract scalar values inside the block (prevents DetachedInstanceError)
- Added 7 new payload keys to the payload dict in `index()`: `source_id`, `source_name`, `source_url`, `format`, `tags`, `title`, `organization` — all degrade gracefully to None/[]
- Fixed `register_source()` config construction: replaced one-liner with multi-step `config_dict` that persists `domain`, `tags`, and `organization` (D-05, backward-compatible)
- Added `TestPayloadSourceFields` to `test_index_payload.py` with 4 tests covering full-metadata path, degradation, title-from-enrichment, and register_source() tags persistence
- Updated `index.py` module docstring to document all 7 new payload fields

## Task Commits

1. **Task 1: Add get_source() and extend index.py payload join** — `79ebab9` (feat)
2. **Task 2: Fix register_source() tags gap and extend test_index_payload.py** — `b0a3f70` (feat)

## Files Created/Modified

- `src/knowledge_lake/registry/repo.py` — `get_source()` added after `get_domain_for_source()` (line ~833)
- `src/knowledge_lake/pipeline/index.py` — module docstring extended; session block extended with Source row lookup; 7 new payload keys added to payload dict
- `src/knowledge_lake/pipeline/ingest.py` — `register_source()` signature adds `tags` and `organization` kwargs; config construction replaced with `config_dict` multi-step build
- `tests/unit/test_index_payload.py` — `TestPayloadNewFieldsStub` (RED scaffold) + `TestPayloadSourceFields` (4 GREEN tests) added; 11 total tests, all passing

## Decisions Made

- Source scalars extracted inside the `with get_session()` block (not after) to prevent `DetachedInstanceError` on lazy-loaded SQLAlchemy attributes — critical fix discovered during Task 1 GREEN implementation
- `TestPayloadNewFieldsStub` RED stub retained as documentation of TDD flow; can be removed in a cleanup pass
- `test_payload_source_fields_degrade_gracefully_when_no_source` uses a source with `config=None` — asserts `source_name`/`format` are still returned (source row exists), while `tags`/`organization`/`title`/`source_url` degrade

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] DetachedInstanceError on SQLAlchemy lazy-loaded attributes**
- **Found during:** Task 1 GREEN — first test run after implementing index.py extension
- **Issue:** Source ORM object was accessed after the `with get_session()` block closed, triggering `DetachedInstanceError` on `source.name`, `source.url`, etc.
- **Fix:** Moved all Source scalar extractions (`source_name`, `source_url`, `fmt`, `tags`, `organization`) inside the `with get_session()` block before it closes
- **Files modified:** `src/knowledge_lake/pipeline/index.py`
- **Commit:** `79ebab9`

## Issues Encountered

None beyond the auto-fixed DetachedInstanceError above.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Plan 03: `ensure_payload_indexes()` implementation — turns RED tests from Plan 01 GREEN (independent of this plan's changes)
- Plan 04: Search filter extension — uses `format`/`source_name`/`tags`/`source_id` payload fields added here

## Known Stubs

None — all 7 payload fields are wired to real Source row data with proper degradation paths.

## Threat Flags

No new trust boundaries introduced. Changes are confined to trusted operator-controlled paths (sources.yaml → register_source → Source.config; registry DB → index() payload → Qdrant). Per T-07-02-01/02/03 in plan threat model: all accepted at low severity.

## Self-Check

- [x] `src/knowledge_lake/registry/repo.py` exists and contains `def get_source`
- [x] `src/knowledge_lake/pipeline/index.py` contains `"source_name"`, `"format"`, `"tags"`, `"title"`, `"organization"` in payload dict
- [x] `src/knowledge_lake/pipeline/ingest.py` contains `tags: Optional[list[str]] = None` and `config_dict` pattern
- [x] `tests/unit/test_index_payload.py` contains `class TestPayloadSourceFields`
- [x] `uv run pytest tests/unit/test_index_payload.py -v` — 11 tests all PASS
- [x] `uv run pytest tests/unit/ -q` — 221 of 222 tests pass (1 is intentional RED scaffold from Plan 01)
- [x] Task 1 commit: `79ebab9`
- [x] Task 2 commit: `b0a3f70`

## Self-Check: PASSED

---
*Phase: 07-metadata-foundation*
*Completed: 2026-07-08*
