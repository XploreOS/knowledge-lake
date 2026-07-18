# Phase 17: Close the Bypass + Measurement - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-15
**Phase:** 17-Close the Bypass + Measurement
**Areas discussed:** Bypass wiring strategy, Quality audit output, Rejection recording, Conservation invariant

---

## Bypass Wiring Strategy

### Q1: How should the cleaned ParsedDoc reach chunk/enrich/tree_index in the Dagster graph?

| Option | Description | Selected |
|--------|-------------|----------|
| Replace in output dict | clean_document replaces parsed_doc with the cleaned version in its output dict. Downstream assets see cleaned text with zero signature change. Simplest fix. | |
| Separate output key | clean_document adds a new 'cleaned_doc' key alongside 'parsed_doc'. Downstream assets switch to reading 'cleaned_doc'. More explicit. | |
| You decide | Claude picks the approach that minimizes code churn and preserves existing test contracts. | ✓ |

**User's choice:** You decide
**Notes:** None — user trusts Claude's judgment on internal wiring.

### Q2: For process_crawled (CLI path), should the clean step produce the same artifact registration as Dagster?

| Option | Description | Selected |
|--------|-------------|----------|
| Full parity | process_crawled calls clean() with artifact registration. Both paths produce identical lineage graphs. | ✓ |
| In-memory only | process_crawled calls clean() but skips artifact registration. Fewer DB writes, faster. | |
| You decide | Claude picks based on WR-05 convention requirements. | |

**User's choice:** You decide (interpreted as full parity based on CLEAN-02 acceptance criteria requiring identical output)
**Notes:** CLEAN-02 explicitly requires "same source produces identical chunks whether processed via Dagster or via `klake process`."

### Q3: Should the curate path be touched?

| Option | Description | Selected |
|--------|-------------|----------|
| Leave alone | curate_document_asset already works correctly off cleaned text. Don't touch what isn't broken. | |
| Verify only | Add a test assertion confirming curate reads cleaned text. Prevents future regression. | |
| You decide | Claude assesses whether curate actually uses the cleaned path. | ✓ |

**User's choice:** You decide
**Notes:** None.

### Q4: Hash convention — forward-only or versioned?

| Option | Description | Selected |
|--------|-------------|----------|
| Forward-only (D-2) | Existing data is test data. New hash convention applies to all new clean() calls. No migration. | ✓ |
| Version the hash scheme | Add hash_version field. Future-proofs for production data. | |

**User's choice:** Forward-only (D-2)
**Notes:** Aligns with existing scope decision D-2 (forward-only confirmed).

---

## Quality Audit Output

### Q1: What interface should the quality audit expose?

| Option | Description | Selected |
|--------|-------------|----------|
| CLI command only | `klake quality-audit` outputs table to stdout. JSON flag for machine-readable. | |
| CLI + API endpoint | Both CLI and API for dashboarding. | |
| You decide | Claude picks based on existing surface patterns. | ✓ |

**User's choice:** You decide
**Notes:** None.

### Q2: How should the held-out subset be defined?

| Option | Description | Selected |
|--------|-------------|----------|
| All 34 sources | Run across all 34 healthcare sources in domain pack. Matches original audit. | ✓ |
| Tagged subset | Tag specific sources as audit-holdout in sources.yaml. | |
| You decide | Claude picks based on MEAS-01 acceptance criteria. | |

**User's choice:** All 34 sources
**Notes:** MEAS-01 acceptance criteria explicitly says "34 rows."

### Q3: Measurement approach — pipeline output or frozen heuristic?

| Option | Description | Selected |
|--------|-------------|----------|
| Pipeline output | Re-runs real pipeline and measures actual rejected/kept. Simple, honest. | ✓ |
| Frozen heuristic | Static classifier that never changes. Pipeline can improve but measurement stick constant. | |
| Both | Two columns — frozen for comparison, real for actual behavior. | |

**User's choice:** Pipeline output
**Notes:** User wants audit to reflect real pipeline behavior.

### Q4: Table columns?

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal (5 cols) | source_name, total_sections, kept, rejected, garbage_rate%. | |
| Detailed (8+ cols) | Adds rejection_reasons, avg_section_tokens, format. | |
| You decide | Claude picks based on MEAS-01 and downstream phase needs. | ✓ |

**User's choice:** You decide
**Notes:** None.

---

## Rejection Recording

### Q1: Where should rejection records be stored?

| Option | Description | Selected |
|--------|-------------|----------|
| Postgres table | New `chunk_rejections` table. Queryable, supports metrics natively. | |
| Structured log only | Log via structlog. No new table, query from log aggregation. | |
| You decide | Claude picks based on QUAL-04 requirements and existing infrastructure. | ✓ |

**User's choice:** You decide
**Notes:** None.

### Q2: Should rejections be recorded before the substance gate exists (Phase 20)?

| Option | Description | Selected |
|--------|-------------|----------|
| Record from Phase 17 | Start recording now with current clean rejections. Audit harness needs this data. | |
| Schema only in 17, populate in 20 | Create infrastructure now, wire writes when substance gate lands. | |
| You decide | Claude picks based on what MEAS-01 needs. | ✓ |

**User's choice:** You decide
**Notes:** None.

### Q3: How to interpret "frozen metric"?

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed formula | garbage_rate = rejected / (rejected + kept). Formula fixed, what counts as rejected evolves. | |
| Fixed classifier | Separate static classifier labels chunks as garbage, independent of live gate. | |
| You decide | Claude interprets based on QUAL-04 acceptance criteria. | ✓ |

**User's choice:** You decide
**Notes:** None.

---

## Conservation Invariant

### Q1: How should the conservation invariant be enforced at runtime?

| Option | Description | Selected |
|--------|-------------|----------|
| Hard assertion (raise) | Halt processing if invariant violated. Fail loud. | |
| Logged warning + metric | Log warning, emit metric, continue. Relies on monitoring. | |
| You decide | Claude picks based on existing error handling patterns. | ✓ |

**User's choice:** You decide
**Notes:** None.

### Q2: Where in the pipeline should the conservation check run?

| Option | Description | Selected |
|--------|-------------|----------|
| At clean() exit | clean() checks input sections == output + removed. Earliest point. | |
| At chunk entry | chunk_document verifies received sections match clean metadata. Consumer boundary. | |
| Both | Double-check at both points. Belt and suspenders. | |
| You decide | Claude picks based on failure modes. | ✓ |

**User's choice:** You decide
**Notes:** None.

### Q3: Should conservation apply at text-level now or section-level stub?

| Option | Description | Selected |
|--------|-------------|----------|
| Wire at text level | Track bytes_in vs bytes_out + bytes_removed. Proves invariant works before Phase 19. | |
| Section-level stub | Define interface now, all sections as 'kept'. Phase 19 populates real counts. | |
| You decide | Claude picks based on QUAL-05 and what makes Phase 19 easier. | ✓ |

**User's choice:** You decide
**Notes:** None.

---

## Claude's Discretion

User delegated to Claude on: bypass threading approach, curate verification, audit interface, audit columns, rejection storage mechanism, rejection timing, metric interpretation, conservation enforcement, conservation placement, conservation granularity.

User locked: hash convention (forward-only), audit scope (34 sources), measurement approach (real pipeline output).

## Deferred Ideas

None — discussion stayed within phase scope.
