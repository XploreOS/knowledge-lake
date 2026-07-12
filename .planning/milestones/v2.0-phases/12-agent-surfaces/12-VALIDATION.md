---
phase: 12
slug: agent-surfaces
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-11
validated: 2026-07-12
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `12-RESEARCH.md` §"Validation Architecture".
> **Post-execution audit (2026-07-12): all Wave-0 tests landed and are green — nyquist-compliant.**

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8+ with `pytest-asyncio` (`asyncio_mode = "auto"`) — already present |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`) |
| **Quick run command** | `uv run pytest tests/unit/test_surface_parity.py -x` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~90 seconds (full suite; targeted unit tests <5s) |

---

## Sampling Rate

- **After every task commit:** Run the task's targeted unit test (e.g. `uv run pytest tests/unit/test_surface_parity.py -x`)
- **After every plan wave:** Run `uv run pytest tests/unit -q`
- **Before `/gsd-verify-work`:** Full suite `uv run pytest -q` must be green
- **Max feedback latency:** ~90 seconds

---

## Per-Task Verification Map

| Req ID | Behavior | Test Type | Automated Command | File Exists |
|--------|----------|-----------|-------------------|-------------|
| MCP-02 | stdio emits only JSON-RPC bytes (stdout lockdown) — **first-task gate** | integration | `uv run pytest tests/integration/test_stdio_lockdown.py -x` | ✅ |
| MCP-01 | 11 tools registered; handlers call `pipeline/*` not REST | unit | `uv run pytest tests/unit/test_tool_registry.py -x` | ✅ |
| MCP-01 | each handler shims the correct pipeline fn (mock service, assert call) | unit | `uv run pytest tests/unit/test_tool_handlers.py -x` | ✅ |
| MCP-02 | Streamable-HTTP app starts at 127.0.0.1; bearer enforced when set; non-localhost host rejected | integration | `uv run pytest tests/integration/test_mcp_http.py -x` | ✅ |
| MCP-02 | `KLAKE_MCP__READONLY` registers only read tools | unit | `uv run pytest tests/unit/test_readonly.py -x` | ✅ |
| SKILL-02 | `klake openapi` writes deterministic `docs/openapi.json` | unit | `uv run pytest tests/unit/test_openapi_export.py -x` | ✅ |
| SKILL-03 | parity: stdio == http == openapi == openai (normalized) | unit | `uv run pytest tests/unit/test_surface_parity.py -x` | ✅ |
| SKILL-01 | four skill files exist, valid frontmatter, reference tool names | unit | `uv run pytest tests/unit/test_skills_present.py -x` | ✅ |
| D-05 | extracted `process_crawled`/`list_sources`/`stats`/`init_domain` return documented shapes; CLI still works | unit | `uv run pytest tests/unit/test_pipeline_extractions.py -x` | ✅ |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

All 9 mapped test files exist and pass (85 passed, audited 2026-07-12). Every phase requirement (MCP-01, MCP-02, SKILL-01, SKILL-02, SKILL-03) has automated behavioral coverage — 0 MISSING, 0 PARTIAL.

---

## Wave 0 Requirements

- [x] `tests/integration/test_stdio_lockdown.py` — MCP-02, the **first-task gate** (self-test asserting only JSON-RPC on stdout)
- [x] `tests/unit/test_surface_parity.py` + a shared `normalize(schema)` helper — SKILL-03 / D-04 (Pydantic v2 `$defs`/`$ref`/`title` normalization)
- [x] `tests/unit/test_tool_registry.py`, `test_tool_handlers.py`, `test_readonly.py` — MCP-01 / D-11
- [x] `tests/integration/test_mcp_http.py` — MCP-02 / D-09 / D-10 (`httpx` against uvicorn or Starlette `TestClient`; assert `TransportSecuritySettings.allowed_hosts` populated)
- [x] `tests/unit/test_openapi_export.py`, `test_skills_present.py`, `test_pipeline_extractions.py`
- [x] Framework install: none — pytest + pytest-asyncio already present

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end MCP tool call from a live Claude Code / MCP client over stdio | MCP-01/02 | Requires an external MCP client process attaching to `klake mcp` | Start `uv run klake mcp`, attach an MCP client, call `search`, confirm JSON result and no stdout corruption |
| Skills drive real journeys when loaded by Claude Code | SKILL-01 | Requires the Claude Code runtime to load and execute the skill | Load `skills/build-corpus.md` in Claude Code, confirm it invokes the MCP tools by name end-to-end |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 90s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated 2026-07-12 — all requirements have automated coverage; the 2 manual-only items are inherently runtime-bound (live MCP client / Claude Code skill loading) and documented above.

---

## Validation Audit 2026-07-12

| Metric | Count |
|--------|-------|
| Requirements | 5 (MCP-01, MCP-02, SKILL-01, SKILL-02, SKILL-03) |
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |
| Manual-only | 2 (runtime-bound, documented) |

Audited in **State A** against the completed phase: all Wave-0 test files landed and are green (85 passed across the 9 mapped files; full suite 530 passed). No tests needed to be generated. Verdict: **NYQUIST-COMPLIANT**.
