# Phase 8: Crawl Maturation - Research

**Researched:** 2026-07-08
**Domain:** Python async crawl orchestration, adaptive rate limiting, LLM response recovery, SSRF-safe linked-document ingestion
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**CRAWL-01 — Per-source config wiring**
- D-01: Add `get_source_crawl_config(source_id)` helper to `repo.py` mirroring `get_domain_for_source` (line 820) — same None-guard and session-handling style.
- D-02: In `crawl_source` (`crawl.py:296`), replace `source_config = None` with lookup via `get_source_crawl_config(source_id)`. Pass the dict to `resolve_delay()`.
- D-03: `resolve_delay()` extended to accept `rate_limit_rps`: if present and `rate_limit_seconds` absent, convert via `1 / rate_limit_rps`. `rate_limit_seconds` wins if both present.
- D-04: Per-source depth read from `source_config.get("crawl_config", {}).get("depth")`. If present, overrides `effective_max_pages`. If absent, `settings.crawl.max_pages` wins.
- D-05: `crawl_config` nesting is `source_config.get("crawl_config", {})` — never flatten the structure.

**CRAWL-02 — `klake crawl-all` batch command**
- D-06: `crawl_all_sources()` function in `crawl.py` (or `pipeline/batch.py`) — sequential loop, no parallelism for v2.0.
- D-07: CLI `klake crawl-all` with `--domain` option. `asyncio.run(crawl_all_sources(...))`. Emits a summary row per source.
- D-08: REST API `POST /crawl-all` with optional `domain` query param. Returns list of per-source result dicts.
- D-09: Per-source failure is logged+counted, does not abort the batch. Return `{total, succeeded, failed, results: [...]}`.

**CRAWL-03 — Adaptive rate limiting**
- D-10: Adaptive backoff in the page-fetch loop in `crawl.py` (not in adapters). `AdaptiveRateLimiter` or extended `PerHostLimiter` tracks consecutive 429/403 per host.
- D-11: Exponential backoff with base 2, starting at `config_delay`, capped at `MAX_BACKOFF_SECONDS` (default 60). Reset on any non-4xx response. Per-host.
- D-12: `resolve_delay()` extended with `backoff_extra` parameter (float, default 0.0). Effective delay = `max(tier_result, tier_result + backoff_extra)`.
- D-13: Per-host cooldown after 429: wait at least `COOLDOWN_SECONDS` (default 30) before re-querying that host.

**ENRICH-07 — Partial-JSON recovery**
- D-14: Truncation detected via `choices[0].finish_reason == "length"` on LiteLLM response — not via `ValidationError`.
- D-15: Longest-valid-prefix: balanced-brace scan backward from end of stripped content to find last `}` closing outermost object. `model_validate_json()` on prefix. Accept with `is_partial=True`.
- D-16: Cache key for partials: `"partial:{content_hash}"` key (or `is_partial` column). Partial results never returned to callers expecting complete enrichment. Cached partial = cache miss for complete.
- D-17: Add `is_partial: bool = False` to `EnrichmentResult`. Callers log warning, do NOT block indexing.
- D-18: No retry loop inside `enrich_document()` for truncation. Log `enrich.partial_result` with `finish_reason` + `content_hash`.

**INGEST-10 — Linked-document ingestion**
- D-19: Link extraction runs after bronze artifact write. Only `.pdf` and `.docx` followed (configurable `LINKED_DOC_EXTENSIONS`).
- D-20: Frontier bounded at `MAX_LINKED_DOCS_PER_PAGE` (default 10). Deduplicated against `_seen_urls` set. Registry content-hash match = skip silently.
- D-21: SSRF guard via `validate_public_url()` on every followed link, every time, before any HTTP.
- D-22: Each followed link ingested via existing `ingest_url()`. Linked artifact shares `source_id` and `job_id` with parent HTML page.
- D-23: Dedup via `ingest_url()`'s existing content-hash dedup — no additional logic needed.
- D-24: Failed link follows logged per link, counted as `linked_docs_failed` in job summary. Do not abort parent HTML crawl.

### Claude's Discretion
- Exact naming of `get_source_crawl_config` vs `get_source_config` in `repo.py`.
- Whether `AdaptiveRateLimiter` is a new class or extension of `PerHostLimiter`.
- Whether `crawl_all_sources()` lives in `crawl.py` or `pipeline/batch.py`.
- Exact `EnrichmentResult` field name for partial flag (`is_partial` vs `partial`).
- Whether `MAX_LINKED_DOCS_PER_PAGE`, `MAX_BACKOFF_SECONDS`, `COOLDOWN_SECONDS` are in `Settings` or module-level constants.

