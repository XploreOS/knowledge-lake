---
phase: 08-crawl-maturation
plan: "02"
subsystem: crawl
tags: [infrastructure, registry, ratelimit, protocols, adapter, tdd, crawl, adaptive-backoff]
dependency_graph:
  requires:
    - 08-01 (Wave 0 test scaffold — xfail stubs that this plan turns green)
  provides:
    - src/knowledge_lake/registry/repo.py (get_source_crawl_config, list_sources_for_crawl_all)
    - src/knowledge_lake/crawl/ratelimit.py (MAX_BACKOFF_SECONDS, COOLDOWN_SECONDS, extended resolve_delay, adaptive PerHostLimiter)
    - src/knowledge_lake/plugins/protocols.py (CrawlPageResult.http_status_code field)
    - src/knowledge_lake/plugins/builtin/crawl4ai_adapter.py (http_status_code set on all return paths)
  affects:
    - 08-03 (crawl orchestrator reads get_source_crawl_config and uses adaptive PerHostLimiter)
    - 08-04 (crawl-all command uses list_sources_for_crawl_all)
tech_stack:
  added: []
  patterns:
    - TDD RED/GREEN cycle for all additive repo and ratelimit changes
    - Module-level exported constants (MAX_BACKOFF_SECONDS, COOLDOWN_SECONDS)
    - Backward-compatible signature extension with default parameters (backoff_extra=0.0)
    - Python-side domain filter over SQLAlchemy query results (database-agnostic)
    - Additive dataclass field with Optional default (http_status_code: Optional[int] = None)
key_files:
  created: []
  modified:
    - src/knowledge_lake/registry/repo.py
    - src/knowledge_lake/crawl/ratelimit.py
    - src/knowledge_lake/plugins/protocols.py
    - src/knowledge_lake/plugins/builtin/crawl4ai_adapter.py
    - tests/unit/test_crawl_all.py
decisions:
  - get_source_crawl_config returns inner crawl_config sub-dict (not full Source.config) per D-05 nesting requirement
  - resolve_delay rate_limit_seconds wins over rate_limit_rps when both present (D-03)
  - backoff_extra has default of 0.0 making it fully backward-compatible; max(tier, tier+extra) ensures floor is raised not replaced
  - PerHostLimiter extended (not new class) to carry error count state per D-10 discretion
  - T-08-02-01 guard: rps <= 0 falls through to global_default to prevent divide-by-zero from attacker-influenced config
  - http_status_code defaults to None for backward compatibility with all existing CrawlPageResult constructions
metrics:
  duration: "15m"
  completed_date: "2026-07-08"
  tasks_completed: 3
  files_changed: 5
status: complete
requirements:
  - CRAWL-01
  - CRAWL-03
---

# Phase 08 Plan 02: Infrastructure Layer Summary

Infrastructure layer for Phase 8: four additive changes to the registry, rate-limit, protocol, and adapter layers providing the foundation the crawl orchestrator (Plan 3) depends on.

## What Was Built

### Task 1: repo.py — get_source_crawl_config + list_sources_for_crawl_all (TDD)

**`get_source_crawl_config(session, source_id) -> dict`**
- Returns `source.config.get("crawl_config", {})` — the inner sub-dict only (D-05)
- Returns `{}` if source is missing, `source.config` is None, or `crawl_config` key absent
- Mirrors `get_domain_for_source` pattern exactly (D-01): same None-guard, same session handling

**`list_sources_for_crawl_all(session, domain=None) -> list[Source]`**
- Returns all Source rows ordered by `created_at` ascending
- Optional `domain` kwarg filters Python-side: `[s for s in all if (s.config or {}).get("domain") == domain]`
- Database-agnostic (avoids JSONB-specific SQL), mirrors `api/app.py:1176` pattern

**Tests added:** `TestSourceCrawlConfig` (4 tests) and `TestListSourcesForCrawlAll` (3 tests) in `tests/unit/test_crawl_all.py` — all pass green.

### Task 2: ratelimit.py — extended resolve_delay + adaptive PerHostLimiter (TDD)

**Module-level constants:**
- `MAX_BACKOFF_SECONDS: float = 60.0` — per-host exponential backoff cap (D-11)
- `COOLDOWN_SECONDS: float = 30.0` — minimum post-429 wait (D-13)

