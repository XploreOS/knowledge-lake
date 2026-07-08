---
phase: 08-crawl-maturation
plan: "01"
subsystem: crawl
tags: [test-scaffold, xfail, wave-0, tdd, crawl, enrich, ingest]
dependency_graph:
  requires: []
  provides:
    - tests/unit/test_robots_ratelimit.py (TestAdaptiveRateLimiter, TestResolveDelay phase-8 stubs)
    - tests/unit/test_crawl_all.py
    - tests/unit/test_enrich.py (partial enrichment stubs)
    - tests/unit/test_linked_doc_ingest.py
  affects:
    - plans 08-02 through 08-06 (all implementation plans have test targets)
tech_stack:
  added: []
  patterns:
    - xfail(strict=False) stubs with guarded imports for pre-implementation test contracts
    - try/except ImportError guard on not-yet-defined symbols at module level
key_files:
  created:
    - tests/unit/test_crawl_all.py
    - tests/unit/test_linked_doc_ingest.py
  modified:
    - tests/unit/test_robots_ratelimit.py
    - tests/unit/test_enrich.py
decisions:
  - Used try/except ImportError at module scope for symbols not yet defined (crawl_all_sources, _extract_linked_docs, MAX_LINKED_DOCS_PER_PAGE) to prevent collection failures before Plan 3
  - Created TestResolveDelayPhase8 methods inside existing TestResolveDelay class (not separate class) per plan spec
  - Used pytest.mark.xfail(strict=False) for all stubs so xpassed tests (which pass even in current code) do not break the suite
metrics:
  duration: "5m"
  completed_date: "2026-07-08"
  tasks_completed: 2
  files_changed: 4
status: complete
requirements:
  - CRAWL-01
  - CRAWL-02
  - CRAWL-03
  - ENRICH-07
  - INGEST-10
---

# Phase 08 Plan 01: Wave 0 Test Scaffold Summary

Wave 0 Nyquist test scaffold: xfail stubs covering all 5 Phase 8 requirements (CRAWL-01/02/03, ENRICH-07, INGEST-10) across four test files.

## What Was Built

Four test files updated with failing-but-importable stubs that enforce the Phase 8 contract before any implementation begins. All stubs use `pytest.mark.xfail(strict=False)` so the suite stays green (339 passed, 15 xfailed, 21 xpassed — zero errors).

### Task 1: test_robots_ratelimit.py + test_crawl_all.py (CRAWL-01/02/03)

**test_robots_ratelimit.py extensions:**

- `TestResolveDelay.test_rate_limit_rps_tier1` — asserts `resolve_delay({'rate_limit_rps': 2.0}, None, 1.0)` returns 0.5 (CRAWL-01: rps support)
- `TestResolveDelay.test_backoff_extra_raises_floor` — asserts `resolve_delay({}, None, 1.0, backoff_extra=3.0)` returns >= 4.0 (CRAWL-01: backoff_extra kwarg)
- `TestAdaptiveRateLimiter` class (4 methods):
  - `test_record_error_increments_count` — consecutive_errors['example.com'] == 1 after one record_error
  - `test_reset_errors_clears_count` — consecutive_errors cleared after reset_errors
  - `test_backoff_extra_exponential` — backoff_extra returns min(base * 4, MAX_BACKOFF_SECONDS) after 2 errors
  - `test_backoff_extra_capped` — backoff_extra never exceeds MAX_BACKOFF_SECONDS after N errors

**test_crawl_all.py (new file, 3 async xfail tests):**

- `test_crawl_all_sources_returns_summary` — result dict has keys: total, succeeded, failed, results
- `test_crawl_all_sources_failure_does_not_abort` — one source raises, failed==1, others proceed
- `test_crawl_all_sources_domain_filter` — passing domain='healthcare' passes it to list_sources_for_crawl_all

### Task 2: test_enrich.py + test_linked_doc_ingest.py (ENRICH-07/INGEST-10)

**test_enrich.py extensions (3 new xfail functions):**

- `test_partial_enrichment` — finish_reason='length' → result['is_partial'] is True
- `test_partial_cache_key` — partial enrichment stored with content_hash starting with 'partial:'
- `test_partial_not_returned_as_complete` — partial enrichment does not count as cache hit for subsequent complete call

**test_linked_doc_ingest.py (new file, 4 xfail tests):**

- `test_extract_linked_docs_pdf_only` — only .pdf href returned (not .html)
- `test_extract_linked_docs_docx` — .docx href also returned
- `test_max_linked_docs_cap` — result count <= MAX_LINKED_DOCS_PER_PAGE
- `test_ssrf_blocked_link_counted_as_failed` — SSRF-blocked URLs (169.254.*) excluded from result

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | 2ae7944 | test(08-01): add Wave 0 xfail stubs for CRAWL-01/02/03 |
| Task 2 | e3259ed | test(08-01): add Wave 0 xfail stubs for ENRICH-07 and INGEST-10 |

## Verification Results

```
pytest tests/unit/ -v -x
339 passed, 15 xfailed, 21 xpassed, 17 warnings in 35.99s
```

```
grep -c "TestAdaptiveRateLimiter" tests/unit/test_robots_ratelimit.py
2

grep -c "test_partial_enrichment\|test_partial_cache_key\|test_partial_not_returned" tests/unit/test_enrich.py
3
```

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. This plan creates test-only files with no production code modifications.

## Self-Check: PASSED

- [x] tests/unit/test_robots_ratelimit.py modified — TestAdaptiveRateLimiter present (2 occurrences)
- [x] tests/unit/test_crawl_all.py created — 3 async xfail tests
- [x] tests/unit/test_enrich.py extended — 3 xfail stubs present
- [x] tests/unit/test_linked_doc_ingest.py created — 4 xfail tests
- [x] Commit 2ae7944 exists
- [x] Commit e3259ed exists
- [x] Full suite passes green (339 passed, 0 ERROR, 0 FAILED)
