---
phase: 21-index-time-dedup
plan: 08
subsystem: testing
tags: [dedup, qdrant, postgres, dagster, integration-test, reindex]

# Dependency graph
requires:
  - phase: 21-index-time-dedup (Plan 06)
    provides: "process_crawled() calls dedup_chunks() between chunk() and embed()/index() (CLI/API/MCP path)"
  - phase: 21-index-time-dedup (Plan 07)
    provides: "dedup_chunks/embed_chunks/index_chunks Dagster assets wired between chunk_document and index_chunks"
  - phase: 21-index-time-dedup (Plan 05)
    provides: "index()'s duplicate_chunks kwarg — contributor append, capped mirror, self-heal"
provides:
  - "tests/integration/test_dedup_cli_dagster_parity.py — D-18 parity proof: point_id_for_text() determinism + contributor_count==2 + matching text_sha256 across the CLI path and the Dagster path, each in its own live collection"
  - "tests/integration/test_dedup_reindex_survival.py — proof that reindex_collection() (default copy_all_points() path and refresh_payload=True path) never disturbs a deduplicated point's contributors/contributor_count payload or the chunk_dedup_ledger row (D-08)"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dagster path exercised via DIRECT INVOCATION of the real dedup_chunks/embed_chunks/index_chunks asset functions (a standard Dagster testing pattern — @asset-decorated function objects remain plain-callable) with real PostgresResource/QdrantResource, instead of a full dagster.materialize() graph run from raw ingest — avoids needing a parseable document fixture since this phase's focus is the DEDUP layer, not parsing/ingest, while still calling the exact production asset code against the live stack"
    - "Both new integration test files use fully synthetic parsed_artifact_id/source_id strings (never backed by real Source/Artifact registry rows) — index()'s _resolve_document_payload_fields() and get_artifact() gracefully degrade to None/[] for an unknown artifact id, confirmed empirically before writing the tests, so no raw-document/source seeding fixture machinery was needed"

key-files:
  created:
    - tests/integration/test_dedup_cli_dagster_parity.py
    - tests/integration/test_dedup_reindex_survival.py
  modified: []

key-decisions:
  - "Dagster path uses direct asset-function invocation (dedup_chunks(chunk_document=..., postgres=...), etc.) rather than dagster.materialize() from raw ingest — this Dagster version's materialize() has no input_values parameter to seed an unfulfilled data input (chunk_document) without also materializing chunk_document itself, and chunk_document's own upstream chain (clean/curate/parse/ingest) would require a real parseable fixture with byte-identical shared boilerplate text surviving parse+clean+chunk, which is exactly the fragile complexity the plan's action text explicitly permits avoiding ('prefer whichever needs less fixture-authoring code while still exercising the REAL assets, not mocks')"
  - "Both test files use fully synthetic parsed_artifact_id/source_id/chunk_id strings with no seeded raw_document/Source registry rows, verified via a scratch script to gracefully degrade rather than raise — this collapses the CLI-path setup to exactly Plan 21-06's three-call shape (dedup_chunks() -> embed() -> index()) with no _seed_raw_document-style fixture needed"

requirements-completed: [DEDUP-01, DEDUP-02, DEDUP-03]

