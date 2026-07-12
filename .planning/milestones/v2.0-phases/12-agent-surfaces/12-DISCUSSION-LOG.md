# Phase 12: Agent Surfaces - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-11
**Phase:** 12-agent-surfaces
**Mode:** `--auto` — all gray areas auto-selected; the recommended (first) option was chosen for each without user prompts. Every choice is revisable before planning.
**Areas discussed:** Schema source-of-truth architecture, Service-function extraction, stdout isolation, HTTP transport security + read/write separation, Long-running tools + error shape, Skills file location/format

---

## Schema source-of-truth architecture (MCP-01, SKILL-03)

| Option | Description | Selected |
|--------|-------------|----------|
| One Python-level `ToolDef` registry over Pydantic I/O models | MCP + OpenAI defs + parity test all derive from `input_model.model_json_schema()`; OpenAPI stays FastAPI-generated from the same reused models | ✓ |
| Derive tool schemas from FastAPI routes / OpenAPI | Treat the generated OpenAPI as the source; back-derive MCP + OpenAI defs from it | |
| Hand-write each surface (MCP, OpenAI, OpenAPI) separately | Independent schema per surface, reconciled by review | |

**Auto-selected:** One `ToolDef` registry (D-01–D-04). Single import point, reuses `api/schemas.py`, drift enforced by `test_surface_parity.py`.
**Notes:** Directly satisfies success criterion 4 ("assert stdio == http == openapi == openai; no drift"). Hand-writing surfaces guarantees drift; deriving from OpenAPI muddies the "never proxy REST" rule.

---

## Service-function extraction (MCP-01 "thin shim over pipeline/*.py")

| Option | Description | Selected |
|--------|-------------|----------|
| Extract missing service fns into `pipeline`/`registry`; refactor CLI to call them | `process_crawled` (inline CLI today), `list_sources`, `stats` (new), `init_domain` become real service functions the tools shim | ✓ |
| Let MCP handlers reimplement the missing logic inline | Duplicate the CLI/endpoint logic inside each MCP handler | |
| Have the missing tools call the REST API | Proxy the four gaps through HTTP endpoints | |

**Auto-selected:** Extract into `pipeline`/`registry`, one function many callers (D-05, D-06).
**Notes:** Reimplementing violates the no-duplication pattern (Phase 11 D-13); proxying REST violates MCP-01. Extraction also discharges the ROADMAP dependency note ("process_crawled / list_sources extracted into pipeline/registry").

---

## stdout isolation for the stdio JSON-RPC stream (MCP-02, research first-task gate)

| Option | Description | Selected |
|--------|-------------|----------|
| FD-level `dup2` stdout→stderr lockdown + logging/warnings to stderr, stdio-only, with self-test | Hardest guarantee against stray `print`/library/C-extension writes; landed first before any tool logic | ✓ |
| Reconfigure only the Python logger to stderr | Structlog/logging emit to stderr but raw `print`/C writes still leak to stdout | |
| Buffer/filter stdout post-hoc | Wrap stdout in a filter that drops non-JSON-RPC lines | |

**Auto-selected:** FD-level lockdown + self-test, stdio mode only (D-07, D-08).
**Notes:** ROADMAP research note names this the first-task gate. Logger-only reconfiguration misses non-Python writes; post-hoc filtering is fragile. HTTP mode is exempt.

---

## HTTP transport security + read/write separation (MCP-02, research note)

| Option | Description | Selected |
|--------|-------------|----------|
| Localhost bind + optional bearer token + CORS closed + `access` tags + `KLAKE_MCP__READONLY` flag | One binary, two safe postures; minimal auth surface for v2.0 | ✓ |
| Full auth/RBAC + remote (`0.0.0.0`) hosting | OAuth, per-user scopes, production remote exposure | |
| No security posture (open, all tools) | Bind `0.0.0.0`, no token, no read/write split | |

**Auto-selected:** Localhost + optional token + read/write capability flag (D-09–D-11).
**Notes:** Full auth/RBAC is deferred (Deferred Ideas); "open" is unsafe for write tools. The `access` tag + `KLAKE_MCP__READONLY` is the concrete "read/write tool-separation model" the research note asks to settle.

---

## Long-running tools + error/result shape (MCP-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Synchronous bounded calls + structured summaries; expected errors → MCP `isError`, unexpected → protocol error | `crawl`/`crawl_all`/`process_crawled` block and return a summary; consistent error contract | ✓ |
| Background job queue (submit → job_id → poll) | Async job surface for long crawls | |
| Fire-and-forget (no result) | Kick off work, return immediately without status | |

**Auto-selected:** Synchronous bounded + structured error contract (D-12, D-13).
**Notes:** A job-queue surface is out of MCP-01's intent-tool scope (Deferred Ideas). Fire-and-forget loses provenance/status. Errors preserve Phase 10 fail-loud semantics as agent-readable tool errors.

---

## Skills file location & format (SKILL-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Repo-root `skills/*.md` with `name`+`description` frontmatter, driving journeys by MCP tool name | Documentation-visible, independent of runtime config, tracks the single tool registry | ✓ |
| `.claude/skills/` runtime-config location | Skills live under the agent runtime config dir | |
| Inline the workflows into existing `docs/` | No dedicated skill files; fold guidance into docs | |

**Auto-selected:** Repo-root `skills/*.md` (D-16) — planner may choose `.claude/skills/` instead.
**Notes:** The four journeys (build-corpus, search-knowledge, add-source, export-dataset) reference tools by their registry names so they stay in sync with the surface.

---

## Claude's Discretion

- Exact `mcp` version pin and `streamable_http_app()`/lifespan wiring (confirm ~1.28.x at research; add `mcp` to `pyproject.toml`).
- Agent package module layout; whether `stats`/`list_sources` live in `pipeline/` or `registry/repo.py`.
- Whether OpenAI tool defs are a CLI verb, a committed artifact, or both.
- Skills directory name (`skills/` vs `.claude/skills/`) and frontmatter schema.
- Return shapes of `stats` and the `process_crawled`/`crawl_all` summaries.
- Form of the stdout-lockdown (context manager vs startup fn vs `agent/stdio.py`).

## Deferred Ideas

- Background/async job tools (submit → poll) for long crawls.
- Full auth / RBAC / multi-tenant + remote (`0.0.0.0`) MCP hosting.
- MCP `resources` & `prompts` primitives (this phase ships tools only).
- Per-tool rate limiting / quota on write tools.
- Additional skills beyond the required four.
