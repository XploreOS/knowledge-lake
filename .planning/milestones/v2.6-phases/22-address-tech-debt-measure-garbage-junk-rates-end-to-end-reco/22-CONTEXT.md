# Phase 22: Address tech debt: measure garbage/junk rates end-to-end, reconcile Nyquist validation - Context

**Gathered:** 2026-07-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Close the two open tech-debt items from the v2.6 milestone audit (`.planning/v2.6-MILESTONE-AUDIT.md`):

1. **Produce genuine, reproducible measurement** of the milestone's two quantitative success criteria — <5% garbage chunks, <2% junk rows in gold export — against real reprocessed data, since neither has ever actually been measured (confirmed by live DB inspection during this discussion — see `<code_context>`). The existing `klake quality-audit` (Phase 17, MEAS-01) measures a *different* unit (sections, post-clean) than the milestone's stated criteria (chunks, gold-export rows) — it must be extended or supplemented, not just re-run.
2. **Reconcile Nyquist validation status** for phases 17–21, all of which currently sit at NOT-VALIDATED (seeded pre-execution, never reconciled to `status: validated`).

**Requirements:** None new — this phase closes measurement/process gaps against already-shipped v2.6 requirements (MEAS-01, QUAL-03, EXPORT-01) rather than adding new capability.

**Explicitly NOT in this phase:** wiping the dev stack (`docker compose down -v`) for a "clean" measurement environment; retroactively cleaning/re-chunking the full pre-v2.6 corpus in place (still forward-only per milestone D-2); making `export_rag_corpus()` dedup-aware (a separate, informational-only finding from the milestone audit — see D-07 below); any new capability beyond measurement + Nyquist reconciliation.

</domain>

<decisions>
## Implementation Decisions

*Auto-mode: every decision below is the recommended default, selected without prompting. Review before planning — D-04 in particular changes how the measurement must be built, not just what it measures.*

