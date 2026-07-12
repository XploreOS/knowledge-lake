---
phase: 12-agent-surfaces
audited_at: 2026-07-12
asvs_level: 1
block_on: high
threats_total: 13
threats_closed: 13
threats_open: 0
verdict: SECURED
register_source: PLAN threat_model blocks (register_authored_at_plan_time=true)
---

# Phase 12 — Agent Surfaces: Security Audit

**Scope:** MCP server (stdio + Streamable HTTP), OpenAPI/OpenAI tool-def exports,
Claude Code skills. The 13-threat register was authored at plan time across the 8
`12-0N-PLAN.md` threat_model blocks; this audit verifies each declared mitigation
is **present in the implemented code** at ASVS L1 depth (mitigation exists in the
cited file). It does **not** scan for new threats.

**Verdict: SECURED — 13/13 threats CLOSED, 0 open, 0 blocking.**

Severity gate: `block_on: high`. No open threats at any severity, so
`threats_open = 0`.

## Threat Verification

| Threat ID | Category | Severity | Disposition | Status | Evidence |
|-----------|----------|----------|-------------|--------|----------|
| T-12-SC | Tampering | high | mitigate | CLOSED | `pyproject.toml:48` `"mcp==1.28.1"` (exact pin, no extras); `uv.lock:2144` `specifier = "==1.28.1"`; `uv.lock:2473-2475` resolved `name = "mcp"`, `version = "1.28.1"`, pypi registry |
| T-12-01 | Spoofing | high | mitigate | CLOSED | `agent/http.py:155-159` `TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=[f"{host}:{port}", f"localhost:{port}"], allowed_origins=[])`; integration proof `tests/integration/test_mcp_http.py:98` (foreign Host rejected), `:116` (bound Host accepted) |
| T-12-02 | Elevation of Privilege | high | mitigate | CLOSED | Localhost bind default `config/settings.py:327` `host = "127.0.0.1"`, threaded via `agent/http.py:140-143` + `cli/app.py:1103,1139`; read-only filter `agent/registry.py:374-389` `registered_tools()`; **fail-closed** guard `cli/app.py:1123-1127` (raises `typer.BadParameter` when write tools would be served over HTTP with no token and not readonly — commit 5343d88); optional bearer (see T-12-04); unit `tests/unit/test_readonly.py`, integration `tests/integration/test_mcp_http.py:190` |
| T-12-03 | Tampering/Info Disclosure | high | mitigate | CLOSED | No new fetch path: `agent/registry.py:294-303` `ingest_url` tool → `_ingest_url_handler` → `pipeline/ingest.py:ingest_url`; existing SSRF boundary `pipeline/ingest.py:99` `validate_public_url` (blocks non-https, RFC-1918, 169.254 IMDS, loopback, IPv6 ULA, IPv4-mapped) called at `ingest.py:376` (entry) and `:191` (per-redirect-hop) |
| T-12-04 | Information Disclosure | medium | mitigate | CLOSED | `agent/http.py:90` `secrets.compare_digest(provided, self._expected)` (never `==`); middleware attached **only** when token set `agent/http.py:170`; test `tests/integration/test_mcp_http.py:175` asserts `compare_digest` present and no `==` in dispatch |
| T-12-05 | Tampering | high | mitigate | CLOSED | `agent/stdio.py:75` `os.dup(1)` (preserve) → `:78` `os.dup2(2, 1)` (fd 1 → stderr) → `:93-108` structlog/stdlib logging + warnings → stderr → `:119` `stdio_server(stdout=preserved)`; wired at `cli/app.py:1144-1147` (`anyio.run(run_stdio, ...)`); subprocess self-test `tests/integration/test_stdio_lockdown.py:143` (every stdout line is JSON-RPC; probe on stderr only) |
| T-12-06 | Tampering | medium | mitigate | CLOSED | `api/schemas.py:771-777` `DomainLoadRequest.name` `pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$"`; `init_domain` tool binds this model `agent/registry.py:358-367`; defense-in-depth CLI guard `cli/app.py:991-998` `_DOMAIN_NAME_RE.fullmatch(domain)` before `load_domain` |
| T-12-07 | Tampering | medium | mitigate | CLOSED | Layer 1 — SDK `@server.call_tool()` default `validate_input=True` (`.venv/.../mcp/server/lowlevel/server.py:498`, validates against inputSchema); Layer 2 — explicit Pydantic re-validation `agent/server.py:93` `model = tdef.input_model(**arguments)`; per-field bounds in `api/schemas.py` (e.g. `top_k` `ge=1,le=100`; `max_pages` `ge=1,le=10000`) |
| T-12-13 | Information Disclosure | low | mitigate | CLOSED | `agent/server.py:106-113` expected `(ValueError, LookupError)` → `CallToolResult(isError=True)` readable text; `:128-136` `TrainEvalContaminationError` → readable isError; `:138` unexpected exceptions propagate (SDK-wrapped, no leak). CR-01 fix commit 654f54f switched to `%`-style logging so the readable message is no longer masked by a `TypeError`; regression `tests/unit/test_tool_handlers.py:288,334` assert `content[0].text` verbatim |
| T-12-CORS | Spoofing | low | mitigate | CLOSED | `agent/http.py:158-159` `allowed_origins=[]` inside `TransportSecuritySettings` — browser origins stay closed |
| T-12-INFO | Information Disclosure | low | accept | CLOSED | Accepted risk logged below. Committed exports present: `docs/openapi.json`, `docs/openai_tools.json` — public schema shapes only, generated deterministically from Pydantic `model_json_schema()` (`agent/openai_defs.py:43`, `cli/app.py:1166` `sort_keys=True`); no secrets, tokens, or endpoints in payload |
| T-12-DRIFT | Tampering | medium | mitigate | CLOSED | `tests/unit/test_surface_parity.py` asserts normalized equality: MCP inputSchema == OpenAI parameters == `model_json_schema` (`:238` three-way gate) + OpenAPI components (`:282`) + identical stdio/http tool-name sets (`:256`, `:270`) |
| T-12-SKILL | Spoofing | low | mitigate | CLOSED | `tests/unit/test_skills_present.py:148` `test_skill_mentions_only_registry_tools` — every tool-shaped backticked token in a skill must exist in live `TOOLS`; four skills present under `skills/` (add-source, build-corpus, export-dataset, search-knowledge) |

