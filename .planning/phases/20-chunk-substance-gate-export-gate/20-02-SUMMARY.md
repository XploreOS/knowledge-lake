---
phase: 20-chunk-substance-gate-export-gate
plan: 02
subsystem: pipeline
tags: [domain-loader, chunk, quality-gate, dagster, cli, healthcare-pack]

# Dependency graph
requires:
  - phase: 20-chunk-substance-gate-export-gate
    provides: "20-01: chunk()'s domain_filters keyword parameter, ChunkQualitySettings, _apply_substance_gate() composite substance gate"
provides:
  - "chunk_document (Dagster asset) resolving settings.domain.domain_name via DomainLoader.from_name(...).filters and threading it into chunk(domain_filters=...)"
  - "process_crawled() (CLI/API/MCP shared entry point) resolving the same DomainLoader.filters once per call and threading it into every chunk() call"
  - "domains/healthcare/filters.yaml cardinality_constraint pattern, closing MEAS-02's 5th and final fixture-category gap"
affects: [20-03 (export_rag_corpus substance_passed filter can now assume domain_filters was actually applied in production), 20-04 (must-not-reject.yaml cardinality_constraint fixtures now have a real allowlist match)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Mirrored enrich_document's existing DomainLoader guard shape (assets.py) at a second call site (chunk_document) — same settings.domain.domain_name truthy-check, same function-local DomainLoader import, only the attribute consumed differs (.filters vs .render_prompt(...))"
    - "process_crawled() resolves domain_filters ONCE outside the per-document loop (settings.domain.domain_name is call-invariant), then threads the same resolved value into every chunk() call inside the loop"

key-files:
  created: []
  modified:
    - src/knowledge_lake/dagster_defs/assets.py
    - src/knowledge_lake/pipeline/process.py
    - domains/healthcare/filters.yaml
    - tests/unit/test_process_crawled_clean.py

key-decisions:
  - "process.py resolves domain_filters via a function-local `from knowledge_lake.config.settings import get_settings` import (matching the file's existing local-import convention for parse/clean/chunk/embed/index) rather than accepting a settings parameter — process_crawled()'s public signature (source_id, limit, collection) stays unchanged per the plan's acceptance criteria"
  - "New test class patches knowledge_lake.config.settings.get_settings (the SOURCE module process_crawled's local import reads from) and knowledge_lake.domains.loader.DomainLoader.from_name — mirrors this file's established parse/clean/chunk/embed/index interception pattern rather than patching knowledge_lake.pipeline.process's own namespace"

patterns-established: []

requirements-completed: [QUAL-03, MEAS-02]

coverage:
  - id: D1
    description: "chunk_document (Dagster asset) resolves settings.domain.domain_name via DomainLoader.from_name(...).filters and passes domain_filters=domain_filters into chunk(), mirroring enrich_document's existing guard"
    requirement: "QUAL-03"
    verification:
      - kind: unit
        ref: "AST-based verify command in 20-02-PLAN.md Task 1 (DomainLoader + domain_filters=domain_filters present in chunk_document's body) — ran directly, OK"
        status: pass
      - kind: unit
        ref: "tests/unit/test_asset_ordering.py, tests/unit/test_dagster_retry_policies.py, tests/unit/test_tree_index_asset.py (chunk_document signature/ordering unchanged)"
        status: pass
    human_judgment: false
  - id: D2
    description: "process_crawled() resolves domain_filters once (outside the per-document loop) via the same DomainLoader.from_name(...).filters pattern and threads it into every chunk() call; None when no domain pack configured, with no DomainLoader call"
    requirement: "QUAL-03"
    verification:
      - kind: unit
        ref: "tests/unit/test_process_crawled_clean.py::TestProcessCrawledDomainFilters::test_domain_filters_resolved_and_threaded_when_domain_configured"
        status: pass
      - kind: unit
        ref: "tests/unit/test_process_crawled_clean.py::TestProcessCrawledDomainFilters::test_domain_filters_none_when_no_domain_configured"
        status: pass
      - kind: unit
        ref: "tests/unit/test_process_crawled_clean.py (all 7 tests, existing 5 + new 2)"
        status: pass
    human_judgment: false
  - id: D3
    description: "domains/healthcare/filters.yaml gains a 7th normative_allowlists entry (\\d+\\s*(?:of|/)\\s*\\d+) protecting the cardinality_constraint MEAS-02 fixture category; ReDoS-safe (no nested quantifiers); DomainFilters schema still validates"
    requirement: "MEAS-02"
    verification:
      - kind: unit
        ref: "Plan-specified verify script: DomainFilters.model_validate against filters.yaml, len==7, re.search matches 'Meets 2 of 4 SIRS criteria' — ran directly, OK"
        status: pass
      - kind: unit
        ref: "tests/unit/test_domain_loader.py, tests/unit/test_clean.py (46 tests, no schema/count regression)"
        status: pass
    human_judgment: false

duration: 6min
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 02: Domain Filters Production Wiring Summary

**Wires `DomainLoader.from_name(settings.domain.domain_name).filters` into both `chunk_document` (Dagster) and `process_crawled()` (CLI/API/MCP), and adds a cardinality-constraint pattern to the healthcare pack's `filters.yaml`, making Plan 20-01's substance-gate domain allowlist exemption actually active in every production pipeline run instead of only at the unit-test level.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-17T03:01:58Z
- **Completed:** 2026-07-17T03:08:20Z
- **Tasks:** 3 completed
- **Files modified:** 4 (assets.py, process.py, filters.yaml, test_process_crawled_clean.py)

## Accomplishments
- `chunk_document` (Dagster asset) resolves `domain_filters` via `DomainLoader.from_name(settings.domain.domain_name).filters` — exact mirror of `enrich_document`'s existing guard at lines 452-455, substituting `.filters` for `.render_prompt("enrich.j2")`
- `process_crawled()` (the CLI/API/MCP-shared entry point) resolves `domain_filters` **once**, before the per-document loop, using a function-local `get_settings()` import matching the file's existing local-import style — closes RESEARCH.md Pitfall 1's explicitly-flagged gap: a unit-level predicate test alone does not prove the production pipeline protects clinical codes
- Both entry points' `chunk(...)` calls now pass `domain_filters=domain_filters`; when `settings.domain.domain_name` is falsy, `domain_filters` stays `None` and `chunk()` behaves exactly as before (no regression for domain-less sources)
- `domains/healthcare/filters.yaml`'s `normative_allowlists` grows 6→7 entries with `\d+\s*(?:of|/)\s*\d+`, covering the last of MEAS-02's 5 fixture categories (icd_code, dosage, loinc, hipaa_ref, cardinality_constraint) — matches "2 of 4 SIRS criteria" and "2/4 SIRS criteria" via `re.search`, linear-time/ReDoS-safe
- New `TestProcessCrawledDomainFilters` test class (2 tests) proves the CLI path's wiring against the REAL `process_crawled()` function, not a predicate-level mock

## Task Commits

Each task was committed atomically:

1. **Task 1: Resolve domain_filters in chunk_document and process_crawled** - `85a2acf` (feat)
2. **Task 2: Add domain_filters wiring test for process_crawled()** - `a36055d` (test)
3. **Task 3: Extend healthcare filters.yaml with cardinality-constraint pattern** - `ec541ce` (feat)

_Note: no TDD tasks in this plan (tdd not specified in frontmatter) — each task is a single atomic commit._

## Files Created/Modified
- `src/knowledge_lake/dagster_defs/assets.py` - `chunk_document` resolves and threads `domain_filters`; description string updated to mention the new resolution
- `src/knowledge_lake/pipeline/process.py` - `process_crawled()` resolves `domain_filters` once via `get_settings()` before the loop, threads it into every `chunk()` call; module docstring updated
- `domains/healthcare/filters.yaml` - new 7th `normative_allowlists` entry (cardinality-constraint pattern); the 6 existing entries are byte-identical and unreordered
- `tests/unit/test_process_crawled_clean.py` - new `TestProcessCrawledDomainFilters` class with 2 tests; existing `TestProcessCrawledCleanWiring`/`TestProcessCrawledCleanBoundaries` classes untouched

## Decisions Made
- `process.py` resolves `domain_filters` via a function-local `from knowledge_lake.config.settings import get_settings` import, matching the file's existing local-import convention for `parse`/`clean`/`chunk`/`embed`/`index`, rather than adding a `settings` parameter to `process_crawled()`'s public signature — keeps `source_id`/`limit`/`collection` unchanged per the plan's acceptance criteria.
- The new test class patches `knowledge_lake.config.settings.get_settings` (the SOURCE module the local import reads from) and `knowledge_lake.domains.loader.DomainLoader.from_name`, mirroring this file's established interception pattern (patch the source module, not `knowledge_lake.pipeline.process`'s own namespace, since it never carries these names as module attributes).

## Deviations from Plan

None — plan executed exactly as written. All acceptance criteria and verify commands from the plan ran unmodified and passed.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `chunk_document` and `process_crawled()` both resolve and thread `domain_filters` in production — Plan 20-01's substance-gate domain allowlist exemption (QUAL-03) is now genuinely active end-to-end, not just at the predicate/unit level.
- `domains/healthcare/filters.yaml` protects all 5 MEAS-02 fixture categories (icd_code, dosage, loinc, hipaa_ref, cardinality_constraint) — Plan 20-04's must-not-reject.yaml CI fixtures now have a real allowlist match for every category.
- Full test suite verified green after all 3 tasks: 1079 passed, 3 skipped, 6 xfailed, 0 failed (no regressions).
- No known gaps for Plan 20-03 (export_rag_corpus substance_passed filter) — that plan can proceed assuming domain_filters is genuinely wired in production, not just theoretically available.

---
*Phase: 20-chunk-substance-gate-export-gate*
*Completed: 2026-07-17*

## Self-Check: PASSED
