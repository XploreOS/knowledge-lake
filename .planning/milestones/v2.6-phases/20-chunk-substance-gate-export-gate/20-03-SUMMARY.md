---
phase: 20-chunk-substance-gate-export-gate
plan: 03
subsystem: pipeline
tags: [export, parquet, datasets, eval, chunk-quality, structlog]

# Dependency graph
requires:
  - phase: 20-chunk-substance-gate-export-gate
    plan: 01
    provides: chunk()'s substance_passed/rejection_reason metadata annotations, ChunkQualitySettings.filter_config_version
provides:
  - export_rag_corpus() chunk-level substance_passed gate (backward-compatible default True for missing key)
  - substance_filtered_out structlog counter on export.rag_corpus.building
  - generate_qa_example()/generate_instruction_example() version-tagged DatasetExample.payload (D-11, D-12)
  - documented operator regeneration path via unmodified `klake generate-dataset` CLI
affects: [20-04 (must-not-reject fixtures exercise the full pipeline these gates sit in)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pre-row-build 'continue' skip pattern reused from the existing domain-mismatch filter in export_rag_corpus() — substance_passed gate never becomes an exported column"
    - "Additive payload versioning (not a cache-key dimension) — version tag on DatasetExample.payload is independent of _dataset_gen_cache_key()"

key-files:
  created: []
  modified:
    - src/knowledge_lake/pipeline/export.py
    - src/knowledge_lake/pipeline/datasets.py
    - tests/unit/test_export.py
    - tests/unit/test_datasets.py

key-decisions:
  - "EXPORT-02 scope is versioning-only, not migration: existing pre-Phase-20 DatasetExample rows are NOT backfilled with a 'version' key. The operator-facing regeneration mechanism is the existing, unmodified `klake generate-dataset qa|instruction <artifact_id> --dataset-name <name>` CLI command — re-run against artifacts re-processed under the current filter_config_version to produce fresh, version-tagged examples. This boundary was flagged as a plan-checker warning and resolved during plan revision by adding an <operational_followup> section to 20-03-PLAN.md rather than building new regeneration tooling."
  - "meta.get('substance_passed', True) treats an explicit None the same as False (excluded) — 'not None' is True — a deliberate, tested distinction from a missing key (which defaults to True/included)."

patterns-established:
  - "Chunk-level quality gates on exports: pre-filter with a 'continue' skip before row construction, log a dedicated *_filtered_out counter, never add the gate field itself as an exported column."

requirements-completed: [EXPORT-01, EXPORT-02]

coverage:
  - id: D1
    description: "export_rag_corpus() gates on chunk-level substance_passed instead of document-level quality_score — mixed-quality documents export only clinical chunks"
    requirement: "EXPORT-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_export.py::TestRagCorpus (substance_passed True/False/None/missing-key cases)"
        status: pass
    human_judgment: false
  - id: D2
    description: "_RAG_CORPUS_FIELDS unchanged; substance_passed/rejection_reason never appear as exported Parquet columns; substance_filtered_out counter added to export.rag_corpus.building log event"
    requirement: "EXPORT-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_export.py::TestRagCorpus (column-set assertion)"
        status: pass
    human_judgment: false
  - id: D3
    description: "generate_qa_example()/generate_instruction_example() tag DatasetExample.payload with a version field copied verbatim from settings.chunk_quality.filter_config_version; different filter_config_version values produce distinct version tags"
    requirement: "EXPORT-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_datasets.py::test_qa_example_payload_carries_version_field, test_instruction_example_payload_carries_version_field, test_qa_example_different_filter_config_version_yields_different_version_tag"
        status: pass
    human_judgment: false
  - id: D4
    description: "Operator-facing regeneration path (klake generate-dataset, unmodified) documented as the mechanism for producing fresh version-tagged examples against re-processed artifacts"
    requirement: "EXPORT-02"
    verification:
      - kind: unit
        ref: "klake generate-dataset --help exits 0 (chained in Task 2's <verify>)"
        status: pass
    human_judgment: false

# Metrics
duration: ~40min (interrupted mid-Task-2 by a session usage-limit cutoff; resumed and completed in the same working tree)
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 03: Export Gate + Eval Dataset Versioning Summary

**Chunk-level substance_passed gate on export_rag_corpus() plus version-tagged eval/instruction dataset examples derived from filter_config_version**

## Performance

- **Duration:** ~40 min total (executor session was cut off by a usage-limit reset partway through Task 2's GREEN implementation; the in-progress uncommitted change was verified against its own RED tests and committed to complete the task)
- **Tasks:** 2/2 complete
- **Files modified:** 4

## Accomplishments
- `export_rag_corpus()` now excludes chunks with `substance_passed=False` or explicit `substance_passed=None`, includes `True` and missing-key chunks (backward-compatible default), and never exports `substance_passed`/`rejection_reason` as columns
- `export.rag_corpus.building`'s structlog event gains a `substance_filtered_out` counter, independent of the pre-existing domain-mismatch `filtered_out` counter
- `generate_qa_example()` and `generate_instruction_example()` both tag their `DatasetExample.payload` dict with `"version": settings.chunk_quality.filter_config_version`, leaving `_dataset_gen_cache_key()` untouched
- Documented the operator-facing regeneration path (`klake generate-dataset`, unmodified) as the explicit mechanism for producing fresh version-tagged examples — closing the plan-checker's EXPORT-02 scope-boundary warning without building new tooling

## Task Commits

Each task was committed atomically:

1. **Task 1: Gate export_rag_corpus() on chunk-level substance_passed** - `eb54301` (test, RED) → `9235fcc` (feat, GREEN)
2. **Task 2: Tag generated eval/instruction examples with a version field** - `f89de93` (test, RED) → `506fcdd` (feat, GREEN)

_Note: TDD tasks produced RED→GREEN commit pairs as specified._

## Files Created/Modified
- `src/knowledge_lake/pipeline/export.py` - `export_rag_corpus()` gates on chunk-level `substance_passed` via a pre-row-build `continue` skip; adds `substance_filtered_out` to the structlog event
- `src/knowledge_lake/pipeline/datasets.py` - `generate_qa_example()`/`generate_instruction_example()` add `"version": s.chunk_quality.filter_config_version` to their `DatasetExample.payload` dicts
- `tests/unit/test_export.py` - `TestRagCorpus` extended with substance-gate cases (True/False/None/missing-key, column-set assertion, zero-rows document, counter assertion)
- `tests/unit/test_datasets.py` - new tests for version-tag presence and divergence across `filter_config_version` values

## Decisions Made
- EXPORT-02 is delivered as versioning-only for this phase; regeneration of pre-v2.6 eval datasets is an explicit operator action via the existing `klake generate-dataset` CLI, not new code. See `20-03-PLAN.md`'s `<operational_followup>` section for the exact runbook. This boundary was surfaced by the plan-checker as a warning during the plan-phase revision loop and resolved by making the operator path visible and testable (`klake generate-dataset --help` exit-0 check) rather than silently leaving it as a bare prohibition.
- `meta.get("substance_passed", True)` treats explicit `None` identically to `False` (both excluded) — `not None` evaluates `True`, so the skip branch fires. This is a deliberate, tested distinction from a genuinely missing key (defaults to `True`, included).

## Deviations from Plan

None in implementation — plan executed exactly as written. One session-level interruption:

### Session Interruption (not a plan deviation)

The original executor agent was cut off mid-Task-2 by a Claude Code session usage-limit reset, after committing Task 2's RED test commit (`f89de93`) but before committing the GREEN implementation. The in-progress uncommitted 2-line change to `datasets.py` (adding the `"version"` payload key to both functions) was found intact in the working tree, verified to satisfy all of Task 2's RED tests and acceptance criteria exactly as specified in the plan (including the `klake generate-dataset --help` check and confirming `_dataset_gen_cache_key()` was untouched), and committed as `506fcdd` to complete the task. No plan content was altered; the GREEN change matches the plan's `<action>` block verbatim.

## Issues Encountered
- Claude Code session hit its usage limit mid-execution (see above). Resolved by inspecting `git status`/`git diff` to recover the in-progress uncommitted work, independently verifying it against the plan's own acceptance criteria and RED tests, then committing and continuing.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Plan 20-04 (must-not-reject CI fixtures) can now exercise the full production pipeline: Plan 20-01's gate, Plan 20-02's `DomainLoader` wiring, and Plan 20-03's export gate are all in place and tested.
- Full test suite verified green post-completion: 1089 passed, 0 failed, 3 skipped, 6 xfailed (no regressions).
- Operational note for future work: pre-v2.6 `DatasetExample` rows remain unversioned (no `version` key) until an operator explicitly re-runs `klake generate-dataset` against re-processed artifacts — this is intentional per the D-11/D-12 scope boundary, not an oversight.

---
*Phase: 20-chunk-substance-gate-export-gate*
*Completed: 2026-07-17*
