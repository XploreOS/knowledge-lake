---
phase: 09-storage-segmentation
plan: "04"
subsystem: pipeline
tags: [pipeline, silver-zone, domain-segmentation, object-tags, s3, parse, clean, tdd]

requires:
  - phase: 09-storage-segmentation
    plan: "03"
    provides: put_object(tags=) kwarg, put_raw/put_bronze domain-scoped keys, _format_tags helper

provides:
  - parse.py silver_key construction moved inside get_session() block; domain segment from get_domain_for_source; tags dict passed to put_object
  - clean.py cleaned_key construction moved inside get_session() block; same domain + tags pattern with /cleaned/ sub-path
  - test_parse_silver_key.py RED xfail tests now GREEN (2 tests PASSED)
  - test_clean_silver_key.py RED xfail tests now GREEN (2 tests PASSED)

affects:
  - 09-05 (ingest.py/crawl.py caller domain resolution uses same get_domain_for_source + get_source pattern)
  - 09-06 (export.py gold-zone key updates; put_object tags= call pattern established)

tech-stack:
  added: []
  patterns:
    - "domain = registry_repo.get_domain_for_source(session, source_id) or '_unclassified' — inside with get_session() block (Pitfall 3 avoidance)"
    - "source_obj = registry_repo.get_source(session, source_id); source_name = source_obj.name if source_obj else 'unknown'"
    - "silver_key = f'{_SILVER_PREFIX}/{domain}/{source_id}/{content_hash}.md' — domain-scoped f-string inside session block"
    - "put_object(key, data, tags={domain, source_name, format, artifact_type}) — tags wired at call site per D-11"

key-files:
  created: []
  modified:
    - src/knowledge_lake/pipeline/parse.py
    - src/knowledge_lake/pipeline/clean.py
    - tests/unit/test_parse_silver_key.py
    - tests/unit/test_clean_silver_key.py

key-decisions:
  - "silver_key and cleaned_key f-strings placed INSIDE with get_session() block so get_domain_for_source has an active session (Pitfall 3 from RESEARCH.md)"
  - "source_name resolved via get_source(session, source_id) within the same session block — single extra read, no separate session boundary"
  - "fallback source_name = 'unknown' when get_source returns None — consistent with T-09-04 accepted risk (information disclosure is low severity)"

requirements-completed:
  - STORE-01
  - STORE-02

coverage:
  - id: D1
    description: "parse.py writes silver artifact at silver/healthcare/{source_id}/{hash}.md when source domain=healthcare (STORE-01)"
    requirement: STORE-01
    verification:
      - kind: unit
        ref: "tests/unit/test_parse_silver_key.py::TestParseSilverKeyDomain::test_domain_segment_in_silver_key"
        status: pass
    human_judgment: false
  - id: D2
    description: "parse.py writes silver artifact at silver/_unclassified/{source_id}/{hash}.md when source has no domain (STORE-01)"
    requirement: STORE-01
    verification:
      - kind: unit
        ref: "tests/unit/test_parse_silver_key.py::TestParseSilverKeyDomain::test_none_domain_uses_unclassified_segment"
        status: pass
    human_judgment: false
  - id: D3
    description: "clean.py writes cleaned artifact at silver/healthcare/{source_id}/cleaned/{hash}.md when source domain=healthcare (STORE-01)"
    requirement: STORE-01
    verification:
      - kind: unit
        ref: "tests/unit/test_clean_silver_key.py::TestCleanSilverKeyDomain::test_domain_segment_in_cleaned_key"
        status: pass
    human_judgment: false
  - id: D4
    description: "clean.py writes cleaned artifact at silver/_unclassified/{source_id}/cleaned/{hash}.md when source has no domain (STORE-01)"
    requirement: STORE-01
    verification:
      - kind: unit
        ref: "tests/unit/test_clean_silver_key.py::TestCleanSilverKeyDomain::test_none_domain_uses_unclassified_segment"
        status: pass
    human_judgment: false

duration: ~20min
completed: 2026-07-09
status: complete
---

# Phase 9 Plan 04: Silver Zone Pipeline Callers — Domain-Scoped Keys and Object Tags Summary

