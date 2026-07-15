---
phase: 13-tree-index-foundation
reviewed: 2026-07-13T00:00:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - src/knowledge_lake/config/settings.py
  - src/knowledge_lake/dagster_defs/assets.py
  - src/knowledge_lake/dagster_defs/definitions.py
  - src/knowledge_lake/ids.py
  - src/knowledge_lake/pipeline/tree_index.py
  - src/knowledge_lake/plugins/builtin/__init__.py
  - src/knowledge_lake/plugins/builtin/pageindex_indexer.py
  - src/knowledge_lake/plugins/protocols.py
  - src/knowledge_lake/plugins/resolver.py
  - src/knowledge_lake/registry/repo.py
  - tests/unit/test_builtin_plugins.py
  - tests/unit/test_registry.py
  - tests/unit/test_tree_index.py
  - tests/unit/test_tree_index_asset.py
findings:
  critical: 2
  warning: 3
  info: 2
  total: 7
status: issues_found
---

# Phase 13: Code Review Report (re-review after WR-01 scope fix)

**Reviewed:** 2026-07-13
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Re-review triggered after the WR-01 fix changed `pipeline/tree_index.py` LLM spend scope from `"global"` to `"tree_index"`. The production code is now correct: both the budget-cap read (line 295) and the spend write (line 347) use `scope="tree_index"`. However, `tests/unit/test_tree_index.py` was not updated to match. Two stale `scope="global"` references remain in `test_llm_mode_budget_cap` — one causes the happy-path spend assertion to fail unconditionally, the other prevents the budget cap from ever being reached, rendering the budget-exceeded sub-test permanently broken. Both are BLOCKERs for CI.

Three pre-existing warnings carry forward: a dead-code `hasattr` guard, cross-stage settings coupling in the LLM cost fallback path, and a loose status assertion in the deterministic tree test that accepts phantom values. Two info-level items remain from the protocol/plugin layer.

---

## Critical Issues

### CR-01: Happy-path spend assertion reads from wrong scope — fails unconditionally

**File:** `tests/unit/test_tree_index.py:452`

**Issue:** After the happy-path LLM run, the test verifies `record_llm_spend` was called:
```python
with Session(engine) as check:
    spend_after = registry_repo.get_llm_spend(check, scope="global")
assert spend_after > 0, "record_llm_spend must have been called after LLM mode"
```
After WR-01, `tree_index()` writes spend to `scope="tree_index"` (line 347 of `tree_index.py`). Reading from `scope="global"` returns the `repo.get_llm_spend` default of `0.0`. `0.0 > 0` is `False` — this assertion fires unconditionally on every run. The test always fails regardless of whether the production code is correct.

**Fix:**
```python
# tests/unit/test_tree_index.py line 452
# Before (stale scope):
spend_after = registry_repo.get_llm_spend(check, scope="global")
# After (matches production):
spend_after = registry_repo.get_llm_spend(check, scope="tree_index")
```

---

### CR-02: Budget-exceeded path never fires — spend seeded into wrong scope

**File:** `tests/unit/test_tree_index.py:467`

**Issue:** The budget-exceeded sub-test seeds the full budget into `scope="global"`:
```python
registry_repo.record_llm_spend(s3, "global", budget_usd)
```
After WR-01, the production budget check reads from `scope="tree_index"` (line 295 of `tree_index.py`). The in-memory `"tree_index"` spend row is `0.0`; `0.0 >= budget_usd` (5.0) is `False`. The budget cap never triggers. `tree_index()` proceeds normally and returns `status="tree_indexed"`. The assertion at line 482 (`assert budget_result.get("status") == "skipped_budget_exceeded"`) then fires. This sub-test always fails — the budget enforcement path is completely untested since the WR-01 fix.

**Fix:**
```python
# tests/unit/test_tree_index.py line 467
# Before (stale scope — cap never reached):
registry_repo.record_llm_spend(s3, "global", budget_usd)
# After (matches production budget-check scope):
registry_repo.record_llm_spend(s3, "tree_index", budget_usd)
```

---

## Warnings

### WR-01: `hasattr(s, "tree")` guard is dead code — else branch unreachable

**File:** `src/knowledge_lake/pipeline/tree_index.py:234`

