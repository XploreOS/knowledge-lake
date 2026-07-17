---
phase: 22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco
plan: 03
subsystem: pipeline
tags: [quality-audit, measurement, chunk, export, real-data, milestone-validation]

requires:
  - phase: 22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco (Plan 22-01)
    provides: run_full_pipeline_audit() — chunk-level garbage rate + export-level junk rate measurement
  - phase: 22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco (Plan 22-02)
    provides: "--full flag on klake quality-audit CLI, dual table/JSON output"
provides:
  - "Real, reproducible chunk-level garbage rate (45.64%) and export-level junk rate (0.0%) for the 34-source healthcare corpus, captured against the live dev stack and reported side-by-side with the milestone's original 28%/33% baselines"
  - "Pitfall-2/Assumption-A1 convergence check result: export_junk_rate (0.0%) <= chunk_garbage_rate (45.64%) — holds, no anomaly"
  - "D-08/D-09 Nyquist reconciliation logged as an explicit operator follow-up (/gsd-validate-phase 17-21), not coded in this phase"
affects: [milestone-audit-reconciliation, v2.6-close-out]

tech-stack:
  added: []
  patterns: []

key-files:
  created:
    - .planning/phases/22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco/22-03-SUMMARY.md
  modified: []

key-decisions:
  - "Reported chunk_garbage_rate against the 28% baseline using D-10's frozen rejected/(rejected+kept) formula, but explicitly flagged that this measures THIS run's substance-gate rejection rate of candidate chunks (garbage caught before persistence), not garbage remaining in the delivered corpus — a different measurement basis than the original 28% baseline, which was a post-hoc classification of an already-delivered, ungated 4,499-chunk corpus. The literal successor metric to '% of what was shipped that is garbage' is export_junk_rate, which dropped from 33% to 0.0%."
  - "The first real run (PID 3581067) was accidentally killed by my own `timeout 590` shell wrapper (exit 124) after processing 24/34 sources — discarded and re-run with no artificial timeout per this session's explicit runtime_note authorization to let the command run to completion."
  - "documents_errored=6 (3 sources x 2 each: AHRQ Evidence-Based Reports, NIH ClinicalTrials.gov, Implementation Guides) is pre-existing per-document error isolation behavior inherited from run_quality_audit()'s established pattern (Phase 17), not a regression introduced by this measurement run."

patterns-established: []

requirements-completed: [MEAS-01, EXPORT-01]

coverage:
  - id: D1
    description: "A real klake quality-audit --domain healthcare --full --json run against the live 34-source healthcare corpus produced actual kept/rejected chunk counts and an export-junk count, reported against the 28%/33% baselines"
    requirement: "MEAS-01"
    verification:
      - kind: other
        ref: "uv run klake quality-audit --domain healthcare --full --json (live run, captured summary: chunks_considered=2397, chunk_garbage_rate=0.4564, export_kept=984, export_junk=0, export_junk_rate=0.0)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Pitfall 2 / Assumption A1 convergence check (export_junk_rate <= chunk_garbage_rate) explicitly verified, not silently assumed"
    requirement: "EXPORT-01"
    verification:
      - kind: other
        ref: "0.0 <= 0.45640383813099705 confirmed from the captured summary JSON — holds, no anomaly"
        status: pass
    human_judgment: false
  - id: D3
    description: "Nyquist reconciliation for phases 17-21 explicitly logged as an operator follow-up (/gsd-validate-phase), not implemented as phase-22 code"
    verification:
      - kind: other
        ref: "Operational Follow-up section below names the exact 5 commands the operator must run"
        status: pass
    human_judgment: false

duration: 73min
completed: 2026-07-17
status: complete
---

# Phase 22 Plan 03: Real measurement run against the live 34-source healthcare corpus Summary

**Ran `klake quality-audit --domain healthcare --full --json` against the live dev stack's real 34 healthcare sources: chunk-level `chunk_garbage_rate` came out at 45.64% (vs. 28% baseline) while export-level `export_junk_rate` came out at 0.0% (vs. 33% baseline) — the Pitfall-2/A1 convergence check holds (0.0% <= 45.64%), and the gold RAG corpus's actual junk content is now measured at zero.**

## Performance

