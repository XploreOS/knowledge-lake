---
phase: 15-query-router
reviewed: 2026-07-14T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - src/knowledge_lake/pipeline/route.py
  - src/knowledge_lake/config/settings.py
  - src/knowledge_lake/api/schemas.py
  - src/knowledge_lake/api/app.py
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/agent/registry.py
  - tests/unit/test_route.py
  - tests/unit/test_api_route.py
  - tests/unit/test_cli_route.py
  - docs/openapi.json
findings:
  critical: 2
  warning: 4
  info: 3
  total: 9
status: issues_found
---

# Phase 15: Code Review Report

**Reviewed:** 2026-07-14
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Phase 15 delivers the query-router dispatch layer: `classify_route()`, `routed_search()`, `RouterSettings`, API/CLI/MCP surface wiring, and unit tests. The core routing logic in `route.py` is clean and the security boundaries (Pydantic validation, fallback semantics, structlog emission) are correctly placed.

Two critical defects are present. The first is a hard crash in the MCP `_search_handler` that renders the MCP `search` tool non-functional for any non-empty result. The second is an unresolved semantic conflict in the shared `mode` parameter that makes the combined `mode + tree-route` path produce undefined behavior. Four warnings cover a dead import, a silent fallthrough for unsanitized values reaching `routed_search()` from Python callers, and two API design gaps. Three info items cover dead-code classes and a minor input-validation inconsistency.

---

## Critical Issues

### CR-01: MCP `_search_handler` crashes on any non-empty result — `dict(h)` fails for dataclass `Hit`

**File:** `src/knowledge_lake/agent/registry.py:171`

**Issue:** `Hit` is a `@dataclass` (not a `NamedTuple`), so `hasattr(h, "_asdict")` is always `False`. The fallback `dict(h)` then raises `TypeError: cannot convert 'Hit' object to dict items` because `dict()` on a plain dataclass instance requires either a mapping interface (`keys()`) or an iterable of `(k, v)` pairs — neither of which `dataclass` provides. Every MCP `search` tool call that returns any hits will raise an unhandled `TypeError`, returned to the MCP client as a tool-invocation error. Zero-hit results silently succeed, masking the bug in low-traffic tests.

```python
# Current (broken)
return [h._asdict() if hasattr(h, "_asdict") else dict(h) for h in hits]

# Fix — use dataclasses.asdict() which recursively converts dataclass fields
import dataclasses
return [dataclasses.asdict(h) for h in hits]
```

---

### CR-02: `mode` parameter has irreconcilable dual semantics — `mode="hybrid"` forwarded to `tree_search()` is structurally invalid

**File:** `src/knowledge_lake/pipeline/route.py:135-154, 174-180`

**Issue:** `routed_search()` accepts a single `mode` parameter and unconditionally forwards it to *both* `search()` and `tree_search()`. The two callees have entirely different valid values:
- `search()` accepts: `"hybrid" | "dense" | "sparse"`
- `tree_search()` accepts: `"heuristic" | "llm"` (per `TreeSearchSettings.mode: Literal["heuristic", "llm"]`)

The API layer validates `mode` only against the chunk-search set (`^(hybrid|dense|sparse)$`). A request such as `GET /search?q=test&mode=hybrid&route=tree` passes API input validation, enters `routed_search()`, and then calls `tree_search(mode="hybrid")`. "hybrid" is not a valid tree traversal mode; behaviour depends entirely on how `tree_search()` handles the unexpected value — it may silently ignore it (hiding operator intent), use a wrong default, or raise a `ValueError` that becomes an unhandled 500.

The CLI has the same surface: `klake search "query" --mode hybrid --route tree` takes the same broken path; the CLI validates `--mode` against `VALID_MODES = {"hybrid", "dense", "sparse"}` only.

**Fix:** Separate the two semantics by introducing a distinct `tree_mode` parameter. `mode` is the chunk-retrieval mode forwarded only to `search()`; `tree_mode` is the traversal mode forwarded only to `tree_search()`. Update `routed_search()` signature, API query params, CLI flags, schemas, and unit tests accordingly.

