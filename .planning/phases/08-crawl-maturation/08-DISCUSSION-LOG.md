# Phase 8: Crawl Maturation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-08
**Phase:** 8-crawl-maturation
**Mode:** `--auto` (all areas auto-selected, recommended defaults chosen without user prompts)
**Areas discussed:** crawl-config-lookup, rate-key-reconciliation, adaptive-backoff, linked-doc-ingestion, partial-json-recovery, crawl-all-design

---

## Crawl-Config Lookup (CRAWL-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Add `get_source_crawl_config()` helper to `repo.py` mirroring `get_domain_for_source` | Registry lookup once per crawl_source call; None-guard; same session handling | ✓ |
| Inline the lookup directly in `crawl.py` | Simpler but duplicates the session/None pattern | |

**Auto-selected:** `get_source_crawl_config()` helper — mirrors established pattern.
**Notes:** Replaces the `source_config = None` hard-code at line 296.

---

## Rate-Key Reconciliation (`rate_limit_rps` vs `rate_limit_seconds`)

| Option | Description | Selected |
|--------|-------------|----------|
| Accept both keys in `resolve_delay()`, convert `rps → 1/rps` | Backward-compatible; no `sources.yaml` migration needed | ✓ |
| Mandate `rate_limit_seconds` only, drop `rps` | Simpler but breaks existing healthcare `sources.yaml` entries | |

**Auto-selected:** Accept both keys at Tier 1; `rate_limit_seconds` wins if both present.
**Notes:** `rate_limit_rps → seconds` conversion via `1 / rps`.

---

## Adaptive Backoff (CRAWL-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Centralized in crawl.py page-fetch loop | Adapters stay thin; backoff is orchestration-level | ✓ |
| In each adapter (crawl4ai, scrapy, playwright) | Adapters already have rate-limit awareness (playwright) | |

**Auto-selected:** Centralized in `crawl.py` — adapters are thin; backoff belongs at orchestration level.
**Notes:** Exponential base-2, per-host, cap at `MAX_BACKOFF_SECONDS=60`; `COOLDOWN_SECONDS=30` floor after 429.

---

## Linked-Document Ingestion (INGEST-10)

| Option | Description | Selected |
|--------|-------------|----------|
| Post-bronze extraction, bounded frontier, reuse `ingest_url()` | Parent HTML always committed first; no new ingest path | ✓ |
| Pre-write extraction | Risks losing parent page artifact on link-follow failure | |

**Auto-selected:** Post-bronze, `MAX_LINKED_DOCS_PER_PAGE=10`, every link SSRF-guarded, `ingest_url()` reused.
**Notes:** Failed follows counted in `linked_docs_failed`, never abort parent crawl.

---

## Partial-JSON Recovery (ENRICH-07)

| Option | Description | Selected |
|--------|-------------|----------|
| `finish_reason == "length"` gate + balanced-brace prefix trim + `partial:` cache key | Authoritative signal; no false positives from parse errors | ✓ |
| Catch `ValidationError` and attempt recovery | Conflates truncation with malformed output; harder to distinguish | |

**Auto-selected:** `finish_reason` gate; cache under `partial:{content_hash}`; `is_partial=True` flag on result.
**Notes:** Partial results are cache misses for complete-enrichment callers; no retry loop inside enrich (D-18).

---

## `crawl-all` Design (CRAWL-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Sequential loop, `--domain` filter, per-source failure isolation | Simple; no rate-limit amplification; v2.0 appropriate | ✓ |
| Parallel/concurrent source crawls | Faster but risk amplified rate-limiting and complexity | |

**Auto-selected:** Sequential loop; fail-soft per source; CLI `klake crawl-all` + `POST /crawl-all` API.
**Notes:** Each source returns its own result dict; batch summary includes `total`, `succeeded`, `failed`.

---

## Claude's Discretion

- Exact naming of `get_source_crawl_config` vs `get_source_config` (repo.py).
- Whether `AdaptiveRateLimiter` is a new class or extension of `PerHostLimiter`.
- File placement of `crawl_all_sources()` (crawl.py or pipeline/batch.py).
- Exact field name for partial flag (`is_partial` vs `partial`) on `EnrichmentResult`.
- Whether tunable constants (`MAX_LINKED_DOCS_PER_PAGE`, `MAX_BACKOFF_SECONDS`, `COOLDOWN_SECONDS`) go in `Settings` or module-level.

## Deferred Ideas

- Parallel `crawl-all` execution — future optimization pass.
- Sitemap-first crawl strategy (SITEMAP-01) — v2.1.
- Re-crawl change detection (SCHED-02) — Phase 11.
- Quality-score propagation (QUALITY-01) — v2.1.
- Retry loop for truncated enrichment — deliberately deferred to caller (budget risk, D-18).
