---
phase: 09-storage-segmentation
plan: "03"
subsystem: storage
tags: [s3, boto3, minio, storage, domain-segmentation, object-tags, worm, tdd]

requires:
  - phase: 09-storage-segmentation
    plan: "01"
    provides: RED-state xfail tests for put_raw/put_bronze domain keys and _format_tags + put_object tags (STORE-01, STORE-02)
  - phase: 09-storage-segmentation
    plan: "02"
    provides: RED-state xfail tests for silver/gold zone domain keys (STORE-01, STORE-03)

provides:
  - _format_tags module-level helper in s3.py (URL-encodes tag dict for S3 Tagging= parameter, 256-char truncation)
  - StorageBackend.put_object gains tags: Optional[dict[str,str]]=None kwarg with inline Tagging= and best-effort ClientError fallback (D-07, D-08, D-10)
  - StorageBackend.put_raw gains domain: Optional[str]=None and tags: Optional[dict[str,str]]=None kwargs; Layer 3 key = raw/{domain_seg}/{source_id}/{hash}.{ext}
  - StorageBackend.put_bronze gains domain: Optional[str]=None and tags: Optional[dict[str,str]]=None kwargs; Layer 3 key = bronze/{domain_seg}/{source_id}/{hash}.{ext}
  - WORM layers 1, 2, 4, 6 unchanged — domain enters only at Layer 3 after dedup check (D-05)
  - test_raw_immutable.py integration assertions updated for _unclassified segment when no domain configured
  - Wave 0 test_format_tags.py, test_put_object_tags.py, test_put_raw_domain.py, TestPutBronzeDomainKey all GREEN (xfail removed)

affects:
  - 09-04 (silver key updates in parse.py/clean.py call into put_object with tags=; domain resolution pattern established here)
  - 09-05 (ingest.py/crawl.py domain resolution and put_raw/put_bronze call-site updates consume new signatures)
  - 09-06 (export.py gold-zone key updates; put_object tags= available)

tech-stack:
  added:
    - urllib.parse (stdlib, for urlencode in _format_tags)
  patterns:
    - "domain_seg = domain or '_unclassified' pattern applied at Layer 3 in put_raw and put_bronze — prevents None/empty S3 key segments"
    - "Best-effort tagging: put_object wraps boto3 call in try/except ClientError; retries tagless when tags cause error (D-10)"
    - "_format_tags module-level function (not static method) — accessible for testing without class instance"
    - "log.warning uses positional %-format string (not keyword kwargs) — standard Python logging.Logger API"

key-files:
  created: []
  modified:
    - src/knowledge_lake/storage/s3.py
    - tests/unit/test_format_tags.py
    - tests/unit/test_put_object_tags.py
    - tests/unit/test_put_raw_domain.py
    - tests/unit/test_put_bronze.py
    - tests/integration/test_raw_immutable.py

key-decisions:
  - "log.warning uses positional format string (not structlog-style kwargs) — standard Python logging.Logger requires %-style positional args; structlog is only used for info/debug"
  - "put_object uses a kwargs dict (not individual method args) to conditionally include Tagging= — cleaner than conditional call branching"
  - "_format_tags placed at module level (not inside class) — importable directly in tests without constructing a StorageBackend"

requirements-completed:
  - STORE-01
  - STORE-02

