# Phase 22: Address tech debt: measure garbage/junk rates end-to-end, reconcile Nyquist validation - Research

**Researched:** 2026-07-17
**Domain:** Internal pipeline measurement/reporting (no new external technology) — Python/SQLAlchemy/Polars/DuckDB codebase archaeology
**Confidence:** HIGH (all findings grounded in direct reads of the actual source files this phase touches; zero new external libraries)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Measure the criteria in their literal, originally-audited units — chunk-level garbage rate
  (criterion #1) and gold-export-row junk rate (criterion #2) — not the section-level unit `klake quality-audit`
  already measures. The existing tool stays as-is (it's still useful for the clean-stage signal); extend it or
  add alongside it to also produce chunk-level and export-level numbers.
- **D-02:** Reprocess the existing 34 healthcare sources from the immutable raw zone — parse (reuse existing
  `parsed_document` children), fresh `clean()`, fresh `chunk()` — mirroring `quality_audit.py`'s established
  `load_parsed_doc()`/`reparse_from_raw()` pattern. No new crawl needed; sources and raw docs already exist.
- **D-03:** The measurement path stays `parse → clean → chunk (→ export for criterion #2)` — it never calls
  `dedup_chunks()`, `embed()`, or `index()`. This avoids embedding spend and Qdrant writes, consistent with
  Phase 17's D-07 "measurement-only, the pipeline IS the measurement" discipline. `export_rag_corpus()` does not
  require embed/index to have run — it reads directly from registry chunk artifacts.
- **D-04 (CRITICAL — dilution risk, the central design constraint of this phase):** Only 9 of 4,521 existing
  `chunk` artifacts carry the v2.6 `substance_passed` flag; the other ~4,512 predate Phase 17–20 entirely.
  `export_rag_corpus()` (and any naive registry-wide aggregation) iterates over **all** of a domain's chunk
  artifacts, and pre-v2.6 chunks default `substance_passed=True` (Phase 20 D-09, backward-compat) — they would
  all silently "pass," diluting or masking the new gate's real effect if the measurement naively re-runs
  `export_rag_corpus(domain="healthcare")` and reads its aggregate log. **The measurement must be scoped to only
  the freshly-reprocessed chunks from this run, not the domain's full old+new chunk population.** Non-destructive
  scoping is preferred over wiping the dev stack or deleting old chunk artifacts. Concrete scoping mechanism was
  left to the planner/researcher — resolved in this document (see Pattern 1, Pattern 2, Pattern 3 above).
- **D-05:** Full 34/34 healthcare sources, not a subset — matches Phase 17's D-06 established `quality-audit`
  scope and gives a consistent before/after baseline.
- **D-06:** Report results against the two originally-audited baselines side by side: 28% garbage / 4,499 chunks
  (criterion #1) and 33% junk / 357 gold rows (criterion #2) — both from `MILESTONE-CONTEXT.md`.
- **D-07:** Document only — do not write code to make `export_rag_corpus()` dedup-aware. Add a short clarifying
  note to `export_rag_corpus()`'s docstring (and/or `PROJECT.md`) stating the export is chunk-artifact-scoped
  (citation-complete training data) by design, distinct from the vector index (deduplicated retrieval).
- **D-08:** Nyquist reconciliation happens via direct `/gsd-validate-phase {17..21}` command invocations — a
  process/tooling action outside Phase 22's own implementation plan, not a coded task.
- **D-09:** If `/gsd-validate-phase` surfaces genuine missing test coverage for phases 17–21, Claude's discretion
  whether to fold those fixes into Phase 22's plan or handle them as a separate quick task.

### Claude's Discretion

Exact CLI/function shape for the chunk-level measurement (new flag on `klake quality-audit` vs. a new command);
the concrete non-destructive mechanism for scoping the export-junk-rate measurement to only the reprocessed
chunks (D-04); report format and column names; whether garbage/junk-rate results get written to a new report
file, appended to `PROJECT.md`, or emitted as structured-log output only; exact wording of the export docstring
note (D-07); and whether to run the 5 `/gsd-validate-phase` invocations before or after the measurement work.

### Deferred Ideas (OUT OF SCOPE)

- Wiping the dev stack (`docker compose down -v`) for a fully "clean" production-like measurement.
- Retroactively cleaning/re-chunking the full pre-v2.6 corpus in place — still forward-only per milestone D-2.
- Making `export_rag_corpus()` dedup-aware (collapsing duplicate-text rows via `chunk_dedup_ledger`) —
  documented as an accepted design boundary (D-07), not implemented.
- Any new capability beyond measurement + Nyquist reconciliation (e.g., a permanent CI gate on garbage rate, a
  dashboard).
</user_constraints>

## Summary

This phase writes no new integration, installs no new package, and touches no unexplored technology — it is a
measurement-and-reporting extension of code that already exists and already ships the exact numbers needed
(`clean()`'s section counts, `chunk()`'s conservation-invariant counts, `export_rag_corpus()`'s
`kept`/`substance_filtered_out`/`total` log). The entire research task was reading four files closely enough to
answer one question precisely: **how do you get a scoped, non-destructive, in-memory measurement out of code that
was written to operate registry-wide?**

The answer, confirmed by direct code reading: `pipeline/chunk.py`'s `_apply_substance_gate()` **mutates its
`raw_chunks` list argument in place** before deciding what to return — so a caller that builds `raw_chunks` itself
(via the already-public `_build_token_chunks()`) and calls `_apply_substance_gate()` against it gets the full
per-chunk `substance_passed`/`rejection_reason` annotation on every item, kept and rejected alike, regardless of
`gate_mode`. This lets the new measurement code compute exact kept/rejected/reason counts **without querying the
registry at all** — the same "sum the pure function's own output" discipline `quality_audit.py` already uses for
`clean()`. No changes to `pipeline/chunk.py` or `pipeline/export.py` are required for the counting logic itself.

For the export-side scoping problem (D-04), the critical structural fact this research uncovered is that
**`chunk()`'s `enforce`-mode gate (the shipped default) never persists a rejected chunk as an artifact in the first
place** — `_apply_substance_gate()` filters `raw_chunks` down to the passing subset *before* the persistence loop
runs. That means every chunk artifact this phase's reprocess run creates will, by construction, already carry
`substance_passed=True`. Scoping the export measurement to just this run's own chunk IDs (tracked in memory as
`chunk()` returns them) and checking each one's `metadata_.substance_passed` via a handful of bounded
`get_artifact()` lookups — never `list_artifacts_by_type(session, "chunk")` — sidesteps the whole dilution problem
without any new repo function or SQL filter. Calling the real `export_rag_corpus(domain="healthcare")` (as D-03
explicitly permits) and then filtering its output Parquet by this run's chunk-ID set is the recommended way to
prove the exported artifact itself (not just a simulated check) reflects the measurement.

**Primary recommendation:** Add a new function alongside `run_quality_audit()` in `pipeline/quality_audit.py` (or a
sibling module) that re-runs `clean() → chunk()` per document with `domain_filters` resolved via `DomainLoader` (a
gap the *existing* `run_quality_audit()` has — see Pitfall 1), tallies chunk-level kept/rejected/reasons using the
`_build_token_chunks()` + `_apply_substance_gate()` in-memory pattern, tracks the real persisted chunk IDs from a
normal `chunk()` call, then calls the real `export_rag_corpus(domain="healthcare")` once and cross-references its
output Parquet against that ID set for the export-junk number. Expose it via a new CLI command (sibling to
`quality-audit`) or a new flag on the existing one. No `chunk.py`/`export.py` source changes are required.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Chunk-level garbage-rate measurement (criterion #1) | Pipeline/Batch measurement (`pipeline/quality_audit.py`) | — | Mirrors MEAS-01's existing section-level harness; pure re-run of `clean()`→`chunk()`, no new layer |
| Export-junk-rate measurement (criterion #2) | Pipeline/Batch measurement | Export stage (`pipeline/export.py`, read-only reuse) | Measurement code calls the real `export_rag_corpus()` and post-filters its output; no new export logic |
| Non-destructive run-scoping (D-04) | Pipeline/Batch measurement (in-memory ID tracking) | Registry (bounded `get_artifact()` lookups) | Avoids registry-wide scans entirely — matches `quality_audit.py`'s existing "sum pure-function output" discipline |
| CLI surface for the new measurement | CLI (`cli/app.py`) | — | Sibling command pattern already established by `cmd_quality_audit` |
| Before/after report presentation | Documentation/reporting (phase artifact, not source code) | — | No runtime "dashboard" tier exists in this project; reporting is a file, not a service |
| Nyquist reconciliation (17–21) | Process/tooling (`/gsd-validate-phase`) | — | Explicitly NOT source code per D-08 — outside this map |

## Package Legitimacy Audit

**Not applicable.** This phase introduces zero new external packages. It extends existing, already-installed
modules (`pipeline/quality_audit.py`, `pipeline/chunk.py` — read-only reuse of its already-public helpers,
`pipeline/export.py` — read-only reuse via its real public function, `cli/app.py`). No `pip install`/`uv add`
step belongs in this phase's plan.

## Architecture Patterns

### System Architecture Diagram

```
                     Source.domain == "healthcare"  (34 sources, unchanged)
                                   │
                                   ▼
                    ┌───────────────────────────────┐
                    │   NEW measurement function      │   (pipeline/quality_audit.py,
                    │   run_full_pipeline_audit()      │    sibling to run_quality_audit())
                    └───────────────────────────────┘
                                   │  per raw_document (load_parsed_doc / reparse_from_raw
                                   │  — identical reuse pattern to run_quality_audit())
                                   ▼
                    clean(parsed_id, source_id, parsed_doc, domain_filters=domain_filters)
                                   │  clean_result["cleaned_doc"]           ◄─ MUST pass domain_filters
                                   │  clean_result["sections_*"]  (existing MEAS-01 numbers, unchanged)
                                   ▼
        ┌──────────────────────────┴───────────────────────────┐
        │                                                       │
        ▼ (in-memory, PURE — no registry writes)                ▼ (real, PERSISTED — chunk artifacts)
_build_token_chunks(cleaned_doc, ...)                    chunk(parsed_id, source_id, cleaned_doc,
        │                                                        domain_filters=domain_filters)
        ▼                                                       │
_apply_substance_gate(raw_chunks, s, domain_filters, ...)       │  results = KEPT chunks only
   mutates raw_chunks IN PLACE with                              │  (enforce mode default —
   substance_passed / rejection_reason                           │   rejected chunks never
   on every entry, kept AND rejected                              │   become artifacts, see
        │                                                         │   Key Finding below)
        ▼                                                         ▼
  tally kept / rejected / rejection_reasons            track this run's own chunk_ids
  → CRITERION #1 (chunk garbage_rate)                  (in-memory set, no query yet)
                                                                    │
                                                                    ▼
                                                  export_rag_corpus(domain="healthcare")
                                                  (real call — writes real gold Parquet,
                                                   D-03 explicitly permits this)
                                                                    │
                                                                    ▼
                                          read back Parquet (StorageBackend.get_object() +
                                          polars.read_parquet(io.BytesIO(...)))
                                          filter rows to THIS RUN's chunk_id set only
                                          → CRITERION #2 (export junk_rate, D-04-safe)
                                                                    │
                                                                    ▼
                                          before/after report (28%→X%, 33%→Y%)
                                          — file format is Claude's discretion (see below)
```

### Recommended Project Structure

No new files strictly required — extend in place:

```
src/knowledge_lake/
├── pipeline/
│   └── quality_audit.py     # ADD: run_full_pipeline_audit() (or similarly named), reusing
│                             #      clean()/chunk()/export_rag_corpus() — no new module needed;
│                             #      keeps MEAS-01's "one measurement module" precedent intact
├── cli/
│   └── app.py                # ADD: new command (e.g. `quality-audit --full` flag, or a
│                              #      sibling `quality-audit-chunks` command) next to
│                              #      cmd_quality_audit (line 974)
tests/unit/
├── test_quality_audit.py     # EXTEND: new test class/functions for the chunk+export tally
└── test_cli_quality_audit.py # EXTEND: CLI surface test for the new flag/command
```

### Pattern 1: In-memory gate mutation reuse (the D-04 solution)

**What:** `_apply_substance_gate(raw_chunks, s, domain_filters, parsed_artifact_id)` in `pipeline/chunk.py`
(line 340) mutates every dict in its `raw_chunks` argument in place (`raw["substance_passed"] = result.passed`,
line 395) **before** deciding what subset to return. The function's *return value* is mode-dependent (filtered
subset in `enforce` mode, full list in `report` mode) — but the *input list object* always ends up fully
annotated regardless of mode, because Python mutates dicts by reference.

**When to use:** Any time you need per-item kept/rejected/reason detail from the gate without changing
`gate_mode` to `"report"` (which would also change production chunk-persistence behavior if `settings` were
shared) and without a second gate implementation.

**Example:**
```python
# Source: src/knowledge_lake/pipeline/chunk.py (existing code, imported not modified)
from knowledge_lake.pipeline.chunk import _build_token_chunks, _apply_substance_gate

raw_chunks = _build_token_chunks(
    cleaned_doc, s.chunk.max_tokens, s.chunk.overlap_tokens, s.chunk.heading_breadcrumb_depth,
)
_apply_substance_gate(raw_chunks, s, domain_filters, parsed_id)  # mutates raw_chunks in place
total_generated = len(raw_chunks)
kept = sum(1 for r in raw_chunks if r["substance_passed"])
rejected = total_generated - kept
reasons: dict[str, int] = {}
for r in raw_chunks:
    if not r["substance_passed"]:
        reasons[r["rejection_reason"]] = reasons.get(r["rejection_reason"], 0) + 1
```

This is a **private-by-underscore but already-imported-elsewhere** module contract — `_build_token_chunks` and
`_apply_substance_gate` are pure functions with no I/O (verified: no `get_session()`/`StorageBackend` calls in
either), so importing them from a sibling pipeline module is a lateral reuse, not a layering violation. It mirrors
`export.py`'s own internal reuse of `_enforce_no_contamination()` as a private helper called from three different
public export functions.

### Pattern 2: Bounded ID lookup instead of registry-wide scan (D-04, criterion #2)

**What:** `registry_repo.get_artifact(session, artifact_id)` (repo.py line 380) is a single-row lookup. There is
no existing `get_artifacts_by_ids()` batch helper — but the measurement's own chunk-ID set from this run is
bounded (order of hundreds, not the domain's full 4,521), so a `for chunk_id in this_run_ids: get_artifact(...)`
loop (or read the resulting Parquet and filter client-side, see Pattern 3) is a legitimate "scoped" query, not the
"registry-wide" pattern D-04 warns against. **Do not add `WHERE id IN (...)` to `list_artifacts_by_type()`** —
that changes a shared function's contract for one caller's need; a local loop or Parquet post-filter is simpler
and touches zero shared code.

**When to use:** Whenever the measurement needs the *persisted* state of only its own newly created artifacts.

### Pattern 3: Read-back-and-filter instead of re-deriving export logic (D-04, research question 3)

**What:** `export_rag_corpus()`'s row-level filter is exactly one line: `if not meta.get("substance_passed",
True): substance_filtered_out += 1; continue` (export.py line 309). It is trivial enough that duplicating it as a
standalone pure predicate is *possible* but unnecessary — the safer, more end-to-end-faithful approach is to call
the **real** `export_rag_corpus(domain="healthcare")` (D-03 explicitly lists export as in scope for criterion #2),
let it write its normal domain-wide gold Parquet, then read that Parquet back and filter to just this run's
`chunk_id` set (the exported DataFrame's first column, per `_RAG_CORPUS_FIELDS`, line 65). This proves the actual
shipped export path — not a reimplementation of its filter — behaves correctly on freshly gated data, while still
avoiding the D-04 dilution because the *count you report* is scoped, even though the *file written* is
domain-wide (matching existing/expected export behavior, not a new mode).

**Example:**
```python
# Source: mirrors StorageBackend usage in pipeline/export.py (io.BytesIO pattern, line 371)
import io
import polars as pl
from knowledge_lake.pipeline.utils import uri_to_key

export_result = export_rag_corpus(domain="healthcare", settings=s)
storage = StorageBackend(s.storage)
buf = io.BytesIO(storage.get_object(uri_to_key(export_result["storage_uri"])))
df = pl.read_parquet(buf)
exported_from_this_run = df.filter(pl.col("chunk_id").is_in(list(this_run_chunk_ids))).height
junk_from_this_run = total_generated_this_run - exported_from_this_run
```
This avoids DuckDB/S3-httpfs entirely (unlike `verify_export()`, which is DuckDB-based and is a *separate*,
pre-existing verification path this measurement doesn't need to duplicate) — `StorageBackend.get_object()` +
`polars.read_parquet(io.BytesIO(...))` is simpler and reuses code already imported throughout the pipeline
modules.

### Anti-Patterns to Avoid

- **Calling `list_artifacts_by_type(session, "chunk")` and filtering client-side for "recent" chunks by
  timestamp.** Tempting (it avoids ID tracking) but re-introduces the exact registry-wide scan D-04 forbids, and
  "recent" is not a reliable proxy — content-hash no-op branches (line 509 in chunk.py) mean a re-run of an
  *already-processed* document reuses the existing artifact's `created_at`, silently excluding it from a
  timestamp-window filter even though it's legitimately part of "this run."
- **Setting `gate_mode="report"` globally for the measurement run.** This changes what gets *persisted* (report
  mode persists ALL chunks including rejected ones, per `_apply_substance_gate`'s enforce/report branch at line
  423) — it would make this run's registry data diverge from what a real production `enforce`-mode run would
  produce, undermining the "the pipeline IS the measurement" (Phase 17 D-07) principle this phase must preserve.
  Use the in-memory `_build_token_chunks` + `_apply_substance_gate` pattern (Pattern 1) to get report-mode-style
  full annotation WITHOUT changing what the real `chunk()` call persists.
- **Reimplementing `export_rag_corpus()`'s substance filter as a new standalone function in the measurement
  module.** Two independent implementations of the same one-line check will drift. Prefer Pattern 3 (call the
  real function, filter its real output).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Chunk-level kept/rejected/reason tallying | A new gate re-implementation or regex reuse | `_build_token_chunks()` + `_apply_substance_gate()` (already-public, pure, imported) | Single source of truth for what "garbage" means (QUAL-05 conservation invariant already enforced inside `_apply_substance_gate`) |
| Export-scoped junk counting | A new SQL `WHERE id IN (...)` filter on `export_rag_corpus()` | Real `export_rag_corpus()` call + client-side Parquet filter by chunk_id | Proves the shipped export path, not a parallel implementation; zero export.py changes |
| Domain-filter resolution | Hardcoding healthcare's `filters.yaml` path | `DomainLoader.from_name(settings.domain.domain_name).filters` (process.py line 112–113 precedent) | Exact existing wiring pattern; also fixes the missing-domain_filters gap in `run_quality_audit()`'s current `clean()` call (Pitfall 1) |
| Report table generation | A new report-formatting library | Plain Python string formatting matching `cmd_quality_audit`'s existing table layout (cli/app.py line 1003–1016), or the `v2.6-MILESTONE-AUDIT.md` "before/after criteria" table style | No new dependency; matches an established in-repo precedent for exactly this kind of table |

**Key insight:** Every piece this phase needs to measure already exists and already computes the right numbers
internally (`clean()`'s section counts, `chunk()`'s conservation-invariant counts, `export_rag_corpus()`'s
kept/filtered counts) — the entire engineering task is *plumbing*, not new logic. The temptation to write a new
gate, a new filter, or a new SQL query is exactly the temptation D-04 already warned against ("naive re-run...
diluting or masking the new gate's real effect").

## Runtime State Inventory

*(Included because this phase creates new registry rows via a reprocess run — not a rename/refactor, but the
"what does this run leave behind" question is analogous and worth answering explicitly.)*

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | This run WILL create new `chunk` artifacts (content-hash includes `filter_config_version`, so even previously-chunked text gets fresh artifacts if never run through the v2.6 gate before) and a new `dataset` row + gold Parquet object under `gold/healthcare/rag_corpus/{new_export_id}.parquet` | Expected/desired — this IS the measurement's evidence; no cleanup needed (forward-only, D-2) |
| Live service config | None — no Dagster job/schedule config, no n8n-equivalent, no external service touched | None — confirmed no live-service state affected |
| OS-registered state | None — this is a one-shot measurement script/CLI invocation, not a scheduled task | None |
| Secrets/env vars | None new — reuses existing `KLAKE_*` Settings (database_url, storage.*, no new secret) | None |
| Build artifacts | None — no new package, no new egg-info, no compiled binary | None |

**Nothing found requiring migration** — verified by reading `chunk()`'s persistence loop (registry no-op branch
on existing content_hash, line 509) and `export_rag_corpus()`'s always-additive `create_dataset()` call (line
385) — neither mutates or deletes existing rows.

## Common Pitfalls

### Pitfall 1: `run_quality_audit()`'s existing `clean()` call does not thread `domain_filters`

**What goes wrong:** `pipeline/quality_audit.py` line 114–116 calls `clean(parsed_id, source_id, parsed_doc=parsed_doc,
settings=s)` — **no `domain_filters` argument**. If the new chunk-level measurement is built by extending this
existing loop without also fixing this, `clean()` could strip a clinical-code section (ICD-10/LOINC/RxNorm/dosage
text) *before* `chunk()`'s gate — and `chunk()`'s domain-allowlist exemption (which depends on the same
`DomainFilters.normative_allowlists`) never gets a chance to protect it, because the text is already gone.

**Why it happens:** `run_quality_audit()` predates Phase 20's `domain_filters` wiring (Phase 20's own post-execution
code review found and fixed the *exact same* gap in `process.py`'s `clean()` call — see PROJECT.md Phase 20 summary:
"`clean()` (which runs before `chunk()`) never received the resolved `domain_filters` in production" — this is
the same class of bug, in a sibling call site that Phase 20's fix never touched because `quality_audit.py` wasn't
in scope for that phase).

**How to avoid:** Resolve `domain_filters` once per audit run via `DomainLoader.from_name(settings.domain.domain_name).filters`
(process.py line 112–113 pattern) and pass it into **both** the `clean()` and `chunk()` calls in the new
measurement function.

**Warning signs:** A must-not-reject-style clinical code (e.g., `ICD-10 E11.9`) disappearing from the "kept"
count with no corresponding `chunk.substance_gate` rejection reason logged — because it was already gone before
the chunk-level gate ever ran.

### Pitfall 2: Enforce-mode `chunk()` never persists rejected chunks — criterion #1 and #2 may converge

**What goes wrong:** Because `gate_mode` defaults to `"enforce"` (QUAL-03's shipped default, `ChunkQualitySettings.gate_mode`,
settings.py line 326) and `_apply_substance_gate()` filters `raw_chunks` down to the passing subset *before* the
persistence loop runs (chunk.py line 477, then loop at line 490 iterates the already-filtered list), **every chunk
artifact this run creates already has `substance_passed=True` by construction.** A correctly D-04-scoped
export-junk measurement (criterion #2) will therefore find essentially 0% of this run's own chunks excluded by
`export_rag_corpus()`'s substance filter — because they were never candidates for exclusion in the first place;
the garbage was already filtered out one stage earlier, at chunk-persistence time.

**Why it happens:** This is not a bug — it's QUAL-03 + EXPORT-01 working as designed, with EXPORT-01's
`substance_passed` check acting as a redundant safety net for *pre-v2.6* chunks (D-09's backward-compat default),
not as an independent filter on freshly-gated data.

**How to avoid:** Don't be alarmed if criterion #1 (chunk garbage_rate) and criterion #2 (export junk_rate), once
correctly D-04-scoped, come out numerically identical or very close — **this is the expected, correct outcome**,
not a measurement error. Document it explicitly in the before/after report rather than silently presenting two
numbers that look suspiciously alike without explanation. The 28%→X% and 33%→Y% baselines will differ (they
measured genuinely different original problems), but the two "after" numbers converging is itself evidence the
fix worked end-to-end.

**Warning signs:** If criterion #2's junk_rate comes out *higher* than criterion #1's garbage_rate on the same
run, that's a real anomaly worth investigating (e.g., a chunk read failure falling back to empty text at export
time, or a `text` field's `chunk_text = meta.get("text", "")` fallback firing because `chunk.storage_uri` read
failed — export.py line 322–330) — but converging to *equal or lower* is expected.

### Pitfall 3: `export_rag_corpus()` is not a dry-run — it writes a real Parquet every time it's called

**What goes wrong:** Running the measurement twice (e.g., once during development, once for the "official" run)
writes two separate gold-zone Parquet files and two `dataset` registry rows, both domain-wide. This is normal/
expected behavior (not a bug to fix — D-07 in CONTEXT.md explicitly decided not to touch this), but a planner
that assumes the measurement is side-effect-free could be surprised by extra gold-zone objects piling up across
iteration attempts during plan execution/debugging.

**How to avoid:** No code change needed — just document this expectation in the plan/task description so
execution doesn't treat a second Parquet object as a bug. If iterative dev runs are needed before the "official"
measurement, that's an accepted cost (matches D-04's explicit rejection of any destructive dev-stack wipe as
out of scope).

### Pitfall 4: `chunk()`'s content-hash no-op branch can make a "fresh" reprocess partially reuse *ungated* prior artifacts

**What goes wrong:** `chunk()`'s content-hash formula is `f"{parsed_artifact_id}:{filter_config_version}:{text}"`
(chunk.py line 502) — it's scoped by `parsed_artifact_id`, so a **different** `parsed_artifact_id` (which is
what a fresh `reparse_from_raw()`/`load_parsed_doc()` call typically returns, since `quality_audit.py`'s own
loop mirrors this) generally produces new content hashes and new chunk artifacts. However, if `load_parsed_doc()`
returns the SAME already-existing `parsed_document` artifact ID (the reuse branch at quality_audit.py line 101–104
explicitly prefers reusing an existing parsed child over re-parsing), and that same parsed document was ALREADY
run through `chunk()` under the *current* `filter_config_version` by an earlier operation (e.g., Phase 20/21's own
test runs, or a prior partial run of this very measurement), the no-op branch at chunk.py line 509 returns the
**existing** artifact rather than creating a new one. This is not a correctness bug (idempotency is intentional,
PIPE-01), but it means "chunk_ids created by this run" is not the same as "chunk_ids returned by this run's
`chunk()` calls" if some of those calls hit the no-op branch — the returned dict still has `substance_passed`
correctly set from THIS call's fresh gate computation (chunk.py comment, line 507–508: "substance_passed/
rejection_reason are sourced from `raw` ... never from the existing artifact's persisted metadata"), so **the
counting logic (Pattern 1) stays correct regardless of no-op branches** — but if the measurement instead tried to
infer "which chunks are from this run" by DB timestamp, it would silently miss no-op'd chunks.

**How to avoid:** Track chunk IDs from `chunk()`'s **return value** (`results` list — the source of truth
regardless of whether each entry hit the no-op or persistence branch), never by inferring "created recently" from
the registry.

## Code Examples

### Existing per-document counts already available from `clean()` (no change needed)

```python
# Source: src/knowledge_lake/pipeline/quality_audit.py (unmodified, existing code, lines 114-131)
clean_result = clean(
    parsed_id, source_id, parsed_doc=parsed_doc, settings=s, domain_filters=domain_filters,  # ADD domain_filters
)
cleaned_doc = clean_result["cleaned_doc"]  # feed this into chunk(), NOT the original parsed_doc
sections_considered += clean_result["sections_considered"]
sections_kept += clean_result["sections_kept"]
sections_rejected += clean_result["sections_rejected"]
```

### The frozen garbage_rate formula (Phase 17 D-10) — reuse verbatim, do not redefine

```python
# Source: src/knowledge_lake/pipeline/quality_audit.py line 133-134
total = sections_rejected + sections_kept
garbage_rate = (sections_rejected / total) if total > 0 else None
```
Apply the identical `rejected / (rejected + kept)` shape to the chunk-level tally — QUAL-04's frozen-formula
discipline extends naturally; there is no reason for the chunk-level metric to use a different denominator
convention.

### Existing CLI command pattern to extend (cli/app.py, line 974-1017)

```python
# Source: src/knowledge_lake/cli/app.py (existing, unmodified) — table-printing convention to mirror
header = (
    f"{'source_name':<30} {'considered':>10} {'kept':>6} {'rejected':>8} "
    f"{'errored':>8} {'garbage_rate':>12}"
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Section-level garbage rate only (`klake quality-audit`, MEAS-01) | Section-level (unchanged) + new chunk-level + export-level measurement | This phase (22) | Closes the unit mismatch the milestone audit flagged: MEAS-01 measured sections, the milestone's actual success criteria were defined in chunks and gold-export rows |
| `clean()` call in `quality_audit.py` without `domain_filters` | Must add `domain_filters` resolution to both `clean()` and the new `chunk()` call | This phase, if extending `run_quality_audit()`'s loop | See Pitfall 1 — otherwise clinical codes are at risk during the audit itself |

**Deprecated/outdated:** None — no library or pattern in this phase is being replaced; this is additive
measurement code only.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Criterion #1 and criterion #2's "after" numbers will converge (or criterion #2 ≤ criterion #1) once both are correctly D-04-scoped, because enforce-mode `chunk()` never persists rejected chunks | Common Pitfalls, Pitfall 2 | If wrong (criterion #2 comes out *higher*), it signals a genuine export-stage data-loss bug (e.g., `chunk.storage_uri` read failures at export time) that the plan should investigate rather than just report — low risk of silent harm since the anomaly itself would be visible in the numbers, but the planner should not assume equality without checking |
| A2 | No existing report-file precedent for a dedicated "before/after criteria" measurement report exists beyond `v2.6-MILESTONE-AUDIT.md`'s own table and `SUMMARY.md`/`VERIFICATION.md` conventions — this was a targeted grep, not exhaustive | Architecture Patterns / report format | Low risk — CONTEXT.md already delegates the exact report format/location to Claude's discretion during planning, so this is informational, not a hard dependency |

**A1 is the one item worth a deliberate check during planning:** add a verification step to the plan that asserts
`export_junk_rate <= chunk_garbage_rate` (or investigates why not) rather than silently accepting whatever number
comes out.

## Open Questions

1. **Should the "before vs after" report live as a new file, a `PROJECT.md` append, or structured-log-only?**
   - What we know: CONTEXT.md explicitly defers this to Claude's discretion. `v2.6-MILESTONE-AUDIT.md` and
     phase `SUMMARY.md`/`VERIFICATION.md` files are the closest in-repo precedents for a comparison table.
   - What's unclear: whether the planner should treat this as a throwaway CLI-output artifact (ephemeral,
     re-runnable per MEAS-01's "reproducible" contract) or a durable committed report.
   - Recommendation: Given MEAS-01's own acceptance criterion is "reproducible across runs" (not "produces a
     permanent document"), the CLI's structured `--json` output (mirroring `cmd_quality_audit`'s existing
     `--json` flag) is sufficient for reproducibility; a short narrative in the phase's own `SUMMARY.md` (standard
     GSD phase-completion artifact) can carry the actual before/after numbers for human record-keeping, avoiding
     a new bespoke report-file format.

2. **Does the new measurement function belong in `quality_audit.py` itself, or a new sibling module?**
   - What we know: `quality_audit.py`'s docstring explicitly scopes itself to "parse -> clean" and states "must
     never import `knowledge_lake.pipeline.embed` or `knowledge_lake.pipeline.index`." It does NOT currently
     import `chunk` or `export` at all.
   - What's unclear: whether extending it to also call `chunk()`/`export_rag_corpus()` violates the spirit of
     that module-level docstring boundary, or whether the boundary was specifically about embed/index (the
     "no vector-store writes" concern) and chunk/export are fine since D-03 explicitly scopes this phase to
     `parse → clean → chunk (→ export)`.
   - Recommendation: Extend `quality_audit.py` in place (update its module docstring to reflect the new scope)
     rather than creating a new module — MEAS-01's "one measurement module" precedent and the shared
     per-source/per-document loop skeleton make a new module mostly duplicated boilerplate. The docstring's
     "must never import embed/index" constraint is the one to keep untouched (D-03 preserves it).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL (docker compose) | Registry reads/writes for the reprocess run | Yes (confirmed live 2026-07-17 during discuss-phase) | project-pinned | — |
| MinIO (docker compose) | S3-compatible storage for parsed/cleaned/chunk/gold objects | Yes (confirmed live) | project-pinned | — |
| Qdrant | Not needed — D-03 explicitly excludes `embed()`/`index()` from this phase's measurement path | N/A (not required) | — | — |
| Dagster (daemon+webserver) | Not needed — measurement runs via CLI/pipeline function calls, not a Dagster asset materialization | Available but unused | project-pinned | — |
| LiteLLM | Not needed — no LLM calls in `parse → clean → chunk → export` (deterministic-first, PROJECT.md constraint) | Available but unused | project-pinned | — |
| SearXNG | Not needed | Available but unused | — | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None — all required services confirmed live during discuss-phase's own
DB inspection (2026-07-17), and this phase adds no new service dependency.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 (project-pinned, confirmed via `pyproject.toml`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (line 121) — `testpaths=["tests"]`, `xfail_strict=true`, markers `browser`/`integration` |
| Quick run command | `pytest tests/unit/test_quality_audit.py tests/unit/test_cli_quality_audit.py -x` |
| Full suite command | `pytest` (1176+ passing baseline per PROJECT.md; must stay green — REQUIREMENTS.md success criterion #6) |

### Phase Requirements → Test Map

No new REQ-IDs are assigned to this phase (per phase description). The table below maps the measurement work to
the already-shipped requirements it closes the loop on, and to concrete tests:

| Req ID (existing, being closed out) | Behavior | Test Type | Automated Command | File Exists? |
|--------------------------------------|----------|-----------|--------------------|--------------|
| MEAS-01 (extended) | New chunk-level + export-level measurement function returns correct kept/rejected/reason tallies against a seeded in-memory-SQLite fixture (mirrors `test_quality_audit.py`'s existing fixture pattern) | unit | `pytest tests/unit/test_quality_audit.py -k chunk_audit -x` | ❌ Wave 0 — extend existing file |
| MEAS-01 (extended) | New CLI command/flag prints the extended table / `--json` output correctly | unit | `pytest tests/unit/test_cli_quality_audit.py -k chunk -x` | ❌ Wave 0 — extend existing file |
| EXPORT-01 (measurement-side verification) | D-04 scoping: export-junk count only reflects this run's own chunk IDs, not the domain's full 4,521-chunk population (regression test: seed old ungated chunks + new gated chunks in the same fixture DB, assert old chunks are excluded from the reported rate) | unit | `pytest tests/unit/test_quality_audit.py -k dilution -x` | ❌ Wave 0 — new test, critical regression coverage for D-04 |
| — | Domain_filters gap fix (Pitfall 1): a clinical-code fixture text survives the extended audit's `clean()` call | unit | `pytest tests/unit/test_quality_audit.py -k domain_filters -x` | ❌ Wave 0 — new test |

### Sampling Rate

- **Per task commit:** `pytest tests/unit/test_quality_audit.py tests/unit/test_cli_quality_audit.py -x`
- **Per wave merge:** `pytest` (full suite)
- **Phase gate:** Full suite green before `/gsd-verify-work`; additionally, since this phase's actual purpose is
  producing a real number against real (reprocessed) data, plan a manual/scripted "run the real thing against
  the live dev stack" step distinct from the pytest fixture-based unit tests — the fixture tests prove the
  *code* is correct; only a real run against the 34 healthcare sources proves the *milestone criteria* are met.

### Wave 0 Gaps

- [ ] `tests/unit/test_quality_audit.py` — extend with chunk-level tally tests + the D-04 dilution-regression test
      (seed both a pre-v2.6 chunk with no `substance_passed` key and a fresh gated chunk in the same fixture DB;
      assert the scoped measurement reports only the fresh one)
- [ ] `tests/unit/test_cli_quality_audit.py` — extend with the new CLI surface's output-format test
- [ ] No new fixtures/conftest needed — `test_quality_audit.py`'s existing in-memory-SQLite engine/session
      fixtures (StaticPool, monkeypatched `get_engine`) are directly reusable

*(If a real end-to-end run against the live dev stack is also desired as an integration test, it would go in
`tests/integration/` under the existing `integration` marker — mirroring `tests/integration/test_export_parquet_duckdb.py` — but this is optional given the "real run against real data" step is better executed as a one-time
measurement command invocation during phase execution, not a permanent CI-gated integration test, per D-04's
"the concrete non-destructive mechanism ... is preferred over wiping the dev stack" framing, which implies a
manual/scripted run rather than a repeatable CI fixture.)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | This phase adds no new auth surface (internal CLI/pipeline function only) |
| V3 Session Management | No | N/A |
| V4 Access Control | No | N/A — reuses existing `Source.domain` scoping already enforced elsewhere |
| V5 Input Validation | Yes | `domain` CLI param reuses the existing `Source.domain == domain` equality-filter pattern (`quality_audit.py` line 59) — no new string interpolation into SQL; if any DuckDB read-back is added (Pattern 3 alternative), reuse `export.py`'s existing `_S3_URI_RE` single-quote guard (line 58, 710) rather than a new unvalidated f-string |
| V6 Cryptography | No | No new crypto surface |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|-----------------------|
| SQL injection via `domain` CLI param | Tampering | Already mitigated — `Source.domain == domain` is a parameterized SQLAlchemy `.where()` clause (ORM-level, not raw SQL string formatting), same as the existing `run_quality_audit()` |
| DuckDB f-string SET-statement injection (only relevant if the measurement reuses `verify_export()`'s DuckDB path) | Tampering | Reuse `export.py`'s existing `_S3_URI_RE` regex + single-quote rejection guard (lines 58, 701-714) rather than constructing a new unguarded f-string; **prefer Pattern 3's Polars read-back instead of DuckDB**, which avoids this whole class of risk since Polars' `read_parquet()` takes a byte buffer, not an interpolated connection string |
| Information disclosure via export column allow-list bypass | Tampering/Info disclosure | Not modified by this phase — `_RAG_CORPUS_FIELDS` allow-list (T-05-08) stays untouched since this phase reuses `export_rag_corpus()` unmodified |

## Sources

### Primary (HIGH confidence — direct source-file reads this session)
- `src/knowledge_lake/pipeline/quality_audit.py` (full file read) — existing MEAS-01 harness, exact pattern to extend
- `src/knowledge_lake/pipeline/chunk.py` (full file read) — `_build_token_chunks`, `_apply_substance_gate`,
  `_assert_chunk_conservation_invariant`, `chunk()`'s persistence loop and content-hash formula
- `src/knowledge_lake/pipeline/export.py` (full file read) — `export_rag_corpus()`, `_RAG_CORPUS_FIELDS`,
  `verify_export()`'s DuckDB SQL-injection guard pattern
- `src/knowledge_lake/pipeline/process.py` (lines 55-145) — `domain_filters` resolution and threading pattern
  (`DomainLoader.from_name(...).filters`), the exact wiring this phase's measurement must replicate
- `src/knowledge_lake/pipeline/clean.py` (`clean()` signature, lines 435-442) — confirms `domain_filters` kwarg
  exists and is currently unused by `quality_audit.py`'s `clean()` call (Pitfall 1)
- `src/knowledge_lake/cli/app.py` (lines 220-284, 974-1017) — `cmd_chunk`, `cmd_clean`, `cmd_quality_audit`
  existing CLI patterns
- `src/knowledge_lake/registry/repo.py` (grep for `get_artifact`/`list_artifacts_by_type`) — confirms no batch
  ID-lookup helper exists; single-row `get_artifact()` is the available primitive
- `src/knowledge_lake/config/settings.py` (grep for `gate_mode`, `filter_config_version`, `DomainSettings`) —
  confirms `gate_mode: Literal["enforce","report"] = "enforce"` default and `domain.domain_name` field
- `tests/unit/test_quality_audit.py`, `tests/unit/test_export.py` (fixture patterns read) — in-memory-SQLite
  engine/session fixture convention to reuse for new tests
- `pyproject.toml` `[tool.pytest.ini_options]` — test framework/markers/`xfail_strict` confirmation
- `.planning/phases/22-.../22-CONTEXT.md` — locked decisions (D-01 through D-09), live DB inspection findings
- `.planning/v2.6-MILESTONE-AUDIT.md` — the two tech-debt items this phase closes, in the auditor's own words
- `.planning/MILESTONE-CONTEXT.md` §D-2 — forward-only scope decision, original 28%/33% baseline evidence table
- `.planning/REQUIREMENTS.md` — MEAS-01/QUAL-03/QUAL-04/QUAL-05/EXPORT-01 original acceptance text
- `.planning/phases/17-.../17-CONTEXT.md`, `.planning/phases/20-.../20-CONTEXT.md` — D-06/D-07/D-10 (Phase 17)
  and D-08/D-09 (Phase 20) decisions this phase's measurement must stay consistent with

No secondary/tertiary sources were needed — this phase required zero external web research; all technology is
already installed, already documented in this codebase's own docstrings, and was verified by direct reading.

## Metadata

**Confidence breakdown:**
- Standard stack: N/A — no new packages (see Package Legitimacy Audit)
- Architecture: HIGH — every pattern cited is read directly from the actual source files this phase will modify
- Pitfalls: HIGH — Pitfall 1 (missing `domain_filters`) and Pitfall 4 (content-hash no-op branch) are confirmed
  by direct code inspection, not inference; Pitfall 2 (criteria convergence) is a structural deduction from
  confirmed code behavior, flagged as Assumption A1 for the planner to verify empirically during execution

**Research date:** 2026-07-17
**Valid until:** No expiry driver — this is internal-codebase research tied to the current commit, not a
time-sensitive external-library version check. Re-verify only if `pipeline/chunk.py`, `pipeline/export.py`, or
`pipeline/quality_audit.py` change before this phase is planned/executed.
