---
phase: 11-crawl-scheduling
plan: "03"
subsystem: pipeline/crawl
tags: [change-detection, recrawl, signature, WORM, staleness]
dependency_graph:
  requires: [11-02]
  provides: [recrawl_source, _signature]
  affects: [pipeline/crawl.py]
tech_stack:
  added: []
  patterns: [content-hash gate, normalize-then-SHA256, SSRF-first validation]
key_files:
  created: []
  modified:
    - src/knowledge_lake/pipeline/crawl.py
decisions:
  - "D-06: reuse remove_boilerplate for the content signature (same normalizer as silver stage)"
  - "D-07: gate runs before put_raw (WORM-safe by construction)"
  - "D-08: unchanged content never reaches put_raw or crawl_source"
  - "D-09: source-level signature keyed on the seed page"
  - "D-10: per-source max_staleness_days override from crawl_config"
  - "D-11: last_crawled_at bumped on every attempt including skips"
metrics:
  duration: 4m
  completed: "2026-07-10"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 1
status: complete
---

# Phase 11 Plan 03: Change-Detection Gate Summary

Recrawl gate using normalize-then-SHA256 content signature to skip unchanged pages before any raw write or LLM spend.

## What Was Built

- **`_signature(markdown: str) -> str`**: Computes content hash by passing markdown through `remove_boilerplate` (from `pipeline.clean`) then SHA256. No second normalizer authored.
- **`_get_source_for_recrawl(source_id: str) -> dict`**: Loads source metadata (url, last_content_hash, last_crawled_at, crawl_config) in its own session so the gate doesn't require callers to hold one.
- **`async recrawl_source(source_id, *, settings=None) -> dict`**: The change-detection gate. Probes the seed URL, normalizes, computes signature, and decides:
  - **Skip path** (unchanged sig + within staleness + non-NULL hash): bumps `last_crawled_at` only via `touch_source_crawl`; `crawl_source` never called.
  - **Crawl path** (NULL hash / changed sig / stale): calls `crawl_source()` wholesale then records new `last_content_hash` + `last_crawled_at`.

## Key Design Points

1. **SSRF guard first**: `validate_public_url(url)` runs before `adapter.fetch_page(url)`.
2. **WORM-safe**: Skip path never calls `crawl_source` or `put_raw`.
3. **Single normalizer**: `remove_boilerplate` imported from `pipeline.clean` — no duplicate definition.
4. **Per-source staleness**: `crawl_config.max_staleness_days` overrides global default (D-10).
5. **Tz-aware UTC**: All datetimes use `datetime.timezone.utc`; no naive `utcnow()`.

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Reuse `remove_boilerplate` for signature | Same definition of "changed" as silver zone (D-06) |
| `isinstance(crawl_result, dict)` guard on spread | Defensive against mocked/unexpected returns |
| `_get_source_for_recrawl` as patchable helper | Tests can inject controlled source data without DB |

## Deviations from Plan

None - plan executed exactly as written.

## Threat Surface Addressed

| Threat ID | Mitigation |
|-----------|-----------|
| T-11-SSRF | `validate_public_url(url)` before `adapter.fetch_page` |
| T-11-THRASH | Normalized-text SHA256 skips unchanged pages before `put_raw` |
| T-11-WRITE | Skip path bumps only `last_crawled_at`; hash unchanged |

## Verification

```
$ pytest tests/unit/test_recrawl_gate.py -v
5 passed

$ pytest tests/unit/test_crawl_all.py tests/unit/test_linked_doc_ingest.py -q
12 passed, 1 xfailed
```

## Self-Check: PASSED

- [x] `src/knowledge_lake/pipeline/crawl.py` contains `recrawl_source`, `_signature`, `_get_source_for_recrawl`
- [x] Commit `b24e01f` exists in git log
- [x] All 5 gate tests green, no crawl vertical regressions
