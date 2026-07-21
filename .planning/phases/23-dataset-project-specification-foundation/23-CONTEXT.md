# Phase 23: Dataset Project + Specification Foundation - Context

**Gathered:** 2026-07-21
**Status:** Ready for planning
**Mode:** `--auto` — all gray areas auto-resolved with recommended defaults (no interactive prompts). Every choice below is logged with rationale so the user can override before planning.

<domain>
## Phase Boundary

This phase delivers the **foundation everything else in v2.7 scopes to**: a Dataset Project lifecycle state machine (11 states, guarded transitions), a versioned/hashed Dataset Specification, and the CLI/API/MCP surface convention (new `project` Typer group, thin MCP shims, shared Pydantic schemas) that every later phase will follow. It also closes Pitfall 2 — the `Dataset.name`/`export_finetune_dataset(name)` identity ambiguity — before any spec-version concept can reference it.

**Explicitly NOT in this phase** (deferred to later phases per roadmap ordering): Usage Policy engine (Phase 25), Quality Contract rule evaluation (Phase 26), CurationEngine/DataTrove (Phase 27), candidate validation (Phase 28), splits/contamination (Phase 29), Release/reproducibility (Phase 30), diff/lineage/eval (Phase 31), flagship release (Phase 32). Dataset Specification's schema references these concepts by field (per SPEC-01) but the *tables* they'd validate against don't exist until Phases 25/26 — see D-01 below.

</domain>

<decisions>
## Implementation Decisions

### D-01: Forward-referencing spec fields (quality_contract, policy) validate structurally now, referentially later
`klake dataset spec validate` (SPEC-03) must check "referenced sources/quality-contract/policy exist" — but `quality_contracts` and `policy_definitions` tables don't land until Phases 25/26. **Decision:** the Dataset Specification schema includes all SPEC-01 fields now (including `quality_contract_ref`, `policy_ref` as nullable free-form identifier strings), but `spec validate`'s referential-integrity check only enforces existence for references to tables that exist *today* (sources). References to quality-contract/policy are schema-validated (type/shape only) in Phase 23 and become referentially enforced in Phases 25/26 without a spec schema version bump (additive validation tightening, not a breaking schema change). Document this explicitly in the spec schema's field-level docstrings so Phase 25/26 planners know where to wire the stricter check in.
**Rationale:** Matches the codebase's existing precedent of shipping schema fields ahead of the subsystem that enforces them (e.g. `DomainFilters.thresholds` in Phase 19 — validated but intentionally unconsumed, reserved for a later phase). Keeps SPEC-02's "new immutable version on every change" contract from forcing a spec re-version when Phase 25/26 land.
**[auto] Recommended default selected — no interactive prompt.**

