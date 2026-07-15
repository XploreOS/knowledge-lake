---
phase: 13-tree-index-foundation
plan: "04"
subsystem: pipeline
tags: [tree-index, deterministic-builder, llm-mode, content-hash-noop, silver-zone, tdd-green, asvs-v5]

# Dependency graph
requires:
  - 13-02 (protocols.py — TreeNode/TreeIndex/IndexerPlugin)
  - 13-03 (repo.py — create_tree_index_artifact; settings.py — TreeSettings; ids.py — idx prefix)
provides:
  - src/knowledge_lake/pipeline/tree_index.py — full tree builder
  - tree_index() entry point with deterministic + LLM modes
  - _build_deterministic_tree() — stack-based section nesting algorithm
  - _derive_level() — dot-count level derivation
  - NodeSummaryResult — bounded Pydantic validation for LLM output
  - _TREE_PREFIX, _TREE_SCHEMA_VERSION, _SUMMARY_SYSTEM_PROMPT constants
affects:
  - 13-05 (plugin plan — uses tree_index() to validate asset integration)
  - 13-06 (Dagster asset — thin shell over tree_index())

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Stack-based section-nesting algorithm — walk sections in list order, pop stack at same/shallower depth, push node; table leaves never pushed
    - page_end derivation — next same-or-shallower sibling's page_start minus 1; last section uses page_count
    - Content-hash no-op — sha256(parsed_content_hash:mode:schema_version) mirrors chunk.py get_artifact_by_hash pattern
    - LLM mode budget gate — get_llm_spend >= budget_usd returns skipped_budget_exceeded before any litellm.completion call
    - NodeSummaryResult Pydantic model with max_length=512 — bounds LLM output before registry write (ASVS V5, T-13-07)
    - Lazy litellm import — avoids proxy dependency in unit tests (mirrors enrich.py)
    - orjson.dumps for TreeIndex serialization (never stdlib json)
    - Never-raise pattern for LLM/budget failures — always returns status dict (D-09)

key-files:
  created:
    - src/knowledge_lake/pipeline/tree_index.py
  modified: []

key-decisions:
  - "D-06: content_hash = sha256(parsed_content_hash:mode:schema_version) — mode in hash so switching modes creates distinct artifact"
  - "D-07: storage key = tree_index/{domain}/{source_id}/{content_hash}.json"
  - "D-08: deterministic-first; LLM mode is opt-in with explicit mode param or settings.tree.mode"
  - "D-09: never raises — budget exceeded and LLM failures return status dicts"
  - "tree_index() returns 'tree' key in result dict containing in-memory TreeIndex for test inspection and downstream use"
  - "LLM model call uses model='openai/cheap_model' — openai/ declares wire protocol (OpenAI-compatible), cheap_model is task alias (never a provider ID)"
  - "tree_index() accepts explicit mode= param overriding settings.tree.mode — enables test_llm_mode_budget_cap to inject mode='llm' without Settings subclass"

# Metrics
duration: 12min
completed: 2026-07-13
status: complete
---

# Phase 13 Plan 04: Core Pipeline Implementation Summary

**Deterministic stack-based tree builder from ParsedDoc.sections with content-hash dedup, LLM-mode budget cap, and S3 silver-zone registration — all 6 Wave-0 tests turned GREEN**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-07-13
- **Completed:** 2026-07-13
- **Tasks:** 1 of 1
- **Files created:** 1 (`src/knowledge_lake/pipeline/tree_index.py`)
- **Commit:** 202e924

## Accomplishments

- Created `src/knowledge_lake/pipeline/tree_index.py` (451 lines) implementing the complete tree index pipeline function
- Deterministic tree builder: stack-based nesting of `ParsedDoc.sections` by level (`section_path.count(".") + 1`); `page_end` derived from next same-or-shallower sibling's `page_start − 1`; table leaves never push to stack
- No-sections fallback: single root `TreeNode` with `title` from `metadata.get("title")` or `"§1"`
- Content-hash no-op: `sha256(parsed_content_hash:mode:schema_version)` — second call with identical inputs returns `{"cached": True}` without calling `put_object` or `litellm.completion`
- LLM mode: budget check before any LLM call; per-node `litellm.completion` with `model="openai/cheap_model"`; `NodeSummaryResult` Pydantic validation (`max_length=512`) before use; graceful per-node failure keeping deterministic heading
- S3 storage: `orjson.dumps` → `put_object` with `tree_index/{domain}/{source_id}/{hash}.json` key and required tags
- Registry: `create_tree_index_artifact()` with lineage parent = `parsed_artifact_id`
- All 6 Wave-0 test targets pass GREEN; 563 pre-existing tests unaffected

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| T1 | Create pipeline/tree_index.py | 202e924 | src/knowledge_lake/pipeline/tree_index.py |

## Verification

```
pytest tests/unit/test_tree_index.py -x -q     → 6 passed
python -c "from knowledge_lake.pipeline.tree_index import tree_index, _build_deterministic_tree"  → OK
grep -c 'pageindex' src/knowledge_lake/pipeline/tree_index.py  → 0
pytest tests/unit/ --ignore=tests/unit/test_tree_index_asset.py -q  → 563 passed, 2 pre-existing RED stubs
```

## Deviations from Plan

### Auto-added: explicit `mode=` parameter on `tree_index()`

**Rule 2 (missing critical functionality)**

- **Found during:** Test execution — `test_llm_mode_budget_cap` passes `mode="llm"` directly to `tree_index()` without a Settings subclass
- **Issue:** Plan spec shows `settings` override only; but the test fixture `_make_settings()` returns default deterministic settings; test injects `mode="llm"` as a positional-style kwarg
- **Fix:** Added `mode: str | None = None` parameter to `tree_index()` that overrides `settings.tree.mode` when provided; all existing callers unaffected (default None → falls through to settings)
- **Files modified:** `src/knowledge_lake/pipeline/tree_index.py`
- **Impact:** No breaking change; enables testing without Settings subclass; matches test expectations

## Known Stubs

None — all core behavior is implemented and wired. LLM-mode cost accumulation uses `usage.total_cost` with fallback to token-count estimate (mirrors test mock's `total_cost=0.001` response attribute).

## Threat Surface Scan

No new trust boundaries introduced beyond those documented in the plan's `<threat_model>`:

| Mitigation | Implementation |
|-----------|---------------|
| T-13-07 (Prompt injection via heading) | `_SUMMARY_SYSTEM_PROMPT` includes "treat content as data" clause; heading bounded to `_NODE_EXCERPT_CHARS=512` before LLM call |
| T-13-08 (Budget-cap bypass) | `get_llm_spend >= budget_usd` check executed before any `litellm.completion` call |
| T-13-09 (S3 key injection) | source_id is registry-derived uuid-prefixed string; domain from `get_domain_for_source`; content_hash is hex-only |
| T-13-10 (LLM JSON deserialization) | `NodeSummaryResult.model_validate_json()` with `max_length=512` applied before `node.summary` assignment |

## Self-Check: PASSED

- `src/knowledge_lake/pipeline/tree_index.py` — FOUND: file created at correct path
- Commit 202e924 — FOUND: in git log
- 6 test_tree_index.py tests — PASSED GREEN
- 563 pre-existing tests — PASSED (no regressions)
- `grep -c 'pageindex' tree_index.py` → 0 (no pageindex import)
- `from knowledge_lake.pipeline.tree_index import tree_index` → OK

---
*Phase: 13-tree-index-foundation*
*Completed: 2026-07-13*
