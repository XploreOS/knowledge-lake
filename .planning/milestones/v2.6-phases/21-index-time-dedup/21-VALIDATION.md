---
phase: 21
slug: index-time-dedup
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-17
validated: 2026-07-18
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
| 21-01-T1 | 21-01 | 1 | DEDUP-01 | V5 | `ChunkDedupLedger` schema (migration 0011) unique on `(collection, text_sha256)`; `claim_dedup_ledger_entry()` atomic first-writer-wins via `.returning()`, never `.rowcount` | unit + integration | `uv run pytest tests/unit/test_repo_dedup_ledger.py -x` | `tests/unit/test_repo_dedup_ledger.py` (11 tests) + live-Postgres migration round-trip | ✅ green |
| 21-01-T2 | 21-01 | 1 | DEDUP-03 | Repudiation | `get_dedup_ledger_entry()` pure lookup, never raises; `append_dedup_contributor()` count always `len(contributors)`, never drifts | unit | `uv run pytest tests/unit/test_repo_dedup_ledger.py -k contributor -x` | `tests/unit/test_repo_dedup_ledger.py::test_append_dedup_contributor_count_never_drifts` | ✅ green |
| 21-02-T1 | 21-02 | 1 | DEDUP-01 | V5 | `normalize_for_dedup` is exact-only (NFKC + whitespace collapse, no casefolding); `text_sha256_for`/`point_id_for_text` pure and deterministic | unit | `uv run pytest tests/unit/test_index_dedup.py -k "NormalizeForDedup or TextSha256For or PointIdForText" -x` | `tests/unit/test_index_dedup.py::TestNormalizeForDedup`, `::TestTextSha256For`, `::TestPointIdForText` (15 tests) | ✅ green |
| 21-03-T1 | 21-03 | 1 | DEDUP-03 | Denial of Service | `VectorStorePlugin.set_payload()` protocol + `QdrantVectorStore` impl: True on success, False on 404, re-raises other errors (self-heal precondition, D-26) | unit | `uv run pytest tests/unit/test_qdrant_store_set_payload.py -x` | `tests/unit/test_qdrant_store_set_payload.py::TestSetPayload` (3 tests) | ✅ green |
| 21-04-T1 | 21-04 | 1 | DEDUP-01 | Repudiation | `dedup_chunks()` router: empty-input no-session guard, all-distinct→new, within-batch/cross-call duplicates routed correctly; conservation invariant raises `RuntimeError` unconditionally | unit | `uv run pytest tests/unit/test_index_dedup.py -k TestDedupChunks -x` | `tests/unit/test_index_dedup.py::TestDedupChunks` (8 tests) | ✅ green |
| 21-04-T2 | 21-04 | 1 | DEDUP-02 | V6 | Re-processing the identical document a second time routes every chunk to duplicates (idempotent re-index via uuid5) | unit | `uv run pytest tests/unit/test_index_dedup.py -k idempotent -x` | `tests/unit/test_index_dedup.py::TestDedupChunks::test_reprocessing_identical_document_is_idempotent` | ✅ green |
| 21-05-T1 | 21-05 | 1 | DEDUP-03 | V4 | `index()`'s `duplicate_chunks` kwarg: no-op when omitted (payload filterability PAYLOAD-01/02 unaffected); `set_payload` called with ONLY `{contributors, contributor_count}` | unit | `uv run pytest tests/unit/test_index_dedup.py -k TestIndexDuplicateRouting -x` | `tests/unit/test_index_dedup.py::TestIndexDuplicateRouting` (6 tests) | ✅ green |
| 21-05-T2 | 21-05 | 1 | DEDUP-03 | Denial of Service | Contributors mirror capped at 50 with primary always first (even under timestamp-tie edge case); `set_payload` self-heals (re-embed + ledger repair) when the Qdrant point vanished | unit | `uv run pytest tests/unit/test_index_dedup.py -k "contributor_cap or self_heal" -x` | `tests/unit/test_index_dedup.py::TestIndexDuplicateRouting::test_contributor_cap_boundary_51_contributors_yields_50_length_mirror`, `::test_self_heal_on_vanished_point_reembeds_and_repairs_ledger` | ✅ green |
| 21-06-T1 | 21-06 | 1 | DEDUP-01 | — | `process_crawled()` (CLI/API/MCP) calls `dedup_chunks()` between `chunk()`/`embed()`; `embed()` receives only `new`, `index()` receives `new` + `duplicate_chunks=duplicates`; all-duplicates batch still calls both | unit | `uv run pytest tests/unit/test_process_crawled_dedup.py -x` | `tests/unit/test_process_crawled_dedup.py::TestProcessCrawledDedupWiring`, `::TestProcessCrawledDedupBoundaries` | ✅ green |
| 21-07-T1 | 21-07 | 1 | DEDUP-01 | — | New `dedup_chunks` Dagster asset sits between `chunk_document`/`embed_chunks`; `embed_chunks`/`index_chunks` rewired to consume its output | unit | `python -c "from knowledge_lake.dagster_defs.definitions import defs; defs.resolve_job_def('core_pipeline_e2e_job')"` | `src/knowledge_lake/dagster_defs/assets.py`, `definitions.py` (modified) | ✅ green |
| 21-07-T2 | 21-07 | 1 | DEDUP-01 | Repudiation | `core_pipeline_e2e_job`'s `AssetSelection` includes `dedup_chunks` between `chunk_document`/`embed_chunks` (Pitfall 1 — KL-06 regression class); guard proven non-vacuous | unit | `uv run pytest tests/unit/test_asset_ordering.py -k dedup_chunks -x` | `tests/unit/test_asset_ordering.py::test_job_selection_contains_dedup_chunks`, `::test_dedup_chunks_is_ancestor_and_executable_for_index_chunks`, `::test_embed_chunks_ordering_edge_survives_inside_the_job` | ✅ green |
| 21-08-T1 | 21-08 | 1 | DEDUP-02 | Tampering | D-18 parity: CLI path and Dagster path produce byte-identical deterministic point IDs + `contributor_count==2` + matching `text_sha256` for the same shared text, against the live dev stack | integration | `uv run pytest tests/integration/test_dedup_cli_dagster_parity.py -x` | `tests/integration/test_dedup_cli_dagster_parity.py::TestDedupCliDagsterPointIdLedgerParity` (3 tests) | ✅ green |
| 21-08-T2 | 21-08 | 1 | DEDUP-01, DEDUP-03 | — | `reindex_collection()` (both `copy_all_points()` default and `refresh_payload=True` modes) never disturbs a deduplicated point's `contributors`/`contributor_count` payload or its ledger row (D-08) | integration | `uv run pytest tests/integration/test_dedup_reindex_survival.py -x` | `tests/integration/test_dedup_reindex_survival.py::TestDedupSurvivesDefaultCopyReindex`, `::TestDedupSurvivesRefreshPayloadReindex` | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs assigned by the planner (21-index-time-dedup, 2026-07-17): 8 plans, 1 wave (sequential dependency chain — 21-04/05 build on 21-01/02/03; 21-06/07 build on 21-04/05; 21-08 proves 21-06/07 end-to-end), 14 tasks total.*

