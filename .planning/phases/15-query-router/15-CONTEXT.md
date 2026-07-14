# Phase 15: Query Router - Context

**Gathered:** 2026-07-14
**Status:** Ready for planning

> Captured in `--auto` mode: all gray areas auto-resolved to the recommended
> (conservative-first, additive-surface, single-Pydantic-source) option.
> Decisions are logged in `15-DISCUSSION-LOG.md`. Review before planning if
> any default is wrong.

<domain>
## Phase Boundary

Deliver a **query router** that dispatches each search to exactly one
retrieval path — the existing chunk search (`pipeline/search.py:search()`)
or the existing two-stage tree search (`pipeline/tree_search.py:tree_search()`,
built in Phase 14) — based on an explicit `route` value or a conservative
heuristic classifier when `route="auto"` (ROUTE-01..04).

- **Explicit routes are an operator override:** `route="chunk"` always calls
  `search()`; `route="tree"` and `route="two_stage"` are **aliases** that both
  call `tree_search()` (Phase 14 shipped only one tree path, and it is
  inherently two-stage — there is no separate "tree without shortlist" mode
  to dispatch to).
- **`route="auto"` (the default) runs a narrow, regex-only heuristic** over
  the query text — section/page references, comparison/multi-hop phrasing,
  and outline/breadth requests upgrade to the tree path; everything else gets
  chunk search (ROUTE-02, ROUTE-03). No LLM classification this phase
  (ROUTE-05 is explicitly deferred).
- **Surfaces are extended, not duplicated:** the existing `/search` API
  endpoint, `klake search` CLI command, and MCP `search` tool each gain a new
  `route` parameter alongside the existing `mode` (hybrid/dense/sparse)
  parameter — no new endpoints/commands/tools (ROUTE-04, matches the
  requirement text literally).

**In scope:** new `pipeline/route.py:routed_search()` orchestrator; narrow
heuristic classifier (regex, deterministic, zero LLM/network cost); `route`
param added to `SearchParams` (the single Pydantic schema shared by
API/MCP/OpenAPI/OpenAI per the existing no-drift convention) and to the CLI
`search` command; a `RouterSettings`-style config submodel; structlog
routing-decision logging (route chosen + reason) so the "no labeled query
dataset yet" gap (STATE.md blocker) can be tuned from production logs later;
graceful auto-mode fallback from tree back to chunk when the tree path yields
zero hits.

**Out of scope (later phases / deferred):** merged/deduped **combination**
of chunk+tree results in a single response (a "both" path) — despite being
sketched in `.planning/research/ARCHITECTURE.md`/`FEATURES.md` and mentioned
as "deferred to Phase 15" in `14-CONTEXT.md`, the **locked** ROUTE-01..04
requirements only cover single-path dispatch; there is no MERGE requirement
in REQUIREMENTS.md. LLM-based routing/classification and routing telemetry
feedback loops (ROUTE-05/06, Future Requirements). OpenKB wiki (Phase 16).

</domain>

<decisions>
## Implementation Decisions

### Route values — `tree` and `two_stage` are aliases for the one tree path
- **D-01:** The `route` parameter accepts exactly the four literal values in
  ROUTE-01: `chunk | tree | two_stage | auto`. Because Phase 14 built only
  one tree-retrieval function (`tree_search()`, which is Qdrant-shortlist +
  per-doc traversal by construction — see Phase-14 D-08), `tree` and
  `two_stage` are **synonyms**: both dispatch to `tree_search()` unchanged.
  No new "tree-only, no-shortlist" implementation is built to justify a
  behavioral difference between the two names.

### New orchestrator, existing pipeline functions untouched
- **D-02:** Add `pipeline/route.py:routed_search()` as the new unified entry
  point. `pipeline/search.py:search()` and `pipeline/tree_search.py:tree_search()`
  are **not modified** — `routed_search()` calls one or the other based on
  the resolved route (additive-only convention, mirrors every prior phase's
  "new function, not modified function" pattern; see
  `.planning/research/PITFALLS.md` router section).
