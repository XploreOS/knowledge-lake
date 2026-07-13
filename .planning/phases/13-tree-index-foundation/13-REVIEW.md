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
  critical: 0
  warning: 3
  info: 2
  total: 5
status: issues_found
---

# Phase 13: Code Review Report (Iteration 3 — Final Re-review After All Fixes)

**Reviewed:** 2026-07-13
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Iteration 3 re-review. All five mandated findings are confirmed fixed. Three warnings and two info items remain: two warnings carried over from iteration 2 (unfixed by the current change set), one new warning surfaced by this pass on `PageIndexIndexer`, and two info items carried forward unchanged.

**Mandated findings status:**

| Finding | Description | Status |
|---------|-------------|--------|
| CR-01 | `page_count=None` → `int(None)` TypeError | **FIXED** — both `tree_index.py:263` and `pageindex_indexer.py:79` use `int(... or 1)` |
| WR-01 | Budget scope wrong in production and tests | **FIXED** — `scope="tree_index"` in `tree_index.py:295,347`; tests at lines 452,467 also corrected |
| WR-02 | `generate_dataset` else branch was silent no-op | **FIXED** — `assets.py:675-679` raises `ValueError` for unknown kind |
| WR-03 | Protocol/implementation signature divergence | **FIXED** — `PageIndexIndexer.build_index` signature identical to `IndexerPlugin.build_index` Protocol |
| IN-01 | Phantom status assertion accepted wrong values | **FIXED** — `test_tree_index.py:173` now asserts `== "tree_indexed"` |

---

## Warnings

### WR-01: `PageIndexIndexer.build_index` returns empty roots for empty-sections document

**File:** `src/knowledge_lake/plugins/builtin/pageindex_indexer.py:79-88`

**Issue:** When `parsed_doc.sections` is empty, `build_index` delegates to `_build_deterministic_tree([], page_count)` which returns `[]`. The returned `TreeIndex` has `roots=[]`. The pipeline-layer `tree_index()` function (lines 265-279) has an explicit fallback that creates a single synthetic root node (`node_id="§1"`, `title=metadata.get("title") or "§1"`) when sections is empty. Any caller reaching the tree-index layer through the plugin seam (`get_indexer(settings).build_index(doc)`) receives structurally different output from the same document, silently breaking any downstream consumer that iterates `tree.roots`. The broken path is latent (no current production caller wires through `get_indexer` for this purpose), but the seam contract is already inconsistent and will cause a failure when the first caller adopts it.

**Fix:** Mirror the pipeline fallback inside `build_index`:

```python
from knowledge_lake.plugins.protocols import TreeNode  # add to imports at top

def build_index(self, parsed_doc, *, mode="deterministic", metadata=None):
    from knowledge_lake.pipeline.tree_index import _build_deterministic_tree

    meta = metadata or {}
    page_count: int = int(parsed_doc.metadata.get("page_count") or 1)

    if not parsed_doc.sections:
        title = parsed_doc.metadata.get("title") or "§1"
        roots = [
            TreeNode(
                node_id="§1",
                title=title,
                summary=title,
                page_start=1,
                page_end=page_count,
                level=1,
                section_path="§1",
            )
        ]
    else:
        roots = _build_deterministic_tree(parsed_doc.sections, page_count)

    return TreeIndex(
        parsed_artifact_id=meta.get("parsed_artifact_id", ""),
        source_id=meta.get("source_id", ""),
        roots=roots,
        mode=mode,
        schema_version="1",
        content_hash="",
    )
```

---

### WR-02: `hasattr(s, "tree")` guard is permanently dead code — `else` branch unreachable

**File:** `src/knowledge_lake/pipeline/tree_index.py:233-234`

**Issue:** Line 233 accesses `s.tree.mode` with no guard. Line 234 conditionally accesses `s.tree.schema_version` behind a `hasattr` guard:

```python
effective_mode = mode if mode is not None else s.tree.mode          # no guard
schema_ver = s.tree.schema_version if hasattr(s, "tree") else _TREE_SCHEMA_VERSION  # guarded
```

