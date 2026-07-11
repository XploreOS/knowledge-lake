---
phase: 12-agent-surfaces
plan: "08"
subsystem: agent-surfaces
status: complete
tags: [mcp, surface-parity, schema-drift, claude-skills, tests]
requires:
  - agent/registry.py (TOOLS, registered_tools)
  - agent/server.py (build_server list_tools handler)
  - agent/openai_defs.py (openai_tool_defs)
  - docs/openapi.json (committed export from Plan 07)
provides:
  - tests/unit/test_surface_parity.py (real D-04 drift gate)
  - skills/build-corpus.md
  - skills/search-knowledge.md
  - skills/add-source.md
  - skills/export-dataset.md
  - tests/unit/test_skills_present.py (registry-tracking gate)
affects:
  - closes Phase 12 (last wave) — no downstream consumers in this phase
tech-stack:
  added: []
  patterns:
    - "normalize()/canonical() reconcile Pydantic-v2 vs FastAPI schema noise: drop title + null defaults, canonicalize $defs/definitions/components-schemas $refs to #/DEFS/, coerce int-valued floats"
    - "MCP inputSchema derived from the live build_server list_tools handler (via anyio.run) — parity asserts what the server emits, not just what the registry could emit"
    - "Skill stale-tool guard: self-maintaining allowlist = live union of tool input-field names + literal enum/return values; residual backticked identifiers must be registry tools"
key-files:
  created:
    - skills/build-corpus.md
    - skills/search-knowledge.md
    - skills/add-source.md
    - skills/export-dataset.md
  modified:
    - tests/unit/test_surface_parity.py
    - tests/unit/test_skills_present.py
decisions:
  - "normalize() extended past the Plan-01 title/$ref spec to also drop default:null, canonicalize #/components/schemas refs, and coerce int-valued floats — the exact residual noise between model_json_schema() and FastAPI's app.openapi()"
  - "MCP leg invokes the real ListToolsRequest handler on build_server(tools) rather than reading model_json_schema() directly, so the gate proves server emission end-to-end"
  - "Skill tool-reference detection excludes non-tool backticked tokens via a live-derived field-name allowlist plus a small literal set (enum values, return keys, prose booleans/domains)"
metrics:
  duration: ~10m
  completed: 2026-07-11
  tasks: 2
  files: 6
---

# Phase 12 Plan 08: Surface Parity Gate + Claude Code Skills Summary

Shipped the phase's correctness gate and its user-facing journeys: a real
`test_surface_parity.py` proving **stdio == http == openapi == openai** for all 11
tools (SKILL-03 / D-04 no-drift), and the four repo-visible Claude Code skills that
drive the lake by MCP tool name (SKILL-01) with a presence test that keeps them
locked to the single tool registry.

## What Was Built

### Task 1 — Surface parity gate (`tests/unit/test_surface_parity.py`)

Replaced the Wave-0 xfail scaffold with 15 real assertions. The `normalize()` helper
was extended beyond the Plan-01 title/`$ref` spec to reconcile the full residual
noise between Pydantic's `model_json_schema()` and FastAPI's `app.openapi()`:

1. drop every `title`,
2. drop `default: null` (FastAPI omits null defaults; Pydantic keeps them),
3. canonicalize `$ref` — `#/$defs/`, `#/definitions/`, **and** `#/components/schemas/`
   all collapse to `#/DEFS/`,
4. coerce integer-valued floats to `int` (FastAPI emits `10000.0` for an `le=10000`
   bound where Pydantic emits `10000`),
5. sort keys.

The four surfaces are all derived **live** (no hardcoded schemas, per prohibition):

- **MCP inputSchema** — invokes the real `ListToolsRequest` handler on
  `build_server(tools)` via `anyio.run`, reading the emitted `Tool.inputSchema`.
- **OpenAI parameters** — from `openai_tool_defs(TOOLS)`.
- **model_json_schema** — the shared `input_model` schema.
- **OpenAPI components** — `docs/openapi.json` `components/schemas` for the four
  endpoint-backing models (`SourceCreate`, `CrawlJobCreate`, `ExportRequest`,
  `DomainLoadRequest`); the leg asserts `>= {those four}` so it can never go vacuous.

Additional legs assert stdio and http emit identical tool-name sets, and the
read-only posture (`registered_tools(True) == {search, list_sources, lineage, stats}`)
is identical across both transports.

### Task 2 — Four skills + presence test

Created four repo-root `skills/*.md` files, each with `name`/`description`
frontmatter and a workflow body that drives its D-16 journey by MCP tool name:

- **build-corpus.md** — `add_source` → `crawl`/`crawl_all` → `process_crawled` → `search`.
- **search-knowledge.md** — filtered `search` (`source_name`/`format`/`tags`/`domain`) + `lineage`.
- **add-source.md** — `add_source` (register) / `ingest_url` (one-shot fetch+ingest).
- **export-dataset.md** — `export` (rag-corpus / pretrain / finetune) → `stats`.

