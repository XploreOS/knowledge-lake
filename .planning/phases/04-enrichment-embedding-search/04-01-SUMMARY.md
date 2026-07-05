---
phase: 04-enrichment-embedding-search
plan: 01
subsystem: database
tags: [sqlalchemy, alembic, postgresql, pydantic-settings, registry]

# Dependency graph
requires:
  - phase: 03-parse-clean-chunk
    provides: parsed_document/cleaned_document artifact chain, quality_score column added by migration 0006
provides:
  - Artifact.quality_score real ORM column
  - LlmSpend and VectorCollection ORM models + migration 0007
  - registry.repo functions for enrichment, LLM budget accounting, and vector-collection alias registry
  - EnrichSettings / IndexSettings nested config
  - enriched_document ID prefix in ids.py
affects: [04-02-enrichment-pipeline, 04-03-index-search]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Get-or-create-by-unique-key repo functions (record_llm_spend, register_vector_collection) mirroring upsert_crawl_state's existing-check-then-update-or-insert shape"
    - "is_current boolean flip pattern for alias -> physical-collection registry rows (zero-downtime reindex, D-06)"

key-files:
  created:
    - src/knowledge_lake/registry/alembic/versions/0007_enrichment_index_tables.py
  modified:
    - src/knowledge_lake/registry/models.py
    - src/knowledge_lake/registry/repo.py
    - src/knowledge_lake/config/settings.py
    - src/knowledge_lake/ids.py
    - tests/integration/test_migrations.py
    - tests/unit/test_settings.py
    - tests/unit/test_registry.py

key-decisions:
  - "Artifact.quality_score mapped as a real ORM column (no new migration needed — 0006 already added the physical column); language/dedup_status remain metadata_-JSON-only, out of scope for this plan"
  - "Single global llm_spend scope acceptable for Phase 4 MVP; scope is a plain string key so per-source/per-job scopes can be added later without a schema change"
  - "vector_collections uses is_current boolean flip (not a separate 'active alias pointer' table) so reindex history is preserved and auditable via created_at"
  - "get_enriched_artifact_for_parsed walks parsed -> cleaned -> enriched (2 hops) reusing list_children, since enrichment parents off cleaned_document per D-01, not parsed_document"

patterns-established:
  - "New artifact-adjacent registry tables (llm_spend, vector_collections) get a generic art_-prefixed ID via new_id('artifact') when they are not part of the lineage tree"

requirements-completed: [ENRICH-05, INDEX-02]

coverage:
  - id: D1
    description: "Artifact.quality_score is a real Mapped[Optional[float]] SQLAlchemy column"
    requirement: "ENRICH-05"
    verification:
      - kind: unit
        ref: "tests/unit/test_registry.py::TestEnrichedArtifactAndSpend::test_create_enriched_artifact_sets_fields"
        status: pass
    human_judgment: false
  - id: D2
    description: "Migration 0007 creates llm_spend and vector_collections tables and round-trips cleanly"
    requirement: "ENRICH-05"
    verification:
      - kind: integration
        ref: "tests/integration/test_migrations.py::TestLlmSpendAndVectorCollectionsSchema"
        status: pass
      - kind: integration
        ref: "tests/integration/test_migrations.py::TestMigrationRoundTrip::test_downgrade_then_upgrade_roundtrip"
        status: pass
    human_judgment: false
  - id: D3
    description: "get_llm_spend/record_llm_spend accumulate LLM cost per scope"
    requirement: "ENRICH-05"
    verification:
      - kind: unit
        ref: "tests/unit/test_registry.py::TestEnrichedArtifactAndSpend::test_record_llm_spend_accumulates"
        status: pass
    human_judgment: false
  - id: D4
    description: "register_vector_collection/get_current_vector_collection track alias -> physical collection with is_current flip"
    requirement: "INDEX-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_registry.py::TestEnrichedArtifactAndSpend::test_register_vector_collection_flips_current"
        status: pass
    human_judgment: false
  - id: D5
    description: "create_enriched_artifact, get_enriched_artifact_for_parsed, get_domain_for_source available for Plans 02/03"
    verification:
      - kind: unit
        ref: "tests/unit/test_registry.py::TestEnrichedArtifactAndSpend"
        status: pass
    human_judgment: false
  - id: D6
    description: "EnrichSettings/IndexSettings load with correct defaults and KLAKE_ENRICH__*/KLAKE_INDEX__* env overrides"
    verification:
      - kind: unit
        ref: "tests/unit/test_settings.py::TestEnrichAndIndexSettings"
        status: pass
    human_judgment: false

duration: 8min
completed: 2026-07-05
status: complete
---

# Phase 4 Plan 1: Enrichment/Index Registry Foundation Summary

