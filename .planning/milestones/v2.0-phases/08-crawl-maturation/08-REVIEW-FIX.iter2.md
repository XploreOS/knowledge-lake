---
phase: 08-crawl-maturation
fixed_at: 2026-07-09T00:00:00Z
review_path: .planning/phases/08-crawl-maturation/08-REVIEW.md
iteration: 2
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 08: Code Review Fix Report (Iteration 2)

**Fixed at:** 2026-07-09
**Source review:** `.planning/phases/08-crawl-maturation/08-REVIEW.md`
**Iteration:** 2

**Summary:**
- Findings in scope: 2 (WR-01, WR-02)
- Fixed: 2
- Skipped: 0

---

## Fixed Issues

### WR-01: H-03 Incomplete — Playwright 429/403 responses never trigger adaptive backoff

**Files modified:** `src/knowledge_lake/plugins/builtin/playwright_adapter.py`
**Commit:** `9e0b6ca`
**Applied fix:** Added an `http_status_code >= 400` check in `fetch_page` after `_render_page` returns (between the exception handler and the size-cap check). When the Playwright navigation succeeds but the server returns a 4xx or 5xx HTTP status code, the adapter now returns `CrawlPageResult(status="failed", error=f"HTTP {http_status_code}", http_status_code=http_status_code)` instead of `status="complete"`. This ensures `_crawl_loop`'s existing `if result.status == "failed":` gate fires, calling `limiter.record_error` and triggering exponential backoff, rather than incorrectly calling `reset_errors` and writing the error-page HTML as a valid artifact.

---

### WR-02: Stale `xfail(strict=False)` markers on implemented features

**Files modified:** `tests/unit/test_robots_ratelimit.py`, `tests/unit/test_crawl_all.py`, `tests/unit/test_linked_doc_ingest.py`
**Commit:** `34335d7`
**Applied fix:** Removed `@pytest.mark.xfail(strict=False, ...)` from all tests that exercise fully-implemented Phase-8 features:

- `test_robots_ratelimit.py`: Removed from `TestResolveDelay.test_rate_limit_rps_tier1` and `test_backoff_extra_raises_floor` (CRAWL-01 features); and from all four `TestAdaptiveRateLimiter` methods (`test_record_error_increments_count`, `test_reset_errors_clears_count`, `test_backoff_extra_exponential`, `test_backoff_extra_capped`) — CRAWL-03 features.
- `test_crawl_all.py`: Removed from `test_crawl_all_sources_failure_does_not_abort` and `test_crawl_all_sources_domain_filter` — both use `unittest.mock` patches and require no live DB. `test_crawl_all_sources_returns_summary` intentionally left as `xfail` (requires live PostgreSQL connection).
- `test_linked_doc_ingest.py`: Removed from `test_extract_linked_docs_pdf_only`, `test_extract_linked_docs_docx`, and `test_max_linked_docs_cap`. `test_ssrf_blocked_link_counted_as_failed` intentionally left as `xfail` (outside the review's stated scope for this finding).

---

_Fixed: 2026-07-09_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