```python
# routed_search signature
def routed_search(
    query: str,
    *,
    route: str | None = None,
    collection: str = "klake_chunks",
    top_k: int = 5,
    mode: str | None = None,        # chunk path only: hybrid|dense|sparse
    tree_mode: str | None = None,   # tree path only: heuristic|llm
    ...
) -> list[Hit]: ...

# tree dispatch
hits = tree_search(
    query,
    collection=collection,
    top_k=top_k,
    mode=tree_mode,   # was: mode
    settings=s,
)

# chunk dispatch
hits = search(
    query,
    collection=collection,
    top_k=top_k,
    mode=mode,        # correct: chunk-only mode
    ...
)
```

---

## Warnings

### WR-01: Unused import `search` in `agent/registry.py`

**File:** `src/knowledge_lake/agent/registry.py:105`

**Issue:** `from knowledge_lake.pipeline.search import search` imports the bare `search` symbol, but no `ToolDef` entry uses it as a handler. The MCP search tool is wired to `_search_handler` (which calls `routed_search`). The unused import adds confusion — a reader may expect a `handler=search` somewhere, and linters will flag it. It also creates a hidden coupling: `search` is imported at module load time, which means any import-time error in `pipeline/search.py` will prevent the agent registry from loading.

**Fix:** Remove the unused import on line 105.

```python
# Remove this line:
from knowledge_lake.pipeline.search import search  # noqa: E402
```

---

### WR-02: Silent fallthrough in `routed_search()` when `effective_route` is an unrecognized value

**File:** `src/knowledge_lake/pipeline/route.py:182-191`

**Issue:** The comment at line 182 says `# effective_route == "chunk"` but this is an assumption, not an assertion. If `routed_search()` is called directly from Python code (not via the API or CLI) with an arbitrary `route=` value (e.g., `route="CHUNK"`, `route="dense"`, or any misspelling), `effective_route` will not match `"auto"`, `"tree"`, or `"two_stage"`, and silently falls through to `search()`. The `Settings.router.default_route` is protected by a `Literal` type, but `routed_search()` accepts an unconstrained `str | None`. The public API could be hardened.

**Fix:** Add an explicit guard before the final `search()` call to fail loudly on unrecognized routes:

```python
# Replace the comment-only guard at line 182
if effective_route != "chunk":
    log.warning("route.unknown_route", effective_route=effective_route)
    # Unknown values fall back to chunk as safe default; log for operator visibility
return search(query, collection=collection, top_k=top_k, mode=mode, settings=s, **chunk_filters)
```

Or fail closed instead of silently degrading:
```python
if effective_route not in ("auto", "tree", "two_stage", "chunk"):
    raise ValueError(f"Unknown route {effective_route!r}; expected: auto, chunk, tree, two_stage")
```

---

### WR-03: `/domains/{name}/sources` endpoint uses untyped `list[dict]` response model

**File:** `src/knowledge_lake/api/app.py:1541`

**Issue:** `list_domain_sources_endpoint` declares `response_model=list[dict]`. This is the only endpoint in the entire API surface without a typed Pydantic response schema. Consequences:
1. The OpenAPI spec generates no schema for the response body items (confirmed by inspecting the spec generation path).
2. FastAPI performs no response validation — the endpoint can return arbitrary, inconsistent shapes.
3. API consumers (including the MCP layer) cannot rely on a documented contract.

**Fix:** Define a typed schema for `SourceEntry` (the shape returned by `loader.sources`), declare it in `schemas.py`, and use it as the response model:

```python
class DomainSourceEntry(BaseModel):
    name: str
    url: str | None = None
    source_type: str
    license_type: str | None = None
    ...

# In app.py
@app.get("/domains/{name}/sources", response_model=list[DomainSourceEntry], ...)
```

---

### WR-04: `_search_handler` ignores the `route` field from `SearchParams` — only uses positional fields

**File:** `src/knowledge_lake/agent/registry.py:141-171`

