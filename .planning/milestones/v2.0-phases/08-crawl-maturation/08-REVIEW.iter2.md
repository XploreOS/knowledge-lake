---
phase: 08-crawl-maturation
reviewed: 2026-07-09T00:00:00Z
depth: standard
iteration: 2
files_reviewed: 15
files_reviewed_list:
  - src/knowledge_lake/api/app.py
  - src/knowledge_lake/api/schemas.py
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/crawl/ratelimit.py
  - src/knowledge_lake/pipeline/crawl.py
  - src/knowledge_lake/pipeline/enrich.py
  - src/knowledge_lake/plugins/builtin/crawl4ai_adapter.py
  - src/knowledge_lake/plugins/builtin/playwright_adapter.py
  - src/knowledge_lake/plugins/builtin/scrapy_adapter.py
  - src/knowledge_lake/plugins/protocols.py
  - src/knowledge_lake/registry/repo.py
  - tests/unit/test_crawl_all.py
  - tests/unit/test_enrich.py
  - tests/unit/test_linked_doc_ingest.py
  - tests/unit/test_robots_ratelimit.py
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_found
---

# Phase 08: Code Review Report (Iteration 2 — Fix Verification)

**Reviewed:** 2026-07-09
**Depth:** standard
**Files Reviewed:** 15
**Status:** issues_found — all 12 original BLOCKERs/WARNINGs fixed; 2 new warnings found, 3 info items

## Summary

All 12 findings from the iteration-1 review (H-01 through H-04, M-01 through M-04, L-01 through L-04) are correctly resolved. No regressions were introduced. Two new issues were found:

1. **H-03 is architecturally incomplete for Playwright**: `playwright_adapter.py` now correctly sets `http_status_code` on all `CrawlPageResult` returns, but the adaptive backoff in `crawl.py` (`_crawl_loop`) only checks `if result.status == "failed":` before calling `limiter.record_error`. Playwright's `page.goto()` does not raise on 4xx/5xx HTTP responses — it returns a response object. A 429 from the server produces `CrawlPageResult(status="complete", http_status_code=429)`, which bypasses the `if result.status == "failed":` gate. Backoff never fires for Playwright-crawled 429/403 pages; the error page HTML is written as a valid artifact and `reset_errors` is called.

2. **Stale `xfail(strict=False)` markers**: All three Phase-8 xfail test classes now test implemented code. With `strict=False`, these tests always succeed regardless of correctness, providing zero regression protection.

---

## Fix Verification

### H-01 — Partial cache key column overflow (`enrich.py`)

**Status: FIXED correctly.**

`f"partial:{synthetic_hash[:55]}"` = 8 + 55 = 63 chars ≤ `String(64)`. The SHA-256 `synthetic_hash` is always exactly 64 hex chars, so `[:55]` is always exactly 55 chars. No truncation ambiguity. The non-partial path stores the full 64-char `synthetic_hash` which also fits exactly in `String(64)`.

### H-02 — Tenacity retries unrecoverable truncation (`enrich.py`)

**Status: FIXED correctly.**

```python
# enrich.py:267-270
try:
    result = EnrichmentResult.model_validate_json(prefix_content)
except ValidationError as exc:
    raise ValueError(f"partial enrichment has no recoverable prefix: {exc}") from exc
```

`ValueError` is not in tenacity's `retry_if_exception_type((RuntimeError, ValidationError))` set, so it propagates immediately to `enrich_document`'s `except Exception` handler, which returns `skipped_enrichment_failed` after a single LLM call. The `attempt_costs.append(...)` at line 248 executes before the `finish_reason` check, so cost is accumulated even on this failure path (though it is not recorded to the DB for any `skipped_*` outcome — consistent with the pre-existing behavior for exhausted retries).

### H-03 — CRAWL-03 dead for Playwright (`playwright_adapter.py`)

**Status: PARTIALLY FIXED — see WR-01 below.**

`_render_page` now correctly returns `(html, http_status_code)` and `fetch_page` correctly forwards it on all paths (robots_blocked→None, render_exception→None, size_exceeded→actual code, complete→actual code). The fix is correct at the adapter layer. The remaining gap (described as WR-01) is that the orchestrator never sees `status="failed"` for Playwright 429/403 responses.

### H-04 — CRAWL-03 dead for Scrapy (`scrapy_adapter.py`)

**Status: FIXED correctly.**

```python
# scrapy_adapter.py:209-211
# H-04 fix: read http_status_code from JSONL so the crawl
# orchestrator can trigger CRAWL-03 adaptive backoff on 429/403.
http_status_code: int | None = obj.get("http_status_code")
```