### Deferred Ideas (OUT OF SCOPE)
- Parallel `crawl-all` execution
- Sitemap-first crawl strategy (SITEMAP-01)
- Re-crawl change detection (SCHED-02)
- Quality-score propagation to search (QUALITY-01)
- Retry loop inside `enrich_document()` for truncation
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CRAWL-01 | Per-source crawl_config wiring: fix `source_config = None` bug at crawl.py:296; reconcile `rate_limit_rps` vs `rate_limit_seconds` | `get_domain_for_source` pattern confirmed at repo.py:820; `resolve_delay()` at ratelimit.py:32 ready for `rate_limit_rps` extension; `crawl_config` nesting confirmed persisted by domain-init at app.py:1044 |
| CRAWL-02 | `klake crawl-all` batch command with `--domain` filter; sequential loop; per-source failure tolerance | `cmd_crawl` pattern confirmed at app.py:456; no `list_all_sources` function exists in repo.py — must add; API crawl endpoint pattern confirmed at api/app.py:476 |
| CRAWL-03 | Adaptive backoff on 429/403, per-host cooldown, effective delay = max(robots, backoff, config) | `PerHostLimiter` confirmed at ratelimit.py:95 — carries `_last_fetch` dict, ready to extend with error-count state; `CrawlPageResult` has `status` field but no `http_status_code` field — see Pitfall 2 |
| ENRICH-07 | Truncation detection via `finish_reason`, longest-valid-prefix recovery, partial-result cache isolation | LiteLLM response structure confirmed: `response.choices[0].finish_reason`; `_call_llm_for_enrichment` returns `(result, response)` — `response` object available to check `finish_reason` |
| INGEST-10 | HTML crawl → linked .pdf/.docx ingestion via `ingest_url()`; SSRF guard; bounded frontier; dedup | `ingest_url()` confirmed at ingest.py:337 with SSRF guard, size cap, content-hash dedup; `validate_public_url()` at ingest.py:99; `_seen_urls` set confirmed in `_crawl_loop` |
</phase_requirements>

---

## Summary

Phase 8 is a pure Python refactor and extension phase — no new dependencies, no schema migrations, no Qdrant changes. All five requirements operate on the existing async crawl orchestrator (`pipeline/crawl.py`), the rate-limit module (`crawl/ratelimit.py`), the enrichment stage (`pipeline/enrich.py`), and the ingest path (`pipeline/ingest.py`). The codebase is mature and well-structured; every required extension point exists and has been confirmed in code.

The largest structural change is CRAWL-03 (adaptive backoff): `PerHostLimiter` currently only tracks `_last_fetch` time and `_locks`. To support backoff state it needs a second dict (`_consecutive_errors: dict[str, int]`) and the page-fetch loop in `_crawl_loop` must inspect `result.status` to increment/reset counters. The challenge here is that `CrawlPageResult.status` is a string (`'complete'`, `'failed'`, `'robots_blocked'`) — it does NOT carry an HTTP status code. Adapters (crawl4ai, playwright) must be checked: crawl4ai surfaces `status_code` as a `getattr(result, "status_code", None)` (confirmed at crawl4ai_adapter.py:118), but `CrawlPageResult.status` only has three string states. For backoff to work on 429/403, the `CrawlPageResult` dataclass must grow an optional `http_status_code: Optional[int]` field, OR adapters translate 429 → a distinct status string before returning to the orchestrator.

ENRICH-07 is well-scoped: `_call_llm_for_enrichment` returns `(result, response)` so the `response` object with `finish_reason` is already available at the call site in `enrich_document()`. The longest-valid-prefix algorithm is a balanced-brace scan — straightforward but must handle nested objects correctly.

**Primary recommendation:** Implement in 5 discrete, independently testable units: (1) repo helper + config wiring, (2) crawl-all function + CLI + API, (3) adaptive backoff + `CrawlPageResult` http_status_code field, (4) partial-JSON recovery in enrich, (5) linked-doc ingestion post-bronze-write.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Per-source crawl config lookup | Registry (repo.py) | Pipeline (crawl.py) | Config is stored in Source.config JSON column — registry layer owns the query |
| Rate-limit resolution | Crawl module (ratelimit.py) | Pipeline (crawl.py) | `resolve_delay()` encapsulates tier logic; crawl loop calls it |
| Adaptive backoff state | Crawl module (ratelimit.py or AdaptiveRateLimiter) | Pipeline (crawl.py orchestrates) | State tracking belongs with the rate-limit primitive, not scattered in the loop |
| Batch crawl orchestration | Pipeline (crawl.py or pipeline/batch.py) | CLI + API (thin shims) | Business logic in pipeline; CLI/API are call-through wrappers |
| Truncation detection + prefix recovery | Pipeline (enrich.py) | — | LiteLLM response is only visible inside `_call_llm_for_enrichment`; detection must happen there |
| Partial-result cache isolation | Pipeline (enrich.py) + Registry (repo.py) | — | Cache key discipline enforced where artifacts are written |
| Linked-document extraction | Pipeline (crawl.py) | — | Runs post-bronze-write in `_crawl_loop`; delegates fetching to `ingest_url()` |
| SSRF guard on linked links | Pipeline (ingest.py validate_public_url) | — | Shared guard; must be called before any HTTP |

---

## Standard Stack

No new packages are installed in this phase. All required capabilities are covered by existing dependencies.

### Core — Existing (no changes)
| Library | Version | Purpose | Used In |
|---------|---------|---------|---------|
| Python asyncio | stdlib | Async crawl loop, per-host locks | `_crawl_loop`, `PerHostLimiter` |
| SQLAlchemy 2.0 | existing | ORM queries for source config + artifact writes | `repo.py`, `get_session()` |
| pydantic 2.x | existing | `EnrichmentResult` model validation, prefix recovery | `enrich.py` |
| litellm | existing | LLM gateway — `finish_reason` field on response | `enrich.py` |
| tldextract | existing | Domain key extraction for per-host rate limiter | `ratelimit.py` |
| httpx | existing | Used inside `ingest_url()` for linked-doc fetching | `ingest.py` |
| structlog | existing | Structured logging for all new operations | throughout |
| tenacity | existing | Retry on LLM calls (existing); NOT used for backoff | `enrich.py` |

