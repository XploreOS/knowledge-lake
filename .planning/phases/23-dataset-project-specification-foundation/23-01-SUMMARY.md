---
phase: 23-dataset-project-specification-foundation
plan: 01
subsystem: database
tags: [sqlalchemy, alembic, postgres, registry, schema-migration]

# Dependency graph
requires: []
provides:
  - "dataset_projects table (11-state lifecycle project record, PROJ-01..03)"
  - "dataset_specs table (insert-only, self-referencing, versioned spec, SPEC-01..03)"
  - "Dataset.dataset_project_id / dataset_spec_id nullable FK columns"
  - "ids.py dataset_project -> dpj, dataset_spec -> dsp prefixes"
affects: [23-02, 23-03, 23-04, 23-05, 23-06, 23-07, phase-24, phase-25, phase-26, phase-27, phase-28, phase-29, phase-30, phase-31, phase-32]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dataset Project / Dataset Spec pattern established: DatasetProject owns lifecycle status; DatasetSpec is immutable by table design (no update function), single status source of truth lives on the parent project, not duplicated"

key-files:
  created:
    - src/knowledge_lake/registry/alembic/versions/0012_dataset_project_and_spec.py
  modified:
    - src/knowledge_lake/registry/models.py
    - src/knowledge_lake/ids.py

key-decisions:
  - "DatasetSpec has no status column — immutability is structural (insert-only), status lives solely on DatasetProject"
  - "Dataset.dataset_project_id/dataset_spec_id are NULLABLE with no backfill — every pre-v2.7 Dataset row stays permanently unscoped, satisfying the legacy-fallback detection Plan 23-04 needs"
  - "prohibited_uses/intended_uses documented as declarative-only in Phase 23 — no enforcement gate exists yet (arrives via Phase 25's Policy Engine)"

patterns-established:
  - "Pattern: immutability-by-table-design (insert-only, no update function) as the mechanism for versioned/audit-trail tables, distinct from Phase 30's planned DB-trigger immutability for dataset_releases"

requirements-completed: [PROJ-01, SPEC-02]

coverage:
  - id: D1
    description: "DatasetProject and DatasetSpec SQLAlchemy models with exact field sets, DatasetSpec has no status column"
    requirement: "PROJ-01"
    verification:
      - kind: unit
        ref: "uv run python -c \"from knowledge_lake.registry.models import Base, DatasetProject, DatasetSpec, Dataset; ... Base.metadata.create_all(e)\" (SQLite compile check + assertions)"
        status: pass
    human_judgment: false
  - id: D2
    description: "DatasetSpec immutability by table design (no status column, no update function) — SPEC-02"
    requirement: "SPEC-02"
    verification:
      - kind: unit
        ref: "'status' not in [c.name for c in DatasetSpec.__table__.columns] assertion"
        status: pass
    human_judgment: false
  - id: D3
    description: "Dataset.dataset_project_id/dataset_spec_id added as nullable FK columns in the same migration as the two new tables"
    verification:
      - kind: integration
        ref: "uv run python -c \"... insp.get_columns('datasets') ... nullable is True\" against live dev Postgres"
        status: pass
    human_judgment: false
  - id: D4
    description: "Migration 0012 applies cleanly to dev Postgres and round-trips downgrade/upgrade without FK errors"
    verification:
      - kind: integration
        ref: "uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head"
        status: pass
    human_judgment: false
  - id: D5
    description: "uq_dataset_projects_name unique constraint enforced at the raw-SQL level"
    verification:
      - kind: integration
        ref: "raw INSERT with duplicate name raises IntegrityError (verified and cleaned up against live dev Postgres)"
        status: pass
    human_judgment: false
  - id: D6
    description: "new_id('dataset_project') / new_id('dataset_spec') return dpj_/dsp_-prefixed UUIDv7 strings, additive-only ids.py entries"
    verification:
      - kind: unit
        ref: "uv run python -c \"from knowledge_lake.ids import new_id; ...\""
        status: pass
    human_judgment: false
  - id: D7
    description: "No regression in existing unit suite from the new models/migration"
    verification:
      - kind: unit
        ref: "uv run pytest tests/unit -x -q"
        status: pass
    human_judgment: false