- **Duration:** 73 min (dominated by two real ~13-20 min end-to-end reprocessing runs across 34 sources with real Docling parsing, real S3/MinIO I/O, and real Postgres writes — not idle/blocked time)
- **Started:** 2026-07-17T18:27:04Z
- **Completed:** 2026-07-17T19:40:22Z
- **Tasks:** 1
- **Files modified:** 0 (measurement-only; this plan's frontmatter declares `files_modified: []`)

## Accomplishments

- Executed a real, full-corpus `uv run klake quality-audit --domain healthcare --full --json` run against the live docker-compose stack (postgres, minio confirmed healthy) — no `--limit`, full 34/34 healthcare sources per D-05, reprocessing `parse → clean → chunk → export_rag_corpus`
- Also captured the human-readable table-mode invocation (`uv run klake quality-audit --domain healthcare --full`, no `--json`) — its printed per-source table and corpus-wide summary block match the JSON run's numbers exactly (`chunk_garbage_rate: 45.6% (baseline: 28.0%)`, `export_junk_rate: 0.0% (baseline: 33.0%)`)
- Computed and recorded the before/after comparison for both of the milestone's originally-audited quantitative criteria (see **Real Measurement Results** below)
- Explicitly verified the Pitfall-2/Assumption-A1 expectation (`export_junk_rate <= chunk_garbage_rate`) — it holds (0.0% <= 45.64%), so no anomaly investigation was required
- Flagged and explained (rather than silently reported) an important interpretive nuance: `chunk_garbage_rate`'s rise relative to the 28% baseline is *not* a regression — see **Interpretive Note** below
- `pytest -x` (full existing suite) passes: **1185 passed, 3 skipped, 6 xfailed, 0 failed** — no regressions from this measurement-only run
- Logged D-08/D-09 Nyquist reconciliation for phases 17-21 as an explicit operator follow-up, not phase-22 code (see **Operational Follow-up** below)

## Real Measurement Results

Captured from the live run's `summary` object (34/34 healthcare sources, full pipeline reprocess):

```json
{
  "domain": "healthcare",
  "sources_count": 34,
  "documents_errored": 6,
  "sections_considered": 3567,
  "sections_kept": 2129,
  "sections_rejected": 1438,
  "sections_garbage_rate": 0.4031398934679002,
  "chunks_considered": 2397,
  "chunks_kept": 1303,
  "chunks_rejected": 1094,
  "chunk_rejection_reasons": {
    "line_punct_ratio": 724,
    "char_dup_ratio": 97,
    "short_line_ratio": 258,
    "below_stopword_ratio:0.03<0.05": 2,
    "below_terminal_punct_ratio:0.02<0.02": 6,
    "below_stopword_ratio:0.05<0.05": 5,
    "list_ratio": 1,
    "below_stopword_ratio:0.00<0.05": 1
  },
  "chunk_garbage_rate": 0.45640383813099705,
  "export_kept": 984,
  "export_junk": 0,
  "export_junk_rate": 0.0,
  "baseline_chunk_garbage_rate": 0.28,
  "baseline_export_junk_rate": 0.33
}
```

Human-readable table-mode invocation's summary block (verbatim, matches the JSON exactly):

```
Corpus-wide summary for domain 'healthcare':
  chunk_garbage_rate: 45.6% (baseline: 28.0%)
  export_junk_rate:   0.0% (baseline: 33.0%)
```

### Before/After Comparison Against Milestone Success Criteria

| Criterion | Baseline | This run | Absolute delta | Relative delta | Target | Met? |
|---|---|---|---|---|---|---|
| #1 chunk_garbage_rate (D-10 formula: `rejected/(rejected+kept)`) | 28.0% (4,499 chunks, post-hoc classified) | 45.64% (2,397 candidate chunks this run) | +17.64pp | +63.0% | <5% | **NOT MET** (literal reading — see Interpretive Note) |
| #2 export_junk_rate (D-04-scoped, this run's own chunks only) | 33.0% (357 gold rows, post-hoc classified) | 0.0% (984 gold rows this run) | -33.0pp | -100.0% | <2% | **MET** |

### Pitfall 2 / Assumption A1 Convergence Check

RESEARCH.md's Pitfall 2 / Assumption A1 predicted `export_junk_rate <= chunk_garbage_rate` once both are correctly D-04-scoped, because enforce-mode `chunk()` never persists rejected chunks. **Confirmed: 0.0% <= 45.64% — holds.** No anomaly requiring investigation (e.g., no `chunk.storage_uri` read-failure fallback-to-empty-text symptom observed).

### Interpretive Note (flagged explicitly, not silently reported)

The `chunk_garbage_rate` number (45.64%, up from the 28% baseline) reads, on its face, as if garbage got *worse*. It did not — the two numbers are measuring different things:

- **The original 28% baseline** was a post-hoc, one-time heuristic classification of the 4,499 chunks that were *already persisted* into the corpus before any substance gate existed (Phase 17-20 hadn't shipped yet). It answers: "of what was shipped, how much is garbage?"
- **This run's `chunk_garbage_rate`** uses the D-10 frozen formula `rejected/(rejected+kept)` computed *live*, during generation, by `chunk()`'s enforce-mode substance gate. It answers a different question: "of what the pipeline generated as candidates, how much did the gate catch and discard *before* it was ever persisted?"

Because enforce-mode `chunk()` never persists rejected chunks, the metric that is the direct successor to the original "% of what was shipped that is garbage" question is **`export_junk_rate`**, not `chunk_garbage_rate` — and that metric fell from 33% to **0.0%**, decisively beating the milestone's <2% target. A `chunk_garbage_rate` of 45.64% is evidence the gate is working *aggressively* (catching nearly half of all raw candidate chunks before they ever reach storage), which is exactly *why* the delivered corpus (`export_junk_rate`) is now clean. Read literally against REQUIREMENTS.md's "<5% garbage chunks" wording, criterion #1 is **not met** by this run's own definition of chunk_garbage_rate; read as "how much garbage reaches the corpus," the milestone's actual quality goal is met with room to spare. This split verdict is surfaced explicitly here per this plan's own must-have truth ("If chunk_garbage_rate and export_junk_rate do not converge as expected... the anomaly is explicitly flagged and investigated, not silently reported") — the numbers do converge in the expected *direction* (Pitfall 2/A1 holds), but the absolute chunk_garbage_rate figure needs this context to be read correctly rather than taken as a raw before/after regression.

### Worst / Best Sources (chunk-level, this run)

Worst (highest `chunk_garbage_rate`, small-sample sources at 100% are single-digit chunk counts):
- `Home - US Core Implementation Guide v9.0.0 - FHIR`: 79.0% (542 chunks considered — largest source in the corpus)
- `Implementation Guides`: 75.0% (20 chunks)
- `RxNorm via NLM RxNav`: 68.0% (25 chunks)
- Several near-empty sources (`HL7 FHIR R4 Specification`, `CDC MMWR`, `CDC WONDER`, `MedlinePlus Health Information`) show 100% on 2-3 chunk samples — statistically noisy, not representative.

Best:
- `AHA Clinical Guidelines`: 15.8% (38 chunks)
- `FHIR® Implementation Guide: How to Implement FHIR® in 2026 - Kodjin`: 18.9% (684 chunks — second-largest source)
- `HIPAA Security Rule`: 22.2%, `HIPAA Privacy Rule`: 25.0%

9 sources produced zero chunks this run (`chunk_garbage_rate: N/A`) — includes `CMS Conditions of Participation`, `HCPCS Level II Code System`, `AHRQ Evidence-Based Reports`, `PubMed Central Open Access`, and 5 others — these sources' parsed documents yielded no sections that survived to the chunking stage in this reprocess.

`documents_errored: 6` (3 sources x 2 documents each: `AHRQ Evidence-Based Reports`, `NIH ClinicalTrials.gov`, `Implementation Guides`) — per-document error isolation caught and skipped these without aborting the corpus-wide run, matching `run_quality_audit()`'s established Phase 17 pattern; not investigated further as out of this plan's scope (pre-existing behavior, not introduced here).

## Task Commits

Task 1 (`Run the real measurement against the live 34-source healthcare corpus and record results`) declares `files_modified: []` in this plan's frontmatter — it performs a live measurement run and produces no source-code changes. Its sole artifact is this `22-03-SUMMARY.md`, committed as:

1. **Task 1: Run the real measurement and record results** - captured in the `docs(22-03)` commit immediately following this file's creation (see `git log --oneline -1 -- .planning/phases/22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco/22-03-SUMMARY.md`)

**Plan metadata:** captured in the final `docs(22-03): complete` commit alongside STATE.md/ROADMAP.md/REQUIREMENTS.md updates.

## Files Created/Modified

- `.planning/phases/22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco/22-03-SUMMARY.md` - this file (the plan's sole artifact — narrative + captured JSON of the real measurement run)

No source code files were created or modified — this plan is measurement-only per its `files_modified: []` frontmatter declaration and threat model (T-22-09: real `export_rag_corpus()` write is expected/accepted behavior of the existing, unmodified function, not new code).

## Decisions Made

- Reported `chunk_garbage_rate` against the 28% baseline as instructed by D-06, but added the **Interpretive Note** above rather than letting the raw before/after delta (+17.64pp) stand unexplained — the two numbers use different measurement bases (post-hoc classification of an ungated legacy corpus vs. live gate-rejection-rate of fresh candidates), and presenting the delta without this context would misrepresent the milestone's actual outcome (which is a clear win on the metric that matters for corpus quality, `export_junk_rate`).
- Re-ran the full measurement from scratch after the first attempt was killed by my own `timeout 590` wrapper (exit 124, 24/34 sources processed) — discarded that partial run entirely rather than trying to splice/extend it, and re-ran with no artificial timeout per this session's explicit `runtime_note` authorization.
- Also captured the non-`--json` table-mode invocation as a second, independent confirmation of the same numbers (per the plan's action text), rather than relying solely on the JSON capture.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] First measurement attempt killed by an executor-introduced `timeout 590` wrapper, not a genuine hang**
- **Found during:** Task 1, first invocation attempt
- **Issue:** I wrapped the real `uv run klake quality-audit --domain healthcare --full --json` command in a shell `timeout 590` (~10 min) as a safety net, despite this session's explicit `runtime_note` stating the command may legitimately take several minutes and should not be treated as a hang. The command was still actively processing (24/34 sources done, real S3/MinIO I/O ongoing, 90%+ CPU) when `timeout` killed it at 590s (exit 124).
- **Fix:** Discarded the killed run's partial output entirely. Re-ran the identical command via `nohup ... &` with no artificial timeout, and monitored it to natural completion (all 34/34 sources processed, ~63 min total for this second attempt due to real Docling parsing on cache misses plus unrelated host CPU contention from other docker workloads on the shared machine).
- **Files modified:** None (measurement-only; no source files touched by either attempt).
- **Verification:** Second run's captured `summary.sources_count == 34` (full corpus) and `documents_errored` breakdown accounted for; table-mode run's independently-captured summary block matches the JSON run's numbers exactly, confirming reproducibility.
- **Committed in:** N/A (no code change — self-correction during task execution, not a code commit).

---

**Total deviations:** 1 auto-fixed (1 blocking — an executor-side tooling mistake, not a bug in the plan or the shipped code)
**Impact on plan:** No impact on the plan's scope, design, or deliverable. The re-run produced the genuine, complete, reproducible measurement the plan requires; the first attempt's partial data was never used for any reported number.

## Issues Encountered

- Shared-host CPU contention (unrelated `exf-patient-identity-*` docker workloads on the same machine, load average ~3) made the second full run noticeably slower per-source than the first attempt's early progress — not a bug, just real infrastructure contention. Both live-service dependencies (postgres, minio) remained healthy throughout per `docker compose ps` / `docker stats` checks taken mid-run.
- No other issues. `pytest -x` full suite green with zero regressions (1185 passed, unchanged from the 22-02 baseline — expected, since this plan touches no source code).

## User Setup Required

None - no external service configuration required. The live dev stack (postgres, minio) was already up and healthy at task start.

## Next Phase Readiness

- The milestone's two quantitative success criteria are now genuinely measured for the first time (closing tech-debt item #1 from `.planning/v2.6-MILESTONE-AUDIT.md`): `export_junk_rate` (the corpus-quality metric that matters) is 0.0%, decisively beating the <2% target and improved from the 33% baseline. `chunk_garbage_rate` (the gate's own candidate-rejection rate) is 45.64% — read correctly per the Interpretive Note above, this reflects the gate working as designed, not a regression, but the raw number does not satisfy REQUIREMENTS.md's literal "<5% garbage chunks" wording if that wording is read as this specific metric. An operator/product decision may be warranted on whether REQUIREMENTS.md's criterion #1 wording should be revised to reference `export_junk_rate` (the metric that is actually representative of "garbage reaching the corpus" post-gate) rather than `chunk_garbage_rate` (which is structurally expected to be nonzero and even high under a working gate).
- **Nyquist reconciliation (D-08/D-09) is an explicit operator follow-up, not phase-22 code** — see below.
- Every source's chunk artifacts from this run are new content-addressed artifacts (forward-only, D-2) — the registry's chunk count grew further; no destructive `docker compose down -v` was run (out of scope, confirmed not needed).

## Operational Follow-up

**D-08/D-09 — Nyquist reconciliation is NOT part of this phase's coded work.** The operator should now run:

```
/gsd-validate-phase 17
/gsd-validate-phase 18
/gsd-validate-phase 19
/gsd-validate-phase 20
/gsd-validate-phase 21
```

to reconcile each phase's `VALIDATION.md` `status`/`nyquist_compliant` fields from their pre-execution seed state to their true post-execution state (per `.planning/v2.6-MILESTONE-AUDIT.md`'s Nyquist Coverage finding). Per D-09, if any of these five invocations surfaces genuine missing test coverage (as opposed to a merely stale `status:` field), the decision to fold the fix into a new quick task or a phase-22 follow-up plan is deliberately deferred to that moment.

---
*Phase: 22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco*
*Completed: 2026-07-17*