### Package Legitimacy Audit

No new packages to install. Phase 8 is a pure refactor/extension of existing code.

| Package | Registry | Verdict | Disposition |
|---------|----------|---------|-------------|
| (none) | — | — | No new installs |

**Packages removed due to SLOP verdict:** none
**Packages flagged as suspicious SUS:** none

---

## Architecture Patterns

### System Architecture Diagram

```
HTTP Request
     |
     v
[_crawl_loop]
     |
     +---> SSRF guard (validate_public_url)
     |
     +---> robots.txt check (robots_policy.is_allowed)
     |
     +---> resolve_delay(source_config, robots_delay, global_default, backoff_extra)
     |           |
     |           +-- Tier 1: source_config["crawl_config"]["rate_limit_seconds|rps"]
     |           +-- Tier 2: robots Crawl-delay
     |           +-- Tier 3: settings.crawl.rate_limit_seconds
     |           +-- Floor: max(tier_result, tier_result + backoff_extra)
     |
     +---> AdaptiveRateLimiter.wait(url, delay)  [tracks cooldown per host]
     |
     +---> adapter.fetch_page(url)
     |           |
     |           +-- returns CrawlPageResult(status, html, markdown, http_status_code)
     |
     +---> on 429/403: increment host error count, compute backoff_extra
     |     on success: reset host error count
     |
     +---> _write_artifacts (raw + bronze)  [D-01 lineage]
     |
     +---> _extract_linked_docs(html, base_url)  [INGEST-10 — post-bronze]
               |
               +-- filter to .pdf/.docx only
               +-- SSRF guard each link
               +-- bounded frontier (MAX_LINKED_DOCS_PER_PAGE)
               +-- ingest_url() for each passing link
               +-- count linked_docs_failed

[crawl_all_sources(domain=None)]
     |
     +-- list_sources_for_crawl_all(domain) -> [Source]
     |
     +-- for each source: crawl_source(source.url)
     |       on error: log + increment failed count
     |
     +-- return {total, succeeded, failed, results: [...]}

[enrich_document — ENRICH-07 extension]
     |
     +-- _call_llm_for_enrichment -> (result, response)
     |
     +-- check response.choices[0].finish_reason
     |       if "length":
     |           _extract_longest_valid_prefix(content)
     |           model_validate_json(prefix) -> partial EnrichmentResult
     |           set is_partial=True
     |           use cache key "partial:{content_hash}"
     |       else:
     |           normal path
```

### Recommended Project Structure

No new modules required. Changes are additive within existing files:

```
src/knowledge_lake/
├── crawl/
│   └── ratelimit.py         # extend resolve_delay() + PerHostLimiter/AdaptiveRateLimiter
├── pipeline/
│   ├── crawl.py             # fix source_config=None; add backoff loop; add linked-doc post-write; add crawl_all_sources()
│   └── enrich.py            # add finish_reason check + prefix recovery + is_partial flag
├── registry/
│   └── repo.py              # add get_source_crawl_config() + list_sources_for_crawl_all()
├── cli/
│   └── app.py               # add cmd_crawl_all command
└── api/
    └── app.py               # add POST /crawl-all endpoint
```

Planner may choose to add `pipeline/batch.py` for `crawl_all_sources()` if crawl.py grows too large. Either location is consistent with existing module conventions.

### Pattern 1: Registry helper — get_source_crawl_config

**What:** Fetch a source's `crawl_config` sub-dict from `Source.config`. Returns `{}` if source missing or config absent.

**When to use:** Called in `crawl_source()` after `source_id` is resolved, before passing to `resolve_delay()`.

```python
# Source: verified from repo.py:820 get_domain_for_source pattern [VERIFIED: codebase]
def get_source_crawl_config(session: Session, source_id: str) -> dict:
    """Return the crawl_config sub-dict from Source.config, or {} if absent."""
    source = session.get(Source, source_id)
    if source is None or not source.config:
        return {}
    return source.config.get("crawl_config", {})
```

Note: The function returns the `crawl_config` sub-dict (nesting: `source.config["crawl_config"]`), not the full `source.config`. This matches D-05 — do not flatten the structure.

### Pattern 2: resolve_delay() extension with rate_limit_rps + backoff_extra

**What:** Backward-compatible extension of existing `resolve_delay()`. Adds `rate_limit_rps` conversion at Tier 1 and `backoff_extra` as a floor-raising additive layer.

```python
# Source: verified from ratelimit.py:32 [VERIFIED: codebase]
def resolve_delay(
    source_config: Optional[dict],
    robots_crawl_delay: Optional[float],
    global_default: float,
    backoff_extra: float = 0.0,
) -> float:
    # Tier 1: source config — accept both keys
    if source_config:
        if "rate_limit_seconds" in source_config:
            tier_result = float(source_config["rate_limit_seconds"])
            return max(tier_result, tier_result + backoff_extra)
        if "rate_limit_rps" in source_config:
            rps = float(source_config["rate_limit_rps"])
            tier_result = 1.0 / rps if rps > 0 else global_default
            return max(tier_result, tier_result + backoff_extra)
    # Tier 2: robots.txt
    if robots_crawl_delay is not None:
        tier_result = float(robots_crawl_delay)
        return max(tier_result, tier_result + backoff_extra)
    # Tier 3: global default
    return max(global_default, global_default + backoff_extra)
```

