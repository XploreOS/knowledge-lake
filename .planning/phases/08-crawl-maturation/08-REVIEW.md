---
phase: 08-crawl-maturation
reviewed: 2026-07-09T06:02:33Z
depth: standard
iteration: 3
files_reviewed: 11
files_reviewed_list:
  - src/knowledge_lake/pipeline/crawl.py
  - src/knowledge_lake/pipeline/enrich.py
  - src/knowledge_lake/plugins/builtin/playwright_adapter.py
  - src/knowledge_lake/plugins/builtin/scrapy_adapter.py
  - src/knowledge_lake/crawl/ratelimit.py
  - src/knowledge_lake/api/app.py
  - src/knowledge_lake/cli/app.py
  - tests/unit/test_robots_ratelimit.py
  - tests/unit/test_crawl_all.py
  - tests/unit/test_linked_doc_ingest.py
  - tests/unit/test_enrich.py
findings:
  critical: 0
  warning: 1
  info: 0
  total: 1
status: clean
---

# Phase 08: Code Review Report (Iteration 3 — Final)

**Reviewed:** 2026-07-09T06:02:33Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found — 0 blockers, 1 warning

## Summary

This is the final iteration of the `--auto` review loop. The two previous iterations found and fixed 14 issues. This pass verifies the iteration-2 fixes and scans for anything missed.

### Iteration-2 WR-01 fix: Playwright `http_status_code >= 400` → `status="failed"` (CONFIRMED CORRECT)

`playwright_adapter.py:208-221` now maps any 4xx/5xx HTTP status to `status="failed"` before returning from `fetch_page`. The check is correctly placed after `_render_page` returns the `(html, http_status_code)` tuple and before the size-cap check. The fix is correct:

- Playwright follows redirects natively; `response.status` is always the final-response code, so 3xx never reaches this guard.
- 404 → `status="failed"`, `html=None`. Correct — the crawl cannot use a "page not found" response.
- 429/403 → `status="failed"`, which flows to the orchestrator's `if result.status == "failed":` gate at `crawl.py:419`. That gate checks `result.http_status_code in (429, 403)` and calls `limiter.record_error(url)`. Adaptive backoff fires correctly.
- 5xx → `status="failed"`, no backoff (intentional, per `crawl.py:430`).
- No false-positives: the only valid statuses that fall through to artifact-write are 1xx/2xx/3xx (all success/redirect).

### Iteration-2 WR-02 fix: xfail test conversion (LARGELY CORRECT, one stale marker remains)

The following tests were correctly converted to proper assertions (no xfail markers):

- `TestAdaptiveRateLimiter` in `test_robots_ratelimit.py` (all four methods)
- `test_crawl_all_sources_failure_does_not_abort` in `test_crawl_all.py` (line 162)
- `test_crawl_all_sources_domain_filter` in `test_crawl_all.py` (line 193)
- `test_extract_linked_docs_pdf_only`, `test_extract_linked_docs_docx`, `test_max_linked_docs_cap` in `test_linked_doc_ingest.py`

One stale xfail marker was not removed (see WR-01 below).

The remaining xfail on `test_ssrf_blocked_link_counted_as_failed` (`test_linked_doc_ingest.py:66`) is intentionally kept: `_extract_linked_docs` correctly does not perform SSRF filtering (the caller, `_crawl_loop`, does). The test documents a known design boundary. `strict=False` is the right marker for a known-limitation stub.

### Partial cache key truncation consistency (CONFIRMED CORRECT)

All three code paths that touch the partial cache key use the same `effective_cache_key` alias:

- **Write path** (`enrich.py:444`): `content_hash=effective_cache_key`
- **Step-5 re-check** (`enrich.py:416`): `get_artifact_by_hash(session, effective_cache_key, ...)`
- **IntegrityError fallback** (`enrich.py:459`): `get_artifact_by_hash(session, effective_cache_key, ...)`

The key is `"partial:" + synthetic_hash[:55]` for partial results (8 + 55 = 63 chars, fits `String(64)`) and the full 64-char `synthetic_hash` for complete results. No asymmetry between write and lookup.

### `ValueError` not in tenacity retry set (CONFIRMED CORRECT)

The `@retry` decorator on `_call_llm_for_enrichment` retries only on `retry_if_exception_type((RuntimeError, ValidationError))`. `ValueError` is not a subclass of either. When prefix recovery fails and raises `ValueError`, tenacity does not intercept it — it propagates immediately to `enrich_document`'s outer `except Exception` block, returning `skipped_enrichment_failed` after one LLM call. The H-02 fix is correct and the cost semantics are also correct: `attempt_costs.append(compute_call_cost(response, settings))` executes at line 248 before the `finish_reason` check, so the cost of a single partial call is always accumulated even when it is ultimately unrecoverable.

### `depth_override` guard warning quality (CONFIRMED USEFUL)

Both invalid-depth branches log `source_id`, the rejected `depth_override` value, a human-readable `reason` string, and `effective_max_pages` (the value that will actually be used). Operators can diagnose the rejection and know what fallback was applied without consulting source code.

---

## Warnings

### WR-01: Stale `xfail(strict=False)` on `test_crawl_all_sources_returns_summary`

**File:** `tests/unit/test_crawl_all.py:148`

**Issue:** `crawl_all_sources` is fully implemented at `pipeline/crawl.py:746-820`, but the test at line 148 still carries `@pytest.mark.xfail(strict=False, reason="Phase 8 CRAWL-02 — not yet implemented")`. The reason string is factually wrong.

Because the test calls `crawl_all_sources()` without mocking the database layer, it fails with a connection error in the unit-test environment. With `strict=False`, this expected failure is silently swallowed, so CI never surfaces the stale marker. Two properly-mocked tests for the same function already exist in the same file (lines 162 and 193); this stub is redundant and misleading. Any developer reading the file would incorrectly infer the batch-crawl orchestrator is not yet complete.

**Fix option A — remove the stub** (preferred, since lines 162 and 193 already cover the same assertions with proper mocking):

Delete lines 147-158.

**Fix option B — convert to a mocked assertion:**

```python
@pytest.mark.asyncio
async def test_crawl_all_sources_returns_summary():
    """crawl_all_sources() returns dict with keys total, succeeded, failed, results."""
    from unittest.mock import patch
    from knowledge_lake.pipeline.crawl import crawl_all_sources as _crawl_all

    with patch(
        "knowledge_lake.pipeline.crawl.list_sources_for_crawl_all",
        return_value=[],
    ):
        result = await _crawl_all()

    assert isinstance(result, dict)
    assert "total" in result
    assert "succeeded" in result
    assert "failed" in result
    assert "results" in result
```

---

_Reviewed: 2026-07-09T06:02:33Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Iteration: 3 (final)_