**Issue:** The `SearchParams` model includes a `route` field (added in Phase 15, line 71-83 of `schemas.py`). The `_search_handler` function signature (lines 141-154) explicitly lists all `SearchParams` fields including `route: str | None = None` and forwards it to `routed_search()`. This part is correct.

However, `build_server`'s `call_tool` dispatch calls `handler(**args)` where `args` is derived from `model.model_dump(exclude_none=True)`. Since `SearchParams.route` has `default=None` and the model dump excludes None values, an unset `route` field will *not* be present in the kwargs at all — the handler receives no `route` keyword argument, so Python uses the default `route=None` from the function signature. This is intentional per the schema comment ("default=None, not 'auto', so model_dump(exclude_none=True) omits it when unset").

The actual gap is that the `search` tool description (line 248-252 of registry.py) does NOT mention that users can control routing. The tool description only mentions dense/sparse/hybrid modes but not the `route` parameter, making the `route` field invisible to LLM agents consuming the tool spec. This is a usability/documentation bug that may reduce the value of Phase 15 for agent use cases.

**Fix:** Update the tool description to mention route control:
```python
description=(
    "Semantic search over the knowledge lake. "
    "Returns ranked chunk hits with scores and citation metadata. "
    "Supports dense, sparse, and hybrid retrieval modes. "
    "Use 'route' to select retrieval path: 'chunk' (default), 'tree' (document-structure-aware), "
    "'auto' (classifier-driven), or 'two_stage' (alias for tree)."
),
```

---

## Info

### IN-01: `DatasetKind` and `ExportKind` string subclass definitions are dead code

**File:** `src/knowledge_lake/cli/app.py:405-409, 981-990`

**Issue:** Two classes (`DatasetKind(str)` and `ExportKind(str)`) are defined in `cli/app.py` but are never referenced by any Typer type annotation or runtime validation. Both commands (`cmd_generate_dataset`, `cmd_export`) perform manual `if kind not in (...)` validation instead of using these classes. The `_valid_values()` classmethod on `ExportKind` is never called.

**Fix:** Remove both dead classes. If they were intended as an enum-style validator, use `typer.Argument(..., show_choices=True)` with the appropriate type annotation.

---

### IN-02: `SearchParams.q` is required (Ellipsis) but allows `min_length=0`

**File:** `src/knowledge_lake/api/schemas.py:47-51`

**Issue:** `q: str = Field(..., min_length=0, ...)` uses `...` (Ellipsis) to make the field required while simultaneously allowing an empty string. This is contradictory: forcing clients to provide the parameter but allowing the degenerate case of an empty value. The behaviour is documented ("empty string is valid — handler returns []") and `routed_search()` does handle it, so this is not a correctness bug, but it creates a confusing client contract — OpenAPI will document the field as required with no minimum length, which is unusual.

**Fix:** Change to optional with a default, which is more semantically accurate:
```python
q: str = Field(
    default="",
    description="Natural-language search query. Empty string returns [].",
)
```
Or add `min_length=1` and handle the empty case at the routing layer only.

---

### IN-03: `comparison_multihop` regex uses unbounded `.+` in a compound alternation pattern

**File:** `src/knowledge_lake/pipeline/route.py:41-43`

**Issue:** The pattern `r"\bhow does .+ (?:affect|relate to|impact)\b"` uses `.+` (one or more of any character). While there are no nested quantifiers of the form `(a+)+` that cause catastrophic backtracking, `.+` in a mid-pattern context followed by a group can still cause quadratic backtracking on crafted long inputs where the suffix `(?:affect|relate to|impact)` never matches. Python's `re` module is backtracking-NFA based and can exhibit this on adversarial queries, though the real-world risk is low given that `query.strip()` is checked for emptiness before this path is reached.

The code comment `# Patterns are linear with literal keyword anchors — no nested quantifiers (T-15-02 ReDoS guard)` is not fully accurate for this sub-pattern.

**Fix:** Anchor the `.+` with a character class or a bounded quantifier:
```python
r"\bhow does .{1,100} (?:affect|relate to|impact)\b"
```
This caps the backtracking surface to 100 characters, covering all realistic queries.

---

_Reviewed: 2026-07-14_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
