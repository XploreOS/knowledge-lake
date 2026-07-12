# Phase 12: Agent Surfaces - Context

**Gathered:** 2026-07-11
**Status:** Ready for planning
**Mode:** `--auto` (all gray areas auto-selected; recommended default chosen for each without prompts — every decision below is auditable and revisable before planning)

<domain>
## Phase Boundary

Expose the **entire lake to AI agents** through a curated, intent-level tool surface plus static schema exports — all driven from **one shared schema source of truth**, sequenced LAST because it wraps the now-stabilized service functions from Phases 7–11.

Three deliverables, five locked requirements:

- **MCP-01** — An MCP server exposes ~11 curated intent-level tools (`search`, `ingest_url`, `crawl`, `crawl_all`, `process_crawled`, `add_source`, `list_sources`, `lineage`, `export`, `init_domain`, `stats`) as **thin shims over the existing `pipeline/*.py` service functions** (never proxying the REST API), sharing **one tool registry** across all transports.
- **MCP-02** — `klake mcp` starts the server over **stdio** with a guaranteed-clean JSON-RPC stream (structlog and all library output redirected off stdout); `klake mcp --sse --port 3001` starts it over HTTP backed by MCP **Streamable HTTP** (the deprecated HTTP+SSE transport is not used; `--sse` is retained as the flag name).
- **SKILL-01** — The repo ships four Claude Code skills — `build-corpus.md`, `search-knowledge.md`, `add-source.md`, `export-dataset.md` — that drive the lake through the stabilized MCP tools.
- **SKILL-02** — `klake openapi` exports the API's OpenAPI schema; a generated `docs/openapi.json` is committed to the repo.
- **SKILL-03** — OpenAI-format tool definitions are auto-generated from the Pydantic schemas, sharing a **single schema source of truth** with the OpenAPI export and the MCP tool registry (assert `stdio == http == openapi == openai`; no drift between surfaces).

**Out of scope:** any new lake *capability* — this phase only re-surfaces existing pipeline functions (new crawling, retrieval, storage, or scheduling behavior belongs to Phases 8–11, already shipped). Also out: a background/async job-queue tool surface, full auth/RBAC/multi-tenant MCP hosting, MCP resource/prompt primitives (tools only for v2.0), remote-hosted (non-localhost) production deployment, and per-tool rate limiting. These are captured under Deferred Ideas.
</domain>

<decisions>
## Implementation Decisions

### Schema source of truth — one tool registry (MCP-01, SKILL-03)