`tests/unit/test_skills_present.py` (22 assertions) enforces: exactly four skill
files (no fifth — SKILL-01 scope), valid `name`/`description` frontmatter with
`name` matching the filename, each journey's tools present in the body **and** in
`TOOLS`, and — the T-12-SKILL guard — every tool-shaped backticked token that is not
a known input-field name or literal value must be a real registry tool.

## Task Commits

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Real surface-parity gate (stdio == http == openapi == openai) | `bbf6d26` | tests/unit/test_surface_parity.py |
| 2 | Four Claude Code skills + registry-tracking presence test | `026d42b` | skills/*.md (×4), tests/unit/test_skills_present.py |

## Verification

- `uv run pytest tests/unit/test_surface_parity.py -q` → **15 passed**.
- `uv run pytest tests/unit/test_skills_present.py -q` → **22 passed**.
- `uv run pytest tests/unit -q` → **518 passed, 2 xfailed, 39 xpassed** (full unit gate green; all Wave-0 RED tests for this plan now green).
- `uv run ruff check` on both test files → clean.
- Parity is a real gate: the three registry surfaces are byte-compared per tool after
  normalization, and the MCP leg reads actual server emission — mutating any tool's
  `input_model` turns `test_three_way_parity_all_tools` red.

**Full-suite note (out of scope):** `uv run pytest -q` (whole repo) shows 7 failures
+ 75 errors, all in `tests/integration/*` (test_lineage, test_migrations,
test_dedup_noop, test_ingest_url_dedup, test_upload). These require live Postgres/
MinIO services that are not running in this environment — they are pre-existing
infra-dependent tests, unaffected by this plan (which only adds unit tests and
Markdown). No code defect; not deferred as a code item.

## Must-Haves Satisfied

| Truth | Evidence |
| ----- | -------- |
| For every tool, normalized MCP inputSchema == OpenAI parameters == model_json_schema (SKILL-03, D-04) | `test_three_way_parity_all_tools` + three per-leg tests over all 11 tools |
| The tool set is identical across stdio and HTTP (same Server) | `test_stdio_http_tool_name_sets_identical` + `test_readonly_posture_is_identical_across_transports` |
| Each tool's shared model appears identically (normalized) in docs/openapi.json where it backs an endpoint | `test_openapi_components_match_registry_models` (SourceCreate, CrawlJobCreate, ExportRequest, DomainLoadRequest) |
| Four skills with name/description frontmatter driving end-to-end journeys by MCP tool name (D-16) | four `skills/*.md`; `test_skill_has_valid_frontmatter`, `test_skill_references_its_journey_tools` |

## Deviations from Plan

**1. [Rule 2 — Missing critical functionality] normalize() extended past title/$ref**
- **Found during:** Task 1
- **Issue:** The Plan-01 `normalize()` only dropped `title` and canonicalized `$defs`/`definitions` `$ref`s. Comparing the registry `model_json_schema()` to `docs/openapi.json` components still failed on three systematic FastAPI-vs-Pydantic artifacts: `default: null` (FastAPI omits), `#/components/schemas/` ref root (vs Pydantic `#/$defs/`), and int-valued float constraints (`10000.0` vs `10000`).
- **Fix:** Extended `normalize()` to drop null defaults, canonicalize `#/components/schemas/` into the same `#/DEFS/` token, and coerce integer-valued floats to `int`. Added five helper unit tests covering each new behavior. This is sanctioned normalization (the plan mandates comparing via `normalize()`, Pitfall 2), not schema tampering.
- **Files modified:** tests/unit/test_surface_parity.py
- **Commit:** `bbf6d26`

**2. [Rule 2 — Missing critical functionality] Presence test hardening**
- **Found during:** Task 2
- **Issue:** The plan asks the presence test to assert "exactly four" skills and that "every tool name a skill mentions exists in TOOLS". A naive token scan flags input-field names and enum/return values (e.g. `top_k`, `finetune`, `processed`) as if they were tools.
- **Fix:** Built the stale-tool guard on a self-maintaining allowlist = the live union of every tool's `input_model` property names plus a small literal set (enum values, return keys, prose booleans/domains). Only residual backticked identifiers must be registry tools — so the guard fires on a genuinely stale/foreign tool reference without false positives.
- **Files modified:** tests/unit/test_skills_present.py
- **Commit:** `026d42b`

## Threat Surface

Both threat-register mitigations are now live tests, no new surface introduced:
- **T-12-DRIFT** (surface schema drift) — `test_surface_parity.py` asserts normalized
  equality across MCP/OpenAI/OpenAPI + identical stdio/http tool sets; any divergence
  fails loudly (D-04).
- **T-12-SKILL** (skill references stale tool) — `test_skills_present.py` asserts every
  tool-shaped token a skill mentions exists in `TOOLS`; a renamed/removed tool cannot be
  referenced without a red test.

No stubs. No new endpoints, auth paths, or schema changes.

## Self-Check: PASSED

- FOUND: tests/unit/test_surface_parity.py
- FOUND: tests/unit/test_skills_present.py
- FOUND: skills/build-corpus.md
- FOUND: skills/search-knowledge.md
- FOUND: skills/add-source.md
- FOUND: skills/export-dataset.md
- FOUND commit: bbf6d26
- FOUND commit: 026d42b
