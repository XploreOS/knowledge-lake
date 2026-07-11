---
phase: 12-agent-surfaces
reviewed: 2026-07-11T00:00:00Z
depth: standard
files_reviewed: 28
files_reviewed_list:
  - docs/openai_tools.json
  - docs/openapi.json
  - skills/add-source.md
  - skills/build-corpus.md
  - skills/export-dataset.md
  - skills/search-knowledge.md
  - src/knowledge_lake/agent/__init__.py
  - src/knowledge_lake/agent/http.py
  - src/knowledge_lake/agent/openai_defs.py
  - src/knowledge_lake/agent/registry.py
  - src/knowledge_lake/agent/server.py
  - src/knowledge_lake/agent/stdio.py
  - src/knowledge_lake/api/schemas.py
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/config/settings.py
  - src/knowledge_lake/pipeline/domains.py
  - src/knowledge_lake/pipeline/process.py
  - src/knowledge_lake/pipeline/query.py
  - tests/integration/test_mcp_http.py
  - tests/integration/test_stdio_lockdown.py
  - tests/unit/test_input_models.py
  - tests/unit/test_openapi_export.py
  - tests/unit/test_pipeline_extractions.py
  - tests/unit/test_readonly.py
  - tests/unit/test_skills_present.py
  - tests/unit/test_surface_parity.py
  - tests/unit/test_tool_handlers.py
  - tests/unit/test_tool_registry.py
findings:
  critical: 1
  warning: 4
  info: 0
  total: 5
status: issues_found
---

# Phase 12: Code Review Report

**Reviewed:** 2026-07-11
**Depth:** standard
**Files Reviewed:** 28
**Status:** issues_found

## Summary

This phase exposes the lake through an MCP server (stdio + Streamable HTTP), OpenAI/OpenAPI
exports, and Claude Code skills. The transport-security core (`agent/http.py`, `agent/stdio.py`)
is largely sound: localhost-only bind, DNS-rebinding `allowed_hosts`, closed CORS, constant-time
bearer via `secrets.compare_digest`, `Route` (not `Mount`) to avoid the Authorization-dropping
307 redirect, and an fd-level stdout lockdown for stdio. The surface-parity gate
(`test_surface_parity.py`) is a genuinely strong correctness harness.

However, the review found one **BLOCKER**: the `add_source` MCP tool is completely
non-functional — its handler calls the wrong function signature and raises `TypeError` on every
invocation. This is not caught by any test because no test executes the handler body (the parity
and registry tests only inspect `ToolDef` metadata and schemas, never call `_add_source_handler`).
Four warnings cover an auth-wiring footgun in `build_http_app`, a diverging `name` default in the
same handler, silent exception-swallowing in `process_crawled`, and the unauthenticated write-tool
default posture of the HTTP surface.

## Critical Issues

### CR-01: `add_source` MCP tool always raises TypeError — passes a `session` to a session-less function

**File:** `src/knowledge_lake/agent/registry.py:200-222`
**Issue:**
`_add_source_handler` calls `register_source` with a `session` as the first positional argument
**and** `url=` as a keyword:

```python
with get_session() as session:
    source = register_source(
        session,          # ← bound positionally to the `url` parameter
        url=url,          # ← then url= again → collision
        name=name,
        domain=domain,
        license_type=license_type,
    )
```

But the target function takes no session (`ingest.py:230`):

```python
def register_source(url, name, *, domain=None, license_type="unknown", ...): ...
```

`session` binds to the positional `url` parameter, then the explicit `url=url` keyword produces
`TypeError: register_source() got multiple values for argument 'url'`. `TypeError` is **not** in
`_EXPECTED_ERRORS = (ValueError, LookupError)` (`server.py:33`), so it propagates as a raw protocol
error rather than a clean `isError` result. The `add_source` tool therefore fails 100% of the time
on both stdio and HTTP surfaces.

This appears to be a copy/paste confusion with `registry.repo.create_source` /
`get_source_by_normalized_url` (which *do* take a session, as used correctly in
`pipeline/domains.py:100-105`). `register_source` already opens and commits its own
`get_session()` internally (`ingest.py:266`), so the surrounding `with get_session()` block is also
redundant. No test exercises this path, so the defect ships silently.

**Fix:**
```python
def _add_source_handler(
    url: str,
    name: str | None = None,
    domain: str | None = None,
    license_type: str = "unknown",
) -> dict:
    """Thin shim: maps SourceCreate fields to register_source()."""
    from urllib.parse import urlparse

    # register_source manages its own session + commit; do not wrap it.
    result = register_source(
        url=url,
        name=name or (urlparse(url).hostname or url),  # see WR-02
        domain=domain,
        license_type=license_type,
    )
    return {
        "source_id": result["source_id"],
        "name": result["name"],
        "url": result["url"],
        "is_new": result["is_new"],
    }
```

## Warnings

