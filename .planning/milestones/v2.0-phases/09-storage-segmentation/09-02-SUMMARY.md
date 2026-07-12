---
phase: 09-storage-segmentation
plan: "02"
subsystem: testing
tags: [pytest, xfail, s3, storage, silver, gold, tdd, parse, clean, export]

requires:
  - phase: 09-storage-segmentation
    plan: "01"
    provides: Wave 0 TDD scaffold pattern, engine/_patch_engine/session/source fixture conventions

provides:
  - RED-state unit tests for STORE-01 domain-scoped silver key in parse.py (2 tests)
  - RED-state unit tests for STORE-01 domain-scoped silver key in clean.py (2 tests)
  - RED-state unit tests for STORE-03 gold zone domain keys in export.py (4 tests)
  - TestParseSilverKeyDomain in test_parse_silver_key.py (2 xfail tests)
  - TestCleanSilverKeyDomain in test_clean_silver_key.py (2 xfail tests)
  - TestGoldZoneDomainKey, TestGoldZoneUnclassified, TestGoldZonePretrain, TestGoldZoneFinetune in test_export.py (4 xfail tests)

affects:
  - 09-04 (Plan that turns silver key RED tests GREEN: parse.py and clean.py domain resolution)
  - 09-06 (Plan that turns gold key RED tests GREEN: export.py domain kwarg addition)

tech-stack:
  added: []
  patterns:
    - "Wave 0 TDD scaffold: xfail(strict=False) stubs allow RED tests before production changes"
    - "StorageBackend patch-at-module-level: patch.object(parse_module, 'StorageBackend', return_value=mock) to intercept all put_object calls without real S3 client"
    - "parse_with_fallback patch: avoid heavy ML imports in parse stage tests"
    - "Local fixture duplication: each test module defines its own engine/session fixtures — not imported from another module"

key-files:
  created:
    - tests/unit/test_parse_silver_key.py
    - tests/unit/test_clean_silver_key.py
  modified:
    - tests/unit/test_export.py

key-decisions:
  - "Patched StorageBackend at the parse/clean module level (patch.object(module, 'StorageBackend', ...)) rather than boto3.client — cleaner interception for key capture without real S3 setup"
  - "Patched parse_with_fallback in test_parse_silver_key.py to avoid importing docling/heavy ML dependencies"
  - "TestGoldZone* tests call export functions with domain= kwarg (not yet on signatures) — TypeError causes xfail naturally, per PATTERNS.md Pitfall 2"
  - "All 4 gold zone classes are additive — no existing test_export.py classes or fixtures modified"

requirements-completed:
  - STORE-01
  - STORE-03

coverage:
  - id: D1
    description: "2 RED-state unit tests for parse.py domain-scoped silver key construction (STORE-01)"
    requirement: STORE-01
    verification:
      - kind: unit
        ref: "tests/unit/test_parse_silver_key.py::TestParseSilverKeyDomain"
        status: xfail
    human_judgment: false
  - id: D2
    description: "2 RED-state unit tests for clean.py domain-scoped silver key construction (STORE-01)"
    requirement: STORE-01
    verification:
      - kind: unit
        ref: "tests/unit/test_clean_silver_key.py::TestCleanSilverKeyDomain"
        status: xfail
    human_judgment: false
  - id: D3
    description: "4 RED-state unit tests for export.py gold zone domain-scoped key construction (STORE-03)"
    requirement: STORE-03
    verification:
      - kind: unit
        ref: "tests/unit/test_export.py::TestGoldZone*"
        status: xfail
    human_judgment: false

duration: ~15min
completed: 2026-07-09
status: complete
---

# Phase 9 Plan 02: Storage Segmentation Wave 0 Pipeline Stage Test Scaffold Summary

**Wave 0 RED-state test scaffold for domain-scoped silver keys (STORE-01 parse/clean stages) and gold zone domain keys (STORE-03 export stage): 4 new xfail tests across 2 new files + 4 new xfail classes in test_export.py.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-07-09T11:10:00Z
- **Completed:** 2026-07-09T13:53:00Z
- **Tasks:** 3
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments

