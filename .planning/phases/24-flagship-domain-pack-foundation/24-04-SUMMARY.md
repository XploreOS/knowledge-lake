---
phase: 24-flagship-domain-pack-foundation
plan: 04
subsystem: database
tags: [dataset-project, dataset-spec, agent-security, lifecycle, project-py]

# Dependency graph
requires:
  - phase: 24-flagship-domain-pack-foundation
    provides: "7 real Source rows (domain='agent-security') registered end-to-end by Plan 24-02, one per sources.yaml entry"
provides:
  - "agent-security-spec.yaml: DatasetSpecFields YAML referencing all 7 real agent-security Source IDs, dataset_type=rag_corpus, allowed_license_categories covering the corpus's actual 5 distinct license strings"
  - "A real DatasetProject row ('AI Agent Security and Permission Dataset', domain=agent-security, dataset_type=rag_corpus) in status=ready"
  - "A real DatasetSpec version (dsp_019f8a45-78ff-71e1-90fa-cbbc615c4d88) that passes validate_spec() non-trivially against 7 real, existence-checked Source IDs"
affects: [25-usage-policy-engine, 26-quality-contract, 27-curation-engine, 28-candidates, 29-splits, 30-release, 31-lineage-eval, 32-flagship-release]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Reused Phase 23's unmodified pipeline/project.py lifecycle machinery (create_project/create_spec_version/validate_spec/transition_project) with zero code changes — this plan is pure CLI-driven registry state, same shape as Plan 24-02's ingestion work"

key-files:
  created:
    - .planning/phases/24-flagship-domain-pack-foundation/agent-security-spec.yaml
  modified: []

key-decisions:
  - "included_sources authored as the full real 7-Source-ID list (queried directly via SQLAlchemy against domain='agent-security'), never an empty list — satisfies Pitfall 6's non-trivial-validation requirement exactly as the plan's prohibition demanded"
  - "Task 2 (project transition) produced zero repository file changes — matches the plan's own <files></files> empty declaration; no per-task commit exists for Task 2, only Task 1's spec-YAML commit and this plan's final metadata commit"

patterns-established: []

requirements-completed: []

coverage:
  - id: D1
    description: "Dataset Project 'AI Agent Security and Permission Dataset' created (domain=agent-security, dataset_type=rag_corpus), first Dataset Specification version authored referencing all 7 real Source IDs, and validate_spec() passes non-trivially"
    verification:
      - kind: other
        ref: "uv run klake project new/dataset spec create/dataset spec validate CLI output: project created in status=draft, spec version dsp_019f8a45-78ff-71e1-90fa-cbbc615c4d88 created, 'Spec ... is valid.' printed with exit 0 against 7 non-empty included_sources"
        status: pass
      - kind: unit
        ref: "uv run pytest tests/unit/test_project.py -x -> 25 passed"
        status: pass
    human_judgment: false
  - id: D2
    description: "Project transitions draft -> configured -> sources_pending -> ready via the existing unmodified _TRANSITIONS map, reaching status=ready"
    verification:
      - kind: other
        ref: "uv run klake project transition (x3) CLI output: 'Project ... -> configured/sources_pending/ready' each with no Error: line; klake project show --json reports \"status\": \"ready\""
        status: pass
      - kind: unit
        ref: "uv run pytest tests/unit/test_project.py -x -> 25 passed (no regression to Phase 23's own lifecycle tests)"
        status: pass
    human_judgment: false

# Metrics
duration: 8min
completed: 2026-07-22
status: complete
---

# Phase 24 Plan 04: Flagship Dataset Project + Specification Summary

**Created the "AI Agent Security and Permission Dataset" project (dataset_type=rag_corpus) with a Dataset Specification referencing all 7 real agent-security Source IDs, validated non-trivially, and drove it through draft->configured->sources_pending->ready to status=ready.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-22T14:38:00Z
- **Completed:** 2026-07-22T14:41:11Z
- **Tasks:** 2/2 completed
- **Files modified:** 1