- **D-03:** CLI `search` command, `/search` API endpoint, and the MCP
  `search` tool are updated **in place** to call `routed_search()` instead of
  calling `search()` directly, and each gains the new `route` parameter
  (ROUTE-04 explicitly says "alongside existing mode parameter" on the
  **existing** surfaces — not new endpoints). `mode` keeps its current
  meaning (hybrid/dense/sparse, stage-1/chunk retrieval mode) unchanged;
  `route` is the new, orthogonal path-selection parameter.

### Heuristic classifier — narrow and regex-only (deterministic-first)
- **D-04:** `route="auto"` heuristics only ever *upgrade* to the tree path;
  they never downgrade an explicit request. Trigger categories (all
  case-insensitive regex, no LLM, no embeddings):
  - Section/page references: `section \d`, `§`, `page[s]? \d`, `chapter \d`
  - Comparison / multi-hop phrasing: `compare`, `difference between`,
    `vs\.?|versus`, `how does .+ (affect|relate to|impact)`
  - Structural/breadth requests: `outline of`, `table of contents`,
    `all sections`, `summarize (the|all)`
  Any match → route to the tree path; no match → chunk (ROUTE-02, ROUTE-03).
  Matches the STATE.md blocker's own plan ("start conservative, tune with
  production data") and `PITFALLS.md`'s explicit recommendation to keep
  initial triggers narrow.

### Fallback semantics — operator override is literal; auto is forgiving
- **D-05:** Explicit `route` values (`chunk`/`tree`/`two_stage`) are honored
  literally — no automatic fallback, even if that path returns zero hits
  (operator override, per `.planning/research/ARCHITECTURE.md` §6). Under
  `route="auto"`, if the heuristic upgrades to the tree path and
  `tree_search()` returns **zero** Hits, `routed_search()` falls back to a
  chunk-search call and returns those results instead — never silently
  returns empty when chunk search could have helped
  (`.planning/research/PITFALLS.md`: "verify what happens when BOTH fail").
  If chunk search *also* returns zero hits, return an empty list (not an
  error) — matches existing `search()` empty-result behavior.

### Observability
- **D-06:** Every `routed_search()` call emits one structlog event recording
  the chosen route, the matched trigger category (or `"operator_override"` /
  `"no_match"`), and whether an auto-fallback occurred. This is the concrete
  mechanism for tuning the heuristic later, per the STATE.md Phase-15
  blocker ("no labeled query dataset ... tune with production data").

### Config surface
- **D-07:** Add a small settings submodel (e.g. `RouterSettings`) to
  `config/settings.py`, mirroring `SearchSettings`/`TreeSearchSettings`:
  `default_route: Literal["chunk","tree","two_stage","auto"] = "auto"`. Env
  override via the existing `KLAKE_<SECTION>__<FIELD>` nested-delimiter
  convention. Per-call `route` (CLI flag / API query param / MCP field)
  overrides the settings default — identical precedence to the existing
  `mode` parameter (RETR-03 pattern).
- **D-08:** Add `route` to `SearchParams` (`api/schemas.py`) — the single
  Pydantic schema already shared by the API handler, MCP tool, OpenAPI
  export, and OpenAI tool defs (SKILL-03 no-drift rule) — so all four
  surfaces stay in lockstep automatically, exactly as the `mode` field did
  in Phase 10.

### Scope guard
- **D-09:** The chunk+tree **merge/"both"** path is explicitly **not** built
  this phase (see Phase Boundary "Out of scope"), even though
  `14-CONTEXT.md`'s Deferred Ideas section named it as coming "to Phase 15."
  REQUIREMENTS.md's locked ROUTE-01..04 only specify single-path dispatch;
  building a merge path here would be scope creep beyond the roadmap
  boundary. Carried forward as a deferred idea below.

### Claude's Discretion
- Exact regex pattern list wording/ordering, the router module's exact
  filename (`pipeline/route.py` vs `routing.py`), the structlog event name,
  and the `RouterSettings` field name (`default_route` vs `route`) are left
  to planner/executor, provided the D-01/D-04/D-05 contracts stay stable.