- Created `test_parse_silver_key.py` with 2 xfail tests: domain segment in silver key and `_unclassified` fallback for no-domain source — patches `StorageBackend` at module level and `parse_with_fallback` to avoid heavy ML imports
- Created `test_clean_silver_key.py` with 2 xfail tests: domain segment in cleaned silver key and `_unclassified` fallback — mirrors parse test structure, patches `StorageBackend` to capture put_object key
- Appended 4 new `TestGoldZone*` classes to `test_export.py`: domain-scoped RAG corpus, `_unclassified` RAG corpus, pretrain corpus, and finetune dataset keys — all xfail due to missing `domain` kwarg on export functions (PATTERNS.md Pitfall 2)
- Full unit suite (366 tests) passes with 0 failures — new tests show as XFAIL as expected

## Task Commits

1. **Task 1: test_parse_silver_key.py — STORE-01 parse silver key RED tests** - `80ef06d` (test)
2. **Task 2: test_clean_silver_key.py — STORE-01 clean silver key RED tests** - `ba406ba` (test)
3. **Task 3: TestGoldZone* classes in test_export.py — STORE-03 gold key RED tests** - `fbbbdfb` (test)

## Files Created/Modified

- `/root/healthlake/tests/unit/test_parse_silver_key.py` — Class: TestParseSilverKeyDomain (2 xfail tests); patches StorageBackend + parse_with_fallback
- `/root/healthlake/tests/unit/test_clean_silver_key.py` — Class: TestCleanSilverKeyDomain (2 xfail tests); patches StorageBackend
- `/root/healthlake/tests/unit/test_export.py` — New classes: TestGoldZoneDomainKey (1), TestGoldZoneUnclassified (1), TestGoldZonePretrain (1), TestGoldZoneFinetune (1); 4 xfail tests appended; 9 existing tests unmodified

## Decisions Made

- Patched `StorageBackend` at the pipeline module level (not `boto3.client`) — `parse_module.StorageBackend` provides the cleanest intercept point that captures all `put_object` calls including the key argument
- Patched `parse_with_fallback` in parse stage tests to return a fake `ParsedDoc` — avoids importing docling/heavy ML model loading during unit tests
- Gold zone tests pass `domain=` as a kwarg that doesn't exist yet → TypeError → natural xfail (no assert needed to fail the test)
- `TestGoldZoneUnclassified` uses `domain=None` (explicit None, per CONTEXT.md D-13: if `domain=None`, use `_unclassified`)
- Followed local fixture duplication convention (engine/session per module, not imported)

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Known Stubs

None — all test files are Wave 0 contract stubs for not-yet-implemented production code changes. All tests are explicitly marked `xfail(strict=False)`.

## Threat Flags

None — this plan creates and modifies only test files. No new network endpoints, auth paths, or production S3 calls introduced.

## Next Phase Readiness

- Wave 0 test contracts established for STORE-01 (silver keys: parse/clean stages) and STORE-03 (gold keys: all three export functions)
- Plan 09-03 (implementation) will make Plan 09-01's STORE-01/STORE-02 RED tests GREEN by adding `domain`/`tags` to `put_raw`/`put_bronze`/`put_object`
- Plan 09-04 will make this plan's silver key tests GREEN by updating parse.py and clean.py key construction
- Plan 09-06 will make this plan's gold key tests GREEN by adding `domain` kwarg to export functions
- No blockers

## Self-Check: PASSED

- tests/unit/test_parse_silver_key.py: EXISTS, 2 tests collected, both XFAIL
- tests/unit/test_clean_silver_key.py: EXISTS, 2 tests collected, both XFAIL
- tests/unit/test_export.py: TestGoldZoneDomainKey, TestGoldZoneUnclassified, TestGoldZonePretrain, TestGoldZoneFinetune present, all 4 XFAIL, all 9 prior tests still PASSED
- Commits: 80ef06d, ba406ba, fbbbdfb all exist in git log
- Full unit suite: 366 passed, 2 skipped, 16 xfailed, 20 xpassed, 0 failures

---
*Phase: 09-storage-segmentation*
*Completed: 2026-07-09*