### WR-01: `build_http_app` never resolves `token` from `settings.mcp.token` — auth silently disabled for factory/direct callers

**File:** `src/knowledge_lake/agent/http.py:92-137,157`
**Issue:**
`build_http_app` auto-resolves `host`, `port`, and `server` from `get_settings()` when they are
`None`, but `token` is **not** defaulted from `settings.mcp.token`:

```python
if host is None:  host = settings.mcp.host
if port is None:  port = settings.mcp.port
if server is None: server = build_server(...)
# token is never pulled from settings.mcp.token
...
middleware = [Middleware(StaticBearerMiddleware, token=token)] if token else []
```

The shipped CLI path (`cli/app.py:1121`) passes `token=settings.mcp.token` explicitly, so the
`klake mcp --sse` command is fine. But the module docstring advertises the factory as
"safe-by-default," and a natural ASGI deployment
(`uvicorn knowledge_lake.agent.http:build_http_app --factory`, or any caller invoking
`build_http_app()` without threading the token) will run **unauthenticated even when
`KLAKE_MCP__TOKEN` is set** — a silent auth bypass. The asymmetry (host/port/server resolved,
token not) is a footgun.

**Fix:** resolve the token from settings alongside host/port when not explicitly provided, using a
sentinel to distinguish "caller passed None on purpose" from "unset":
```python
def build_http_app(server=None, *, host=None, port=None, token: str | None = _UNSET):
    settings = get_settings()
    ...
    if token is _UNSET:
        token = settings.mcp.token
```

### WR-02: `add_source` MCP path drops the documented "defaults to URL hostname" name behavior

**File:** `src/knowledge_lake/agent/registry.py:200-216`
**Issue:**
`skills/add-source.md:24` and `SourceCreate.name` both promise `name` "defaults to the URL
hostname." The CLI implements this (`cli/app.py:78`:
`effective_name = name or (urlparse(url).hostname or url)`). The MCP handler does not — it forwards
`name=None` straight to `register_source`, which passes it unchanged to `create_source`. Depending
on the `Source.name` column nullability this either stores a `NULL`/`None` name (contract
violation) or raises a NOT NULL `IntegrityError`. Even after CR-01 is fixed, an `add_source` call
without an explicit `name` behaves differently from the CLI and from the skill's stated contract.

**Fix:** compute the hostname fallback in the handler (folded into the CR-01 fix above:
`name=name or (urlparse(url).hostname or url)`).

### WR-03: `process_crawled` swallows every per-doc exception with no logging

**File:** `src/knowledge_lake/pipeline/process.py:114-116`
**Issue:**
```python
except Exception:
    failed += 1
```
The per-document loop catches *all* exceptions, increments a counter, and discards the exception
entirely — no `log.warning`, no artifact ID, no error type. A run can report `{"processed": 0,
"failed": 100}` with zero diagnostic signal about *why* every document failed (bad MIME, embed
service down, Qdrant unreachable, etc.). This blindly-broad catch also masks genuinely unexpected
failures (e.g. `KeyboardInterrupt` is spared since it's not an `Exception`, but programming errors
like `AttributeError`/`TypeError` are silently counted as content failures). This surface is
reachable directly as the `process_crawled` MCP write tool, so operators get no observability.

**Fix:** log the failure with structured context before counting it:
```python
except Exception:
    log.warning("process_crawled.doc_failed", raw_id=raw_id, source_id=src_id, exc_info=True)
    failed += 1
```
(add a module-level `log = structlog.get_logger(__name__)`).

### WR-04: HTTP surface exposes all 7 destructive write tools unauthenticated by default

**File:** `src/knowledge_lake/config/settings.py:319-332`, `src/knowledge_lake/agent/http.py:137,157`
**Issue:**
Defaults are `McpSettings.readonly = False` and `McpSettings.token = None`. With both defaults, the
Streamable HTTP surface exposes the full 11-tool set — including `crawl`, `crawl_all`, `ingest_url`
(network fetch), `export`, `init_domain`, and `process_crawled` — with **no authentication**. The
only mitigation is the localhost bind + Host guard. Any local process (or a browser via a
non-preflighted request that survives the Host check, or another user on a shared host) can drive
destructive, network-egress-capable tools. The phase brief calls for a "read-only tool posture" as
the security expectation; the shipped default is the opposite. This is a documented design decision
(D-10/D-11), but the safe default for an unauthenticated transport should be `readonly=True` (or the
server should refuse to expose write tools over HTTP unless a token is configured).

**Fix:** make write-tool exposure over HTTP conditional on auth, e.g. in `build_http_app` warn or
fail-closed when `token is None and not settings.mcp.readonly`, or flip the default posture:
```python
if token is None and any(t.access == "write" for t in server_tools):
    log.warning("mcp.http.unauthenticated_write_tools_exposed")  # or raise / force readonly
```

---

_Reviewed: 2026-07-11_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
