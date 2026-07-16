---
phase: 19
slug: section-classifier-patterns
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-16
---

# Phase 19 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-cov 5.x (both pinned in pyproject.toml) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `xfail_strict = true`, `testpaths = ["tests"]` |
| **Quick run command** | `uv run pytest tests/unit/test_clean.py tests/unit/test_quality_predicates.py tests/unit/test_domain_loader.py -x -q` |
| **Full suite command** | `uv run pytest --cov=knowledge_lake --cov-branch` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit/test_clean.py tests/unit/test_quality_predicates.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/unit/ -x -q` (all unit tests — this phase touches shared `clean.py` consumed by `process.py`, `quality_audit.py`, and the Dagster `clean_document` asset)
- **Before `/gsd-verify-work`:** `uv run pytest --cov=knowledge_lake --cov-branch` full suite green, plus the explicit 100%-branch-coverage gate on `pipeline/quality/`
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 19-01-01 | 01 | 1 | CLEAN-04 | — | `classify_sections()` computes substance signals + `is_boilerplate`; `clean()` drops boilerplate sections | unit | `pytest tests/unit/test_clean.py -k classify -x` | ❌ Wave 0 (extend existing test_clean.py) | ⬜ pending |
| 19-01-02 | 01 | 1 | CLEAN-04 | — | Substance annotations persisted in `cleaned_document.metadata_["section_annotations"]` | unit | `pytest tests/unit/test_clean.py -k section_annotations -x` | ❌ Wave 0 | ⬜ pending |
| 19-02-01 | 02 | 1 | CLEAN-05 | — | Extended patterns cover 5 garbage categories; existing Phase-3 assertions still pass | unit | `pytest tests/unit/test_clean.py -x` (full file — regression-checks existing + new patterns) | ✅ (existing file, extend) | ⬜ pending |
| 19-03-01 | 03 | 1 | CLEAN-06 | — | `DomainFilters` model validates `filters.yaml`; healthcare allowlist never drops clinical codes | unit | `pytest tests/unit/test_domain_loader.py -k filters -x` | ❌ Wave 0 | ⬜ pending |
| 19-03-02 | 03 | 1 | CLEAN-06 | — | `ICD-10 E11.9` / `Metformin 500 mg PO BID` chunk never dropped | unit (must-not-reject fixture, forward reference to Phase 20 MEAS-02) | `pytest tests/unit/test_clean.py -k allowlist -x` | ❌ Wave 0 | ⬜ pending |
| 19-04-01 | 04 | 1 | QUAL-01 | — | Predicates are pure, zero-I/O, independently importable | unit + import-boundary test | `pytest tests/unit/test_quality_predicates.py -x` plus explicit test asserting `import knowledge_lake.pipeline.quality` does not transitively import `sqlalchemy`/`boto3`/`dagster` | ❌ Wave 0 | ⬜ pending |
| 19-04-02 | 04 | 1 | QUAL-01 | — | 100% branch coverage on `pipeline/quality/` | coverage gate | `pytest tests/unit/test_quality_predicates.py --cov=knowledge_lake.pipeline.quality --cov-branch --cov-report=term-missing --cov-fail-under=100` | ❌ Wave 0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs above are placeholders pending the planner's actual plan/task numbering — the planner should reconcile this table with final task IDs once PLAN.md files exist.*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_quality_predicates.py` — new file, covers QUAL-01 (100% branch coverage target)
- [ ] `domains/healthcare/filters.yaml` — new fixture file, needed before `test_domain_loader.py` filters tests can run against the real healthcare pack
- [ ] A must-not-reject fixture set (short ICD-10/LOINC/RxNorm/dosage strings) — forward reference to Phase 20's MEAS-02, but Phase 19 needs at least a minimal version of these fixtures to prove CLEAN-06's acceptance criterion in this phase, since the full ~20-item MEAS-02 set is Phase 20's job
- [ ] Coverage gate: `--cov-branch` flag is not in the default `make test` — the planner should decide whether to add a `make test-quality-coverage` target or run coverage inline in a verification task

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
