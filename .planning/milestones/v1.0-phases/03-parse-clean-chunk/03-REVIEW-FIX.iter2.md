---
phase: 03-parse-clean-chunk
fixed_at: 2026-07-05T03:30:00Z
review_path: .planning/phases/03-parse-clean-chunk/03-REVIEW.md
iteration: 2
findings_in_scope: 1
fixed: 1
skipped: 0
status: all_fixed
---

# Phase 03: Code Review Fix Report

**Fixed at:** 2026-07-05
**Source review:** .planning/phases/03-parse-clean-chunk/03-REVIEW.md
**Iteration:** 2

**Summary:**
- Findings in scope: 1 (1 Critical, 0 Warning)
- Fixed: 1
- Skipped: 0

## Fixed Issues

### CR-01: `test_fallback_chain.py` — all four tests patch a dead code path after WR-03 refactor

**Files modified:** `tests/unit/test_fallback_chain.py`
**Commit:** `cb9fb57`
**Applied fix:** Replaced all four `patch("knowledge_lake.plugins.resolver.resolve", ...)` usages with `patch("knowledge_lake.plugins.resolver.entry_points", ...)` targeting the function `parse_with_fallback` actually calls since the WR-03 refactor.

Key changes:
- Added `from importlib.metadata import entry_points as real_entry_points` import so the mock can forward non-parser groups to the real implementation.
- Added `_FakeEP` class with `.name` and `.load()` matching the `importlib.metadata.EntryPoint` interface that `parse_with_fallback` uses.
- Added `_make_entry_points_mock(ep_map)` helper that builds a `side_effect` callable: for `group == "knowledge_lake.parsers"` it returns a list of `_FakeEP` objects keyed from `ep_map`; for all other groups it delegates to the real `entry_points()`. Each `_FakeEP.load()` returns a factory that accepts `**kwargs` so the tika `factory(tika_server_url=...)` call works transparently.
- Removed all four `_side_resolve` inner functions (now obsolete).
- Updated all four test functions to use `_make_entry_points_mock({name: mock_instance, ...})` with the appropriate name/mock pairs. For `test_unavailable_parser_skipped`, `"missing"` is absent from the ep_map so the `for/else` inside `parse_with_fallback` correctly raises `LookupError`, which is caught and causes the chain to advance to `"b"`.

All 4 tests pass after the fix (verified: `uv run pytest tests/unit/test_fallback_chain.py -v` → 4 passed in 0.53s).

---

_Fixed: 2026-07-05_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
