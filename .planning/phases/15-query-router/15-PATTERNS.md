# Phase 15: Query Router - Pattern Map

**Mapped:** 2026-07-14
**Files analyzed:** 6 source + 5 test analogs
**Analogs found:** 6 / 6 (all exact or role-match)

> Every "new" behavior in this phase has a byte-for-byte precedent from the
> Phase-10 `mode` parameter rollout. Treat `route` as a second `mode`-shaped
> parameter and copy each site. The one trap: the REST endpoint does NOT
> consume `SearchParams` — it duplicates params as `Query()` args (Pitfall 1).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `pipeline/route.py` (NEW) | service / orchestrator | request-response (dispatch) | `pipeline/tree_search.py:tree_search()` (wraps `search()`) + `pipeline/search.py:search()` | exact (same wrap-and-dispatch shape) |
| `config/settings.py` (MOD) | config | — | `SearchSettings` (L404), `TreeSearchSettings` (L223) | exact |
| `api/schemas.py` (MOD) | model / schema | — | `SearchParams.mode` field (L62-70) | exact |
| `api/app.py` (MOD) | route / controller | request-response | `search_endpoint` `mode` Query (L210-220) | exact |
| `cli/app.py` (MOD) | route / CLI command | request-response | `cmd_search` `--mode` + `VALID_MODES` (L661-688) | exact |
| `agent/registry.py` (MOD) | handler / adapter | request-response | `_search_handler` shim (L140-168) + `search` ToolDef (L241-251) | exact |

## Pattern Assignments

### `pipeline/route.py` (NEW — service, dispatch orchestrator)

**Analogs:** `pipeline/search.py:search()` (the callee + `mode` resolution), `pipeline/tree_search.py:tree_search()` (the sync wrap-and-dispatch shape; it owns `asyncio.run()`).

**Imports pattern** (copy from `search.py:20-32` + `tree_search.py:40-49`):
```python
from __future__ import annotations
import re
import structlog
from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.pipeline.search import search
from knowledge_lake.pipeline.tree_search import tree_search
from knowledge_lake.plugins.protocols import Hit

log = structlog.get_logger(__name__)
```

**Per-call-override resolution** (verbatim precedent, `search.py:97`):
```python
effective_mode = mode or s.search.mode          # existing
# route.py mirror:
s = settings or get_settings()
effective_route = route or s.router.default_route
```

**Empty-query guard** (copy `search.py:87-89` / `tree_search.py:166-168`):
```python
if not query.strip():
    log.warning("route.empty_query")
    return []
```

**Sync-not-async — MUST stay synchronous.** `tree_search()` raises `RuntimeError` if called from a running event loop (`tree_search.py:230-239` — it does `asyncio.run(_load_all(...))` internally). `routed_search()` must be a plain `def`, exactly like `search()`/`tree_search()`. Every current caller already calls the sync functions, so no caller becomes async.

**Regex classifier** (D-04; module-level compiled, upgrade-only). Shape:
```python
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
Keep patterns linear/anchored on literal keywords — no nested quantifiers (ReDoS guard, Security Domain).

**Dispatch + fallback + structlog** (D-05/D-06). Follow the RESEARCH.md skeleton (15-RESEARCH.md L358-393). Key contracts:
- `route="auto"` + classify→tree + `tree_search()` returns zero Hits → fall back to `search()` (log `fallback=True`). Both empty → return `[]`, never raise (Pitfall 4; mirrors `search.py:87-89`).
- Explicit `tree`/`two_stage` → `tree_search()`, NO fallback (`trigger="operator_override"`). `tree` and `two_stage` are aliases (D-01) — identical dispatch.
- Explicit `chunk` → `search()`, no fallback.
- One structlog event per call: `route`, `trigger` (category / `operator_override` / `no_match`), `fallback` bool.

**Filter forwarding** (A4 / Open Q1): thread the full chunk-filter kwarg set (`domain, document_type, min_quality_score, source_name, format, tags, source_id`) into `routed_search()` and forward to `search()`. Forward ONLY `top_k/mode/collection` to `tree_search()` — its signature (`tree_search.py:132-140`) accepts no payload filters. Chunk-filter kwarg source of truth: `search.py:35-48`.

---

### `config/settings.py` (MODIFY — config submodel)

**Analog:** `SearchSettings` (L404-426) — the closest (single-`Literal`-field submodel). `TreeSearchSettings` (L223-265) shows multi-field + validator if needed.

**New submodel** — mirror `SearchSettings` exactly (Literal = fail-closed boundary, T-10-02):
```python
class RouterSettings(BaseModel):
    """Query-router dispatch config (ROUTE-01, D-07). Env: KLAKE_ROUTER__DEFAULT_ROUTE."""
    default_route: Literal["chunk", "tree", "two_stage", "auto"] = "auto"
