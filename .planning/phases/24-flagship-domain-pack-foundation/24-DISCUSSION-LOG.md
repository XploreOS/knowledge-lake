# Phase 24: Flagship Domain Pack Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-21
**Phase:** 24-flagship-domain-pack-foundation
**Areas discussed (auto-selected, all):** Domain pack identity, Source corpus composition, Taxonomy focus, Quality-gate diagnostic scope, Dataset Project scoping

---

## Domain pack identity — slug and scaffold path

| Option | Description | Selected |
|--------|-------------|----------|
| `agent-security` at top-level `domains/` | Short slug, loadable via standard `klake init --domain` path | ✓ |
| Reuse `domains/aviation` or `domains/climate` | Pre-existing stub packs | |
| Scaffold under `domains/local/agent-security` | Default location for ad-hoc packs | |

**Selected:** `agent-security`, scaffolded top-level via `klake domain new agent-security` (default `--root domains`).
**Notes:** Audited `domains/aviation` (real FAA/flight-training pack, unrelated) and `domains/climate` (empty stub) — neither is a legitimate substitute for "AI Agent Security and Permission." `domains/local/` was explicitly rejected per PITFALLS.md Pitfall 9's documented `DomainLoader.from_name()` loader-path trap.

---

## Source corpus composition

| Option | Description | Selected |
|--------|-------------|----------|
| 8-source seed (OWASP LLM Top10, OWASP Agentic AI, MCP spec, NIST AI RMF, NIST AI 600-1, MITRE ATLAS, CISA guidelines, IETF RFC 6749) | Public-domain / CC BY-SA / open-spec / IETF-licensed sources across html+pdf | ✓ |
| Port a subset of existing aviation/climate sources | Reuse existing stub sources | |
| Defer source selection entirely to planner | No seed list in context | |

**Selected:** 8-source seed list (see CONTEXT.md D-02).
**Notes:** Every candidate source has a clear, non-restrictive license, satisfying the project's legal constraint without needing Phase 25's Policy engine to exist first. Flagged as a starting candidate list requiring live URL verification during research/planning, not a locked manifest.

---

## Taxonomy focus

| Option | Description | Selected |
|--------|-------------|----------|
| Security/permission-centric taxonomy (tool_identifier, permission_scope, protocol, threat_category, mitigation, severity) | Names the exact short/structured content shapes Pitfall 9 calls out | ✓ |
| Generic taxonomy copied from healthcare pack shape | Faster but domain-irrelevant | |

**Selected:** Security/permission-centric taxonomy (see CONTEXT.md D-03).
**Notes:** Directly informs both the enrichment prompts and what the Phase 24 gate-review findings document should specifically look for.

---

## Quality-gate diagnostic scope

| Option | Description | Selected |
|--------|-------------|----------|
| Report-only gate run + committed human-review findings doc, fix deferred to Phase 26 | Matches roadmap's explicit ordering note and Phase 19/20 precedent | ✓ |
| Author `filters.yaml` for `agent-security` in this phase | Would close the gap immediately | |
| Skip the gate diagnostic entirely | Fastest, but violates success criterion 3 and Pitfall 9's explicit warning sign | |

**Selected:** Report-only run (`gate_mode="report"`) + `24-GATE-REVIEW-FINDINGS.md`, fix explicitly deferred to Phase 26.
**Notes:** ROADMAP.md's own scope-decision note states Phase 24's quality-gate tuning "still waits on Phase 26 (Quality Contract) to exist" — authoring `filters.yaml` now would be scope creep against the phase's own charter, not a citation-worthy improvement.

---

## Dataset Project scoping

| Option | Description | Selected |
|--------|-------------|----------|
| Drive project to `ready` (draft→configured→sources_pending→ready) | All 4 transitions legal today, most-advanced honest state | ✓ |
| Stop at `sources_pending` | More conservative, avoids any perception of a "complete" spec | |

**Selected:** `ready`.
**Notes:** `dataset_type="rag_corpus"` chosen to match what this phase actually ingests (instruction/eval slices come later, Phase 28). `purpose`/`intended_uses`/`prohibited_uses` text drafted now, including an explicit dual-use caveat given the domain's subject matter (a security corpus could itself be misused to train attack-capable behavior) — even though Phase 25's Policy engine is what will formally enforce it.

---

## Claude's Discretion

- Exact `sources.yaml` entry count/order beyond the D-02 seed list
- Exact validator class shape and prompt template content beyond the D-03 taxonomy anchors
- Spec-authoring mechanics (YAML file vs hand-built) — follows Phase 23's established convention
- Rejection-sample size/formatting in the gate-review findings document

## Deferred Ideas

- `domains/agent-security/filters.yaml` authoring — Phase 26 (Quality Contract)
- KL-16 (domain-pack-owned Dagster jobs) — remains deferred tech debt, no change
- Formal Usage Policy decisions for the 8 seed sources — Phase 25's job (open question there: live-policy path vs. grandfather/backfill path)
