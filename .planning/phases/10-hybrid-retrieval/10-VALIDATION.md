---
phase: 10
slug: hybrid-retrieval
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-10
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `10-RESEARCH.md` §Validation Architecture (HIGH confidence, verified against installed `qdrant-client==1.18.0`).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`pytest`, `pytest-asyncio`, `pytest-cov`) — present in pyproject |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` — `testpaths=["tests"]`, `asyncio_mode="auto"`, markers `integration`, `browser` |
| **Quick run command** | `uv run pytest tests/unit -q` |
| **Full suite command** | `uv run pytest -q` (integration needs a live Qdrant ≥ 1.10) |
| **Estimated runtime** | ~30–60s unit; integration adds live-Qdrant round-trips |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit -q`
- **After every plan wave:** Run `uv run pytest -q` (with a live Qdrant ≥ 1.10 for `-m integration`)
- **Before `/gsd-verify-work`:** Full suite must be green (incl. integration against a ≥ 1.10 server)
- **Max feedback latency:** ~60 seconds (unit)

---

## Per-Task Verification Map

> Task IDs are assigned by the planner (PLAN.md). Rows below are the requirement→test contract the planner MUST bind to concrete task IDs; the Nyquist auditor reconciles task IDs post-planning.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | 0 | RETR-01 | — | Named create-path builds `{"dense":VectorParams}` + `sparse_vectors_config{"sparse":IDF}` | unit (mock) | `pytest tests/unit/test_qdrant_hybrid.py::test_named_create_config -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | — | RETR-01 | T-mig | Migration re-embeds sparse for ALL points; count parity old==new before swap | integration | `pytest tests/integration/test_qdrant_hybrid_migration.py::test_reembed_parity -m integration -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | — | RETR-01 | — | Every migrated point has a non-empty `sparse` vector | integration | `pytest tests/integration/test_qdrant_hybrid_migration.py::test_all_points_have_sparse -m integration -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | — | RETR-01 | — | `Modifier.IDF` present in created collection's `sparse_vectors` config | integration | `pytest tests/integration/test_qdrant_hybrid_migration.py::test_idf_modifier_set -m integration -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 0 | RETR-01 | T-dos | Hybrid `query_points` uses two prefetch branches + `Fusion.RRF`; prefetch limit == `top_k+offset` | unit (mock) | `pytest tests/unit/test_qdrant_hybrid.py::test_hybrid_prefetch_limits -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 0 | RETR-01 | — | `get_collection_dim()` returns dense dim for named collections (no AttributeError) | unit | `pytest tests/unit/test_qdrant_hybrid.py::test_get_dim_named -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | — | RETR-01 | — | Payload keyword indexes survive named recreate; filtered hybrid doesn't full-scan | integration | `pytest tests/integration/test_qdrant_hybrid_migration.py::test_payload_indexes_survive -m integration -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 0 | RETR-03 | T-val | `KLAKE_SEARCH__MODE` resolves to `settings.search.mode`; default `hybrid` | unit | `pytest tests/unit/test_settings_search.py::test_search_mode_env -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 0 | RETR-03 | T-repudiation | `hybrid`/`sparse` on a sparse-less collection **raises** (fail loud, no dense fallback) | unit + integration | `pytest tests/unit/test_search_mode.py::test_fail_loud_missing_sparse -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | — | RETR-03 | — | `dense` mode works on BOTH legacy unnamed and migrated named collections | integration | `pytest tests/integration/test_qdrant_hybrid_migration.py::test_dense_both_shapes -m integration -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 0 | RETR-03 | T-val | `--mode` (CLI) and `?mode=` (API) thread through to `pipeline.search()` | unit | `pytest tests/unit/test_cli_search_mode.py -x` / `pytest tests/unit/test_api_search_mode.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | — | RETR-01/03 | — | Phase-7 payload filters work identically in dense/sparse/hybrid | unit + integration | `pytest tests/unit/test_search_filters.py -x` (extend existing) | ⚠️ extend | ⬜ pending |
| TBD | TBD | 0 | RETR-01 (D-07) | T-dos | Server-version preflight raises on server < 1.10 | unit (mock `info()`) | `pytest tests/unit/test_qdrant_hybrid.py::test_server_preflight -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_qdrant_hybrid.py` — named create-config, prefetch/RRF assembly, `get_collection_dim` branch, server-preflight, sparse-presence probe (RETR-01, D-07)
- [ ] `tests/unit/test_settings_search.py` — `SearchSettings` env resolution + default `hybrid` (RETR-03)
- [ ] `tests/unit/test_search_mode.py` — fail-loud on missing sparse (RETR-03, D-10)
- [ ] `tests/unit/test_cli_search_mode.py` + `tests/unit/test_api_search_mode.py` — `--mode` / `?mode=` threading
- [ ] `tests/integration/test_qdrant_hybrid_migration.py` — re-embed parity, all-sparse, IDF set, payload-index survival, dense-on-both-shapes (RETR-01); mirror `tests/integration/test_qdrant_alias_reindex.py`, `pytestmark = pytest.mark.integration`
- [ ] Extend `tests/unit/test_search_filters.py` — assert reused filter attaches on each prefetch branch (D-14)
- [ ] Framework install: none needed (pytest present)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `fastembed` install footprint + `Qdrant/bm25` model download on the CPU droplet | RETR-01 (D-01) | First-use HF model fetch over the network; supply-chain + runtime footprint can't be asserted in a unit test | After `uv add 'fastembed>=0.8,<0.9'`, run a one-shot embed of a sample string, confirm no torch/GPU deps pulled and the `Qdrant/bm25` model caches; this is a `checkpoint:human-verify` (RESEARCH Open Question 2), not an automated test |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