### Measurement Scope & Approach (garbage/junk rate criteria)
- **D-01:** Measure the criteria in their literal, originally-audited units — chunk-level garbage rate (criterion #1) and gold-export-row junk rate (criterion #2) — not the section-level unit `klake quality-audit` already measures. The existing tool stays as-is (it's still useful for the clean-stage signal); extend it or add alongside it to also produce chunk-level and export-level numbers.
- **D-02:** Reprocess the existing 34 healthcare sources from the immutable raw zone — parse (reuse existing `parsed_document` children), fresh `clean()`, fresh `chunk()` — mirroring `quality_audit.py`'s established `load_parsed_doc()`/`reparse_from_raw()` pattern. No new crawl needed; sources and raw docs already exist.
- **D-03:** The measurement path stays `parse → clean → chunk (→ export for criterion #2)` — it never calls `dedup_chunks()`, `embed()`, or `index()`. This avoids embedding spend and Qdrant writes, consistent with Phase 17's D-07 "measurement-only, the pipeline IS the measurement" discipline. `export_rag_corpus()` does not require embed/index to have run — it reads directly from registry chunk artifacts.
- **D-04 (CRITICAL — dilution risk, the central design constraint of this phase):** Live DB inspection during this discussion confirmed only 9 of 4,521 existing `chunk` artifacts in the registry carry the v2.6 `substance_passed` flag — the other ~4,512 predate Phase 17–20 entirely. `export_rag_corpus()` (and any naive registry-wide aggregation) iterates over **all** of a domain's chunk artifacts, and pre-v2.6 chunks default `substance_passed=True` (Phase 20 D-09, backward-compat) — they would all silently "pass," diluting or masking the new gate's real effect if the measurement naively re-runs `export_rag_corpus(domain="healthcare")` and reads its aggregate log. **The measurement must be scoped to only the freshly-reprocessed chunks from this run, not the domain's full old+new chunk population.** Non-destructive scoping (e.g., summing counts in-memory as new chunks are produced — mirroring how `quality_audit.py` never queries the `cleaned_document` table and instead sums `clean()`'s return values directly — or filtering by the specific artifact IDs/timestamps this run creates) is preferred over wiping the dev stack or deleting old chunk artifacts. A full `docker compose down -v` wipe was considered — it's literally named in `PROJECT.md`/`MILESTONE-CONTEXT.md` as the eventual pre-production step — but is out of scope for a measurement-only phase and would destroy unrelated dev/test state (other domains, Qdrant test collections, the dedup ledger). Concrete scoping mechanism is left to the planner/researcher.
- **D-05:** Full 34/34 healthcare sources, not a subset — matches Phase 17's D-06 established `quality-audit` scope and gives a consistent before/after baseline.
- **D-06:** Report results against the two originally-audited baselines side by side: 28% garbage / 4,499 chunks (criterion #1) and 33% junk / 357 gold rows (criterion #2) — both from `MILESTONE-CONTEXT.md`.

### Export Dedup-Awareness Finding (informational item from the milestone audit)
- **D-07:** Document only — do not write code to make `export_rag_corpus()` dedup-aware (i.e., do not collapse cross-document duplicate text into a single exported row via `chunk_dedup_ledger`). This finding was explicitly informational/non-blocking in `.planning/v2.6-MILESTONE-AUDIT.md`, is architecturally non-trivial (would redefine EXPORT-01's row semantics), and sits outside what "measure garbage/junk rates end-to-end, reconcile Nyquist validation" commits to. Recommended action: add a short clarifying note to `export_rag_corpus()`'s docstring (and/or `PROJECT.md`) stating the export is chunk-artifact-scoped (citation-complete training data) by design, distinct from the vector index (deduplicated retrieval) — formalizing the finding as an accepted boundary rather than a defect.

### Nyquist Reconciliation (phases 17–21)
- **D-08:** Reconciliation happens via direct `/gsd-validate-phase {17..21}` command invocations — a process/tooling action outside Phase 22's own implementation plan, not a coded task. `/gsd-validate-phase` (dispatches `gsd-nyquist-auditor`) audits coverage gaps and updates each phase's `VALIDATION.md` directly; it needs no Phase 22 code changes to run and can happen before, during, or after Phase 22's plan execution.
- **D-09:** If `/gsd-validate-phase` surfaces genuine missing test coverage for phases 17–21 (as opposed to just a stale `status:`/`nyquist_compliant:` field needing reconciliation), Claude's discretion whether to fold those fixes into Phase 22's plan or handle them as a separate quick task — decide at that time based on what's actually found.

### Claude's Discretion

Claude has flexibility on: exact CLI/function shape for the chunk-level measurement (new flag on `klake quality-audit` vs. a new command); the concrete non-destructive mechanism for scoping the export-junk-rate measurement to only the reprocessed chunks (D-04); report format and column names; whether garbage/junk-rate results get written to a new report file, appended to `PROJECT.md`, or emitted as structured-log output only; exact wording of the export docstring note (D-07); and whether to run the 5 `/gsd-validate-phase` invocations before or after the measurement work.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Scope
- `.planning/v2.6-MILESTONE-AUDIT.md` — the audit report this phase directly closes; both named tech-debt items originate here
- `.planning/MILESTONE-CONTEXT.md` §D-2 (lines 103–109) — forward-only scope decision; explicitly names "a deliberate reprocess from the (immutable, intact) raw zone" as the intended future path this phase now executes
- `.planning/REQUIREMENTS.md` §Success Criteria (lines 192–199) — the two quantitative criteria in their original units (chunks, gold rows), plus MEAS-01/EXPORT-01's original acceptance text
- `.planning/PROJECT.md` line 177 (original baseline: 34 sources, 4,499 chunks, 28% garbage) and line 47 (forward-only via `docker compose down -v` for *production* — NOT invoked by this phase)

### Prior Phase Context
- `.planning/phases/17-close-the-bypass-measurement/17-CONTEXT.md` — D-06 (all 34 sources), D-07 (measurement-only, no embed/index), D-10 (frozen `garbage_rate = rejected/(rejected+kept)` formula) — the pattern this phase's chunk-level measurement must follow
- `.planning/phases/20-chunk-substance-gate-export-gate/20-CONTEXT.md` — D-08/D-09 (export gate + backward-compat default `True` for pre-v2.6 chunks) — the exact mechanism behind D-04's dilution risk

### Pipeline Code (measurement path)
- `src/knowledge_lake/pipeline/quality_audit.py` — `run_quality_audit()` — the section-level pattern to mirror: per-source loop, `load_parsed_doc()`/`reparse_from_raw()` reuse, try/except per-document error isolation, `rejection_reasons` summed dict, `garbage_rate = rejected/(rejected+kept) if total>0 else None`
- `src/knowledge_lake/pipeline/chunk.py` — `chunk()` (~line 263), `_assert_chunk_conservation_invariant()` (line 315) — already computes `kept_count`/`rejected_count`/`total_generated` per document; no new gate logic needed, only aggregation across the corpus
- `src/knowledge_lake/pipeline/export.py` — `export_rag_corpus()` (line 244) — reads **all** of a domain's chunk artifacts via `registry_repo.list_artifacts_by_type(session, "chunk")` (line 286), logs `kept`/`substance_filtered_out`/`total` (line 346) — this is both the exact number criterion #2 needs AND where the D-04 dilution risk lives
- `src/knowledge_lake/cli/app.py` — `cmd_quality_audit` (line 974) — existing CLI command pattern to extend or place a sibling command next to

### Process
- `$HOME/.claude/gsd-core/workflows/validate-phase.md` — what `/gsd-validate-phase` does (Nyquist gap audit + `VALIDATION.md` update); confirms it's a standalone command, not phase-implementation code

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `run_quality_audit()` (`quality_audit.py`) — exact pattern to mirror for chunk-level measurement: per-source loop, `load_parsed_doc`/`reparse_from_raw` reuse, per-document error isolation, summed rejection-reasons dict, the frozen `garbage_rate` formula.
- `chunk()`'s own conservation-invariant counts (`chunk.py:315-336`) — already computes `kept_count`/`rejected_count`/`total_generated` per document; the measurement just needs to aggregate what's already being computed, not add new gate logic.
- `export_rag_corpus()`'s existing `kept`/`substance_filtered_out`/`total` structured log (`export.py:346`) — already the exact numbers criterion #2 needs, *if* scoped correctly (see D-04).

### Live Environment State (checked during this discussion, 2026-07-17)
- Full docker-compose stack is up and healthy: postgres, minio, qdrant, dagster (daemon+webserver), litellm, api, searxng — a real end-to-end reprocess run is feasible right now.
- Registry currently holds: 387 `raw_document`, 282 `parsed_document`, 5 `cleaned_document`, 4,521 `chunk` artifacts total (across all domains); only **9** chunk artifacts carry `substance_passed` (i.e., have gone through the v2.6-gated `chunk()`); 12 rows in `chunk_dedup_ledger`. 34 sources have `domain='healthcare'`.
- This confirms the milestone's quantitative claims are genuinely unmeasured — the healthcare corpus has not been reprocessed through the v2.6 pipeline at scale, and the vast majority of existing chunk data predates the clean/chunk gates entirely.

### Established Patterns
- Settings hierarchy with `_env_file` override and `KLAKE_*` env var pattern (same as `ChunkQualitySettings`/`DedupSettings`)
- Structured logging via `structlog` with dotted stage-scoped event names
- Content-addressed artifact dedup — reprocessing produces **new** chunk artifacts (different content hash) rather than mutating old ones, forward-only by construction

### Landmines
- **Dilution risk (D-04)** — the single most important implementation constraint in this phase. A naive "just re-run `export_rag_corpus(domain='healthcare')` and read the log" will report a junk rate diluted by ~4,512 old, ungated chunks defaulting to `substance_passed=True`. Must be designed around.
- **`export_rag_corpus()` writes a real Parquet to the gold zone** (`gold/healthcare/rag_corpus/`) as a side effect of running it — not a dry-run function. Acceptable (matches its normal behavior) but the planner should know it's not side-effect-free.
- **Pre-v2.6 chunks lack `filter_config_version` in their content hash** — reprocessing via `chunk()` will produce chunk artifacts with new content hashes even for text that's substantively similar (WR-05 + PIPE-01 hash scoping), so this reprocess run necessarily **adds** chunk artifacts rather than replacing existing ones (forward-only, D-2, as designed) — the registry's chunk count will grow further.

</code_context>

<specifics>
## Specific Ideas

No user-supplied specifics — `--auto` mode, all decisions are Claude's recommended defaults grounded in live DB inspection and prior-phase precedent. D-04 (the dilution risk) is the one item most worth a human glance before planning — it changes *how* the measurement must be built, not just what it measures.

</specifics>

<deferred>
## Deferred Ideas

- **Wiping the dev stack (`docker compose down -v`)** for a fully "clean" production-like measurement — named in `PROJECT.md`/`MILESTONE-CONTEXT.md` as the eventual pre-production step, but destructive to unrelated dev/test state and out of scope for a measurement-only phase.
- **Retroactively cleaning/re-chunking the full pre-v2.6 corpus in place** — still forward-only per milestone D-2; not reconsidered here.
- **Making `export_rag_corpus()` dedup-aware** (collapsing duplicate-text rows via `chunk_dedup_ledger`) — documented as an accepted design boundary (D-07), not implemented.
- **Any new capability beyond measurement + Nyquist reconciliation** (e.g., a permanent CI gate on garbage rate, a dashboard) — out of this phase's named scope.

</deferred>

---

*Phase: 22-Address tech debt: measure garbage/junk rates end-to-end, reconcile Nyquist validation*
*Context gathered: 2026-07-17*
