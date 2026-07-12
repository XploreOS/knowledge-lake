---
phase: 7
slug: metadata-foundation
status: verified
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-08
validated: 2026-07-12
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pyproject.toml `[tool.pytest.ini_options]`) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/unit/ -x -q` |
| **Full suite command** | `uv run pytest --cov=knowledge_lake` |
| **Estimated runtime** | ~30 seconds (unit), ~2 min (full) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit/ -x -q`
- **After every plan wave:** Run `uv run pytest --cov=knowledge_lake`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds (unit)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 07-01-T1 | 01 | 1 | PAYLOAD-02 | unit | `uv run pytest tests/unit/test_qdrant_payload_indexes.py -x -q` | ✅ | ✅ green |
| 07-02-T1 | 02 | 1 | PAYLOAD-01 | unit | `uv run pytest tests/unit/test_index_payload.py -x -q` | ✅ | ✅ green |
| 07-02-T2 | 02 | 1 | PAYLOAD-01 | unit | `uv run pytest tests/unit/test_index_payload.py -x -q` | ✅ | ✅ green |
| 07-03-T1 | 03 | 2 | PAYLOAD-02 | unit | `uv run pytest tests/unit/test_qdrant_payload_indexes.py -x -q` | ✅ | ✅ green |
| 07-03-T2 | 03 | 2 | PAYLOAD-02 | unit | `uv run pytest tests/unit/test_search_filters.py -x -q` | ✅ | ✅ green |
| 07-04-T1 | 04 | 3 | PAYLOAD-01, PAYLOAD-02 | unit | `uv run pytest tests/unit/ -x -q` | ✅ | ✅ green |
| 07-04-T2 | 04 | 3 | PAYLOAD-01, PAYLOAD-02 | unit | `uv run pytest tests/unit/ -x -q` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_qdrant_payload_indexes.py` — stubs for payload index creation (ensure_payload_indexes); existing `test_index_payload.py` and `test_search_filters.py` cover PAYLOAD-01/02 core behavior

*Note: `test_index_payload.py` and `test_search_filters.py` already exist and must be extended in-place (not replaced).*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Filters on pre-Phase-7 points return no results (backward-compat documented) | PAYLOAD-01 | Requires live Qdrant with pre-existing data | Index a chunk, note it lacks new fields; verify filtered search doesn't match on new fields |

---

## Validation Audit 2026-07-12

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

All 7 mapped tasks COVERED by green unit tests: `test_qdrant_payload_indexes.py` (3), `test_index_payload.py` (11), `test_search_filters.py` (12+1 xpass) — 26 passed, 1 xpassed. The single manual-only item (pre-Phase-7 backward-compat) remains manual (requires live Qdrant with legacy data).

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** verified 2026-07-12
