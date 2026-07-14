---
phase: 15
slug: query-router
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-14
---

# Phase 15 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `15-RESEARCH.md` § Validation Architecture. Task IDs are filled
> in by the planner; requirement-level commands below are authoritative.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`[tool.pytest.ini_options]`, `testpaths = ["tests"]`, `addopts = "-v"` in `pyproject.toml`) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/unit/test_route.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~5s for route unit tests (no DB — `search`/`tree_search` mocked); full suite dominated by existing tests |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit/test_route.py -x`
- **After every plan wave:** Run `uv run pytest tests/unit -x` (surface tests + schema parity)
- **Before `/gsd-verify-work`:** Full suite must be green — critically includes `tests/unit/test_openapi_export.py` (the deterministic-dump byte guard)
- **Max feedback latency:** ~10 seconds (unit tests only; no network, no DB)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD (planner) | — | 0 | ROUTE-02 | — | Each trigger category (section/page, comparison, structural) → `classify_route` returns `("tree", <category>)` | unit (table-driven) | `uv run pytest tests/unit/test_route.py -k classify -x` | ❌ W0 | ⬜ pending |
| TBD (planner) | — | 0 | ROUTE-03 | — | No structural signal → `classify_route` returns `("chunk","no_match")`; `routed_search` calls `search()` unchanged | unit | `uv run pytest tests/unit/test_route.py -k no_match -x` | ❌ W0 | ⬜ pending |
| TBD (planner) | — | 0 | ROUTE-01 | — | `route="tree"` and `route="two_stage"` dispatch identically to `tree_search()` (alias equivalence) | unit (mock `tree_search`) | `uv run pytest tests/unit/test_route.py -k alias -x` | ❌ W0 | ⬜ pending |
| TBD (planner) | — | 0 | ROUTE-01 | — | Route resolution: per-call wins; else `settings.router.default_route`; `Literal` rejects bad value at load | unit | `uv run pytest tests/unit/test_route.py -k settings -x` | ❌ W0 | ⬜ pending |
| TBD (planner) | — | 0 | ROUTE-01 (D-05) | — | auto tree→zero hits→chunk fallback; explicit route→no fallback; both-empty→`[]` | unit (mock both callees) | `uv run pytest tests/unit/test_route.py -k fallback -x` | ❌ W0 | ⬜ pending |
| TBD (planner) | — | 0 | ROUTE-01 (D-06) | — | Every call emits one structlog event: route chosen + matched category (or `operator_override`/`no_match`) + fallback flag | unit (capture logs) | `uv run pytest tests/unit/test_route.py -k log -x` | ❌ W0 | ⬜ pending |
| TBD (planner) | — | 1 | ROUTE-04 | — | REST `?route=bogus`→422; `?route=tree` forwards `route="tree"` into `routed_search` | unit (TestClient + patch) | `uv run pytest tests/unit/test_api_route.py -x` | ❌ W0 | ⬜ pending |
| TBD (planner) | — | 1 | ROUTE-04 | — | CLI `--route bogus`→exit 1; `--route tree` calls `routed_search(route="tree")` | unit (typer runner + patch) | `uv run pytest tests/unit/test_cli_route.py -x` | ❌ W0 | ⬜ pending |
| TBD (planner) | — | 1 | ROUTE-04 | — | `SearchParams.route` in `model_json_schema()` → MCP inputSchema + OpenAI defs; `docs/openapi.json` regenerated & byte-identical | unit | `uv run pytest tests/unit/test_openapi_export.py tests/unit/test_tool_registry.py -x` | ✅ (extend) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_route.py` — classifier table (all 3 categories + no_match), alias equivalence (`tree`==`two_stage`), settings precedence, the three D-05 fallback branches, and D-06 log emission. Mock `search`/`tree_search` at `knowledge_lake.pipeline.route.search` / `.tree_search` (mirror `test_tree_search.py`'s module-level patch style).
- [ ] `tests/unit/test_api_route.py` — TestClient `?route=` forwarding + 422 on bad value (mirror `test_api_search_mode.py` structure).
- [ ] `tests/unit/test_cli_route.py` — typer `--route` forwarding + exit-1 on bad value (mirror `test_cli_search_mode.py`).
- [ ] `tests/unit/test_openapi_export.py` — no new file; the existing byte-identical deterministic-dump test will fail RED until `docs/openapi.json` is regenerated via `klake openapi` (the desired RED→GREEN signal for the OpenAPI regeneration task).
- [ ] Framework install: none — pytest already present.

---

## Manual-Only Verifications

*All phase behaviors have automated verification.* Routing is a deterministic dispatch layer (regex + function dispatch); no manual/visual verification is needed.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
