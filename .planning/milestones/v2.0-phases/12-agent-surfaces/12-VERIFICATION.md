---
phase: 12-agent-surfaces
verified: 2026-07-11T00:00:00Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 12: Agent Surfaces Verification Report

**Phase Goal:** AI agents can drive the whole lake through a curated, intent-level MCP tool surface plus static schema exports — all sharing one schema source of truth.
**Verified:** 2026-07-11
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | MCP server exposes 11 curated intent-level tools as thin shims over `pipeline/*.py` (never REST), one shared registry | ✓ VERIFIED | `registry.py` `TOOLS` has exactly 11 entries with module-level `assert len(TOOLS)==11` + duplicate-name assert. All handlers imported from `pipeline.*` / `lineage`; `test_handlers_are_pipeline_callables_not_api` asserts no `api.app` binding (passed). Names match spec exactly: search, ingest_url, crawl, crawl_all, process_crawled, add_source, list_sources, lineage, export, init_domain, stats. |
| 2 | `klake mcp` starts stdio (clean JSON-RPC, structlog off stdout) and `klake mcp --sse --port 3001` starts Streamable HTTP | ✓ VERIFIED | CLI verb `cmd_mcp` (app.py:1086) dispatches stdio vs `--sse`; `--port` default 3001. `stdio.py` performs fd-level `os.dup`/`os.dup2(2,1)` lockdown + structlog re-config to stderr. `http.py` uses `StreamableHTTPSessionManager` (not deprecated HTTP+SSE). **Behavior proven:** `test_stdio_stdout_is_only_json_rpc` drives initialize→tools/call end-to-end and asserts every stdout line is valid JSON-RPC with structlog probe on stderr (ran here, passed); `test_mcp_http.py` (7 tests) exercises the HTTP transport (ran here, passed). |
| 3 | `klake openapi` exports OpenAPI schema; generated `docs/openapi.json` committed | ✓ VERIFIED | `cmd_openapi` (app.py:1134) dumps `fastapi_app.openapi()` deterministically. `docs/openapi.json` git-tracked, 26 paths / 37 component schemas. `test_openapi_export.py` (3 tests) passed. |
| 4 | OpenAI tool defs auto-generated from Pydantic schemas; single source of truth, no drift (stdio==http==openapi==openai) | ✓ VERIFIED | `openai_defs.py` builds each def from `t.input_model.model_json_schema()` — same call as MCP `inputSchema`. `test_surface_parity.py` (15 tests) asserts normalized MCP==OpenAI==model_json_schema for all 11 tools plus OpenAPI-components parity for the 4 endpoint-backed models (ran, passed). `docs/openai_tools.json` regeneration is a no-op vs committed (MATCH). |
| 5 | Repo ships 4 Claude Code skills driving the lake through MCP tools | ✓ VERIFIED | `skills/{build-corpus,search-knowledge,add-source,export-dataset}.md` all present, git-tracked, reference only registry tool names. `test_skills_present.py` (22 tests) passed. |

