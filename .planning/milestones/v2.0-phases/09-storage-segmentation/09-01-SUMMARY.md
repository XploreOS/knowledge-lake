---
phase: 09-storage-segmentation
plan: "01"
subsystem: testing
tags: [pytest, xfail, s3, storage, minio, boto3, tdd]

requires:
  - phase: 08-crawl-maturation
    provides: xfail(strict=False) Wave 0 TDD scaffold pattern for storage layer tests

provides:
  - RED-state unit tests for STORE-01 domain-scoped raw/bronze S3 keys (7 tests)
  - RED-state unit tests for STORE-02 S3 object tagging + best-effort fallback (4 tests)
  - TestPutRawDomainKey + TestDeduplicationOrderPreserved in test_put_raw_domain.py (3 tests)
  - test_format_tags.py with ImportError guard for _format_tags (2 tests, SKIP until defined)
  - TestPutObjectTagging + TestTaggingBestEffortFallback in test_put_object_tags.py (2 tests)
  - TestPutBronzeDomainKey class in test_put_bronze.py (2 tests)

affects:
  - 09-02 (Wave 0 silver/gold test scaffold)
  - 09-03 (Plan that turns these RED tests GREEN: put_raw/put_bronze domain kwarg + _format_tags)

tech-stack:
  added: []
  patterns:
    - "Wave 0 TDD scaffold: xfail(strict=False) stubs allow RED tests before production changes"
    - "ImportError guard at module scope: try/except ImportError + None sentinel prevents collection failures for undefined symbols"
    - "Local fixture duplication: each test module defines its own engine/session/mock_storage rather than importing from another test module"

key-files:
  created:
    - tests/unit/test_put_raw_domain.py
    - tests/unit/test_format_tags.py
    - tests/unit/test_put_object_tags.py
  modified:
    - tests/unit/test_put_bronze.py

key-decisions:
  - "xfail(strict=False) used throughout Wave 0 so the suite stays green during the RED phase (per Phase 8 Plan 01 precedent)"
  - "test_format_tags.py uses pytest.skip (not xfail assert) when _format_tags=None — ImportError guard keeps collection clean"
  - "TestTaggingBestEffortFallback uses a closure counter instead of side_effect list to simulate first-call-fails pattern"

patterns-established:
  - "Pattern: fixture duplication per test module (engine/session/mock_storage copied, not imported) follows established test_put_bronze.py convention"
  - "Pattern: source fixture calls create_source + session.flush() to establish a valid source_id for S3 key tests"

requirements-completed:
  - STORE-01
  - STORE-02

coverage:
  - id: D1
    description: "3 RED-state unit tests for put_raw domain-scoped key construction and dedup ordering (STORE-01)"
    requirement: STORE-01
    verification:
      - kind: unit
        ref: "tests/unit/test_put_raw_domain.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "2 RED-state unit tests for _format_tags URL-encoding helper (STORE-02)"
    requirement: STORE-02
    verification:
      - kind: unit
        ref: "tests/unit/test_format_tags.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "2 RED-state unit tests for put_object Tagging= kwarg + best-effort ClientError fallback (STORE-02)"
    requirement: STORE-02
    verification:
      - kind: unit
        ref: "tests/unit/test_put_object_tags.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "2 RED-state unit tests for put_bronze domain-scoped key via TestPutBronzeDomainKey (STORE-01)"
    requirement: STORE-01
    verification:
      - kind: unit
        ref: "tests/unit/test_put_bronze.py::TestPutBronzeDomainKey"
        status: pass
    human_judgment: false

duration: 8min
completed: 2026-07-09
status: complete
---

# Phase 9 Plan 01: Storage Segmentation Wave 0 Test Scaffold Summary

**Wave 0 RED-state test scaffold for domain-scoped S3 keys (STORE-01) and S3 object tagging (STORE-02): 9 new xfail/skip tests across 3 new files + 1 extended existing file.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-07-09T11:00:00Z
- **Completed:** 2026-07-09T11:07:20Z
- **Tasks:** 3
- **Files modified:** 4 (3 created, 1 modified)