```

**Wire into `Settings`** — add beside `search:` (L546), same `Field(default_factory=...)` idiom used by all 15 existing submodels:
```python
router: RouterSettings = Field(default_factory=RouterSettings)
```
No custom env parsing — the existing `env_nested_delimiter="__"` (L447) resolves `KLAKE_ROUTER__DEFAULT_ROUTE` automatically. This env var is the cheap rollback lever (`=chunk` reverts to chunk-only).

Do NOT copy the stale STACK.md sketch (`strategy`/`auto_classifier`/`two_stage` fields) — follow D-07's `default_route` Literal.

---

### `api/schemas.py` (MODIFY — shared Pydantic schema)

**Analog:** `SearchParams.mode` field (L62-70). Add `route` directly beside it. `default=None` is critical (Pitfall 5 — non-None default breaks settings fall-through and `model_dump(exclude_none=True)` semantics).
```python
route: str | None = Field(
    default=None,
    pattern=r"^(chunk|tree|two_stage|auto)$",
    description=(
        "Retrieval route; default resolves from KLAKE_ROUTER__DEFAULT_ROUTE (auto). "
        "Must be one of: chunk, tree, two_stage, auto. "
        "An unrecognised value is rejected with 422 (ASVS V5)."
    ),
)
```
This field feeds the MCP inputSchema and OpenAI defs (both call `SearchParams.model_json_schema()`) — no hand-written schema needed.

---

### `agent/registry.py` (MODIFY — MCP handler shim)

**Analog:** `_search_handler` (L140-168). The MCP server does `model.model_dump(exclude_none=True)` → `fn(**kwargs)`, so an unexpected `route` kwarg raises `TypeError` unless the shim signature accepts it (Pitfall 1).

Add `route: str | None = None` to the `_search_handler` signature (beside `mode`, L151), switch the call from `search(...)` to `routed_search(...)`, and forward `route=route`:
```python
def _search_handler(q, collection="klake_chunks", top_k=5, ..., mode=None, route=None):
    from knowledge_lake.pipeline.route import routed_search
    hits = routed_search(query=q, collection=collection, top_k=top_k, ..., mode=mode, route=route)
    return [h._asdict() if hasattr(h, "_asdict") else dict(h) for h in hits]
```
Optional (Open Q2): extend the `search` ToolDef description (L243-247) to mention route selection. Not required by ROUTE-04.

---

### `api/app.py` (MODIFY — REST endpoint)

**Analog:** the `mode` `Query()` validator in `search_endpoint` (L210-220). The endpoint uses individual `Query()` args and does NOT consume `SearchParams` (Pitfall 1) — `route` must be added here separately. Add beside `mode`:
```python
route: str | None = Query(
    default=None,
    pattern=r"^(chunk|tree|two_stage|auto)$",
    description=(
        "Retrieval route: chunk|tree|two_stage|auto. "
        "Defaults to KLAKE_ROUTER__DEFAULT_ROUTE (auto). "
        "An unrecognised value is rejected with 422 (fail-closed, ASVS V5)."
    ),
),
```
Then switch the delegation (L258 / L293-305) from `search(...)` to `routed_search(...)`, add `route=route` to the call and to the `logger.info("api.search", ...)` event (L279-292). The pattern `Query` auto-rejects bad values with 422 before the handler body runs.

**Regenerate `docs/openapi.json`** (Pitfall 3): adding the Query param mutates the live schema; `tests/unit/test_openapi_export.py::test_openapi_json_matches_deterministic_dump` asserts byte-identity. Run `klake openapi` (writes the file, see `cli/app.py:1215`) and commit. Make this an explicit plan task.

---

### `cli/app.py` (MODIFY — CLI command)

**Analog:** `cmd_search` `--mode` Option (L661-664) + `VALID_MODES` guard (L682-688). Also `cmd_tree_search` (L735) stays callable directly (D-03). Add a `--route` Option beside `--mode`:
```python
route: str | None = typer.Option(
    None, "--route",
    help="Retrieval route: chunk|tree|two_stage|auto (default from KLAKE_ROUTER__DEFAULT_ROUTE, else auto).",
),
```
Add the guard mirroring `VALID_MODES` (L682-688):
```python
VALID_ROUTES = {"chunk", "tree", "two_stage", "auto"}
if route is not None and route not in VALID_ROUTES:
    typer.echo(f"Error: --route must be one of {sorted(VALID_ROUTES)}, got {route!r}", err=True)
    raise typer.Exit(code=1)
