# Phase 17: Close the Bypass + Measurement - Context

**Gathered:** 2026-07-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the cleaned text onto the load-bearing path (both Dagster asset graph and CLI `process_crawled`), fix the lineage hash to prevent cross-document corruption, and establish a measurable garbage-rate baseline. This phase makes the clean stage actually effective and provides the measurement infrastructure that all subsequent quality phases (19, 20, 21) depend on.

**Requirements:** CLEAN-01, CLEAN-02, CLEAN-03, QUAL-04, QUAL-05, MEAS-01

</domain>

<decisions>
## Implementation Decisions

### Bypass Wiring (CLEAN-01, CLEAN-02)
- **D-01:** Claude decides the threading approach (replace-in-dict vs separate key) — optimize for minimal code churn and preserved test contracts.
- **D-02:** Both paths (Dagster `clean_document` asset and `process_crawled` CLI) must produce full parity — same artifact registration, same lineage graph, same DB records. The CLI is not a shortcut; it's a first-class path.
- **D-03:** The curate path (`curate_document_asset`) already reads cleaned text correctly — verify with a test assertion but don't change its code.

### Content Hash (CLEAN-03)
- **D-04:** Forward-only hash convention per scope decision D-2. New `sha256(f"{parsed_artifact_id}:{cleaned_text}")` applies to all new `clean()` calls. No migration of existing artifacts (they are test data that gets wiped).

### Quality Audit (MEAS-01)
- **D-05:** Claude decides the interface (CLI command, API endpoint, or both) based on existing `klake` surface patterns and what MEAS-01 requires.
- **D-06:** Audit runs against all 34 healthcare sources from the domain pack — matches original audit scope exactly.
- **D-07:** Audit measures real pipeline output (re-runs the pipeline and reports what gets rejected/kept). No separate frozen classifier — the pipeline IS the measurement.
- **D-08:** Claude decides column set for the audit table — must satisfy MEAS-01 acceptance criteria at minimum (total sections, kept, rejected, rejection reasons, garbage rate).

### Rejection Recording (QUAL-04)
- **D-09:** Claude decides storage mechanism (Postgres table vs structured log) and timing (record now vs schema-only-now-populate-later). Must support computing per-source garbage-rate from the records.
- **D-10:** "Frozen metric" means the FORMULA is fixed: `garbage_rate = rejected / (rejected + kept)`. What counts as "rejected" evolves as gates improve — that's the point. The formula itself doesn't change.

### Conservation Invariant (QUAL-05)
- **D-11:** Claude decides enforcement mechanism (hard assertion vs logged warning vs both) and placement in the pipeline. Must satisfy QUAL-05's acceptance criteria: a broken parser returning 0 sections is detected as distinct from a correct gate rejecting all sections.
- **D-12:** Phase 17 wires the conservation infrastructure at whatever granularity makes sense for the current clean stage. Phase 19 will populate it with section-level rejection counts when the section classifier arrives.

### Claude's Discretion

The user delegated most HOW decisions to Claude's judgment, keeping only these locked:
- Hash convention: forward-only (D-2 confirmed)
- Audit scope: all 34 sources
- Audit measurement: real pipeline output (not frozen heuristic)
- Metric formula: `rejected / (rejected + kept)` — fixed definition
- Full parity between Dagster and CLI paths

Claude has flexibility on: threading approach, enforcement mechanism, storage choice, table format, curate verification strategy, conservation check placement and granularity.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Scope
- `.planning/REQUIREMENTS.md` — Full v2.6 requirement definitions (CLEAN-01 through MEAS-02)
- `.planning/MILESTONE-CONTEXT.md` — Audit evidence, root causes, scope decisions D-1 through D-5
- `.planning/ROADMAP.md` §Phase 17 — Success criteria and dependency graph

### Research
- `.planning/research/SUMMARY.md` — Synthesized research from 4 parallel researchers (stack, features, architecture, pitfalls)

### Pipeline Code (the bypass)
- `src/knowledge_lake/dagster_defs/assets.py` — `clean_document` asset (line ~276), `chunk_document` (line ~350), `enrich_document` (line ~408) — the bypass is HERE
- `src/knowledge_lake/pipeline/process.py` — `process_crawled()` function (line 17) — the CLI bypass is HERE
- `src/knowledge_lake/pipeline/clean.py` — `clean()` function (line 167), `BOILERPLATE_PATTERNS` (line 46)

### Lineage & Registry
- `src/knowledge_lake/lineage.py` — WR-05 content hash convention
- `src/knowledge_lake/ids.py` — Artifact type identifiers

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `clean()` in `pipeline/clean.py:167` — Already produces cleaned text and registers artifacts; just not connected to downstream consumers
- `BOILERPLATE_PATTERNS` in `clean.py:46` — 4 existing regexes that strip boilerplate text
- `registry_repo.get_artifact_by_hash()` — Content-addressable dedup pattern (used by clean, enrich, tree_index)
- `structlog` throughout pipeline — Established logging pattern for all pipeline stages

### Established Patterns
- Dagster assets pass dicts with `parsed_artifact_id`, `source_id`, `parsed_doc`, `collection` keys — downstream assets destructure these
- `process_crawled` mirrors the Dagster graph imperatively: parse → (should be clean →) chunk → embed → index
- RetryPolicy on all Dagster assets — error handling is at the orchestrator level
- Content hashing via `hashlib.sha256` for artifact dedup
- `_curation_cache_key` pattern in curate.py for config versioning (reusable for PIPE-01 in Phase 20)

### Integration Points
- `clean_document` output dict → consumed by `chunk_document`, `enrich_document`, `tree_index_document`, `curate_document_asset`
- `process_crawled` → needs `clean()` call inserted between parse and chunk
- Postgres artifact registry — where new rejection records would live
- `klake` CLI (Typer app) — where `quality-audit` command would be added

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches. The user wants Claude to make pragmatic implementation choices that minimize churn and maximize correctness.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 17-Close the Bypass + Measurement*
*Context gathered: 2026-07-15*
