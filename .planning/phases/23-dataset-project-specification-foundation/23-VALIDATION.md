---
phase: 23
slug: dataset-project-specification-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-21
---

# Phase 23 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (per `pyproject.toml [tool.pytest.ini_options]`) |
| **Config file** | `pyproject.toml:121-129` — `testpaths = ["tests"]`, `xfail_strict = true`, `asyncio_mode = "auto"` |
| **Quick run command** | `uv run pytest tests/unit/test_project.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~90 seconds (unit) / full suite per existing baseline |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit/test_project.py -x`
- **After every plan wave:** Run `uv run pytest tests/unit tests/integration -x`
- **Before `/gsd-verify-work`:** Full suite must be green (`uv run pytest`)
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 23-01-01 | 01 | 1 | PROJ-01 | — | `create_project()` persists all specified fields, `klake project new` creates a `draft`-state row | unit | `pytest tests/unit/test_project.py::test_create_project_draft_state -x` | ❌ W0 |
| 23-01-02 | 01 | 1 | PROJ-02 | — | Illegal transition raises `IllegalProjectTransitionError` naming from/to/legal-next-states | unit | `pytest tests/unit/test_project.py::test_illegal_transition_rejected -x` | ❌ W0 |
| 23-01-03 | 01 | 1 | PROJ-02 | — | Legal transition succeeds and updates `status` | unit | `pytest tests/unit/test_project.py::test_legal_transition_succeeds -x` | ❌ W0 |
| 23-02-01 | 02 | 2 | PROJ-03 | — | `klake project new/list/show/transition` CLI round-trip | integration | `pytest tests/integration/test_project_cli.py -x` | ❌ W0 |
| 23-02-02 | 02 | 2 | PROJ-03 | — | API `/projects`, `/projects/{id}`, `/projects/{id}/transition` routes | integration | `pytest tests/integration/test_api_project.py -x` | ❌ W0 |
| 23-03-01 | 03 | 1 | SPEC-01 | T-06-04 | Spec YAML with all fields including nullable `quality_contract_ref`/`policy_ref` parses via `yaml.safe_load` and validates structurally | unit | `pytest tests/unit/test_project.py::test_spec_all_fields_structural_validate -x` | ❌ W0 |
| 23-03-02 | 03 | 1 | SPEC-02 | — | Editing a spec produces a new version with distinct content hash, parent-version link intact, previous version unmodified/retrievable | unit | `pytest tests/unit/test_project.py::test_spec_version_immutable_chain -x` | ❌ W0 |
| 23-03-03 | 03 | 1 | SPEC-02 | — | Re-saving byte-identical (but re-formatted) YAML does NOT bump the version (canonical-hash stability) | unit | `pytest tests/unit/test_project.py::test_spec_hash_stable_across_yaml_formatting -x` | ❌ W0 |
| 23-03-04 | 03 | 2 | SPEC-03 | T-01-03 | `klake dataset spec validate` fails with specific reason for nonexistent source reference (ORM `select()` only, no raw SQL) | unit | `pytest tests/unit/test_project.py::test_spec_validate_unknown_source_fails -x` | ❌ W0 |
| 23-03-05 | 03 | 2 | SPEC-03 | — | `klake dataset spec validate` passes when all references resolve | unit | `pytest tests/unit/test_project.py::test_spec_validate_all_refs_resolve -x` | ❌ W0 |
| 23-04-01 | 04 | 3 | — (D-02/Pitfall 2) | — | `export_finetune_dataset("name")` (no version) resolves to the 'released' spec version's Dataset against a project with two spec versions | integration | `pytest tests/integration/test_export_project_resolution.py::test_latest_released_resolution -x` | ❌ W0 |
| 23-04-02 | 04 | 3 | — (D-02) | — | Legacy (pre-v2.7, no project FK) dataset export behavior is byte-identical to pre-phase behavior | regression | `pytest tests/unit/test_export.py -k legacy -x` | ✓ existing (extend) |
| 23-05-01 | 05 | 3 | SURFACE-01 | — | Full existing CLI test suite passes unchanged | regression | `pytest tests/ -k "not test_project"` | ✓ existing |
| 23-05-02 | 05 | 3 | SURFACE-02 | — | `docs/openapi.json` regenerated and `test_openapi_export.py` passes after new routes added | regression | `pytest tests/unit/test_openapi_export.py -x` | ✓ existing |
| 23-05-03 | 05 | 3 | SURFACE-03 | — | `TOOLS` count assertion == 14, no duplicate names, full existing MCP test suite passes unchanged | regression + unit | `pytest tests/integration/test_mcp_http.py -x` | ✓ existing (extend for 3 new tools) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs above are provisional — the planner assigns final plan/task numbering; this map anchors each phase requirement to its test, not to a specific plan file name.*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_project.py` — covers PROJ-01/02, SPEC-01/02/03 (pure pipeline-logic tests; check `test_curate.py`'s session-mocking convention before writing new fixtures — no live Postgres needed if that pattern is followed)
- [ ] `tests/integration/test_project_cli.py` — covers PROJ-03 CLI round-trip
- [ ] `tests/integration/test_api_project.py` — covers PROJ-03 API routes, mirrors `tests/integration/test_api_new_endpoints.py`'s existing shape
- [ ] `tests/integration/test_export_project_resolution.py` — covers the D-02/Success-Criterion-5 resolution rule across all 4 call sites (or fold into `test_dedup_cli_dagster_parity.py`'s existing CLI/Dagster-parity pattern if reusable)
- [ ] No new framework/config install needed — pytest + existing fixtures cover this phase entirely

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification per the Phase Requirements → Test Map above.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