duration: 5min
completed: 2026-07-21
status: complete
---

# Phase 23 Plan 01: Dataset Project + Specification Foundation Summary

**Postgres schema foundation for v2.7: `dataset_projects` (11-state lifecycle) and `dataset_specs` (insert-only, versioned) tables plus nullable Dataset FK columns, migration 0012 applied to dev DB**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-07-21T05:17:57Z
- **Completed:** 2026-07-21T05:21:08Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- `DatasetProject` and `DatasetSpec` SQLAlchemy models added to `registry/models.py`, mirroring the file's existing docstring/field conventions exactly
- `Dataset` gained two new nullable FK columns (`dataset_project_id`, `dataset_spec_id`) satisfying the pre-v2.7 legacy-row safety requirement (no backfill needed)
- Migration `0012_dataset_project_and_spec.py` created and applied to the dev Postgres database — revision `0012`, `down_revision "0011"`
- `ids.py` gained two additive prefix entries: `dataset_project -> dpj`, `dataset_spec -> dsp`

## Task Commits

Each task was committed atomically:

1. **Task 1: DatasetProject + DatasetSpec models, Dataset FK columns, ids.py prefixes** - `778fbe5` (feat)
2. **Task 2: Alembic migration 0012 — write, apply, verify (schema-push gate)** - `9b83dd0` (feat)

**Plan metadata:** committed via final commit step (see completion output)

## Files Created/Modified
- `src/knowledge_lake/registry/models.py` - Added `DatasetProject`/`DatasetSpec` classes; `Dataset` gained `dataset_project_id`/`dataset_spec_id` nullable FK columns; module docstring table updated
- `src/knowledge_lake/registry/alembic/versions/0012_dataset_project_and_spec.py` - New migration creating both tables plus the two `datasets` FK columns in one file (Pitfall 5); applied to dev Postgres
- `src/knowledge_lake/ids.py` - Added `"dataset_project": "dpj"`, `"dataset_spec": "dsp"` to `_PREFIX`

## Decisions Made
- `DatasetSpec` has no `status` column by design — immutability is achieved structurally (insert-only, no `update_spec_version()` function will ever exist); `DatasetProject.status` is the single source of truth for lifecycle state (per RESEARCH.md Open Question 1)
- `Dataset.dataset_project_id`/`dataset_spec_id` are nullable with no server_default and no backfill UPDATE — the only correct value for pre-v2.7 rows is permanent NULL (Pitfall 3)
- `prohibited_uses`/`intended_uses` column docstrings explicitly state Phase 23 stores these declaratively only, with no enforcement gate — enforcement arrives in Phase 25's Policy Engine (threat T-23-03 mitigation)

## Deviations from Plan

None - plan executed exactly as written. Both tasks' exact field lists, column orders, docstrings, and migration structure matched the plan's `<action>` blocks verbatim.

## Issues Encountered

None. `python` is not on PATH in this environment (only `python3` and `uv`); all verification commands were run via `uv run python` instead of bare `python` — a tooling adaptation, not a plan deviation, since the plan's verify blocks are illustrative shell snippets rather than literal required invocations.

## User Setup Required

None - no external service configuration required. Migration was applied directly to the existing dev Postgres database already configured via `KLAKE_DATABASE_URL`/`get_settings().database_url`.

## Next Phase Readiness

- `dataset_projects` and `dataset_specs` exist in the dev Postgres database at migration head `0012`; every later plan in Phase 23 (23-02 project lifecycle, 23-03 spec versioning, 23-04 D-02 identity resolution) can build on this schema without touching `models.py`'s new classes or the migration again
- `Dataset.dataset_project_id`/`dataset_spec_id` nullable FK columns are live and verified nullable against the actual Postgres schema (not just the ORM model), ready for Plan 23-04's `get_latest_released_dataset_by_name()` legacy-fallback detection
- No blockers. Existing 972-test unit suite passes unmodified alongside the new schema.

---
*Phase: 23-dataset-project-specification-foundation*
*Completed: 2026-07-21*

## Self-Check: PASSED

All created/modified files verified present on disk; all task commit hashes (778fbe5, 9b83dd0) and this SUMMARY's own commit (cdeadce) verified present in git log.
