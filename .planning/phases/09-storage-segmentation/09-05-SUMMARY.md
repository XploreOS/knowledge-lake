---
phase: 09-storage-segmentation
plan: "05"
subsystem: pipeline
tags: [pipeline, raw-zone, bronze-zone, domain-segmentation, object-tags, s3, ingest, crawl, tdd]

requires:
  - phase: 09-storage-segmentation
    plan: "03"
    provides: put_raw/put_bronze domain= and tags= kwargs, _format_tags helper, domain-scoped key construction
  - phase: 09-storage-segmentation
    plan: "04"
    provides: domain resolution pattern via get_domain_for_source + get_source inside session block (parse.py/clean.py)

provides:
  - ingest.py ingest_url(): domain resolved via get_domain_for_source(session, source.id) inside session block; tags dict passed to put_raw at line 430 region
  - ingest.py ingest_file(): same domain resolution + tags at second put_raw call site; source_name from function parameter (no extra registry lookup)
  - crawl.py _write_artifacts(): domain + source_name resolved inside with get_session() block; put_raw updated with domain= + tags={raw_document}; put_bronze updated with domain= + tags={bronze_document}
  - All unit tests remain green (379 passed, 0 failures)

affects:
  - 09-06 (export.py gold-zone key updates; same domain resolution pattern applies)

tech-stack:
  added: []
  patterns:
    - "domain = registry_repo.get_domain_for_source(session, source.id) or '_unclassified' — inside session block (Pitfall 3 avoidance)"
    - "source_name from ingest_url/ingest_file function parameter — no extra registry lookup needed"
    - "source_name from get_source(session, source_id).name in crawl.py — mirrors parse.py/clean.py pattern from Plan 04"
    - "put_raw(source_id, data, ext, session, mime_type=..., domain=domain, tags={...}) — additive kwargs, backward-compatible defaults"

key-files:
  created: []
  modified:
    - src/knowledge_lake/pipeline/ingest.py
    - src/knowledge_lake/pipeline/crawl.py

key-decisions:
  - "ingest.py source_name is already a function parameter on both ingest_url() and ingest_file() — no extra registry_repo.get_source() call needed (plan truth: D-11)"
  - "crawl.py _write_artifacts requires get_source(session, source_id) for source_name because _write_artifacts receives source_id (not source_name) as parameter — mirrors parse.py/clean.py pattern from Plan 04"
  - "All domain/source_name resolution inside with get_session() block — avoids DetachedInstanceError (Pitfall 3) and respects D-04 session boundary rules"

requirements-completed:
  - STORE-01
  - STORE-02

coverage:
  - id: D1
    description: "ingest.py ingest_url() resolves domain via get_domain_for_source(session, source.id) inside session block and passes domain= + tags= to put_raw (STORE-01, STORE-02)"
    requirement: STORE-01
    verification:
      - kind: unit
        ref: "tests/unit/ — 379 passed, 0 failures (existing ingest tests continue to pass)"
        status: pass
    human_judgment: false
  - id: D2
    description: "ingest.py ingest_file() resolves domain inside session block and passes domain= + tags= to put_raw at second call site (STORE-01, STORE-02)"
    requirement: STORE-01
    verification:
      - kind: unit
        ref: "tests/unit/ — 379 passed, 0 failures"
        status: pass
    human_judgment: false
  - id: D3
    description: "crawl.py _write_artifacts() resolves domain + source_name inside session block; put_raw receives domain= + tags={artifact_type: raw_document}; put_bronze receives domain= + tags={artifact_type: bronze_document} (STORE-01, STORE-02)"
    requirement: STORE-01
    verification:
      - kind: unit
        ref: "tests/unit/ — 379 passed, 0 failures"
        status: pass
    human_judgment: false

duration: ~6min
completed: 2026-07-09
status: complete
---

# Phase 9 Plan 05: Raw/Bronze Zone Pipeline Callers — Domain-Scoped Keys and Object Tags Summary

