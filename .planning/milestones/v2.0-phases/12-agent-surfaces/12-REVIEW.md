---
phase: 12-agent-surfaces
reviewed: 2026-07-12T00:00:00Z
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
  info: 2
  total: 7
status: issues_found
---

# Phase 12: Code Review Report (Re-Review)

**Reviewed:** 2026-07-12T00:00:00Z
**Depth:** standard
**Files Reviewed:** 28
**Status:** issues_found

## Summary

This is the re-review of Phase 12 (agent-surfaces) after the prior fix pass.

**Prior CR-01 (register_source signature) — VERIFIED FIXED.** `_add_source_handler`
(`registry.py:201-228`) now calls `register_source(url, name, domain=..., license_type=...)`
with no session argument and reads the returned dict keys. Regression tests in
`tests/unit/test_tool_handlers.py` (`test_add_source_handler_calls_register_source_without_session`,
`test_add_source_handler_defaults_name_to_hostname`) exercise the handler body directly and
pass. Not re-reported.

**One genuinely NEW blocker was found (CR-01 below):** the MCP server's expected-error
path calls a stdlib `logging` logger with structlog-style keyword arguments, which raises
`TypeError` and *replaces* every readable tool error message with a confusing internal
`Logger._log() got an unexpected keyword argument 'tool'` string. This breaks the D-13
contract on the most common failure path (any `ValueError`/`LookupError` from a handler,
e.g. `export` with a missing `dataset_name`). It slipped past the existing test because
`test_call_tool_value_error_returns_is_error` only asserts `isError is True`, never the
message content.

**Of the three carried-over warnings, all three are still open:** WR-01 (token not
auto-resolved from settings for factory/direct callers), WR-03 (`process_crawled` swallows
every per-doc exception with a bare `except Exception` and no logging), and WR-04 (default
`readonly=False` + `token=None` exposes all destructive write tools unauthenticated over
HTTP). A new fourth warning (WR-05) was found: the CLI `mcp --port` option hardcodes
`3001` and never reads `settings.mcp.port`, so `KLAKE_MCP__PORT` is dead config despite the
docstring promising it as an override.

The surface-parity architecture (single `TOOLS` registry → stdio/http/OpenAI/OpenAPI) is
sound and well-tested. The stdio fd-level stdout lockdown is correct. Security controls on
the HTTP transport (localhost bind, Host guard, closed CORS, constant-time bearer) are
correctly implemented where wired.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: MCP expected-error path crashes on stdlib logger, masking every readable tool error (NEW)

**File:** `src/knowledge_lake/agent/server.py:109` and `:132`
**Issue:**
`server.py` uses a **stdlib** logger (`import logging`; `log = logging.getLogger(__name__)`,
line 22/27) but calls it with **structlog-style keyword arguments**:

```python
log.warning("mcp.call_tool.expected_error", tool=name, error=str(exc))       # line 109
log.warning("mcp.call_tool.contamination_error", tool=name, error=str(exc))  # line 132
```

`logging.Logger.warning()` does not accept arbitrary keyword arguments — it forwards them to
`Logger._log()`, which raises `TypeError: Logger._log() got an unexpected keyword argument
'tool'`. Verified empirically:

```
$ python3 -c "import logging; logging.getLogger('x').warning('m', tool='a', error='b')"
TypeError: Logger._log() got an unexpected keyword argument 'tool'
```

Impact: in the `except _EXPECTED_ERRORS` block (and the contamination branch), the intended
readable message is never returned. The `TypeError` raised *inside* the except handler
propagates out and the SDK wraps it as a generic `isError` result. The client sees the
internal logging error string, not the domain message. Verified end-to-end against the real
`build_server`:

```
isError= True
content= ["Logger._log() got an unexpected keyword argument 'tool'"]   # expected the ValueError text
```

