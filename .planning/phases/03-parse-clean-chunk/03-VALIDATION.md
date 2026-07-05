---
phase: 03
slug: parse-clean-chunk
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-04
---

# Phase 03 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `uv run pytest tests/unit/ -x -q` |
| **Full suite command** | `uv run pytest tests/ -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit/ -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | PARSE-01 | — | N/A | unit | `uv run pytest tests/unit/test_parse_multiformat.py -k docling` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | PARSE-02 | — | N/A | unit | `uv run pytest tests/unit/test_fallback_chain.py -k fallback` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | PARSE-03 | — | N/A | unit | `uv run pytest tests/unit/test_parse_multiformat.py -k quality` | ❌ W0 | ⬜ pending |
| 03-01-04 | 01 | 1 | PARSE-04 | — | N/A | integration | `uv run pytest tests/integration/test_torture_corpus.py` | ❌ W0 | ⬜ pending |
| 03-01-05 | 01 | 1 | PARSE-05 | — | N/A | unit | `uv run pytest tests/unit/test_parse_multiformat.py -k structured` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 2 | CLEAN-01 | — | N/A | unit | `uv run pytest tests/unit/test_clean.py -k boilerplate` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 2 | CLEAN-02 | — | N/A | unit | `uv run pytest tests/unit/test_clean.py -k language` | ❌ W0 | ⬜ pending |
| 03-02-03 | 02 | 2 | CLEAN-03 | — | N/A | unit | `uv run pytest tests/unit/test_clean.py -k dedup` | ❌ W0 | ⬜ pending |
| 03-03-01 | 03 | 3 | CHUNK-01 | — | N/A | unit | `uv run pytest tests/unit/test_chunk_token.py -k hierarchy` | ❌ W0 | ⬜ pending |
| 03-03-02 | 03 | 3 | CHUNK-02 | — | N/A | unit | `uv run pytest tests/unit/test_chunk_token.py -k token_size` | ❌ W0 | ⬜ pending |
| 03-03-03 | 03 | 3 | CHUNK-03 | — | N/A | unit | `uv run pytest tests/unit/test_chunk_token.py -k table` | ❌ W0 | ⬜ pending |
| 03-03-04 | 03 | 3 | CHUNK-04 | — | N/A | unit | `uv run pytest tests/unit/test_chunk_token.py -k metadata` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_parse_multiformat.py` — stubs for PARSE-01, PARSE-03, PARSE-05
- [ ] `tests/unit/test_fallback_chain.py` — stubs for PARSE-02 (fallback chain)
- [ ] `tests/unit/test_clean.py` — stubs for CLEAN-01 through CLEAN-03
- [ ] `tests/unit/test_chunk_token.py` — stubs for CHUNK-01 through CHUNK-04
- [ ] `tests/integration/test_torture_corpus.py` — stubs for PARSE-04 torture test corpus
- [ ] `tests/conftest.py` — shared fixtures (sample docs, mock storage)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Torture-test visual quality review | PARSE-04 | Quality judgment on parse fidelity requires human review of rendered output | Run torture test, inspect output markdown for 5 representative docs |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