**`resolve_delay` extended:**
- New `backoff_extra: float = 0.0` parameter — additive floor raiser (D-12)
- New Tier 1 fallback: `rate_limit_rps` converted via `1/rps` when `rate_limit_seconds` absent (D-03)
- `rate_limit_seconds` wins if both present; rps <= 0 falls through to global_default (T-08-02-01 guard)
- Backward-compatible: all existing callers with `backoff_extra=0.0` see identical behavior

**`PerHostLimiter` extended:**
- `_consecutive_errors: dict[str, int]` and `_cooldown_until: dict[str, float]` added in `__init__`
- `record_error(url)` — increments count + sets cooldown deadline
- `reset_errors(url)` — clears both dicts for the host key
- `backoff_extra(url, base_delay=1.0)` — returns `min(base_delay * 2**n, MAX_BACKOFF_SECONDS)` or 0.0
- `consecutive_errors` read-only property exposes error dict
- `wait()` gains cooldown check before normal last-fetch sleep (D-13)

**Previously-xfail stubs now XPASS:** 6 tests in `TestAdaptiveRateLimiter` + 2 in `TestResolveDelay`

### Task 3: protocols.py + crawl4ai_adapter.py — CrawlPageResult.http_status_code

**`CrawlPageResult.http_status_code: int | None = None`** added in protocols.py after `error` field.
- Backward-compatible: defaults to None; all existing constructions unchanged
- Enables crawl orchestrator to detect 429/403 for adaptive backoff (CRAWL-03, Pitfall 1)

**crawl4ai_adapter.py updated** (3 return paths):
- `robots_blocked` path: `http_status_code=403`
- `failed` path: `http_status_code=status_code` (from `getattr(result, "status_code", None)`)
- `complete` path: `http_status_code=getattr(result, "status_code", None)`

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | 2cf1ace | feat(08-02): add get_source_crawl_config and list_sources_for_crawl_all to repo.py |
| Task 2 | 6c8121d | feat(08-02): extend resolve_delay and add adaptive PerHostLimiter |
| Task 3 | 788a4e4 | feat(08-02): add http_status_code field to CrawlPageResult and wire in crawl4ai adapter |

## Verification Results

```
pytest tests/unit/ -v -x
346 passed, 9 xfailed, 27 xpassed, 17 warnings
```

```
grep -c "get_source_crawl_config" src/knowledge_lake/registry/repo.py  # 2
grep -c "list_sources_for_crawl_all" src/knowledge_lake/registry/repo.py  # 2
grep -c "rate_limit_rps" src/knowledge_lake/crawl/ratelimit.py  # 4
grep -c "backoff_extra" src/knowledge_lake/crawl/ratelimit.py  # 13
grep -c "http_status_code" src/knowledge_lake/plugins/protocols.py  # 1
grep -c "http_status_code" src/knowledge_lake/plugins/builtin/crawl4ai_adapter.py  # 3
```

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface Scan

No new network endpoints, auth paths, or schema migrations introduced.

**T-08-02-01 mitigated:** `resolve_delay` guards against `rate_limit_rps <= 0` (attacker-influenced source config divide-by-zero) — falls through to `global_default`.

**T-08-02-02 accepted:** `MAX_BACKOFF_SECONDS` caps per-host backoff at 60s. Per-host scope limits blast radius; attacker must control the target server to trigger.

**T-08-02-03 accepted:** `CrawlPageResult.http_status_code` is set from adapter-side network response; informs backoff decisions only; does not cross into auth/storage trust boundary.

## Self-Check: PASSED

- [x] `src/knowledge_lake/registry/repo.py` — `get_source_crawl_config` present (2 occurrences)
- [x] `src/knowledge_lake/registry/repo.py` — `list_sources_for_crawl_all` present (2 occurrences)
- [x] `src/knowledge_lake/crawl/ratelimit.py` — `MAX_BACKOFF_SECONDS`, `COOLDOWN_SECONDS` present (9 occurrences)
- [x] `src/knowledge_lake/crawl/ratelimit.py` — `backoff_extra` present (13 occurrences)
- [x] `src/knowledge_lake/plugins/protocols.py` — `http_status_code` present (1 occurrence)
- [x] `src/knowledge_lake/plugins/builtin/crawl4ai_adapter.py` — `http_status_code` present (3 occurrences)
- [x] Commit 2cf1ace exists
- [x] Commit 6c8121d exists
- [x] Commit 788a4e4 exists
- [x] Full unit suite passes: 346 passed, 0 FAILED, 0 ERROR
