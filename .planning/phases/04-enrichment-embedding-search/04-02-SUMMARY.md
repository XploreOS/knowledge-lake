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

requirements-completed: []  # ENRICH-01..06 implementation is complete and unit-tested, but this plan's checkpoint (live Bedrock smoke test) has not yet been human-approved — see "Next Phase Readiness" below. Requirements will be marked complete once the checkpoint resolves.

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
    verification: []
    human_judgment: true
    rationale: "RESEARCH.md Open Question #2 could not be resolved without a live AWS Bedrock credential and a running LiteLLM proxy — this is the plan's blocking checkpoint, not yet resolved as of this SUMMARY."

# Metrics
duration: 8min (through Task 3; checkpoint pending)
completed: 2026-07-05
status: paused
---

# Phase 4 Plan 2: Enrichment Pipeline (LLM-judged Metadata) Summary

**pipeline/deterministic.py + llm/pricing.py + pipeline/enrich.py deliver a cached, budget-capped single-call LiteLLM enrichment producing enriched_document artifacts, wired into klake enrich / POST /enrich / a parallel Dagster asset — PAUSED at the plan's blocking live-Bedrock-smoke-test checkpoint, awaiting human sign-off**

## Performance

- **Duration (through Task 3):** 8 min
- **Started:** 2026-07-05T17:33:52Z
- **Paused at checkpoint:** 2026-07-05T17:41:53Z
- **Tasks completed:** 3 of 4 (Task 4 is the blocking checkpoint)
- **Files modified:** 11 (6 created, 5 modified)

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

**Task 4 (checkpoint:human-verify, gate="blocking") is NOT yet resolved** — see "Next Phase Readiness" below. No plan-completion metadata commit has been made; this SUMMARY.md documents the paused state and will be superseded once the checkpoint is approved.

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

None affecting behavior. One documentation-only note:

**1. [Informational] Dagster asset-graph acceptance-criteria command uses a renamed API**
- **Found during:** Task 3 verification
- The plan's acceptance criteria command `defs.get_asset_graph()` does not exist in the installed Dagster 1.13.11 (renamed to `resolve_asset_graph()` in this version). Verified the underlying claim — `enrich_document` is present in the asset graph — using the current equivalent: `defs.resolve_asset_graph().get_all_asset_keys()`. No code change was needed; this is a pre-existing Dagster API-drift note for future plans that reference `get_asset_graph()`.

## Issues Encountered
None.

## User Setup Required

**This plan's Task 4 is a blocking `checkpoint:human-verify` requiring a live AWS Bedrock credential and a running LiteLLM proxy.** See "Next Phase Readiness" below for exact verification steps. No SUMMARY-level user setup beyond what the checkpoint itself specifies.

## Next Phase Readiness

**PAUSED — Task 4 (checkpoint:human-verify, gate="blocking") has not been resolved.**

What remains before this plan (and Phase 4's enrichment slice) can be considered complete:
1. `AWS_BEDROCK_API_KEY` set in `.env`
2. `docker compose up -d litellm postgres qdrant minio` (or the full stack) with a healthy `litellm` container
3. Ingest + clean a test document to obtain a real `cleaned_document` artifact_id + source_id
4. `klake enrich <cleaned_artifact_id> <source_id>` prints `status: enriched` with a populated `quality_score`
5. A second identical `klake enrich` call prints `status: cached` (ENRICH-04 no-op)
6. Human types the approval resume-signal (or reports a failure, per RESEARCH.md Open Question #2's real risk that the configured Bedrock model ID may not be live-callable)

Once approved: `requirements-completed` in this SUMMARY's frontmatter should be updated to `[ENRICH-01, ENRICH-02, ENRICH-03, ENRICH-04, ENRICH-05, ENRICH-06]`, `status: paused` should become `status: complete`, and `STATE.md`/`ROADMAP.md`/`REQUIREMENTS.md` should be advanced via the normal `state advance-plan` / `roadmap update-plan-progress` / `requirements mark-complete` flow.

No blockers to Plan 03 (index/search) starting in parallel — Plan 03 depends on Plan 01's registry/settings foundation, not on this plan's LLM enrichment output, per the phase's dependency graph.

---
*Phase: 04-enrichment-embedding-search*
*Paused: 2026-07-05 (awaiting checkpoint approval)*

## Self-Check: PASSED

All 11 created/modified files confirmed present on disk; all 3 task commits (`a542e49`, `687d246`, `1e57025`) confirmed present in git log. Task 4 (checkpoint) intentionally not resolved — see "Next Phase Readiness".
