# Phase 22: Address tech debt: measure garbage/junk rates end-to-end, reconcile Nyquist validation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-17
**Phase:** 22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco
**Mode:** `--auto` (autonomous — no interactive prompts; Claude selected the recommended option for every question, logged inline)
**Areas discussed:** Measurement unit & scope, reprocessing data source, dilution-risk scoping, export dedup-awareness finding, Nyquist reconciliation mechanism

---

## Measurement Unit — does the existing `quality-audit` tool already answer the milestone's criteria?

| Option | Description | Selected |
|--------|-------------|----------|
| Re-run existing `klake quality-audit` as-is and report its section-level rate as a proxy | No new code; fast | |
| Extend/supplement measurement to report chunk-level and export-row-level rates, matching the milestone's literal units | Reproduces the originally-audited units (4,499 chunks / 28%, 357 gold rows / 33%) exactly | ✓ |

**Claude's choice:** Extend/supplement (D-01). Investigation showed `run_quality_audit()` (Phase 17) is scoped strictly `parse→clean` and reports *section*-level garbage — a related but different unit from the milestone's stated "garbage chunks" (Phase 20's chunk substance gate) and "junk rows in gold export" (Phase 20's export gate). Neither of the latter two has ever been measured against real data.
**Notes:** Confirmed by reading `quality_audit.py`'s own docstring ("Scope is strictly parse -> clean") and cross-checking against `MILESTONE-CONTEXT.md`'s original baseline figures, which are explicitly chunk-count and gold-row-count based, not section-count based.

---

## Reprocessing Data Source

| Option | Description | Selected |
|--------|-------------|----------|
| Fresh crawl of the 34 sources | Re-fetches from the internet | |
| Reprocess from the existing immutable raw zone (`load_parsed_doc`/`reparse_from_raw`) | No new crawl; raw/parsed docs already exist for all 34 sources | ✓ |

**Claude's choice:** Reprocess from raw zone (D-02). `MILESTONE-CONTEXT.md` D-2 explicitly names this as the intended future path ("A deliberate reprocess from the (immutable, intact) raw zone remains possible later if desired"), and `quality_audit.py` already proves the pattern works.

---

## Dilution Risk — the central design constraint

| Option | Description | Selected |
|--------|-------------|----------|
| Naively re-run `export_rag_corpus(domain="healthcare")` and read its aggregate log | Simple, no new code | |
| Wipe the dev stack (`docker compose down -v`) for a fully clean measurement | Matches the eventual production step named in PROJECT.md | |
| Scope the measurement to only the freshly-reprocessed chunks, non-destructively (in-memory aggregation, mirroring `quality_audit.py`'s own approach) | No destructive action; isolates the real effect of the new gates | ✓ |

**Claude's choice:** Non-destructive scoping (D-04).
**Notes:** Live DB inspection during this discussion (`docker compose exec postgres psql ...`) found only 9 of 4,521 existing `chunk` artifacts carry the v2.6 `substance_passed` flag. Pre-v2.6 chunks default `substance_passed=True` (Phase 20 D-09, backward-compat), so a naive full-domain export would silently count ~4,512 old, ungated chunks as "passing," diluting/masking the new gate's real effect. A stack wipe was considered and rejected as out of scope for a measurement-only phase — it would destroy unrelated dev/test state (other domains, Qdrant test collections, the dedup ledger) — and is explicitly named elsewhere as the *production* cutover step, not something this phase should trigger. Concrete scoping mechanism left to the planner.

---

## Export Dedup-Awareness Finding (from the milestone audit)

| Option | Description | Selected |
|--------|-------------|----------|
| Write code to make `export_rag_corpus()` collapse duplicate-text rows via `chunk_dedup_ledger` | Closes the finding functionally | |
| Document only — formalize the current behavior as an accepted design boundary | Matches phase's named scope; avoids redefining EXPORT-01's row semantics | ✓ |

**Claude's choice:** Document only (D-07). The finding was explicitly informational/non-blocking in `.planning/v2.6-MILESTONE-AUDIT.md`, and fixing it is a non-trivial semantic change outside what "measure garbage/junk rates end-to-end, reconcile Nyquist validation" commits to.

---

## Nyquist Reconciliation Mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Encode Nyquist reconciliation as a coded task inside Phase 22's plan | Keeps everything in one plan | |
| Run `/gsd-validate-phase {17..21}` directly — a process action outside Phase 22's implementation plan | Matches what the command actually is (a standalone Nyquist audit + VALIDATION.md updater); needs no Phase 22 code | ✓ |

**Claude's choice:** Direct `/gsd-validate-phase` invocations (D-08). Confirmed via `$HOME/.claude/gsd-core/workflows/validate-phase.md` that this command is a self-contained audit/update tool, not something requiring Phase 22 source changes.

---

## Claude's Discretion

- Exact CLI/function shape for the chunk-level measurement (new flag vs. new command)
- Concrete non-destructive mechanism for scoping the export-junk-rate measurement (D-04)
- Report format, column names, and where results get written (new file / PROJECT.md / structured log only)
- Exact wording of the export docstring note (D-07)
- Sequencing of the 5 `/gsd-validate-phase` invocations relative to the measurement work
- Whether `/gsd-validate-phase` findings (if any real coverage gaps surface) get folded into Phase 22's plan or spun out separately

## Deferred Ideas

- Wiping the dev stack (`docker compose down -v`) for a fully clean production-like measurement — named elsewhere as the eventual production cutover step, not this phase's job.
- Retroactively cleaning/re-chunking the full pre-v2.6 corpus in place — still forward-only per milestone D-2.
- Making `export_rag_corpus()` dedup-aware — documented as an accepted boundary, not implemented.
- Any capability beyond measurement + Nyquist reconciliation (permanent CI gate on garbage rate, dashboarding).