**Migration 0007 (llm_spend + vector_collections tables), Artifact.quality_score mapped as a real ORM column, and 7 new repo.py functions plus EnrichSettings/IndexSettings for the enrichment and index/search vertical slices**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-05T17:16:21Z
- **Completed:** 2026-07-05T17:23:29Z
- **Tasks:** 2
- **Files modified:** 7 (1 created, 6 modified)

## Accomplishments
- Mapped `Artifact.quality_score` as a real `Mapped[Optional[float]]` SQLAlchemy column, resolving the Phase 3 CONTEXT.md-flagged quality_score/ORM discrepancy (language/dedup_status remain a deliberate out-of-scope follow-up)
- Added `LlmSpend` and `VectorCollection` ORM models plus Alembic migration 0007 (down_revision `0006`), giving ENRICH-05's budget cap and INDEX-02's alias registry concrete Postgres-backed accounting
- Added `enriched_document` -> `doc` prefix mapping in `ids.py`
- Added `EnrichSettings` (budget_usd, prompt_version, cache_enabled, excerpt_chars, model pricing/registration fields) and `IndexSettings` (collection_alias, keep_old_collections) nested under `Settings`
- Added 7 new `registry/repo.py` functions: `create_enriched_artifact`, `get_llm_spend`, `record_llm_spend`, `get_enriched_artifact_for_parsed`, `get_domain_for_source`, `register_vector_collection`, `get_current_vector_collection`

## Task Commits

Each task was committed atomically:

1. **Task 1: Migration 0007 (llm_spend, vector_collections tables) + models.py mapping + ids.py prefix** - `6dc5b46` (feat)
2. **Task 2: EnrichSettings/IndexSettings + repo.py functions for enrichment caching, budget, and alias registry** - `e94043c` (feat)

**Plan metadata:** commit created by this step (see git log after this SUMMARY commit)

_Note: Both tasks were TDD-flagged; tests were written alongside the implementation in the same commit per the plan's action instructions (which specified extending existing test files rather than a separate RED-then-GREEN commit split)._

## Files Created/Modified
- `src/knowledge_lake/registry/models.py` - Added `Float` import, `Artifact.quality_score` mapped column, `LlmSpend` and `VectorCollection` classes
- `src/knowledge_lake/registry/alembic/versions/0007_enrichment_index_tables.py` - New migration creating `llm_spend` and `vector_collections` tables, down_revision `0006`
- `src/knowledge_lake/ids.py` - Added `enriched_document` -> `doc` prefix entry
- `tests/integration/test_migrations.py` - Added `llm_spend`/`vector_collections` to `EXPECTED_TABLES`, new `TestLlmSpendAndVectorCollectionsSchema` class, extended round-trip assertion
- `src/knowledge_lake/config/settings.py` - Added `EnrichSettings`, `IndexSettings` classes and `Settings.enrich`/`Settings.index` fields
- `src/knowledge_lake/registry/repo.py` - Added 7 new functions and extended the models import line
- `tests/unit/test_settings.py` - Added `TestEnrichAndIndexSettings` class
- `tests/unit/test_registry.py` - Added `TestEnrichedArtifactAndSpend` class covering all 5 new artifact/spend/alias repo functions

## Decisions Made
- Artifact.quality_score mapped without a new migration (0006 already added the physical column) — zero additional migration cost per RESEARCH.md's recommendation
- Single "global" llm_spend scope accepted for Phase 4 MVP; the `scope` column is a plain string so finer-grained scopes can be added later without a schema change
- vector_collections uses an `is_current` boolean flip rather than a separate pointer table, preserving full reindex history with `created_at` timestamps for audit
- `get_enriched_artifact_for_parsed` performs a 2-hop walk (parsed -> cleaned -> enriched) via `list_children`, matching D-01's decision that enrichment parents off cleaned_document, not parsed_document

## Deviations from Plan

None - plan executed exactly as written. All acceptance criteria commands were run and passed as specified.

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required. This plan is schema/settings-only with no CLI/API surface of its own (per the plan's Phase Goal note).

## Next Phase Readiness
- Migration 0007 is live on the dev/test Postgres schema and round-trips cleanly (`downgrade base` -> `upgrade head`)
- `registry/repo.py` and `registry/models.py` need NO further changes for Plans 02 (enrichment) or 03 (index/search) — every function either plan needs already exists and is unit-tested, avoiding same-wave file conflicts
- `EnrichSettings`/`IndexSettings` are ready for Plan 02's `litellm.register_model()` bootstrap and Plan 03's alias-based Qdrant reindex logic respectively
- No blockers identified

---
*Phase: 04-enrichment-embedding-search*
*Completed: 2026-07-05*

## Self-Check: PASSED

All created/modified files confirmed present on disk; both task commits (`6dc5b46`, `e94043c`) confirmed present in git log.
