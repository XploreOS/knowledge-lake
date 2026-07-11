# Phase 12: Agent Surfaces - Research

**Researched:** 2026-07-11
**Domain:** MCP server implementation (Python), stdio/Streamable-HTTP transports, single-source-of-truth schema surfacing, Claude Code skills
**Confidence:** HIGH (MCP SDK API verified against installed `mcp==1.28.1`; all repo symbols verified at file:line)

## Summary

This phase surfaces the existing lake service layer to AI agents. Everything is a **thin re-surfacing** — no new lake capability. The three hard technical problems are all verifiable now and have clean answers against the installed `mcp==1.28.1`:

1. **One registry, three surfaces.** The correct architecture is a single **low-level `mcp.server.lowlevel.Server`** built from a declarative `TOOLS: list[ToolDef]` where each tool's `inputSchema` is `input_model.model_json_schema()`. That same low-level `Server` object is fed to **both** `stdio_server()` (stdio) **and** `StreamableHTTPSessionManager(app=server, ...)` (HTTP) — so the tool set is provably identical across transports because it is literally the same object. The high-level `FastMCP` derives tool schemas from *function signatures*, which fights the "shared registry of Pydantic input models" constraint (D-01) — use the low-level Server, not FastMCP, as the shared core. `[VERIFIED: mcp==1.28.1 source]`

2. **stdout lockdown ordering is the subtle one.** `stdio_server()` captures `sys.stdout.buffer` *at call time* and wraps it in a fresh `TextIOWrapper` (verified in source). Therefore you must **`os.dup(1)` to preserve the real JSON-RPC channel BEFORE** `os.dup2(2, 1)` (point process fd 1 at stderr), then pass the *preserved* handle explicitly as `stdio_server(stdout=preserved)`. If you dup2 first and let the SDK grab `sys.stdout` afterward, JSON-RPC goes to stderr and the client sees nothing. This repo's structlog is configured with `PrintLoggerFactory()` (no `file=`), which writes to **stdout** — confirmed at `src/knowledge_lake/__init__.py:42`. This is the exact corruption source D-07 targets.

3. **Async bridging correction (affects D-06/D-12 wording).** The MCP `call_tool` handler is **already `async`** and runs inside an anyio/asyncio event loop. `asyncio.run(crawl_source(...))` inside it raises `RuntimeError: asyncio.run() cannot be called from a running event loop`. The handler must **`await crawl_source(...)` directly**. The `asyncio.run` pattern in D-06/D-12 is correct only for *sync* callers (CLI, Dagster ops) — inside the async MCP handler it is wrong. `crawl_source`'s own docstring already says "awaited directly from the async handler." `[VERIFIED: crawl.py:244 docstring + mcp Server.call_tool source]`

**Primary recommendation:** Build one low-level `mcp.server.lowlevel.Server` from a `TOOLS` registry of Pydantic input models; feed it to `stdio_server()` and `StreamableHTTPSessionManager` unchanged; land the fd-level stdout-lockdown shim + self-test as task #1 (stdio only); `await` async service functions directly in handlers; enforce localhost + optional static bearer + read-only subset via a thin Starlette middleware and `TransportSecuritySettings`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Tool schema definition | Shared registry (`agent/registry.py`) | — | Single source of truth; imported by every surface (D-01) |
| stdio JSON-RPC transport | `agent/` (MCP stdio server) | Process/OS (fd 1) | JSON-RPC framing owns real stdout; logs must go to stderr (D-07) |
| HTTP transport + security | `agent/` (Streamable HTTP) + Starlette/uvicorn | — | Bind, auth, CORS live at the ASGI layer, not in tool logic (D-09/10/11) |
| Business logic | `pipeline/*.py` service functions | `registry/repo.py` | Handlers are thin shims; never duplicate logic (D-03) |
| Service-function extraction | `pipeline/` / `registry/` | `cli/app.py` (refactor caller) | `process_crawled`/`list_sources`/`stats`/`init_domain` extracted so CLI + MCP call one function (D-05) |
| OpenAPI export | FastAPI `app.openapi()` | `cli/app.py` (`klake openapi`) | Free, deterministic; same Pydantic models as the registry (D-14) |
| OpenAI tool defs | `agent/openai_defs.py` | — | Generated from the registry's `model_json_schema()` (D-15) |
| Skills | `skills/*.md` (repo-visible docs) | — | Reference tools by name; track the registry (D-16) |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `mcp` | `==1.28.1` | Official Anthropic MCP Python SDK — low-level `Server`, `stdio_server`, `StreamableHTTPSessionManager`, `types` | The reference implementation of the Model Context Protocol; only credible Python option `[VERIFIED: npm/pypi analog — PyPI, official modelcontextprotocol/python-sdk]` |

