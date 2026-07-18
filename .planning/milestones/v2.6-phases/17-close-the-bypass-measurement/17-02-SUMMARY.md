---
phase: 17-close-the-bypass-measurement
plan: 02
subsystem: pipeline
tags: [dagster, clean, chunk, lineage, boilerplate, in-memory-forwarding, materialize-test]

# Dependency graph
requires:
  - phase: 17-01
    provides: "clean() accepts an optional in-memory parsed_doc kwarg and always returns a cleaned_doc key; WR-05 parent-scoped content_hash"
provides:
  - "clean_document Dagster asset threads parsed_doc=parsed_doc into clean() and forwards clean_result['cleaned_doc'] under the same 'parsed_doc' dict key its three consumers already read"
  - "Materialize-test proof (test_dagster_materialize_produces_artifacts) that clean_document forwards a distinct (cleaned) object, that chunk text carries no unremoved page-footer boilerplate, and that curate_document_asset remains fully functional (D-03) with zero code change to curate.py"
affects: [17-03-cli-process-crawled-wiring, 17-04-quality-audit, 18-gate-decouple]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single-value dict-key swap inside the producing asset — zero changes to any consumer asset that already destructures the same key (Pattern 1: Replace-in-dict threading)"
    - "Object-identity assertion (`is not`) as the regression proof that a forwarding bypass has not silently reopened, rather than only asserting the key's presence"

key-files:
  created: []
  modified:
    - src/knowledge_lake/dagster_defs/assets.py
    - tests/integration/test_dagster_assets.py

key-decisions:
  - "Task 2 is tagged tdd=\"true\" in the plan but its <behavior> assertions verify functionality Task 1 (non-TDD) already implemented in the prior task/commit — writing the test did not fail first (RED), it passed immediately (GREEN was already shipped). This is the plan's intended task decomposition (implementation task, then proof-of-behavior task), not a TDD violation within a single task's own RED->GREEN cycle. Documented under 'TDD Gate Compliance' below rather than silently treated as a normal TDD pass."
  - "Kept the plan's boilerplate content-check assertion best-effort/defensive as specified — it inspects trimmed lines within chunk text for an exact BOILERPLATE_PATTERNS match rather than asserting a specific chunk count change, since the real HIPAA PDF fixture's exact boilerplate occurrence count is not pinned by any prior test."

requirements-completed: [CLEAN-01]

coverage:
  - id: D1
    description: "clean_document threads its in-memory parsed_doc into clean(parsed_artifact_id, source_id, parsed_doc=parsed_doc, settings=settings) and forwards clean_result['cleaned_doc'] under the same 'parsed_doc' key — chunk_document, tree_index_document, enrich_document, and curate_document_asset required zero code changes"
    requirement: "CLEAN-01"
    verification:
      - kind: integration
        ref: "tests/integration/test_dagster_assets.py::TestAssetMaterialization::test_dagster_materialize_produces_artifacts"
        status: pass
      - kind: integration
        ref: "tests/integration/test_dagster_assets.py::TestDefinitionsLoad::test_definitions_importable"
        status: pass
    human_judgment: false
  - id: D2
    description: "Materialize-test proof: clean_document's forwarded parsed_doc is a distinct object from parsed_document's parsed_doc (proves the uncleaned object is no longer forwarded verbatim)"
    requirement: "CLEAN-01"
    verification:
      - kind: integration
        ref: "tests/integration/test_dagster_assets.py::TestAssetMaterialization::test_dagster_materialize_produces_artifacts"
        status: pass
    human_judgment: false
  - id: D3
    description: "Defensive content check: no chunk_document chunk text contains an unremoved page-footer boilerplate line matching BOILERPLATE_PATTERNS' Page-N-of-M pattern"
    requirement: "CLEAN-01"
    verification:
      - kind: integration
        ref: "tests/integration/test_dagster_assets.py::TestAssetMaterialization::test_dagster_materialize_produces_artifacts"
        status: pass
    human_judgment: false
  - id: D4
    description: "curate_document_asset (D-03) regression check: produces a non-None quality_score and a status key with zero code change to curate.py, proving it re-fetches cleaned text from S3 independently of the in-memory dict-value swap"
    requirement: "CLEAN-01"
    verification:
      - kind: integration
        ref: "tests/integration/test_dagster_assets.py::TestAssetMaterialization::test_dagster_materialize_produces_artifacts"
        status: pass
    human_judgment: false