### Pattern 3: Adaptive backoff state in PerHostLimiter

**What:** Extend `PerHostLimiter` to track consecutive error count per host. Compute backoff delay as `min(config_delay * (2 ** consecutive_errors), MAX_BACKOFF_SECONDS)`.

**When to use:** Called from `_crawl_loop` on every fetch result.

```python
# Source: verified from ratelimit.py:95 [VERIFIED: codebase]
class PerHostLimiter:
    def __init__(self) -> None:
        self._last_fetch: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._consecutive_errors: dict[str, int] = {}   # NEW
        self._cooldown_until: dict[str, float] = {}      # NEW

    def record_error(self, url: str) -> None:
        """Increment consecutive error count for this host (call on 429/403)."""
        key = _domain_key(url)
        self._consecutive_errors[key] = self._consecutive_errors.get(key, 0) + 1
        self._cooldown_until[key] = time.monotonic() + COOLDOWN_SECONDS

    def reset_errors(self, url: str) -> None:
        """Reset error count on successful response."""
        key = _domain_key(url)
        self._consecutive_errors.pop(key, None)
        self._cooldown_until.pop(key, None)

    def backoff_extra(self, url: str, base_delay: float) -> float:
        """Return additional backoff seconds based on consecutive error count."""
        key = _domain_key(url)
        n = self._consecutive_errors.get(key, 0)
        if n == 0:
            return 0.0
        backoff = base_delay * (2 ** n)
        return min(backoff, MAX_BACKOFF_SECONDS)
```

**Cooldown enforcement:** In `wait()`, check `_cooldown_until[key]` before the normal `_last_fetch` sleep. If current time < cooldown_until, sleep until cooldown expires.

### Pattern 4: Truncation detection and prefix recovery (ENRICH-07)

**What:** After `_call_llm_for_enrichment`, check `finish_reason`. On `"length"`, extract longest valid JSON prefix and return partial result.

**Key implementation detail:** The check belongs in `enrich_document()` where the `response` object is available — NOT inside `_call_llm_for_enrichment`. Currently `_call_llm_for_enrichment` parses the JSON and returns `(result, response)` — the `finish_reason` check must happen in the caller after receiving both.

**However,** there is a design constraint: `_call_llm_for_enrichment` raises `ValidationError` when JSON is truncated (parse fails). The `tenacity` retry decorator on `_call_llm_for_enrichment` re-raises `ValidationError`. This means truncated output currently triggers a retry, which is wrong per D-18.

**Resolution:** The `finish_reason` check must intercept *before* `ValidationError` propagates. Two options:
1. Move `finish_reason` check inside `_call_llm_for_enrichment` before `model_validate_json()` — set a flag or return a sentinel.
2. Pass `finish_reason` out via the `attempt_costs` accumulator list pattern (already used for cost) — but this is awkward.

**Recommended (cleanest):** Extract the JSON content and check `finish_reason` *inside* `_call_llm_for_enrichment`, before `model_validate_json()`. If `finish_reason == "length"`, do NOT call `model_validate_json()` normally. Instead, call `_extract_longest_valid_prefix(content)` and `model_validate_json(prefix)`. Return `(partial_result, response, is_partial=True)` via a 3-tuple (or a dedicated `LLMCallResult` dataclass). The tenacity retry stays on the non-truncation path; truncation exits immediately without retry.

```python
# Balanced-brace scan for longest valid JSON prefix [ASSUMED pattern, standard technique]
def _extract_longest_valid_prefix(content: str) -> str:
    """Walk backward to find last balanced closing brace."""
    depth = 0
    last_close = -1
    in_string = False
    escape = False
    for i, ch in enumerate(content):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                last_close = i
    if last_close == -1:
        return content  # no balanced close found
    return content[:last_close + 1]
```

### Pattern 5: Linked-document extraction (INGEST-10)

**What:** After `_write_artifacts`, scan HTML for `.pdf`/`.docx` links and ingest each via `ingest_url()`.

**Where in code:** In `_crawl_loop`, after the `_write_artifacts(...)` call and `_record_state("complete")` call — post-bronze, as required by D-19.

```python
# Source: verified from crawl.py:343 link extraction section [VERIFIED: codebase]
# Post-bronze linked-doc ingestion
linked_docs_failed = 0
if result.html:
    linked_links = _extract_linked_docs(result.html, url)  # new function
    for link_url in linked_links[:MAX_LINKED_DOCS_PER_PAGE]:
        norm_link = normalize_url(link_url)
        if norm_link in seen:
            continue
        seen.add(norm_link)
        try:
            validate_public_url(link_url)  # SSRF guard — always
        except ValueError as exc:
            log.warning("crawl.linked_doc_ssrf_blocked", url=link_url, error=str(exc))
            linked_docs_failed += 1
            continue
        try:
            ingest_url(link_url, source_name=_name_from_url(link_url), settings=settings)
        except Exception as exc:
            log.warning("crawl.linked_doc_ingest_failed", url=link_url, error=str(exc))
            linked_docs_failed += 1
```

Note: `ingest_url()` is synchronous (uses `httpx.Client`). In the async `_crawl_loop`, wrap with `asyncio.get_running_loop().run_in_executor(None, ingest_url, link_url, ...)` to avoid blocking the event loop.

