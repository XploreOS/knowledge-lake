# Phase 15: Query Router - Research

**Researched:** 2026-07-14
**Domain:** Deterministic query dispatch / retrieval routing (backend, zero-LLM)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** `route` accepts exactly `chunk | tree | two_stage | auto`. `tree` and
  `two_stage` are **synonyms** — both dispatch to the existing `tree_search()`
  unchanged. No new "tree-only, no-shortlist" implementation.
- **D-02:** Add `pipeline/route.py:routed_search()` as the new unified entry point.
  `pipeline/search.py:search()` and `pipeline/tree_search.py:tree_search()` are
  **not modified** (additive-only convention).
- **D-03:** CLI `search`, `/search` API endpoint, and MCP `search` tool are updated
  **in place** to call `routed_search()` and each gains the new `route` parameter
  alongside the existing `mode` param (hybrid/dense/sparse — unchanged meaning). No
  new endpoints/commands/tools.
- **D-04:** `route="auto"` heuristics only ever *upgrade* to the tree path; never
  downgrade an explicit request. Case-insensitive regex only — no LLM, no embeddings.
  Trigger categories: section/page refs (`section \d`, `§`, `page[s]? \d`,
  `chapter \d`); comparison/multi-hop (`compare`, `difference between`,
  `vs\.?|versus`, `how does .+ (affect|relate to|impact)`); structural/breadth
  (`outline of`, `table of contents`, `all sections`, `summarize (the|all)`).
  Any match → tree path; no match → chunk.
- **D-05:** Explicit routes (`chunk`/`tree`/`two_stage`) are honored literally — no
  automatic fallback even on zero hits (operator override). Under `route="auto"`, if
  the heuristic upgrades to the tree path and `tree_search()` returns **zero** Hits,
  fall back to a chunk-search call and return those results. If chunk search also
  returns zero, return an empty list (not an error) — mirrors `search()` behavior.
- **D-06:** Every `routed_search()` call emits one structlog event: chosen route,
  matched trigger category (or `"operator_override"` / `"no_match"`), and whether an
  auto-fallback occurred.
- **D-07:** Add a `RouterSettings`-style submodel to `config/settings.py`:
  `default_route: Literal["chunk","tree","two_stage","auto"] = "auto"`. Env override
  via `KLAKE_<SECTION>__<FIELD>`. Per-call `route` overrides the settings default —
  identical precedence to the existing `mode` param.
- **D-08:** Add `route` to `SearchParams` (`api/schemas.py`) — the shared schema for
  MCP tool inputSchema + OpenAI tool defs — so those surfaces stay in lockstep.
- **D-09:** The chunk+tree **merge/"both"** path is explicitly **NOT** built this
  phase. ROUTE-01..04 only specify single-path dispatch. Carried forward as deferred.

### Claude's Discretion
- Exact regex pattern wording/ordering; router module filename (`pipeline/route.py`
  vs `routing.py`); the structlog event name; the `RouterSettings` field name
  (`default_route` vs `route`) — provided the D-01/D-04/D-05 contracts stay stable.
- Whether the classifier is a standalone function
  (`classify_route(query) -> RouteDecision`) or inline in `routed_search()` —
  executor's choice, provided routing decisions are logged per D-06.
- **Executor model:** sub-agent executors run on `sonnet` (already pinned via
  `model_overrides.gsd-executor` in `.planning/config.json` — no plan task).

### Deferred Ideas (OUT OF SCOPE)
- **Merged/"both" chunk+tree result path (dedup + re-rank)** — deferred (D-09).
- **LLM-based routing (ROUTE-05); routing telemetry/feedback loop (ROUTE-06)** —
  Future Requirements, do not build.
- **OpenKB wiki export** — Phase 16.
- **Corpus-level meta-tree navigation (PageIndex File System, TREE-07)** — v2.6+.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ROUTE-01 | Search mode configurable as `chunk\|tree\|two_stage\|auto` via settings, CLI flag, and API parameter | `RouterSettings.default_route` Literal (D-07, mirrors `SearchSettings.mode`); `--route` CLI flag on `cmd_search`; `route` Query param on `search_endpoint`; `route` field on `SearchParams` (D-08). All four resolve via the `route or settings.router.default_route` precedence pattern established by `search()`'s `effective_mode = mode or s.search.mode`. |
| ROUTE-02 | Heuristic router detects structural/multi-hop queries and upgrades to tree search | Standalone regex classifier (D-04) — three case-insensitive trigger categories; any match → dispatch to existing `tree_search()`. Zero LLM / zero network (deterministic-first constraint). |
| ROUTE-03 | Auto mode defaults to chunk search when no structural signals detected (conservative) | Classifier returns `chunk` on no-match; `routed_search()` calls `search()` unchanged. PITFALLS.md Pitfall 3: "default to chunk; tree is the UPGRADE path." |
| ROUTE-04 | MCP tools and API endpoints expose `route` alongside existing `mode` param | `route` added to `SearchParams` (MCP inputSchema + OpenAI defs, D-08) + `_search_handler` shim signature; separate `route` Query param on the REST `/search` endpoint (it does NOT consume `SearchParams` — see Pitfall 1). `mode` retained unchanged. |
</phase_requirements>