coverage:
  - id: D1
    description: "point_id_for_text() computed independently by the test equals the actual point_id present in both the CLI-path and Dagster-path collections' Qdrant points for the same shared boilerplate text"
    requirement: "DEDUP-02"
    verification:
      - kind: integration
        ref: "tests/integration/test_dedup_cli_dagster_parity.py::TestDedupCliDagsterPointIdLedgerParity::test_point_id_is_deterministic_and_present_in_both_collections"
        status: pass
    human_judgment: false
  - id: D2
    description: "Each collection (CLI-path and Dagster-path) shows contributor_count==2 for the shared boilerplate text's ledger row after two documents are processed — the second document's chunk was recognized as a duplicate on both call sites"
    requirement: "DEDUP-01"
    verification:
      - kind: integration
        ref: "tests/integration/test_dedup_cli_dagster_parity.py::TestDedupCliDagsterPointIdLedgerParity::test_contributor_count_is_two_for_both_paths"
        status: pass
    human_judgment: false
  - id: D3
    description: "text_sha256 column value is identical between the CLI-path ledger row and the Dagster-path ledger row for the same text, even though the rows differ by collection/point_id/primary_* fields"
    requirement: "DEDUP-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_dedup_cli_dagster_parity.py::TestDedupCliDagsterPointIdLedgerParity::test_text_sha256_identical_across_cli_and_dagster_ledger_rows"
        status: pass
    human_judgment: false
  - id: D4
    description: "reindex_collection(hybrid=False, refresh_payload=False) — the default verbatim copy_all_points() path — leaves the chunk_dedup_ledger row byte-for-byte unchanged and preserves the deduplicated point's contributors/contributor_count payload after the alias repoints"
    requirement: "DEDUP-01"
    verification:
      - kind: integration
        ref: "tests/integration/test_dedup_reindex_survival.py::TestDedupSurvivesDefaultCopyReindex::test_default_reindex_preserves_ledger_and_contributors_payload"
        status: pass
    human_judgment: false
  - id: D5
    description: "reindex_collection(hybrid=False, refresh_payload=True) — the payload-re-derivation path — also leaves the ledger row unchanged and preserves contributors/contributor_count, proving the existing dict-merge behavior in _build_payload_refresh_fn's _resolve() does not drop dedup-specific payload keys"
    requirement: "DEDUP-01"
    verification:
      - kind: integration
        ref: "tests/integration/test_dedup_reindex_survival.py::TestDedupSurvivesRefreshPayloadReindex::test_refresh_payload_reindex_preserves_contributors_payload"
        status: pass
    human_judgment: false

# Metrics
duration: 18min
completed: 2026-07-17
status: complete
---

# Phase 21 Plan 08: D-18 Parity + Reindex-Survival Integration Proof Summary