coverage:
  - id: D1
    description: "_format_tags function produces URL-encoded string for S3 Tagging= parameter with 256-char value truncation (STORE-02)"
    requirement: STORE-02
    verification:
      - kind: unit
        ref: "tests/unit/test_format_tags.py::test_format_tags_produces_urlencode_string"
        status: pass
      - kind: unit
        ref: "tests/unit/test_format_tags.py::test_tag_value_truncated_at_256_chars"
        status: pass
    human_judgment: false
  - id: D2
    description: "put_object passes Tagging= kwarg when tags dict provided; best-effort ClientError fallback retries tagless (STORE-02, D-07, D-08, D-10)"
    requirement: STORE-02
    verification:
      - kind: unit
        ref: "tests/unit/test_put_object_tags.py::TestPutObjectTagging::test_tags_passed_as_tagging_kwarg"
        status: pass
      - kind: unit
        ref: "tests/unit/test_put_object_tags.py::TestTaggingBestEffortFallback::test_clienterror_retries_without_tags"
        status: pass
    human_judgment: false
  - id: D3
    description: "put_raw with domain kwarg produces domain-scoped S3 key raw/{domain}/{source_id}/{hash}.{ext}; domain=None uses _unclassified segment; WORM dedup ordering preserved (STORE-01)"
    requirement: STORE-01
    verification:
      - kind: unit
        ref: "tests/unit/test_put_raw_domain.py::TestPutRawDomainKey::test_domain_segment_in_raw_key"
        status: pass
      - kind: unit
        ref: "tests/unit/test_put_raw_domain.py::TestPutRawDomainKey::test_none_domain_uses_unclassified_segment"
        status: pass
      - kind: unit
        ref: "tests/unit/test_put_raw_domain.py::TestDeduplicationOrderPreserved::test_no_put_object_when_artifact_already_in_registry"
        status: pass
    human_judgment: false
  - id: D4
    description: "put_bronze with domain kwarg produces domain-scoped S3 key bronze/{domain}/{source_id}/{hash}.{ext}; domain=None uses _unclassified segment (STORE-01)"
    requirement: STORE-01
    verification:
      - kind: unit
        ref: "tests/unit/test_put_bronze.py::TestPutBronzeDomainKey::test_domain_segment_in_bronze_key"
        status: pass
      - kind: unit
        ref: "tests/unit/test_put_bronze.py::TestPutBronzeDomainKey::test_none_domain_uses_unclassified_segment"
        status: pass
    human_judgment: false
  - id: D5
    description: "test_raw_immutable.py integration test assertions updated to expect _unclassified segment when source has no domain configured (backward-compatible default)"
    requirement: STORE-01
    verification:
      - kind: unit
        ref: "tests/unit/ — 375 passed, 0 failures"
        status: pass
    human_judgment: false

duration: ~51min
completed: 2026-07-09
status: complete
---

# Phase 9 Plan 03: Storage Layer Foundation — Domain-Scoped Keys and Object Tags Summary

**s3.py storage layer updated with _format_tags helper, inline S3 Tagging= support on put_object (best-effort, D-10), and domain-scoped key construction in put_raw/put_bronze (raw/{domain}/…, bronze/{domain}/…) — all Wave 0 RED tests now GREEN.**

## Performance

- **Duration:** ~51 min
- **Started:** 2026-07-09T14:10:29Z
- **Completed:** 2026-07-09T15:01:09Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- Added `_format_tags(tags: dict[str, str]) -> str` module-level helper using `urllib.parse.urlencode` with `[:256]` value truncation — satisfies S3 Tagging= parameter format (STORE-02)
- Updated `put_object` with `tags: Optional[dict[str, str]] = None` kwarg: builds kwargs dict, conditionally includes `Tagging=_format_tags(tags)`, wraps `_client.put_object` in try/except for best-effort fallback on ClientError (D-10) — object always written, tags are convenience metadata
- Updated `put_raw` and `put_bronze` with `domain: Optional[str] = None` and `tags: Optional[dict[str, str]] = None` kwargs; Layer 3 key construction adds `domain_seg = domain or "_unclassified"` guard; Layer 5 passes `tags=tags` to `put_object`; WORM Layers 1, 2, 4, 6 unchanged
- Removed xfail markers from all Wave 0 RED tests: `test_format_tags.py`, `test_put_object_tags.py`, `test_put_raw_domain.py`, `TestPutBronzeDomainKey` — all 9 tests now PASSED
- Updated `tests/integration/test_raw_immutable.py`: 3 assertion lines and module docstring updated for `_unclassified` segment when source has no domain config

## Task Commits

1. **Task 1: _format_tags + put_object tags + best-effort fallback (STORE-02)** - `72e7bc9` (feat)
2. **Task 2: put_raw and put_bronze domain kwarg + domain-scoped keys (STORE-01)** - `138d6f5` (feat)
3. **Task 3: test_raw_immutable.py key assertions updated for _unclassified (Pitfall 6)** - `5fb6b38` (feat)

## Files Created/Modified

