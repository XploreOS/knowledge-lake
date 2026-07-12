---
phase: 08-crawl-maturation
status: reviewed
severity_summary: 2 high, 5 medium, 5 low
reviewed_at: 2026-07-08
base_commit: 96618ec
head_commit: f1775e6
---

# Phase 08: Crawl Maturation — Code Review

## Summary

12 findings across 4 severity levels. **2 findings require fixes before verification can pass:** the partial-enrichment cache key truncates the `String(64)` DB column (crashes every partial enrichment in production), and CRAWL-03 adaptive backoff is silently dead for both the Playwright and Scrapy adapters (the only adapters with non-trivial use; crawl4ai already wired). The tenacity-retries-on-unrecoverable-truncation bug compounds the budget cost of the first.

---

## HIGH — Fix before verification

### H-01 · `src/knowledge_lake/pipeline/enrich.py:384` — Partial cache key (72 chars) overflows `String(64)` column

**Summary:** `f"partial:{synthetic_hash}"` is 8 + 64 = 72 characters; the `Artifact.content_hash` column is `String(64)`. Every partial enrichment write raises `DataError: value too long for type character varying(64)` on PostgreSQL, so ENRICH-07 is completely broken in production.

**Trigger:** Any document long enough to hit the LLM token limit where prefix recovery succeeds (the "happy path" of partial enrichment).

**Fix:** Either widen the column (new migration, `String(80)` or `Text`) or truncate the hash component to 56 chars (`synthetic_hash[:56]`) so the full key stays ≤ 64.

---

### H-02 · `src/knowledge_lake/pipeline/enrich.py:262` — Tenacity retries unrecoverable truncation, burning 3× LLM budget

**Summary:** The `@retry(retry=retry_if_exception_type((RuntimeError, ValidationError)))` decorator on `_call_llm_for_enrichment` also catches the `ValidationError` raised at line 262 when `_extract_longest_valid_prefix` cannot produce a valid prefix. The docstring comment "no tenacity involvement" is factually wrong — tenacity retries the LLM call up to 3 times on truly unrecoverable truncation.

**Trigger:** A document whose content, when truncated by the model at the token limit, has no recoverable JSON prefix (e.g., the model output starts with a string value and never closes the root brace). All 3 tenacity attempts make a full LiteLLM call and append to `attempt_costs`.

**Fix:** Catch the `ValidationError` from the prefix path and re-raise as a non-retried exception type, or add `retry=retry_if_exception_type(RuntimeError)` (drop `ValidationError`) and handle the normal-path `ValidationError` without tenacity.

---

### H-03 · `src/knowledge_lake/plugins/builtin/playwright_adapter.py:181` — CRAWL-03 dead for Playwright

**Summary:** The Playwright adapter calls `resolve_delay(source_config, robots_delay, self._global_rate_limit)` without the new `backoff_extra` keyword argument (always 0.0), and never sets `http_status_code` on any `CrawlPageResult` it returns. Since `crawl.py:400` gates `record_error` on `result.http_status_code in (429, 403)`, and `http_status_code` is always `None` for Playwright results, the adaptive backoff is completely inoperative for the Playwright adapter.

**Fix:** Set `http_status_code` on all three `CrawlPageResult` construction sites in `playwright_adapter.py` (mirror the existing `crawl4ai_adapter.py` pattern at lines 121–137).

---

### H-04 · `src/knowledge_lake/plugins/builtin/scrapy_adapter.py:221` — CRAWL-03 dead for Scrapy

**Summary:** All three `CrawlPageResult` constructions in `scrapy_adapter.get_results()` (lines 221, 230, 240) omit `http_status_code`. Scrapy 429/403 responses never trigger `record_error`, silently defaulting to `reset_errors` instead.

**Fix:** Pass the HTTP status code from the Scrapy JSONL result into `CrawlPageResult.http_status_code` on the `complete` and `failed` paths. The `robots_blocked` path can set `http_status_code=None`.

---

## MEDIUM — Should fix

### M-01 · `src/knowledge_lake/api/schemas.py:306` + `api/app.py:42` — `CrawlAllRequest` is dead code / behavioral contract mismatch

**Summary:** `CrawlAllRequest` defines a request body with `domain: Optional[str]`, but the `/crawl-all` endpoint declares `domain` as `Query(None)`, not as a body parameter. Clients POSTing `{"domain": "healthcare"}` get `domain=None` (body silently ignored). The schema is imported but never referenced in the endpoint signature.

**Fix:** Either (a) change the endpoint to accept `body: CrawlAllRequest` and read `body.domain`, or (b) delete `CrawlAllRequest` and document that the endpoint takes a query parameter.

---

### M-02 · `src/knowledge_lake/pipeline/crawl.py:153` — `depth_override=0` silently produces a no-op crawl