**parse.py and clean.py updated to construct silver keys inside the session block with domain segment from get_domain_for_source and tags passed to put_object — all Wave 0 RED xfail tests now GREEN.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-09T15:29:08Z
- **Completed:** 2026-07-09T15:49:40Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Updated `parse.py`: moved `silver_key` assignment from line 100 (outside session block) to inside the `with get_session() as session:` block; added `get_domain_for_source(session, source_id) or "_unclassified"` domain resolution; added `get_source(session, source_id)` for `source_name`; new key f-string: `silver/{domain}/{source_id}/{hash}.md`; updated `put_object` call with tags dict `{"domain", "source_name", "format": "md", "artifact_type": "parsed_document"}`
- Updated `clean.py`: same three-step edit; removed `cleaned_key` from outside session block (line 300); key now `silver/{domain}/{source_id}/cleaned/{hash}.md`; updated `put_object` with tags dict `{"artifact_type": "cleaned_document"}`; `storage.object_uri(cleaned_key)` call remains valid (inside same session block)
- Removed `@pytest.mark.xfail` decorators from all 4 tests in `test_parse_silver_key.py` and `test_clean_silver_key.py` — all 4 tests now PASSED

## Task Commits

1. **Task 1: parse.py silver_key inside session block with domain scope and tags** - `6d4429a` (feat)
2. **Task 2: clean.py cleaned_key inside session block with domain scope and tags** - `928b188` (feat)

## Files Created/Modified

- `/root/healthlake/src/knowledge_lake/pipeline/parse.py` — Removed pre-session `silver_key` assignment; added domain/source_name resolution + new `silver_key` f-string inside `with get_session()` block; updated `put_object` with `tags=` dict
- `/root/healthlake/src/knowledge_lake/pipeline/clean.py` — Removed pre-session `cleaned_key` assignment; added domain/source_name resolution + new `cleaned_key` f-string inside `with get_session()` block; updated `put_object` with `tags=` dict
- `/root/healthlake/tests/unit/test_parse_silver_key.py` — Removed two `@pytest.mark.xfail` decorators; 2 tests now PASSED
- `/root/healthlake/tests/unit/test_clean_silver_key.py` — Removed two `@pytest.mark.xfail` decorators; 2 tests now PASSED

## Decisions Made

- `silver_key` and `cleaned_key` f-strings are placed INSIDE the `with get_session() as session:` block so that `get_domain_for_source` has an active session — avoids `DetachedInstanceError` (Pitfall 3 from RESEARCH.md)
- `source_name` resolved via `get_source(session, source_id)` within the same session block — single additional read, no extra session context required
- Fallback `source_name = "unknown"` when `get_source` returns `None` — consistent with T-09-04 accepted risk disposition in the threat model

## Deviations from Plan

None — plan executed exactly as written. All edits mapped 1:1 to the three-step instructions in the plan actions.

## Issues Encountered

None.

## Known Stubs

None — all production code wired. Wave 0 xfail stubs removed, tests pass green.

## Threat Flags

None — no new network endpoints, auth paths, or trust boundaries introduced. Changes are additive to existing silver zone write path only. Domain resolution inside the session block addresses T-09-03 (Tampering via session boundary for get_domain_for_source). Source name fallback to "unknown" addresses T-09-04 (accepted, low severity).

## Next Phase Readiness

- Plan 09-04 (this plan) is complete — `parse.py` and `clean.py` silver keys are now domain-scoped
- Plan 09-05 can now update `ingest.py` and `crawl.py` using the same `get_domain_for_source` + `get_source` pattern established here; `put_raw`/`put_bronze` already accept `domain=` and `tags=` kwargs (Plan 03)
- Plan 09-06 can now update `export.py` gold-zone key construction — no blockers

## Self-Check: PASSED

- `src/knowledge_lake/pipeline/parse.py`: EXISTS; `get_domain_for_source(session, source_id)` count=1; `get_source(session, source_id)` count=1; `domain}/{source_id}` in silver_key f-string; `with get_session` at line 112 before `silver_key =` at line 116
- `src/knowledge_lake/pipeline/clean.py`: EXISTS; `get_domain_for_source(session, source_id)` count=1; `get_source(session, source_id)` count=1; `domain}/{source_id}` in cleaned_key f-string; `with get_session` at line 300 before `cleaned_key =` at line 304
- `tests/unit/test_parse_silver_key.py`: EXISTS; 0 xfail markers; 2 tests PASSED
- `tests/unit/test_clean_silver_key.py`: EXISTS; 0 xfail markers; 2 tests PASSED
- Full unit suite: 379 passed, 0 failures
- Commits: 6d4429a and 928b188 exist in git log

---
*Phase: 09-storage-segmentation*
*Completed: 2026-07-09*