## Summary

This phase adds a thin, deterministic **dispatch layer** over two retrieval
functions that already exist and are frozen by contract: `pipeline/search.py:search()`
(chunk) and `pipeline/tree_search.py:tree_search()` (two-stage tree, Phase 14). No
new retrieval algorithm is built. The work is: (1) a regex classifier that decides
`chunk` vs `tree` for `route="auto"`, (2) a `routed_search()` orchestrator that
resolves the effective route, dispatches, and applies the auto-mode zero-hit
fallback, (3) a `RouterSettings` config submodel, and (4) threading a new `route`
parameter through the four existing surfaces (CLI / REST / MCP / OpenAI defs).

The dominant risk is **not** the routing logic (which is trivial and fully specified
by D-01/D-04/D-05) — it is **surface plumbing correctness**. The "single Pydantic
schema" story is only partially true in this codebase: the MCP tool and OpenAI defs
derive from `SearchParams`, but the FastAPI `/search` endpoint declares its params as
individual `Query()` arguments and does **not** consume `SearchParams`. So `route`
must be added in *both* places, plus the `_search_handler` shim signature, plus the
CLI. Adding a Query param also mutates the committed `docs/openapi.json`, which a
byte-identical deterministic-dump test guards — that file must be regenerated.

**Primary recommendation:** Build `routed_search()` as a **synchronous** function
(never async — see Pitfall 2), with a standalone `classify_route(query) -> str`
regex classifier. Add `route` to four surfaces (`SearchParams` + `_search_handler`,
`search_endpoint` Query param, `cmd_search` `--route` flag) and regenerate
`docs/openapi.json`. Validate with table-driven unit tests over the classifier and
the fallback branches — no integration infra needed.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Route classification (regex) | API/Backend (`pipeline/route.py`) | — | Pure business logic; deterministic, no I/O. Belongs beside the pipeline functions it dispatches to. |
| Route dispatch + fallback orchestration | API/Backend (`pipeline/route.py`) | — | Orchestrator owns the "which path + fallback" decision; mirrors `tree_search()` orchestrating `search()`. |
| `route` config default | Config (`config/settings.py`) | — | Settings submodel + env-var precedence, identical to `SearchSettings`/`TreeSearchSettings`. |
| `route` param validation (fail-closed) | API boundary (REST `Query` pattern + Pydantic `SearchParams`) | CLI `VALID_ROUTES` guard | ASVS V5 input validation at each surface, mirroring the existing `mode` validators. |
| `route` surface exposure | API/Backend surfaces (REST/CLI/MCP/OpenAI) | — | Additive param on existing surfaces; no new endpoints (ROUTE-04). |

## Standard Stack

**No new external packages.** This phase uses only the Python standard library
`re` module plus dependencies already in the project (`structlog`, `pydantic`,
`typer`, `fastapi`). The deterministic-first constraint (regex before LLM) is fully
satisfied by `re`. `[VERIFIED: codebase — search.py/tree_search.py/settings.py all
use only these already-present deps]`

