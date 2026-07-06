---
phase: 04-enrichment-embedding-search
plan: 02
subsystem: enrichment
tags: [litellm, pydantic, tenacity, fastapi, typer, dagster]

# Dependency graph
requires:
  - phase: 04-enrichment-embedding-search
    provides: "Plan 01's quality_score ORM column, EnrichSettings/IndexSettings, and create_enriched_artifact/get_llm_spend/record_llm_spend repo functions"
provides:
  - "pipeline/deterministic.py — non-LLM title/dates/headings extraction (ENRICH-02)"
  - "llm/pricing.py — bootstrap_llm_pricing()/compute_call_cost() (ENRICH-05)"
  - "pipeline/enrich.py — enrich_document() cache-check -> budget-check -> single cheap_model LiteLLM call -> validate -> registry write (ENRICH-01, 03, 04, 05)"
  - "klake enrich CLI, POST /enrich API, enrich_document Dagster asset (D-02 wiring)"
affects: [04-03-index-search]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deterministic-first extraction merged into LLM-judged metadata at persist time (title never LLM-derived)"
    - "Cache key = sha256(cleaned_content_hash:prompt_version), re-checked once before the LLM call and again immediately before the registry write to guard a concurrent identical run"
    - "Budget check reads llm_spend before any LLM call; on breach, halts with a status dict — never raises (D-05)"

key-files:
  created:
    - src/knowledge_lake/pipeline/deterministic.py
    - src/knowledge_lake/llm/__init__.py
    - src/knowledge_lake/llm/pricing.py
    - src/knowledge_lake/pipeline/enrich.py
    - tests/unit/test_deterministic.py
    - tests/unit/test_enrich.py
  modified:
    - src/knowledge_lake/api/schemas.py
    - src/knowledge_lake/cli/app.py
    - src/knowledge_lake/api/app.py
    - src/knowledge_lake/dagster_defs/assets.py
    - src/knowledge_lake/dagster_defs/definitions.py

key-decisions:
  - "enrich_document() always parents the enriched_document artifact on the cleaned_document artifact (never parsed_document), enforced with an explicit artifact_type check that raises ValueError otherwise (D-01)"
  - "Deterministic title merged into persisted metadata_['title'] at write time since EnrichmentResult has no title field of its own — regression-tested by fetching the persisted artifact and asserting its title matches extract_deterministic_fields() output"
  - "enrich_document Dagster asset is a parallel branch off clean_document (same dependency as chunk_document, neither blocks the other) — mirrors the existing D-01 fan-out pattern"

patterns-established:
  - "In-memory SQLite unit-test harness for pipeline functions that call get_session() internally: monkeypatch knowledge_lake.registry.db.get_engine to return a StaticPool-backed sqlite engine so multiple independent get_session() calls inside the function under test all see the same committed data"

requirements-completed: [ENRICH-01, ENRICH-02, ENRICH-03, ENRICH-04, ENRICH-05, ENRICH-06]  # Checkpoint (live Bedrock smoke test) resolved by human-authorized live test; see "Next Phase Readiness" below and commit ac299e1.