---

## Wave 0 Requirements

All gaps closed within the plans' own tasks:

- [x] `tests/unit/test_index_dedup.py` — new file (class-per-concern structure, 5 classes/29+ tests across plans 21-02/04/05), covering `normalize_for_dedup`, `point_id_for_text`, `dedup_chunks()` conservation invariant, contributor cap/primary logic, and the `set_payload` self-heal branch (mocked `VectorStorePlugin`). Correctly not named `test_dedup.py` (that's the unrelated MinHash near-dup test file)
- [x] `tests/integration/test_dedup_cli_dagster_parity.py` — new file, D-18's parity guard proven against the live dev stack — Plan 21-08, Task 1
- [x] Extended `tests/unit/test_asset_ordering.py`'s `TestCorePipelineE2eJobSelectionPreservesOrdering` with 3 assertions that `dedup_chunks` is present/ordered in `core_pipeline_e2e_job`'s selection, proven non-vacuous by manual removal — Plan 21-07, Task 2
- [x] `tests/unit/test_qdrant_store_set_payload.py` — new file, unit test for `set_payload()`: success, 404-as-False, non-404-propagates — Plan 21-03
- [x] Framework install: none — pytest already present and configured

**Deferred, out-of-scope note (not a gap):** `tests/unit/test_dagster_retry_policies.py`'s `_get_pipeline_assets()` roster (9 assets) was not extended to include `dedup_chunks` — logged explicitly in 21-07-SUMMARY.md as out of scope (that test only asserts retry_policy on assets it already names, not roster completeness; `dedup_chunks` does carry the correct `retry_policy`). Does not affect any requirement in this phase's binding map.

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies — all 14 tasks across 8 plans carry `<verify><automated>` commands
- [x] Sampling continuity: no 3 consecutive tasks without automated verify — every task has one
- [x] Wave 0 covers all MISSING references — all gaps closed within the plans' own tasks
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated — all 8 plans (14 tasks) executed and verified green; full suite reached 1175 passed, 3 skipped, 6 xfailed, 0 failed at phase completion (including 2 new live-stack integration test files); retroactive audit 2026-07-18 re-confirmed all named test functions/classes present

---

## Validation Audit 2026-07-18

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

Reconstructed per-task map from all 8 plans' SUMMARY.md files (task IDs/plan/wave were TBD placeholders at planning time — this was the largest phase in the milestone). Cross-checked every named test function/class against source via grep — all present, including the two live-stack integration test files (`test_dedup_cli_dagster_parity.py`, `test_dedup_reindex_survival.py`). Noted one legitimate, explicitly-scoped-out deferred item (test_dagster_retry_policies.py's asset roster) that does not constitute a requirement gap. No gaps requiring auditor intervention.
