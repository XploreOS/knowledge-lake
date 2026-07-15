---
phase: 13-tree-index-foundation
fixed_at: 2026-07-13T00:00:00Z
review_path: .planning/phases/13-tree-index-foundation/13-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 13: Code Review Fix Report

**Fixed at:** 2026-07-13
**Source review:** .planning/phases/13-tree-index-foundation/13-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (1 Critical + 3 Warning)
- Fixed: 4
- Skipped: 0

## Fixed Issues

### CR-01: `page_count=None` causes `TypeError` crash in `_build_deterministic_tree`

**Files modified:** `src/knowledge_lake/pipeline/tree_index.py`, `src/knowledge_lake/plugins/builtin/pageindex_indexer.py`
**Commit:** 9f20fa6
**Applied fix:** Changed `parsed_doc.metadata.get("page_count", 1)` to `parsed_doc.metadata.get("page_count") or 1` and wrapped in `int(...)` in both files. The `or 1` form falls back to `1` when the key is absent OR when the value is explicitly `None` (or any other falsy value), preventing the `TypeError` crash in `_build_deterministic_tree` at `max(node.page_start, page_end)` and in `int(None)` in the plugin.

---

### WR-01: Tree-index budget check reads combined enrich+tree LLM spend

**Files modified:** `src/knowledge_lake/pipeline/tree_index.py`
**Commit:** 2a44291
**Applied fix:** Changed `scope="global"` to `scope="tree_index"` in both the budget check (`registry_repo.get_llm_spend`) and the spend recording (`registry_repo.record_llm_spend`) calls inside `tree_index()`. This isolates tree-index LLM spend from enrichment spend so `settings.tree.budget_usd` applies only to tree-index operations.

---

### WR-02: `generate_dataset` asset silently routes unknown `kind` to `generate_instruction_example`

**Files modified:** `src/knowledge_lake/dagster_defs/assets.py`
**Commit:** 2afaa36
**Applied fix:** Replaced the bare `else` branch with an explicit `elif config.kind == "instruction":` branch followed by an `else: raise ValueError(...)` that surfaces the invalid kind string and lists the valid values (`'qa'`, `'instruction'`). Typos and future unrecognised kinds now fail fast with a clear error instead of silently misrouting.

---

### WR-03: `IndexerPlugin` protocol and `PageIndexIndexer` have divergent `build_index` signatures

**Files modified:** `src/knowledge_lake/plugins/protocols.py`
**Commit:** eb92f39
**Applied fix:** Added defaults to the `IndexerPlugin` Protocol's `build_index` signature — `mode: str = "deterministic"` and `metadata: dict[str, Any] | None = None` — matching the `PageIndexIndexer` implementation. Callers coding against the Protocol can now omit `metadata` without breaking, and type checkers (mypy/pyright) will no longer flag the divergence.

---

_Fixed: 2026-07-13_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
