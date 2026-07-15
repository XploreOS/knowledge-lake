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
  critical: 1
  warning: 3
  info: 3
  total: 7
status: issues_found
---

# Phase 13: Code Review Report

**Reviewed:** 2026-07-13
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Phase 13 introduces a hierarchical tree-index pipeline stage (`pipeline/tree_index.py`), a new `TreeNode`/`TreeIndex` data model in `plugins/protocols.py`, a built-in `PageIndexIndexer` plugin, a `TreeSettings` config block, a `create_tree_index_artifact` repo function, and a `tree_index_document` Dagster asset. The implementation is generally well-structured: deferred imports avoid circular dependencies, the D-09 "never raise on LLM failure" contract is honoured, the content-hash no-op dedup (TREE-02) is correctly wired, and the storage-key pattern (TREE-01) matches the established convention.

One confirmed crash path exists in `tree_index.py` when a caller populates `parsed_doc.metadata["page_count"]` with an explicit `None` value. Three quality/correctness warnings affect the tree-index budget accounting, silent misrouting in `generate_dataset`, and a protocol-vs-implementation signature divergence. Three info-level issues cover test assertion looseness, a hardcoded schema version in the plugin, and an empty `content_hash` returned by the plugin's `build_index`.

---

## Critical Issues

### CR-01: `page_count=None` causes `TypeError` crash in `_build_deterministic_tree`

**File:** `src/knowledge_lake/pipeline/tree_index.py:263`

**Issue:** `page_count` is fetched with a default of `1`, but `dict.get(key, default)` only uses the default when the key is **absent**. If a caller (or parser) explicitly writes `metadata["page_count"] = None` — which is legal in the `ParsedDoc.metadata: dict[str, Any]` field — `get("page_count", 1)` returns `None`. That `None` is then passed to `_build_deterministic_tree` as `page_count`. Inside the function, at line 172 `page_end = page_count` assigns `None`, and at line 179 `node.page_end = max(node.page_start, page_end)` crashes with:

```
TypeError: '>' not supported between instances of 'NoneType' and 'int'
```

The no-sections fallback at line 274 (`page_end=page_count`) has the same problem: it passes `None` directly into `TreeNode(page_end=None)` without crashing immediately, but any downstream consumer that treats `page_end` as an integer will fail.

Confirmed:
```python
>>> max(1, None)
TypeError: '>' not supported between instances of 'NoneType' and 'int'
```

Browsers of `ParsedDoc` from non-Docling parsers (e.g. Tika, JSON/XML, custom crawl results) may never set `page_count` and some may set it to `None`.

**Fix:**
```python
# line 263 — guard against explicit None in metadata
page_count: int = int(parsed_doc.metadata.get("page_count") or 1)
```

The same one-liner fix covers both the no-sections fallback and the `_build_deterministic_tree` call path. Also apply the same guard in `pageindex_indexer.py:79` where `int(parsed_doc.metadata.get("page_count", 1))` would raise `TypeError` on an explicit `None` for the same reason (`int(None)` is not valid).

---

## Warnings

### WR-01: Tree-index budget check reads combined enrich+tree LLM spend — premature blocking

**File:** `src/knowledge_lake/pipeline/tree_index.py:295-296`

**Issue:** `tree_index()` in LLM mode checks `registry_repo.get_llm_spend(session, scope="global")` against `settings.tree.budget_usd` (default 5.0 USD). The `enrich` pipeline also accumulates its costs into the identical `scope="global"` bucket (confirmed in `pipeline/enrich.py:356,427`). This means the **combined** spend from enrichment and tree-index operations is compared against `tree.budget_usd`. After a full enrichment run that spends 5.0 USD, tree-index LLM mode will always return `status="skipped_budget_exceeded"` even though the tree-index stage itself has spent nothing. The tree budget cap is silently shared with, and exhausted by, a completely different stage.

**Fix:** Use a distinct scope for tree-index LLM spend:
```python
# In tree_index() — budget check (line 295) and spend record (line 347):
current_spend = registry_repo.get_llm_spend(session, scope="tree_index")
# ...
registry_repo.record_llm_spend(session, scope="tree_index", cost_usd=total_cost)
```

This mirrors the settings separation (`settings.tree.budget_usd` vs `settings.enrich.budget_usd`) and gives operators independent visibility and control over each stage's spend.

---

### WR-02: `generate_dataset` asset silently routes any unrecognised `kind` to `generate_instruction_example`

**File:** `src/knowledge_lake/dagster_defs/assets.py:667-673`

**Issue:** The `kind` dispatch uses a bare `else` branch:
```python
if config.kind == "qa":
    result = generate_qa_example(...)
else:
    result = generate_instruction_example(...)
```
Any typo or future invalid `kind` value (e.g. `"QA"`, `"qa_pair"`, `"rag"`) silently invokes `generate_instruction_example` with an incorrect `source_artifact_id` (a chunk ID rather than an `enriched_document` ID), which will either fail deep in `generate_instruction_example` with a confusing error or silently produce a malformed example. The `GenerateDatasetConfig.kind` docstring acknowledges only `"qa"` and `"instruction"` as valid values but there is no validation.

