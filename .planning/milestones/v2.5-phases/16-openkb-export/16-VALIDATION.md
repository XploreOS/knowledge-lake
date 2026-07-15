---
phase: 16
slug: openkb-export
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-14
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `python -m pytest tests/unit/test_wiki.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/unit/test_wiki.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | KB-01 | — | N/A | unit | `python -m pytest tests/unit/test_wiki.py -k "test_export_produces_markdown"` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | KB-02 | — | N/A | unit | `python -m pytest tests/unit/test_wiki.py -k "test_page_types"` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | KB-03 | — | N/A | unit | `python -m pytest tests/unit/test_wiki.py -k "test_idf_filtering"` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | KB-04 | — | N/A | unit | `python -m pytest tests/unit/test_wiki.py -k "test_incremental_rebuild"` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | KB-05 | — | N/A | integration | `python -m pytest tests/unit/test_wiki.py -k "test_cli_and_api"` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_wiki.py` — stubs for KB-01..KB-05
- [ ] Test fixtures for mock enrichment data (EnrichmentResult with entities/keywords)
- [ ] Test fixtures for mock storage backend

*Existing pytest infrastructure covers framework installation.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Obsidian vault import | KB-01 | Requires Obsidian desktop app | Download archive via `--archive`, open in Obsidian, verify wikilinks resolve |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