coverage:
  - id: D1
    description: "pipeline/deterministic.py extracts title/dates/headings from already-computed ParsedDoc data with zero LLM/network/DB calls"
    requirement: "ENRICH-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_deterministic.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "enrich_document() makes exactly one litellm.completion() call via the cheap_model task alias, validates the JSON response against EnrichmentResult, and persists an enriched_document artifact parented on the cleaned_document artifact with the deterministic title merged in"
    requirement: "ENRICH-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_enrich.py::test_enrich_produces_valid_result"
        status: pass
    human_judgment: false
  - id: D3
    description: "Re-calling enrich_document() for the same cleaned artifact + prompt_version is a cache hit — no second LLM call"
    requirement: "ENRICH-04"
    verification:
      - kind: unit
        ref: "tests/unit/test_enrich.py::test_enrich_cache_hit_is_noop"
        status: pass
    human_judgment: false
  - id: D4
    description: "enrich_document() halts gracefully with status=skipped_budget_exceeded when llm_spend already meets/exceeds the budget cap, without calling the LLM or raising"
    requirement: "ENRICH-05"
    verification:
      - kind: unit
        ref: "tests/unit/test_enrich.py::test_budget_exceeded_halts_gracefully"
        status: pass
    human_judgment: false
  - id: D5
    description: "enrich_document() returns status=skipped_enrichment_failed (never raises) when litellm.completion fails on every retry attempt"
    requirement: "ENRICH-05"
    verification:
      - kind: unit
        ref: "tests/unit/test_enrich.py::test_llm_call_failure_is_skipped_not_raised"
        status: pass
    human_judgment: false
  - id: D6
    description: "klake enrich, POST /enrich, and the enrich_document Dagster asset all call the same pipeline.enrich.enrich_document() with no duplicated logic"
    requirement: "ENRICH-01"
    verification:
      - kind: unit
        ref: "tests/unit/ full suite (260 passed) — CLI command registration, API route registration, Dagster asset-graph membership verified via acceptance-criteria commands"
        status: pass
    human_judgment: false
  - id: D7
    description: "A human has confirmed a live klake enrich call against the real Bedrock-backed LiteLLM proxy succeeds (status=enriched) and that a second identical call is a cache no-op (status=cached)"
    verification:
      - kind: manual
        ref: "Human-authorized live test against the real Bedrock-backed LiteLLM proxy (user set LITELLM_MASTER_KEY in .env and restarted the litellm container). Six real bugs were found and fixed during the test, all committed in ac299e1 (missing openai/ provider-prefix on litellm.completion()/litellm.embedding() calls plus Settings.litellm_api_key + resolver.py wiring; missing DATABASE_URL for the LiteLLM proxy via a new litellm_storage Postgres database; infra/litellm/config.yaml master_key fixed from shell-style ${VAR} to LiteLLM's os.environ/VAR syntax; config.yaml litellm_params fixed from nonexistent aws_bedrock_api_key to the generic api_key field; Claude model IDs replaced with real cross-region inference-profile IDs (us.anthropic.claude-haiku-4-5-20251001-v1:0, us.anthropic.claude-sonnet-4-5-20250929-v1:0) verified live against AWS ListFoundationModels/ListInferenceProfiles; defensive markdown-fence-stripping added in enrich.py/scorer.py before model_validate_json()/json.loads()). Live results: `uv run klake enrich doc_019f3059-c9b1-77c3-bcb5-f0f2742a859b src_019f261f-0698-76e3-912b-8f82df31f051` -> status: enriched, quality_score: 0.92, artifact_id: doc_019f36b9-b10f-7032-9562-b5685dcd54de, cost_usd: 0.0007455; identical second call -> status: cached, cached: True, same artifact_id (ENRICH-04 cache-hit confirmed, no second LLM call); full unit suite `uv run pytest tests/unit/ -q` -> 260 passed after the fixes."
        status: pass
    human_judgment: true
    rationale: "RESEARCH.md Open Question #2 could not be resolved without a live AWS Bedrock credential and a running LiteLLM proxy. Resolved: user explicitly authorized the live test, then authorized fixing the infra/code gaps discovered, then personally set LITELLM_MASTER_KEY and restarted the litellm container. Checkpoint approved based on the live evidence above; fixes committed in ac299e1."

# Metrics
duration: 8min (through Task 3) + checkpoint resolution (Task 4, ac299e1)
completed: 2026-07-06
status: complete
---

# Phase 4 Plan 2: Enrichment Pipeline (LLM-judged Metadata) Summary

**pipeline/deterministic.py + llm/pricing.py + pipeline/enrich.py deliver a cached, budget-capped single-call LiteLLM enrichment producing enriched_document artifacts, wired into klake enrich / POST /enrich / a parallel Dagster asset — the blocking live-Bedrock-smoke-test checkpoint is RESOLVED via a human-authorized live test (commit ac299e1)**

## Performance

- **Duration (through Task 3):** 8 min
- **Checkpoint resolved:** 2026-07-06 (live Bedrock smoke test run and approved; six blocking gaps found and fixed in ac299e1)
- **Tasks completed:** 4 of 4 (Task 4 checkpoint resolved by human-authorized live test)
- **Files modified:** 11 (6 created, 5 modified) + checkpoint-resolution fixes in ac299e1 (see below)