### Core (existing, reused unchanged)
| Component | Location | Purpose | Why Standard |
|-----------|----------|---------|--------------|
| `search()` | `pipeline/search.py` | Chunk path — called for `route="chunk"` and as auto-fallback | Frozen by D-02; already the Phase-14 stage-1 caller |
| `tree_search()` | `pipeline/tree_search.py` | Tree path — called for `route="tree"`/`"two_stage"` | Frozen by D-02; the one and only tree path (D-01) |
| `SearchSettings`/`TreeSearchSettings` | `config/settings.py` (~L404 / ~L223) | Template for `RouterSettings` (Literal field + env-var precedence) | Direct pattern to copy (D-07) |
| `SearchParams` | `api/schemas.py` (~L31) | Shared schema for MCP inputSchema + OpenAI defs | `route` added here (D-08) |
| `re` (stdlib) | — | Case-insensitive trigger matching | Zero-cost, deterministic (ROUTE-02) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `RouteDecision` Enum (ARCHITECTURE.md §6 sketch) | Plain `str` literals | The codebase convention is `Literal[...]` string fields (`mode`, tree `mode`), not Enums. `Hit`/`TreeHit` precedent (Phase 14 dropped `TreeHit`, reused `Hit`) shows the project prefers reusing plain types over new wrapper types. Prefer `str` literals + `Literal` validation over a new Enum. `[ASSUMED — style inference, planner's discretion per D-01 note]` |
| `both`/`BOTH` route value (ARCHITECTURE.md/STACK.md sketches) | — | **Explicitly excluded by D-09.** The `RouterSettings` sketch in STACK.md (~L319) uses different field names (`strategy`, `auto_classifier`, `two_stage`) that pre-date the locked D-07 contract — **do not copy it verbatim**; follow D-07's `default_route` Literal. |

**Installation:** None. No `uv add` / `pip install` step in this phase.

## Package Legitimacy Audit

> Not applicable — this phase installs **zero** external packages. All code uses the
> Python standard library (`re`) plus dependencies already pinned in the project.

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                         route param (per-call override)
   CLI --route ─────┐        REST ?route= ─────┐       MCP/OpenAI route field ─────┐
        │           │             │            │              │ (SearchParams)     │
        └───────────┴─────────────┴────────────┴──────────────┴────────────────────┘
                                        │
                                        ▼
                        ┌─────────────────────────────────┐
                        │   pipeline/route.py              │
                        │   routed_search(query, route=…)  │
                        │                                  │
                        │  1. effective_route =            │
                        │     route or settings.router     │
                        │            .default_route        │
                        └───────────────┬──────────────────┘
                                        │
              ┌──────── effective_route == "auto"? ────────┐
              │ yes                                        │ no (explicit override, D-05)
              ▼                                            │
   ┌──────────────────────┐                                │
   │ classify_route(query) │  regex, zero-cost             │
   │  → "chunk" | "tree"   │                               │
   └──────────┬───────────┘                                │
              │                                             │
      ┌───────┴───────┐                          ┌──────────┴───────────┐
      │ "tree"        │ "chunk"                  │ "chunk"    "tree"/"two_stage"
      ▼               ▼                          ▼                      ▼
 tree_search()    search()                   search()             tree_search()
      │                                                                 │
   zero hits? ──yes──► search()  (auto-fallback, D-05)              (no fallback, D-05)
      │ no                    │
      ▼                       ▼
   return Hits            return Hits (or [] if both empty)
              │
              ▼
     structlog event: {route, trigger_category, fallback_used}  (D-06)