- Whether the heuristic classifier lives as a standalone function
  (`classify_route(query) -> RouteDecision`) or inline in `routed_search()`
  — executor's choice, provided routing decisions are logged per D-06.
- **Executor model:** sub-agent executors run on `sonnet` (already pinned via
  `model_overrides.gsd-executor` in `.planning/config.json` — no plan task).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### v2.5 project research (read first — this phase is a documented design)
- `.planning/research/ARCHITECTURE.md` §6 "Query Router Dispatch Mechanism"
  (lines ~306-370) — `RouteDecision`/`QueryRouter` sketch, config-driven
  default + heuristic override design. Note D-01: `tree`/`two_stage` collapse
  to one dispatch target, overriding any implied distinction in the sketch.
- `.planning/research/PITFALLS.md` — router-misclassification section
  (~lines 60-90: narrow triggers, log routing decisions, default to chunk);
  additive-surface section (~lines 185-215: new function not modified
  function); citation/lineage dedup note (~lines 247-271, not applicable
  since D-09 defers merge); "both fail" gap (~line 331); rollback lever
  (~line 347: `default_route="chunk"` env var reverts instantly).
- `.planning/research/FEATURES.md` — query router feature table (~lines
  58-90: conservative heuristic list, "both paths coexist" framing) and
  phase ordering (~lines 125-146).
- `.planning/research/STACK.md` — `RouterSettings` sketch (~lines 319-359,
  env var names) and the routing pipeline ASCII diagram (~lines 125-137).
- `.planning/research/SUMMARY.md` — Phase 3/Query Router synthesis
  (~lines 88-120).

### Requirements & roadmap
- `.planning/ROADMAP.md` § "Phase 15: Query Router" — goal + 4 success criteria.
- `.planning/REQUIREMENTS.md` § "Query Routing" — ROUTE-01…ROUTE-04 (locked);
  "Enhanced Routing" Future Requirements — ROUTE-05/06 (explicitly deferred,
  do not build).

