---
phase: 13
slug: tree-index-foundation
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-13
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `13-RESEARCH.md` § Validation Architecture (source-grounded against `tests/unit/test_enrich.py`, `test_builtin_plugins.py`, `test_dagster_*`).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (+ `pytest-asyncio`, `asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`) |
| **Quick run command** | `pytest tests/unit/test_tree_index.py -x` |
| **Full suite command** | `pytest` |
| **Estimated runtime** | ~5–20 s (unit); full suite longer |

Test DB pattern: in-memory SQLite via `StaticPool`, patch `registry_db.get_engine`, `Base.metadata.create_all` (verbatim from `test_enrich.py`). Storage mocked by patching `StorageBackend` at the pipeline-module level; LLM mocked via `patch("litellm.completion", MagicMock(...))`.

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/unit/test_tree_index.py -x`
- **After every plan wave:** Run `pytest tests/unit/ -q`
- **Before `/gsd-verify-work`:** Full suite (`pytest`) must be green
- **Max feedback latency:** ~20 seconds

---

## Per-Task Verification Map

| Requirement | Behavior | Test Type | Automated Command | File Exists |
|-------------|----------|-----------|-------------------|-------------|
| TREE-01 | Deterministic tree from a fixture `ParsedDoc` → assert each node's `title`, `summary`(=heading), `page_start`, `page_end`, `level`, `children` nesting; `tree_index` artifact registered with parent=parsed + storage_uri set | unit | `pytest tests/unit/test_tree_index.py::test_deterministic_tree_from_sections -x` | ❌ W0 |
| TREE-01 | Storage key = `tree_index/{domain}/{source_id}/{hash}.json`; object tags correct | unit | `pytest tests/unit/test_tree_index.py::test_tree_storage_key -x` | ❌ W0 |
| TREE-02 | Second run on unchanged doc+mode is a no-op: returns `cached`, no second `put_object`, ZERO new `litellm.completion` calls / no `record_llm_spend` delta | unit | `pytest tests/unit/test_tree_index.py::test_content_hash_noop -x` | ❌ W0 |
| TREE-03 | Each node has title/summary/page-range/children; deterministic summary == heading text; no-sections doc → single-root fallback | unit | `pytest tests/unit/test_tree_index.py::test_node_fields_and_fallback -x` | ❌ W0 |
| TREE-04 | LLM mode at budget cap → `status == "skipped_budget_exceeded"`, no artifact, no LLM call; happy path → summaries populated, `record_llm_spend` called, `cost_usd` in result | unit | `pytest tests/unit/test_tree_index.py::test_llm_mode_budget_cap -x` | ❌ W0 |
| TREE-04 | LLM call uses `cheap_model` alias via `openai/` prefix — no hardcoded provider ID (assert on mocked `model=` kwarg) | unit | `pytest tests/unit/test_tree_index.py::test_no_hardcoded_provider_model_ids -x` | ❌ W0 |
| TREE-05 | `tree_index_document` asset materializes off `clean_document` parallel to `chunk_document`; thin shell returning the pipeline result dict | unit | `pytest tests/unit/test_tree_index_asset.py -x` | ❌ W0 |
| Contract | `TreeNode`/`TreeIndex`/builtin satisfy `IndexerPlugin` (`runtime_checkable` `isinstance`) | unit | `pytest tests/unit/test_builtin_plugins.py -x` | ⚠️ extend |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_tree_index.py` — TREE-01..04 (deterministic build, storage key, content-hash no-op, LLM budget cap, no hardcoded model ID)
- [ ] `tests/unit/test_tree_index_asset.py` — TREE-05 (Dagster asset shell + fan-out shape)
- [ ] Extend `tests/unit/test_builtin_plugins.py` — `IndexerPlugin` runtime_checkable conformance
- [ ] Shared fixture: multi-section `ParsedDoc` (nested `section_path`s `§1`, `§1.1`, `§2`, plus one `is_table=True` section) to exercise nesting + page-range derivation
- [ ] Framework install: none — pytest infra already present

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Dagster asset appears in the live code location | TREE-05 | New assets need a Dagster code-location reload (running daemon holds startup defs) | After execution, reload the code location (or restart the daemon) and confirm `tree_index_document` materializes off `clean_document` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