**Score:** 5/5 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `src/knowledge_lake/agent/registry.py` | 11-tool single source of truth | ✓ VERIFIED | 11 ToolDefs, pipeline-only handlers, `registered_tools(readonly)` filter |
| `src/knowledge_lake/agent/server.py` | build_server list_tools+call_tool | ✓ VERIFIED | inputSchema from model_json_schema; async bridge via iscoroutinefunction; no asyncio.run |
| `src/knowledge_lake/agent/stdio.py` | fd-level stdout lockdown | ✓ VERIFIED | dup→dup2→logger reconfig→stdio_server(stdout=preserved); proven by lockdown integration test |
| `src/knowledge_lake/agent/http.py` | Streamable HTTP transport | ✓ VERIFIED | StreamableHTTPSessionManager, DNS-rebinding guard, closed CORS, constant-time bearer, Route not Mount |
| `src/knowledge_lake/agent/openai_defs.py` | OpenAI defs from registry | ✓ VERIFIED | Deterministic render; shared model_json_schema |
| `src/knowledge_lake/cli/app.py` | klake mcp / klake openapi verbs | ✓ VERIFIED | Both commands present and wired |
| `docs/openapi.json` | committed export | ✓ VERIFIED | Tracked, 26 paths |
| `docs/openai_tools.json` | committed export | ✓ VERIFIED | Tracked, 11 tools, regenerates no-op |
| `skills/*.md` | 4 Claude Code skills | ✓ VERIFIED | All 4 present + tracked |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| registry TOOLS | server.build_server | list_tools reads t.input_model.model_json_schema() | ✓ WIRED | proven by parity + list_tools tests |
| stdio.py / http.py | server.build_server | both call build_server(registered_tools(readonly)) | ✓ WIRED | stdio==http tool-set tests pass |
| openai_defs | registry model schema | shared model_json_schema() | ✓ WIRED | three-way parity gate green |
| add_source handler | pipeline.ingest.register_source | correct `register_source(url, name, ...)` no session | ✓ WIRED | fix commit 2d73db1; 2 regression tests pass |
| openapi verb | api.app FastAPI app | app.openapi() dumped to docs/openapi.json | ✓ WIRED | openapi_export tests pass |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| stdio JSON-RPC stream is clean (structlog off stdout) | pytest test_stdio_lockdown.py -m integration | 2 passed | ✓ PASS |
| HTTP Streamable transport serves tools + auth guards | pytest test_mcp_http.py -m integration | 7 passed | ✓ PASS |
| Surface parity (stdio==http==openapi==openai) | pytest test_surface_parity.py | 15 passed | ✓ PASS |
| add_source handler correct signature + hostname default | pytest test_tool_handlers.py | 12 passed | ✓ PASS |
| openai_tools.json regenerates as no-op | render_openai_tools_json(TOOLS) vs committed | MATCH | ✓ PASS |
| Full unit suite regression | pytest tests/unit | 520 passed, 2 xfailed, 39 xpassed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
| ----------- | -------------- | ----------- | ------ | -------- |
| MCP-01 | 12-01,02,03,05 | Curated intent-level MCP tools, thin pipeline shims, one registry | ✓ SATISFIED | Truth 1 |
| MCP-02 | 12-01,04,05,06,07 | stdio + Streamable HTTP start via klake mcp | ✓ SATISFIED | Truth 2 |
| SKILL-01 | 12-01,08 | 4 Claude Code skills ship | ✓ SATISFIED | Truth 5 |
| SKILL-02 | 12-01,07 | klake openapi + committed docs/openapi.json | ✓ SATISFIED | Truth 3 |
| SKILL-03 | 12-01,03,07,08 | Auto-generated OpenAI defs, no drift | ✓ SATISFIED | Truth 4 |

All 5 requirement IDs accounted for across plan frontmatter; none orphaned. REQUIREMENTS.md marks all 5 Complete.

### Anti-Patterns Found

None. No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/placeholder markers in any phase-modified file (`src/knowledge_lake/agent/`, `skills/`, `cli/app.py`).

### Deferred Warnings (from 12-REVIEW.md — do NOT block goal)

| ID | Issue | Impact on must_haves |
| -- | ----- | -------------------- |
| WR-01 | `build_http_app` factory path doesn't resolve token from `settings.mcp.token` | None on MH2 — the shipped `klake mcp --sse` path (app.py:1121) passes `token=settings.mcp.token` explicitly. Only affects direct `--factory` ASGI deployment. Security-posture choice deferred to user. |
| WR-03 | `process_crawled` swallows per-doc exceptions without logging | None on any must_have — observability gap, tool still functions. Deferred to user. |
| WR-04 | HTTP surface exposes 7 write tools unauthenticated by default (readonly=False, token=None) | None on MH2 — must_haves do not mandate authentication; localhost bind + Host guard mitigate. Documented D-10/D-11 posture decision deferred to user. |

The CR-01 BLOCKER (`add_source` TypeError) is confirmed FIXED in commit `2d73db1` with two passing regression tests; `_add_source_handler` now calls `register_source(url, name, domain=..., license_type=...)` with no session arg and defaults name to the URL hostname.

### Gaps Summary

None. All 5 success criteria are observably true in the codebase and backed by passing behavioral tests (unit + the two integration suites for the stdio/HTTP runtime invariants, both runnable without live services). The registry is the single 11-tool source of truth; every surface (stdio, HTTP, OpenAI defs, OpenAPI components) derives argument schemas from the same `model_json_schema()` call, and the parity gate proves no drift. The three deferred review warnings are security-posture/observability choices that do not affect goal achievement.

---

_Verified: 2026-07-11_
_Verifier: Claude (gsd-verifier)_
