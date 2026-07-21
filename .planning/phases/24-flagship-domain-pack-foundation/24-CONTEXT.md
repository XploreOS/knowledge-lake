# Phase 24: Flagship Domain Pack Foundation - Context

**Gathered:** 2026-07-21
**Status:** Ready for planning
**Mode:** `--auto` — all gray areas auto-resolved with recommended defaults (no interactive prompts). Every choice below is logged with rationale so the user can override before planning.

<domain>
## Phase Boundary

This phase scaffolds a real, non-healthcare domain pack ("AI Agent Security and Permission Dataset") and ingests a genuine source corpus for it through the existing parse → clean → chunk → enrich → embed → index pipeline — so every later v2.7 phase (Policy, Quality Contract, CurationEngine, Candidates, Splits, Release, Lineage) has real flagship data instead of synthetic fixtures. It also runs the existing chunk-substance gate against that corpus in **report-only mode** and produces a human-reviewed findings document per PITFALLS.md Pitfall 9, and scopes a Dataset Project to the flagship pack, advancing it to `sources_pending`/`ready`.

**Explicitly NOT in this phase:**
- Authoring a `filters.yaml` normative allowlist (or any fix) for the flagship domain — Pitfall 9's remediation is explicitly deferred to **Phase 26 (Quality Contract)** per ROADMAP.md's own ordering note ("its domain-specific quality-gate tuning still waits on Phase 26 to exist"). Phase 24's job is to run the gate in report-only mode and **document** the gap, not close it.
- Usage Policy decisions for the new sources (Phase 25), Quality Contract rule evaluation (Phase 26), CurationEngine/DataTrove (Phase 27), generated-example candidates (Phase 28), splits/contamination (Phase 29), Release/reproducibility (Phase 30), diff/lineage/eval (Phase 31), the actual flagship *release* (Phase 32 — this phase only formally *enables* FLAGSHIP-01/02, it does not satisfy them; the roadmap's own Note says so explicitly).
- Domain-pack-owned Dagster jobs/schedules (KL-16) — per ARCHITECTURE.md, the flagship pack runs through the existing generic `core_pipeline_e2e_job` + `DomainLoader.from_name()` runtime branch exactly like healthcare does today; no new Dagster job is needed unless a later phase proves it needs a genuinely distinct schedule/sensor (not in scope here).

</domain>

<decisions>
## Implementation Decisions

### Domain pack identity

- **D-01 — Domain pack slug: `agent-security`.** Scaffolded via `klake domain new agent-security` (default `--root domains`, i.e. **top-level** `domains/agent-security/`, never `domains/local/`). This sidesteps the known `DomainLoader.from_name()` path-traversal-guard limitation documented in project memory and explicitly flagged by PITFALLS.md Pitfall 9 — a pack under `domains/local/` is not loadable via `klake init --domain <name>`. Confirm post-scaffold that `klake init --domain agent-security` actually registers sources (Pitfall 9's stated verification step), not just that the directory exists.
  Rationale: short, matches the existing single-word pack naming style (`healthcare`, `aviation`, `climate`); passes `_DOMAIN_NAME_RE` (`^[a-zA-Z][a-zA-Z0-9_-]{0,63}$}`); `domains/aviation` and `domains/climate` are pre-existing, unrelated stub packs — audited and confirmed NOT reusable as the flagship (aviation is FAA/flight-training content, climate is an empty stub; neither matches "AI Agent Security and Permission").
  [auto] Recommended default selected — no interactive prompt.

- **D-02 — Source corpus composition (starting seed, not final scale).** Seed `sources.yaml` with a small set of real, clearly-licensed public sources covering the domain's core themes (agent tool-use security, permission/scope models, threat taxonomies), mirroring how the healthcare pack started small and grew to 28 over time — this phase needs a "genuine corpus," not full scale:
  - OWASP Top 10 for LLM Applications (html, CC BY-SA) — prompt injection, excessive agency, supply chain
  - OWASP Agentic AI — Threats and Mitigations (html, CC BY-SA)
  - Model Context Protocol specification site (html, MIT-licensed spec repo) — tool/resource permission model, authorization
  - NIST AI Risk Management Framework (AI RMF 1.0) (pdf, US gov public domain)
  - NIST AI 600-1 Generative AI Profile (pdf, US gov public domain)
  - MITRE ATLAS (html, open/public) — adversarial threat taxonomy for AI systems
  - CISA Guidelines for Secure AI System Development (pdf/html, US gov public domain)
  - IETF RFC 6749 (OAuth 2.0 Authorization Framework) (html, IETF Trust license — free reproduction) — canonical scope/permission model reference
  Rationale: every source is public-domain, CC BY-SA, or an open spec/IETF license — satisfies the project's legal constraint (license tracking, no restricted scraping) without needing a policy-engine gate that doesn't exist until Phase 25. Mix of html/pdf exercises the same multi-format parser fallback chain healthcare already proved.
  **Caveat:** exact URLs must be live-verified (HTTP reachable, robots.txt-compliant) during research/planning before ingestion — this is a starting candidate list, not a locked, pre-verified source manifest.
  [auto] Recommended default selected — no interactive prompt.

- **D-03 — Taxonomy focus.** `taxonomy.yaml` entity types center on: `tool_identifier`, `permission_scope`, `protocol` (MCP / OAuth / RBAC / ABAC), `threat_category` (prompt_injection, privilege_escalation, confused_deputy, tool_poisoning, data_exfiltration), `mitigation`, `severity`. Categories: `agent_security`, `permission_model`, `threat_taxonomy`, `standards_framework`.
  Rationale: directly names the domain-specific short/structured content shapes PITFALLS.md Pitfall 9 calls out by name (permission-scope strings like `read:documents`, tool-call identifiers like `mcp__filesystem__read`, CVSS-style severity strings) — gives the enrichment prompts and the Phase 24 gate review something concrete to check for, and gives Phase 26's Quality Contract a head start on what a domain-specific allowlist needs to protect.
  [auto] Recommended default selected — no interactive prompt.

### Quality-gate diagnostic (Pitfall 9 discipline)

- **D-04 — Report-only run + human review artifact.** Run the existing chunk-substance gate against the flagship corpus with `chunk_quality.gate_mode="report"` (already-supported `Literal["enforce", "report"]` on `Settings`, no new gate logic needed). Produce a committed findings document, `24-GATE-REVIEW-FINDINGS.md` in the phase directory, containing: the report-only run's rejection count/rate, a sample of rejected chunks that look domain-specific and short/structured (permission scopes, tool identifiers, protocol names, CVSS-style scores), an explicit judgment on whether healthcare-tuned heuristics are wrongly dropping them, and a handoff note pointing at Phase 26 as the phase that will actually author the fix (a domain-level Quality Contract rule / normative allowlist).
  Rationale: this is success criterion 3, verbatim — "documents whether... is being wrongly dropped," not "fixes it." Matches the discipline Phase 19/20 established for healthcare (report-only first, human review before any gate change) and the explicit warning sign PITFALLS.md calls out: "rejection-list review... skipped or done by whoever is available" — this decision names the artifact so the review is real and inspectable, not implicit.
  [auto] Recommended default selected — no interactive prompt.

### Dataset Project scoping

- **D-05 — Target lifecycle state: `ready`.** Create a Dataset Project scoped to `agent-security` and drive it through `draft → configured → sources_pending → ready` (all four transitions are legal per the existing `_TRANSITIONS` adjacency map in `pipeline/project.py`; none of them are gated on Quality Contract/Policy tables that don't exist until Phases 25/26 — that forward-reference is exactly what Phase 23's D-01 already established for spec fields). `ready` is the stronger, still-achievable target per the roadmap's "sources_pending/ready" wording, since nothing in the state machine blocks it.
  Rationale: gives Phases 25-31 the most-advanced starting state that's honestly achievable today, without inventing a workaround for the unfinished Policy/Quality Contract references (D-01 precedent from Phase 23 already covers the forward-reference this project's spec would need).
  [auto] Recommended default selected — no interactive prompt.

- **D-06 — Project purpose/intended/prohibited uses text.** `purpose`: "Proof dataset demonstrating governed, policy-evaluated, quality-validated dataset production for AI agent tool-use security and permission-scope corpora — the v2.7 milestone's flagship, non-healthcare proof (enables FLAGSHIP-01/02, formally satisfied at Phase 32)." `intended_uses`: RAG grounding for agent-security Q&A, safety/security research evaluation, instruction-tuning for agent guardrail behaviors. `prohibited_uses`: training or fine-tuning a model specifically to develop, automate, or optimize permission-escalation, prompt-injection, or tool-poisoning attacks — an explicit dual-use caveat given the domain's subject matter.
  Rationale: this domain is unusually dual-use (a corpus *about* attacks and permission bypass could itself be misused to train attack-capable behavior) — worth stating now even though the Policy engine that formally *enforces* intended-use restrictions doesn't land until Phase 25 (POLICY-04). Documents intent early rather than treating it as an afterthought.
  [auto] Recommended default selected — no interactive prompt.

- **D-07 — `dataset_type` value: `rag_corpus`.** This phase's ingestion only builds the RAG-corpus slice (parse→clean→chunk→enrich→embed→index); the instruction-tuning and protected-eval slices FLAGSHIP-01 ultimately requires come from Phase 28's candidate-generation lifecycle, layered on top of this same source corpus. `dataset_type` is a free-form string column (not an enum), so this is a starting value, not a schema lock.
  Rationale: matches what Phase 24 actually produces; avoids over-claiming a composite type before the mechanisms that produce the other slices exist.
  [auto] Recommended default selected — no interactive prompt.

### Claude's Discretion
- Exact `sources.yaml` entry count/order beyond the D-02 seed list, and any additional sources the planner/researcher finds during live URL verification.
- Exact validator class shape (`AgentSecurityValidator` in `validators/validate.py`) and prompt template content (`enrich.j2`, `qa_generation.j2`) beyond the D-03 taxonomy anchors — follows the healthcare/aviation pack precedent structurally.
- Whether the flagship Dataset Project's spec is authored via `klake dataset spec create` against a YAML file or hand-built — follows Phase 23's established D-03 convention (YAML authoring, canonical-JSON hash).
- Precise rejection-sample size and formatting in `24-GATE-REVIEW-FINDINGS.md` — planner/executor judgment, as long as it's a real, inspectable sample (not a summary claim without evidence).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/ROADMAP.md` §"Phase 24: Flagship Domain Pack Foundation" — Goal, Depends on, 4 Success Criteria, and the Note clarifying this phase *enables but does not satisfy* FLAGSHIP-01/02 (those complete at Phase 32)
- `.planning/ROADMAP.md` §"Scope decisions carried in from research" — "Phase 24 is scaffolded immediately after Phase 23... its domain-specific quality-gate tuning still waits on Phase 26 (Quality Contract) to exist" — the explicit scope boundary behind this phase's "Explicitly NOT in this phase" list above
- `.planning/REQUIREMENTS.md` §FLAGSHIP (FLAGSHIP-01, FLAGSHIP-02) — the requirements this phase's work ultimately serves (formally traced to Phase 32, not this phase, per the Traceability table)

### Research (architecture + pitfalls) — MOST important refs for this phase
- `.planning/research/PITFALLS.md` §"Pitfall 9" (lines 612-690) — the exact mechanics of the healthcare-only quality-gate-tuning gap, why `domains/aviation`/`domains/climate` already partially reproduce it, the `domains/local/` loader trap, and the prescribed report-only-first + human-review discipline. D-01/D-02/D-03/D-04 above implement this directly.
- `.planning/research/SUMMARY.md` (Phase 11 section, "Flagship non-healthcare domain pack") and lines 133-153 — phase rationale, delivery scope, and the explicit call-out that "report-only dry-run against real flagship sources is load-bearing here"
- `.planning/research/ARCHITECTURE.md` lines 263-264, 283, 289-291 — confirms no KL-16 fix is required (flagship pack runs through the existing generic `core_pipeline_e2e_job` + `DomainLoader.from_name()` runtime branch), and that `klake domain new` is the existing scaffolding command to use

### Existing code patterns to follow
- `src/knowledge_lake/domains/scaffold.py` — `scaffold_domain()` / `klake domain new <name>` generates a fully loadable pack skeleton (`domain.yaml`, `sources.yaml`, `taxonomy.yaml`, `prompts/{enrich,qa_generation}.j2`, `validators/{__init__,validate}.py`); default `--root domains` already produces a top-level, loadable pack (avoids the `domains/local/` trap by default)
- `src/knowledge_lake/domains/loader.py:173-210` (`DomainLoader.from_name()`) — confirms the hardcoded `domains/` path segment and the `_DOMAIN_NAME_RE` path-traversal guard
- `src/knowledge_lake/config/settings.py:326` — `gate_mode: Literal["enforce", "report"] = "enforce"` — the existing, already-built report-only toggle D-04 uses; no new gate code needed
- `src/knowledge_lake/pipeline/chunk.py:353,424,473` — where `gate_mode` is consumed; confirms report mode already logs rejections without dropping them
- `src/knowledge_lake/domains/models.py:70-104` (`DomainFilters`) and `domains/healthcare/filters.yaml` — the exact mechanism Phase 26 will extend for `agent-security`; Phase 24 does NOT author this file (see Phase Boundary), but the gate-review findings should reference these shapes when describing what's needed
- `src/knowledge_lake/pipeline/project.py:115-129` (`_TRANSITIONS`) — the 11-state adjacency map confirming `draft→configured→sources_pending→ready` are all legal, unguarded-by-missing-tables transitions
- `src/knowledge_lake/cli/app.py:1358-1372` (`cmd_init`) — `klake init --domain <name>` registers crawl-type sources from `sources.yaml`; upload-type sources are reported, not auto-registered
- `.planning/phases/23-dataset-project-specification-foundation/23-CONTEXT.md` D-01 (forward-reference precedent) and D-03 (YAML spec authoring + canonical-JSON hash convention) — directly reused by D-05/D-06/D-07 above and the Claude's Discretion spec-authoring note

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `pipeline/domains.py` (`load_domain()`) and `cli/app.py`'s `klake init --domain` — bulk-register a domain pack's crawl-type sources into the registry; same path healthcare used
- `klake crawl-all --domain agent-security` (existing batch-crawl command, CRAWL-02) — drives the actual parse→clean→chunk→enrich→embed→index pipeline run for success criterion 2, no new ingestion code needed
- `pipeline/quality_audit.py`'s `run_full_pipeline_audit()` / `klake quality-audit --full` (Phase 22) — directly reusable to produce the report-only rejection-rate measurement D-04 needs, scoped to `agent-security`'s freshly-produced chunk IDs (same dilution-avoidance discipline as Phase 22, D-04 there)
- `pipeline/project.py`'s `create_project()`, `create_spec_version()`, `transition_project()` (Phase 23) — directly reusable for D-05/D-06/D-07, no new state-machine code needed

### Established Patterns
- Domain pack convention over plugin entry-points (validated Phase 6, reaffirmed by aviation/climate stubs) — zero core code changes needed per new domain, `agent-security` follows the same `domains/<name>/` shape
- Report-only-before-enforce discipline (Phase 19/20 precedent) — this phase's D-04 is the same discipline applied to a new domain instead of a new gate
- Forward-reference-now/enforce-later for cross-phase dependencies (Phase 23 D-01) — reused here for the Dataset Project's spec references to not-yet-existing Policy/Quality Contract tables

### Integration Points
- New `domains/agent-security/` pack plugs into the exact same `DomainLoader.from_name()` runtime branch every existing asset (`assets.py:326,404,478`) already uses — set via `settings.domain.domain_name`, no Dagster code change
- Flagship Dataset Project links to the `agent-security` domain via the existing `domain` field on Dataset Project (PROJ-01) — same shape as any other project

</code_context>

<specifics>
## Specific Ideas

No user-provided specifics beyond the milestone brief's own naming ("AI Agent Security and Permission Dataset") — `--auto` mode ran with zero interactive prompts. All source/taxonomy/naming choices above are Claude's researched recommendations and should be treated as a starting point the user can override before `/gsd-plan-phase 24` runs.

</specifics>

<deferred>
## Deferred Ideas

- Authoring `domains/agent-security/filters.yaml` (the actual quality-gate fix) — explicitly deferred to Phase 26 (Quality Contract), per the Phase Boundary above. Not lost — D-04's findings document is the direct input Phase 26 will consume.
- Domain-pack-owned Dagster jobs/schedules (KL-16) — remains deferred tech debt; only becomes a hard prerequisite if a later phase proves the flagship pack needs a genuinely distinct Dagster schedule/sensor, not just parameterized asset behavior (per ARCHITECTURE.md).
- Formal Usage Policy decisions for the 8 seed sources — Phase 25's job, including whether any of them need the grandfather/backfill report-only treatment (they're new sources, not grandfathered legacy ones, so likely they go through Phase 25's live policy-decision path rather than the backfill path — a question for Phase 25's own discussion).

### Reviewed Todos (not folded)
None — no pending todos matched this phase (`todo.match-phase` returned 0 matches).

</deferred>

---

*Phase: 24-Flagship Domain Pack Foundation*
*Context gathered: 2026-07-21*