### Upstream contracts this phase consumes (Phases 13-14)
- `.planning/phases/14-tree-retrieval/14-CONTEXT.md` — D-01/D-02 (`Hit` +
  `citation_source` discriminator this phase must preserve untouched), D-13
  (Phase 14 kept surface exposure to a thin CLI wrapper only — this phase is
  where the full CLI/API/MCP surface lands), Deferred Ideas (names the
  merge/"both" path — see D-09 for why it's still out of scope).
- `.planning/phases/13-tree-index-foundation/13-CONTEXT.md` — background only;
  no direct dependency for routing logic.

### Source files to mirror / integrate (existing patterns)
- `src/knowledge_lake/pipeline/search.py` — chunk path; called by
  `routed_search()` unchanged.
- `src/knowledge_lake/pipeline/tree_search.py` — `tree_search()`, the target
  for both `tree` and `two_stage` routes; note its module docstring already
  anticipates a router caller (CR-02: a future async caller should await
  `_load_all()` directly rather than call `tree_search()` from a running
  event loop — relevant if `routed_search()` is ever made async).
- `src/knowledge_lake/config/settings.py` — `SearchSettings` (~L404) and
  `TreeSearchSettings` (~L223) as the template for the new router settings
  submodel + env-var precedence pattern (D-07).
- `src/knowledge_lake/api/schemas.py` — `SearchParams` (~L31) — add `route`
  here, the single schema source for API/MCP/OpenAPI/OpenAI parity (D-08).
- `src/knowledge_lake/api/app.py` — `search_endpoint` (~L161) — existing
  `mode` Query pattern-validation (`^(hybrid|dense|sparse)$`) is the template
  for a matching `route` Query validator (`^(chunk|tree|two_stage|auto)$`).
- `src/knowledge_lake/cli/app.py` — `cmd_search` (~L633, existing `--mode`
  flag + `VALID_MODES` guard) and `cmd_tree_search` (~L735) — `cmd_search`
  gains `--route`; both existing commands stay callable directly.
- `src/knowledge_lake/agent/registry.py` — `TOOLS` list, `search` `ToolDef`
  (~L242), `SearchParams` input model — `route` flows through automatically
  once added to the shared schema (D-08).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`pipeline/search.py:search()`** — chunk path, called as-is by
  `routed_search()` for `route="chunk"` and as the auto-fallback (D-05).
- **`pipeline/tree_search.py:tree_search()`** — the one and only tree path;
  called as-is for `route="tree"`/`route="two_stage"` (D-01).
- **`SearchSettings`/`TreeSearchSettings`** — direct templates for the new
  router settings submodel (Literal constraint, env-var precedence, D-07).
- **`SearchParams`** (`api/schemas.py`) — already the single schema shared by
  API handler + MCP tool + OpenAPI + OpenAI defs; adding `route` here is the
  proven way to get 4-surface parity for free (D-08), exactly like Phase 10's
  `mode` field did.
- **Existing `mode` Query-pattern validator** in `search_endpoint` — direct
  template for a `route` validator with the same fail-closed 422 behavior.

### Established Patterns
- **Per-request override wins over settings default** — established by
  `search()`'s `mode` resolution (`effective_mode = mode or s.search.mode`);
  `routed_search()`'s `route` resolution follows the identical shape.
- **Additive-only, new-function convention** — every prior phase (13, 14)
  added new pipeline modules/functions rather than modifying existing ones;
  `pipeline/route.py` continues this for Phase 15.
- **Single Pydantic schema source for surface parity** — proven in v2.0
  (MCP-01..03) and reused verbatim for `route` (D-08).
- **Deterministic-first constraint** — regex heuristic before any LLM
  classification (ROUTE-05 explicitly deferred), same ordering as Phase 13's
  deterministic-before-LLM tree builder and Phase 14's heuristic-before-LLM
  traversal.

### Integration Points
- New module `src/knowledge_lake/pipeline/route.py` (`routed_search()` +
  the heuristic classifier).
- `route` field added to `api/schemas.py:SearchParams`.
- `search_endpoint` (`api/app.py`), `cmd_search` (`cli/app.py`), and the
  `search` `ToolDef` handler (`agent/registry.py`) updated to call
  `routed_search()` and accept `route`.
- New router settings submodel + `router` (or similarly named) section in
  `config/settings.py:Settings`.
- **Zero Alembic migrations** — no schema change; routing is a dispatch
  layer over existing search functions.

</code_context>

<specifics>
## Specific Ideas

- Keep the rollback lever cheap: since `default_route` is just a settings
  field, an operator can revert the whole system to chunk-only behavior via
  one env var (`KLAKE_ROUTER__DEFAULT_ROUTE=chunk` or equivalent) with zero
  code change if the heuristic misbehaves in production
  (`.planning/research/PITFALLS.md` ~line 347).
- The router must never make `route="chunk"` (today's only behavior) slower
  or different for existing callers who don't pass `route` at all and whose
  queries don't match any heuristic trigger — auto-mode's "no match" path is
  chunk search, unchanged.

</specifics>

<deferred>
## Deferred Ideas

- **Merged/"both" chunk+tree result path (dedup + re-rank)** — named in
  `ARCHITECTURE.md`/`FEATURES.md` research and in `14-CONTEXT.md`'s Deferred
  Ideas as "coming to Phase 15," but the locked ROUTE-01..04 requirements
  don't include it (see D-09). Candidate for a future release once there's a
  concrete need for combined results.
- **LLM-based routing for ambiguous queries; routing telemetry/feedback
  loop** — ROUTE-05/06, deferred to future release (REQUIREMENTS.md Future
  Requirements).
- **OpenKB wiki export** — Phase 16 (KB-01…05), independent of this phase.
- **Corpus-level meta-tree navigation (PageIndex File System, TREE-07)** —
  v2.6+.

### Reviewed Todos (not folded)
None — `todo.match-phase 15` returned zero matches.

</deferred>

---

*Phase: 15-query-router*
*Context gathered: 2026-07-14*