**ingest.py and crawl.py updated to resolve domain via get_domain_for_source inside existing session blocks and pass domain + tags to put_raw/put_bronze — raw and bronze artifacts from URL ingestion and web crawling are now domain-segmented.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-07-09T15:59:41Z
- **Completed:** 2026-07-09T16:05:36Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Updated `ingest.py` `ingest_url()`: added `domain = registry_repo.get_domain_for_source(session, source.id) or "_unclassified"` inside the `with get_session()` block immediately before `put_raw`; updated `put_raw` call with `domain=domain` and `tags={"domain": domain, "source_name": source_name, "format": ext, "artifact_type": "raw_document"}` — `source_name` is already a parameter of `ingest_url()`, no extra lookup needed
- Updated `ingest.py` `ingest_file()`: identical domain resolution pattern at the second `put_raw` call site (line 539 region); `source_name` from function parameter again, no registry lookup
- Updated `crawl.py` `_write_artifacts()`: added three resolution lines immediately after `with get_session() as session:` opens — `domain` from `get_domain_for_source`, `source_obj` from `get_source`, `source_name` from `source_obj.name` (fallback: `"unknown"`); updated `put_raw` with `domain=` and `tags={artifact_type: raw_document}`; updated `put_bronze` with `domain=` and `tags={artifact_type: bronze_document}`
- Full unit suite: 379 passed, 5 xfailed, 20 xpassed, 0 failures — all existing ingest and crawl tests continue to pass (additive `domain=None, tags=None` defaults maintain backward compatibility)

## Task Commits

1. **Task 1: ingest.py domain resolution + tags at both put_raw call sites** - `266b291` (feat)
2. **Task 2: crawl.py _write_artifacts domain + source_name resolution + tags on put_raw/put_bronze** - `4e99489` (feat)

## Files Created/Modified

- `/root/healthlake/src/knowledge_lake/pipeline/ingest.py` — Lines 430 and 539 regions: domain resolution added; `put_raw` calls updated with `domain=domain` and `tags=` dict at both call sites
- `/root/healthlake/src/knowledge_lake/pipeline/crawl.py` — `_write_artifacts` function (lines 678-700 region): 3 resolution lines added after session opens; `put_raw` and `put_bronze` calls updated with `domain=` and `tags=`

## Decisions Made

- `ingest_url()` and `ingest_file()` both have `source_name` as a direct function parameter — no `registry_repo.get_source()` lookup is needed; using the parameter directly is more efficient and matches the plan's stated truth
- `crawl.py _write_artifacts()` receives `source_id` (not `source_name`) as its parameter, so `get_source(session, source_id)` lookup is required — mirrors the `parse.py`/`clean.py` pattern from Plan 04
- All resolution inside the `with get_session()` block to prevent `DetachedInstanceError` and satisfy D-04 session boundary requirements (Pitfall 3 from RESEARCH.md)

## Deviations from Plan

None — plan executed exactly as written. Both task actions mapped 1:1 to the plan instructions.

## Issues Encountered

None.

## Known Stubs

None — all production code wired. Both put_raw call sites in ingest.py and both put_raw/put_bronze call sites in crawl.py now receive domain + tags.

## Threat Flags

None — no new network endpoints, auth paths, or trust boundaries introduced. Changes are additive to existing raw/bronze zone write paths. Domain resolution inside session block addresses T-09-03 (Tampering via stale domain resolution). Source name fallback to "unknown" in crawl.py addresses T-09-05 (accepted, low severity). Tag value truncation via `_format_tags` (Plan 03) handles T-09-01.

## Next Phase Readiness

- Plan 09-05 (this plan) is complete — `ingest.py` and `crawl.py` raw/bronze artifacts are now domain-segmented
- Plan 09-06 can now update `export.py` gold-zone key construction using the same `get_domain_for_source` pattern — no blockers

## Self-Check: PASSED

- `src/knowledge_lake/pipeline/ingest.py`: EXISTS; `get_domain_for_source(session` count=2; `domain=domain` count=2; `artifact_type.*raw_document` count=2
- `src/knowledge_lake/pipeline/crawl.py`: EXISTS; `get_domain_for_source(session, source_id)` count=1; `get_source(session, source_id)` count=1; `artifact_type.*raw_document` count=1; `artifact_type.*bronze_document` count=1
- Full unit suite: 379 passed, 0 failures
- Commits: 266b291 and 4e99489 exist in git log

---
*Phase: 09-storage-segmentation*
*Completed: 2026-07-09*
