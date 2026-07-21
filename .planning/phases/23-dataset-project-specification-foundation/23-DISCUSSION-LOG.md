# Phase 23: Dataset Project + Specification Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-21
**Phase:** 23-Dataset Project + Specification Foundation
**Mode:** `--auto` (fully autonomous — no interactive prompts; Claude selected the recommended option for every gray area, logged below)
**Areas discussed:** Forward-referencing spec fields, export_finetune_dataset legacy resolution, spec input/storage format, illegal transition error shape, MCP surface scope

---

## Forward-referencing spec fields (quality_contract, policy validation timing)

| Option | Description | Selected |
|--------|-------------|----------|
| Fail spec validate on any quality_contract/policy reference (blocks all specs until Phase 25/26 ship) | Referential integrity strictly enforced from day one | |
| Schema-validate now, referentially enforce later (additive, no schema version bump) | Fields exist in schema, shape-checked; existence-checked once Phases 25/26 land | ✓ |
| Omit the fields entirely until Phase 25/26 | Spec schema grows a breaking field addition later | |

**Selected:** Schema-validate now, referentially enforce later.
**Notes:** [auto] Matches Phase 19's `DomainFilters.thresholds` precedent (validated but intentionally unconsumed, reserved for a later phase) — avoids forcing SPEC-02 re-versioning when Phase 25/26 land.

---

## `export_finetune_dataset(name)` legacy resolution rule

| Option | Description | Selected |
|--------|-------------|----------|
| Leave implicit query-order resolution | What Pitfall 2 explicitly warns against | |
| Add `get_latest_released_dataset_by_name()`, route all 4 call sites through it, with legacy fallback for project-less datasets | Named, tested, explicit rule | ✓ |
| Require an explicit version arg everywhere (breaking) | Would break the MCP tool's no-version signature — an LLM agent has no version to supply | |

**Selected:** Add `get_latest_released_dataset_by_name()` with legacy fallback.
**Notes:** [auto] This is the literal fix PITFALLS.md Pitfall 2 prescribes and is directly tested by Phase 23's Success Criterion 5.

---

## Dataset Specification input/storage format

| Option | Description | Selected |
|--------|-------------|----------|
| YAML authoring, JSON storage, hash over canonical parsed form | Matches existing `sources.yaml`/`domain.yaml` convention; hash immune to formatting noise | ✓ |
| JSON-only authoring and storage | Inconsistent with rest of the codebase's config-authoring convention | |
| Hash raw file bytes | Would spuriously re-version on whitespace/reordering edits | |

**Selected:** YAML authoring, JSON storage, canonical-form hash.
**Notes:** [auto] Consistent with WR-05's existing content-hash discipline elsewhere in the pipeline.

---

## Illegal transition error shape

| Option | Description | Selected |
|--------|-------------|----------|
| Generic `ValueError` | Inconsistent with codebase's typed-exception convention | |
| Dedicated `IllegalProjectTransitionError` (from_state/to_state/legal_next_states) surfaced as CLI error / HTTP 409 / MCP tool error | Follows `TrainEvalContaminationError` precedent | ✓ |

**Selected:** Dedicated `IllegalProjectTransitionError`.
**Notes:** [auto] Keeps CLI/API/MCP error surfaces consistent with each other per SURFACE-01/02.

---

## MCP surface scope for this phase

| Option | Description | Selected |
|--------|-------------|----------|
| Ship both read and mutating MCP tools (project_new, transition, spec edit) | Full parity with CLI/API immediately | |
| Read-only MCP tools only (project_list, project_show, spec_validate); defer mutating tools | Matches SURFACE-03's explicit risk ordering | ✓ |
| No MCP tools this phase | Under-delivers SURFACE-03's intent for this phase | |

**Selected:** Read-only MCP tools only.
**Notes:** [auto] SURFACE-03 explicitly states "read tools are prioritized over mutating ones per governance-action risk" — mutating governance actions stay CLI/API-only until later phases establish the human-approval-gate pattern for Release.

---

## Claude's Discretion

- Exact column/table naming within `dataset_projects`/`dataset_specs` beyond the `dpj_`/`dsp_` ID-prefix convention already fixed by ARCHITECTURE.md
- Internal transition-graph encoding of the 11-state lifecycle (state list and order are already fixed by PROJECT.md/ROADMAP.md)
- Whether `pipeline/project.py` stays one file or splits state-machine vs. spec-versioning logic

## Deferred Ideas

- Referential enforcement of quality_contract/policy spec fields → Phases 25/26
- Human-approval-gate pattern for mutating governance actions → likely Phase 30 (Release)
- KL-16 (domain-pack-owned Dagster jobs) → already tracked as deferred tech debt, not touched here