`mcp==1.28.1` — verified present on PyPI (`pip download mcp` resolved `mcp-1.28.1-py3-none-any.whl`, 2026). `Requires-Python: >=3.10` (repo is `>=3.12` ✓). `[VERIFIED: PyPI, mcp wheel metadata]`

### Supporting (already in `pyproject.toml` — reused, not added)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `starlette` | transitive (via fastapi/mcp) | ASGI app + middleware for the HTTP surface | HTTP transport, bearer-token middleware |
| `uvicorn` | `==0.49.0` (pinned) | ASGI server to run the Streamable-HTTP app | `klake mcp --sse` |
| `fastapi` | `==0.139.0` (pinned) | `app.openapi()` schema export | `klake openapi` (D-14) |
| `pydantic` | `==2.13.4` (pinned) | `model_json_schema()` — the shared schema source | Every surface (D-01/02) |
| `anyio` | transitive (via mcp) | `wrap_file` for the preserved stdout handle | stdout lockdown |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| low-level `Server` | `FastMCP` high-level API | FastMCP derives `inputSchema` from function type hints, not from a shared Pydantic model — it splits the schema source and complicates the D-01 single-registry / D-04 parity constraint. FastMCP is better only if you accept its function-signature schema model. **Rejected for D-01.** |
| static bearer middleware | `FastMCP` `TokenVerifier` / OAuth | OAuth is out of scope (D-10). A 10-line Starlette middleware checking `Authorization: Bearer` is the right weight. |
| `mcp[cli]` extra | — | The `[cli]` extra only adds `typer`+`python-dotenv` for the SDK's own `mcp` dev command; not needed (we have `klake`). Pin **bare `mcp`**. `[VERIFIED: mcp Provides-Extra = cli, rich, ws]` |

**Installation:**
```bash
uv add mcp==1.28.1     # base package — Streamable HTTP needs NO extras
```
No version conflicts: mcp requires `httpx<1,>=0.27.1` (repo `0.28.1` ✓), `pydantic<3,>=2.11` (repo `2.13.4` ✓), `pydantic-settings>=2.5.2` (repo `2.14.2` ✓), `starlette>=0.27`, `uvicorn>=0.31.1` (repo `0.49.0` ✓). New transitive dep: `jsonschema>=4.20` (used by the SDK for input validation). `[VERIFIED: mcp requires-dist]`

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `mcp` | PyPI | mature (official SDK) | very high | github.com/modelcontextprotocol/python-sdk | OK | Approved — official Anthropic/MCP SDK |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none
`mcp` is the canonical Model Context Protocol Python SDK maintained by the protocol authors; version 1.28.1 confirmed downloadable from PyPI in this session. No postinstall/build scripts of concern (pure-Python wheel). `[VERIFIED: PyPI wheel download]`

## Architecture Patterns

### System Architecture Diagram

