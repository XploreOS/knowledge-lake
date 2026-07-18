---
phase: 22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco
verified: 2026-07-18T02:33:47Z
status: passed
score: 8/9 must-haves verified
behavior_unverified: 0
overrides_applied: 0
human_verification:

  - test: "Decide how REQUIREMENTS.md Success Criterion #1 ('<5% garbage chunks') should be read/reworded now that a real measurement exists"
    expected: "A product/maintainer decision on whether criterion #1 is (a) considered met via export_junk_rate (0.0%, the metric that represents garbage actually reaching the delivered corpus), (b) considered unmet via the literal chunk_garbage_rate reading (45.64%, the gate's own candidate-rejection rate), or (c) REQUIREMENTS.md's wording is revised to reference export_junk_rate explicitly, as 22-03-SUMMARY.md itself recommends considering"
    why_human: "This is a definitional/product judgment about what the milestone's original criterion was intended to measure, not something a grep or test can resolve. The phase surfaced it explicitly rather than silently picking an answer; a maintainer must sign off on the interpretation before the milestone tech-debt item is considered fully closed."
---

# Phase 22: Address tech debt: measure garbage/junk rates end-to-end, reconcile Nyquist validation — Verification Report

**Phase Goal:** Produce genuine, reproducible chunk-level and export-level measurements of the v2.6 milestone's two quantitative success criteria (<5% garbage chunks, <2% junk gold-export rows) against real reprocessed data from the 34 healthcare sources — scoped to avoid dilution by the ~4,512 pre-v2.6 chunk artifacts (D-04) — and document the export dedup-awareness boundary as an accepted design decision (D-07). Closes the two open tech-debt items from `.planning/v2.6-MILESTONE-AUDIT.md`.