## Accepted Risks Log

### T-12-INFO — Committed OpenAPI / OpenAI tool-def JSON exports (low, accepted)
- **What:** `docs/openapi.json` and `docs/openai_tools.json` are committed to the repo.
- **Why acceptable:** Both are generated deterministically from the Pydantic
  `input_model.model_json_schema()` of already-public tool/endpoint contracts.
  They contain only argument *shapes* (names, types, bounds, descriptions) — no
  secrets, bearer tokens, credentials, internal hostnames, or private endpoints.
  The OpenAI export is `sort_keys=True` + trailing newline for a no-op re-dump
  diff (`cli/app.py:1166`), and the OpenAPI leg is drift-gated by
  `test_surface_parity.py::test_openapi_components_match_registry_models`.
- **Disposition:** accept (planner-declared). Verified present and matches the
  L1 accept criterion (documented rationale in this log).

## Unregistered Flags

**None.** Only `12-03-SUMMARY.md` carries a `## Threat Flags` section; it maps to
already-registered threats **T-12-07** (Pydantic tool-arg validation) and
**T-12-06** (`init_domain` / `DomainLoadRequest` path-traversal guard). No new
attack surface appeared during implementation without a threat mapping. The
remaining SUMMARY files (12-01, 12-02, 12-04..12-08) declare no new
trust-boundary surface.

## Recent-Fix Confirmation (from 12-REVIEW-FIX.md)

The two code-review passes cited in the audit brief were verified in the current tree:
- **CR-01 / T-12-13** (commit 654f54f): both `log.warning` calls in
  `agent/server.py:109,132` use `%`-style args, not structlog kwargs; regression
  tests assert `content[0].text` (`test_tool_handlers.py:288,334`). Confirmed.
- **WR-04 / T-12-02** (commit 5343d88): fail-closed `typer.BadParameter` guard
  present at `cli/app.py:1123-1127`. Confirmed.
- **WR-01 / T-12-02+T-12-04** (commit 16e1448): `agent/http.py:47` `_UNSET`
  sentinel + `:144-145` resolves `token` from `settings.mcp.token` when omitted,
  so direct/factory callers are not fail-open. Confirmed.

## Audit Method Notes

- ASVS L1: each declared mitigation confirmed **present** at its cited boundary
  via direct read/grep of the implementation file (not documentation/intent).
- Implementation files were treated as read-only; nothing was modified. Only this
  `12-SECURITY.md` was written.
- `threats_open = 0`: no OPEN threats at or above the `high` block threshold (in
  fact none at any severity).