### Pattern 6: list_sources_for_crawl_all

**What:** `crawl_all_sources()` needs all registered sources, optionally filtered by domain. No `list_all_sources()` function currently exists in `repo.py`. The API endpoint at `api/app.py:1146` implements domain filtering inline (Python-side filter over all sources for correctness). The same approach should be used in a new `list_sources_for_crawl_all()` repo function.

```python
# Source: verified from api/app.py:1176 pattern [VERIFIED: codebase]
def list_sources_for_crawl_all(
    session: Session,
    domain: Optional[str] = None,
) -> list[Source]:
    """Return all sources, optionally filtered by domain (stored in Source.config['domain'])."""
    all_sources = list(session.execute(select(Source).order_by(Source.created_at.asc())).scalars())
    if domain is None:
        return all_sources
    return [s for s in all_sources if (s.config or {}).get("domain") == domain]
```

### Anti-Patterns to Avoid

- **Checking `finish_reason` after `model_validate_json()` raises:** `ValidationError` will have been caught and tenacity will retry before the caller sees the response object. Must check `finish_reason` before or during JSON parsing, not after.
- **Adding adaptive backoff to individual adapters (crawl4ai, playwright):** D-10 is explicit — adapters stay thin. Backoff state belongs in the orchestration layer (`_crawl_loop`/`PerHostLimiter`).
- **Running `ingest_url()` directly in the async event loop:** `ingest_url()` uses `httpx.Client` (synchronous). Calling it directly from an async function blocks the event loop. Use `run_in_executor`.
- **Caching partial enrichment under the normal content-hash key:** D-16 is the enforcement mechanism. The `partial:` prefix must be applied to the cache key before any registry write.
- **Filtering linked links by same-domain constraint:** Linked documents (PDFs, DOCX) on other domains ARE valid follows (e.g., a healthcare site linking to a CDC PDF). The existing `_extract_links` same-domain filter applies to HTML page traversal only. Linked-doc extraction (`_extract_linked_docs`) must use the extension filter, NOT the domain filter.
- **Using `source_config` directly (flat) for rate_limit lookups:** The correct nesting is `source_config.get("crawl_config", {}).get("rate_limit_seconds")`. The outer `source_config` dict also carries `domain`, `tags`, `organization` — the crawl config is one sub-key.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP status code on 429 | Custom HTTP parser in crawl loop | `CrawlPageResult.http_status_code` field + adapter translates | Adapters already have the status code from the network layer |
| Balanced-brace scan | Complex parser library | Simple in-Python scan (Pattern 4 above) | JSON truncation recovery only needs outermost-brace balance; no full parse needed |
| SSRF guard for linked docs | New SSRF check | `validate_public_url()` (ingest.py:99) | Already handles all private IP ranges, redirect chains, IPv6-mapped addresses |
| Source dedup for linked docs | Custom hash comparison | `ingest_url()` existing content-hash dedup | `ingest_url()` already checks `get_source_by_normalized_url` and `get_artifact_by_hash` |
| Per-host asyncio lock | Custom locking | `PerHostLimiter._get_lock(key)` (ratelimit.py:107) | Already exists and is event-loop-aware |
| Bulk source listing with domain filter | New ORM query | Pattern from `api/app.py:1176` (Python-side filter) | DB-agnostic, avoids JSONB-specific syntax; already proven correct |

---

## Common Pitfalls

### Pitfall 1: CrawlPageResult has no http_status_code field

**What goes wrong:** `CrawlPageResult.status` is a 3-value string (`'complete'`, `'failed'`, `'robots_blocked'`) [VERIFIED: codebase — protocols.py:426]. There is no `http_status_code: int` field. The orchestrator loop in `_crawl_loop` cannot distinguish a 429 Too Many Requests from a 404 Not Found — both arrive as `status='failed'` with `error='...'`.

**Why it happens:** The protocol was designed for simple pass/fail crawl results. HTTP status codes were left to adapters (crawl4ai surfaces `status_code` via `getattr`).

**How to avoid:** Add `http_status_code: Optional[int] = None` to `CrawlPageResult` dataclass (protocols.py). Update crawl4ai adapter to set this field (already reads `getattr(result, "status_code", None)` at adapter line 118). The playwright adapter can extract it from Playwright's response. The orchestrator loop checks `result.http_status_code in (429, 403)` to trigger backoff.

**Warning signs:** Adaptive backoff never triggering during testing even when simulating rate limiting.

### Pitfall 2: `_call_llm_for_enrichment` retry intercepts truncation

**What goes wrong:** `_call_llm_for_enrichment` is decorated with `@retry(..., retry=retry_if_exception_type((RuntimeError, ValidationError)))`. Truncated JSON fails `model_validate_json()` with `ValidationError`. Tenacity retries the call instead of recovering the prefix — burning double the LLM budget on each truncation (violates D-18).

**Why it happens:** The `ValidationError` retry was added for malformed JSON from flaky models. Truncation is a different failure mode.

**How to avoid:** Inside `_call_llm_for_enrichment`, check `finish_reason` BEFORE calling `model_validate_json()`. If `finish_reason == "length"`, skip the normal validation path entirely. Use `_extract_longest_valid_prefix` + `model_validate_json`. Do NOT raise `ValidationError` — return a 3-tuple (or result wrapper) with `is_partial=True`. Tenacity never sees the error.

