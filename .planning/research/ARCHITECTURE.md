# Architecture Research

**Domain:** DatasetOps control plane integration onto an existing document-ingestion/RAG framework (Python/SQLAlchemy/Dagster monolith)
**Researched:** 2026-07-19
**Confidence:** HIGH (grounded in direct inspection of `src/knowledge_lake/registry/models.py`, `ids.py`, `alembic/versions/`, `cli/app.py`, `agent/registry.py`, `dagster_defs/assets.py`, `pipeline/curate.py`, `pipeline/datasets.py`, `pipeline/export.py`, `api/schemas.py`)

> Note: this file supersedes the previous ARCHITECTURE.md (written 2026-07-15 for the v2.6 clean-stage-bypass milestone). That content is preserved in git history; this file is scoped entirely to v2.7 (Governed Dataset Production and Release Lifecycle).

## Standard Architecture

### System Overview

```
┌───────────────────────────────────────────────────────────────────────────┐
│  SURFACES (thin shims, zero business logic — D-02/D-03 pattern)           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────────────┐    │
│  │ cli/app.py│  │api/app.py│  │agent/    │  │ dagster_defs/assets.py │    │
│  │ (Typer)  │  │(FastAPI) │  │registry.py│  │ (asset/job/sensor defs)│    │
│  │ new:     │  │ new:     │  │(MCP TOOLS)│  │ new: release/curation  │    │
│  │ dataset_ │  │ /dataset,│  │ new: N   │  │ assets, +1 job         │    │
│  │ app,     │  │ /project,│  │ tools    │  │                        │    │
│  │ project_ │  │ /policy, │  │appended  │  │                        │    │
│  │ app,     │  │ /release │  │(assert   │  │                        │    │
│  │ policy_  │  │ routes   │  │count     │  │                        │    │
│  │ app,     │  │          │  │bumped)   │  │                        │    │
│  │ release_ │  │          │  │          │  │                        │    │
│  │ app      │  │          │  │          │  │                        │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───────────┬────────────┘    │
│       │             │             │                     │                 │
│       └─────────────┴──────┬──────┴─────────────────────┘                 │
│                             │  ALL call the SAME functions                │
├─────────────────────────────┴──────────────────────────────────────────────┤
│  APPLICATION / PIPELINE LAYER (business logic, one function per stage)     │
│  ┌────────────────┐ ┌─────────────────┐ ┌───────────────┐ ┌────────────┐ │
│  │pipeline/project │ │pipeline/policy.py│ │pipeline/       │ │pipeline/   │ │
│  │.py (NEW)       │ │(NEW)             │ │curation/ (NEW  │ │validation.py│ │
│  │Dataset Project  │ │Policy Definition │ │package,        │ │(NEW)       │ │
│  │+ Spec lifecycle │ │+ Policy Decision │ │generalizes     │ │Validation  │ │
│  │                │ │                 │ │curate.py)      │ │Run/Result  │ │
│  └────────────────┘ └─────────────────┘ └───────────────┘ └────────────┘ │
│  ┌────────────────┐ ┌─────────────────┐ ┌───────────────┐ ┌────────────┐ │
│  │pipeline/quality_│ │pipeline/datasets │ │pipeline/split.py│ │pipeline/   │ │
│  │contract.py (NEW)│ │.py (MODIFIED:   │ │(NEW: splits +  │ │release.py  │ │
│  │Quality Contract │ │Example Candidate │ │contamination)  │ │(NEW)       │ │
│  │evaluation       │ │lifecycle added) │ │                │ │Release     │ │
│  └────────────────┘ └─────────────────┘ └───────────────┘ └────────────┘ │
│  ┌────────────────┐                                                       │
│  │pipeline/eval.py │  All still: deferred imports, Settings-driven,       │
│  │(NEW)           │  session-scoped registry access, S3 via              │
│  │Evaluation Run   │  StorageBackend — same conventions as existing       │
│  └────────────────┘  pipeline/*.py                                        │
├─────────────────────────────────────────────────────────────────────────┤
│  REGISTRY LAYER (SQLAlchemy models + Alembic, PostgreSQL source of truth) │
│  registry/models.py (MODIFIED: +12-14 new model classes, +cols on        │
│  Dataset/DatasetExample)  ·  registry/repo.py (MODIFIED: +CRUD functions)│
│  registry/alembic/versions/0012..NNNN_*.py (NEW, additive only)          │
├─────────────────────────────────────────────────────────────────────────┤
│  STORAGE / EXTERNAL PLUGINS (unchanged contracts)                        │
│  S3/MinIO (StorageBackend) · Qdrant (VectorStorePlugin) · DataTrove      │
│  (first CurationEngine backend) · LiteLLM (ExampleValidator LLM calls)   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation Here |
|-----------|----------------|------------------------------|
| `pipeline/project.py` (NEW) | Dataset Project state machine (draft→…→archived) + Dataset Specification versioning/hashing | Mirrors `pipeline/curate.py`'s function shape: `create_project()`, `create_spec_version()`, `transition_project()`, deferred imports, `Settings`-driven |
| `pipeline/policy.py` (NEW) | Policy Definition CRUD + deterministic Policy Decision evaluation against `Source.license_type`/new policy axes | Pure-function decision engine first (deterministic-first constraint), LLM fallback only for `unknown` classification, gated by `LlmSpend` |
| `pipeline/curation/` (NEW package, generalizes `pipeline/curate.py`) | `CurationEngine` Protocol (prepare/execute/collect) + DataTrove backend + Curation Run/Result bookkeeping | See Pattern section below |
| `pipeline/quality_contract.py` (NEW) | Quality Contract rule evaluation at source/document/chunk/example/split/release levels, feeding Curation/Validation Runs | Reuses `pipeline/quality/` pure predicates (Phase 19) as one rule-type; contract itself is data-driven (YAML/DB), not code |
| `pipeline/validation.py` (NEW) | Validation Run + Result orchestration — runs Quality Contract rules over a scope (spec/split/release) and records partitioned outcomes | Analogous to `curate_document()`'s cache-check + write pattern |
| `pipeline/datasets.py` (MODIFIED) | Example Candidate lifecycle (generated→validating→accepted/recoverable/repaired/rejected) via `ExampleValidator` interface | Adds `status`/`generation_metadata` to `DatasetExample`; recovery attempts in new child table |
| `pipeline/split.py` (NEW) | Deterministic, versioned, group-aware split assignment + contamination gate | Replaces ad hoc `check_train_eval_contamination()` in `pipeline/export.py` with a first-class, persisted gate keyed off Quality Contract + splits |
| `pipeline/release.py` (NEW) | Immutable Dataset Release assembly: manifests, checksums, approvals | Writes `Dataset Release` + `Release Artifact` + `Release Approval` rows; snapshots `Dataset`/`DatasetExample` state, never mutates them |
| `pipeline/eval.py` (NEW) | Evaluation Run foundation + one adapter | Thin: records run config/results against a Release; no RAGAS/RAG-FiT integration yet (per milestone scope) |
| `registry/models.py` (MODIFIED) | New ORM classes + additive columns | See table-by-table decision below |
| `registry/alembic/versions/` (NEW files) | One additive migration per logically-grouped entity set | Linear chain continuing at `0012_*` |
| `cli/app.py` (MODIFIED) | New sub-Typer groups mirroring `domain_app` | `project_app`, `policy_app`, `dataset_app` (or fold into existing verbs) |
| `api/app.py` + `api/schemas.py` (MODIFIED) | New routes + Pydantic schemas reused by MCP | Handlers stay thin, call `pipeline/*.py` directly per D-02 |
| `agent/registry.py` (MODIFIED) | New `ToolDef` entries, `TOOLS` count assertion bumped | Handlers import from the new `pipeline/*.py` modules, never `api.app` |
| `dagster_defs/assets.py` (MODIFIED) | New assets for curation-run execution + release cutting; one new job | Curation/Validation/Release become Dagster-launched per milestone goal ("Dagster-launched" curation backend) |

## Recommended Project Structure

```
src/knowledge_lake/
├── pipeline/
│   ├── project.py            # NEW — Dataset Project + Spec lifecycle
│   ├── policy.py              # NEW — Policy Definition + Decision engine
│   ├── quality_contract.py    # NEW — Quality Contract rule evaluation
│   ├── validation.py          # NEW — Validation Run + Result orchestration
│   ├── split.py               # NEW — splits + contamination gate (supersedes ad hoc check in export.py)
│   ├── release.py             # NEW — Dataset Release assembly + manifests
│   ├── eval.py                 # NEW — Evaluation Run foundation
│   ├── curation/               # NEW package (generalizes curate.py)
│   │   ├── __init__.py
│   │   ├── protocol.py        # CurationEngine Protocol (prepare/execute/collect)
│   │   ├── datatrove_engine.py# first production backend — wraps _build_filters()/score_document() from curate.py
│   │   └── run.py             # Curation Run + Result bookkeeping (accepted/rejected/recoverable/quarantined writers)
│   ├── curate.py              # KEPT — becomes a thin back-compat wrapper calling curation/datatrove_engine.py (see Pattern 1)
│   ├── datasets.py            # MODIFIED — Example Candidate status/generation_metadata + recovery-attempt writes
│   ├── export.py              # MODIFIED — check_train_eval_contamination() delegates to split.py; existing signature kept for back-compat
│   └── quality/                # UNCHANGED — pure predicates, reused as one Quality Contract rule type
├── registry/
│   ├── models.py               # MODIFIED — +12-14 model classes, +columns on Dataset/DatasetExample
│   ├── repo.py                  # MODIFIED — +CRUD functions per new table
│   └── alembic/versions/
│       ├── 0012_dataset_project_and_spec.py
│       ├── 0013_policy_definition_decision.py
│       ├── 0014_quality_contract.py
│       ├── 0015_curation_run_result.py
│       ├── 0016_validation_run_result.py
│       ├── 0017_example_candidate_columns_and_recovery.py
│       ├── 0018_dataset_split_columns.py
│       └── 0019_dataset_release_artifact_approval_eval_run.py
├── cli/
│   └── app.py                  # MODIFIED — project_app/policy_app/dataset_app sub-Typers added
├── api/
│   ├── app.py                  # MODIFIED — new routes
│   └── schemas.py               # MODIFIED — new Pydantic models, shared with MCP
├── agent/
│   └── registry.py              # MODIFIED — new ToolDef entries, count assertion bumped
├── dagster_defs/
│   └── assets.py                 # MODIFIED — curation_run_asset, validation_run_asset, release assets/job
└── domains/
    └── healthcare/ (unchanged) + <flagship non-healthcare pack> (NEW, per milestone's flagship-proof requirement)
```

### Structure Rationale

- **`pipeline/curation/` as a package, not a single new file:** the milestone explicitly calls for a `CurationEngine` **Protocol** (prepare/execute/collect) with DataTrove as "the first production backend" — that's a Protocol + ≥1 implementation + run-bookkeeping, three concerns. A single `curation.py` would recreate the same "everything in one 400-line file" shape `curate.py` already has, which is exactly what's being generalized away from.
- **`curate.py` is kept, not deleted or renamed**, because its public functions (`curate_document`, `batch_dedup_corpus`, `score_document`) are called directly by `dagster_defs/assets.py::curate_document_asset`, the CLI `curate`/`dedupe` commands, and (per D-03) potentially an MCP tool. Renaming breaks every call site, and the "no logic in CLI/API/MCP" contract would be violated if those call sites had to be rewritten mid-migration. Wrap, don't rename (see Pattern 1).
- **One new pipeline module per major new concept**, matching the existing one-file-per-stage convention (`clean.py`, `chunk.py`, `enrich.py`, `curate.py`, `export.py`) rather than a generic `pipeline/governance.py` grab-bag — keeps deferred-import and Settings-per-stage conventions intact and keeps future diffs scoped.
- **Alembic migrations grouped by entity family, not one-per-table:** 12-14 conceptual tables in 12-14 migrations would be needlessly fragmented given several are tightly coupled (Policy Definition+Decision are always introduced together; Curation Run+Result likewise). Existing precedent: migration `0008_dataset_examples.py` added both `Dataset` columns AND the new `dataset_examples` table in one migration.

## Architectural Patterns

### Pattern 1: Generalize-by-wrapping, not generalize-by-rewriting

**What:** `pipeline/curate.py`'s `_build_filters()` and `score_document()` move (or get imported) into `pipeline/curation/datatrove_engine.py` as the concrete `CurationEngine` implementation. `curate_document()` and `batch_dedup_corpus()` in `curate.py` become thin wrappers that call the new engine and then also write the new `CurationRun`/`CurationResult` rows — but their **public signatures and existing `curated_document` artifact writes stay unchanged**, so `dagster_defs/assets.py::curate_document_asset`, the `klake curate`/`dedupe` CLI commands, and the DEDUP-01..03 downstream chain never see a breaking change.

**When to use:** Any time the milestone description says "generalizing the existing X" where X already has active call sites across CLI/API/Dagster.

**Trade-offs:** Slightly more indirection (an extra function-call layer) but zero call-site churn and zero risk of silently changing `curated_document` artifact semantics that DEDUP/EXPORT stages already depend on.

**Example:**
```python
# pipeline/curation/protocol.py
from typing import Protocol, Any

class CurationEngine(Protocol):
    def prepare(self, run_config: dict, settings: "Settings") -> "PreparedRun": ...
    def execute(self, prepared: "PreparedRun") -> "ExecutionResult": ...
    def collect(self, result: "ExecutionResult") -> dict[str, Any]: ...

# pipeline/curation/datatrove_engine.py
class DataTroveCurationEngine:
    """Wraps the existing datatrove filter classes — the same three filters
    _build_filters() in curate.py already configures. Never calls .run()."""
    def prepare(self, run_config, settings): ...   # builds filter list (was _build_filters)
    def execute(self, prepared): ...                 # per-doc .filter() loop (was score_document body)
    def collect(self, result): ...                   # accepted/rejected/recoverable/quarantined partitions

# pipeline/curate.py (kept, now a thin compat shim)
def curate_document(cleaned_artifact_id, source_id, *, settings=None):
    from knowledge_lake.pipeline.curation.datatrove_engine import DataTroveCurationEngine
    engine = DataTroveCurationEngine()
    ...  # same cache-check / write-artifact flow as today, plus a CurationResult row
```

### Pattern 2: Additive-only Alembic, "extend don't replace" for `Dataset`/`DatasetExample`

**What:** `Dataset.name` is UNIQUE and mutated in-place by `update_dataset_export()`; `DatasetExample.payload` is a loose JSON union with no split/status column. Rather than repurposing these into the new versioned/immutable concepts, add nullable columns (`status`, `generation_metadata`, `split`, `split_version`) directly to them via new migrations, and introduce **separate** tables for anything that needs immutability or 1-to-many structure the existing tables can't express.

**When to use:** Whenever the new concept is "the same row, with more facts about it" (Example Candidate == DatasetExample + lifecycle fields) vs. "a new kind of thing that references the old ones" (Dataset Release, which snapshots many Datasets/DatasetExamples at a point in time and must never be mutated the way `Dataset` is today).

**Trade-offs:** `Dataset` accumulates more columns over time (schema sprawl) but avoids a second parallel example-storage system and keeps `dataset_id`/`source_artifact_id` FKs intact for every existing exporter/CLI command that already queries `dataset_examples`.

### Pattern 3: New entities as `Artifact`-adjacent, not `Artifact`-shaped

**What:** None of the 15 new concepts should become `artifact_type` discriminator values inside the existing unified `Artifact` table. `Artifact` is explicitly the raw→parsed→chunk lineage tree (self-referencing, content-hash-keyed, one node per pipeline transformation of *document content*). Dataset Project, Policy Decision, Curation Run, Validation Run, Dataset Release, and Evaluation Run are **process/governance records**, not content-transformation nodes — they reference `Artifact`/`Source`/`Dataset` rows via foreign keys but live in their own tables, exactly like `LlmSpend`, `VectorCollection`, and `ChunkDedupLedger` already do (all `art_`-prefixed generically, not lineage nodes, per the existing docstring convention "not a lineage node").

**When to use:** Distinguishing "is this a transformation of document bytes" (→ `Artifact`) from "is this a fact/decision/run about artifacts, sources, or datasets" (→ its own table, referencing `Artifact`/`Source`/`Dataset` by FK).

**Trade-offs:** The existing `resolve_ancestry()` lineage-tree walk (used by `klake lineage` and the MCP `lineage` tool) will need a **second, complementary** query path for the new "Project → Release → Split → Example → Validation → Candidate → Chunk → Parsed Doc → Raw Doc → Source → Policy Decision" explorer view described in the milestone — this is explicitly a *different* graph (governance graph) layered on top of, not replacing, the existing `Artifact`/`LineageEvent` content-lineage graph. Build it as a new `pipeline/lineage_explorer.py` (or extend `lineage.py`) that joins across both graphs rather than trying to force governance rows into the `Artifact` self-FK.

## Answering the Seven Specific Questions

### 1. New tables vs. additive columns

| Conceptual entity | Decision | Rationale |
|---|---|---|
| Dataset Project | **NEW table** `dataset_projects` | Needs its own status enum/state machine (11 states) distinct from `Dataset`; `Dataset.name` uniqueness would collide with the "many datasets per project over time" shape |
| Dataset Specification + versions | **NEW 2 tables** `dataset_specs` (one row per version, FK to project, content-hash of the YAML/JSON) + reuse the existing content-hash-cache pattern (like `curate.py`'s `_curation_cache_key`) for idempotent re-application | Versions must be immutable and individually addressable (a Policy Decision or Curation Run references a *specific* spec version) — cannot be a mutable column on Project |
| Quality Contract | **NEW table** `quality_contracts` (+ optionally `quality_contract_rules` child table if rules need independent CRUD/versioning; otherwise rules as a JSON column) | Rules are data-driven (YAML/DB), referenced by both Curation and Validation runs — needs to be independently versioned like `filter_config_version` today |
| Policy Definition | **NEW table** `policy_definitions` | Declarative rule sets (approved/retrieval/training/commercial/etc. axes) — reusable across sources, not 1:1 with `Source` |
| Policy Decision | **NEW table** `policy_decisions`, FK to `Source` (extends `Source.license_type`, does not replace it) and to `policy_definitions` | Each decision is an auditable event (which policy, which source, which outcome, deterministic-or-LLM, timestamp) — an event log, same shape as `LineageEvent`, not a mutable column |
| Curation Run | **NEW table** `curation_runs` | A Run is a Dagster-launched execution with its own status/config/timing — no existing table fits |
| Curation Result | **NEW table** `curation_results` (partitioned: accepted/rejected/recoverable/quarantined), FK to `curation_runs` + `Artifact` | Per-document/per-chunk outcome record; must NOT silently overwrite `Artifact.metadata_["dedup_status"]`-style JSON blob (that pattern already caused the "everything crammed into metadata_" shape this milestone is trying to formalize) |
| Validation Run | **NEW table** `validation_runs` | Same shape as Curation Run — a scoped execution (spec/split/release) evaluating a Quality Contract |
| Validation Result | **NEW table** `validation_results`, FK to `validation_runs` | Same shape as Curation Result — passed/failed/recoverable/skipped/not-applicable, at source/document/chunk/example/split/release granularity (needs a `scope_type` + `scope_id` polymorphic-ish pair, since it spans 6 different levels) |
| Example Candidate | **NO new parent table.** ADDITIVE columns on `DatasetExample`: `status` (generated/validating/accepted/recoverable/repaired/rejected), `generation_metadata` (JSON) | This is exactly the milestone context's own suggested resolution — `DatasetExample` already carries `payload`/`source_artifact_id`/`_cache_key`; it just lacks a lifecycle column |
| Recovery Attempt | **NEW small child table** `example_recovery_attempts`, FK to `dataset_examples` | 1-to-many (an example can be repaired more than once) — cannot be a column on `DatasetExample` without losing history |
| Dataset Release | **NEW table** `dataset_releases`, FK to `dataset_specs` (which spec version), immutable once created | Confirmed by milestone context: "Dataset/DatasetExample extended, not replaced" — Release is the new immutable snapshot table |
| Release Artifact | **NEW table** `release_artifacts`, FK to `dataset_releases` | One-to-many manifest files (dataset/splits/dataset-card/quality/source/license/policy-decisions/lineage/validation/checksums/reproduce.yaml) — each is its own row with a storage_uri + checksum, not 10 columns on `dataset_releases` |
| Release Approval | **NEW table** `release_approvals`, FK to `dataset_releases` | Approval is an auditable event (who/when/decision), 1-to-many (could require multiple sign-offs) — event-log shape again |
| Evaluation Run | **NEW table** `evaluation_runs`, FK to `dataset_releases` | Foundation only per milestone scope; one adapter, own status/config/results JSON |
| Split assignment (implied by "splits" in Release manifest) | **ADDITIVE columns** on `DatasetExample`: `split` (train/validation/test), `split_version`, `split_group_key` | Group-aware split is a per-example fact, same granularity as `status` — no separate table needed unless split *definitions* themselves need independent versioning (if so, a thin `dataset_splits` table FK'd from spec version is cleaner than overloading `dataset_specs`) |

**Net new tables: 12–14** (`dataset_projects`, `dataset_specs`, `quality_contracts`, `policy_definitions`, `policy_decisions`, `curation_runs`, `curation_results`, `validation_runs`, `validation_results`, `example_recovery_attempts`, `dataset_releases`, `release_artifacts`, `release_approvals`, `evaluation_runs` — 14 if `quality_contract_rules` and `dataset_splits` are split out as their own tables too, which is the safer call given the milestone's granular "source/document/chunk/example/split/release" rule levels).
**Additive-column-only: 1 existing table meaningfully modified** (`DatasetExample` gets `status`, `generation_metadata`, `split`, `split_version`, `split_group_key`; `Dataset` itself gets no new columns and stays the mutable "current export" record the existing `klake generate-dataset`/`export` commands already use).

### 2. New ID prefixes

Current `_PREFIX` dict in `src/knowledge_lake/ids.py` maps 14 kinds to 9 distinct prefixes: `src, doc, chk, art, job, cst, dst, dex, idx`. Every new kind needs an entry. Proposed additions (all distinct 3-letter prefixes, none colliding with the existing 9):

| New kind | Proposed prefix |
|---|---|
| `dataset_project` | `dpj` |
| `dataset_spec` | `dsp` |
| `quality_contract` | `qct` |
| `policy_definition` | `pol` |
| `policy_decision` | `pde` |
| `curation_run` | `crn` |
| `curation_result` | `crs` |
| `validation_run` | `vrn` |
| `validation_result` | `vrs` |
| `example_recovery_attempt` | `rec` |
| `dataset_release` | `rel` |
| `release_artifact` | `rla` |
| `release_approval` | `apr` |
| `evaluation_run` | `evl` |
| `dataset_split` (if broken out as its own table) | `spl` |

All still generated via the existing `new_id(kind)` → `f"{prefix}_{uuid7()}"` convention — no change to `ids.py`'s mechanism (`_uuid_utils.uuid7()`), only additive dict entries in `_PREFIX`, fully backward compatible.

### 3. Where `CurationEngine` lives

New package `src/knowledge_lake/pipeline/curation/` (`protocol.py` + `datatrove_engine.py` + `run.py`). `pipeline/curate.py` is **kept as a thin compat wrapper** (Pattern 1 above) — its existing public functions (`curate_document`, `batch_dedup_corpus`, `score_document`, `_build_filters`) keep working for every existing call site (`dagster_defs/assets.py::curate_document_asset` at `assets.py:814`, CLI `curate`/`dedupe` at `cli/app.py:402`/`:430`, any MCP tool) while internally delegating to the new `DataTroveCurationEngine`. Do not delete or rename `curate.py` — that would require simultaneously rewriting every call site in the same migration, which the milestone's "backward-compatible CLI/API/MCP/export behavior" constraint (from PROJECT.md's "Preserve" list) explicitly rules out.

### 4. New CLI command groups

Follow the `domain_app` sub-Typer precedent exactly (`app.add_typer(domain_app, name="domain")` at `cli/app.py:1574`). Add:
- `project_app` → `klake project new/list/show/transition <name>` (Dataset Project + Spec lifecycle)
- `policy_app` → `klake policy define/decide/list` (Policy Definition + Decision)
- `dataset_app` → `klake dataset release <project> <spec-version>`, `klake dataset diff <release-a> <release-b>`, `klake dataset validate/curate-run` — the milestone context spells the diff command explicitly as `klake dataset diff`, which implies a single `dataset_app` group housing release/diff/validate/curate-run subcommands is the more literal fit, rather than a separate `release_app`.
- Do **not** flatten these into more top-level kebab verbs on `app` directly — the milestone context explicitly says "new `dataset`/`project`/`policy`/`curation`/`release` command groups, mirroring the existing `domain` sub-Typer group pattern," and 28 flat verbs already sit on `cli/app.py`'s root Typer today; grouping keeps `--help` navigable.
- Every new command keeps the existing convention: function-local deferred imports of `pipeline/*.py`, zero business logic in the command body, `typer.Exit(code=1)` on caught domain errors.

### 5. API + MCP reuse of D-02/D-03

- New Pydantic request/response schemas go in `api/schemas.py` alongside the existing ~40 (e.g. `ProjectCreate`/`ProjectOut`, `PolicyDecisionRequest`/`Out`, `CurationRunRequest`/`Out`, `ReleaseCreateRequest`/`Out`, `ReleaseDiffRequest`/`Out`) — same file, same naming convention (`*Request`/`*Response`/`*Out`).
- New FastAPI routes in `api/app.py` call the new `pipeline/*.py` functions directly, each handler docstring stating "Calls pipeline.X.Y() — the same function the CLI uses (D-02)," matching every existing handler's documented contract.
- New MCP `ToolDef` entries appended to `agent/registry.py`'s `TOOLS` list, `input_model=` reusing the **same** schemas just added to `api/schemas.py` (one schema, two surfaces — the existing pattern). Handlers import directly from the new `pipeline/*.py` modules — never from `api.app` (the explicit prohibition already documented at the top of `registry.py`).
- The hardcoded `assert len(TOOLS) == 11` at `agent/registry.py:375` (plus the duplicate-name assertion at `:376`) **must be bumped** to the new count in the same change that appends new tools — this is a deliberate tripwire, not an oversight, so treat it as a required edit, not a test to work around.
- Not every new entity needs an MCP tool — per the existing D-11 read/write split, prioritize exposing read tools (`get_release`, `diff_releases`, `list_curation_runs`) over every possible write action; mutating actions with real consequences (cutting an immutable Release, approving it) may be deliberately CLI/API-only for v2.7, the same way some governance actions might reasonably stay out of the agent surface — flag this as a decision for REQUIREMENTS.md rather than assuming full parity.

### 6. Dagster asset/job changes and the KL-16 interaction

Yes — new Dagster assets/job are required, and this **does** interact with (but does not strictly *require prerequisite-fixing*) KL-16:
- New assets: `curation_run_asset` (wraps the new `CurationEngine.execute()`, replacing/wrapping `curate_document_asset` at `assets.py:814`), `validation_run_asset`, and a `release_asset` (or a dedicated `dataset_release_job` since cutting a Release is a terminal, deliberately-triggered action rather than part of the continuous `core_pipeline_e2e_job` asset-selection chain at `assets.py:1073`).
- **KL-16 interaction:** the milestone's flagship proof is an "AI Agent Security and Permission Dataset" — a **non-healthcare** domain pack. Every existing asset in `assets.py` resolves `settings.domain.domain_name` via `DomainLoader.from_name(...)` at runtime (the documented KL-16 gap: "domain packs cannot contribute their own Dagster jobs/assets without editing framework source"). Because the new curation/validation/release assets are **framework-level**, not domain-level, they do **not** strictly require KL-16 to be fixed first — the flagship pack can run through the same generic `core_pipeline_e2e_job` + new curation/validation/release assets exactly like healthcare does today, with `domain_name` set via config/env, no code change needed.
  - However, if the flagship dataset's Quality Contract or Curation Run needs **domain-specific rules** (e.g., a security-taxonomy-aware quality rule analogous to healthcare's `filters.yaml` clinical-code allowlist), that logic will hit the exact same "framework code branches on `if settings.domain.domain_name`" pattern the existing assets already use (`assets.py:324-326`, `:402-404`, `:477-478`) — so it is **architecturally consistent to replicate the existing workaround** (not to fix KL-16) for v2.7. Recommend treating KL-16 as still-deferred tech debt unless a specific new asset genuinely cannot express itself via the `DomainLoader.from_name()` runtime branch (e.g., if the flagship pack needs a distinct Dagster *schedule/sensor*, not just parameterized asset behavior) — flag this as an open question for REQUIREMENTS.md rather than pre-deciding a KL-16 fix is in scope.

### 7. Suggested build order

Dependency-ordered, matching the milestone context's own hints and the state-machine described in PROJECT.md:

1. **Dataset Project + Dataset Specification** (`dataset_projects`, `dataset_specs`, `pipeline/project.py`, `dpj_`/`dsp_` prefixes) — everything else scopes to a project/spec version; must exist first.
2. **Policy Definition + Policy Decision** (`policy_definitions`, `policy_decisions`, `pipeline/policy.py`, `pol_`/`pde_` prefixes) — can be built in parallel with #1 since it extends `Source.license_type` independently, but Policy Decisions should be scopable to a Spec once #1 lands (per the milestone context's explicit ordering hint).
3. **Quality Contract** (`quality_contracts` [+ optional `quality_contract_rules`], `pipeline/quality_contract.py`, `qct_` prefix) — must exist before CurationEngine or ValidationRun can consume it; can start once #1 exists (contracts are scoped to a project/spec).
4. **CurationEngine Protocol + DataTrove backend + Curation Run/Result** (`pipeline/curation/`, `curation_runs`, `curation_results`, `crn_`/`crs_` prefixes; wraps `pipeline/curate.py`) — depends on #3 (contract to evaluate against) and #2 (policy decisions gate what's even eligible for curation).
5. **Example Candidate lifecycle + Recovery Attempt** (`DatasetExample.status`/`generation_metadata` columns, `example_recovery_attempts` table, `rec_` prefix; modifies `pipeline/datasets.py`) — depends on #4's curated output existing as candidate input.
6. **Validation Run/Result** (`validation_runs`, `validation_results`, `pipeline/validation.py`, `vrn_`/`vrs_` prefixes) — depends on #3 (contract) and #5 (candidates to validate); can partially overlap with #5's build if scoped carefully.
7. **Splits + contamination gate** (`DatasetExample.split`/`split_version`/`split_group_key` [+ optional `dataset_splits` table], `pipeline/split.py`, `spl_` prefix; supersedes `check_train_eval_contamination()` in `pipeline/export.py`) — depends on #5/#6 (only validated/accepted examples should be split); must exist before Release per the milestone context's explicit dependency note.
8. **Dataset Release + Release Artifact + Release Approval** (`dataset_releases`, `release_artifacts`, `release_approvals`, `pipeline/release.py`, `rel_`/`rla_`/`apr_` prefixes) — depends on #1 (spec being released), #2 (policy decisions manifest), #3/#6 (quality/validation manifest), #7 (splits manifest). This is the latest-dependent entity — confirmed by the milestone context's own note that Release must exist before diff/lineage-explorer.
9. **Evaluation Run foundation** (`evaluation_runs`, `pipeline/eval.py`, `evl_` prefix) — depends on #8 (evaluates against a cut Release); lowest-risk, can slip to last.
10. **`klake dataset diff` + lineage explorer extension** — depends on #8 (needs ≥2 Releases to diff) and reads across both the existing content-lineage graph (`Artifact`/`LineageEvent`) and the new governance-entity graph (Pattern 3 above); build last since it's read-only tooling over everything prior.
11. **Dagster wiring** (curation_run_asset, validation_run_asset, release job) — can be built incrementally alongside #4/#6/#8 rather than as one final step, since each pipeline function should get its Dagster asset wrapper as soon as it's stable (matching the existing precedent where every pipeline stage has a 1:1 asset).
12. **CLI/API/MCP surface wiring** (`project_app`, `policy_app`, `dataset_app` sub-Typers; new routes; new `ToolDef`s + bumped `TOOLS` assertion) — wire per-entity as each pipeline function lands (#1 through #10), not as one big final surface pass — this matches how prior milestones (v2.0, v2.5) shipped surface wiring phase-by-phase rather than as a separate "surfaces" phase.

**Flagship non-healthcare domain pack** (AI Agent Security and Permission Dataset) should be scaffolded early (right after or alongside step 1, using the existing `klake domain new` scaffolding command) so every subsequent step (#2 through #10) can be built and tested against real flagship data rather than synthetic fixtures — this also surfaces any KL-16-adjacent friction (question 6) as early as possible rather than at the end.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| Single flagship dataset (v2.7 scope) | Everything above is correctly sized — one project, one spec version chain, one release at a time is the actual proof target |
| Multiple concurrent Dataset Projects | `dataset_projects`/`dataset_specs` already designed for this (FK-scoped, no shared mutable state); Curation/Validation Runs already scoped per-project via spec FK — no architecture change needed |
| Multi-domain flagship packs (post-v2.7) | This is exactly where KL-16 (domain-pack-owned Dagster jobs) stops being deferrable — if a second non-healthcare pack needs a genuinely different Dagster schedule/sensor (not just parameterized asset behavior), KL-16 becomes a hard prerequisite rather than an optional one |

## Anti-Patterns

### Anti-Pattern 1: Cramming governance facts into `Artifact.metadata_` JSON

**What people do:** Following the path of least resistance already visible in `curate.py` (`metadata_["dedup_status"]`, `metadata_["filter_results"]`), it's tempting to add `metadata_["policy_decision"]`, `metadata_["quality_contract_result"]`, etc. to the existing JSON blob instead of new tables.
**Why it's wrong:** These become unqueryable without full-table JSON scans, unversioned, and un-auditable at the granularity the milestone demands (source/document/chunk/example/split/release — 6 distinct scopes, only two of which — document/chunk — map to an `Artifact` row at all; "split" and "release" have no `Artifact` row to attach metadata to).
**Do this instead:** First-class tables per Pattern 3, with proper FKs to `Artifact`/`Source`/`Dataset` where a relationship exists, and their own primary keys/timestamps/status columns.

### Anti-Pattern 2: Repurposing `Dataset`/`DatasetExample` in place instead of adding a Release layer

**What people do:** Add a `version` int and `is_released` bool directly to `Dataset`, treating "cutting a release" as just flipping a flag on the existing mutable row.
**Why it's wrong:** `Dataset.name` is UNIQUE and `update_dataset_export()` already mutates the row in place on every export (confirmed in `models.py`) — an immutable Release semantically cannot live on a row whose entire existing contract is "gets overwritten." Any code path that still calls `update_dataset_export()` for ordinary re-exports would silently corrupt a "released" dataset's frozen state.
**Do this instead:** `dataset_releases` as a genuinely separate, insert-only table that snapshots/references `Dataset`/`DatasetExample` rows (by ID + content hash) at the moment of cutting — exactly the pattern the milestone context itself already prescribes.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| DataTrove | `CurationEngine` Protocol implementation (`pipeline/curation/datatrove_engine.py`) | Same "in-memory `.filter()` loop, never `.run()`" constraint from `curate.py` carries forward unchanged |
| LiteLLM | `ExampleValidator` LLM-backed validators call through existing LiteLLM gateway wrapper, budget-capped via `LlmSpend` | No new gateway integration — reuse `pipeline/enrich.py`'s existing LiteLLM call pattern |
| Dagster | New assets registered in `dagster_defs/assets.py`, one new `dataset_release_job` (`define_asset_job`) | Reuse `_PIPELINE_RETRY`/`_EXPORT_RETRY` `RetryPolicy` constants already defined at `assets.py:71,76` |
| S3/MinIO | Release manifests (`reproduce.yaml`, `checksums`, etc.) written via existing `StorageBackend`, gold-zone segmented per `release_artifacts.storage_uri` | No new storage abstraction |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `pipeline/curation/` ↔ `pipeline/curate.py` | Direct function call (wrapper delegates to engine) | Pattern 1 — one-directional, `curate.py` depends on `curation/`, never the reverse |
| `pipeline/quality_contract.py` ↔ `pipeline/quality/` (existing predicates) | Direct import/reuse | Quality Contract rules can wrap existing pure predicates as one rule type among several |
| `pipeline/release.py` ↔ `Dataset`/`DatasetExample` | Read-only snapshot (FK references + content hashes), never writes back to `Dataset`/`DatasetExample` | Enforces immutability — Release is a consumer, not a mutator |
| `pipeline/split.py` ↔ `pipeline/export.py::check_train_eval_contamination()` | `export.py`'s function becomes a thin delegator to `split.py`'s new persisted gate, OR is left as a legacy fallback path with the new gate as the primary check for anything scoped to a Dataset Project | Confirm which in REQUIREMENTS.md — the milestone context labels the old function "replacing," implying full delegation, but existing callers of `check_train_eval_contamination()` need a compatible return shape during transition |
| Governance graph (new) ↔ Content-lineage graph (existing `Artifact`/`LineageEvent`) | New `pipeline/lineage_explorer.py` joins both via FK, existing `lineage.py::resolve_ancestry()` untouched | Two distinct graphs, one explorer UI/CLI command spanning both |

## Sources

- Direct code inspection: `src/knowledge_lake/registry/models.py` (655 lines, all 9 existing model classes read in full)
- Direct code inspection: `src/knowledge_lake/ids.py` (full file — `_PREFIX` dict, `new_id()`)
- Direct code inspection: `src/knowledge_lake/registry/alembic/versions/` (directory listing, 11 migrations, `0008_dataset_examples.py` precedent for grouped migrations)
- Direct code inspection: `src/knowledge_lake/pipeline/curate.py` (full 434-line file)
- Direct code inspection: `src/knowledge_lake/pipeline/datasets.py`, `pipeline/export.py` (`check_train_eval_contamination` signature + docstring)
- Direct code inspection: `src/knowledge_lake/cli/app.py` (grep of all `@app.command`/`@domain_app.command`, full `domain_app` sub-Typer block)
- Direct code inspection: `src/knowledge_lake/agent/registry.py` (header docstring, `TOOLS` assertion lines, `ToolDef` dataclass)
- Direct code inspection: `src/knowledge_lake/dagster_defs/assets.py` (all asset/job/sensor names, `RetryPolicy` constants, `DomainLoader.from_name()` call sites)
- Direct code inspection: `src/knowledge_lake/api/schemas.py` (all ~40 existing Pydantic model names)
- `.planning/PROJECT.md` (v2.7 milestone target features, constraints, "Preserve" list, current state)

---
*Architecture research for: Knowledge Lake Framework v2.7 (DatasetOps control plane repositioning)*
*Researched: 2026-07-19*
