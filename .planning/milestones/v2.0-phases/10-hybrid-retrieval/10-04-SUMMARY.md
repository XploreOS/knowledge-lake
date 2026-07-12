---
phase: 10-hybrid-retrieval
plan: "04"
subsystem: config,protocols
tags: [hybrid-retrieval, settings, protocols, retr-03, retr-01]
dependency_graph:
  requires: [10-01, 10-02]
  provides: [SearchSettings, VectorPoint.sparse, VectorStorePlugin.search-contract]
  affects: [10-06, 10-07]
tech_stack:
  added: []
  patterns: [nested-BaseModel-settings, additive-default-back-compat, Literal-fail-closed-validation]
key_files:
  created: []
  modified:
    - src/knowledge_lake/config/settings.py
    - src/knowledge_lake/plugins/protocols.py
    - tests/unit/test_settings_search.py
decisions:
  - "SearchSettings nested model uses Literal[hybrid,dense,sparse] for fail-closed pydantic validation at config load time (T-10-02)"
  - "VectorPoint.sparse defaults to None — additive back-compat, mirrors CrawlPageResult.http_status_code pattern"
  - "VectorStorePlugin.search keyword-only params mode/sparse_query/offset with additive defaults — existing callers unaffected until opt-in (D-09)"
metrics:
  duration: "4m"
  completed: "2026-07-10"
  tasks: 2
  files: 3
status: complete
---

# Phase 10 Plan 04: Config + Protocol Contracts Summary

Wave 2 — landed SearchSettings (RETR-03/D-08) and additive protocol changes (RETR-01/D-09).

**One-liner:** SearchSettings nested config with Literal fail-closed validation + VectorPoint.sparse optional field + VectorStorePlugin.search keyword-only mode/sparse_query/offset contract for plans 10-06 and 10-07 to build against.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | SearchSettings + Settings.search field (RETR-03, D-08, T-10-02) | 6289bce | settings.py, test_settings_search.py |
| 2 | VectorPoint.sparse + VectorStorePlugin.search signature (RETR-01, D-09) | e6df0df | protocols.py |

## Artifacts Produced

- **`SearchSettings`** (config/settings.py) — new nested `BaseModel` with `mode: Literal["hybrid","dense","sparse"] = "hybrid"`. Mirrors `IndexSettings` pattern exactly. Fail-closed: unknown values raise `ValidationError` at pydantic boundary (T-10-02).
- **`Settings.search`** field — `search: SearchSettings = Field(default_factory=SearchSettings)`, attached alongside `settings.index`. Resolved via `KLAKE_SEARCH__MODE` env var through existing `env_nested_delimiter="__"` — no custom parsing needed.
- **`VectorPoint.sparse: Optional[Any] = None`** — additive field on the dataclass; all existing constructions remain valid without modification.
- **`VectorStorePlugin.search`** Protocol — extended with keyword-only `mode="dense"`, `sparse_query=None`, `offset=0` params. Back-compat: existing callers unaffected until they pass the new kwargs.

## Verification Results

```
tests/unit/test_settings_search.py  4 passed (xfail markers removed — RED tests now green)
tests/unit (full suite)             387 passed, 19 xfailed, 21 xpassed — no regressions
VectorPoint(id='x', vector=[0.1]).sparse is None  ✓
inspect.signature(VectorStorePlugin.search) contains mode, sparse_query, offset (keyword-only)  ✓
KLAKE_SEARCH__MODE=bogus → ValidationError (fail-closed confirmed)  ✓
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — this plan is pure contract / config work. No data is wired; behavior implementation is in plans 10-06 and 10-07.

## Threat Surface Scan

No new network endpoints, auth paths, or trust-boundary changes introduced. SearchSettings adds a config-layer validation surface — the Literal constraint is the T-10-02 mitigation (present). No threat flags.

## Self-Check: PASSED

- [x] `src/knowledge_lake/config/settings.py` modified — SearchSettings class + Settings.search field present
- [x] `src/knowledge_lake/plugins/protocols.py` modified — VectorPoint.sparse + extended search signature present
- [x] `tests/unit/test_settings_search.py` modified — xfail markers removed, 4 tests pass
- [x] Commit 6289bce exists (task 1)
- [x] Commit e6df0df exists (task 2)