```

*File-to-implementation mapping is in the Component Responsibilities table below,
not in the diagram.*

### Component Responsibilities
| File | Change | Detail |
|------|--------|--------|
| `pipeline/route.py` (NEW) | `routed_search()` + `classify_route()` | Sync function; resolves route, dispatches, applies auto-fallback (D-05), logs (D-06). |
| `config/settings.py` | Add `RouterSettings` submodel + wire into `Settings` | New class near `SearchSettings` (~L404); add `router: RouterSettings = Field(default_factory=RouterSettings)` in the `Settings` body (~L546, beside `search:`). |
| `api/schemas.py` | Add `route` field to `SearchParams` (~L62, beside `mode`) | `str \| None`, `pattern=r"^(chunk\|tree\|two_stage\|auto)$"`, default `None`. Feeds MCP inputSchema + OpenAI defs. |
| `agent/registry.py` | Add `route` kwarg to `_search_handler` (~L140) + call `routed_search()` | The MCP server does `model.model_dump(exclude_none=True)` → `fn(**kwargs)`, so an unexpected `route` kwarg raises `TypeError` unless the shim signature accepts it. |
| `api/app.py` | Add `route` Query param to `search_endpoint` (~L210, beside `mode`) + call `routed_search()` | REST endpoint uses explicit `Query()` args — NOT `SearchParams`. Mirror the `mode` pattern validator: `pattern=r"^(chunk\|tree\|two_stage\|auto)$"` → fail-closed 422. |
| `cli/app.py` | Add `--route` Option to `cmd_search` (~L661, beside `--mode`) + `VALID_ROUTES` guard + call `routed_search()` | Mirror the `VALID_MODES` guard block (~L682); `raise typer.Exit(1)` on invalid value. |
| `docs/openapi.json` | Regenerate via `klake openapi` | Adding the REST `route` Query param mutates the schema; a byte-identical test guards it (Pitfall 3). |

### Pattern 1: Per-call override wins over settings default
**What:** `effective_route = route or settings.router.default_route`.
**When to use:** In `routed_search()`, exactly once at the top.
**Example:**
```python
# Source: pipeline/search.py:97 (existing, verbatim precedent)
effective_mode = mode or s.search.mode
# routed_search() mirror:
s = settings or get_settings()
effective_route = route or s.router.default_route
```
`[VERIFIED: codebase — pipeline/search.py:97]`

### Pattern 2: Fail-closed Literal/pattern validation at every surface
**What:** Each surface validates `route` against the four-value set before dispatch.
**Where:** REST → `Query(pattern=r"^(chunk|tree|two_stage|auto)$")` (auto-422);
Pydantic → `SearchParams.route` field `pattern=...`; CLI → explicit `VALID_ROUTES`
set guard; Config → `Literal[...]` on the settings field (raises `ValidationError`
at load time).
**Example:**
```python
# Source: api/app.py:210-220 (existing mode validator — copy the shape)
mode: str | None = Query(default=None, pattern=r"^(hybrid|dense|sparse)$", ...)
# new, alongside it:
route: str | None = Query(default=None, pattern=r"^(chunk|tree|two_stage|auto)$", ...)
```
`[VERIFIED: codebase — api/app.py:210, cli/app.py:682, settings.py:415]`

### Pattern 3: Regex classifier (deterministic-first, upgrade-only)
**What:** `classify_route(query) -> ("chunk"|"tree", trigger_category)` — returns the
matched category name for D-06 logging, or `"no_match"`.
**Example (shape only — exact patterns are planner's discretion per D-04):**
```python
import re
# case-insensitive, compiled once at module level
_TREE_TRIGGERS: list[tuple[str, re.Pattern[str]]] = [
    ("section_page_ref", re.compile(r"\bsection\s+\d|§|\bpages?\s+\d|\bchapter\s+\d", re.I)),
    ("comparison_multihop", re.compile(r"\bcompare\b|\bdifference between\b|\bvs\.?\b|\bversus\b|\bhow does .+ (affect|relate to|impact)\b", re.I)),
    ("structural_breadth", re.compile(r"\boutline of\b|\btable of contents\b|\ball sections\b|\bsummarize (the|all)\b", re.I)),
]
def classify_route(query: str) -> tuple[str, str]:
    for category, pat in _TREE_TRIGGERS:
        if pat.search(query):
            return "tree", category
    return "chunk", "no_match"