**Warning signs:** Enrichment costs doubling when documents exceed `max_tokens`. `enrich.llm_call_failed` log entries on documents known to be truncated.

### Pitfall 3: Linked-doc ingestion blocks the async event loop

**What goes wrong:** `ingest_url()` uses `httpx.Client` (sync). Calling it directly inside `async def _crawl_loop()` blocks the event loop for the duration of each HTTP download. On pages with many PDF links, this causes crawl stalls and defeats asyncio's concurrency model.

**Why it happens:** `ingest_url()` was designed for synchronous CLI use. It was never made async.

**How to avoid:** Wrap each `ingest_url()` call with `await asyncio.get_running_loop().run_in_executor(None, ingest_url, url, name, settings=settings)`. This offloads to a thread pool. Pattern already used in `crawl_source()` for `fetch_robots` (line 102).

**Warning signs:** Crawl jobs with PDF-heavy pages taking disproportionately longer than HTML-only pages with no async yield points.

### Pitfall 4: Nested crawl_config vs flat source_config

**What goes wrong:** `source_config = get_source_crawl_config(source_id)` returns the inner `crawl_config` dict directly. If the function is written to return `source.config` instead of `source.config.get("crawl_config", {})`, then `resolve_delay(source_config, ...)` receives `{"domain": "healthcare", "tags": [...], "crawl_config": {...}}` and finds no `rate_limit_seconds` at the top level.

**Why it happens:** The CONTEXT.md has two uses of "source_config": the outer `Source.config` JSON (which holds `domain`, `tags`, `organization`, `crawl_config`) and the inner `crawl_config` sub-dict. D-05 says to traverse the nesting.

**How to avoid:** `get_source_crawl_config()` returns `source.config.get("crawl_config", {})` — the inner dict only. Then `resolve_delay()` receives `{"rate_limit_rps": 0.5}` or similar. Rate-limit and depth values are at the top of the returned dict, not nested further.

**Warning signs:** `resolve_delay()` always returning the global default despite `crawl_config` entries being present in `sources.yaml`.

### Pitfall 5: crawl-all batch silently skips sources with no crawl_config

**What goes wrong:** `crawl_all_sources()` iterates all sources. Sources registered without a `crawl_config` (e.g., manually registered via `klake ingest-url`, not via `domain-init`) will have `get_source_crawl_config()` return `{}`. This is correct behavior (falls through to global defaults), but if the code inadvertently checks `if source_config:` to skip rather than to override, these sources are never crawled.

**How to avoid:** `source_config = {}` is still a valid config (means "use global defaults"). The `if source_config and "rate_limit_seconds" in source_config:` guard in `resolve_delay()` already handles this correctly. The `crawl_all_sources()` loop must call `crawl_source()` for ALL sources regardless of whether `get_source_crawl_config()` returns an empty dict.

### Pitfall 6: Linked-doc ingest_url needs source_name derived from URL, not from parent

**What goes wrong:** `ingest_url(link_url, source_name=parent_source_name)` — using the parent HTML page's source name for a PDF from a different domain. `ingest_url` calls `register_source(name=source_name)` which uses this name for the `Source` row. If the parent name is "www.cms.gov" but the PDF is from "downloads.cms.gov", the source name should still be derived from the PDF's URL.

**How to avoid:** Use `_name_from_url(link_url)` as the `source_name` argument, not the parent page's source name. This is already available as a module-level function in `crawl.py:487`.

---

## Code Examples

### CRAWL-01: Wire per-source config (the exact bug line)

```python
# Source: crawl.py:296 — current buggy line [VERIFIED: codebase]
# BEFORE:
source_config = None
delay = resolve_delay(source_config, robots_crawl_delay, settings.crawl.rate_limit_seconds)

# AFTER (add lookup above the existing line):
with get_session() as session:
    source_config = registry_repo.get_source_crawl_config(session, source_id)
delay = resolve_delay(source_config, robots_crawl_delay, settings.crawl.rate_limit_seconds,
                      backoff_extra=limiter.backoff_extra(url, settings.crawl.rate_limit_seconds))
```

### CRAWL-02: crawl_all_sources return shape

```python
# Source: D-09 decision [VERIFIED: context.md]
async def crawl_all_sources(domain: Optional[str] = None, settings: Optional[Settings] = None) -> dict:
    s = settings or get_settings()
    with get_session() as session:
        sources = registry_repo.list_sources_for_crawl_all(session, domain=domain)
    total = len(sources)
    succeeded = 0
    failed = 0
    results = []
    for source in sources:
        try:
            result = await crawl_source(source.url, settings=s)
            results.append({"source_id": source.id, "status": "ok", **result})
            succeeded += 1
        except Exception as exc:
            log.warning("crawl_all.source_failed", source_id=source.id, error=str(exc))
            results.append({"source_id": source.id, "status": "failed", "error": str(exc)})
            failed += 1
    return {"total": total, "succeeded": succeeded, "failed": failed, "results": results}
```

### ENRICH-07: finish_reason detection point