`Settings.tree` is declared as `tree: TreeSettings = Field(default_factory=TreeSettings)` in `settings.py:477`. `hasattr(s, "tree")` is always `True` for any valid `Settings` instance; the `else _TREE_SCHEMA_VERSION` branch is permanently unreachable. The asymmetric guarding also misleads readers into thinking line 233 is differently safe than line 234. The module-level `_TREE_SCHEMA_VERSION = "1"` constant (line 44) is unused since the `else` branch never executes.

**Fix:** Remove the dead guard and the unused constant:

```python
# line 234:
schema_ver = s.tree.schema_version

# Remove or comment the unused module-level constant at line 44:
# _TREE_SCHEMA_VERSION = "1"
```

---

### WR-03: `_summarize_nodes_llm` borrows fallback cost constants from the wrong settings namespace

**File:** `src/knowledge_lake/pipeline/tree_index.py:437-442`

**Issue:** When `usage.total_cost` is `None`, the cost estimate reads from the enrichment settings namespace:

```python
total_cost += (
    prompt_tokens / 1000 * s.enrich.fallback_cost_per_1k_input
    + completion_tokens / 1000 * s.enrich.fallback_cost_per_1k_output
)
```

`s.enrich` is the enrichment-stage namespace. If an operator tunes `EnrichSettings.fallback_cost_per_1k_input` for enrichment's model, the change silently affects tree-index cost accounting. `TreeSettings` has no corresponding fields. Values happen to match today because both settings share the same `cheap_model` alias default, but the cross-namespace coupling is an implicit assumption with no guard.

**Fix:** Add matching fallback cost fields to `TreeSettings` (same defaults) and read from `s.tree.*`:

```python
# settings.py — add to TreeSettings:
fallback_cost_per_1k_input: float = 0.0005
"""Fallback USD per 1k input tokens when LiteLLM usage.total_cost is None."""
fallback_cost_per_1k_output: float = 0.0015
"""Fallback USD per 1k output tokens when LiteLLM usage.total_cost is None."""

# tree_index.py lines 437-442:
total_cost += (
    prompt_tokens / 1000 * s.tree.fallback_cost_per_1k_input
    + completion_tokens / 1000 * s.tree.fallback_cost_per_1k_output
)
```

---

## Info

### IN-01: `TreeNode.summary` docstring contradicts deterministic-mode implementation

**File:** `src/knowledge_lake/plugins/protocols.py:626-627`

**Issue:** The `TreeNode.summary` field docstring reads:
> "LLM-generated or heuristic summary of the section (empty in deterministic mode)."

`_build_deterministic_tree` sets `summary=section.heading` (tree_index.py:137). Deterministic mode always assigns the heading text, never leaves summary empty. A downstream consumer that checks `if node.summary` to detect deterministic mode, or that defaults to the heading on empty summary, will behave incorrectly.

**Fix:**

```python
summary: str
"""Section summary.

In deterministic mode, equals the section heading text (same as ``title``).
In LLM mode, a 1-2 sentence LLM-generated restatement of the section heading.
Never empty for either mode.
"""
```

---

### IN-02: `PageIndexIndexer.build_index` returns `content_hash=""` without documentation

**File:** `src/knowledge_lake/plugins/builtin/pageindex_indexer.py:82-88`

**Issue:** The returned `TreeIndex` always has `content_hash=""`. This is intentional — `pipeline.tree_index.tree_index()` computes and owns the hash. But any caller who uses `get_indexer(settings).build_index(...)` and then attempts to persist the result via `create_tree_index_artifact()` will write a blank hash, violating the D-06 dedup invariant (the UNIQUE(content_hash, artifact_type) constraint allows one empty-hash row per type). There is no docstring warning.

**Fix:** Add a caller-contract note to `build_index`:

```python
def build_index(self, parsed_doc, *, mode="deterministic", metadata=None):
    """...
    NOTE: The returned ``TreeIndex.content_hash`` is always empty string.
    Callers who persist the result via the registry MUST compute and assign
    ``content_hash`` (e.g. SHA-256 of parsed_content_hash + mode + schema_version)
    before calling ``create_tree_index_artifact()`` — D-06 uniqueness depends on it.
    The ``pipeline.tree_index.tree_index()`` function handles this automatically.
    """
```

---

_Reviewed: 2026-07-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
