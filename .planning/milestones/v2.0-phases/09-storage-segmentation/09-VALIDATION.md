---
phase: 9
slug: storage-segmentation
status: verified
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-09
validated: 2026-07-12
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `python -m pytest tests/unit/ -v -x` |
| **Full suite command** | `python -m pytest tests/ -v --ignore=tests/e2e --ignore=tests/integration` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/unit/ -v -x`
- **After every plan wave:** Run `python -m pytest tests/ -v --ignore=tests/e2e --ignore=tests/integration`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 09-01-01 | 01 | 0 | STORE-01 | — | N/A | unit | `pytest tests/unit/test_put_raw_domain.py -x` | ✅ | ✅ green |
| 09-01-02 | 01 | 0 | STORE-01 | — | `_unclassified` prevents empty segment injection | unit | `pytest tests/unit/test_put_raw_domain.py::TestPutRawDomainKey -x` | ✅ | ✅ green |
| 09-01-03 | 01 | 0 | STORE-01 | — | dedup no-op ordered before key construction | unit | `pytest tests/unit/test_put_raw_domain.py::TestDeduplicationOrderPreserved -x` | ✅ | ✅ green |
| 09-01-04 | 01 | 0 | STORE-02 | T-09-01 | tag values truncated to 256 chars (no overflow) | unit | `pytest tests/unit/test_format_tags.py -x` | ✅ | ✅ green |
| 09-01-05 | 01 | 0 | STORE-02 | T-09-02 | tags inline with write; best-effort fallback prevents blocking | unit | `pytest tests/unit/test_put_object_tags.py -x` | ✅ | ✅ green |
| 09-02-01 | 02 | 1 | STORE-01 | — | N/A | unit | `pytest tests/unit/test_put_bronze.py::TestPutBronzeDomainKey -x` | ✅ | ✅ green |
| 09-02-02 | 02 | 1 | STORE-01 | — | domain resolved inside session boundary | unit | `pytest tests/unit/test_parse_silver_key.py -x` | ✅ | ✅ green |
| 09-02-03 | 02 | 1 | STORE-01 | — | domain resolved inside session boundary | unit | `pytest tests/unit/test_clean_silver_key.py -x` | ✅ | ✅ green |
| 09-03-01 | 03 | 2 | STORE-03 | — | N/A | unit | `pytest tests/unit/test_export.py::TestGoldZoneDomainKey -x` | ✅ | ✅ green |
| 09-03-02 | 03 | 2 | STORE-03 | — | N/A | unit | `pytest tests/unit/test_export.py::TestGoldZoneUnclassified -x` | ✅ | ✅ green |
| 09-03-03 | 03 | 2 | STORE-03 | — | N/A | unit | `pytest tests/unit/test_export.py::TestGoldZonePretrain -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_put_raw_domain.py` — stubs for STORE-01 (raw key domain scoping, dedup order)
- [ ] `tests/unit/test_format_tags.py` — stubs for STORE-02 (URL-encoded tag string, 256-char truncation)
- [ ] `tests/unit/test_put_object_tags.py` — stubs for STORE-02 (inline tagging, best-effort fallback)
- [ ] `tests/unit/test_parse_silver_key.py` — stubs for STORE-01 (silver key domain scope in parse stage)
- [ ] `tests/unit/test_clean_silver_key.py` — stubs for STORE-01 (silver key domain scope in clean stage)
- [ ] New class `TestPutBronzeDomainKey` in `tests/unit/test_put_bronze.py` — stubs for STORE-01 bronze key
- [ ] New classes `TestGoldZoneDomainKey`, `TestGoldZoneUnclassified`, `TestGoldZonePretrain`, `TestGoldZoneFinetune` in `tests/unit/test_export.py` — stubs for STORE-03

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| MinIO `Tagging=` actually applied to object | STORE-02 | Requires live MinIO container + `s3.list_object_tags()` verification | Run `klake ingest <url>` then inspect MinIO console for object tags |

---

## Validation Audit 2026-07-12

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

All 11 mapped tasks COVERED by green unit tests across `test_put_raw_domain.py`, `test_format_tags.py`, `test_put_object_tags.py`, `test_put_bronze.py`, `test_parse_silver_key.py`, `test_clean_silver_key.py`, `test_export.py` — 32 passed. STORE-02 tag-truncation (T-09-01) and best-effort fallback (T-09-02) asserted. One manual-only item (live MinIO `Tagging=` verification) remains manual.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** verified 2026-07-12