```python
# Source: enrich.py:156-202 — _call_llm_for_enrichment [VERIFIED: codebase]
# The response object is available at line ~200. finish_reason lives at:
finish_reason = response.choices[0].finish_reason
# "stop" = complete, "length" = truncated, None/other = anomalous

# Return type should become a 3-tuple or named result:
# (EnrichmentResult, response_object, is_partial: bool)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hard-coded `source_config = None` in crawl loop | Per-source lookup from registry | Phase 8 | Enables per-source rate limits and depths |
| Fixed rate limit (global only) | Three-tier: source > robots > global, plus adaptive backoff | Phase 8 | Polite crawling that respects server signals |
| ValidationError inferred as truncation | `finish_reason == "length"` as authoritative truncation signal | Phase 8 | Avoids unnecessary retries; recovers partial data |
| Crawl HTML only — linked PDFs ignored | Post-bronze linked .pdf/.docx ingestion via `ingest_url()` | Phase 8 | Captures embedded regulatory documents |

**Deprecated/outdated:**
- `source_config = None` at crawl.py:296: replaced by registry lookup in Phase 8.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Balanced-brace scan (Pattern 4) correctly handles nested JSON objects and string escaping | Code Examples | Partial prefix extraction fails silently; falls back to no recovery; low risk — fallback is log + return None |
| A2 | crawl4ai returns HTTP status code as `getattr(result, "status_code", None)` consistently across 429/403 responses | Pitfall 1 | Adaptive backoff never triggers on crawl4ai adapter; medium risk |
| A3 | Playwright adapter can surface HTTP status code from Playwright's response object | Pitfall 1 | Same as A2 for playwright-served crawls |
| A4 | LiteLLM's `response.choices[0].finish_reason` is reliably `"length"` for token-limit truncation (not `None` or `"stop"`) | ENRICH-07 pattern | Truncation undetected; falls through to ValidationError path and existing retry; medium risk |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed.
*(Table is not empty — see above)*

---

## Open Questions (RESOLVED)

1. **Does CrawlPageResult need a new field, or should adapters map 429/403 to a distinct status string?**
   - What we know: `CrawlPageResult.status` has three string values. Adding `http_status_code: Optional[int]` is clean. Alternatively, a new status string `"rate_limited"` maps 429/403 without a schema change to the dataclass.
   - What's unclear: Whether changing `CrawlPageResult` breaks any existing tests (integration tests check `status == "failed"`).
   - Recommendation: Add `http_status_code: Optional[int] = None` to `CrawlPageResult` — cleaner, backward-compatible (field defaults to None), does not change existing status string values that tests assert.
   - RESOLVED: Add `http_status_code: Optional[int] = None` to `CrawlPageResult` dataclass (Plan 03 Task 3). Backward-compatible default preserves all existing `status == "failed"` assertions.

2. **Should `ingest_url()` be async or remain sync?**
   - What we know: `ingest_url()` is sync (httpx.Client). INGEST-10 requires calling it from async `_crawl_loop`.
   - What's unclear: Whether to make `ingest_url()` async (httpx.AsyncClient) or use `run_in_executor`.
   - Recommendation: Use `run_in_executor` — avoids refactoring `ingest_url()` and its callers (CLI, API, Dagster assets). Lower risk for Phase 8.
   - RESOLVED: Use `run_in_executor` wrapping the synchronous `ingest_url()` call inside `_crawl_loop` (Plan 05 Task 2). No changes to `ingest_url()` or its existing callers.

---

## Environment Availability

No new external dependencies. The following are required and confirmed available in the existing dev environment:

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL | Source config lookup, artifact writes | Assumed running | 16+ | — |
| MinIO | Artifact storage (`_write_artifacts`) | Assumed running | latest | — |
| LiteLLM proxy | Enrichment LLM calls | Assumed running | existing | — |
| Qdrant | Not touched in Phase 8 | — | — | — |

Step 2.6 skipped for per-file code changes — no new external service dependencies introduced.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest with asyncio_mode = "auto" |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/unit/ -v -x` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CRAWL-01 | `get_source_crawl_config` returns crawl_config sub-dict | unit | `pytest tests/unit/test_robots_ratelimit.py -x` | Extend existing |
| CRAWL-01 | `resolve_delay` accepts `rate_limit_rps` input | unit | `pytest tests/unit/test_robots_ratelimit.py -x` | Extend existing |
| CRAWL-01 | `resolve_delay` `backoff_extra` parameter | unit | `pytest tests/unit/test_robots_ratelimit.py -x` | Extend existing |
| CRAWL-02 | `crawl_all_sources` returns summary dict with total/succeeded/failed | unit | `pytest tests/unit/test_crawl_all.py -x` | Wave 0 |
| CRAWL-02 | `klake crawl-all` CLI exits 0 with valid output | unit | `pytest tests/unit/test_crawl_all.py -x` | Wave 0 |
| CRAWL-03 | `PerHostLimiter.record_error` / `reset_errors` / `backoff_extra` | unit | `pytest tests/unit/test_robots_ratelimit.py::TestAdaptiveRateLimiter -x` | Wave 0 |
| CRAWL-03 | Backoff capped at MAX_BACKOFF_SECONDS | unit | `pytest tests/unit/test_robots_ratelimit.py::TestAdaptiveRateLimiter -x` | Wave 0 |
| ENRICH-07 | `finish_reason == "length"` triggers prefix recovery, not retry | unit | `pytest tests/unit/test_enrich.py::test_partial_enrichment -x` | Wave 0 |
| ENRICH-07 | Partial result uses `partial:` cache key | unit | `pytest tests/unit/test_enrich.py::test_partial_cache_key -x` | Wave 0 |
| ENRICH-07 | Complete result lookup returns None for partial cache entry | unit | `pytest tests/unit/test_enrich.py::test_partial_not_returned_as_complete -x` | Wave 0 |
| INGEST-10 | `_extract_linked_docs` returns only .pdf/.docx links | unit | `pytest tests/unit/test_linked_doc_ingest.py -x` | Wave 0 |
| INGEST-10 | SSRF-blocked linked link counted as failed, does not abort | unit | `pytest tests/unit/test_linked_doc_ingest.py -x` | Wave 0 |
| INGEST-10 | `MAX_LINKED_DOCS_PER_PAGE` cap enforced | unit | `pytest tests/unit/test_linked_doc_ingest.py -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/ -v -x`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_crawl_all.py` — covers CRAWL-02 (crawl_all_sources + CLI)
- [ ] `tests/unit/test_robots_ratelimit.py::TestAdaptiveRateLimiter` — covers CRAWL-03 (add to existing file)
- [ ] `tests/unit/test_enrich.py::test_partial_enrichment` and `test_partial_cache_key` — covers ENRICH-07
- [ ] `tests/unit/test_linked_doc_ingest.py` — covers INGEST-10

---

## Security Domain

`security_enforcement: true` (confirmed in config.json)

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No new auth surfaces |
| V3 Session Management | no | No session changes |
| V4 Access Control | no | No new access control surfaces |
| V5 Input Validation | yes | `validate_public_url()` on every followed link; Pydantic bounds on `EnrichmentResult`; `max_length` on tag params |
| V6 Cryptography | no | Content hashing uses xxhash (existing); no new crypto |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SSRF via linked document URL | Spoofing / Elevation of Privilege | `validate_public_url()` called before every `ingest_url()` call (D-21); blocks RFC-1918, loopback, cloud IMDS |
| SSRF via redirect in followed link | Spoofing | `_fetch_with_retry()` already validates redirect hops (ingest.py:191); `ingest_url()` reuses this |
| Prompt injection via crawled HTML content enriched as LLM input | Tampering | `_ENRICHMENT_SYSTEM_PROMPT` already includes explicit injection mitigation; `EnrichmentResult` bounds; `is_partial` flag carries no attacker-controlled data |
| Partial JSON recovery exposing injected content | Tampering | `model_validate_json(prefix)` on partial prefix still validates against `EnrichmentResult` field bounds — attacker cannot smuggle extra fields through partial recovery |
| Infinite loop via crawler following linked docs that link to more docs | Denial of Service | `MAX_LINKED_DOCS_PER_PAGE` cap (default 10) + `_seen_urls` dedup prevents expansion; linked docs are ingested but NOT re-crawled for further links |
| Rate-limit amplification via crawl-all | Denial of Service | Sequential loop (D-06) + per-host adaptive backoff ensure crawl-all cannot overwhelm a target more than single-source crawl |

**Critical security invariant (INGEST-10):** `validate_public_url()` MUST be called before `ingest_url()` for every followed link, even though `ingest_url()` also calls it internally. The outer call is an explicit defense-in-depth layer. Both calls must remain in code — removing the outer call would be a regression.

---

## Sources

### Primary (HIGH confidence)
- `src/knowledge_lake/pipeline/crawl.py` — full file read; `source_config = None` bug confirmed at line 296; `_crawl_loop` structure confirmed
- `src/knowledge_lake/crawl/ratelimit.py` — full file read; `resolve_delay()` and `PerHostLimiter` confirmed
- `src/knowledge_lake/pipeline/enrich.py` — full file read; `_call_llm_for_enrichment` return shape, tenacity decorator, and LiteLLM response access confirmed
- `src/knowledge_lake/pipeline/ingest.py` — read lines 1-410; `ingest_url()`, `validate_public_url()`, and `_fetch_with_retry()` confirmed
- `src/knowledge_lake/registry/repo.py` — `get_domain_for_source` at line 820 confirmed as pattern; `list_sources_by_type` at line 551; no `list_all_sources` function confirmed
- `src/knowledge_lake/cli/app.py` — `cmd_crawl` at line 456 confirmed; `domain-init` source registration with `crawl_config` nesting confirmed at line 1041–1046
- `src/knowledge_lake/api/app.py` — POST /crawl-jobs at line 476; GET /sources with domain filter pattern at line 1146
- `src/knowledge_lake/plugins/protocols.py` — `CrawlPageResult` dataclass at line 426 confirmed; no `http_status_code` field
- `src/knowledge_lake/plugins/builtin/crawl4ai_adapter.py` — `getattr(result, "status_code", None)` at line 118 confirmed
- `tests/unit/test_robots_ratelimit.py` — existing test structure confirmed; extend for CRAWL-03
- `tests/unit/test_enrich.py` — existing test structure confirmed; extend for ENRICH-07
- `tests/conftest.py` — shared fixtures confirmed

### Secondary (MEDIUM confidence)
- CONTEXT.md decisions D-01 through D-24 — all locked decisions confirmed against codebase

---

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH — no new packages, all existing dependencies confirmed
- Architecture: HIGH — all touch points read and verified in code
- Pitfalls: HIGH — derived from code-verified observations (missing http_status_code, tenacity retry on ValidationError)
- Security: HIGH — SSRF patterns verified, ASVS applied to actual new surfaces

**Research date:** 2026-07-08
**Valid until:** 2026-08-07 (stable Python stdlib patterns; 30 days)