**Fix:**
```python
if config.kind == "qa":
    result = generate_qa_example(
        config.source_artifact_id, config.dataset_name, settings=settings
    )
elif config.kind == "instruction":
    result = generate_instruction_example(
        config.source_artifact_id, config.dataset_name, settings=settings
    )
else:
    raise ValueError(
        f"generate_dataset: unknown kind={config.kind!r}. "
        "Valid values: 'qa', 'instruction'."
    )
```

---

### WR-03: `IndexerPlugin` protocol and `PageIndexIndexer` have divergent `build_index` signatures

**File:** `src/knowledge_lake/plugins/protocols.py:686-692` and `src/knowledge_lake/plugins/builtin/pageindex_indexer.py:49-55`

**Issue:** The `IndexerPlugin` Protocol declares:
```python
def build_index(self, parsed_doc: ParsedDoc, *, mode: str, metadata: dict[str, Any]) -> TreeIndex:
```
`metadata` is required (no default). The `PageIndexIndexer` implementation declares:
```python
def build_index(self, parsed_doc: ParsedDoc, *, mode: str = "deterministic", metadata: dict[str, Any] | None = None) -> TreeIndex:
```
`metadata` is optional (`None` default) and `mode` also has a default.

Because `runtime_checkable` Protocol only checks for method presence (not signature compatibility), `isinstance(PageIndexIndexer(), IndexerPlugin)` returns `True` — this is the Protocols contract in Python. However, any future caller who writes code against the Protocol's contract and calls `plugin.build_index(doc, mode="deterministic")` without `metadata` will get a `TypeError` from a different implementation that strictly enforces the Protocol's required `metadata` parameter, while the builtin silently accepts the call. The type divergence will also cause mypy/pyright failures for callers relying on the Protocol.

Additionally, `mode` has no default in the Protocol but has one in the implementation — callers who use the Protocol type annotation cannot assume `mode` has a default.

**Fix:** Align the protocol and implementation. The simplest approach is to add defaults to the Protocol definition (since optional parameters are a valid extension):
```python
# protocols.py
def build_index(
    self,
    parsed_doc: ParsedDoc,
    *,
    mode: str = "deterministic",
    metadata: dict[str, Any] | None = None,
) -> TreeIndex:
```

---

## Info

### IN-01: Test `test_deterministic_tree_from_sections` accepts phantom status values

**File:** `tests/unit/test_tree_index.py:173`

**Issue:**
```python
assert result["status"] in ("indexed", "tree_indexed", "complete")
```
The values `"indexed"` and `"complete"` are never returned by `tree_index()`. The function's docstring and implementation only return `"tree_indexed"`, `"cached"`, or `"skipped_budget_exceeded"`. Accepting phantom values means the assertion would pass even if the actual return status were any of these three phantom names, masking a regression where the status string changed silently.

**Fix:**
```python
assert result["status"] == "tree_indexed"
```

---

### IN-02: `PageIndexIndexer.build_index` returns `TreeIndex(content_hash="", schema_version="1")` with hardcoded values

**File:** `src/knowledge_lake/plugins/builtin/pageindex_indexer.py:82-88`

**Issue:** The plugin always produces a `TreeIndex` with `content_hash=""` and a hardcoded `schema_version="1"`. The content hash is intentionally left empty because the pipeline layer (`tree_index()`) computes and owns the hash. However, if any caller uses `get_indexer(settings).build_index(...)` directly (e.g. a future CLI command, test, or third-party plugin consumer), the resulting `TreeIndex` will have an empty content hash, silently breaking the D-06 dedup invariant. The `schema_version="1"` string is also hardcoded rather than reading from `settings.tree.schema_version`, so bumping the schema version in settings will have no effect on this plugin.

**Fix:** Document the limitation explicitly in the method docstring, and consider surfacing `schema_version` as a constructor argument so callers can inject it from settings if needed. At minimum, assert in the docstring that callers must populate `content_hash` before persisting the returned `TreeIndex`.

---

### IN-03: `test_tree_index_asset.py` imports `tree_index` at module level but never calls it directly

**File:** `tests/unit/test_tree_index_asset.py:19`

**Issue:**
```python
from knowledge_lake.pipeline.tree_index import tree_index
```
This import at line 19 is unused in the test file — the tests only call the Dagster asset function (`tree_index_document`) and patch the pipeline function at its source-module path. The unused import adds noise and will trigger `F401` linting warnings.

**Fix:** Remove the unused import:
```python
# Remove line 19:
# from knowledge_lake.pipeline.tree_index import tree_index
```

---

_Reviewed: 2026-07-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