duration: 6min
completed: 2026-07-16
status: complete
---

# Phase 17 Plan 02: Close the Bypass — Dagster Wiring Summary

**`clean_document` now forwards the cleaned `ParsedDoc` (not the raw uncleaned one) under the same `"parsed_doc"` key to `chunk_document`/`tree_index_document`/`enrich_document`, proven by a materialize-test object-identity assertion and a curate_document_asset regression check — the literal CLEAN-01 acceptance criterion, with zero changes to any of the three consumer assets or to curate.py.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-16T04:59:39Z (17-01 completion commit)
- **Completed:** 2026-07-16T05:05:37Z
- **Tasks:** 2
- **Files modified:** 2 (`src/knowledge_lake/dagster_defs/assets.py`, `tests/integration/test_dagster_assets.py`)

## Accomplishments

- `clean_document` (`assets.py`) now calls `clean(parsed_artifact_id, source_id, parsed_doc=parsed_doc, settings=settings)` and forwards `clean_result["cleaned_doc"]` under the `"parsed_doc"` dict key, replacing the previous verbatim forward of the raw uncleaned object.
- `chunk_document`, `tree_index_document`, `enrich_document`, and `curate_document_asset` required zero code changes — confirmed by `git diff --stat` scoping the diff to `clean_document`'s function body only.
- Extended `test_dagster_materialize_produces_artifacts` with three new assertions proving: (1) `clean_document`'s forwarded `parsed_doc` is a distinct object from `parsed_document`'s (object-identity check — the literal CLEAN-01 proof), (2) no `chunk_document` chunk text contains an unremoved page-footer boilerplate line, and (3) `curate_document_asset` still produces a valid `quality_score`/`status` (D-03 regression, zero code change to `curate.py`).
- Full `tests/integration/test_dagster_assets.py` suite (15 tests) and the full `tests/unit` + `tests/integration` suite (977 passed, 3 skipped, 6 xfailed, 0 failed) stayed green.

## Task Commits

1. **Task 1: Forward the cleaned ParsedDoc from clean_document** - `6e6348a` (feat)
2. **Task 2: Materialize-test proof of cleaned forwarding and curate regression check** - `a0e316f` (test)

**Plan metadata:** (this commit, following)

## Files Created/Modified

- `src/knowledge_lake/dagster_defs/assets.py` — `clean_document`'s `clean()` call now passes `parsed_doc=parsed_doc`; its return dict forwards `clean_result["cleaned_doc"]` under the `"parsed_doc"` key; docstring updated to describe the forwarded value as the CLEANED ParsedDoc.
- `tests/integration/test_dagster_assets.py` — added `import re`; extended `test_dagster_materialize_produces_artifacts` with the object-identity, boilerplate-content, and curate-regression assertions described above.

## Decisions Made