`http_status_code` is forwarded on both `"complete"` and `"failed"` paths; `"robots_blocked"` correctly receives `None`. Backward compatible: `obj.get("http_status_code")` returns `None` when the key is absent (old JSONL without this field). **Caveat**: `scrapy_spider.py` is not in the review scope; H-04 effectiveness depends on the spider writing this field — see IN-01.

### M-01 — `CrawlAllRequest` dead code (`schemas.py`)

**Status: FIXED correctly.** `CrawlAllRequest` removed; comment at `schemas.py:304-308` explains the contract.

### M-02 — `depth_override=0` silent no-op (`crawl.py`)

**Status: FIXED correctly.**

```python
# crawl.py:168-178
if parsed_depth <= 0:
    log.warning("crawl.depth_override_invalid", ..., reason="depth must be > 0; ...")
else:
    effective_max_pages = parsed_depth
```

Non-integer values (e.g., `"none"`, `3.5`) are caught by `except (ValueError, TypeError)` and fall back to `effective_max_pages` with a diagnostic warning. Zero and negative depths also fall back with a warning.

### M-03 — `reset_errors` on non-429/403 failures (`crawl.py`)

**Status: FIXED correctly.** `limiter.reset_errors(url)` is now called only on the `status == "complete"` success path (line 459). The `status == "failed"` path calls `record_error` only for `http_status_code in (429, 403)` and does not reset for 404/timeout/DNS failures.

### M-04 — `source_id_val` clobbered in `crawl_all_sources` (`crawl.py`)

**Status: FIXED correctly.**

```python
# crawl.py:802
results.append({**result, "source_id": source_id_val, "status": "ok"})
```

The later key wins in a dict merge, so `source_id_val` correctly overrides any `"source_id"` key that `crawl_source()` places in `result`.

### L-01 — `cmd_crawl_all` narrow exception catch (`cli/app.py`)

**Status: FIXED correctly.**

```python
# cli/app.py:535-537
except Exception as exc:  # L-01 fix: OperationalError, ValidationError etc. need clean output
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(code=1)
```

### L-02 — `consecutive_errors` exposes live mutable dict (`ratelimit.py`)

**Status: FIXED correctly.**

```python
# ratelimit.py:166
return dict(self._consecutive_errors)
```

Shallow copy prevents callers from mutating the internal backoff state directly.

### L-03 — `import os.path` inside for-loop (`crawl.py`)

**Status: FIXED correctly.** `import os.path as _osp` is at module level (line 27), used at line 650.

### L-04 — HTML decoded twice per page (`crawl.py`)

**Status: FIXED correctly.** `html_text` is decoded once at line 469 and passed to both `_extract_linked_docs(html_text, url)` and `_extract_links(html_text, url, seed_domain)`.

---

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: H-03 Incomplete — Playwright 429/403 responses never trigger adaptive backoff

**File:** `src/knowledge_lake/plugins/builtin/playwright_adapter.py:231-238` / `src/knowledge_lake/pipeline/crawl.py:419-438`

**Issue:** Playwright's `page.goto()` does not raise on 4xx/5xx HTTP responses — the navigation succeeds and returns a `Response` object with the error status code. Therefore `fetch_page` returns:

```python
CrawlPageResult(status="complete", html=html_bytes, ..., http_status_code=429)
```

The orchestrator in `_crawl_loop` only checks `if result.http_status_code in (429, 403):` inside the `if result.status == "failed":` block (lines 419, 430). A `status="complete"` result with `http_status_code=429` bypasses that gate entirely. Consequences:

- `limiter.record_error` never fires for Playwright-served 429/403 pages
- `limiter.reset_errors` IS called (wrong — clears accumulated backoff state)
- The 429 error-page HTML is written as a valid artifact to S3 (`_write_artifacts` is called unconditionally)

The H-03 fix correctly sets `http_status_code` in the adapter but the orchestrator cannot act on it without a status-mapping step.

**Fix:**
```python
# playwright_adapter.py: after extracting http_status_code from _render_page,
# map 4xx/5xx to "failed" before constructing CrawlPageResult.
if http_status_code is not None and http_status_code >= 400:
    return CrawlPageResult(
        url=url,
        status="failed",
        html=None,
        markdown=None,
        error=f"HTTP {http_status_code}",
        http_status_code=http_status_code,
    )
```
Insert this check after line 200 (after `_render_page` returns) and before the size-cap check.