- **D-01:** Introduce a new **agent package** (planner discretion on exact path — recommend `src/knowledge_lake/agent/`) holding a declarative **tool registry**: `TOOLS: list[ToolDef]`, where each `ToolDef` = `{name, description, input_model (Pydantic), handler (a `pipeline/*.py` service function), access ("read"|"write")}`. This registry is the **single source of truth** imported by every surface. The MCP server, the OpenAI-tool-def generator, and the parity test all derive their schemas from `input_model.model_json_schema()` — there is exactly one place a tool's shape is defined.
- **D-02:** **Reuse existing `api/schemas.py` Pydantic models** as the `input_model` wherever one already fits the tool's arguments (e.g. `SearchParams`, `ExportRequest`, `SourceCreate`, `CrawlJobCreate`); only add new input models for tools that have no matching request schema (e.g. `stats`, `process_crawled`, `list_sources`, `init_domain`). This is what makes the OpenAPI export and the MCP/OpenAI defs share one schema definition rather than two parallel ones — the same Pydantic model backs both the FastAPI endpoint and the tool registry.
- **D-03:** Handlers are **thin shims that call the `pipeline/*.py` service function directly** — never an HTTP round-trip to the REST API (MCP-01 hard rule). A handler unpacks the validated input model into the service function's keyword args, calls it, and wraps the return in the tool's output as JSON. No business logic lives in the handler.
- **D-04:** SKILL-03 "no drift" is enforced by a **`test_surface_parity.py`** that asserts, for every tool, that the JSON schema emitted for the MCP `list_tools` response, the generated OpenAI `parameters` block, and the shared Pydantic `model_json_schema()` are equal (normalized), and that the tool set is identical across stdio and HTTP transports. Parity is a test, not a runtime check.

### Missing service-function extraction — honor "thin shim over pipeline/*.py" (MCP-01)

- **D-05:** Four of the eleven tools have **no clean `pipeline/*.py` service function today** and must be extracted before they can be shimmed (this is the ROADMAP "process_crawled / list_sources extracted into pipeline/registry" dependency made concrete):
  - **`process_crawled`** — logic currently lives **inline in `cli/app.py:cmd_process_crawled`**. Extract to a `pipeline` service function `process_crawled(source_id=None, limit=100, collection=...)` returning a structured summary (counts processed/skipped/failed); refactor `cmd_process_crawled` to call it. **No logic duplication** — the CLI and the MCP tool call the same extracted function.
  - **`list_sources`** — a canonical, MCP-facing `list_sources(domain=None, ...)` returning **materialized rows** (avoid `DetachedInstanceError`, mirror the Phase 11 `list_sources_for_crawl_all` session-safe pattern). Existing `registry/repo.py:list_sources_by_type` / `pipeline/crawl.py:list_sources_for_crawl_all` are close analogs but neither is the general list the tool needs.
  - **`stats`** — a **new** read-only `stats()` service function returning corpus aggregates (source count, artifact counts by type, document count, per-collection Qdrant point count). Nothing named `stats` exists today.
  - **`init_domain`** — shim over the existing domain-load path (`api/app.py:load_domain_endpoint` / `cli/app.py:cmd_init` both call a load-domain routine); expose the underlying function as an `init_domain(domain, ...)` service shim, extracting it to `pipeline`/`domains` if it is not already a standalone callable.
- **D-06:** The other seven tools shim **existing** service functions unchanged: `search` → `pipeline/search.py:search`, `ingest_url` → `pipeline/ingest.py:ingest_url`, `add_source` → `pipeline/ingest.py:register_source`, `crawl` → `pipeline/crawl.py:crawl_source` (via `asyncio.run`), `crawl_all` → `pipeline/crawl.py:crawl_all_sources` (via `asyncio.run`), `export` → `pipeline/export.py:export_*` (dispatch on dataset type, mirroring `api/app.py:export_endpoint`), `lineage` → the lineage query behind `api/app.py:lineage_endpoint`.

### stdout isolation — clean stdio JSON-RPC stream (MCP-02, research-gated FIRST task)

- **D-07:** **First-task gate (per ROADMAP research note):** before any tool logic, land a **stdout-lockdown shim + self-test (stdio mode only)**. In `klake mcp` stdio mode, at process startup and before importing anything that logs, perform an **fd-level `dup2` redirect of stdout → stderr**, then hand the MCP SDK the real stdout for JSON-RPC framing only. Also reconfigure structlog, the stdlib `logging` root, and `warnings` to emit on **stderr**. FD-level redirect (not merely reconfiguring the Python logger) is required because stray `print`, third-party libraries, and C-extension writes would otherwise corrupt the JSON-RPC stream.
- **D-08:** Ship a **self-test** that starts the stdio server, exercises a trivial tool, and asserts that **only** well-formed JSON-RPC bytes reached stdout (any log line or banner on stdout fails the test). HTTP/Streamable-HTTP mode does **not** apply the lockdown (its logs on stdout are fine).

### HTTP transport security + read/write separation (MCP-02, research note)

- **D-09:** The HTTP surface uses MCP **Streamable HTTP** via the `mcp` SDK's `streamable_http_app()` + lifespan wiring (confirm exact API against installed `mcp` ~1.28.x at research time). **Bind `127.0.0.1` by default** (localhost-only); host/port are configurable (`--port`, default 3001; the flag stays `--sse`). Not exposed on `0.0.0.0` by default.
- **D-10:** **Auth stays minimal:** no auth for the localhost default; support an **optional static bearer token** read from env (`KLAKE_MCP__TOKEN` or similar), enforced **only when set**. No OAuth/RBAC/session store in v2.0. **CORS closed by default** (agent clients are not browsers).
- **D-11:** **Read/write tool separation** is modeled as a per-tool `access` tag on `ToolDef` (`read` = `search`, `list_sources`, `lineage`, `stats`; `write` = `ingest_url`, `crawl`, `crawl_all`, `process_crawled`, `add_source`, `export`, `init_domain`) plus a **`KLAKE_MCP__READONLY` capability flag** (default `false`). When true, only `read` tools are registered — one server binary, two safe postures, no separate read/write servers. This is the "read/write tool-separation model" the research note asks to settle.

### Long-running tools + error/result shape (MCP-01)

- **D-12:** Long-running tools (`crawl`, `crawl_all`, `process_crawled`) run **synchronously** within the MCP call and return a **structured summary** when complete. No background job queue in v2.0 — bound the work with each function's existing limits (per-source config, `limit=`, `crawl_config` depth). Document that async/background job tools are deferred. `crawl`/`crawl_all` bridge to their async service functions via `asyncio.run` (same pattern as the Dagster ops and CLI).
- **D-13:** **Error contract:** handlers catch **expected** exceptions (`ValueError` from SSRF/scheme/validation guards, not-found lookups, the search store's fail-loud mode error) and return them as an **MCP tool error** (`isError` content) with a clear, agent-readable message; **unexpected** exceptions propagate as MCP protocol errors. Every successful tool returns its result serialized as JSON text content (the tool's output shape).

### Static exports — OpenAPI + OpenAI tool defs (SKILL-02, SKILL-03)

- **D-14:** `klake openapi` dumps FastAPI's already-generated schema (`app.openapi()` from `api/app.py:145`) to **`docs/openapi.json`** (the `docs/` dir already exists) and the file is committed. This is a deterministic export of the same Pydantic models the tool registry uses (D-02), which is what keeps `openapi` in the parity set.
- **D-15:** OpenAI-format tool definitions are **generated from the tool registry** (D-01) — one function-def object per tool (`{type:"function", function:{name, description, parameters: input_model.model_json_schema()}}`). Whether this is emitted by a CLI verb (e.g. `klake openai-tools`), a committed artifact, or both is planner discretion, as long as the parity test (D-04) covers it.

### Skills (SKILL-01)

- **D-16:** Ship the four skill files as **repo-visible Markdown** (recommend a repo-root `skills/` dir — planner discretion between `skills/` and `.claude/skills/`; repo-root keeps them documentation-visible and independent of runtime config). Each file has a short **frontmatter** (`name`, `description`) plus a workflow body that drives an end-to-end journey **by MCP tool name** so the skills track the single tool registry:
  - `build-corpus.md` — `add_source` → `crawl`/`crawl_all` → `process_crawled` → `search` (verify).
  - `search-knowledge.md` — `search` with metadata filters (`source_name`, `format`, `tags`, `domain`) + `lineage` for provenance.
  - `add-source.md` — `add_source` (register) and/or `ingest_url` (one-shot fetch+ingest).
  - `export-dataset.md` — `export` (rag_corpus / pretrain / finetune) → `stats`.

### Claude's Discretion
- Exact `mcp` package version pin and the precise `streamable_http_app()` / lifespan wiring — confirm against the installed `mcp` (~1.28.x) at research time; `mcp` is **not yet a dependency** and must be added to `pyproject.toml`.
- Exact module layout of the agent package (`agent/registry.py`, `agent/server.py`, `agent/openai_defs.py`, …) and whether `stats`/`list_sources` land in `pipeline/` or `registry/repo.py`.
- Whether OpenAI tool defs are a CLI verb, a committed artifact, or both (as long as parity is tested).
- Exact skills directory name (`skills/` vs `.claude/skills/`) and frontmatter schema.
- The concrete return shape of `stats` and the summary dicts for `process_crawled` / `crawl_all`.
- Whether the fd-lockdown is a context manager, a startup function, or a small `agent/stdio.py` module.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 12: Agent Surfaces" — goal, 5 success criteria, dependency note (needs `crawl_all` + `process_crawled`/`list_sources` extracted into `pipeline`/`registry`, wraps stabilized Phases 7/9/10/11 functions, sequenced LAST), and the **Research note** (stdout-isolation / Streamable-HTTP spike; confirm `streamable_http_app()`/lifespan against `mcp` ~1.28.x; `--sse`→Streamable HTTP substitution; localhost/auth/CORS + read/write tool separation; **first-task gate: stdout-lockdown shim + self-test, stdio only**).
- `.planning/REQUIREMENTS.md` §"AI Agent Skills" — MCP-01, MCP-02, SKILL-01, SKILL-02, SKILL-03 (full acceptance text), including the MCP-02 note that `--sse` is Streamable HTTP.

### Prior phase context (the service functions this phase wraps)
- `.planning/phases/07-metadata-foundation/07-CONTEXT.md` — the payload/filter model and `SearchParams`/`SourceOut` schema shapes reused as tool input models.
- `.planning/phases/08-crawl-maturation/08-CONTEXT.md` — `crawl_source`/`crawl_all_sources` service-function contracts and per-source `crawl_config` the `crawl`/`crawl_all` tools inherit.
- `.planning/phases/10-hybrid-retrieval/10-CONTEXT.md` — `search()` `mode` arg + **fail-loud** semantics the `search` tool must surface as an error (D-13), not silently degrade.
- `.planning/phases/11-crawl-scheduling/11-CONTEXT.md` — the **"assets/ops call plain pipeline functions, never duplicate logic"** pattern (D-13 there) and the **session-safe materialized-row** enumeration pattern (`list_sources_for_crawl_all`) reused for `list_sources` (D-05).

### Code touch points
- `src/knowledge_lake/pipeline/search.py:35` — `search()`; `pipeline/ingest.py:337` `ingest_url()`, `:230` `register_source()` (→ `add_source`); `pipeline/crawl.py:244` `crawl_source()`, `:911` `crawl_all_sources()`, `:211` `list_sources_for_crawl_all()`; `pipeline/export.py:243/357/449` `export_*()`. These are the shim targets (D-06).
- `src/knowledge_lake/cli/app.py:578` `cmd_process_crawled` — inline `process_crawled` logic to **extract** (D-05); `:1034` `cmd_init` (domain load → `init_domain`); Typer app is where `klake mcp` / `klake openapi` verbs are added.
- `src/knowledge_lake/api/app.py:145` — `FastAPI(...)` app whose `app.openapi()` backs `klake openapi` (D-14); `:1087` `lineage_endpoint`, `:1155` `export_endpoint`, `:1236` `list_sources_endpoint`, `:1574` `load_domain_endpoint` — the endpoint bodies that show how each service function is currently called.
- `src/knowledge_lake/api/schemas.py` — the Pydantic **source of truth** to reuse as tool input models (`SearchParams:30`, `ExportRequest:170`, `SourceCreate:204`, `CrawlJobCreate:266`, `SourceListItem:651`, …) (D-02).
- `src/knowledge_lake/registry/repo.py:558` `list_sources_by_type`, `:877` `list_sources_for_crawl_all` — analogs for the canonical `list_sources` (D-05).
- `docs/` — existing docs dir; `docs/openapi.json` is the committed export target (D-14).
- `pyproject.toml` — `mcp` is **not** a dependency yet; add it (D-09, research-confirm version).

### Framework docs (confirm at research time)
- MCP Python SDK (`mcp` ~1.28.x) — `streamable_http_app()`, lifespan wiring, stdio server, `list_tools`/`call_tool` handlers, `isError` tool-result shape. No local copy; researcher fetches official docs.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`pipeline/search.py:search`, `ingest.py:ingest_url`/`register_source`, `crawl.py:crawl_source`/`crawl_all_sources`, `export.py:export_*`** — clean, keyword-arg service functions that shim directly (D-06); the MCP handlers add no logic.
- **`api/schemas.py` Pydantic models** — reuse as tool input models so OpenAPI, OpenAI defs, and MCP share one schema (D-02); this is the mechanism behind SKILL-03.
- **`api/app.py` endpoint bodies** (`export_endpoint`, `lineage_endpoint`, `list_sources_endpoint`, `load_domain_endpoint`) — reference implementations for how each service function is invoked and what it returns.
- **`FastAPI.app.openapi()`** (`api/app.py:145`) — free, deterministic OpenAPI generation for `klake openapi` (D-14).
- **`list_sources_for_crawl_all` (crawl.py:211 / repo.py:877)** — the session-safe materialized-row pattern to copy for `list_sources` (avoids `DetachedInstanceError`).
- **`asyncio.run(crawl_source(...))` bridge** (used by CLI `cmd_crawl` and the Phase 11 Dagster op) — the same sync→async bridge the `crawl`/`crawl_all` tools use (D-12).

### Established Patterns
- **Thin surfaces call plain pipeline functions, never duplicate logic** (Phase 11 D-13, Dagster ops; the CLI commands) — MCP handlers follow the exact same rule (D-03).
- **`--auto` service-function extraction before re-surfacing** — `process_crawled` is inline CLI logic today; extracting it (D-05) and refactoring the CLI to call the extraction is the established "one function, many callers" shape.
- **Fail-loud over silent degradation** (Phase 10 search mode) — surfaced through the tool error contract (D-13).
- **`Source.config` JSON + additive, forward-only changes** — no schema migration is needed for this phase (pure surface layer); it consumes existing registry state.

### Integration Points
- New `agent/` package ← tool registry (`TOOLS`), MCP server (stdio + Streamable HTTP), OpenAI-def generator, stdout-lockdown shim.
- `cli/app.py` ← new `klake mcp` (`--sse`, `--port`) and `klake openapi` verbs; `cmd_process_crawled` refactored to call the extracted service function.
- `pipeline`/`registry` ← new/extracted `process_crawled`, `list_sources`, `stats`, `init_domain` service functions.
- `api/schemas.py` ← input models reused (and a few added) as the shared tool-schema source of truth.
- `docs/openapi.json` ← committed OpenAPI export.
- `skills/*.md` (new) ← four Claude Code skills driving the MCP tools.
- `pyproject.toml` ← add `mcp` dependency.
- `test_surface_parity.py` (new) ← asserts stdio == http == openapi == openai.

</code_context>

<specifics>
## Specific Ideas

- **One registry, many transports:** a single `TOOLS: list[ToolDef]` over Pydantic input models is the concrete meaning of "single schema source of truth." MCP `list_tools`, OpenAI function defs, and the OpenAPI export all derive from `input_model.model_json_schema()`; a parity test proves no drift (D-01, D-04, SKILL-03 success criterion 4).
- **Never proxy REST:** handlers import and call the `pipeline/*.py` function directly — the REST API and the MCP server are sibling surfaces over the same service layer, not layered on each other (MCP-01).
- **stdout is sacred in stdio mode:** fd-level `dup2` stdout→stderr + logging-to-stderr, landed and self-tested *first*, before any tool logic — the direct fix for JSON-RPC corruption and the ROADMAP first-task gate (D-07, D-08).
- **Two safe postures from one binary:** `KLAKE_MCP__READONLY` registers only read tools; localhost bind + optional bearer token keeps the write surface from being trivially exposed (D-10, D-11).
- **`--sse` is a name, not a transport:** the flag is retained for familiarity but the implementation is MCP Streamable HTTP; the deprecated HTTP+SSE transport is not used (MCP-02).

</specifics>

<deferred>
## Deferred Ideas

- **Background/async job tools** — long-running `crawl_all`/`process_crawled` return synchronously in v2.0 (D-12). A job-submit + poll tool surface (submit → job_id → status) is a future refinement, not in MCP-01's intent-tool scope.
- **Full auth / RBAC / multi-tenant MCP hosting** — v2.0 is localhost-default with an optional static bearer token (D-10). OAuth, per-user scopes, and remote (`0.0.0.0`) production hosting are deferred.
- **MCP resources & prompts primitives** — this phase exposes **tools** only. MCP `resources` (e.g. browse lineage/artifacts as addressable resources) and `prompts` are a natural later addition.
- **Per-tool rate limiting / quota** on the write tools — not requested for v2.0; noted so it isn't lost.
- **Additional skills beyond the four** (e.g. re-crawl scheduling, dedupe/curate, discover-sources) — SKILL-01 scopes exactly four; more can ship later against the same tool registry.

None of the above were requested as scope — captured so they aren't lost.

</deferred>

---

*Phase: 12-agent-surfaces*
*Context gathered: 2026-07-11*
