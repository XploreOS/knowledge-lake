---
phase: 04
slug: enrichment-embedding-search
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-05
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 (installed; `asyncio_mode = "auto"` in `pyproject.toml`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/unit/test_enrich.py tests/unit/test_index_alias.py -x -v` |
| **Full suite command** | `pytest tests/unit tests/integration -v` (integration tests marked `@pytest.mark.integration`, may require running services — all currently running in this environment) |
| **Estimated runtime** | ~30 seconds (unit) / ~90 seconds (full, including live Qdrant integration) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/unit/test_enrich.py tests/unit/test_index_alias.py -x`
- **After every plan wave:** Run `pytest tests/unit tests/integration -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-XX-01 | TBD | TBD | ENRICH-01 | — | No hardcoded provider model IDs in enrichment call | unit (source-scan) | `pytest tests/unit/test_enrich.py::test_no_hardcoded_provider_model_ids -x` | ❌ W0 | ⬜ pending |
| 04-XX-02 | TBD | TBD | ENRICH-02 | — | Deterministic fields extracted without an LLM call | unit | `pytest tests/unit/test_deterministic.py -x` | ❌ W0 | ⬜ pending |
| 04-XX-03 | TBD | TBD | ENRICH-03 | Prompt injection (Tampering) | LLM call produces valid, schema-validated EnrichmentResult JSON | unit (mocked `litellm.completion`) | `pytest tests/unit/test_enrich.py::test_enrich_produces_valid_result -x` | ❌ W0 | ⬜ pending |
| 04-XX-04 | TBD | TBD | ENRICH-04 | — | Re-running enrichment on unchanged content is a no-op | unit | `pytest tests/unit/test_enrich.py::test_enrich_cache_hit_is_noop -x` | ❌ W0 | ⬜ pending |
| 04-XX-05 | TBD | TBD | ENRICH-05 | Cost DoS (Denial of Service) | Budget cap halts gracefully, no crash | unit (mocked cost + spend accumulation past cap) | `pytest tests/unit/test_enrich.py::test_budget_exceeded_halts_gracefully -x` | ❌ W0 | ⬜ pending |
| 04-XX-06 | TBD | TBD | ENRICH-06 | — | Embedding provider switch via config | unit (existing coverage) | `pytest tests/unit/test_builtin_plugins.py -k embedder -x` | ✅ Exists | ⬜ pending |
| 04-XX-07 | TBD | TBD | INDEX-01 | Payload injection (Tampering/Info Disclosure) | Payload carries domain/document_type/keywords/quality_score, bounded length | unit (mocked Qdrant client) | `pytest tests/unit/test_index_payload.py -x` | ❌ W0 | ⬜ pending |
| 04-XX-08 | TBD | TBD | INDEX-02 | — | Alias resolves after reindex without downtime | integration (live Qdrant) | `pytest tests/integration/test_qdrant_alias_reindex.py -x -m integration` | ❌ W0 | ⬜ pending |
| 04-XX-09 | TBD | TBD | INDEX-03 | — | Search returns filtered, cited results via CLI/API, backward-compatible | unit + integration | `pytest tests/unit/test_search_filters.py tests/integration/test_search_e2e.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*Task IDs are placeholders — the planner assigns real plan/task IDs; this map's Req ID / Test Type / Command columns are locked from research.*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_enrich.py` — stubs for ENRICH-01, 02, 03, 04, 05
- [ ] `tests/unit/test_deterministic.py` — covers ENRICH-02 in isolation
- [ ] `tests/unit/test_index_payload.py` — covers INDEX-01 payload extension
- [ ] `tests/integration/test_qdrant_alias_reindex.py` — covers INDEX-02 (live Qdrant, mirrors the manual verification performed during research: create v1 behind alias, reindex to v2, confirm atomic swap, confirm old collection retained until explicit drop)
- [ ] `tests/unit/test_search_filters.py` — covers INDEX-03 filter params, backward-compatibility (no-filter calls unchanged)
- [ ] Framework install: none — pytest already configured and passing for Phases 1-3

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real Bedrock LLM call succeeds with the configured 2026-era model IDs (`claude-haiku-4-5-20260925-v1:0`, `claude-sonnet-4-5-20260925-v1:0`) | ENRICH-01, ENRICH-03 | No AWS credentials available in the research/dev environment — cannot verify the model IDs are live/available without real Bedrock access | Run `klake enrich <doc>` (or equivalent) against a real document with `AWS_BEDROCK_API_KEY` set; confirm a non-error structured response; flag as a `checkpoint:human-verify` task at Wave 0 per RESEARCH.md Open Question #2 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