This breaks the D-13 contract ("the client sees the message without exposing internal stack
traces") on the most common failure path — every `ValueError`/`LookupError` a handler raises
(e.g. `export` with `kind='finetune'` and no `dataset_name` →
`"dataset_name is required for kind='finetune'."`, `lineage` on an unknown artifact id,
`init_domain` with a bad name). The existing regression test passes only because it asserts
`isError is True` and never inspects `content`.

**Fix:** Use stdlib-compatible logging (either `%`-style args or an f-string). Minimal change:

```python
# line 109
log.warning("mcp.call_tool.expected_error tool=%s error=%s", name, str(exc))
# line 132
log.warning("mcp.call_tool.contamination_error tool=%s error=%s", name, str(exc))
```

(Or switch the module to `structlog.get_logger(__name__)` if structured kwargs are desired —
but the stdlib `logging` import must then be removed to avoid confusion.) After the fix,
harden the test: assert the returned `content[0].text` equals the original exception message,
not merely that `isError` is truthy.

## Warnings

### WR-01: `build_http_app` never auto-resolves `token` from settings — fail-open for factory/direct callers (STILL OPEN)

**File:** `src/knowledge_lake/agent/http.py:92-98`, `:125-137`, `:156-157`
**Issue:**
`build_http_app` resolves `host`, `port`, and `server` from `get_settings()` when the caller
passes `None`, but the `token` parameter is **never** resolved from `settings.mcp.token`.

```python
def build_http_app(server=None, *, host=None, port=None, token=None):
    ...
    if server is None or host is None or port is None:
        settings = get_settings()
        if host is None: host = settings.mcp.host
        if port is None: port = settings.mcp.port
        # token is NOT resolved here
    ...
    middleware = [Middleware(StaticBearerMiddleware, token=token)] if token else []
```

A factory/direct caller that constructs the app without passing `token` (e.g.
`build_http_app()` or `build_http_app(server)`) gets **no auth middleware even when
`KLAKE_MCP__TOKEN` is set**. This is a fail-open inconsistency: `readonly`, `host`, and
`port` all honor settings automatically, but the one security-relevant field does not. The
current CLI path (`cli/app.py:1121`) happens to pass `token=settings.mcp.token` explicitly,
so the shipped `klake mcp --sse` command is safe — but any other caller silently loses auth.

**Fix:** Resolve `token` from settings alongside the others (treat an explicit empty string as
"no auth"; use a sentinel to distinguish "not provided" from "explicitly disabled"):

```python
_UNSET = object()

def build_http_app(server=None, *, host=None, port=None, token=_UNSET):
    from knowledge_lake.config.settings import get_settings
    settings = get_settings()
    if host is None:  host = settings.mcp.host
    if port is None:  port = settings.mcp.port
    if token is _UNSET:  token = settings.mcp.token   # default to configured token
    if server is None:
        server = build_server(registered_tools(readonly=settings.mcp.readonly))
    ...
```

### WR-03: `process_crawled` swallows every per-doc exception with a bare `except` and no logging (STILL OPEN)

**File:** `src/knowledge_lake/pipeline/process.py:114-115`
**Issue:**

```python
except Exception:
    failed += 1
```

Every per-document exception — `parse`, `chunk`, `embed`, `index` — is caught, counted, and
discarded with **no logging**. Operators get a bare `failed` integer with no artifact id, no
exception type, and no traceback, making failures undiagnosable. This also contradicts the
function's own docstring (`:42-45`), which claims "Any exception ... propagates as-is for
unexpected errors; expected per-doc failures are caught, counted." The code makes no such
distinction — a config error, an out-of-memory in `embed`, or a Qdrant outage in `index` are
all silently swallowed as "failed", so a systemic outage looks identical to one bad document.

**Fix:** Log each failure with context (artifact id + exception) before counting; keep the
batch resilient but observable:

```python
import logging
log = logging.getLogger(__name__)
...
        except Exception:
            failed += 1
            log.warning("process_crawled: doc %s failed", raw_id, exc_info=True)
```

Optionally narrow the catch and let truly unexpected/systemic errors (e.g. connection
errors) propagate, matching the docstring's stated contract.

### WR-04: Default `readonly=False` + `token=None` exposes all destructive write tools unauthenticated over HTTP (STILL OPEN)

**File:** `src/knowledge_lake/config/settings.py:319-325` (defaults) and
`src/knowledge_lake/agent/http.py:133-157` (wiring)
**Issue:**
With the shipped defaults (`McpSettings.readonly=False`, `McpSettings.token=None`), running
`klake mcp --sse` serves **all 11 tools — including `ingest_url`, `add_source`, `crawl`,
`process_crawled`, `export`, and `init_domain` — with no authentication**, guarded only by the
`127.0.0.1` bind and the Host header rebinding guard. Any local process or co-tenant user on
the host can drive destructive/write operations (fetch arbitrary URLs, mutate the registry,
trigger exports, load domain packs). The Host guard defeats DNS-rebinding but does nothing
against a same-host attacker. Combined with WR-01 (a caller who forgets `token` also gets no
auth), the fail-open story is worse than it appears.

**Fix (defense-in-depth, choose at least one):**
- Default the HTTP transport to read-only unless a token is configured — i.e. when
  `token` is falsy and `--sse` is requested, force `readonly=True` and log a warning that
  write tools are hidden until `KLAKE_MCP__TOKEN` is set; or
- Refuse to start the HTTP transport with write tools enabled and no token (fail-closed):

```python
if sse and not settings.mcp.token and not settings.mcp.readonly:
    raise typer.BadParameter(
        "Refusing to serve write tools over HTTP without KLAKE_MCP__TOKEN. "
        "Set a token or run with KLAKE_MCP__READONLY=true."
    )
```

At minimum, document the exposure prominently and emit a startup warning.

### WR-05: CLI `mcp --port` hardcodes 3001 and ignores `settings.mcp.port` — `KLAKE_MCP__PORT` is dead config (NEW)

**File:** `src/knowledge_lake/cli/app.py:1091-1093`, `:1120`, `:1123`
**Issue:**
The `--port` option defaults to a hardcoded literal:

```python
port: int = typer.Option(3001, "--port", help="HTTP port (localhost only, --sse mode)."),
```

`cmd_mcp` then uses this `port` for both `build_http_app(..., port=port)` and
`uvicorn.run(..., port=port)`, and never reads `settings.mcp.port`. Consequently
`KLAKE_MCP__PORT` has **no effect** on the CLI, directly contradicting the `McpSettings.port`
docstring (`settings.py:332`: "Override via KLAKE_MCP__PORT env var") and the `cmd_mcp`
docstring (`:1100-1101`: "bind host/port ... come from settings.mcp"). The host is correctly
sourced from `settings.mcp.host`, so the port asymmetry is almost certainly unintended. An
operator who sets `KLAKE_MCP__PORT=4000` will silently get 3001.

**Fix:** Default the option to `None` and fall back to `settings.mcp.port`:

```python
port: int | None = typer.Option(None, "--port", help="HTTP port (defaults to settings.mcp.port)."),
...
settings = get_settings()
bind_port = port if port is not None else settings.mcp.port
http_app = build_http_app(server, host=settings.mcp.host, port=bind_port, token=settings.mcp.token)
uvicorn.run(http_app, host=settings.mcp.host, port=bind_port)
```

## Info

### IN-01: `test_call_tool_value_error_returns_is_error` asserts only `isError`, never the message — masked CR-01

**File:** `tests/unit/test_tool_handlers.py:250-285`
**Issue:**
The test asserts `call_result.isError is True` but never inspects `call_result.content`. Because
the SDK converts any raised exception (including the `TypeError` from CR-01) into an `isError`
result, the test stays green even though the intended readable message is destroyed. This is
why the CR-01 logging bug shipped undetected.
**Fix:** Assert the surfaced text equals the raised message:

```python
assert call_result.content[0].text == "test error from handler"
```

Add a symmetric assertion for the contamination-error branch (`server.py:132`).

### IN-02: `process_crawled` docstring describes a propagate/catch split the code does not implement

**File:** `src/knowledge_lake/pipeline/process.py:42-45`
**Issue:**
The docstring states unexpected errors "propagate as-is" while expected per-doc failures are
"caught, counted." The implementation (`:114-115`) catches *all* `Exception` per doc, so the
documented contract is false. Tracks with WR-03; if WR-03 is fixed by narrowing the catch, the
docstring becomes accurate. Otherwise, correct the docstring to state that all per-doc
exceptions are swallowed into `failed`.

---

_Reviewed: 2026-07-12T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
