---
phase: 14
slug: tree-retrieval
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-13
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (+ pytest-asyncio, already installed — no Wave 0 install) |
| **Config file** | pyproject.toml `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/unit/test_tree_search.py -q` |
| **Full suite command** | `pytest tests/unit/test_tree_search.py tests/unit/test_builtin_plugins.py -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run the task's `<verify><automated>` command.
- **After every plan wave:** Run `pytest tests/unit/test_tree_search.py tests/unit/test_builtin_plugins.py -q`.
- **Before `/gsd-verify-work`:** Full suite must be green (Wave 3 turns the entire Wave-0 scaffold GREEN).
- **Max feedback latency:** ~15 seconds.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 14-01-01 | 01 | 0 | RETR-04..08 | — | N/A (scaffold) | unit | `grep -c 'def test_' tests/unit/test_tree_search.py` ≥ 8 | ✅ W0 | ⬜ pending |
| 14-01-02 | 01 | 0 | RETR-05 | — | N/A (scaffold) | unit | `grep -c 'RetrieverPlugin' tests/unit/test_builtin_plugins.py` ≥ 1 | ✅ W0 | ⬜ pending |
| 14-02-01 | 02 | 1 | RETR-08 | T-14-04 | Additive citation_source; chunk path unchanged | unit | `pytest tests/unit/test_tree_search.py::TestHitContract -q` | ✅ W0 | ⬜ pending |
| 14-02-02 | 02 | 1 | RETR-04/06/07 | T-14-03 | Invalid retriever swap key rejected by _validate_swap_key | unit | `python -c "..."` defaults + `grep` validator tuple has retriever | ✅ | ⬜ pending |
| 14-03-01 | 03 | 2 | RETR-05/06/08 | T-14-05 / T-14-06 | Injection-resistant prompt + bounded NavResult; budget-gated scope=tree_search, never raises | unit | `pytest tests/unit/test_tree_search.py::TestHeuristicRetriever tests/unit/test_tree_search.py::TestLlmNav -q` | ✅ W0 | ⬜ pending |
| 14-03-02 | 03 | 2 | RETR-05 | T-14-07 | get_retriever LookupError on unknown name; editable reinstall exposes group | unit | `uv pip install -e . -q && pytest tests/unit/test_builtin_plugins.py::TestPageIndexRetriever -q` | ✅ W0 | ⬜ pending |
| 14-04-01 | 04 | 3 | RETR-04/07/08 | T-14-09 / T-14-10 / T-14-11 | Semaphore-bounded loads; skip missing tree; typed deserialization | unit | `pytest tests/unit/test_tree_search.py::TestDictToTree tests/unit/test_tree_search.py::TestTwoStageSearch -q` | ✅ W0 | ⬜ pending |
| 14-04-02 | 04 | 3 | RETR-04 | T-14-12 | Thin shim; renders only payload fields, no DB lookup | unit | `python -c "from knowledge_lake.cli.app import app"` + `grep -c 'name="tree-search"'` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_tree_search.py` — stubs for RETR-04..08 + D-11 round-trip (RED until Waves 1-3)
- [ ] `tests/unit/test_builtin_plugins.py` — `TestPageIndexRetriever` conformance stub (RED until Wave 2)
- [x] No framework install — pytest + pytest-asyncio already present (RESEARCH.md: zero new packages)

*Wave 0 is delivered by Plan 14-01. All Wave 1-3 implementation tasks reference these test functions as their automated verify targets.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| (none) | — | — | All phase behaviors have automated verification. |

*All phase behaviors have automated verification. LLM-nav is validated via mocked litellm.completion (degrade paths), not live calls.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (test_tree_search.py + TestPageIndexRetriever)
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-13