```
`[CITED: CONTEXT.md D-04 + PITFALLS.md Pitfall 3]`

### Anti-Patterns to Avoid
- **Making `routed_search()` async.** `tree_search()` raises `RuntimeError` if called
  from within a running event loop (it does `asyncio.run(_load_all(...))` internally
  and guards against nesting — see `tree_search.py:230-239`). Keep `routed_search()`
  sync so it can call `tree_search()` directly. (Pitfall 2.)
- **Downgrading explicit routes.** D-04/D-05: heuristics only *upgrade*; an explicit
  `route="chunk"` must never be re-routed, and an explicit `route="tree"` must never
  auto-fall-back to chunk.
- **Modifying `search()` or `tree_search()`.** D-02: additive only. `routed_search()`
  wraps; it never edits the callees.
- **Copying the STACK.md `RouterSettings` sketch verbatim.** Its `strategy`/
  `auto_classifier`/`two_stage` field names pre-date the locked D-07 contract
  (`default_route` Literal). Follow D-07, not the sketch.
- **Adding a `both`/merge path.** D-09 — out of scope.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Query-param validation | A manual `if route not in {...}: raise` in the endpoint body | FastAPI `Query(pattern=...)` → auto-422 (REST); Pydantic `Field(pattern=...)` (SearchParams); `Literal[...]` (settings) | Fail-closed at the boundary before the handler runs (ASVS V5), exactly as `mode` does today. |
| Settings env override | Custom env parsing for `KLAKE_ROUTER__DEFAULT_ROUTE` | The existing `env_nested_delimiter="__"` on `Settings` | Resolves nested submodel fields automatically — no code (settings.py:447). |
| MCP/OpenAI schema for `route` | Hand-written JSON schema | Add the field to `SearchParams`; `model_json_schema()` is the single source for both surfaces | `agent/openai_defs.py:43` and the MCP inputSchema both call `input_model.model_json_schema()`. |
| Tree/chunk retrieval | Any new retrieval logic | `tree_search()` / `search()` as-is | D-01/D-02 — the router is dispatch-only. |

**Key insight:** Every "new" behavior in this phase already has a byte-for-byte
precedent from the Phase-10 `mode` parameter rollout. Treat `route` as a second
`mode`-shaped parameter and copy each site.

## Common Pitfalls

### Pitfall 1: The REST `/search` endpoint does NOT consume `SearchParams`
**What goes wrong:** The plan assumes "add `route` to `SearchParams` → all four
surfaces get it for free." True for MCP + OpenAI defs (both derive from
`SearchParams.model_json_schema()`), but **false** for the REST endpoint:
`search_endpoint` in `api/app.py` declares each parameter as an individual
`Query()` argument (`q`, `top_k`, `mode`, filters…) and never references
`SearchParams`. If `route` is only added to the schema, `GET /search?route=tree`
silently ignores the param.
**Why it happens:** The "single schema" convention (D-08) is real for the
agent/MCP surface but the FastAPI handler predates it and duplicates the params.
**How to avoid:** Add `route` in **four** places: `SearchParams` field (MCP+OpenAI),
`_search_handler` signature (so `model_dump()` unpack doesn't `TypeError`),
`search_endpoint` `Query()` param, and `cmd_search` `--route` Option. Each must
call `routed_search()`.
**Warning signs:** MCP `search` accepts `route` but `curl "/search?route=tree"`
returns chunk results.

### Pitfall 2: `routed_search()` must be synchronous
**What goes wrong:** If `routed_search()` is written `async` (or called from a
running event loop), `tree_search()` raises
`RuntimeError("tree_search() cannot be called from within a running event loop…")`
— it guards against nested `asyncio.run()` (`tree_search.py:230-239`).
**Why it happens:** `tree_search()` owns the single top-level event-loop entry point
for its parallel S3 loads; it explicitly forbids being called from inside a loop.
The module docstring anticipates the Phase-15 router (CR-02).
**How to avoid:** Keep `routed_search()` **sync**, mirroring `search()` and
`tree_search()` themselves. All four surfaces already call the sync `search()`/
`tree_search()` today, so no caller needs to become async.
**Warning signs:** `RuntimeError` about event loops only on the `tree`/`two_stage`
path; chunk path works fine.

### Pitfall 3: Adding a REST Query param breaks the OpenAPI byte-identical test
**What goes wrong:** `tests/unit/test_openapi_export.py::test_openapi_json_matches_deterministic_dump`
asserts `docs/openapi.json` is **byte-identical** to a fresh
`json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"`. Adding the `route`
Query param changes the live schema → the committed file goes stale → test fails.
**How to avoid:** After adding the endpoint param, regenerate with `klake openapi`
(writes `docs/openapi.json`, see `cli/app.py:1215`) and commit the result. Make this
an explicit plan task, not an afterthought.
**Warning signs:** All routing tests green, but `test_openapi_json_matches_deterministic_dump`
red with "docs/openapi.json is stale — re-run `klake openapi`."

### Pitfall 4: The "both fail" path must return `[]`, not error
**What goes wrong:** Under `route="auto"` → tree upgrade → zero tree hits →
fallback to chunk → chunk also zero. If the fallback isn't careful it might return
the empty tree result while logging a fallback, or raise.
**How to avoid:** D-05 is explicit: fall back to `search()`, return whatever it
gives (including `[]`). Never raise. Mirrors `search()`'s own empty-result behavior
(`search.py:87-89`). PITFALLS.md "Looks Done But Isn't" checklist calls this out.
**Warning signs:** 500 error or a stack trace on a query that matches a tree trigger
but has no indexed content.

### Pitfall 5: `SearchParams.route` default must not force tree on every MCP call
**What goes wrong:** If `route` defaults to `"auto"` (not `None`) on `SearchParams`,
`model_dump(exclude_none=True)` will still include it, and every MCP call carries an
explicit route — usually fine, but it removes the "fall through to settings default"
semantics. `mode` uses `default=None` precisely so omission → settings default.
**How to avoid:** Default `route` to `None` on `SearchParams` (and on the REST Query
param and CLI Option), exactly like `mode`. `routed_search()` resolves
`route or settings.router.default_route`. The settings field carries the `"auto"`
default (D-07), not the wire params.
**Warning signs:** `KLAKE_ROUTER__DEFAULT_ROUTE=chunk` has no effect from MCP/REST
because a non-None per-call default always wins.

## Runtime State Inventory