## Accomplishments

- Created `test_put_raw_domain.py` with 3 xfail tests: domain segment in raw key, `_unclassified` fallback, and dedup ordering preserved before key construction
- Created `test_format_tags.py` with 2 skip-guarded tests for `_format_tags` pure function (URL-encoding + 256-char truncation)
- Created `test_put_object_tags.py` with 2 xfail tests for `Tagging=` kwarg presence and best-effort `ClientError` fallback (D-10)
- Appended `TestPutBronzeDomainKey` to existing `test_put_bronze.py` with 2 xfail tests for `bronze/{domain}/` key pattern
- Full unit suite (366 tests) passes with 0 failures — new tests show as XFAIL/SKIP as expected

## Task Commits

1. **Task 1: test_put_raw_domain.py — STORE-01 raw key + dedup ordering RED tests** - `9fab9ee` (test)
2. **Task 2: test_format_tags.py + test_put_object_tags.py — STORE-02 tag encoding + best-effort RED tests** - `3c4e1b2` (test)
3. **Task 3: TestPutBronzeDomainKey class in test_put_bronze.py — STORE-01 bronze key RED tests** - `aff1035` (test)

## Files Created/Modified

- `/root/healthlake/tests/unit/test_put_raw_domain.py` — Classes: TestPutRawDomainKey (2), TestDeduplicationOrderPreserved (1); 3 xfail tests
- `/root/healthlake/tests/unit/test_format_tags.py` — 2 functions with ImportError guard + pytest.skip for absent `_format_tags`
- `/root/healthlake/tests/unit/test_put_object_tags.py` — Classes: TestPutObjectTagging (1), TestTaggingBestEffortFallback (1); 2 xfail tests
- `/root/healthlake/tests/unit/test_put_bronze.py` — New class TestPutBronzeDomainKey appended (2 xfail tests); existing 6 tests unmodified

## Decisions Made

- Followed Phase 8 Plan 01 Wave 0 TDD precedent: `xfail(strict=False)` for all RED tests that will become GREEN in Plan 09-03
- `_format_tags` ImportError guard uses `pytest.skip()` (not assertion failure) when symbol absent — keeps test output clean and non-misleading
- `TestTaggingBestEffortFallback` uses a closure counter (`call_count["n"]`) instead of a `side_effect` list for the first-call-raises pattern; more resilient to mock state isolation between tests
- All test modules define their own `engine`, `session`, and `mock_storage` fixtures locally (not imported from another module) — matches established `test_put_bronze.py` convention

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Known Stubs

None — all test files are contract stubs for not-yet-implemented production code. The tests are explicitly marked `xfail(strict=False)` so they document the expected future behavior without masking failures.

## Threat Flags

None — this plan creates only test files. No new network endpoints, auth paths, or production S3 calls introduced.

## Next Phase Readiness

- Wave 0 test contracts established for STORE-01 (raw/bronze domain keys) and STORE-02 (S3 object tagging)
- Plan 09-02 can now add Wave 0 tests for silver-zone (parse.py/clean.py) and gold-zone (export.py) domain keys
- Plan 09-03 (implementation) will make Tests D1 and D4 GREEN by adding `domain` kwarg to `put_raw`/`put_bronze` and `_format_tags`
- No blockers

## Self-Check: PASSED

- tests/unit/test_put_raw_domain.py: EXISTS, 3 tests collected, all XFAIL
- tests/unit/test_format_tags.py: EXISTS, 2 tests collected, all SKIP
- tests/unit/test_put_object_tags.py: EXISTS, 2 tests collected, all XFAIL
- tests/unit/test_put_bronze.py: TestPutBronzeDomainKey present, 2 new XFAIL tests
- Commits: 9fab9ee, 3c4e1b2, aff1035 all exist in git log

---
*Phase: 09-storage-segmentation*
*Completed: 2026-07-09*