## Accomplishments
- `pipeline/deterministic.py`: `extract_title()`/`extract_dates()`/`extract_headings()`/`extract_deterministic_fields()` — pure, zero-LLM, zero-DB, zero-network transform reusing already-computed `ParsedDoc.metadata`/`Section` data (ENRICH-02, D-02)
- `llm/pricing.py`: `bootstrap_llm_pricing()` registers the project's configured Bedrock model IDs with LiteLLM's cost map (never raises); `compute_call_cost()` computes real USD cost with a token-count-based fallback (ENRICH-05, RESEARCH.md Pitfall 1)
- `pipeline/enrich.py`: `EnrichmentResult` (field-bounded Pydantic model: quality_score `ge=0/le=1`, keywords/entities capped at 20/50 items of 200 chars) and `enrich_document()` implementing the full cache-check -> budget-check -> single `cheap_model` LiteLLM call -> validate -> registry-write flow, parented on the `cleaned_document` artifact (never `parsed_document`, D-01) and never raising out of a budget/LLM failure (D-05)
- Prompt-injection mitigation (T-04-04): system/user message role separation plus an explicit instruction in `_ENRICHMENT_SYSTEM_PROMPT` to treat any instruction-like text inside the document excerpt as content, never as a command
- `klake enrich` CLI command, `POST /enrich` API endpoint, and a new `enrich_document` Dagster asset (parallel branch off `clean_document`, same dependency as `chunk_document`, neither blocks the other) — all three call the same `pipeline.enrich.enrich_document()` with no duplicated logic (D-02)
- ENRICH-06 (configurable embedding provider) regression-confirmed unaffected: `tests/unit/test_builtin_plugins.py -k embedder` (16 tests) still passes unchanged

## Task Commits

Each task was committed atomically:

1. **Task 1: pipeline/deterministic.py — non-LLM title/dates/headings extraction (ENRICH-02)** - `a542e49` (feat)
2. **Task 2: llm/pricing.py + pipeline/enrich.py — cached, budget-capped LLM enrichment call (ENRICH-01, 03, 04, 05)** - `687d246` (feat)
3. **Task 3: klake enrich CLI + POST /enrich API + enrich_document Dagster asset (D-02 wiring)** - `1e57025` (feat)

4. **Task 4: Live Bedrock enrichment smoke test (checkpoint:human-verify, gate="blocking")** - RESOLVED via human-authorized live test; fixes committed as `ac299e1` (fix)

**Task 4's checkpoint is now resolved.** The user explicitly authorized running the live Bedrock smoke test, then authorized fixing the infra/code gaps it surfaced, then personally set `LITELLM_MASTER_KEY` in `.env` and restarted the litellm container. Six real bugs were found and fixed (commit `ac299e1`) — see "Deviations from Plan" and "Next Phase Readiness" below for full detail. Live verification: `klake enrich` returned `status: enriched` with `quality_score: 0.92`, and a second identical call returned `status: cached` (ENRICH-04 confirmed). Full unit suite (`uv run pytest tests/unit/ -q`) passed 260/260 after the fixes.

## Files Created/Modified
- `src/knowledge_lake/pipeline/deterministic.py` - `extract_title()`/`extract_dates()`/`extract_headings()`/`extract_deterministic_fields()`, zero LLM/DB/network calls
- `tests/unit/test_deterministic.py` - 12 unit tests (title fallback chain, date regex tuple-vs-str regression, heading order/skip, exact-key-set assertion)
- `src/knowledge_lake/llm/__init__.py` - empty package init
- `src/knowledge_lake/llm/pricing.py` - `bootstrap_llm_pricing()`, `compute_call_cost()`
- `src/knowledge_lake/pipeline/enrich.py` - `EnrichmentResult`, `enrich_document()`, `_ENRICHMENT_SYSTEM_PROMPT`, cache-key/prompt-builder/retry-wrapped LLM-call helpers
- `tests/unit/test_enrich.py` - 5 unit tests using an in-memory-SQLite `get_engine()` monkeypatch harness + mocked `litellm.completion` (happy path with persisted-title regression assertion, cache-hit no-op, budget-exceeded halt, LLM-failure halt, no-hardcoded-provider-ID source scan)
- `src/knowledge_lake/api/schemas.py` - Added `EnrichRequest`/`EnrichResponse`
- `src/knowledge_lake/cli/app.py` - Added `cmd_enrich` (`klake enrich`), updated module docstring's Commands list
- `src/knowledge_lake/api/app.py` - Added `enrich_endpoint` (`POST /enrich`), added `EnrichRequest`/`EnrichResponse` to the schemas import
- `src/knowledge_lake/dagster_defs/assets.py` - Added `enrich_document` asset (parallel branch off `clean_document`), updated module docstring's asset-ordering comment
- `src/knowledge_lake/dagster_defs/definitions.py` - Added `enrich_document` to the assets import and `Definitions(assets=[...])` list