### D-02: `export_finetune_dataset(name)` legacy resolution rule
Per PITFALLS.md Pitfall 2 and Phase 23's own Success Criterion 5: the old 4-call-site signature `export_finetune_dataset(dataset_name, ...)` (CLI `cli/app.py:1280`, API `api/app.py:1242`, MCP `agent/registry.py:130`, Dagster `dagster_defs/assets.py:1018`) keeps working unchanged, but its resolution semantics become explicit and named instead of implicit row order. **Decision:** add one function, `get_latest_released_dataset_by_name(name)` (in `registry/repo.py`, alongside `get_dataset_by_name()`), with this exact rule: if the name resolves to a `Dataset` row associated (via new FK) with a Dataset Project, resolve to the `Dataset` tied to that project's spec version last transitioned into `released` state (highest `created_at` if more than one, which SHOULD NOT happen per PROJ-02's guarded transitions but the tiebreak is still pinned by a test); if the name has no associated Dataset Project (pre-v2.7 legacy dataset), fall back unchanged to today's `get_dataset_by_name()` behavior. All 4 call sites route through this one function in the same commit that adds project/spec versioning — never independently.
**Rationale:** This is the literal fix PITFALLS.md Pitfall 2 prescribes ("encode that resolution rule in one function... not as an implicit side effect of query ordering") and is directly tested by Success Criterion 5.
**[auto] Recommended default selected — no interactive prompt.**

### D-03: Dataset Specification input/storage format
SPEC-01 says "YAML/JSON". **Decision:** authoring format is YAML (matches every other Knowledge Lake config surface — `sources.yaml`, `domain.yaml`, `filters.yaml`); `klake dataset spec` CLI commands accept a YAML file path; on save, the parsed spec is stored as a JSON column (`dataset_specs.spec` or similar) for queryability, and the content hash (SPEC-02) is computed over a canonical JSON serialization (sorted keys, no whitespace variance) of the parsed spec — not over the raw YAML bytes — so re-indenting or reordering a YAML file doesn't spuriously produce a new version.
**Rationale:** Matches existing domain-pack YAML-authoring convention; hashing the canonical parsed form (not raw file bytes) avoids false-positive re-versioning from formatting-only edits, consistent with WR-05's existing content-hash discipline elsewhere in the pipeline.
**[auto] Recommended default selected — no interactive prompt.**

### D-04: Illegal transition error shape
PROJ-02 requires illegal transitions "rejected with a clear error naming the invalid transition." **Decision:** raise a dedicated `IllegalProjectTransitionError` (mirrors existing domain-specific exception precedent, e.g. `TrainEvalContaminationError`) carrying `from_state`, `to_state`, and the list of legal next states; CLI surfaces it as a clear error message and non-zero exit; API surfaces it as HTTP 409 Conflict with the same structured detail; MCP shim (if a `project transition` tool ships in this phase — see D-05) returns it as a tool error, not a silent no-op.
**Rationale:** Follows the project's established pattern of typed domain exceptions over generic `ValueError`, keeps CLI/API/MCP error surfaces consistent with each other per SURFACE-01/02.
**[auto] Recommended default selected — no interactive prompt.**

### D-05: MCP surface scope for this phase
SURFACE-03 explicitly says "read tools are prioritized over mutating ones per governance-action risk." **Decision:** this phase ships MCP read tools only — `project_list`, `project_show`, `spec_validate` (or equivalent thin shims) — and does NOT ship mutating MCP tools (`project_new`, `project_transition`, spec-edit) in Phase 23. Mutating governance actions stay CLI/API-only until a later phase's context establishes the human-approval-gate pattern the milestone brief calls for on Release. The `assert len(TOOLS) == N` count is bumped by exactly the number of new read tools added.
**Rationale:** Directly satisfies SURFACE-03's stated risk ordering without inventing new policy; avoids giving an LLM agent unsupervised project-lifecycle-mutation or spec-authoring capability before the milestone's policy/quality-contract layers (Phases 25-26) exist to bound what a "configured" or "ready" project even means.
**[auto] Recommended default selected — no interactive prompt.**

### Claude's Discretion
- Exact column/table naming within `dataset_projects`/`dataset_specs` (already anchored by ARCHITECTURE.md's `dpj_`/`dsp_` ID-prefix convention) — planner/executor follow existing ID-prefix and migration-numbering conventions (`0012_dataset_project_and_spec.py`).
- Internal shape of the 11-state lifecycle enum/transition table (which states are terminal, which allow which next-states) beyond what PROJECT.md's ordering already implies (draft → configured → sources_pending → ready → processing → validating → review_required → releasable → released → failed → archived) — planner encodes the graph, not re-litigated here since the milestone brief already fixes the state list and its written order.
- Whether `pipeline/project.py` is one file or splits state-machine logic from spec-versioning logic — ARCHITECTURE.md recommends one file mirroring `curate.py`'s shape; planner may split if the file grows unwieldy.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` §PROJ, §SPEC, §SURFACE (lines 116-127, 195-199) — locked requirement text (PROJ-01/02/03, SPEC-01/02/03, SURFACE-01/02/03) for this phase
- `.planning/ROADMAP.md` §"Phase 23: Dataset Project + Specification Foundation" — Goal, Depends on, Requirements, 6 Success Criteria (the acceptance bar for this phase)
- `.planning/ROADMAP.md` §"Scope decisions carried in from research" — the bullet "Phase 23 resolves the `Dataset.name` / `export_finetune_dataset()` versioning-identity break before anything else references a spec version" is this phase's explicit charter

### Research (architecture + pitfalls)
- `.planning/research/PITFALLS.md` §"Pitfall 2" (lines 96-146) — the exact `export_finetune_dataset` identity-break mechanics, the four call sites, and the prescribed fix (D-02 above implements this directly)
- `.planning/research/ARCHITECTURE.md` (Dataset Project / Dataset Specification sections, lines 37, 68, 89, 109, 194, 211, 220, 245, 270, 290) — confirms `dataset_projects` is a **new table**, distinct from the existing `Dataset` table ("`Dataset.name` uniqueness would collide with the 'many datasets per project over time' shape"); `pipeline/project.py` mirrors `curate.py`'s function shape (`create_project()`, `create_spec_version()`, `transition_project()`, deferred imports, `Settings`-driven); `dpj_`/`dsp_` ID prefixes; migration `0012_dataset_project_and_spec.py`; `project_app` CLI group naming
- `.planning/research/SUMMARY.md` (Phase 1 / ordering rationale) — Dataset Project + Spec is the first FK-dependency-chain phase; everything else scopes to it

### Existing code patterns to follow
- `src/knowledge_lake/cli/app.py:1569-1583` — `domain_app` sub-Typer group pattern (`typer.Typer(name=..., help=..., add_completion=False)` + `app.add_typer(domain_app, name="domain")`) — the exact pattern SURFACE-01 says to mirror for `project_app`
- `src/knowledge_lake/registry/models.py:566-601` — existing `Dataset`/`DatasetExample` models and their `UNIQUE(name)` constraint (`uq_datasets_name`) — the identity contract D-02 must preserve without breaking
- `src/knowledge_lake/agent/registry.py:246,375` — `TOOLS` list and the hardcoded `assert len(TOOLS) == 11` — must be bumped in the same commit per D-05

No other external specs/ADRs exist for this phase — REQUIREMENTS.md and ROADMAP.md fully capture scope.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `pipeline/curate.py` — the exact structural template for the new `pipeline/project.py`: function-shaped (not class-shaped), deferred imports at function scope (not module scope — avoids the registry.db/storage.s3 import-time cost the codebase consistently avoids), `Settings`-driven configuration
- `cli/app.py`'s `domain_app` sub-Typer group (lines 1569-1583) — template for the new `project_app` group; note the Rich-markup `[...]`-escaping gotcha (KL-13) already solved there for regex-pattern help text, relevant if the new project-name validation reuses a similar pattern
- `registry/repo.py:1351` (`get_dataset_by_name()`/`get_or_create_dataset()`) — existing identity-resolution functions that `get_latest_released_dataset_by_name()` (D-02) sits alongside, not replaces

### Established Patterns
- ID prefix convention: every new entity gets a short prefix + uuidv7 (`dpj_`, `dsp_` per ARCHITECTURE.md, matching existing `art_`, `dex_`, `src_` etc.) via the existing `new_id()` helper
- One small, reversible Alembic migration per phase (never a giant combined migration) — this phase's migration is `0012_dataset_project_and_spec.py`
- Governance/process tables (this phase's `dataset_projects`, `dataset_specs`) live in their own tables with FKs back into the lineage graph — never crammed into `Artifact.metadata_` JSON, per the anti-pattern this milestone specifically avoids (ARCHITECTURE.md line 182, 297)
- Typed domain exceptions over generic `ValueError` (e.g. `TrainEvalContaminationError` precedent) — D-04 follows this for `IllegalProjectTransitionError`

### Integration Points
- CLI: new `project_app` Typer group registered via `app.add_typer(project_app, name="project")`, mirroring `domain_app`
- API: new routes reusing shared Pydantic schemas, calling `pipeline/project.py` functions directly — no logic in route handlers (SURFACE-02)
- MCP: read-only thin shims added to `agent/registry.py`'s `TOOLS` list (D-05); assertion count bumped in the same commit
- Dagster: `dagster_defs/assets.py:1018` and `definitions.py:45,85` are two of the four `export_finetune_dataset` call sites D-02 must update

</code_context>

<specifics>
## Specific Ideas

No specific UI/UX preferences were expressed — this is a backend/CLI/API/MCP governance phase with no frontend surface. The "specific idea" driving this phase's shape is entirely the milestone brief's own target-feature list and the research's Pitfall 2 fix, both already captured in the Decisions above.

</specifics>

<deferred>
## Deferred Ideas

- **Referential enforcement of quality_contract/policy spec fields** — belongs to Phases 25 (Policy) and 26 (Quality Contract) respectively; Phase 23 only schema-validates these fields (D-01).
- **Human-approval-gate pattern for mutating governance actions** — the milestone brief implies this matters most for Release (Phase 30); Phase 23 defers all mutating MCP tooling rather than half-implementing an approval gate now (D-05).
- **KL-16 (domain-pack-owned Dagster jobs)** — explicitly deferred per REQUIREMENTS.md's DOMAIN-07 and STATE.md's carried-forward tech debt; not touched by this phase.

### Reviewed Todos (not folded)
None — `todo.match-phase 23` returned zero matches.

</deferred>

---

*Phase: 23-Dataset Project + Specification Foundation*
*Context gathered: 2026-07-21*