- **Task 2's tdd="true" attribute did not produce a classic RED->GREEN cycle within Task 2 itself.** The plan deliberately split implementation (Task 1, non-TDD) from proof-of-behavior (Task 2, tdd="true"). Since Task 1's commit already shipped the forwarding change, writing Task 2's test caused it to pass immediately rather than fail first. Per the fail-fast rule's own carve-out ("the feature may already exist"), this was investigated and confirmed to be the plan's intended structure, not a stale/incorrect test — see TDD Gate Compliance below.
- Kept the docstring comment update on `clean_document` (not explicitly listed as a required line in the plan's acceptance criteria, but within the plan's scoped edit to `clean_document`'s own body) to prevent the now-stale "forwarded in-memory" wording from misleadingly implying the object is still the uncleaned one.

## TDD Gate Compliance

Plan `type` is `execute` (not `tdd`), so the plan-level RED/GREEN/REFACTOR gate sequence validation does not apply to this plan as a whole. Task 2 individually carries `tdd="true"` with a `<behavior>` block. Its test commit (`a0e316f`) was written and run only after Task 1's `feat` commit (`6e6348a`) had already landed the underlying implementation — so the new assertions passed on first run rather than failing first. This is consistent with the plan's own task boundary (Task 1 = implementation, Task 2 = materialize-test proof of that implementation plus an independent curate regression check) and was verified deliberate, not a stale/no-op test: reverting Task 1's change locally and re-running would fail the new object-identity assertion (not independently re-verified via revert-and-rerun in this execution, since the plan's own commit-boundary design makes that redundant — Task 1's diff is fully isolated to `clean_document` and directly produces the object-identity divergence the new test checks).

## Deviations from Plan

None — plan executed exactly as written. All four `must_haves.truths` from the plan frontmatter are satisfied:

1. ✅ `clean_document` threads `parsed_doc=parsed_doc` into `clean()` and forwards `clean_result["cleaned_doc"]` under the same `"parsed_doc"` key.
2. ✅ `chunk_document`, `tree_index_document`, `enrich_document` require zero code changes — confirmed via `git diff --stat` scoping and by full-suite green.
3. ✅ `curate_document_asset` and `pipeline/curate.py` require zero code changes — verified by the new D-03 regression assertion (`quality_score`/`status` present after materialization), not a code change.
4. ✅ `result.output_for_node("clean_document")["parsed_doc"] is not result.output_for_node("parsed_document")["parsed_doc"]` — asserted and passing.

One acceptance-criterion literalism note (non-blocking): the plan's acceptance criteria for Task 1 states `grep -n "parsed_doc=parsed_doc" src/knowledge_lake/dagster_defs/assets.py` should match "exactly once." The grep in fact matches twice in the final file — once inside `clean_document` (this task's new line) and once pre-existing inside `enrich_document`'s unrelated call to `pipeline.enrich.enrich_document`'s own `parsed_doc=parsed_doc` kwarg (present before this plan ran, untouched by this task). The task's own scoped edit is correctly singular and isolated to `clean_document`; the acceptance criterion's exact-match wording did not anticipate the pre-existing unrelated match elsewhere in the file. No fix needed — `git diff --stat` (the plan's second acceptance criterion) confirms the diff is fully scoped to `clean_document`.

## Issues Encountered

None.

## Next Phase Readiness

- Plan 17-03 (`process_crawled` CLI/API/MCP wiring) can insert the identical `clean(..., parsed_doc=parsed_doc, ...)` call pattern between `parse()` and `chunk()`, following the exact shape now proven in the Dagster path.
- Plan 17-04 (quality-audit) can rely on the Dagster path now genuinely delivering cleaned text to chunk/tree/enrich, so audit findings against gold RAG corpus chunks reflect the post-fix behavior for any newly materialized documents.
- No blockers. Full unit + integration suite (977 passed, 3 skipped, 6 xfailed, 0 failed) green; `tests/integration/test_dagster_assets.py` (15/15) green including `TestDefinitionsLoad`, `TestResourcesUseEnvVar`, and `test_lineage_resolves_after_dagster_materialize`.
- The Docker Compose stack (postgres, minio, qdrant, litellm) was already running in this environment and was used for the materialize test.

---
*Phase: 17-close-the-bypass-measurement*
*Completed: 2026-07-16*

## Self-Check: PASSED

- FOUND: src/knowledge_lake/dagster_defs/assets.py
- FOUND: tests/integration/test_dagster_assets.py
- FOUND: .planning/phases/17-close-the-bypass-measurement/17-02-SUMMARY.md
- FOUND commits: 6e6348a, a0e316f
