---
phase: 04-enrichment-embedding-search
fixed_at: 2026-07-06T10:27:21Z
review_path: .planning/phases/04-enrichment-embedding-search/04-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 4: Code Review Fix Report

**Fixed at:** 2026-07-06T10:27:21Z
**Source review:** .planning/phases/04-enrichment-embedding-search/04-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (1 Critical + 5 Warning; Info findings IN-01..IN-03 out of scope for this pass)
- Fixed: 6
- Skipped: 0

## Fixed Issues

### CR-01: Enrichment title is always empty when invoked via CLI/API (not Dagster)

**Files modified:** `src/knowledge_lake/pipeline/parse.py`, `src/knowledge_lake/api/app.py`,
`src/knowledge_lake/cli/app.py`, `tests/unit/test_enrich.py`
**Commit:** `1d167e9`
**Applied fix:** The review's suggested fix ("reconstruct a ParsedDoc from the parsed
artifact's stored metadata") was adapted after inspecting the actual code: the
parsed_document artifact's persisted `metadata_` never contained a `"title"` key
(`pipeline/parse.py` only stored `quality_score`/`parser_used`; no parser plugin's
`ParsedDoc.metadata` carries a title, and `ParsedDoc.sections` — the other source
`extract_title()` checks — are never persisted to the registry). Reconstructing a
`ParsedDoc` from the stored metadata as literally suggested would therefore still
yield an empty title. Applied a two-part fix instead:
1. `pipeline/parse.py` now computes `extract_title(parsed_doc.metadata, parsed_doc.sections)`
   once at parse time and persists it into the parsed_document artifact's `metadata_`
   dict alongside `quality_score`/`parser_used`.
2. `api/app.py`'s `enrich_endpoint` and `cli/app.py`'s `cmd_enrich` now fetch the
   cleaned artifact's parent (parsed_document) artifact and reconstruct a minimal
   `ParsedDoc(text="", sections=[], metadata=parsed.metadata_ or {})` to pass as
   `parsed_doc=` into `enrich_document()` — mirroring the parent-artifact-fetch
   pattern already used by `chunk_endpoint`/`cmd_chunk`.

Added `test_enrich_title_recovered_via_registry_reconstruction_when_parsed_doc_none`
to `tests/unit/test_enrich.py`, which replicates the new reconstruction logic and
asserts the persisted enriched artifact's title is non-empty and correct.

### WR-01: Registered Bedrock pricing IDs don't match the model IDs LiteLLM actually invokes

**Files modified:** `src/knowledge_lake/config/settings.py`, `tests/unit/test_settings.py`
**Commit:** `ff533f3`
**Applied fix:** Updated `cheap_model_bedrock_id` / `strong_model_bedrock_id` in
`EnrichSettings` to exactly match `infra/litellm/config.yaml`'s current
`cheap_model`/`strong_model` entries (`bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0`
and `bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0` — both were missing the
`us.` cross-region inference-profile prefix and had stale dates). Also added
`TestBedrockPricingIdsMatchLiteLLMConfig`, which parses `infra/litellm/config.yaml`
directly and fails the build if the two ever drift apart again (per the review's
"or better" suggestion).

### WR-02: TOCTOU races on the budget cap and enrichment cache under concurrent enrichment

**Files modified:** `src/knowledge_lake/pipeline/enrich.py`, `tests/unit/test_enrich.py`
**Commit:** `c9f8661`
**Applied fix:** Wrapped the final cache-recheck + spend-record + insert block in a
`try/except IntegrityError`. On the exception (a concurrent writer won the race and
already committed the same `(content_hash, artifact_type)` row), re-selects the
artifact the concurrent writer created and returns it as a cache hit instead of
letting the `IntegrityError` propagate as an unhandled 500. Implemented exactly the
minimum remediation the review specified (catch + treat as cache hit) rather than
the heavier single-flight-locking alternative, since that's what the Fix section
asked for. Added `test_enrich_integrity_error_on_race_is_treated_as_cache_hit`,
which simulates the race by committing a competing artifact in a separate session
mid-flight and asserts the losing call returns `status: "cached"` pointing at the
winner's artifact_id rather than raising.

### WR-03: Retry-induced LLM cost is undercounted against the budget