> Not a rename/refactor/migration phase — this section is informational.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — routing is a stateless dispatch layer; no DB/S3 writes. | None |
| Live service config | None — no external service (n8n/Datadog/etc.) references route. | None |
| OS-registered state | None. | None |
| Secrets/env vars | New env var `KLAKE_ROUTER__DEFAULT_ROUTE` (read-only default; no secret). | Document in settings docstring; no rotation. |
| Build artifacts | `docs/openapi.json` regenerates after the REST param is added (Pitfall 3). | Run `klake openapi`, commit. |

**Zero Alembic migrations** — no schema change (CONTEXT.md D code_context confirms).

## Code Examples

### Resolve-and-dispatch skeleton (grounded in existing precedents)
```python
# Source pattern: pipeline/search.py:91-97 + tree_search.py:161-164
def routed_search(
    query: str,
    *,
    route: str | None = None,
    collection: str = "klake_chunks",
    top_k: int = 5,
    mode: str | None = None,      # forwarded to search()/tree_search() unchanged
    settings: Settings | None = None,
    **filters,                    # forwarded to search() on chunk path
) -> list[Hit]:
    s = settings or get_settings()
    effective_route = route or s.router.default_route          # Pattern 1

    if effective_route == "auto":
        decided, category = classify_route(query)              # Pattern 3
        if decided == "tree":
            hits = tree_search(query, collection=collection, top_k=top_k, mode=mode, settings=s)
            if hits:
                log.info("route.dispatch", route="tree", trigger=category, fallback=False)
                return hits
            # D-05 auto-fallback: tree upgraded but empty → chunk
            log.info("route.dispatch", route="tree", trigger=category, fallback=True)
            return search(query, collection=collection, top_k=top_k, mode=mode, settings=s, **filters)
        log.info("route.dispatch", route="chunk", trigger="no_match", fallback=False)
        return search(query, collection=collection, top_k=top_k, mode=mode, settings=s, **filters)

    # Explicit override (D-05 — no fallback)
    if effective_route in ("tree", "two_stage"):
        log.info("route.dispatch", route=effective_route, trigger="operator_override", fallback=False)
        return tree_search(query, collection=collection, top_k=top_k, mode=mode, settings=s)
    log.info("route.dispatch", route="chunk", trigger="operator_override", fallback=False)
    return search(query, collection=collection, top_k=top_k, mode=mode, settings=s, **filters)
```
`[VERIFIED: skeleton composed from search.py / tree_search.py signatures — planner
should confirm the exact filter-forwarding surface against cmd_search's kwargs]`

*Note the `mode`/`filters` forwarding: chunk path accepts the full filter set; tree
path's `tree_search()` signature accepts only `top_k/mode/max_docs/collection/settings`
(tree_search.py:132) — do not forward chunk-only filters to it.*

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `RouteDecision` Enum + `QueryRouter` class + `both` value (ARCHITECTURE.md §6 sketch) | Plain `routed_search()` function + `str` literals, no `both` | Locked in CONTEXT.md D-01/D-02/D-09 | Simpler; matches the project's function-over-class, reuse-plain-types convention (Phase 14 dropped `TreeHit`). |
| `RouterSettings(strategy, auto_classifier, two_stage)` (STACK.md sketch) | `RouterSettings(default_route: Literal[...] )` | Locked in D-07 | Field names in the sketch are stale — follow D-07. |
| LLM-assisted routing (ARCHITECTURE.md `route_analysis` toggle) | Regex-only, zero-LLM | ROUTE-05 deferred | Deterministic-first; no cost/latency; no LLM gateway involvement this phase. |

**Deprecated/outdated for this phase:**
- The `both`/merge path in ARCHITECTURE.md/FEATURES.md — deferred (D-09).
- `route_analysis`/`auto_classifier="llm"` — ROUTE-05, do not implement.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Prefer `str` literals over a `RouteDecision` Enum, matching codebase convention | Standard Stack / State of the Art | LOW — cosmetic; D-01 note leaves this to planner's discretion either way. |
| A2 | `RouterSettings` should be wired into `Settings` beside `search:` (~L546) with `Field(default_factory=RouterSettings)` | Component Responsibilities | LOW — verified pattern for all 15 existing submodels; only the line number is approximate. |
| A3 | `SearchParams.route` and both wire params default to `None` (not `"auto"`) so settings-default fall-through works | Pitfall 5 | MEDIUM — if wrong, `KLAKE_ROUTER__DEFAULT_ROUTE` becomes ineffective from MCP/REST. Mirrors `mode`'s proven `default=None`. |
| A4 | The `**filters` forwarding surface on `routed_search()` should match `cmd_search`'s existing kwargs (domain/document_type/tags/…) for the chunk path | Code Examples | MEDIUM — under-forwarding drops filter support on `route="auto"`/`"chunk"`; planner should enumerate the exact kwarg set from `search()` (search.py:35-48). |

