---
phase: 22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco
fixed_at: 2026-07-18T02:21:04Z
review_path: .planning/phases/22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco/22-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 22: Code Review Fix Report

**Fixed at:** 2026-07-18T02:21:04Z
**Source review:** .planning/phases/22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco/22-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (fix_scope: critical_warning — CR-01, CR-02, WR-01, WR-02, WR-03; IN-01/IN-02 out of scope)
- Fixed: 5
- Skipped: 0

## Fixed Issues

### CR-01: `run_full_pipeline_audit()`'s real `chunk()` call runs outside the per-document error-isolation `try/except`

**Files modified:** `src/knowledge_lake/pipeline/quality_audit.py`
**Commit:** `7cc8040`
**Applied fix:** Wrapped the in-memory chunk-tally block (`_build_token_chunks()`/`_apply_substance_gate()`) and the real, persisting `chunk()` call in their own `try/except Exception` that increments `documents_errored`, logs `quality_audit.chunk_failed` with `exc_info=True`, and `continue`s — mirroring the existing parse/clean error-isolation pattern in the same loop. A transient S3/DB failure or a `chunk.py` conservation-invariant error on one document is now counted and skipped instead of aborting the whole domain scan. Verified against the existing test suite (`tests/unit/test_quality_audit.py`, `tests/unit/test_cli_quality_audit.py`) — all 43 tests across the touched files pass.

### CR-02: `export_rag_corpus()` call has no exception handling — `TrainEvalContaminationError` crashes the whole audit

**Files modified:** `src/knowledge_lake/pipeline/quality_audit.py`, `src/knowledge_lake/cli/app.py`
**Commit:** `6a54df1`
**Applied fix:** In `run_full_pipeline_audit()`, wrapped the `export_rag_corpus()` call in `try/except TrainEvalContaminationError`, logging `quality_audit.export_scoping_skipped_contamination` and falling back to `export_kept=0`/`export_junk=0`/`export_junk_rate=None` (the same "no chunks this run" shape already used elsewhere in the function) rather than propagating — section- and chunk-level rows are still returned. In `cli/app.py`'s `cmd_quality_audit`, wrapped the `--full` branch's `run_full_pipeline_audit(domain=domain)` call in `try/except (TrainEvalContaminationError, ValueError, LookupError)`, printing a clean `Error: ...` message and exiting with code 1 — matching the existing pattern already used by `cmd_export`.

### WR-01: `--full` writes a new gold-zone export + `Dataset` row on every invocation, contradicting the "read/measurement-only" framing

**Files modified:** `src/knowledge_lake/pipeline/quality_audit.py`, `src/knowledge_lake/cli/app.py`
**Commit:** `ca7ca70`
**Applied fix:** Applied fix option (c) from the review (documentation, not a behavior change — the underlying accumulation issue (a/b) is a larger scoping decision out of this fix pass' safe-change budget). Updated the module docstring in `quality_audit.py` to drop the blanket "read/measurement-only" claim and add an explicit `WR-01` note that `run_full_pipeline_audit()` persists real `chunk()` artifacts and writes a fresh gold-zone Parquet + `Dataset` row on every invocation with no cleanup. Updated the `--full` CLI option help text and `cmd_quality_audit`'s docstring in `app.py` to carry the same warning so `klake quality-audit --full --help` surfaces it directly to operators.

### WR-02: `check_train_eval_contamination()`'s near-dup overlap is a wholesale union, not a pairwise match — can over-flag unrelated documents

**Files modified:** `src/knowledge_lake/pipeline/export.py`
**Commit:** `7d5ce24`
**Applied fix:** `check_train_eval_contamination()` already computed `direct_overlap_count` and `near_dup_overlap_count` separately but `_enforce_no_contamination()`'s raised `TrainEvalContaminationError` message only surfaced the combined `contaminated_count`. Updated the raised message to break out `direct_overlap_count` vs `near_dup_overlap_count` explicitly (with a note that near-dup is a conservative flat-union check, not a pairwise match), so operators can immediately see when the conservative near-dup branch is firing broadly instead of a genuine direct collision. Full pairwise-cluster computation (the "ideally" option in the review) is a larger algorithmic change deferred as a follow-up, consistent with the review's "at minimum" framing.

### WR-03: `export_pretrain_corpus()` re-implements S3-key parsing instead of reusing `uri_to_key()`

**Files modified:** `src/knowledge_lake/pipeline/export.py`
**Commit:** `921c478`
**Applied fix:** Replaced the manual `cleaned.storage_uri.split("/", 3)` key-parsing logic with the already-imported `_uri_to_key()` helper (same one `export_rag_corpus()` uses), and added a `log.warning("export.pretrain.text_retrieval_failed", ..., exc_info=True)` inside the `except Exception` fallback so a malformed `storage_uri` or a failed `get_object()` now produces a debuggable log entry instead of a silently-empty-text row.

## Skipped Issues

None — all 5 in-scope findings (CR-01, CR-02, WR-01, WR-02, WR-03) were fixed and verified.

**Out of scope (fix_scope: critical_warning):** IN-01 (unused `Settings` import) and IN-02 (duplicated parse→clean loop) were not addressed — Info-tier findings are excluded from this fix pass by scope configuration.

**Verification:** All 5 fixes verified via Tier 1 (re-read modified sections) + Tier 2 (`python3 -c "import ast; ast.parse(...)"` syntax check on every touched file, no pre-existing or newly introduced syntax errors). Additionally ran the existing targeted test suite (`tests/unit/test_quality_audit.py`, `tests/unit/test_cli_quality_audit.py`, `tests/unit/test_export.py` — 43 tests) after all 5 fixes were applied; all pass.

---

_Fixed: 2026-07-18T02:21:04Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