## Accomplishments
- Queried the real 7 `Source` rows for `domain='agent-security'` directly via SQLAlchemy (never guessed IDs), confirming the exact set and their license_type values registered by Plan 24-02.
- Authored `agent-security-spec.yaml` with `included_sources` set to all 7 real Source IDs, `dataset_type: rag_corpus` (D-07), `domain: agent-security`, and `allowed_license_categories` covering the corpus's actual 5 distinct license strings (`public-domain`, `CC-BY-SA-4.0`, `MIT`, `open`, `IETF-Trust`). Every other `DatasetSpecFields` key left at schema default, matching the plan's explicit instruction (Phase 25/26 forward-reference fields stay null per Phase 23 D-01 precedent).
- Created a real `DatasetProject` (`dpj_019f8a45-60d3-7d52-840c-278065d9867a`, "AI Agent Security and Permission Dataset") in status `draft`, with D-06's exact purpose text, three intended-use statements, and the dual-use prohibited-use statement.
- Created the project's first `DatasetSpec` version (`dsp_019f8a45-78ff-71e1-90fa-cbbc615c4d88`) from the YAML and ran `klake dataset spec validate` — passed non-trivially (`Spec '...' is valid.`, exit 0) against a real, non-empty `included_sources` list (Pitfall 6 satisfied).
- Drove the project through all three remaining legal transitions in `pipeline/project.py`'s unmodified `_TRANSITIONS` adjacency map: `configured` -> `sources_pending` -> `ready`, each succeeding with no `IllegalProjectTransitionError`. `klake project show --json` confirms `"status": "ready"`.
- `uv run pytest tests/unit/test_project.py -x` passed (25/25) both before and after this plan's work — no regression to Phase 23's lifecycle tests.

## Task Commits

1. **Task 1: Author the spec YAML, create the project, create + validate the spec version** - `fb96c4c` (feat) — commits `agent-security-spec.yaml`; the `DatasetProject`/`DatasetSpec` rows themselves are registry state, not repository files, created by the CLI commands run alongside this commit.
2. **Task 2: Transition the project to ready** - no repository files modified (plan's own `<files></files>` is empty for this task) — pure registry state change via three `klake project transition` CLI invocations against the existing, unmodified `_TRANSITIONS` map. No per-task commit exists.

**Plan metadata:** (this plan's SUMMARY.md/STATE.md/ROADMAP.md commit follows separately)

## Files Created/Modified
- `.planning/phases/24-flagship-domain-pack-foundation/agent-security-spec.yaml` - DatasetSpecFields YAML: purpose (D-06 text), dataset_type=rag_corpus (D-07), domain=agent-security, included_sources=[7 real src_ IDs], allowed_license_categories=[5 real license strings]

## Decisions Made
1. **included_sources authored as the full real 7-Source-ID list, never an empty list.** Queried `Source` rows directly (`domain == 'agent-security'`) rather than guessing/reusing IDs from a prior summary, per Pitfall 6's explicit warning that authoring an empty-list spec would trivially (and falsely) pass `validate_spec()`.
2. **Task 2 produced zero repository file changes**, matching the plan's own `<files></files>` empty declaration for that task — same "DB-state-only, no per-task commit" shape as Plan 24-02's Tasks 2/3.

## Deviations from Plan

None - plan executed exactly as written. Both tasks' acceptance criteria were met literally: `klake dataset spec validate` printed `Spec '<id>' is valid.` and exited 0 against a non-empty `included_sources`; `klake project show` reported `status: draft` immediately after `project new`; the spec's `included_sources` list length (7) equals the real agent-security Source row count; all three transitions printed `Project <id> -> <state>` with no `Error:` line and `klake project show --json` reports `"status": "ready"`.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. PostgreSQL, Qdrant, MinIO, and the LiteLLM proxy were already running (not directly used by this plan's CLI commands, which only touch the `dataset_projects`/`dataset_specs` tables via `pipeline/project.py`).

## Next Phase Readiness

- Phase 24's ROADMAP.md Success Criterion 4 is now fully satisfied: a Dataset Project scoped to the flagship pack exists in `ready` state (the stronger target D-05 selected, beyond the minimum `sources_pending`), with a validated Dataset Specification referencing 7 real, registered Source IDs.
- Phases 25-31 (Usage Policy, Quality Contract, CurationEngine, Candidates, Splits, Release, Lineage/Eval) now have a real, already-advanced `DatasetProject`/`DatasetSpec` pair (`dpj_019f8a45-60d3-7d52-840c-278065d9867a` / `dsp_019f8a45-78ff-71e1-90fa-cbbc615c4d88`) to build and test their own mechanisms against, instead of a synthetic fixture.
- `usage_policy_ref`/`quality_contract_ref` remain `null` on this spec version per Phase 23's D-01 forward-reference precedent — Phase 25/26 add referential enforcement for those fields without requiring a new spec version.
- No blockers for Phase 24 completion. This was the last plan in Phase 24 (4 of 4).

---
*Phase: 24-flagship-domain-pack-foundation*
*Completed: 2026-07-22*

## Self-Check: PASSED

- FOUND: `.planning/phases/24-flagship-domain-pack-foundation/agent-security-spec.yaml` (confirmed on disk)
- FOUND: commit `fb96c4c` (`git log --oneline --all | grep fb96c4c` matches)
- Registry state re-confirmed at write time: `DatasetProject` `dpj_019f8a45-60d3-7d52-840c-278065d9867a` status=`ready`; `DatasetSpec` `dsp_019f8a45-78ff-71e1-90fa-cbbc615c4d88` valid=`true`, errors=`[]`; `uv run pytest tests/unit/test_project.py -x` -> 25 passed.