**Not empty:** these four assumptions should be confirmed during planning; none block
progress, and each has a verified fallback in the existing `mode` rollout.

## Open Questions

1. **Should `routed_search()` accept the full chunk filter set (domain, tags, …) or
   just `query`/`route`/`top_k`/`mode`?**
   - What we know: CLI `cmd_search` today passes 8 filter kwargs into `search()`.
     `route="chunk"`/auto-no-match must preserve that.
   - What's unclear: whether the plan threads all filters through `routed_search()`
     or only the CLI keeps calling `search()` for the chunk case.
   - Recommendation: thread the full filter set through `routed_search()` and forward
     to `search()` on the chunk path; forward only `top_k/mode/collection` to
     `tree_search()` (its signature accepts no filters). Preserves existing CLI
     behavior with one entry point (A4).

2. **Does the MCP `search` tool description need updating to mention `route`?**
   - What we know: the tool description (registry.py:243) currently says "Supports
     dense, sparse, and hybrid retrieval modes."
   - Recommendation: optionally extend the description to mention route selection;
     not required by ROUTE-04 but improves agent tool-use. Planner's discretion.

## Environment Availability

> Skipped — this phase has no external tool/service/runtime dependencies. It is a
> pure Python code change using the standard library `re` and already-installed
> project dependencies. No probing required.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (`[tool.pytest.ini_options]`, `testpaths = ["tests"]`, `addopts = "-v"`) `[VERIFIED: pyproject.toml:120-123]` |
| Config file | `pyproject.toml` |
| Quick run command | `uv run pytest tests/unit/test_route.py -x` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ROUTE-02 | Each trigger category matches → `classify_route` returns `("tree", <category>)` | unit (table-driven) | `uv run pytest tests/unit/test_route.py -k classify -x` | ❌ Wave 0 |
| ROUTE-03 | No structural signal → `classify_route` returns `("chunk","no_match")`; `routed_search` calls `search()` | unit | `uv run pytest tests/unit/test_route.py -k no_match -x` | ❌ Wave 0 |
| ROUTE-01 | `route="tree"` and `route="two_stage"` dispatch identically to `tree_search()` (alias equivalence) | unit (mock `tree_search`) | `uv run pytest tests/unit/test_route.py -k alias -x` | ❌ Wave 0 |
| ROUTE-01 | `route` resolution: per-call wins; else `settings.router.default_route`; `Literal` rejects bad value at load | unit | `uv run pytest tests/unit/test_route.py -k settings -x` | ❌ Wave 0 |
| D-05 | auto tree→zero hits→chunk fallback; explicit route→no fallback; both-empty→`[]` | unit (mock both callees) | `uv run pytest tests/unit/test_route.py -k fallback -x` | ❌ Wave 0 |
| ROUTE-04 | REST `?route=bogus`→422; `?route=tree` forwards `route="tree"` into `routed_search` | unit (TestClient + patch) | `uv run pytest tests/unit/test_api_route.py -x` | ❌ Wave 0 |
| ROUTE-04 | CLI `--route bogus`→exit 1; `--route tree` calls `routed_search(route="tree")` | unit (typer runner + patch) | `uv run pytest tests/unit/test_cli_route.py -x` | ❌ Wave 0 |
| ROUTE-04 | `SearchParams.route` present in `model_json_schema()` → surfaces in MCP inputSchema + OpenAI defs; `docs/openapi.json` regenerated & byte-identical | unit | `uv run pytest tests/unit/test_openapi_export.py tests/unit/test_tool_registry.py -x` | ✅ (openapi/tool-registry tests exist; extend) |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/unit/test_route.py -x`
- **Per wave merge:** `uv run pytest tests/unit -x` (surface tests + schema parity)
- **Phase gate:** `uv run pytest` full suite green before `/gsd-verify-work`
  (critically includes `test_openapi_export.py` — the deterministic-dump guard).

### Wave 0 Gaps
- [ ] `tests/unit/test_route.py` — classifier table (all 3 categories + no_match),
      alias equivalence (`tree`==`two_stage`), settings precedence, and the three
      D-05 fallback branches. Mock `search`/`tree_search` at
      `knowledge_lake.pipeline.route.search` / `.tree_search` (mirror
      `test_tree_search.py`'s module-level patch style).
- [ ] `tests/unit/test_api_route.py` — TestClient `?route=` forwarding + 422 on bad
      value (mirror `test_api_search_mode.py` structure).
- [ ] `tests/unit/test_cli_route.py` — typer `--route` forwarding + exit-1 on bad
      value (mirror `test_cli_search_mode.py`).
- [ ] Extend `tests/unit/test_openapi_export.py` coverage is automatic — the existing
      byte-identical test will fail until `docs/openapi.json` is regenerated (this is
      the desired RED→GREEN signal for the OpenAPI task).
- [ ] Framework install: none — pytest already present.

*Reuse note: `test_tree_search.py` / `test_tree_index.py` provide in-memory SQLite
(StaticPool) + `_patch_engine` fixtures, but `routed_search` unit tests should NOT
need a DB — mock `search`/`tree_search` directly and assert dispatch + logging.*

## Security Domain

> `security_enforcement: true`, `security_asvs_level: 1`, `security_block_on: high`
> (`.planning/config.json`).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface added; existing MCP bearer-token guard unchanged. |
| V3 Session Management | no | Stateless dispatch. |
| V4 Access Control | no | `search` remains a `read` tool; no privilege change. |
| V5 Input Validation | **yes** | `route` validated fail-closed at every surface: REST `Query(pattern=…)`→422; `SearchParams` `Field(pattern=…)`; CLI `VALID_ROUTES` guard→exit 1; settings `Literal[…]`→`ValidationError` at load. Mirrors the `mode` validator (T-10-02). |
| V6 Cryptography | no | No crypto. |

### Known Threat Patterns for {Python regex dispatch, FastAPI/Typer/MCP surfaces}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unvalidated `route` reaches dispatch (routes to unexpected path or errors) | Tampering | Fail-closed pattern/Literal validation at all four surfaces before `routed_search()` runs (V5). Only the 4 literal values pass. |
| Regex catastrophic backtracking (ReDoS) on attacker query text | DoS | Keep trigger patterns linear/anchored on literal keywords (D-04 patterns are simple alternations with no nested quantifiers). No user input is interpolated into the pattern — patterns are static/compiled once. Query length is already bounded upstream (e.g. `DiscoverRequest` max_length; `search` query is passed straight to embedder today). Confirm no `(.+)+`-style nesting when finalizing D-04 wording. |
| Prompt injection via query text | Tampering/Info-disclosure | **Not applicable this phase** — zero LLM calls; the classifier only pattern-matches, never sends the query to a model. (ROUTE-05 LLM routing deferred.) |
| Route param used to enumerate collections | Info-disclosure | `route` does not select a collection; the existing `_COLLECTION_NAME_RE` guard on `collection` (api/app.py:262) is unchanged. |

## Sources

### Primary (HIGH confidence)
- Codebase (`grep`/`Read`, this session): `pipeline/search.py`,
  `pipeline/tree_search.py`, `config/settings.py`, `api/schemas.py`, `api/app.py`,
  `cli/app.py`, `agent/registry.py`, `agent/server.py`, `agent/openai_defs.py`,
  `tests/unit/test_openapi_export.py`, `tests/unit/test_tree_search.py`,
  `pyproject.toml`, `.planning/config.json` — verified signatures, line numbers,
  validators, event-loop guard, and OpenAPI byte-identical test.
- `.planning/phases/15-query-router/15-CONTEXT.md` — locked D-01..D-09.
- `.planning/REQUIREMENTS.md` — ROUTE-01..04 (locked), ROUTE-05/06 (deferred).
- `.planning/STATE.md` — Phase-15 "no labeled query dataset" blocker (→ D-06 logging).

### Secondary (MEDIUM confidence)
- `.planning/research/PITFALLS.md` — Pitfall 3 (routing failures/fallback),
  "both fail" checklist item, rollback lever.
- `.planning/research/ARCHITECTURE.md` §6 — router sketch (superseded on `both`/Enum
  by D-01/D-09).
- `.planning/research/STACK.md` — `RouterSettings` sketch (superseded on field names
  by D-07).

### Tertiary (LOW confidence)
- None — all findings grounded in the codebase or locked planning docs.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all reused components verified in-repo.
- Architecture: HIGH — dispatch design fully specified by locked D-01..D-09 and
  mirrors the verified Phase-10 `mode` rollout.
- Pitfalls: HIGH — event-loop guard, OpenAPI byte-test, and REST-not-SearchParams
  gap all confirmed by reading the actual source.

**Research date:** 2026-07-14
**Valid until:** 2026-08-13 (30 days — stable internal domain, no external deps)