## Decisions Made
- `enrich_document()` raises `ValueError` with an explicit D-01 message if the target artifact's `artifact_type != "cleaned_document"` — a defensive check beyond what the plan's action text required, catching a caller passing the wrong artifact ID before any LLM spend occurs
- Cache re-check happens twice (once before the LLM call, once immediately before the registry write) to guard a concurrent identical run — mirrors `pipeline/clean.py`'s existing exact-dedup-check-then-write session discipline
- In-memory SQLite test harness uses `StaticPool` + `connect_args={"check_same_thread": False}` so multiple independent `get_session()` calls made *inside* `enrich_document()` all resolve against the same committed test data (no prior test in this codebase needed this pattern since existing pipeline-stage unit tests only exercise pure/sub-functions, not the full DB-backed entry point)

## Deviations from Plan

### Auto-fixed Issues (found during Task 4's live Bedrock checkpoint, commit `ac299e1`)

The mocked unit tests in Tasks 1-3 could not surface issues that only appear against a real LiteLLM proxy talking to real AWS Bedrock. The human-authorized live test in Task 4 surfaced six real gaps, all fixed and committed together in `ac299e1`:

**1. [Rule 3 - Blocking issue] Missing `openai/` wire-protocol prefix on LiteLLM calls**
- **Found during:** Task 4 live test
- **Issue:** `litellm.completion()`/`litellm.embedding()` raised `"LLM Provider NOT provided"` when called with a bare task alias (`model="cheap_model"`) against a local proxy reached via `api_base` — LiteLLM needs an explicit `openai/` prefix to know which wire protocol to speak to the proxy itself (the proxy then routes to the real Bedrock model per its own config).
- **Fix:** Added the `openai/` prefix to the `model=` argument in `enrich.py`, `scorer.py`, and `st_embedder.py`; added a new `Settings.litellm_api_key` field and wired it through `resolver.py` since the proxy now enforces auth once a database is attached.
- **Files modified:** `src/knowledge_lake/pipeline/enrich.py`, `src/knowledge_lake/quality/scorer.py`, `src/knowledge_lake/plugins/builtin/st_embedder.py`, `src/knowledge_lake/config/settings.py`, `src/knowledge_lake/config/resolver.py`
- **Commit:** `ac299e1`

**2. [Rule 2 - Missing critical functionality] LiteLLM proxy had no `DATABASE_URL`**
- **Found during:** Task 4 live test
- **Issue:** `ghcr.io/berriai/litellm:main-latest` requires a Prisma-backed `DATABASE_URL` or every completion/embedding call fails with `"400 No connected db"`.
- **Fix:** Added a `litellm_storage` Postgres database (mirroring the existing `dagster_storage` pattern) in `docker-compose.yml` and `infra/postgres/init.sql`.
- **Files modified:** `docker-compose.yml`, `infra/postgres/init.sql`
- **Commit:** `ac299e1`

**3. [Rule 1 - Bug] `infra/litellm/config.yaml` master_key used shell-style `${VAR}` syntax**
- **Found during:** Task 4 live test
- **Issue:** LiteLLM's own config loader does not expand shell-style `${LITELLM_MASTER_KEY}` — it silently became the literal unresolved string, so no real master key was ever active.
- **Fix:** Changed to LiteLLM's own `os.environ/LITELLM_MASTER_KEY` syntax.
- **Files modified:** `infra/litellm/config.yaml`
- **Commit:** `ac299e1`

**4. [Rule 1 - Bug] `litellm_params` used a nonexistent `aws_bedrock_api_key` field**
- **Found during:** Task 4 live test
- **Issue:** This field is silently ignored by LiteLLM's bedrock provider, so the intended API-key auth path never activated.
- **Fix:** Changed to the generic `api_key` field, which the bedrock provider reads as a Bearer token when no SigV4 credentials are present.
- **Files modified:** `infra/litellm/config.yaml`
- **Commit:** `ac299e1`

