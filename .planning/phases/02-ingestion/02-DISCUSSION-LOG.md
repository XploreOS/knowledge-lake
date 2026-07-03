# Phase 2: Ingestion - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-03
**Phase:** 02-Ingestion
**Areas discussed:** Crawler plugin design, Dedup & idempotency, SearXNG discovery flow, Robots.txt & rate limits

---

## Crawler Plugin Design

### Q1: Crawler output format

| Option | Description | Selected |
|--------|-------------|----------|
| Raw bytes + markdown | Crawlers write raw HTML to raw zone AND produce LLM-ready markdown as bronze artifact. Two artifacts per page, full lineage. | ✓ |
| Markdown only | Only LLM-ready markdown into bronze. Raw HTML not stored separately. | |
| Raw bytes only | Only raw HTML to raw zone. Markdown conversion in Phase 3 parse step. | |

**User's choice:** Raw bytes + markdown
**Notes:** Preserves immutable raw zone principle while leveraging Crawl4AI's native markdown output.

### Q2: CrawlerPlugin protocol shape

| Option | Description | Selected |
|--------|-------------|----------|
| Single crawl() method | crawl(source_url, config) → yields CrawlResult per page. Caller handles storage. | |
| Multi-method protocol | start_crawl() → CrawlJob, poll_status(), get_results(). Supports long-running crawls. | ✓ |
| Iterator/generator | crawl() → Iterator[CrawlResult]. Streaming-friendly, caller can stop early. | |

**User's choice:** Multi-method protocol
**Notes:** Supports Scrapy's reactor model and Playwright's browser lifecycle which are inherently async/long-running.

### Q3: Crawl job state tracking for resume

| Option | Description | Selected |
|--------|-------------|----------|
| Registry Job table | Use existing Job model. Store crawl state in job metadata JSON. | |
| Separate crawl_state table | New table with job_id, url, status, fetched_at. More structured. | ✓ |
| Filesystem checkpoint | Crawl state as JSON checkpoint in S3. Like Scrapy's JOBDIR. | |

**User's choice:** Separate crawl_state table
**Notes:** More queryable and structured than JSON blob approach.

### Q4: Crawler responsibility division

| Option | Description | Selected |
|--------|-------------|----------|
| Role-based division | User picks crawler via config/CLI flag. Clear manual control. | |
| Fallback chain | Try Crawl4AI first, fall back to Playwright on JS detection. Scrapy on request only. | |
| Unified with adapters | One protocol, three adapters. Auto-select based on URL analysis. No user choice needed. | ✓ |

**User's choice:** Unified with adapters
**Notes:** System intelligence over manual selection. Config override still available.

---

## Dedup & Idempotency

### Q1: Duplicate detection strategy

| Option | Description | Selected |
|--------|-------------|----------|
| URL-first, hash-second | Normalize URL, check sources first. If new URL but same hash after fetch, link to existing. | ✓ |
| Hash-only dedup | Always fetch, deduplicate by content hash only. | |
| Both with short-circuit | Check URL first (skip if recent), then content hash. Two-layer defense. | |

**User's choice:** URL-first, hash-second
**Notes:** Avoids unnecessary network traffic for known URLs.

### Q2: Duplicate detection return behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Silent success + existing IDs | Return existing IDs as if it succeeded. Log at INFO. True idempotency. | ✓ |
| Distinct result status | Return with 'status' field: 'created' vs 'duplicate'. | |
| Skip with warning | Return None / raise DuplicateError. Caller must handle. | |

**User's choice:** Silent success + existing IDs
**Notes:** Simplifies batch ingestion logic. Callers don't need dedup awareness.

### Q3: URL normalization aggressiveness

| Option | Description | Selected |
|--------|-------------|----------|
| Conservative | Lowercase scheme+host, strip fragment, strip trailing slash. No param reordering. | ✓ |
| Moderate | Conservative + sort query params + remove known tracking params. | |
| Aggressive | Moderate + strip all query params for known static hosts. | |

**User's choice:** Conservative
**Notes:** Low false-positive risk. Can be made more aggressive later if needed.

---

## SearXNG Discovery Flow

### Q1: Discovery result handling

| Option | Description | Selected |
|--------|-------------|----------|
| Staging queue | Results go to candidates table. User approves before anything happens. | |
| Auto-register as sources | Results immediately become sources (source_type='discovered'). Crawling still explicit. | ✓ |
| Return-only (no persist) | Print to stdout. User manually adds what they want. | |

**User's choice:** Auto-register as sources
**Notes:** Less ceremony. Crawling still requires explicit trigger so no risk of unintended action.

### Q2: Metadata per discovered source

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal (URL + title) | Just URL and page title. Domain assignment later. | ✓ |
| Search context | URL, title, snippet, query, engine, timestamp. | |
| Rich with scoring | Everything + relevance score, content type detection, domain category. | |

**User's choice:** Minimal (URL + title)
**Notes:** Keep discovery lightweight. Enrichment happens at later stages.

### Q3: SearXNG integration approach

| Option | Description | Selected |
|--------|-------------|----------|
| Settings + hardcoded API | Add searxng_url to Settings. Use JSON API with httpx directly. | |
| As a plugin | DiscoveryPlugin protocol. SearXNG first implementation. Swappable later. | ✓ |
| You decide | Let planner/researcher figure it out. | |

**User's choice:** As a plugin
**Notes:** Consistent with the framework's tool-agnostic philosophy. Allows future discovery engine swaps.

---

## Robots.txt & Rate Limits

### Q1: Robots.txt checking location

| Option | Description | Selected |
|--------|-------------|----------|
| Per-host cache layer | Shared RobotsChecker service with TTL cache. Called before any fetch. | |
| Built into crawler protocol | Each CrawlerPlugin handles robots.txt internally. Crawl4AI/Scrapy do it natively. | ✓ |
| Centralized middleware | Pre-fetch middleware wrapping all outbound requests. Single enforcement point. | |

**User's choice:** Built into crawler protocol
**Notes:** Crawl4AI and Scrapy already have native robots.txt handling. Avoids redundant middleware.

### Q2: Per-host rate limit configuration

| Option | Description | Selected |
|--------|-------------|----------|
| Global default + per-source override | Default in Settings, override via Source.config JSON. | |
| Crawl-delay from robots.txt | Honor robots.txt Crawl-delay. Fall back to default. No manual config. | |
| Both combined | Three-tier: per-source config > robots.txt Crawl-delay > global default. | ✓ |

**User's choice:** Both combined
**Notes:** Maximum flexibility. Operator always has final say via per-source override.

### Q3: Disallowed path handling

| Option | Description | Selected |
|--------|-------------|----------|
| Skip silently + log | Skip URL, log at INFO, continue. Skipped URLs in job metadata. | |
| Record as 'blocked' in crawl_state | Mark status='robots_blocked' in crawl_states table. Visible in reports. | ✓ |
| Fail the page, warn on majority | Skip individuals, warn if >50% blocked. Suggest reviewing source. | |

**User's choice:** Record as 'blocked' in crawl_state
**Notes:** Provides transparency. User can see exactly what was blocked and why.

---

## Claude's Discretion

- CrawlJob data structure internals
- Exact auto-selection heuristics for crawler choice
- URL normalization implementation details
- SearXNG API query construction
- crawl_states migration schema specifics
- Retry/backoff parameters
- CLI command naming
- API endpoint design

## Deferred Ideas

- None — discussion stayed within phase scope.