**Issue:**
```python
schema_ver = s.tree.schema_version if hasattr(s, "tree") else _TREE_SCHEMA_VERSION
```
`Settings.tree` is declared as `tree: TreeSettings = Field(default_factory=TreeSettings)` (settings.py line 477). `hasattr(s, "tree")` is always `True` for any valid `Settings` instance. The `else _TREE_SCHEMA_VERSION` branch is permanently unreachable. The module-level `_TREE_SCHEMA_VERSION = "1"` constant is defined but never read.

**Fix:** Remove the guard and the unused constant:
```python
# line 234:
schema_ver = s.tree.schema_version

# Remove the module-level constant at line 44:
# _TREE_SCHEMA_VERSION = "1"  -- delete this line
```

---

### WR-02: `_summarize_nodes_llm` borrows fallback cost constants from `s.enrich` namespace

**File:** `src/knowledge_lake/pipeline/tree_index.py:437-442`

**Issue:** When `usage.total_cost` is `None`, the cost fallback reads:
```python
total_cost += (
    prompt_tokens / 1000 * s.enrich.fallback_cost_per_1k_input
    + completion_tokens / 1000 * s.enrich.fallback_cost_per_1k_output
)
```
`s.enrich` is the enrichment-stage settings namespace. If `EnrichSettings.fallback_cost_per_1k_input` is tuned for enrichment's model, the change silently applies to tree-index cost accounting as well. Since `tree.model_alias` defaults to `cheap_model` (same as `enrich.model_alias`), the values happen to match today, but the coupling is an implicit assumption. `TreeSettings` has no corresponding fields.

**Fix:** Add matching fallback cost fields to `TreeSettings` (same defaults) and read from `s.tree.*`:
```python
# settings.py — add to TreeSettings:
fallback_cost_per_1k_input: float = 0.0005
fallback_cost_per_1k_output: float = 0.0015

# tree_index.py lines 437-442:
total_cost += (
    prompt_tokens / 1000 * s.tree.fallback_cost_per_1k_input
    + completion_tokens / 1000 * s.tree.fallback_cost_per_1k_output
)
```

---

### WR-03: Loose success-status assertion accepts phantom return values

**File:** `tests/unit/test_tree_index.py:173`

**Issue:**
```python
assert result["status"] in ("indexed", "tree_indexed", "complete")
```
`"indexed"` and `"complete"` are not values `tree_index()` can ever return. The function returns exactly `"tree_indexed"`, `"cached"`, or `"skipped_budget_exceeded"`. Accepting phantom values means a future regression that renames the status to `"indexed"` would pass this assertion undetected.

**Fix:**
```python
assert result["status"] == "tree_indexed", (
    f"Expected status='tree_indexed', got {result['status']!r}"
)
```

---

## Info

### IN-01: `TreeNode.summary` docstring contradicts implementation for deterministic mode

**File:** `src/knowledge_lake/plugins/protocols.py:626-627`

**Issue:** The `TreeNode.summary` field docstring reads:
> "LLM-generated or heuristic summary of the section (empty in deterministic mode)."

`_build_deterministic_tree` sets `summary=section.heading` (tree_index.py line 137). Deterministic mode always sets summary to the heading text, never leaves it empty. Downstream consumers may condition on an empty `summary` to detect deterministic mode.

**Fix:**
```python
summary: str
"""Section summary. In deterministic mode, equals the section heading text.
In LLM mode, a 1-2 sentence LLM-generated restatement of the heading."""
```

---

### IN-02: `PageIndexIndexer.build_index` always returns `content_hash=""` without documentation

**File:** `src/knowledge_lake/plugins/builtin/pageindex_indexer.py:82-88`

**Issue:** The plugin returns `TreeIndex(content_hash="")`. The hash is intentionally omitted because `pipeline.tree_index.tree_index()` computes and owns it. However, any caller who uses `get_indexer(settings).build_index(...)` directly receives a `TreeIndex` with an empty hash, silently violating the D-06 dedup invariant. There is no docstring warning on `build_index` or on the returned `TreeIndex` that `content_hash` must be populated before persisting.

**Fix:** Add a docstring note:
```python
def build_index(self, parsed_doc, *, mode="deterministic", metadata=None):
    """...
    NOTE: The returned TreeIndex.content_hash is always empty string.
    Callers who persist via the registry must compute and assign content_hash
    before calling create_tree_index_artifact() (D-06).
    """
```

---

_Reviewed: 2026-07-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