**5. [Rule 1 - Bug] Configured Claude model IDs had fictional future dates**
- **Found during:** Task 4 live test
- **Issue:** The model IDs configured for `cheap_model`/`strong_model` were not present in Bedrock's real catalog.
- **Fix:** Replaced with real cross-region inference-profile IDs verified live against AWS's `ListFoundationModels`/`ListInferenceProfiles`: `us.anthropic.claude-haiku-4-5-20251001-v1:0` (cheap_model), `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (strong_model).
- **Files modified:** `infra/litellm/config.yaml`
- **Commit:** `ac299e1`

**6. [Rule 1 - Bug] Live Claude output wrapped JSON in markdown fences**
- **Found during:** Task 4 live test
- **Issue:** Despite `_ENRICHMENT_SYSTEM_PROMPT` explicitly forbidding markdown fences, live Claude output sometimes wrapped its JSON response in ` ```json ... ``` ` fences, breaking `EnrichmentResult.model_validate_json()`/`json.loads()`.
- **Fix:** Added defensive fence-stripping in `enrich.py` and `scorer.py` before JSON parsing.
- **Files modified:** `src/knowledge_lake/pipeline/enrich.py`, `src/knowledge_lake/quality/scorer.py`
- **Commit:** `ac299e1`

One documentation-only note (from Task 3, unchanged):

**7. [Informational] Dagster asset-graph acceptance-criteria command uses a renamed API**
- **Found during:** Task 3 verification
- The plan's acceptance criteria command `defs.get_asset_graph()` does not exist in the installed Dagster 1.13.11 (renamed to `resolve_asset_graph()` in this version). Verified the underlying claim — `enrich_document` is present in the asset graph — using the current equivalent: `defs.resolve_asset_graph().get_all_asset_keys()`. No code change was needed; this is a pre-existing Dagster API-drift note for future plans that reference `get_asset_graph()`.

## Issues Encountered

None outstanding. All six live-test blockers found during Task 4's checkpoint were fixed and verified in commit `ac299e1` (see "Deviations from Plan" above); the full unit suite (260 tests) passes and the live Bedrock call itself succeeded with a cache-hit confirmed on re-run.

## User Setup Required

The user personally set `LITELLM_MASTER_KEY` in `.env` and restarted the litellm container as part of resolving Task 4's checkpoint. No further user setup is required for this plan.

## Next Phase Readiness

**COMPLETE — Task 4 (checkpoint:human-verify, gate="blocking") has been resolved by a human-authorized live test.**

Checkpoint resolution sequence:
1. User explicitly authorized running the live Bedrock smoke test.
2. User authorized fixing the infra/code gaps the test surfaced.
3. User personally set `LITELLM_MASTER_KEY` in `.env` and restarted the litellm container.
4. Six real bugs were found and fixed, committed as `ac299e1` (see "Deviations from Plan").
5. Live verification (the plan's exact required steps):
   - `uv run klake enrich doc_019f3059-c9b1-77c3-bcb5-f0f2742a859b src_019f261f-0698-76e3-912b-8f82df31f051` -> `status: enriched`, `quality_score: 0.92`, `artifact_id: doc_019f36b9-b10f-7032-9562-b5685dcd54de`, `cost_usd: 0.0007455`
   - Identical second call -> `status: cached`, `cached: True`, same `artifact_id` (ENRICH-04 cache-hit confirmed, no second LLM call)
   - Full unit suite: `uv run pytest tests/unit/ -q` -> 260 passed after the fixes

All ENRICH-01..06 requirements are now confirmed complete, including the live-Bedrock risk RESEARCH.md Open Question #2 flagged as unresolved. `requirements-completed` in this SUMMARY's frontmatter is `[ENRICH-01, ENRICH-02, ENRICH-03, ENRICH-04, ENRICH-05, ENRICH-06]`, and `status: complete`.

No blockers to Plan 03 (index/search) — Plan 03 depends on Plan 01's registry/settings foundation, not on this plan's LLM enrichment output, per the phase's dependency graph.

---
*Phase: 04-enrichment-embedding-search*
*Completed: 2026-07-06 (checkpoint resolved via human-authorized live Bedrock test, commit ac299e1)*

## Self-Check: PASSED

All 11 created/modified files confirmed present on disk; all 4 task commits (`a542e49`, `687d246`, `1e57025`, `ac299e1`) confirmed present in git log. Task 4's checkpoint is resolved — live Bedrock verification evidence recorded in coverage item D7 above.