```
                         ┌─────────────────────────────────────────┐
                         │  agent/registry.py                       │
                         │  TOOLS: list[ToolDef]                    │
                         │  ToolDef{name, description,              │
                         │          input_model (Pydantic),         │
                         │          handler (pipeline fn),          │
                         │          access: "read"|"write"}         │
                         └───────────────┬─────────────────────────┘
             derives inputSchema =       │ single source of truth
             input_model.model_json_schema()
        ┌───────────────┬────────────────┼────────────────┬──────────────────┐
        ▼               ▼                ▼                ▼                  ▼
 ┌────────────┐  ┌────────────┐   ┌─────────────┐  ┌──────────────┐  ┌──────────────┐
 │ low-level  │  │ low-level  │   │ openai_defs │  │ FastAPI      │  │ test_surface │
 │ Server     │  │ Server     │   │ generator   │  │ app.openapi()│  │ _parity.py   │
 │ (SAME obj) │  │ (SAME obj) │   │ (D-15)      │  │ (D-14)       │  │ (D-04)       │
 └─────┬──────┘  └─────┬──────┘   └──────┬──────┘  └──────┬───────┘  └──────────────┘
       ▼               ▼                 ▼                ▼
 stdio_server()  StreamableHTTP     openai-tools     docs/openapi.json
 (klake mcp)     SessionManager     .json / verb     (committed)
       │          (klake mcp --sse) 
       ▼               ▼
 clean stdout    uvicorn @127.0.0.1:3001
 (fd-locked)     + bearer + host/CORS guard
       │               │
       └──────┬────────┘
              ▼  call_tool handler (async): validate → unpack → await/call pipeline fn → JSON result
   ┌──────────────────────────────────────────────────────────────┐
   │ pipeline/*.py service functions (search, ingest, crawl,       │
   │ export, + extracted process_crawled/list_sources/stats/       │
   │ init_domain)  ──►  registry (Postgres) / Qdrant / MinIO       │
   └──────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure
```
src/knowledge_lake/agent/
├── __init__.py
├── registry.py        # TOOLS: list[ToolDef]; ToolDef dataclass; read/write tagging
├── server.py          # build low-level Server from TOOLS; list_tools + call_tool handlers
├── stdio.py           # fd-level stdout lockdown (dup/dup2) + run stdio server
├── http.py            # StreamableHTTPSessionManager → Starlette app + bearer middleware
└── openai_defs.py     # emit OpenAI function-tool defs from TOOLS
```
Plus: `cli/app.py` gains `klake mcp` / `klake openapi` verbs; `pipeline/` gains extracted `process_crawled`/`stats` (and `list_sources` in `pipeline` or `registry/repo.py`); `docs/openapi.json`; `skills/*.md`; `tests/.../test_surface_parity.py` + `test_stdio_lockdown.py`.

### Pattern 1: One low-level Server, two transports (shared registry — D-01)
**What:** Build the `Server` once from `TOOLS`; register `list_tools` + `call_tool`; reuse the object for stdio and HTTP.
**When to use:** Always — this is the mechanism that makes `stdio == http` true by construction.
```python
# Source: verified against mcp==1.28.1 (mcp.server.lowlevel.Server)
import mcp.types as types
from mcp.server.lowlevel import Server

def build_server(tools: list[ToolDef]) -> Server:
    server = Server("knowledge-lake")
    by_name = {t.name: t for t in tools}

    @server.list_tools()
    async def _list() -> list[types.Tool]:
        return [
            types.Tool(
                name=t.name,
                description=t.description,
                inputSchema=t.input_model.model_json_schema(),  # D-01 shared schema
            )
            for t in tools
        ]

    @server.call_tool()  # validate_input=True by default → jsonschema-validates inputSchema
    async def _call(name: str, arguments: dict):
        tdef = by_name[name]
        model = tdef.input_model(**arguments)          # Pydantic re-validation + coercion
        try:
            result = await tdef.invoke(model)          # see async-bridge pattern below
        except EXPECTED_ERRORS as exc:                 # D-13
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=str(exc))],
                isError=True,
            )
        # dict return → SDK auto-wraps as structuredContent + JSON text (verified in call_tool source)
        return result if isinstance(result, dict) else {"result": result}
    return server
```
Notes verified in `Server.call_tool` source: returning a **`dict`** makes the SDK emit `structuredContent` **and** a `TextContent` JSON dump automatically; returning a `types.CallToolResult` is passed through unchanged (this is how you set `isError=True`); any *uncaught* `Exception` is turned into an `isError` result by the SDK wrapper via `_make_error_result(str(e))`.

### Pattern 2: fd-level stdout lockdown, correct ordering (D-07/D-08)
**What:** Preserve real stdout, redirect process fd 1 → stderr, hand the preserved handle to the SDK.
**When to use:** stdio mode only (D-08 — HTTP mode leaves stdout alone).
```python
# Source: derived from verified mcp.server.stdio.stdio_server source (grabs sys.stdout.buffer at call time)
import os, sys, anyio
from io import TextIOWrapper
from mcp.server.stdio import stdio_server

async def run_stdio(server, init_opts):
    # 1. Preserve the real JSON-RPC channel BEFORE any redirect
    real_fd = os.dup(1)
    # 2. Point process fd 1 at stderr so stray print/C-ext/library writes cannot corrupt JSON-RPC
    os.dup2(2, 1)
    sys.stdout = sys.stderr                      # Python-level print() → stderr too
    # 3. Reconfigure logging to stderr (belt & suspenders; see structlog note below)
    #    structlog.configure(..., logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))
    #    logging.basicConfig(stream=sys.stderr); logging.captureWarnings(True)
    # 4. Build a clean stdout stream on the PRESERVED fd and give it to the SDK
    preserved = anyio.wrap_file(TextIOWrapper(os.fdopen(real_fd, "wb", buffering=0), encoding="utf-8"))
    async with stdio_server(stdout=preserved) as (read, write):
        await server.run(read, write, init_opts)
```
**Critical ordering:** `os.dup(1)` must run **before** `os.dup2(2, 1)`. `stdio_server()` accepts an explicit `stdout=` param (verified signature) — you MUST use it, because if the SDK grabs `sys.stdout.buffer` after the dup2, JSON-RPC would be written to stderr.

### Pattern 3: Streamable HTTP app with localhost + bearer + CORS-closed (D-09/10/11)
**What:** Wrap the same `Server` in `StreamableHTTPSessionManager`, mount in Starlette, add a bearer middleware, run under uvicorn.
```python
# Source: verified StreamableHTTPSessionManager.__init__ + TransportSecuritySettings (mcp==1.28.1)
from contextlib import asynccontextmanager
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.middleware import Middleware
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings

def build_http_app(server, *, port: int, token: str | None) -> Starlette:
    sec = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,                       # default True
        allowed_hosts=[f"127.0.0.1:{port}", f"localhost:{port}"],   # MUST populate or all rejected
        allowed_origins=[],                                          # CORS closed (D-10)
    )
    mgr = StreamableHTTPSessionManager(app=server, stateless=True, security_settings=sec)

    @asynccontextmanager
    async def lifespan(app):
        async with mgr.run():        # session-manager lifespan (verified pattern from FastMCP)
            yield

    async def handle(scope, receive, send):
        await mgr.handle_request(scope, receive, send)

    mw = [Middleware(StaticBearerMiddleware, token=token)] if token else []
    return Starlette(routes=[Mount("/mcp", app=handle)], lifespan=lifespan, middleware=mw)

# run: uvicorn.run(build_http_app(...), host="127.0.0.1", port=port)
```
`TransportSecuritySettings` fields are exactly `enable_dns_rebinding_protection` (default `True`), `allowed_hosts` (default `[]`), `allowed_origins` (default `[]`) — verified. With protection on and an empty `allowed_hosts`, **all requests are rejected**, so you must list the bind host:port. `allowed_origins=[]` keeps browser origins closed (D-10). The static bearer is a ~10-line Starlette `BaseHTTPMiddleware` that 401s when `KLAKE_MCP__TOKEN` is set and the header does not match; when unset, no middleware is added (D-10 "enforced only when set").

### Pattern 4: async bridge inside the async handler (D-12 correction)
```python
import inspect
async def invoke(tdef, model):
    kwargs = model.model_dump(exclude_none=True)
    fn = tdef.handler
    if inspect.iscoroutinefunction(fn):
        return await fn(**kwargs)                     # crawl_source / crawl_all_sources — AWAIT, not asyncio.run
    return fn(**kwargs)                               # sync fns (search, export, …) called directly
```
`crawl_source` (`crawl.py:244`) and `crawl_all_sources` (`crawl.py:911`) are `async def`; the handler `await`s them. Do **not** use `asyncio.run` here — it raises inside the running loop. (Optionally wrap blocking sync fns in `anyio.to_thread.run_sync` so DB/Qdrant I/O doesn't stall the event loop; acceptable to skip for a single-user localhost server in v2.0.)

### Read/write posture + read-only flag (D-11)
```python
def registered_tools(readonly: bool) -> list[ToolDef]:
    return [t for t in TOOLS if not readonly or t.access == "read"]
# read:  search, list_sources, lineage, stats
# write: ingest_url, crawl, crawl_all, process_crawled, add_source, export, init_domain
```
`KLAKE_MCP__READONLY` (nested pydantic-settings, `KLAKE_` prefix + `__` delimiter — verified `settings.py:346-347`) filters the list feeding *both* `list_tools` and dispatch. One binary, two postures.

### Anti-Patterns to Avoid
- **Proxying the REST API from MCP handlers** — MCP-01 hard rule; import and call `pipeline/*.py` directly.
- **`asyncio.run(...)` in the async call_tool handler** — raises `RuntimeError`; `await` instead.
- **dup2 before preserving fd 1** — sends JSON-RPC to stderr; preserve first, pass `stdout=` explicitly.
- **Using `FastMCP.@tool()` for the shared registry** — schema comes from function signature, breaking the Pydantic-model single source (D-01).
- **Comparing raw `model_json_schema()` to OpenAPI operation schema without normalization** — `$defs` vs `#/components/schemas`, `title` noise, and `mode` differences cause false parity failures (see Pitfall 2).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON-RPC framing / MCP protocol | Custom stdio/HTTP protocol loop | `mcp` SDK `stdio_server` / `StreamableHTTPSessionManager` | Spec-compliant, versioned, handles init handshake + session mgmt |
| Input schema from Pydantic | Hand-written JSON schema per tool | `input_model.model_json_schema()` | Single source of truth; drift-proof (D-01) |
| OpenAPI generation | Manual schema doc | FastAPI `app.openapi()` | Free, deterministic, already wired (D-14) |
| Host/DNS-rebinding guard | Custom Host-header checks | `TransportSecuritySettings` | SDK-built, covers DNS rebinding |
| Tool input validation | Manual arg checks | SDK `validate_input=True` + Pydantic ctor | Double-validated (jsonschema + Pydantic) |

**Key insight:** Every schema in this phase must originate from one Pydantic model per tool. The moment a schema is written twice, drift is guaranteed and the D-04 parity test becomes the only thing standing between you and silent surface divergence.

## Runtime State Inventory

> Pure surface-layer phase — no data migration, no renames. Grepping runtime state for completeness:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no keys/collections/IDs renamed. `stats` *reads* Qdrant point counts + registry rows; no writes. | None |
| Live service config | None — no external service config embeds new strings | None |
| OS-registered state | None — `klake mcp` is a foreground process, not a registered daemon | None |
| Secrets/env vars | **New** env vars introduced (read-only additions): `KLAKE_MCP__TOKEN`, `KLAKE_MCP__READONLY` (nested pydantic-settings, `settings.py`). No existing secret renamed. | Add `McpSettings` model; document in `docs/configuration.md` |
| Build artifacts | New committed artifact `docs/openapi.json`; optional committed OpenAI tool-def JSON. New `mcp` dep → `uv.lock` updates. | Commit generated files; run `uv lock` |

**Nothing found requiring data migration** — verified: no Alembic migration needed (CONTEXT code_context confirms "no schema migration"; consumes existing registry/Qdrant state read-only).

## Common Pitfalls

### Pitfall 1: JSON-RPC stream corruption from stdout writes (the whole reason for D-07)
**What goes wrong:** structlog, `print`, third-party libs, or C-extension writes land on stdout and interleave with JSON-RPC frames; the MCP client fails to parse and the session dies.
**Why it happens:** `src/knowledge_lake/__init__.py:42` configures `structlog.PrintLoggerFactory()` with no `file=` → defaults to **`sys.stdout`**. `_configure_logging()` runs at package import. Every `structlog.get_logger(__name__)` in `pipeline/*.py` (verified: search, export, crawl, ingest, enrich, …) writes there.
**How to avoid:** fd-level `dup2` (Pattern 2) — the robust fix, because it catches writes the Python logger can't (C extensions, subprocess inheritance). Additionally reconfigure `structlog` with `PrintLoggerFactory(file=sys.stderr)`, `logging.basicConfig(stream=sys.stderr)`, and `logging.captureWarnings(True)`.
**Warning signs:** Client reports "invalid JSON" / hangs on init; the D-08 self-test catches this deterministically.

### Pitfall 2: Naive schema equality fails the parity test (D-04)
**What goes wrong:** `SearchParams.model_json_schema()` and the FastAPI OpenAPI operation schema for the same model are *structurally* equal but *literally* different.
**Why it happens (Pydantic v2 quirks):** (a) nested models produce a `$defs` block with `$ref: "#/$defs/X"`, while FastAPI emits `#/components/schemas/X`; (b) Pydantic injects `title` keys derived from field names; (c) `mode='validation'` vs `'serialization'` differ for computed/aliased fields; (d) key ordering differs.
**How to avoid:** Write a `normalize(schema)` helper used by every parity assertion that: recursively drops `title`; rewrites all `$ref`/`$defs` prefixes to a canonical token; inlines or sorts `$defs`; and compares with sorted keys (`json.dumps(x, sort_keys=True)`). Compare the *normalized* forms of stdio-tool `inputSchema`, OpenAI `parameters`, and the OpenAPI operation request schema. Pass `model_json_schema(ref_template="#/$defs/{model}")` consistently.
**Warning signs:** Parity test red on cosmetic diffs; assertion diff shows only `title`/`$ref` string differences.

### Pitfall 3: `docs/openapi.json` produces noisy git diffs
**What goes wrong:** Re-exporting reorders keys → large spurious diffs on every run.
**How to avoid:** Dump with stable ordering: `json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"`. Commit that exact form; the `klake openapi` verb writes identically so re-runs are no-ops unless the schema truly changed.

### Pitfall 4: `SearchParams` under-covers the `search` tool inputs
**What goes wrong:** `SearchParams` (`schemas.py:30`) has only `q, top_k, collection, mode` — but `pipeline/search.py:search` (verified `search.py:35`) also accepts `domain, document_type, min_quality_score, source_name, format, tags, source_id`. Shimming `SearchParams` directly loses all payload filters (PAYLOAD-02 surface).
**How to avoid:** Either **extend `SearchParams`** with the filter fields (preferred — keeps GET /search and the tool identical, honoring D-02's "one model backs both") or add a dedicated `SearchToolInput`. Planner must pick one; extending `SearchParams` maximizes the single-source-of-truth goal. Note the FastAPI GET endpoint currently supplies those filters as separate `Query` params, so extending the model also tidies the endpoint.

### Pitfall 5: `stats` needs a Qdrant point count but no public method exists
**What goes wrong:** `QdrantVectorStore` exposes no public `count()`; only internal `self._client.count(collection, exact=True).count` at `qdrant_store.py:349-350`.
**How to avoid:** Add a small public `count_points(collection: str) -> int` to `QdrantVectorStore` wrapping `self._client.count(collection, exact=True).count` (handle missing-collection → 0), and call it from `stats()` via `get_vectorstore(settings)` (`resolver.py:250`). Do not reach into `_client` from the service function.

## Code Examples

### Extracted `list_sources` service function (D-05 — mirror the session-safe pattern)
```python
# Model on schemas.py:651 (SourceListItem) already materializes rows; the endpoint at
# api/app.py:1236 already does the session-safe fetch. Extract its body verbatim into:
def list_sources(domain=None, *, limit=50, offset=0) -> list[dict]:
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry.models import Source
    from sqlalchemy import select
    with get_session() as session:            # materialize inside session (avoids DetachedInstanceError)
        if domain is not None:
            rows = [s for s in session.execute(select(Source).order_by(Source.created_at.desc())).scalars()
                    if (s.config or {}).get("domain") == domain][offset:offset+limit]
        else:
            rows = list(session.execute(select(Source).order_by(Source.created_at.desc())
                        .limit(limit).offset(offset)).scalars())
        return [{"source_id": s.id, "name": s.name, "url": s.url, "source_type": s.source_type,
                 "license_type": s.license_type, "domain": (s.config or {}).get("domain"),
                 "created_at": s.created_at.isoformat() if s.created_at else ""} for s in rows]
# Then refactor list_sources_endpoint (api/app.py:1236) to call this and map dicts→SourceListItem.
```

### OpenAI function-tool defs from the registry (D-15)
```python
def openai_tool_defs(tools) -> list[dict]:
    return [{
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.input_model.model_json_schema(),   # SAME schema as MCP inputSchema
        },
    } for t in tools]
```

### `stats()` shape (planner discretion on exact keys — recommended)
```python
def stats(*, collection="klake_chunks", domain=None) -> dict:
    # registry counts via ORM; artifact counts grouped by artifact_type; Qdrant points via count_points()
    return {
        "sources": <count>,
        "documents": <count>,
        "artifacts_by_type": {"raw_document": n, "parsed_document": n, "chunk": n, ...},
        "qdrant_points": get_vectorstore(settings).count_points(collection),
        "collection": collection,
    }
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| HTTP+SSE transport (two endpoints: `/sse` + `/messages`) | **Streamable HTTP** (single `/mcp` endpoint) | MCP spec 2025-03-26 | `--sse` is a flag *name* only; back it with `StreamableHTTPSessionManager`. The deprecated `sse_app()` still exists in the SDK but must not be used (MCP-02). |
| 1:1 dump of every REST endpoint as a tool | ~11 curated intent-level tools | project decision (REQUIREMENTS "Out of Scope") | Fewer, higher-signal tools = agents succeed more often. |

**Deprecated/outdated:**
- `FastMCP.sse_app()` / HTTP+SSE transport — deprecated in the MCP spec; do not use (retain only the `--sse` CLI flag name).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `stateless=True` is acceptable for the Streamable-HTTP session manager (no cross-request session state needed for stateless tool calls) | Pattern 3 | Low — if per-session resumability is later wanted, set `stateless=False` + an `EventStore`; stateless is the simpler correct default for a tool-only server |
| A2 | Extending `SearchParams` (vs a new `SearchToolInput`) is the preferred way to cover full search filters | Pitfall 4 | Low — either works; extending best serves D-02 single-source goal but the planner may prefer a dedicated model |
| A3 | The bearer check is a plain Starlette `BaseHTTPMiddleware` (not the SDK's OAuth `TokenVerifier`) | Pattern 3 | Low — matches D-10 "minimal, optional static token"; OAuth is explicitly deferred |
| A4 | `init_domain` extraction target is a `load_domain(name) -> dict` service fn factored out of `cmd_init` (cli/app.py:1034) / `load_domain_endpoint` | D-05 mapping | Medium — confirm `load_domain_endpoint` body during planning to ensure both callers can share one signature |

## Open Questions

1. **Should sync service functions run in a thread pool under HTTP?**
   - What we know: `search`/`export`/registry calls are blocking; the event loop stalls during them.
   - What's unclear: whether v2.0's single-user localhost target cares.
   - Recommendation: Call sync fns directly for v2.0 (simplest); note `anyio.to_thread.run_sync` as the upgrade if concurrency is later needed. Not a blocker.

2. **Exact `init_domain` return shape and whether the load routine is already standalone.**
   - What we know: `cmd_init` (cli/app.py:1034) inlines `DomainLoader.from_name(...)` + per-source `register_source`. `load_domain_endpoint` (api/app.py:1574) is the API twin.
   - Recommendation: Extract a `load_domain(name) -> {name, loaded_count, skipped_count, upload_required_count}` (matches `DomainLoadResponse`, schemas.py:727) into `pipeline`/`domains`; refactor both CLI and endpoint to call it (D-05).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `mcp` package | MCP server (MCP-01/02) | ✓ (installable) | 1.28.1 on PyPI | none needed |
| `uv` | build/run toolchain | ✓ | present (`/root/.local/bin/uv`) | — |
| Python 3.12+ | runtime | ✓ | repo pins `>=3.12`; mcp needs `>=3.10` | — |
| uvicorn / starlette / fastapi | HTTP surface + openapi | ✓ pinned in pyproject | 0.49.0 / transitive / 0.139.0 | — |
| Qdrant server | `stats` point count, `search` | ✓ (docker-compose) | running service | `count_points` returns 0 if collection absent |

**Missing dependencies with no fallback:** none — `mcp` is the only new dependency and it installs cleanly.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8+ with `pytest-asyncio` (`asyncio_mode = "auto"`) `[VERIFIED: pyproject.toml]` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`) |
| Quick run command | `uv run pytest tests/unit/test_surface_parity.py -x` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MCP-01 | 11 tools registered; handlers call `pipeline/*` not REST | unit | `uv run pytest tests/unit/test_tool_registry.py -x` | ❌ Wave 0 |
| MCP-01 | each handler shims the correct pipeline fn (mock service, assert call) | unit | `uv run pytest tests/unit/test_tool_handlers.py -x` | ❌ Wave 0 |
| MCP-02 | stdio emits only JSON-RPC bytes (stdout lockdown) | integration | `uv run pytest tests/integration/test_stdio_lockdown.py -x` | ❌ Wave 0 (first-task gate) |
| MCP-02 | Streamable-HTTP app starts at 127.0.0.1; bearer enforced when set; non-localhost host rejected | integration | `uv run pytest tests/integration/test_mcp_http.py -x` | ❌ Wave 0 |
| MCP-02 | readonly flag registers only read tools | unit | `uv run pytest tests/unit/test_readonly.py -x` | ❌ Wave 0 |
| SKILL-02 | `klake openapi` writes deterministic `docs/openapi.json` | unit | `uv run pytest tests/unit/test_openapi_export.py -x` | ❌ Wave 0 |
| SKILL-03 | parity: stdio == http == openapi == openai (normalized) | unit | `uv run pytest tests/unit/test_surface_parity.py -x` | ❌ Wave 0 |
| SKILL-01 | four skill files exist with valid frontmatter, reference tool names | unit | `uv run pytest tests/unit/test_skills_present.py -x` | ❌ Wave 0 |
| D-05 | extracted `process_crawled`/`list_sources`/`stats`/`init_domain` return documented shapes; CLI still works | unit | `uv run pytest tests/unit/test_pipeline_extractions.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the task's targeted unit test (e.g. `test_surface_parity.py`)
- **Per wave merge:** `uv run pytest tests/unit -q`
- **Phase gate:** `uv run pytest -q` green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/integration/test_stdio_lockdown.py` — MCP-02, the **first-task gate** (self-test asserting only JSON-RPC on stdout)
- [ ] `tests/unit/test_surface_parity.py` + a shared `normalize(schema)` helper — SKILL-03/D-04
- [ ] `tests/unit/test_tool_registry.py`, `test_tool_handlers.py`, `test_readonly.py` — MCP-01/D-11
- [ ] `tests/integration/test_mcp_http.py` — MCP-02/D-09/10 (use `httpx` against uvicorn or Starlette `TestClient`)
- [ ] `tests/unit/test_openapi_export.py`, `test_skills_present.py`, `test_pipeline_extractions.py`
- [ ] Framework install: none — pytest + pytest-asyncio already present

## Security Domain

### Applicable ASVS Categories (Level 1)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (HTTP) | Optional static bearer token via `KLAKE_MCP__TOKEN`, enforced only when set (D-10); no auth on localhost stdio |
| V3 Session Management | minimal | Stateless Streamable-HTTP session manager; no session store (D-10) |
| V4 Access Control | yes | Read/write tool separation + `KLAKE_MCP__READONLY` capability flag (D-11) |
| V5 Input Validation | yes | Double validation: SDK `validate_input=True` (jsonschema on `inputSchema`) + Pydantic model construction; existing SSRF/scheme guards in `ingest_url` remain the boundary for URL inputs |
| V6 Cryptography | no | No crypto introduced; bearer compared with constant-time `secrets.compare_digest` |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| DNS rebinding / Host-header attack on local HTTP server | Spoofing | `TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=[...])` — verified SDK feature |
| Unauthenticated write tools exposed on network | Elevation of Privilege | Bind `127.0.0.1` by default; optional bearer; `KLAKE_MCP__READONLY` for read-only posture (D-09/10/11) |
| SSRF via `ingest_url`/`crawl` followed links | Tampering/Info Disclosure | Reuse existing `validate_public_url` guard (ingest.py:99) — `search`/`ingest` already block RFC-1918/IMDS; MCP handler adds no new fetch path |
| Bearer token timing leak | Info Disclosure | `secrets.compare_digest` in the middleware, not `==` |
| Log/JSON-RPC injection on stdout | Tampering | fd-level stdout lockdown (D-07) — logs can never reach the JSON-RPC channel |
| Domain-name path traversal in `init_domain` | Tampering | `DomainLoadRequest.name` pattern `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$` (schemas.py:710) already blocks traversal |

## Sources

### Primary (HIGH confidence)
- `mcp==1.28.1` installed & introspected this session — `mcp.server.lowlevel.Server` (`call_tool`, `list_tools`, `run`, `_make_error_result`), `mcp.server.stdio.stdio_server`, `mcp.server.streamable_http_manager.StreamableHTTPSessionManager`, `mcp.server.fastmcp.FastMCP.streamable_http_app`, `mcp.server.transport_security.TransportSecuritySettings`, `mcp.types` (`Tool`, `TextContent`, `CallToolResult`). Source read directly via `inspect.getsource`.
- PyPI — `mcp-1.28.1-py3-none-any.whl` metadata: `Requires-Python >=3.10`, extras `[cli, rich, ws]`, requires-dist (httpx/pydantic/starlette/uvicorn/jsonschema).
- Repo code (verified file:line): `src/knowledge_lake/__init__.py:42` (PrintLoggerFactory→stdout); `pipeline/search.py:35`, `ingest.py:230/337`, `crawl.py:211/244/911`, `export.py:243/357/449`; `cli/app.py:578/1034`; `api/app.py:145/1087/1236`; `api/schemas.py:30/170/204/266/651/710/727`; `plugins/builtin/qdrant_store.py:349`; `plugins/resolver.py:250`; `config/settings.py:346-347`.

### Secondary (MEDIUM confidence)
- `.planning/phases/12-agent-surfaces/12-CONTEXT.md` (D-01..D-16 locked decisions), `.planning/REQUIREMENTS.md` (MCP/SKILL acceptance text).

### Tertiary (LOW confidence)
- none — all API claims verified against installed source.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — `mcp==1.28.1` present on PyPI, introspected, no version conflicts.
- Architecture (registry/transports/lockdown/async): HIGH — verified against SDK source and repo code.
- Pitfalls: HIGH — stdout (structlog source), parity (Pydantic v2 behavior), async-bridge (SDK handler is async) all verified.
- Service extraction: HIGH for `list_sources`/`stats`/`process_crawled` (bodies read); MEDIUM for `init_domain` (endpoint body not fully read — flagged A4).

**Research date:** 2026-07-11
**Valid until:** 2026-08-10 (30 days; `mcp` is fast-moving — re-confirm the version pin if planning slips past a new minor release)

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MCP-01 | ~11 intent-level tools as thin shims over `pipeline/*.py`, one registry across transports | Low-level `Server` from `TOOLS` registry (Pattern 1); 7 direct shims (D-06) + 4 extractions (D-05, `list_sources`/`stats`/`process_crawled`/`init_domain` — signatures specified); handlers `await`/call pipeline fns, never REST |
| MCP-02 | `klake mcp` (clean stdio JSON-RPC) + `klake mcp --sse --port 3001` (Streamable HTTP) | fd-level stdout lockdown with correct ordering (Pattern 2, `stdio_server(stdout=preserved)`); `StreamableHTTPSessionManager` + Starlette + uvicorn (Pattern 3); `--sse` name backs Streamable HTTP |
| SKILL-01 | Four Claude Code skills driving MCP tools | `skills/*.md` with `name`/`description` frontmatter (D-16); recommended repo-root `skills/` dir; test asserts presence + tool-name references |
| SKILL-02 | `klake openapi` → committed `docs/openapi.json` | `json.dumps(app.openapi(), indent=2, sort_keys=True)` for deterministic diff (Pitfall 3); `docs/` exists, no `openapi.json` yet |
| SKILL-03 | OpenAI tool defs from Pydantic; no drift across surfaces | `openai_tool_defs()` from `input_model.model_json_schema()` (D-15); `test_surface_parity.py` with `normalize()` handling `$defs`/`$ref`/`title` (Pitfall 2) |
</phase_requirements>
</content>
</invoke>