**Two new live-stack integration test files close out Phase 21: one proves the CLI path and the Dagster path produce byte-identical deterministic point IDs and ledger state for the same text (D-18's "enforced by test" guarantee), the other proves `reindex_collection()`'s two upsert modes never disturb a deduplicated point's contributor lineage or its ledger row (D-08).**

## Performance

- **Duration:** 18 min
- **Started:** 2026-07-17T13:35:37Z
- **Completed:** 2026-07-17T13:53:12Z
- **Tasks:** 2 completed
- **Files modified:** 2 (both created, no existing files touched)

## Accomplishments
- `tests/integration/test_dedup_cli_dagster_parity.py` seeds the SAME shared boilerplate text through two documents on the CLI path (`dedup_chunks()` -> `embed()` -> `index()`, matching Plan 21-06's exact call shape) and two documents on the Dagster path (direct invocation of the real `dedup_chunks`/`embed_chunks`/`index_chunks` asset functions with real `PostgresResource`/`QdrantResource`), each into its own throwaway collection — then independently recomputes `point_id_for_text()` and asserts it matches BOTH paths' actual Qdrant point IDs and ledger rows, that both collections reach `contributor_count == 2`, and that the two paths' `text_sha256` ledger values are identical
- `tests/integration/test_dedup_reindex_survival.py` seeds one deduplicated point (`contributor_count == 2`) into a fresh test collection, snapshots its pre-reindex Qdrant payload, then runs `reindex_collection()` twice across two independent scenarios — `refresh_payload=False` (default `copy_all_points()`) and `refresh_payload=True` (`refresh_all_points_payload()`) — asserting in each case that the `chunk_dedup_ledger` row is byte-for-byte unchanged (reindex never writes to Postgres) and that the post-reindex Qdrant payload's `contributors`/`contributor_count` fields exactly match the pre-reindex snapshot
- Both test files verified empirically, before writing any assertions, that `index()`'s `_resolve_document_payload_fields()` (via `get_artifact()`) gracefully degrades to `None`/`[]` for a synthetic, unregistered `parsed_artifact_id` — so neither test needed `_seed_raw_document`-style Source/Artifact registry fixtures, collapsing both tests' setup to direct pipeline-function calls only
- Discovered (and confirmed via a scratch script against the live stack) that this Dagster version's `materialize()` has no `input_values` parameter to seed an asset's unfulfilled data input without materializing its upstream producer — direct invocation of the `@asset`-decorated functions (still plain-callable Python objects) was used instead, a standard Dagster testing pattern that still exercises the real production asset code (not mocks) with real resources
- Full test suite (`uv run pytest`, unit + integration + e2e): **1175 passed, 3 skipped, 6 xfailed, 0 failed** — no regressions from this plan or any prior Phase 21 plan
- Both new files pass `ruff check` and `mypy` cleanly

## Task Commits

1. **Task 1: D-18 CLI/Dagster point-ID and ledger-state parity test** - `6d57e28` (test)
2. **Task 2: Reindex-survives-dedup integration test** - `58f2c03` (test)

**Plan metadata:** (this commit)

## Files Created/Modified
- `tests/integration/test_dedup_cli_dagster_parity.py` - New file: `parity_run` class-scoped fixture processes the shared boilerplate text through both the CLI path (direct `dedup_chunks()`/`embed()`/`index()` calls) and the Dagster path (direct invocation of the real `dedup_chunks`/`embed_chunks`/`index_chunks` asset functions), each twice into its own collection; `TestDedupCliDagsterPointIdLedgerParity` has 3 tests covering point_id determinism, contributor_count==2, and cross-path text_sha256 equality; best-effort teardown drops both test collections' physical Qdrant collections and ledger rows
- `tests/integration/test_dedup_reindex_survival.py` - New file: `_seed_deduplicated_point()` helper seeds one deduplicated point via `dedup_chunks()`/`embed()`/`index()`; `TestDedupSurvivesDefaultCopyReindex` and `TestDedupSurvivesRefreshPayloadReindex` each seed their own fresh collection, snapshot the pre-reindex Qdrant payload, run `reindex_collection()` with the respective mode, and assert both the ledger row (Postgres) and the Qdrant payload (`contributors`/`contributor_count`) are unchanged

## Decisions Made
- Used direct asset-function invocation for the Dagster path rather than `dagster.materialize()` from raw ingest — documented in full under `key-decisions` in the frontmatter above. This is a deliberate scope choice explicitly permitted by the plan's action text ("either is acceptable; prefer whichever needs less fixture-authoring code while still exercising the REAL ... assets, not mocks of them").
- Used fully synthetic (unregistered) `parsed_artifact_id`/`source_id` strings in both test files rather than seeding real `Source`/`Artifact` registry rows, after confirming empirically that `index()`'s payload-field resolution degrades gracefully for an unknown artifact id rather than raising.

## Deviations from Plan

None - plan executed exactly as written. The plan's action text explicitly anticipated and pre-authorized both implementation choices described above (direct Dagster asset invocation instead of full `materialize()` from raw ingest; calling the `dedup_chunks()` -> `embed()` -> `index()` chain directly instead of driving full `process_crawled()` raw-document discovery), so neither required a deviation-rule fix — they were selections among the plan's own stated alternatives.

## Issues Encountered
- Confirmed via a scratch script (not part of the committed test files) that this Dagster version's `materialize()` signature has no `input_values` parameter, ruling out one candidate approach for seeding `dedup_chunks`' `chunk_document` input without also materializing `chunk_document` itself. Resolved by using direct asset-function invocation instead (see Decisions Made).
- An initial `mypy` pass flagged the `parity_run` class-scoped fixture's `-> dict` return annotation on a generator function ("should be Generator or a supertype"); fixed by annotating it `-> Iterator[dict]` (`collections.abc.Iterator`). No behavior change, caught before the Task 1 commit.

## User Setup Required

None - no external service configuration required. Both test files require the same live dev stack (Postgres + Qdrant, via `docker compose up`) that every other file in `tests/integration/` already requires; no new services or credentials.

## Next Phase Readiness

- Phase 21 (index-time-dedup)'s must_haves are now proven end-to-end against the real Postgres + Qdrant dev stack: identical text dedupes to one point regardless of which of the two wired call sites (CLI/API/MCP or Dagster) processed it, point IDs are deterministic across both paths (not just mutually consistent), and reindexing does not disturb deduplicated points' contributor state under either reindex mode
- This was the phase's final plan (8 of 8) — DEDUP-01/02/03 requirements are now closed
- No blockers identified

---
*Phase: 21-index-time-dedup*
*Completed: 2026-07-17*

## Self-Check: PASSED

Both created files confirmed present on disk (`tests/integration/test_dedup_cli_dagster_parity.py`, `tests/integration/test_dedup_reindex_survival.py`); both commit hashes (`6d57e28`, `58f2c03`) confirmed present in git log; both new integration test files pass (5/5) against the live dev stack; full suite (1175 passed, 3 skipped, 6 xfailed, 0 failed) confirms no regressions.