```
Then switch `from ... import search` / `hits = search(...)` (L690-704) to `routed_search(...)`, forwarding `route=route` plus the existing filter kwargs (note CLI param is `tag` → forwarded as `tags=tag`).

## Shared Patterns

### Per-call override wins over settings default
**Source:** `pipeline/search.py:97` (`effective_mode = mode or s.search.mode`)
**Apply to:** `routed_search()` (`effective_route = route or s.router.default_route`); the `default=None` on all three wire params (`SearchParams.route`, REST `Query`, CLI Option) is what makes fall-through work (Pitfall 5).

### Fail-closed input validation at every surface (ASVS V5)
**Sources:** REST `api/app.py:210` `Query(pattern=...)` → 422; Pydantic `api/schemas.py:62` `Field(pattern=...)`; CLI `cli/app.py:682` `VALID_MODES` set guard → `Exit(1)`; config `settings.py:415` `Literal[...]` → `ValidationError` at load.
**Apply to:** all four `route` surfaces with pattern `^(chunk|tree|two_stage|auto)$`.

### Additive-only, new-function convention
**Source:** `tree_search.py` wraps `search()` unchanged (D-02 precedent).
**Apply to:** `route.py` wraps both callees; never edit `search()`/`tree_search()`.

### Structlog decision event
**Source:** `search.py:99-112` / `tree_search.py` `log.info(...)` calls.
**Apply to:** one `log.info("route.dispatch", route=..., trigger=..., fallback=...)` per `routed_search()` call (D-06).

## Test Analogs (for the planner's Wave 0 tests)

| New test (NEW) | Copy structure from | Key pattern |
|----------------|---------------------|-------------|
| `tests/unit/test_route.py` | `tests/unit/test_tree_search.py` | module-level patch of `knowledge_lake.pipeline.route.search` / `.tree_search`; table-driven classifier cases; alias equivalence; 3 fallback branches. NO DB needed — mock both callees. |
| `tests/unit/test_api_route.py` | `tests/unit/test_api_search_mode.py` | starlette `TestClient` + `try/except ImportError` guard; `?route=tree` forwards, `?route=bogus` → 422. |
| `tests/unit/test_cli_route.py` | `tests/unit/test_cli_search_mode.py` | `typer.testing.CliRunner`; patch `knowledge_lake.pipeline.route.routed_search` (imported inside `cmd_search`); `--route bogus` → exit 1. |
| `tests/unit/test_openapi_export.py` (extend) | existing byte-identical dump test | will RED until `docs/openapi.json` regenerated — desired signal for the OpenAPI task. |
| `tests/unit/test_tool_registry.py` (extend) | existing | assert `route` present in `SearchParams.model_json_schema()` → MCP inputSchema + OpenAI defs. |

## No Analog Found

None. Every file has an exact or role-match analog from the Phase-10 `mode` rollout and the Phase-14 `tree_search()` orchestrator.

## Metadata

**Analog search scope:** `src/knowledge_lake/pipeline/`, `config/`, `api/`, `cli/`, `agent/`, `tests/unit/`
**Files scanned:** search.py, tree_search.py, settings.py, schemas.py, app.py (api), app.py (cli), registry.py, 3 test analogs
**Pattern extraction date:** 2026-07-14
