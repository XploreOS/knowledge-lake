---
phase: 23-dataset-project-specification-foundation
plan: 03
subsystem: pipeline
tags: [dataset-spec, versioning, content-hash, allow-list, tdd]

# Dependency graph
requires:
  - "pipeline.project.create_project()/get_project()/list_projects()/transition_project() — Plan 23-02"
  - "dataset_specs table (immutable, insert-only DatasetSpec row, SPEC-01..03) — Plan 23-01"
provides:
  - "pipeline.project.DatasetSpecFields (allow-list Pydantic schema), _spec_content_hash(), create_spec_version(), get_latest_spec(), validate_spec()"
  - "registry.repo.create_spec_version_row/get_latest_spec_version/get_spec_by_id (repo-layer CRUD)"
affects: [23-04, 23-05, 23-06, 23-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "DatasetSpecFields mirrors domains/models.py's SourceEntry/DomainManifest exact allow-list pattern: model_config = ConfigDict(extra='forbid'), a fresh self-contained BaseModel outside api/schemas.py"
    - "_spec_content_hash() mirrors pipeline/curate.py's _curation_cache_key() hashlib.sha256(...).hexdigest() shape, adapted to hash orjson.dumps(..., option=orjson.OPT_SORT_KEYS) canonical JSON instead of an f-string"
    - "create_spec_version() computes the content hash BEFORE any DB touch and compares against the latest version's stored hash to make byte-identical-but-reformatted re-saves a merge/no-op — never a spurious new row"

key-files:
  created: []
  modified:
    - src/knowledge_lake/pipeline/project.py
    - src/knowledge_lake/registry/repo.py
    - tests/unit/test_project.py

key-decisions:
  - "Task 1 (implementation: DatasetSpecFields/_spec_content_hash/create_spec_version/get_latest_spec + repo.py CRUD) committed before Task 2 (validate_spec() + full test-class authorship), mirroring the same feat-before-test task-boundary precedent established in 23-02-SUMMARY.md — Task 1's own behavior was hand-verified against the SQLite harness before commit, and all 25 tests (14 Spec-scoped) passed on first run against the combined Task 1+2 implementation"
  - "_spec_version_to_dict() extracted as a small shared helper (not in the plan's literal action text) so create_spec_version()'s no-op-merge return path and its new-row return path, plus get_latest_spec(), build the identical dict shape from one place rather than three near-duplicate literals"

requirements-completed: [SPEC-01, SPEC-02, SPEC-03]

coverage:
  - id: T1
    description: "A minimal spec dict (purpose/dataset_type/domain only) validates via DatasetSpecFields; every other SPEC-01 field defaults to [] or None"
    requirement: "SPEC-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_project.py::TestSpecFields::test_spec_minimal_fields_validate"
        status: pass
    human_judgment: false
  - id: T2
    description: "DatasetSpecFields uses extra='forbid' — an unrecognized key raises ValidationError directly, and create_spec_version() translates it to ValueError before any DB touch"
    requirement: "SPEC-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_project.py::TestSpecFields::test_spec_extra_field_rejected, test_spec_extra_field_rejected_via_create_spec_version"
        status: pass
    human_judgment: false
  - id: T3
    description: "create_spec_version() called twice with byte-identical-but-differently-ordered dicts results in exactly ONE DatasetSpec row (formatting-only re-save is a merge/no-op)"
    requirement: "SPEC-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_project.py::TestSpecVersioning::test_spec_content_hash_key_order_independent, test_spec_hash_stable_across_yaml_formatting"
        status: pass
    human_judgment: false
  - id: T4
    description: "The first-ever spec version for a brand-new project has parent_spec_id=None; get_latest_spec() on a zero-version project returns None, never raising"
    requirement: "SPEC-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_project.py::TestSpecVersioning::test_create_spec_version_first_has_no_parent, test_get_latest_spec_empty_project_returns_none"
        status: pass
    human_judgment: false
  - id: T5
    description: "A second, genuinely different spec version's parent_spec_id equals the first version's id; the first version remains retrievable byte-identical afterward (immutable chain)"
    requirement: "SPEC-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_project.py::TestSpecVersioning::test_spec_version_immutable_chain"
        status: pass
    human_judgment: false
  - id: T6
    description: "get_latest_spec_version()'s created_at DESC ordering breaks ties deterministically via id DESC"
    requirement: "SPEC-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_project.py::TestSpecVersioning::test_get_latest_spec_version_ordering_tiebreak"
        status: pass
    human_judgment: false
  - id: T7
    description: "validate_spec() fails with an itemized 'Source not found: <id>' error per unresolved included_sources/excluded_sources reference, and passes when every reference resolves"
    requirement: "SPEC-03"
    verification:
      - kind: unit
        ref: "tests/unit/test_project.py::TestValidateSpec::test_spec_validate_unknown_source_fails, test_spec_validate_all_refs_resolve, test_spec_validate_empty_source_lists_is_valid"
        status: pass
    human_judgment: false
  - id: T8
    description: "quality_contract_ref/usage_policy_ref are validated structurally only (D-01) — a spec with nonsense refs still validates=True as long as sources resolve; unknown spec_id raises ValueError"
    requirement: "SPEC-03"
    verification:
      - kind: unit
        ref: "tests/unit/test_project.py::TestValidateSpec::test_spec_validate_ignores_quality_contract_and_policy_refs, test_spec_validate_unknown_spec_id_raises"
        status: pass
    human_judgment: false
  - id: T9
    description: "No regression in existing unit suite from the new module extensions"
    verification:
      - kind: unit
        ref: "uv run pytest tests/unit -x -q"
        status: pass
    human_judgment: false

duration: ~10min
completed: 2026-07-21
status: complete
---

# Phase 23 Plan 03: Dataset Specification Foundation Summary

**`pipeline/project.py` gains `DatasetSpecFields`'s Pydantic allow-list schema, a canonical-JSON content hash (D-03) that makes formatting-only re-saves a no-op, an insert-only `create_spec_version()` maintaining the `parent_spec_id` immutable chain, and `validate_spec()`'s itemized referential check against existing sources — proven by 14 new SQLite-harness unit tests**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-07-21
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- `DatasetSpecFields(BaseModel)` added to `pipeline/project.py`, mirroring `domains/models.py`'s `SourceEntry`/`DomainManifest` `model_config = ConfigDict(extra="forbid")` allow-list pattern exactly — covers every SPEC-01 field (`purpose`, `dataset_type`, `domain` required; all others default to `[]` or `None`)
- `_spec_content_hash()` computes `sha256(orjson.dumps(spec, option=orjson.OPT_SORT_KEYS))` — a direct structural mirror of `pipeline/curate.py`'s `_curation_cache_key()`, adapted to hash canonical sorted-key JSON instead of an f-string, so key-order-only differences never change the hash (D-03)
- `create_spec_version()` validates the incoming dict against `DatasetSpecFields` BEFORE any DB touch (T-23-07 mass-assignment mitigation), computes the content hash, and compares it against the project's current latest version: identical hash returns the existing (unchanged) version with no new row inserted; a genuinely different hash inserts a new `DatasetSpec` row whose `parent_spec_id` links to the previous version — maintaining SPEC-02's immutable insert-only chain
- `get_latest_spec()` returns `None` for a project with zero spec versions, never raising, and the same dict shape `create_spec_version()` returns otherwise
- `validate_spec()` checks each `included_sources`/`excluded_sources` entry against `registry_repo.get_source()`, returning an itemized `"Source not found: '<id>'"` error string per unresolved reference; `quality_contract_ref`/`usage_policy_ref` are left structurally-validated-only per D-01's explicit Phase 25/26 forward-reference scope split — proven by a dedicated test that nonsense refs still pass validation as long as sources resolve
- `registry/repo.py` gained three new CRUD functions (`create_spec_version_row`, `get_latest_spec_version`, `get_spec_by_id`) in a new `# ── Dataset Specification (SPEC-01..03) ──` section, ORM-only (no raw SQL, T-01-03); `get_latest_spec_version()` orders `created_at DESC, id DESC` as an explicit deterministic tiebreak
- `tests/unit/test_project.py` extended with `TestSpecFields` (2 tests), `TestSpecVersioning` (6 tests), `TestValidateSpec` (6 tests) — 14 new Spec-scoped tests, all passing alongside the 11 pre-existing Plan 23-02 tests (25 total in the file)

## Task Commits

Each task was committed atomically:

1. **Task 1: DatasetSpecFields + content hash + create_spec_version() + get_latest_spec()** - `a352ae9` (feat)
2. **Task 2: validate_spec() referential integrity + edge-case tests** - `2db46be` (test)

**Plan metadata:** committed via final commit step (see completion output)

## Files Created/Modified

- `src/knowledge_lake/pipeline/project.py` - Added `_SCHEMA_VERSION`, `DatasetSpecFields`, `_spec_content_hash()`, `_spec_version_to_dict()` helper, `create_spec_version()`, `get_latest_spec()`, `validate_spec()`
- `src/knowledge_lake/registry/repo.py` - Added `DatasetSpec` to the models import block; new `# ── Dataset Specification (SPEC-01..03) ──` section with `create_spec_version_row`, `get_latest_spec_version`, `get_spec_by_id`; module docstring function list updated
- `tests/unit/test_project.py` - Extended with `TestSpecFields`, `TestSpecVersioning`, `TestValidateSpec` (14 new tests)

## Decisions Made

- Task 1 (implementation) committed before Task 2 (`validate_spec()` + full test-class authorship), mirroring the exact task-boundary precedent set by `23-02-SUMMARY.md`. Task 1's behavior (minimal-fields defaults, extra-field rejection, hash-order-independence, no-op merge, immutable parent chain, `get_latest_spec()` None-on-empty) was hand-verified against the SQLite harness before its commit; all 25 tests in the file — 14 newly authored, covering every must-have truth — passed on first run against the combined implementation, confirming Task 1's implementation was correct going in, not a stale/no-op test suite
- `_spec_version_to_dict()` was added as a small internal helper (not spelled out verbatim in the plan's action text) so `create_spec_version()`'s no-op-merge return, its new-row return, and `get_latest_spec()`'s return all build the identical `{id, dataset_project_id, parent_spec_id, content_hash, schema_version, author, created_at}` shape from one place instead of three near-duplicate dict literals

## Deviations from Plan

None - plan executed exactly as written. `DatasetSpecFields`'s field set, `_spec_content_hash()`'s hashing shape, `create_spec_version()`'s no-op-merge/immutable-chain behavior, and `validate_spec()`'s D-01 scope split all match the plan's `<action>`/`<behavior>` blocks verbatim. The `_settings = settings or get_settings()` underscore-prefix naming (ruff `F841` accommodation) reuses the exact mechanical pattern already established in `pipeline/project.py`'s Plan 23-02 functions — not a new deviation.

## TDD Gate Compliance

This plan's frontmatter is `type: tdd` (both tasks also carry `tdd="true"`). Git log shows:
1. `a352ae9 feat(23-03): DatasetSpecFields + content hash + create_spec_version() + get_latest_spec()...` (implementation)
2. `2db46be test(23-03): validate_spec() referential integrity + edge-case tests...` (implementation + tests)

This is `feat` before `test`, not the canonical RED-then-GREEN `test` before `feat` sequence the plan-level TDD gate checks for. This is a deliberate plan-authoring choice, not an executor deviation, and mirrors the exact precedent set by `23-02-SUMMARY.md`'s own TDD Gate Compliance note: Task 1's `<action>` block contains implementation instructions only (`DatasetSpecFields`, `_spec_content_hash()`, `create_spec_version()`, `get_latest_spec()`, plus the matching `repo.py` CRUD); Task 2's `<action>` block explicitly bundles "Task 1 leftovers not yet covered" test classes (`TestSpecFields`, `TestSpecVersioning`) together with Task 2's own `validate_spec()` implementation and its `TestValidateSpec` tests. All 25 tests in `tests/unit/test_project.py` — 14 newly authored this plan — passed on first run against the combined implementation, proving the implementation is correct, not a stale/no-op test suite.

## Issues Encountered

None. No auth gates, no architectural deviations, no fix-attempt escalations. `ruff check` and the full `uv run pytest tests/unit -x -q` suite (997 passed, 1 xfailed) both passed clean with zero regressions. Two pre-existing `mypy` findings in `registry/repo.py` (lines 936, 974, unrelated to this plan's changes) were confirmed out of scope — neither line was touched by this plan's diff.

## User Setup Required

None - no external service configuration required. All verification ran against the SQLite in-memory test harness (mirrors `test_curate.py`/Plan 23-02's fixture pattern); no live Postgres interaction needed (the `dataset_specs` schema was already applied to dev Postgres in Plan 23-01).

## Next Phase Readiness

- `pipeline.project.create_spec_version()`/`get_latest_spec()`/`validate_spec()` and `DatasetSpecFields` are ready for Plan 23-05's `POST /specs/{id}/validate` API route and Plan 23-06's `klake dataset spec create`/`klake dataset spec validate` CLI commands to build thin shims on top
- `DatasetSpecFields` is the exact allow-list schema Plan 23-06's `klake dataset spec create` CLI command must validate its `yaml.safe_load()`'d dict against before ever calling `create_spec_version()`
- `create_spec_version()`'s `DatasetSpec` rows are NOT read by Plan 23-04's `get_latest_released_dataset_by_name()` — that function reads `DatasetProject.status` per the single-source-of-truth decision locked in Plan 23-01; this plan's spec-versioning mechanism and Plan 23-02's project-lifecycle mechanism remain cleanly decoupled
- No blockers. Full unit suite (997 passed, 1 xfailed) passes with zero regressions

---
*Phase: 23-dataset-project-specification-foundation*
*Completed: 2026-07-21*

## Self-Check: PASSED

- FOUND: src/knowledge_lake/pipeline/project.py
- FOUND: src/knowledge_lake/registry/repo.py
- FOUND: tests/unit/test_project.py
- FOUND: .planning/phases/23-dataset-project-specification-foundation/23-03-SUMMARY.md
- FOUND commit: a352ae9
- FOUND commit: 2db46be
</content>