**Files modified:** `src/knowledge_lake/pipeline/enrich.py`, `tests/unit/test_enrich.py`
**Commit:** `33ab414`
**Applied fix:** `_call_llm_for_enrichment` now takes a caller-owned `attempt_costs: list[float]`
accumulator and appends `compute_call_cost(response, settings)` for every response
actually received from LiteLLM (i.e. every billable call), immediately after the
call succeeds and before JSON validation — so a validation failure that triggers a
tenacity retry does not lose that attempt's cost. `enrich_document()` now sums
`attempt_costs` for the total `cost_usd` instead of computing cost once from only
the final response. Added `test_retry_cost_is_accumulated_not_dropped`, which mocks
one malformed response (triggering a `ValidationError` retry) followed by one valid
response, and asserts `cost_usd` equals exactly double a single attempt's fallback
cost (the retry backoff is zeroed via `monkeypatch` on the tenacity `.retry.wait`
attribute so the test doesn't sleep).

### WR-04: `assert` used for production input validation in `index()`

**Files modified:** `src/knowledge_lake/pipeline/index.py`, `tests/unit/test_index_payload.py`
**Commit:** `d1cc2ef`
**Applied fix:** Replaced the bare `assert len(chunks) == len(vectors)` with an
explicit `if len(chunks) != len(vectors): raise ValueError(...)`, exactly as the
review suggested. Added `test_mismatched_lengths_raise_value_error_not_assert`,
which asserts a `ValueError` is raised (not silently swallowed under `-O`) and that
the vector store is never touched when the lengths mismatch.

### WR-05: `parsed_document` Dagster asset omits the `litellm` resource

**Files modified:** `src/knowledge_lake/dagster_defs/assets.py`
**Commit:** `10bb55f`
**Applied fix:** Added `litellm: LiteLLMResource` to the `parsed_document` asset's
signature and threaded `litellm_url=litellm.litellm_url` into its `Settings(...)`
construction, matching the existing pattern in `enrich_document` and `index_chunks`.
Scoped to `parsed_document` only (not `clean_document`/`chunk_document`/
`ingest_raw_document`) because the review's Issue text identifies `parse()`'s
optional `maybe_llm_spot_check()` as the only in-band LLM call site among those four
assets, and the Fix section explicitly scopes the remediation to `parsed_document`.
No test added — `tests/integration/test_dagster_assets.py`'s existing materialize
tests already construct a `resources` dict containing `"litellm"` and pass
`parsed_document` into `materialize([...])`, so they already exercise (and, after
this fix, correctly wire) the resource; those tests require the live docker-compose
stack (Postgres/MinIO/Qdrant/LiteLLM) and could not be exercised in this run due to
missing storage credentials in the sandboxed shell environment (see Verification
notes below) — this is an environment/credentials limitation unrelated to the fix
itself. `tests/integration/test_dagster_assets.py::TestAssetsModule` and
`TestResourcesModule` (which don't require live infra) pass.

## Skipped Issues

None — all 6 in-scope findings (CR-01, WR-01 through WR-05) were fixed.

## Verification

- `uv run pytest tests/unit/ -q` — **285 passed** (run after all 6 fixes were applied).
- Each individual fix was also verified in isolation before its commit:
  syntax/AST parse of every modified file, `ruff check` on `pipeline/enrich.py`
  (3 pre-existing, unrelated lint findings confirmed present before my changes too —
  no new findings introduced), and the specific unit test file(s) covering that
  finding (`test_enrich.py`, `test_settings.py`, `test_index_payload.py`,
  `test_parse_multiformat.py`, `test_deterministic.py`).
- `uv run pytest tests/integration/test_dagster_assets.py -q -k "not TestAssetMaterialization"` —
  **12 passed** (non-materialization tests; don't require live infra).
- `tests/integration/test_dagster_assets.py::TestAssetMaterialization` (which does
  require the live docker-compose stack) could not be run to completion in this
  sandboxed session: the in-process reference pipeline it depends on
  (`pipeline.run.run_document`) failed with `botocore.exceptions.NoCredentialsError`
  when fetching from MinIO, because `KLAKE_STORAGE__ACCESS_KEY_ID`/
  `KLAKE_STORAGE__SECRET_ACCESS_KEY` were not present in this shell's environment
  (the repo's `.env` file was not accessible to this session). This failure occurs
  before any of the six fixed code paths run and is unrelated to any of the fixes
  in this pass — it is a pre-existing environment/credentials limitation of the
  fixer's sandbox, not a regression. The full suite (`uv run pytest tests/ -q -m ""`)
  was not run for the same reason; all integration tests that touch live
  Postgres/MinIO/Qdrant/LiteLLM require credentials this session did not have
  access to. Recommend the human developer (or a session with `.env` access) run
  `uv run pytest tests/ -q -m ""` to confirm the integration suite passes end-to-end,
  in particular `test_dagster_assets.py::TestAssetMaterialization` for the WR-05
  fix specifically.

---

_Fixed: 2026-07-06T10:27:21Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