**Summary:** `int(depth_override)` with no lower-bound guard means `depth: 0` in `sources.yaml` sets `effective_max_pages=0`. The `while queue and pages_total < max_pages` loop exits immediately (0 < 0 is False), the job completes with zero pages and no error. Additionally, a non-integer `depth` value (e.g., `"none"` or `3.5`) raises `ValueError` which is silently caught by `crawl_all_sources` and counted as a source failure without a meaningful diagnostic.

**Fix:** Validate `depth_override`: reject ≤ 0 with a clear log warning and fall back to the global default.

---

### M-03 · `src/knowledge_lake/pipeline/crawl.py:409` — `reset_errors` on non-429/403 failures clears accumulated backoff state

**Summary:** The `else` branch at line 409 calls `limiter.reset_errors(url)` for ALL non-429/403 failures — including 404 Not Found, connection timeouts, and DNS errors. A single 404 on a host that has accumulated 429-based backoff state wipes the error count, causing the next request to that host to have zero additional delay despite ongoing rate-limiting.

**Trigger:** Crawling a rate-limited host that serves some URLs as 429 and others as 404 (common when a rate-limiter returns 404 instead of 429 for certain paths).

**Fix:** Only call `reset_errors` on `result.status == "complete"` (genuine success), not on all non-429/403 failures.

---

### M-04 · `src/knowledge_lake/pipeline/crawl.py:760` — `**result` spread overwrites `source_id_val` in `crawl_all_sources` result dict

**Summary:** `{'source_id': source_id_val, 'status': 'ok', **result}` — `crawl_source()` returns a dict that also contains `'source_id'`, so `**result` clobbers `source_id_val`. In the common path both IDs are identical; the divergence occurs when `register_source` URL-deduplicates to a pre-existing source with a different ID than the one returned by `list_sources_for_crawl_all`.

**Fix:** Explicitly override after spread: `{**result, 'source_id': source_id_val, 'status': 'ok'}`.

---

## LOW — Cleanup

### L-01 · `src/knowledge_lake/cli/app.py:535` — `cmd_crawl_all` catches only `ValueError`

**Summary:** `OperationalError` (DB down), `pydantic.ValidationError` (bad settings), and other exceptions from `crawl_all_sources` surface as raw Python tracebacks rather than clean `Error: …` + `Exit(1)`. Mirrors the narrow catch in `cmd_crawl`.

**Fix:** Broaden to `except Exception as exc: typer.echo(f"Error: {exc}", err=True); raise typer.Exit(1)`.

---

### L-02 · `src/knowledge_lake/crawl/ratelimit.py:159` — `consecutive_errors` property exposes live mutable dict

**Summary:** The property is documented as "read-only view" but returns `self._consecutive_errors` directly. External mutation (e.g., `del limiter.consecutive_errors['example.com']`) corrupts backoff state without going through `reset_errors`, which would also clear `_cooldown_until`.

**Fix:** Return `dict(self._consecutive_errors)` or `types.MappingProxyType(self._consecutive_errors)`.

---

### L-03 · `src/knowledge_lake/pipeline/crawl.py:611` — `import os.path` inside the `_extract_linked_docs` for-loop

**Summary:** `import os.path as _osp` executes on every regex match iteration. Python's `sys.modules` cache makes it nearly free, but it is unconventional and should be hoisted to module level with the other stdlib imports.

**Fix:** Move to the top of `crawl.py` with the existing `import os` / `import os.path` imports.

---

### L-04 · `src/knowledge_lake/pipeline/crawl.py:436` — HTML content scanned twice per page

**Summary:** For each successful page, `_extract_linked_docs(result.html, url)` and `_extract_links(result.html, url, seed_domain)` both run `_LINK_RE.finditer` independently over the same decoded HTML string.

**Fix:** Combine into a single pass or decode once and share the string between the two callers.

---

## Artifacts this review covers

All changes in commits `2ae7944`–`f1775e6` (Phase 08 — `96618ec`…`HEAD`):
- `src/knowledge_lake/crawl/ratelimit.py`
- `src/knowledge_lake/pipeline/crawl.py`
- `src/knowledge_lake/pipeline/enrich.py`
- `src/knowledge_lake/plugins/builtin/crawl4ai_adapter.py`
- `src/knowledge_lake/plugins/builtin/scrapy_adapter.py` (not modified in diff — H-04 is a gap in Phase 8's CRAWL-03 wiring)
- `src/knowledge_lake/plugins/protocols.py`
- `src/knowledge_lake/registry/repo.py`
- `src/knowledge_lake/api/app.py`
- `src/knowledge_lake/api/schemas.py`
- `src/knowledge_lake/cli/app.py`
- `tests/unit/test_crawl_all.py`
- `tests/unit/test_enrich.py`
- `tests/unit/test_linked_doc_ingest.py`
- `tests/unit/test_robots_ratelimit.py`