**Verified:** 2026-07-18T02:33:47Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `run_full_pipeline_audit()` returns chunk-level `garbage_rate` via the frozen `rejected/(rejected+kept)` formula, derived purely from in-memory gate annotation (no new gate logic) | VERIFIED | `quality_audit.py:339-355` calls `_build_token_chunks()`/`_apply_substance_gate()` (imported unmodified from `chunk.py`) and tallies `substance_passed` directly off the mutated list; `chunk_garbage_rate` formula at lines 389-392 is byte-identical in structure to the frozen Phase-17 section formula. `TestRunFullPipelineAuditChunkTally` (2 tests) pass. |
| 2 | `run_quality_audit()`'s `clean()` call now threads `domain_filters`, closing Pitfall 1 | VERIFIED | `quality_audit.py:158-161`: `clean(parsed_id, source_id, parsed_doc=parsed_doc, settings=s, domain_filters=domain_filters)`, resolved once via new `_resolve_domain_filters()` (line 98). `TestRunQualityAuditDomainFiltersGap::test_domain_filters_threaded_into_existing_clean_call` passes. |
| 3 | A pre-v2.6 chunk artifact with no `substance_passed` key never inflates/dilutes the reported export-junk rate, even though `export_rag_corpus()` itself scans the full domain-wide chunk population (D-04) | VERIFIED | `TestRunFullPipelineAuditExportScoping::test_dilution_regression_excludes_pre_v26_chunks` independently proves both halves: `summary["export_kept"]==1` (scoped, excludes the old chunk) while the real unmodified exported Parquet contains `df.height == 2` (the dilution risk is real and would have fired without the scoping fix). Test passes; logic confirmed by direct code read (`this_run_chunk_ids` built only from `chunk()`'s own return value, `quality_audit.py:366-369`). |
| 4 | `export_rag_corpus()`'s docstring documents D-07 (chunk-artifact-scoped, not dedup-collapsed) with zero export.py logic/behavior change | VERIFIED | `export.py:16-25` (docstring bullet) added; the row-skip filter line `if not meta.get("substance_passed", True):` is byte-identical before (commit `9235fcc`) and after (current) this phase — diffed directly. `tests/unit/test_export.py` (22 tests) unchanged and green. |
| 5 | `klake quality-audit --full` prints a per-source table with chunk-level columns plus a summary comparing measured rates against 28%/33% baselines; `--full --json` emits the exact `run_full_pipeline_audit()` dict; non-`--full` behavior is unchanged | VERIFIED | Live `uv run klake quality-audit --help` confirms `--full` is listed alongside `--domain`/`--json` with WR-01 side-effect warning text. `TestCliQualityAuditFullFlag` (3 tests) + `TestCliQualityAuditHelp::test_help_lists_full_flag` pass; existing 5 non-`--full` tests unmodified and passing. |
| 6 | A real `klake quality-audit --domain healthcare --full --json` run against the live 34-source healthcare corpus produced actual kept/rejected chunk counts and an export-junk count, reported against 28%/33% baselines | VERIFIED | 22-03-SUMMARY.md captures a full JSON summary (`sources_count: 34`, `chunks_considered: 2397`, `chunk_garbage_rate: 0.4564`, `export_kept: 984`, `export_junk_rate: 0.0`). Independently corroborated live: Postgres `datasets` table shows real `rag_corpus` dataset rows created at `2026-07-17 19:36:51` / `19:38:51` (matching the SUMMARY's stated 18:27–19:40 execution window), and `artifacts` table shows 993 chunk rows now carrying a `substance_passed` key (up from the pre-phase baseline of 9 cited in 22-CONTEXT.md) — this is real, not fabricated, output. |
| 7 | If `chunk_garbage_rate` and `export_junk_rate` do not converge as expected (`export_junk_rate <= chunk_garbage_rate`), the anomaly is explicitly flagged, not silently reported | VERIFIED | 22-03-SUMMARY.md explicitly checks and states "0.0% <= 45.64% — holds. No anomaly requiring investigation." Convergence direction is correct; no anomaly was present so no further investigation was required. |
| 8 | Nyquist reconciliation for phases 17-21 is explicitly logged as an operator follow-up (`/gsd-validate-phase`), never implemented as phase-22 code | VERIFIED | 22-03-SUMMARY.md's "Operational Follow-up" section lists the exact 5 commands (`/gsd-validate-phase 17`..`21`). Independently confirmed live: phases 18-21's `VALIDATION.md` still show `status: draft`, `nyquist_compliant: false` — i.e. genuinely not yet reconciled, consistent with "logged as follow-up, not executed by this phase." Phase 22 introduced zero code touching those phases' VALIDATION.md files. |
| 9 | The milestone's literal `<5% garbage chunks` criterion is either met, or the gap is explained rather than glossed over | ⚠️ SEE HUMAN VERIFICATION | See interpretive analysis below — the phase's own reasoning is sound and transparent, but resolving *which* number counts as "the" criterion-#1 metric is a product decision this verifier cannot make unilaterally. |

**Score:** 8/9 truths verified (1 routed to human decision, not a code gap)

### Independent Assessment of the Interpretive Finding (chunk_garbage_rate 45.64% vs export_junk_rate 0.0%)

This phase's central, real finding deserves scrutiny beyond trusting the SUMMARY's own narrative, per this verification's brief.

**The reasoning is sound, not a rationalization of an inconvenient number:**

- The original 28%/33% baselines (`MILESTONE-CONTEXT.md`) were a **post-hoc manual/heuristic classification of already-delivered chunks** (too-short, no-real-sentences, exact-duplicate, boilerplate, marketing categories applied to the 4,499 chunks that existed *before* any substance gate shipped).
- `chunk_garbage_rate` (45.64%) is a **live gate-rejection rate of raw candidate chunks** — `_build_token_chunks()` generates candidates, `_apply_substance_gate()` marks how many the enforce-mode gate would reject *before persistence*. This is a genuinely different measurement basis than the original 28%: it measures how hard the gate is working on raw material, not how much garbage ends up delivered.
- `export_junk_rate` (0.0%) measures, of this run's own **already-persisted** (enforce-mode-passed) chunks, how many `export_rag_corpus()`'s own `substance_passed` row-skip filter would additionally reject. Because enforce-mode `chunk()` never persists a rejected chunk in the first place, this number is close to definitionally low for chunks produced by this very run — it primarily proves the export path reads/respects the same gate metadata correctly (no metadata write/read mismatch bug), rather than being an independent content audit of "is this text actually garbage." The SUMMARY does not claim otherwise, but a reader could over-interpret "0%, decisively beating the target" as an independent quality audit; it is better understood as a **wiring/consistency confirmation** that the gate's decision is what actually reaches the corpus, layered on top of the (separately-validated, in Phases 17-20) assumption that the gate's own heuristics are a reasonable proxy for "garbage."
- Given that, `export_junk_rate` is the more defensible "successor" to the original 33%-junk-rows criterion (both measure garbage in *delivered* content), and the SUMMARY's identification of this is correct methodology, not evasion. The 45.64% headline number is reported prominently, not hidden, and the true nature of the mismatch (different measurement basis, not a regression) is explained rather than glossed over.

**What this verifier will NOT do:** unilaterally declare "criterion #1 met" or "criterion #1 failed" — REQUIREMENTS.md's literal wording ("<5% garbage chunks") is ambiguous between "candidate-rejection rate" and "garbage reaching the corpus," and 22-03-SUMMARY.md itself flags that an operator/product decision on rewording is warranted. This is exactly the kind of judgment call that belongs in human verification, not a silently-assumed PASS or FAIL.

**Conclusion:** the interpretive reasoning is sound; the phase's own document is honest about the split verdict. This is why overall status is `human_needed` rather than `passed` or `gaps_found` — no code gap exists, but a definitional decision on the milestone's headline criterion remains open and should not be silently resolved by this verifier.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/knowledge_lake/pipeline/quality_audit.py` | `run_full_pipeline_audit()` + fixed `run_quality_audit()` | VERIFIED | Both functions present, substantive (508 lines total), wired to `chunk.py`/`export.py`/`clean.py` real functions; CR-01/CR-02 fixes applied (see below). |
| `src/knowledge_lake/pipeline/export.py` | D-07 docstring note, zero logic change | VERIFIED | Docstring bullet present; `substance_passed` filter line byte-identical to pre-phase commit `9235fcc`. WR-02/WR-03 fixes also applied here (see Code Review Fix Verification below), unrelated to D-07's own scope but part of this phase's fix pass. |
| `tests/unit/test_quality_audit.py` | domain_filters-gap, chunk-tally, dilution-regression tests | VERIFIED | 12 test functions across 10 classes, all pass. |
| `src/knowledge_lake/cli/app.py` | `--full` Typer option, dual table/JSON output | VERIFIED | Confirmed live via `klake quality-audit --help`; non-`--full` call site unchanged; CR-02 exception handling present. |
| `tests/unit/test_cli_quality_audit.py` | `--full` table/JSON/help tests | VERIFIED | 9 test functions across 5 classes, all pass. |
| `.planning/phases/22-.../22-03-SUMMARY.md` | Real measurement narrative + captured JSON | VERIFIED | Present, contains full captured `summary` JSON plus before/after comparison table and interpretive note (assessed above). |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `quality_audit.run_full_pipeline_audit()` | `chunk._build_token_chunks()`/`_apply_substance_gate()` | direct import/call | WIRED | Confirmed at `quality_audit.py:234, 339-345`. |
| `quality_audit.run_full_pipeline_audit()` | `export.export_rag_corpus()` | one real call per audit run, after per-source loop, Parquet read-back | WIRED | Confirmed at `quality_audit.py:447-481`, positioned strictly after the `for source_id, source_name in source_rows` loop (grep confirms exactly one call site, not inside any loop). |
| `quality_audit.run_quality_audit()`/`run_full_pipeline_audit()` | `domains.loader.DomainLoader.from_name(...).filters` | `_resolve_domain_filters()` helper | WIRED | Both functions call `_resolve_domain_filters(s)` exactly once each (lines 98, 243). |
| `cli.app.cmd_quality_audit` | `quality_audit.run_full_pipeline_audit()` | function-local import, `--full` branch only | WIRED | Confirmed at `app.py:1011-1019`; non-`--full` path untouched. |

### Code Review Fix Verification (independent re-check, not trusting 22-REVIEW-FIX.md's narrative)

| Finding | Claimed Fix | Independently Verified |
|---------|-------------|------------------------|
| CR-01 (chunk() call unguarded) | Wrapped chunk-tally + real `chunk()` call in own `try/except Exception` | CONFIRMED — `quality_audit.py:334-384`, increments `documents_errored`, logs `quality_audit.chunk_failed` with `exc_info=True`, `continue`s. Mirrors the pre-existing parse/clean pattern exactly. |
| CR-02 (unhandled `TrainEvalContaminationError`) | `try/except TrainEvalContaminationError` in `quality_audit.py`; `try/except (TrainEvalContaminationError, ValueError, LookupError)` in `cli/app.py` | CONFIRMED — `quality_audit.py:454-469` (falls back to `export_kept=0/export_junk=0/export_junk_rate=None`, logs `quality_audit.export_scoping_skipped_contamination`); `app.py:1011-1019` (catches and prints `Error: ...`, exits 1), matching `cmd_export`'s existing pattern. |
| WR-01 (silent gold-zone accumulation) | Documentation-only fix: module docstring + CLI help/docstring updated | CONFIRMED — `quality_audit.py:27-32` explicit WR-01 note; `app.py` `--full` option help text and command docstring both carry the same warning, visible live via `--help`. |
| WR-02 (near-dup overlap wholesale union) | Error message now breaks out `direct_overlap_count` vs `near_dup_overlap_count` | CONFIRMED — `export.py:225-252`; underlying set-union computation itself unchanged (as the fix report states — algorithmic fix deferred), only the raised message's transparency improved. |
| WR-03 (`export_pretrain_corpus()` re-implements S3-key parsing) | Replaced with `_uri_to_key()`, added `log.warning(..., exc_info=True)` on fallback | CONFIRMED — `export.py:491-503`. |

Full targeted suite (`tests/unit/test_quality_audit.py tests/unit/test_cli_quality_audit.py tests/unit/test_export.py`, 43 tests) re-run independently by this verifier: **43 passed**. Full project suite re-run independently: **1185 passed, 3 skipped, 6 xfailed, 0 failed** — matches both 22-01/22-02/22-03-SUMMARY.md's claimed counts and 22-REVIEW-FIX.md's claim exactly.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|--------------|------------|-------------|--------|----------|
| MEAS-01 (extended) | 22-01, 22-02, 22-03 | Quality audit harness now also measures chunk-level + export-level rates | SATISFIED | `run_full_pipeline_audit()` + `--full` CLI + real live run captured. REQUIREMENTS.md already lists MEAS-01 as "Complete" under Phase 17 — Phase 22 explicitly declares no new REQ-IDs (per 22-CONTEXT.md), extending rather than re-satisfying this ID. |
| QUAL-03 (extended) | 22-01 | Chunk min-substance gate's rejection counts are now aggregated corpus-wide via the audit harness | SATISFIED | `chunk_garbage_rate`/`chunk_rejection_reasons` tallying in `run_full_pipeline_audit()`; already listed "Complete" under Phase 20 in REQUIREMENTS.md. |
| EXPORT-01 (extended) | 22-01, 22-03 | Gold RAG export quality gate's effect is now measured end-to-end, scoped correctly (D-04) | SATISFIED | `export_kept`/`export_junk`/`export_junk_rate` scoping + dilution regression test + real captured run; already listed "Complete" under Phase 20. |

No orphaned requirements: `grep -E "Phase 22" .planning/REQUIREMENTS.md` returns zero matches, consistent with 22-CONTEXT.md's explicit statement that this phase adds no new REQ-IDs and only extends already-"Complete" IDs. REQUIREMENTS.md's Phase Mapping/Traceability tables were correctly left unmodified.

### Anti-Patterns Found

None found in the phase-touched files (`quality_audit.py`, `export.py`, `cli/app.py`, both test files) beyond what the code review already caught and the fix pass resolved. No `TBD`/`FIXME`/`XXX` markers, no placeholder returns, no stub handlers introduced by this phase.

### Human Verification Required

1. **Decide how REQUIREMENTS.md Success Criterion #1 should be interpreted/reworded now that a real measurement exists**
   **Test:** Review the Interpretive Note in `22-03-SUMMARY.md` and the independent assessment above; decide whether `export_junk_rate` (0.0%, met) or the literal `chunk_garbage_rate` (45.64%, not met) is the intended criterion-#1 metric, or whether REQUIREMENTS.md's wording needs revision.
   **Expected:** A documented maintainer decision — this affects whether the v2.6 milestone's tech-debt item #2 is considered fully closed or needs a REQUIREMENTS.md wording update as a small follow-up.
   **Why human:** Definitional/product judgment about original intent, not a code-verifiable fact. Both the phase's own SUMMARY and this independent re-analysis converge on the same conclusion: the finding is genuine, correctly measured, and honestly reported, but the "is criterion #1 met" question requires a human call.

### Gaps Summary

No code gaps found. All must-have truths, artifacts, and key links from both PLAN frontmatter and the roadmap goal are verified present, substantive, and correctly wired. The 5 code-review findings (2 critical, 3 warning) were independently confirmed fixed and correctly applied — not just trusted from 22-REVIEW-FIX.md's narrative. The full test suite (1185 passed, 0 failed) was independently re-run and matches all claimed counts. The one open item is a human interpretive decision on how to read the milestone's literal "<5% garbage chunks" wording against a genuinely different (and more informative) measurement basis than the original audit used — explicitly surfaced by the phase rather than hidden, and appropriately routed here for human sign-off rather than assumed one way or the other.

---

_Verified: 2026-07-18T02:33:47Z_
_Verifier: Claude (gsd-verifier)_