---

### WR-02: Stale `xfail(strict=False)` markers on implemented features

**File:** `tests/unit/test_robots_ratelimit.py:208-254`, `tests/unit/test_crawl_all.py:161-208`, `tests/unit/test_linked_doc_ingest.py:23-92`

**Issue:** `xfail(strict=False)` means a test always passes regardless of whether the underlying code is correct or broken. Multiple test classes mark Phase-8 features as "not yet implemented" that are now fully implemented:

- `TestAdaptiveRateLimiter` (`test_robots_ratelimit.py:208-254`): tests `record_error`, `reset_errors`, `backoff_extra`, and cap behaviour of `PerHostLimiter` — all implemented. Because they are xfail, a regression that breaks these methods would go undetected.
- `test_crawl_all_sources_failure_does_not_abort` and `test_crawl_all_sources_domain_filter` (`test_crawl_all.py:161-208`): both mock all I/O and would pass cleanly against the implemented `crawl_all_sources`.
- `test_extract_linked_docs_pdf_only`, `test_extract_linked_docs_docx`, `test_max_linked_docs_cap` (`test_linked_doc_ingest.py:23-67`): `_extract_linked_docs` and `MAX_LINKED_DOCS_PER_PAGE` are implemented in `crawl.py`.

Also note: `test_rate_limit_rps_tier1` and `test_backoff_extra_raises_floor` in `TestResolveDelay` are marked xfail but `rate_limit_rps` and `backoff_extra` are implemented in `resolve_delay`.

**Fix:** Remove `@pytest.mark.xfail` from the tests listed above. `test_crawl_all_sources_returns_summary` may legitimately remain xfail if it requires a live database; the others do not.

---

## Info

### IN-01: `scrapy_spider.py` not in scope — H-04 half-verified

**File:** `src/knowledge_lake/plugins/builtin/scrapy_adapter.py:209-211`

**Issue:** The adapter correctly reads `http_status_code` from the JSONL output. Whether the spider child process actually writes `"http_status_code"` to that JSONL is unverifiable from these files alone. If `scrapy_spider.py` was not updated to write this field, `obj.get("http_status_code")` silently returns `None` for all Scrapy results and adaptive backoff remains inoperative.

**Fix:** Confirm `scrapy_spider.py` writes `"http_status_code"` in its JSONL item output, e.g.:
```python
yield {"url": url, "status": "failed", "http_status_code": response.status, "error": "..."}
```

---

### IN-02: `crawl4ai_adapter.py` size-exceeded path omits `http_status_code`

**File:** `src/knowledge_lake/plugins/builtin/crawl4ai_adapter.py:151-158`

**Issue:** The size-exceeded failure path does not pass `http_status_code`:
```python
return CrawlPageResult(
    url=url,
    status="failed",
    html=None,
    markdown=None,
    error=f"Response exceeded {MAX_DOWNLOAD_BYTES // (1024*1024)} MB cap",
    # http_status_code omitted — defaults to None
)
```
Since Crawl4AI only reaches this path after `result.success=True` (the fetch succeeded with HTTP 200), the omitted status code would be 200, which never triggers adaptive backoff. The practical impact is zero, but it is inconsistent with the playwright adapter's size-exceeded path at `playwright_adapter.py:211-218` which does pass `http_status_code`. Captures the actual response code in the `CrawlPageResult` for debugging.

**Fix:**
```python
return CrawlPageResult(
    ...,
    error=f"Response exceeded {MAX_DOWNLOAD_BYTES // (1024*1024)} MB cap",
    http_status_code=getattr(result, "status_code", None),
)
```

---

### IN-03: `cmd_crawl` catches only `ValueError`; inconsistent with `cmd_crawl_all`

**File:** `src/knowledge_lake/cli/app.py:497-499`

**Issue:** `cmd_crawl` catches only `ValueError` from `crawl_source`. The L-01 fix correctly broadened `cmd_crawl_all` to `except Exception`, but `cmd_crawl` was not updated. `crawl_source` can raise `LookupError` (from `get_crawler` when the adapter is not registered), `RuntimeError`, and SQLAlchemy `OperationalError` — these escape as raw tracebacks instead of clean `Error: …` messages.

**Fix:** Broaden `cmd_crawl`'s except clause to match `cmd_crawl_all`:
```python
except (ValueError, LookupError, Exception) as exc:
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(code=1)
```
Or simply `except Exception`.

---

_Reviewed: 2026-07-09_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Iteration: 2 (fix-verification pass)_
