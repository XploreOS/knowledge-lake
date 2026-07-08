---
phase: 6
slug: healthcare-domain-pack-full-surface-validation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-07
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/unit/ -x -q` |
| **Full suite command** | `pytest tests/ -v` |
| **Integration run** | `pytest -m integration tests/integration/` |
| **Estimated runtime** | ~60 seconds (unit), ~3-5 min (integration), ~10-15 min (e2e) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/unit/ -x -q`
- **After every plan wave:** Run `pytest tests/unit/ tests/integration/ -x`
- **Before `/gsd-verify-work`:** Full suite must be green: `pytest tests/ -v`
- **Max feedback latency:** <5s (unit), <30s (integration)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | DOMAIN-01 | DomainLoader reads YAML/prompts/validator | unit | `pytest tests/unit/test_domain_loader.py -x` | ❌ W0 | ⬜ pending |
| 06-01-02 | 01 | 1 | DOMAIN-01 | klake init --domain registers sources | integration | `pytest tests/integration/test_domain_init.py -x` | ❌ W0 | ⬜ pending |
| 06-02-01 | 02 | 1 | DOMAIN-02 | sources.yaml has ≥25 entries with required fields | unit | `pytest tests/unit/test_healthcare_sources.py -x` | ❌ W0 | ⬜ pending |
| 06-02-02 | 02 | 1 | DOMAIN-03 | enrich.j2 renders with correct variables | unit | `pytest tests/unit/test_healthcare_prompts.py -x` | ❌ W0 | ⬜ pending |
| 06-02-03 | 02 | 1 | DOMAIN-03 | HealthcareValidator.validate_document() returns ValidationResult | unit | `pytest tests/unit/test_healthcare_validator.py -x` | ❌ W0 | ⬜ pending |
| 06-03-01 | 03 | 2 | IFACE-01 | klake init and klake index commands work | unit | `pytest tests/unit/test_cli_init_index.py -x` | ❌ W0 | ⬜ pending |
| 06-03-02 | 03 | 2 | IFACE-02 | GET /sources, GET /documents, GET /datasets return valid data | integration | `pytest tests/integration/test_api_new_endpoints.py -x` | ❌ W0 | ⬜ pending |
| 06-03-03 | 03 | 2 | IFACE-03 | All 12 Dagster assets have RetryPolicy | unit | `pytest tests/unit/test_dagster_retry_policies.py -x` | ❌ W0 | ⬜ pending |
| 06-03-04 | 03 | 2 | IFACE-03 | healthcare_e2e_job defined in Definitions | unit | `pytest tests/unit/test_dagster_e2e_job.py -x` | ❌ W0 | ⬜ pending |
| 06-04-01 | 04 | 3 | DOMAIN-04 | 5-source E2E: lineage intact + search ≥1 result + Parquet exported | e2e | `pytest tests/e2e/test_e2e_healthcare.py -x -m integration` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

All test files are new — Wave 0 must create stubs before execution begins.

- [ ] `tests/unit/test_domain_loader.py` — stubs for DOMAIN-01 loader unit tests
- [ ] `tests/unit/test_healthcare_sources.py` — stubs for DOMAIN-02 YAML schema validation
- [ ] `tests/unit/test_healthcare_prompts.py` — stubs for DOMAIN-03 Jinja2 rendering
- [ ] `tests/unit/test_healthcare_validator.py` — stubs for DOMAIN-03 validator
- [ ] `tests/unit/test_cli_init_index.py` — stubs for IFACE-01 new CLI commands
- [ ] `tests/unit/test_dagster_retry_policies.py` — stubs for IFACE-03 retry audit
- [ ] `tests/unit/test_dagster_e2e_job.py` — stubs for IFACE-03 job registration
- [ ] `tests/integration/test_domain_init.py` — stubs for DOMAIN-01 integration
- [ ] `tests/integration/test_api_new_endpoints.py` — stubs for IFACE-02 new endpoints
- [ ] `tests/e2e/test_e2e_healthcare.py` — stubs for DOMAIN-04 E2E (integration marker)

Existing infrastructure from prior phases covers the shared fixtures and conftest.py — check `tests/integration/test_dagster_assets.py` for the materialize() pattern to reuse.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Dagster UI shows healthcare_e2e_job | IFACE-03 | UI observability requires browser | Start `dagster dev`, open localhost:3000, verify job appears |
| NPPES CSV ingest registers sources | DOMAIN-02 | Requires bulk file download (~10GB) | Download sample CSV from data.cms.gov, run `klake upload`, verify registry entry |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s (unit)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
