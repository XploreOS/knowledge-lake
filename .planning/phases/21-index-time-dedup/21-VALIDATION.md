---
phase: 21
slug: index-time-dedup
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-17
---

# Phase 21 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest, `xfail_strict = true` (`pyproject.toml` `[tool.pytest.ini_options]`, lines 121-129) |
| **Config file** | `pyproject.toml:121` |
| **Quick run command** | `uv run pytest tests/unit/test_index_dedup.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~30s (quick), full suite matches existing 971+ test baseline (as of Phase 20 completion) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit/test_index_dedup.py -x` (or the file under active edit)
- **After every plan wave:** Run `uv run pytest tests/unit -x` plus the new integration parity test (`tests/integration/test_dedup_cli_dagster_parity.py`)
- **Before `/gsd-verify-work`:** Full suite must be green (`uv run pytest`), `xfail_strict=true` holds
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 21-01-01 | 01 | TBD | DEDUP-01 | V5 | Two docs with identical boilerplate text produce exactly 1 Qdrant point; both chunk artifacts persist (WR-05 intact) | unit + integration | `uv run pytest tests/unit/test_index_dedup.py -x` | ❌ W0 | ⬜ pending |
| 21-01-02 | 01 | TBD | DEDUP-01 | V5 | `normalize_for_dedup` is exact-only: no casefolding/punctuation/stopword removal | unit | `uv run pytest tests/unit/test_index_dedup.py -k normalize -x` | ❌ W0 | ⬜ pending |
| 21-01-03 | 01 | TBD | DEDUP-01 | Repudiation | Conservation invariant: `len(new)+len(duplicates)==len(chunks_in)` asserted unconditionally | unit | `uv run pytest tests/unit/test_index_dedup.py -k conservation -x` | ❌ W0 | ⬜ pending |
| 21-02-01 | 02 | TBD | DEDUP-02 | V6 | Re-processing the same document produces the same point ID (idempotent re-index via uuid5) | unit | `uv run pytest tests/unit/test_index_dedup.py -k idempotent -x` | ❌ W0 | ⬜ pending |
| 21-02-02 | 02 | TBD | DEDUP-02 | Tampering | CLI/Dagster parity: identical point IDs + ledger state for the same input (D-18) | integration | `uv run pytest tests/integration/test_dedup_cli_dagster_parity.py -x` | ❌ W0 | ⬜ pending |
| 21-03-01 | 03 | TBD | DEDUP-03 | V4 | Deduplicated point filterable by source_id/domain/format (PAYLOAD-01/02 unaffected) | unit | `uv run pytest tests/unit/test_index_dedup.py -k payload_filter -x` | ❌ W0 | ⬜ pending |
| 21-03-02 | 03 | TBD | DEDUP-03 | — | `contributors[]` lists all source docs; primary = earliest `primary_created_at`; Qdrant mirror capped at 50 with `contributor_count` exact | unit | `uv run pytest tests/unit/test_index_dedup.py -k contributors -x` | ❌ W0 | ⬜ pending |
| 21-03-03 | 03 | TBD | DEDUP-03 | Denial of Service | `set_payload` self-heals when ledger row exists but Qdrant point is gone (D-24) | unit (mocked vstore) | `uv run pytest tests/unit/test_index_dedup.py -k self_heal -x` | ❌ W0 | ⬜ pending |
| 21-04-01 | 04 | TBD | — | — | New asset `dedup_chunks` is present in `core_pipeline_e2e_job`'s selection (Pitfall 1 — KL-06 regression class) | unit | extend `tests/unit/test_asset_ordering.py` (existing file, new test method) | ❌ W0 (extends existing) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Plan/Wave columns are TBD — the planner assigns final plan IDs and wave numbers; this table's Req ID → Test mapping is the binding contract.*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_index_dedup.py` — new file covering `normalize_for_dedup`, `point_id_for_text`, `dedup_chunks()` conservation invariant, contributor cap/primary logic, and the `set_payload` self-heal branch (mocked `VectorStorePlugin`). Do NOT name this `test_dedup.py` — that filename is already taken by the unrelated MinHash near-dup tests (CLEAN-03).
- [ ] `tests/integration/test_dedup_cli_dagster_parity.py` — new file, D-18's parity guard: same fixture input through `process.py`'s CLI path and the Dagster asset path must produce identical point IDs and identical `chunk_dedup_ledger` rows.
- [ ] Extend `tests/unit/test_asset_ordering.py`'s `TestCorePipelineE2eJobSelectionPreservesOrdering` with an assertion that `dedup_chunks` is present in `core_pipeline_e2e_job`'s selection.
- [ ] `tests/unit/test_qdrant_store_set_payload.py` (or add to an existing qdrant_store test file) — unit test for the new `set_payload()` method, asserting both the success path and the 404-caught-as-`False` path.
- [ ] Framework install: none — pytest already present and configured.

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