- `/root/healthlake/src/knowledge_lake/storage/s3.py` — Added `import urllib.parse`, `_format_tags` function, `put_object(tags=)` kwarg + best-effort fallback, `put_raw(domain=, tags=)` + Layer 3 domain_seg, `put_bronze(domain=, tags=)` + Layer 3 domain_seg
- `/root/healthlake/tests/unit/test_format_tags.py` — Removed ImportError guard + xfail markers; direct import of `_format_tags`; 2 tests now PASSED
- `/root/healthlake/tests/unit/test_put_object_tags.py` — Removed xfail markers; 2 tests now PASSED
- `/root/healthlake/tests/unit/test_put_raw_domain.py` — Removed xfail markers; 3 tests now PASSED
- `/root/healthlake/tests/unit/test_put_bronze.py` — Removed xfail markers from TestPutBronzeDomainKey; 2 tests now PASSED
- `/root/healthlake/tests/integration/test_raw_immutable.py` — Module docstring + 3 key assertion lines updated to `_unclassified` segment

## Decisions Made

- `log.warning` uses positional `%`-format string — standard Python `logging.Logger` does not accept keyword arguments the way structlog does; this was a Rule 1 auto-fix discovered during Task 1 verification
- `put_object` builds a `kwargs` dict and conditionally adds `Tagging=` to it rather than using `if/else` call branching — more readable and avoids duplicating all other kwargs
- `_format_tags` is a module-level function (not a `@staticmethod` on `StorageBackend`) — consistent with the Claude's Discretion guidance and directly importable in test files without constructing a StorageBackend instance

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed log.warning keyword argument incompatibility with standard Python logging**
- **Found during:** Task 1 (put_object best-effort fallback implementation)
- **Issue:** `log.warning("...", key=key, hint="tagging failed")` raises `TypeError: Logger._log() got an unexpected keyword argument 'key'` — Python's stdlib `logging.Logger` does not accept keyword arguments in `warning()` calls. Structlog does, but the `log` object in s3.py is a stdlib logger (`logging.getLogger(__name__)`)
- **Fix:** Changed to `log.warning("put_object: tagging failed, retrying without tags (key=%s)", key)` using positional %-format string
- **Files modified:** `src/knowledge_lake/storage/s3.py`
- **Verification:** `test_clienterror_retries_without_tags` PASSED after fix
- **Committed in:** `72e7bc9` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug)
**Impact on plan:** Required fix for correctness; no scope creep. The plan's logging line example used structlog-style kwargs but the actual logger is stdlib.

## Issues Encountered

None beyond the log.warning auto-fix above.

## Known Stubs

None — all production code wired. Wave 0 xfail stubs have been removed and tests pass green.

## Threat Flags

None — no new network endpoints, auth paths, or trust boundaries introduced. Changes are additive to existing S3 write path only. Tag value truncation in `_format_tags` addresses T-09-01 (Denial of Service via tag overflow). Best-effort fallback addresses T-09-02 (object always written regardless of tag success).

## Next Phase Readiness

- Plan 09-03 (this plan) is the load-bearing Wave 1 plan — `put_raw`, `put_bronze`, and `put_object` now accept `domain` and `tags` kwargs
- Plan 09-04 can now update `parse.py` and `clean.py` silver key construction using the new `put_object(key, data, tags=tags)` signature — Wave 0 RED tests in `test_parse_silver_key.py` and `test_clean_silver_key.py` are next to turn GREEN
- Plan 09-05 can now update `ingest.py` and `crawl.py` to resolve domain via `get_domain_for_source` and pass to `put_raw`/`put_bronze`
- Plan 09-06 can now update `export.py` gold-zone key construction and `put_object` calls
- No blockers

## Self-Check: PASSED

- `src/knowledge_lake/storage/s3.py`: EXISTS, `_format_tags` defined, `import urllib.parse` present, `tags: Optional` in put_object/put_raw/put_bronze, `domain_seg = domain or` present twice, `Tagging` used 4 times
- `tests/unit/test_format_tags.py`: EXISTS, 2 tests PASSED (no xfail)
- `tests/unit/test_put_object_tags.py`: EXISTS, 2 tests PASSED (no xfail)
- `tests/unit/test_put_raw_domain.py`: EXISTS, 3 tests PASSED (no xfail)
- `tests/unit/test_put_bronze.py::TestPutBronzeDomainKey`: 2 tests PASSED (no xfail)
- `tests/integration/test_raw_immutable.py`: 4 occurrences of `_unclassified`, 0 occurrences of old `raw/{source_id}/` flat format
- Full unit suite: 375 passed, 0 failures
- Commits: 72e7bc9, 138d6f5, 5fb6b38 all exist in git log

---
*Phase: 09-storage-segmentation*
*Completed: 2026-07-09*
