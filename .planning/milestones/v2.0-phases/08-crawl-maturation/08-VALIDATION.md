---
phase: 8
slug: crawl-maturation
status: verified
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-08
validated: 2026-07-12
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest with asyncio_mode = "auto" |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/unit/ -v -x` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/unit/ -v -x`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 08-01-01 | 01 | 1 | CRAWL-01 | — | N/A | unit | `pytest tests/unit/test_robots_ratelimit.py -x` | ✅ extended | ✅ green |
| 08-01-02 | 01 | 1 | CRAWL-01 | — | N/A | unit | `pytest tests/unit/test_robots_ratelimit.py -x` | ✅ extended | ✅ green |
| 08-02-01 | 02 | 1 | CRAWL-02 | — | N/A | unit | `pytest tests/unit/test_crawl_all.py -x` | ✅ | ✅ green |
| 08-02-02 | 02 | 1 | CRAWL-02 | — | N/A | unit | `pytest tests/unit/test_crawl_all.py -x` | ✅ | ✅ green |
| 08-03-01 | 03 | 1 | CRAWL-03 | T-08-SSRF | Rate-limit amplification cap | unit | `pytest tests/unit/test_robots_ratelimit.py::TestAdaptiveRateLimiter -x` | ✅ | ✅ green |
| 08-03-02 | 03 | 1 | CRAWL-03 | — | N/A | unit | `pytest tests/unit/test_robots_ratelimit.py::TestAdaptiveRateLimiter -x` | ✅ | ✅ green |
| 08-04-01 | 04 | 1 | ENRICH-07 | — | Partial JSON recovery never re-raises ValidationError through tenacity | unit | `pytest tests/unit/test_enrich.py::test_partial_enrichment -x` | ✅ | ✅ green |
| 08-04-02 | 04 | 1 | ENRICH-07 | — | Partial result stored under partial: key | unit | `pytest tests/unit/test_enrich.py::test_partial_cache_key -x` | ✅ | ✅ green |
| 08-04-03 | 04 | 1 | ENRICH-07 | — | Complete result lookup ignores partial cache entry | unit | `pytest tests/unit/test_enrich.py::test_partial_not_returned_as_complete -x` | ✅ | ✅ green |
| 08-05-01 | 05 | 1 | INGEST-10 | T-08-SSRF | validate_public_url called before every ingest_url for linked doc | unit | `pytest tests/unit/test_linked_doc_ingest.py -x` | ✅ | ✅ green |
| 08-05-02 | 05 | 1 | INGEST-10 | T-08-SSRF | SSRF-blocked linked link counted as failed, does not abort parent crawl | unit | `pytest tests/unit/test_linked_doc_ingest.py -x` | ✅ | ✅ green |
| 08-05-03 | 05 | 1 | INGEST-10 | — | MAX_LINKED_DOCS_PER_PAGE cap enforced | unit | `pytest tests/unit/test_linked_doc_ingest.py -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_crawl_all.py` — stubs for CRAWL-02 (crawl_all_sources + CLI)
- [ ] `tests/unit/test_robots_ratelimit.py::TestAdaptiveRateLimiter` — stubs for CRAWL-03 (add class to existing file)
- [ ] `tests/unit/test_enrich.py::test_partial_enrichment`, `test_partial_cache_key`, `test_partial_not_returned_as_complete` — stubs for ENRICH-07 (add to existing file)
- [ ] `tests/unit/test_linked_doc_ingest.py` — stubs for INGEST-10

*Existing `tests/unit/test_robots_ratelimit.py` covers CRAWL-01 extensions — extend in place.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end crawl-all against live registered sources | CRAWL-02 | Requires running Docker Compose stack with live sources | Run `klake crawl-all --domain healthcare` after starting services |
| Adaptive backoff triggers on real 429 response | CRAWL-03 | No test server emitting real 429 | Monitor logs for `crawl.backoff_applied` structured log entry |

---

## Validation Audit 2026-07-12

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

All 12 mapped tasks COVERED by green unit tests across `test_robots_ratelimit.py`, `test_crawl_all.py`, `test_enrich.py`, `test_linked_doc_ingest.py` — 50 passed, 1 xfailed. The HIGH-severity INGEST-10 linked-doc SSRF guard (T-08-SSRF) is asserted by `test_linked_doc_ingest.py`. Two manual-only items (live crawl-all, real-429 backoff) remain manual — require live services.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** verified 2026-07-12
