# Phase 23: Dataset Project + Specification Foundation - Research

**Researched:** 2026-07-21
**Domain:** Governance data-model foundation (Postgres tables + state machine + versioned/hashed spec) layered onto an existing SQLAlchemy/Typer/FastAPI/MCP/Dagster monolith
**Confidence:** HIGH — every claim below is grounded in direct inspection of the actual files this phase touches (line numbers cited throughout); no new external libraries are introduced, so there is no package-registry risk surface for this phase.

## Summary

Phase 23 is a pure internal-extension phase: two new Postgres tables (`dataset_projects`, `dataset_specs`), one new pipeline module (`pipeline/project.py`), one new CLI sub-Typer group (`project_app`), a handful of new FastAPI routes + Pydantic schemas, three new read-only MCP tool shims, and a single new registry function (`get_latest_released_dataset_by_name()`) that all four existing `export_finetune_dataset(dataset_name)` call sites must be repointed at in the same commit. Every pattern this phase needs already has a direct precedent in the codebase: `pipeline/curate.py` for pipeline-module shape (deferred imports, `Settings`-driven, function-not-class), `domain_app` (`cli/app.py:1569-1633`) for the sub-Typer group pattern, `TrainEvalContaminationError` (`pipeline/export.py:90`) for typed domain exceptions, `_curation_cache_key`/`_dataset_gen_cache_key` (`pipeline/curate.py:80-91`, `pipeline/datasets.py:139-150`) for the content-hash convention, and `0008_dataset_examples.py`/`0011_chunk_dedup_ledger.py` for migration shape.

No new production dependencies are required. `pyyaml` (already pinned, already used via `yaml.safe_load` in `domains/loader.py`) covers spec authoring; `hashlib` (stdlib) covers the spec content hash; `orjson` (already pinned) can serialize the canonical JSON form for hashing. The Package Legitimacy Gate is not applicable to this phase — zero new third-party packages are introduced.

The single highest-leverage risk this phase must close is the one CONTEXT.md's D-02 already names precisely: today `export_finetune_dataset(dataset_name)` resolves via `registry_repo.get_dataset_by_name()`, which does a `SELECT ... WHERE name = X LIMIT 1` against a table with a `UNIQUE(name)` constraint (`registry/models.py:576`) — a single deterministic row. The moment `dataset_projects`/`dataset_specs` exist and a `Dataset` row can be associated with a project that has been through multiple spec versions, `Dataset.name` alone is no longer sufficient identity information for "give me the dataset a human means when they type this name" — unless the resolution rule is made explicit in code, not left to accidental row order. This phase's Success Criterion 5 is exactly a test of that rule.

A second, easy-to-miss risk: this codebase's typed-domain-exception convention (`TrainEvalContaminationError`, a `RuntimeError` subclass) is **not** automatically MCP-safe. `agent/server.py`'s `call_tool` handler only auto-converts `(ValueError, LookupError)` to a readable `isError=True` result (`_EXPECTED_ERRORS`, `agent/server.py:33`); `TrainEvalContaminationError` needed its own hand-written `except` clause with a lazy import (`agent/server.py:115-138`) to get the same treatment. `IllegalProjectTransitionError` (D-04) is a `RuntimeError` subclass by design, matching that same precedent — meaning if a *future* phase adds a mutating `project_transition` MCP tool, `agent/server.py` needs a third special-cased `except` block added at that time. Phase 23 itself ships **read-only** MCP tools only (D-05), so `IllegalProjectTransitionError` never crosses the MCP boundary this phase — document this explicitly so the gap doesn't silently resurface when a later phase adds the mutating tool.

**Primary recommendation:** Build `pipeline/project.py` as a direct structural mirror of `pipeline/curate.py` (function-shaped, deferred imports, `Settings`-driven, `get_session()` context manager); add exactly one new registry function `get_latest_released_dataset_by_name()` that all four `export_finetune_dataset` call sites route through in the same commit; ship the migration as `0012_dataset_project_and_spec.py` following `0008_dataset_examples.py`'s grouped-but-scoped shape; add `project_app` as a direct copy of the `domain_app` sub-Typer registration pattern; and bump `agent/registry.py`'s `TOOLS` assertion from `11` to `14` in the same commit that appends the three new read tools.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PROJ-01 | Create Dataset Project (name, description, purpose, intended/prohibited uses, dataset_type, domain pack, owners) | `dataset_projects` table design below; mirrors `Source`/`Dataset` column style (`registry/models.py:59-137`, `566-601`) |
| PROJ-02 | 11-state guarded lifecycle, illegal transitions rejected with clear error | State machine + `IllegalProjectTransitionError` pattern below, mirroring `TrainEvalContaminationError` (`pipeline/export.py:90`) |
| PROJ-03 | `klake project new/list/show/transition` (CLI) + API | `domain_app` sub-Typer precedent (`cli/app.py:1569-1633`); `cmd_lineage`'s show-with-`--json` pattern (`cli/app.py:938-971`) |
| SPEC-01 | Declarative Dataset Specification (YAML/JSON), all listed fields including forward-referencing `quality_contract_ref`/`policy_ref` | `yaml.safe_load` convention (`domains/loader.py:12,47,75`); D-01's forward-reference-nullable decision |
| SPEC-02 | Every spec change -> new immutable version with content hash, schema version, timestamp, author, parent-version link | `_curation_cache_key`/`_dataset_gen_cache_key` content-hash convention (`pipeline/curate.py:80-91`, `pipeline/datasets.py:139-150`); D-03's canonical-JSON-hash decision |
| SPEC-03 | `klake dataset spec validate` — schema + referential integrity (sources only, this phase) | D-01's structural-now/referential-later split; existing `get_domain_for_source`/source-lookup precedent in `registry/repo.py` |
| SURFACE-01 | New CLI groups mirror `domain_app`; existing commands unchanged | `cli/app.py:1569-1633` exact pattern read below |
| SURFACE-02 | New API routes reuse shared Pydantic schemas, call `pipeline/*.py` directly | `export_endpoint`'s D-02 docstring convention (`api/app.py:1199-1219`); `ExportRequest`/`ExportResponse` naming (`api/schemas.py:244-282`) |
| SURFACE-03 | New MCP tools are thin read-only shims; `TOOLS` count bumped in same change | `agent/registry.py`'s `TOOLS` list (11 entries, `agent/registry.py:246-376`), `ToolDef` dataclass, `registered_tools(readonly)` split |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Dataset Project lifecycle state machine | API / Backend (`pipeline/project.py`) | Database (Postgres row + enum-shaped `status` column) | Business logic (transition-graph validation) belongs in the pipeline layer per D-02/D-03; the DB only persists state, it does not enforce the transition graph (no DB trigger needed here — contrast with REL-02's later DB-trigger requirement, which is a different, harder immutability guarantee) |
| Dataset Specification versioning + content hash | API / Backend (`pipeline/project.py`) | Database (`dataset_specs`, insert-only) | Hash computation and canonicalization is pure application logic; immutability is achieved by insert-only table design (no UPDATE path exists), not a DB trigger — simpler than Release's later immutability requirement because nothing here needs post-hoc mutation exemptions |
| Spec validation (schema + referential) | API / Backend (`pipeline/project.py` or a `validate_spec()` function within it) | Database (existence checks against `sources`) | Deterministic-first constraint (PROJECT.md) — no LLM involvement; referential checks are plain SQL existence lookups via `registry/repo.py` |
| `export_finetune_dataset(name)` resolution rule | API / Backend (`registry/repo.py::get_latest_released_dataset_by_name()`) | Database (`Dataset`/`dataset_projects`/`dataset_specs` join) | This is a read-path identity-resolution rule, not a UI concern — must live in one function per D-02, called identically from CLI/API/MCP/Dagster |
| CLI/API/MCP surface convention (project_app, routes, thin shims) | CLI / API / Backend surfaces (`cli/app.py`, `api/app.py`, `agent/registry.py`) | — | Convention-setting only — no new architectural tier, just the established thin-shim-over-pipeline pattern (D-02/D-03) applied to a fourth concept family |
| Illegal-transition error surfacing | API / Backend (raise in `pipeline/project.py`) | CLI (exit code 1) / API (HTTP 409) / — MCP (deferred, no mutating tool this phase) | Error origin is backend; each surface adapts the same exception to its own idiom, matching `TrainEvalContaminationError`'s existing multi-surface handling |

## Standard Stack

### Core

No new libraries. This phase is 100% additive Python code + one Alembic migration using dependencies already pinned in `uv.lock`.

| Library | Version (pinned in `uv.lock`) | Purpose | Why Standard (here) |
|---------|---------|---------|--------------|
| PyYAML | 6.0.3 [VERIFIED: uv.lock] | Parse the authored Dataset Specification YAML | Already the exclusive YAML-parsing library in this codebase (`domains/loader.py`); `yaml.safe_load` only, per T-06-04 |
| SQLAlchemy | 2.0.x (per CLAUDE.md stack table) | `dataset_projects`/`dataset_specs` ORM models | Existing ORM for every table in `registry/models.py` |
| Alembic | 1.18.5 [VERIFIED: uv.lock] | `0012_dataset_project_and_spec.py` migration | Existing migration tool, 11 prior migrations in the same directory |
| Pydantic | 2.13.4 [VERIFIED: uv.lock] | New request/response schemas in `api/schemas.py` | Existing schema library for every API/MCP input model |
| hashlib (stdlib) | n/a | Spec content hash (`sha256`) | Matches `_curation_cache_key`/`_dataset_gen_cache_key`/WR-05 chunk-hash convention exactly — no new hash library |
| uuid_utils | pinned (per `ids.py`) | `new_id("dataset_project")`/`new_id("dataset_spec")` | Existing ID-generation mechanism; only `ids.py`'s `_PREFIX` dict needs two new entries |
| orjson | pinned (per CLAUDE.md) | Canonical JSON serialization for the spec content hash (sorted keys) | Already used for JSONL export (`pipeline/export.py:44`); `orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)` gives a deterministic byte sequence to hash |

### Supporting

None required beyond the Core table — this phase adds zero new runtime surface area (no new external service, no new file format beyond YAML which is already supported).

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Insert-only `dataset_specs` table for immutability | A `version` column mutated in place on `dataset_projects` | Rejected — SPEC-02 explicitly requires "the previous version remains retrievable unmodified"; mutation cannot satisfy that. Matches ARCHITECTURE.md's own Anti-Pattern 2 warning against repurposing mutable rows for immutable-by-design concepts. |
| `hashlib.sha256` over canonical JSON | `xxhash` (already pinned, used for chunk/document dedup keys) | `xxhash` is chosen elsewhere for *speed* at high-volume dedup (per-chunk hashing at ingest scale). Spec versions are a low-frequency, human-triggered event (edit → save) where SHA-256's stronger collision resistance and audit-friendly reputation for "content hash of a governance artifact" is worth the negligible speed difference to keep the two hash-purposes conceptually distinct. Both are `[ASSUMED]`-tier choices — flag as Claude's Discretion in the Assumptions Log below if the executor wants xxhash consistency instead. |

**Installation:** None — no `pyproject.toml`/`uv.lock` changes required for this phase.

## Package Legitimacy Audit

**Not applicable to this phase.** Zero new external packages are introduced. Every library used (`pyyaml`, `sqlalchemy`, `alembic`, `pydantic`, `hashlib`, `orjson`, `uuid_utils`) is already pinned in `uv.lock` and in active use elsewhere in the codebase. The Package Legitimacy Gate protocol is skipped per its own trigger condition ("every phase that installs external packages") — this phase installs none.

## Architecture Patterns

### System Architecture Diagram

```
                         ┌─────────────────────────────────────────────┐
                         │  CLI (Typer)         API (FastAPI)   MCP     │
                         │  project_app         /projects,      3 read  │
                         │  new/list/show/      /projects/{id}, tools:  │
                         │  transition          /specs routes   project_│
                         │                                       list,  │
                         │                                       project_│
                         │                                       show,  │
                         │                                       spec_  │
                         │                                       validate│
                         └───────────────┬───────────────┬───────┬──────┘
                                         │               │       │
                    all three call the SAME pipeline/project.py functions
                                         │               │       │
                         ┌───────────────▼───────────────▼───────▼──────┐
                         │  pipeline/project.py                         │
                         │  create_project() ────────────────┐          │
                         │  create_spec_version() ─┐          │          │
                         │  transition_project() ──┼──────────┼─raises──┼─► IllegalProjectTransitionError
                         │  validate_spec() ────────┼──────────┘          │
                         │  get_latest_released_dataset_by_name()        │◄─ called by CLI export,
                         └───────────────┬─────────────────┬─────────────┘   API export_endpoint,
                                         │                 │                  MCP _export_dispatch,
                                         │                 │                  Dagster export_finetune_dataset
                         ┌───────────────▼───┐   ┌─────────▼──────────┐   asset (4 call sites, D-02)
                         │  registry/repo.py │   │  registry/models.py│
                         │  create_project() │   │  DatasetProject    │
                         │  create_spec_     │   │  DatasetSpec       │
                         │  version()        │   │  (+ FK link on     │
                         │  get_project_by_  │   │   Dataset for      │
                         │  id/name()        │   │   D-02 resolution) │
                         │  get_latest_      │   └─────────┬──────────┘
                         │  released_dataset_│             │
                         │  by_name()        │   ┌─────────▼──────────┐
                         └───────────────────┘   │  Postgres           │
                                                  │  dataset_projects   │
                                                  │  dataset_specs      │
                                                  │  datasets (existing,│
                                                  │  new nullable FK)   │
                                                  └─────────────────────┘
```

### Recommended Project Structure

```
src/knowledge_lake/
├── pipeline/
│   └── project.py                 # NEW — create_project(), create_spec_version(),
│                                   #        transition_project(), validate_spec(),
│                                   #        IllegalProjectTransitionError
├── registry/
│   ├── models.py                  # MODIFIED — +DatasetProject, +DatasetSpec classes;
│   │                               #   +nullable dataset_project_id FK on Dataset
│   ├── repo.py                    # MODIFIED — +create_project, +get_project_by_id,
│   │                               #   +get_project_by_name, +list_projects,
│   │                               #   +create_spec_version, +get_spec_version,
│   │                               #   +get_latest_spec_version, +get_latest_released_dataset_by_name
│   └── alembic/versions/
│       └── 0012_dataset_project_and_spec.py   # NEW — single migration, both tables + Dataset FK
├── cli/
│   └── app.py                     # MODIFIED — project_app sub-Typer + `klake dataset spec validate`
├── api/
│   ├── app.py                     # MODIFIED — /projects, /projects/{id}, /projects/{id}/transition,
│   │                               #   /projects/{id}/specs, /specs/{id}/validate routes
│   └── schemas.py                 # MODIFIED — ProjectCreate/ProjectOut/ProjectTransitionRequest,
│                                   #   SpecVersionCreate/SpecVersionOut/SpecValidateResponse
├── agent/
│   └── registry.py                # MODIFIED — +3 read ToolDefs (project_list, project_show,
│                                   #   spec_validate); TOOLS assertion 11 -> 14
├── dagster_defs/
│   └── assets.py, definitions.py  # MODIFIED — 4th export_finetune_dataset call site repointed
└── ids.py                         # MODIFIED — +"dataset_project": "dpj", +"dataset_spec": "dsp"
```

### Pattern 1: `pipeline/project.py` mirrors `pipeline/curate.py`'s exact shape

**What:** Function-shaped module (not class-shaped), deferred imports at function scope (not module scope), `Settings`-driven configuration via `settings: Settings | None = None` kwargs, `get_session()` context-manager usage for every DB interaction.

**When to use:** Every new `pipeline/*.py` module in this codebase — this is not phase-specific guidance, it is the established house style (`curate.py`, `export.py`, `datasets.py`, `enrich.py` all follow it).

**Example:**
```python
# pipeline/project.py — structural template, mirrors curate.py:1-50
"""Dataset Project + Specification lifecycle (PROJ-01..03, SPEC-01..03).

Design decisions:
  D-02 (CONTEXT.md): get_latest_released_dataset_by_name() is the ONE function
        all four export_finetune_dataset call sites route through — never an
        implicit side effect of query ordering.
"""
from __future__ import annotations

import datetime
import hashlib

import orjson
import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.ids import new_id
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session

log = structlog.get_logger(__name__)

# ── 11-state lifecycle graph (PROJ-02) ────────────────────────────────────
_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"configured"},
    "configured": {"sources_pending", "draft"},
    "sources_pending": {"ready", "configured"},
    "ready": {"processing", "configured"},
    "processing": {"validating", "failed"},
    "validating": {"review_required", "failed"},
    "review_required": {"releasable", "failed"},
    "releasable": {"released", "failed"},
    "released": {"archived"},
    "failed": {"draft", "archived"},
    "archived": set(),
}


class IllegalProjectTransitionError(RuntimeError):
    """Raised when transition_project() is asked to move a project through an
    edge not present in _TRANSITIONS (PROJ-02, D-04).

    Mirrors pipeline.export.TrainEvalContaminationError's shape: a RuntimeError
    subclass, NOT auto-caught by agent/server.py's _EXPECTED_ERRORS tuple
    (ValueError, LookupError) — a future MCP mutating tool needs its own
    special-cased except clause there, same as TrainEvalContaminationError got.
    """

    def __init__(self, from_state: str, to_state: str, legal_next: set[str]) -> None:
        self.from_state = from_state
        self.to_state = to_state
        self.legal_next_states = sorted(legal_next)
        super().__init__(
            f"Illegal transition: {from_state!r} -> {to_state!r}. "
            f"Legal next states from {from_state!r}: {self.legal_next_states}"
        )


def transition_project(project_id: str, to_state: str, *, settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    with get_session() as session:
        project = registry_repo.get_project_by_id(session, project_id)
        if project is None:
            raise ValueError(f"Dataset Project not found: {project_id!r}")
        legal_next = _TRANSITIONS.get(project.status, set())
        if to_state not in legal_next:
            raise IllegalProjectTransitionError(project.status, to_state, legal_next)
        project.status = to_state
        return {"id": project.id, "status": project.status}
```

### Pattern 2: Canonical-JSON content hash for spec versioning (SPEC-02, D-03)

**What:** Hash the *parsed* spec (dict), not the raw YAML bytes — sorted-key JSON serialization gives a stable hash immune to YAML formatting/reordering, matching D-03's decision and the codebase's existing `_curation_cache_key`/`_dataset_gen_cache_key` pattern of hashing a stable derived representation rather than raw input bytes.

**When to use:** Any time a "content hash" needs to survive cosmetic re-formatting of its source representation — exactly the property SPEC-02 needs ("editing produces a new version" should mean *semantic* edits, not YAML re-indentation).

**Example:**
```python
# pipeline/project.py
def _spec_content_hash(parsed_spec: dict) -> str:
    """SHA256 over canonical (sorted-key) JSON serialization of the parsed spec.

    Mirrors _curation_cache_key (pipeline/curate.py:80-91) and
    _dataset_gen_cache_key (pipeline/datasets.py:139-150) — hash a stable
    derived form, not raw file bytes, so formatting-only edits (re-indent,
    key reorder) do NOT produce a spurious new version (D-03).
    """
    canonical_bytes = orjson.dumps(parsed_spec, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(canonical_bytes).hexdigest()
```

### Pattern 3: `project_app` sub-Typer group is a direct copy of `domain_app`

**What:** `domain_app` (`cli/app.py:1569-1633`) is the exact, only existing precedent for a CLI sub-Typer group in this codebase — it has exactly ONE command (`new`) registered today. Reproduce its registration shape verbatim for `project_app`, then add `new`/`list`/`show`/`transition` commands to it, following `cmd_lineage`'s (`cli/app.py:938-971`) show-with-`--json`-flag convention for `project show` and `dataset spec validate`.

**When to use:** SURFACE-01's explicit instruction to mirror `domain_app`.

**Example:**
```python
# cli/app.py — mirrors domain_app registration at cli/app.py:1569-1574 exactly
project_app = typer.Typer(
    name="project",
    help="Create and manage Dataset Projects.",
    add_completion=False,
)
app.add_typer(project_app, name="project")


@project_app.command(name="new")
def cmd_project_new(
    name: str = typer.Argument(..., help="Dataset Project name."),
    dataset_type: str = typer.Option(..., "--dataset-type", "-t"),
    domain: str | None = typer.Option(None, "--domain", "-D"),
) -> None:
    from knowledge_lake.pipeline.project import create_project

    try:
        result = create_project(name=name, dataset_type=dataset_type, domain=domain)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Created project {result['id']!r} in state 'draft'")


@project_app.command(name="transition")
def cmd_project_transition(
    project_id: str = typer.Argument(...),
    to_state: str = typer.Argument(...),
) -> None:
    from knowledge_lake.pipeline.project import IllegalProjectTransitionError, transition_project

    try:
        result = transition_project(project_id, to_state)
    except IllegalProjectTransitionError as exc:
        # D-04: clear, specific error naming the invalid transition + legal next states
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Project {project_id} -> {result['status']}")
```

**Rich-markup gotcha (KL-13) carried forward:** if any new CLI help string embeds a literal regex character class (`[a-z]`) the way `_DOMAIN_NAME_HELP_PATTERN` does (`cli/app.py:1580`), it must be escaped (`.replace("[", "\\[")`) or Typer's Rich-markup rendering silently strips it. Applies if `project new`'s `--name` gets a validation-pattern help string.

### Pattern 4: `IllegalProjectTransitionError` -> HTTP 409, first use of 409 in this codebase

**What:** `grep -rn "status_code=409"` across the entire `src/` tree returns zero matches today — every existing API error path uses 422 (`export_endpoint`'s `TrainEvalContaminationError`/`ValueError` handling, `api/app.py:1243-1248`) or 404. D-04 explicitly calls for 409 Conflict for illegal transitions. This is architecturally correct (409 = state-conflict, which is exactly what an illegal lifecycle transition is — distinct from 422's "your input was malformed") but it is a **new pattern**, not a copy of an existing one — flag this in the plan as a deliberate, first-of-its-kind status code choice, not an oversight.

**Example:**
```python
# api/app.py
@app.post("/projects/{project_id}/transition", response_model=ProjectOut, tags=["project"])
def transition_project_endpoint(project_id: str, body: ProjectTransitionRequest) -> ProjectOut:
    from knowledge_lake.pipeline.project import IllegalProjectTransitionError, transition_project

    try:
        result = transition_project(project_id, body.to_state)
    except IllegalProjectTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "illegal_transition",
                "from_state": exc.from_state,
                "to_state": exc.to_state,
                "legal_next_states": exc.legal_next_states,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProjectOut(**result)
```

### Pattern 5: The one-function resolution rule for `export_finetune_dataset(name)` (D-02, Pitfall 2)

**What:** `get_latest_released_dataset_by_name()` sits in `registry/repo.py` alongside (not replacing) `get_dataset_by_name()`. All four call sites (`cli/app.py:1280`, `api/app.py:1242`, `agent/registry.py:130`, `dagster_defs/assets.py:1034`) call `export_finetune_dataset()` unchanged; `export_finetune_dataset()` itself (`pipeline/export.py:546`) is the ONE place that switches from `get_dataset_by_name()` to the new resolution function — so the four call sites need zero code changes at all, only `pipeline/export.py`'s internals change. This is the cleanest possible interpretation of D-02's "route through one function, never independently" instruction.

**Example:**
```python
# registry/repo.py — new function, alongside get_dataset_by_name (repo.py:1341)
def get_latest_released_dataset_by_name(session: Session, name: str) -> Dataset | None:
    """D-02 resolution rule for export_finetune_dataset(name) (no version arg).

    If `name` resolves to a Dataset row FK'd to a dataset_project: resolve to
    the Dataset tied to that project's spec version last transitioned into
    'released' state (highest created_at on ties — pinned by test, should never
    happen per PROJ-02's guarded transitions).
    If `name` has no associated dataset_project (pre-v2.7 legacy dataset):
    fall back UNCHANGED to get_dataset_by_name() behavior.
    """
    dataset = get_dataset_by_name(session, name)
    if dataset is None or dataset.dataset_project_id is None:
        return dataset  # legacy path, byte-identical to today's behavior
    stmt = (
        select(Dataset)
        .join(DatasetSpec, DatasetSpec.id == Dataset.dataset_spec_id)
        .where(
            Dataset.dataset_project_id == dataset.dataset_project_id,
            DatasetSpec.status == "released",  # or wherever "released" is tracked
        )
        .order_by(Dataset.created_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()
```

```python
# pipeline/export.py:546 — the ONLY internal change; call sites are untouched
def export_finetune_dataset(dataset_name: str, *, domain=None, settings=None) -> dict:
    ...
    with get_session() as session:
        dataset = registry_repo.get_latest_released_dataset_by_name(session, dataset_name)  # was get_dataset_by_name
        if dataset is None:
            raise ValueError(f"Dataset not found: {dataset_name!r}")
        ...
```

### Anti-Patterns to Avoid

- **Adding a DB-layer immutability trigger for `dataset_specs`:** Not needed this phase. Immutability is achieved structurally — there is simply no `update_spec_version()` function; the table is insert-only by construction. Save the Postgres `BEFORE UPDATE` trigger pattern (Pitfall 4, PITFALLS.md) for Phase 30's `dataset_releases`, which has a harder problem (a narrow allowlist of legitimately-mutable post-release fields). Building a trigger here is premature generalization of a pattern this phase doesn't need yet.
- **Repurposing `Dataset.name`'s `UNIQUE` constraint or the existing `get_dataset_by_name()`/`get_or_create_dataset()` functions:** Leave them completely unchanged (ARCHITECTURE.md Anti-Pattern 2). `dataset_projects` is a genuinely new, separate table — not a rename or ALTER of `datasets`.
- **Cramming `dataset_projects`/`dataset_specs` facts into `Artifact.metadata_` JSON:** These are governance/process records, not content-lineage transformation nodes (ARCHITECTURE.md Anti-Pattern 1, Pattern 3). They get their own tables with FKs, never a JSON blob key.
- **Making `IllegalProjectTransitionError` a `ValueError` subclass "for convenience" (auto-caught by `_EXPECTED_ERRORS`):** D-04 and the `TrainEvalContaminationError` precedent both call for a distinct `RuntimeError` subclass so callers must explicitly `except IllegalProjectTransitionError` (or the broader `RuntimeError`) rather than it silently blending into generic input-validation handling. If a future MCP mutating tool is added, its `except` clause in `agent/server.py` needs the same explicit special-casing `TrainEvalContaminationError` got — don't assume `ValueError`-style auto-handling will cover it.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Prefixed unique IDs for the two new tables | A custom ID-generation function in `pipeline/project.py` | `new_id("dataset_project")` / `new_id("dataset_spec")` after adding two entries to `ids.py`'s `_PREFIX` dict | `ids.py` is the single, already-proven mechanism (`uuid_utils.uuid7()`) for every other entity in the registry — adding a parallel ID scheme would break the self-describing-prefix convention every other tool/log line relies on |
| Spec content hashing | A bespoke deep-hash / structural-diff algorithm | `hashlib.sha256(orjson.dumps(spec, option=orjson.OPT_SORT_KEYS))` | Exactly the same technique already proven at `_curation_cache_key`/`_dataset_gen_cache_key`/WR-05's chunk hash — no new algorithm needed, and reusing it keeps "content hash" meaning one consistent thing across the codebase |
| YAML parsing for the spec file | Any parser other than `yaml.safe_load` | `yaml.safe_load` (already the exclusive convention, T-06-04, `domains/loader.py`) | `yaml.load` (unsafe) permits arbitrary Python object construction via YAML tags — a documented CVE class; this codebase already made the safe choice everywhere else, do not introduce a second YAML-loading path that uses the unsafe function |
| Dataset Project lifecycle validation | A generic state-machine library (e.g. `transitions`, `statemachine`) | A plain `dict[str, set[str]]` adjacency map + one lookup, per Pattern 1 above | 11 states / a fixed transition graph is not complex enough to justify a new dependency; this codebase has zero precedent for a state-machine library and the existing `_TRANSITIONS`-as-dict style keeps the whole thing readable and diffable in code review |
| MCP tool error surfacing for read tools | Custom error-wrapping logic per tool | Let `ValueError`/`LookupError` propagate naturally — `agent/server.py`'s existing `_EXPECTED_ERRORS` tuple already converts them to `isError=True` results | `spec_validate`/`project_list`/`project_show` are all read tools; a "not found" or "invalid spec" condition is exactly what `ValueError`/`LookupError` already model correctly in this codebase — no new exception type needed for the three tools this phase actually ships |

**Key insight:** Every "don't hand-roll" item in this phase is really "don't invent a second version of a mechanism this codebase already has exactly one canonical implementation of." Phase 23's entire job is applying four already-proven patterns (ID generation, content hashing, YAML loading, thin-shim surfaces) to a new entity family — there is no genuinely novel technical problem here.

## Common Pitfalls

### Pitfall 1: `TOOLS` assertion math — 11 -> 14, not "some new number"

**What goes wrong:** D-05 requires exactly 3 new read tools (`project_list`, `project_show`, `spec_validate`). It is easy to lose count mid-implementation (e.g., accidentally also stubbing a 4th tool, or forgetting one) and land on an assertion that doesn't match the actual `len(TOOLS)`.

**Why it happens:** The assertion (`agent/registry.py:375-376`) is a deliberate tripwire (per PITFALLS.md Pitfall 2's explicit framing: "a CI failure there as confirmation the surface was touched, not an annoyance to silence") — but a tripwire only works if the *target* number is right, not just present.

**How to avoid:** Count new `ToolDef` entries added, confirm it is exactly 3, set `assert len(TOOLS) == 14`. Update the module docstring's "11 `ToolDef` entries" line (`agent/registry.py:3`) and the "Order: 4 read tools first, then 7 write tools" comment (`agent/registry.py:243`) to "7 read tools first, then 7 write tools" — the docstring is documentation, not just the assertion; both must be updated together or the docstring becomes stale and misleading (exactly the kind of drift `xfail_strict` culture in this project explicitly guards against elsewhere).

**Warning signs:** `assert len(TOOLS) == 14` present but the module docstring/comment still says 11 or "4 read tools."

### Pitfall 2: `IllegalProjectTransitionError` needs to stay OUT of the MCP surface this phase — but the reason must be documented, not just true by omission

**What goes wrong:** Because D-05 defers `project_transition` as an MCP tool, `IllegalProjectTransitionError` never crosses `agent/server.py`'s `call_tool` boundary in Phase 23. If a future phase adds the mutating tool without re-reading this constraint, it will discover (the hard way, via an unhandled-exception protocol error instead of a clean `isError=True`) that `RuntimeError` subclasses are NOT in `_EXPECTED_ERRORS` (`agent/server.py:33`) and need the same hand-rolled `except`-clause treatment `TrainEvalContaminationError` got (`agent/server.py:115-138`).

**Why it happens:** `_EXPECTED_ERRORS = (ValueError, LookupError)` looks like it should catch "expected domain errors" generically, but it is a hard-coded tuple, not an extensible registry — every new `RuntimeError`-based domain exception needs its own explicit `except` clause added to `agent/server.py`.

**How to avoid:** Add a one-line comment in `pipeline/project.py` next to `IllegalProjectTransitionError`'s definition noting "not caught by agent/server.py's _EXPECTED_ERRORS — if a future MCP tool can raise this, agent/server.py needs a new except clause, mirroring the TrainEvalContaminationError special case." This is exactly the kind of gap this project's own history shows gets silently reintroduced (KL-19's `pipeline.route` import-binding gotcha, `xfail_strict`'s months-long silent violation) if not written down where the next implementer will see it.

**Warning signs:** A later phase's MCP tool for `project transition` ships with no corresponding `except IllegalProjectTransitionError` block in `agent/server.py`.

### Pitfall 3: `Dataset.dataset_project_id` FK must be nullable — existing pre-v2.7 `Dataset` rows have no project

**What goes wrong:** If the new FK column on `Dataset` is added `nullable=False`, every existing `Dataset` row (created before this phase, with no project association) fails the migration outright, or requires an impossible backfill (there is no project to backfill them to — they are legitimately projectless).

**Why it happens:** It's tempting to make a "new required relationship" `NOT NULL` by default when designing the target-state schema in isolation, forgetting the migration runs against a live table with pre-existing rows (same root-cause shape as PITFALLS.md Pitfall 1's `DatasetExample.split` backfill gap, just simpler here because the correct backfill value is unambiguously "NULL, permanently" rather than "some derived value").

**How to avoid:** `dataset_project_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("dataset_projects.id", ondelete="SET NULL"), nullable=True)`. `get_latest_released_dataset_by_name()`'s legacy fallback branch (Pattern 5 above) depends on this nullability — `dataset.dataset_project_id is None` is exactly how it detects "pre-v2.7 legacy dataset."

**Warning signs:** A migration `ALTER TABLE datasets ADD COLUMN dataset_project_id ... NOT NULL` with no default and no backfill UPDATE — this will fail against the existing (per STATE.md) live dev/test data the moment it runs.

### Pitfall 4: Spec-version `created_at`/`author` fields need an explicit, deliberate default for `author` — there is no existing authentication/user-identity concept in this codebase to draw from

**What goes wrong:** SPEC-02 requires each spec version to record "author." This codebase has no user/auth model anywhere (`grep` for `current_user`, session-based identity, or an `Actor`/`User` table returns nothing) — CLI commands run as whatever OS user invoked them, API requests carry no identity today. Inventing a full auth system to satisfy "author" would massively over-scope this phase.

**Why it happens:** "author" reads like it implies an authentication system, but the milestone brief's actual ask (per REQUIREMENTS.md SPEC-02, and D-04's precedent of "who/when" event-log shape already used elsewhere, e.g. `release_approvals`' planned shape in ARCHITECTURE.md) is closer to "an attributable string field," not "a verified identity."

**How to avoid:** Treat `author` as a free-text/string field, sourced from an explicit CLI flag (`--author`) or API request field (required, no default), NOT from any inferred system identity (no `os.getlogin()`, no request header sniffing) — this keeps the field honest about what it actually records (a self-reported string) rather than implying a verification guarantee the system doesn't provide. Document this scoping explicitly since it's a common source of "wait, is this actually authenticated?" confusion later.

**Warning signs:** Code that tries to auto-populate `author` from `os.getlogin()`, an environment variable, or a made-up "system" default — any of these silently misrepresent the field's actual provenance guarantee.

### Pitfall 5: Alembic migration must add the `Dataset` FK column in the SAME migration as the two new tables, and downgrade in strict reverse order

**What goes wrong:** Splitting "create `dataset_projects`/`dataset_specs`" and "add `dataset_project_id` FK to `datasets`" into two separate migrations seems tidy (one migration per concern) but actually violates this project's own established grouped-migration precedent — `0008_dataset_examples.py` added BOTH new `dataset_examples` columns on `Dataset` AND the new `dataset_examples` table in one migration, specifically because they are the same logical change. Splitting them here creates an artificial window where `dataset_projects` exists but nothing references it.

**Why it happens:** Migration-per-concern discipline is usually correct (PITFALLS.md Pitfall 8), but "concern" here is "Dataset Project + Spec landing as one coherent unit" — the FK on `Dataset` is part of that same unit, not a separate later concern (contrast with a genuinely later phase adding a `release_id` FK to `dataset_examples`, which PITFALLS.md Pitfall 8 correctly scopes as its own later migration).

**How to avoid:** One migration, `0012_dataset_project_and_spec.py`: creates `dataset_projects`, creates `dataset_specs`, adds the nullable `dataset_project_id`/`dataset_spec_id` columns to `datasets`. `downgrade()` drops in exact reverse order (drop the new `datasets` columns first, then `dataset_specs`, then `dataset_projects`) — mirroring `0008`'s reverse-order `downgrade()` exactly.

**Warning signs:** Two migration files for this phase instead of one; a `downgrade()` that drops tables before dropping the columns that FK into them (will fail with a live FK-constraint error).

## Code Examples

### Migration skeleton (`0012_dataset_project_and_spec.py`)

```python
# Source: mirrors registry/alembic/versions/0008_dataset_examples.py and 0011_chunk_dedup_ledger.py structure
"""Add dataset_projects and dataset_specs tables (PROJ-01..03, SPEC-01..03).

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-21

Dataset Project is the FK-dependency root for the entire v2.7 milestone (D-02,
ARCHITECTURE.md build-order #1). dataset_specs is insert-only (immutability by
table design, no UPDATE path — SPEC-02); the parent-version link is a
self-referencing nullable FK on dataset_specs.id.

datasets gets two new NULLABLE columns (dataset_project_id, dataset_spec_id) —
NULLABLE because every pre-v2.7 Dataset row has no project (Pitfall 3 above);
get_latest_released_dataset_by_name() relies on this nullability to detect the
legacy-fallback case.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dataset_projects",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("intended_uses", sa.JSON(), nullable=True),
        sa.Column("prohibited_uses", sa.JSON(), nullable=True),
        sa.Column("dataset_type", sa.String(64), nullable=False),
        sa.Column("domain", sa.String(64), nullable=True, index=True),
        sa.Column("owners", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_dataset_projects_name", "dataset_projects", ["name"])

    op.create_table(
        "dataset_specs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("dataset_project_id", sa.String(64), sa.ForeignKey("dataset_projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("parent_spec_id", sa.String(64), sa.ForeignKey("dataset_specs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, index=True),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("author", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_dataset_specs_dataset_project_id", "dataset_specs", ["dataset_project_id"])

    op.add_column("datasets", sa.Column("dataset_project_id", sa.String(64), sa.ForeignKey("dataset_projects.id", ondelete="SET NULL"), nullable=True))
    op.add_column("datasets", sa.Column("dataset_spec_id", sa.String(64), sa.ForeignKey("dataset_specs.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("datasets", "dataset_spec_id")
    op.drop_column("datasets", "dataset_project_id")
    op.drop_index("ix_dataset_specs_dataset_project_id", table_name="dataset_specs")
    op.drop_table("dataset_specs")
    op.drop_constraint("uq_dataset_projects_name", "dataset_projects", type_="unique")
    op.drop_table("dataset_projects")
```

### ID prefix additions (`ids.py`)

```python
# Source: ids.py:32-47, additive only — no change to existing entries
_PREFIX: dict[str, str] = {
    "source": "src",
    "raw_document": "doc",
    "parsed_document": "doc",
    "cleaned_document": "doc",
    "enriched_document": "doc",
    "chunk": "chk",
    "artifact": "art",
    "crawl_job": "job",
    "crawl_state": "cst",
    "bronze_document": "doc",
    "curated_document": "doc",
    "dataset": "dst",
    "dataset_example": "dex",
    "tree_index": "idx",
    "dataset_project": "dpj",   # NEW — ARCHITECTURE.md prefix decision
    "dataset_spec": "dsp",      # NEW — ARCHITECTURE.md prefix decision
}
```

## State of the Art

Not applicable in the external-tooling sense — this phase adopts no new third-party technology. The only "state of the art" question is internal: this phase establishes the CLI/API/MCP surface *convention* every later v2.7 phase (policy, quality contract, curation, release, eval, diff) will replicate. Getting the `project_app`/route/MCP-shim shape right here has outsized leverage — 9 later phases copy it.

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `Dataset.name` (UNIQUE) is the whole identity contract for `export_finetune_dataset` | `get_latest_released_dataset_by_name()` — a named, tested resolution rule that falls back to the old behavior for legacy datasets | This phase | Four existing call sites keep compiling AND keep working correctly; the ambiguity Pitfall 2 (PITFALLS.md) warned about is closed by construction, not by convention |

**Deprecated/outdated:** Nothing existing is deprecated by this phase — `get_dataset_by_name()`/`get_or_create_dataset()`/`update_dataset_export()` all remain in active use, unchanged, for the legacy (non-project) dataset path.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `sha256` (not `xxhash`) is the right hash function for spec content, distinct from the corpus's `xxhash`-based chunk/document dedup hashing | Standard Stack > Alternatives Considered | Low — both are cryptographically/practically fine for this non-adversarial use; if the executor prefers `xxhash` for internal consistency, swapping is a one-line change with no design implications |
| A2 | `HTTP 409 Conflict` is the correct status code for `IllegalProjectTransitionError`, even though this codebase has never used 409 before (all prior domain errors use 422/404) | Architecture Patterns > Pattern 4 | Low-Medium — 409 is semantically correct per HTTP spec (state conflict) and is exactly what D-04 in CONTEXT.md specifies; risk is only that a reviewer unfamiliar with the distinction might expect 422 out of habit — flag explicitly in the plan so it's a deliberate choice, not a surprise in code review |
| A3 | `author` on `dataset_specs` should be a free-text string field (no auth system backing it), sourced from an explicit CLI flag / required API field | Common Pitfalls > Pitfall 4 | Medium — if a later phase (e.g. Release approvals) assumes `author` carries a verified-identity guarantee this phase never provided, that phase's design needs to account for the gap explicitly rather than assuming stronger provenance than exists |
| A4 | The 11-state transition graph's specific edges (e.g., whether `failed` can transition back to `draft` vs. only to `archived`) are Claude's Discretion per CONTEXT.md — the graph shown in Pattern 1's code example is one reasonable encoding, not a locked decision | Architecture Patterns > Pattern 1 | Low — CONTEXT.md explicitly delegates this to the planner/executor; any internally-consistent graph matching the milestone brief's stated linear order (draft → configured → sources_pending → ready → processing → validating → review_required → releasable → released, plus failed/archived branches) satisfies PROJ-02 |
| A5 | Neither `check_train_eval_contamination()` nor any other existing function needs modification for this phase — Phase 23's D-02 fix is scoped entirely to `export_finetune_dataset`'s identity resolution, not to the contamination gate | Summary | Low — confirmed by direct reading of REQUIREMENTS.md (SPLIT-01/02 are Phase 29, not Phase 23) and CONTEXT.md's explicit phase boundary; flagged only because PITFALLS.md discusses both `Dataset` versioning and contamination gate changes in adjacent pitfalls, and it would be easy to conflate them |

**If this table is empty:** N/A — see entries above.

## Open Questions

1. **Should `dataset_projects.status` and `dataset_specs.status` be the same enum, or two independent status vocabularies?**
   - What we know: PROJ-02's 11-state lifecycle clearly belongs to the *project*. SPEC-03 says spec validation "before a spec can move a project to `ready`" — implying spec validity is a gate on the *project's* transition, not necessarily a separate spec-level status field.
   - What's unclear: Whether `dataset_specs` needs its own `status` column at all (e.g., `draft`/`validated`/`superseded`) or whether "latest spec version for a project" plus the project's own status is sufficient, with `get_latest_released_dataset_by_name()`'s "released" resolution driven entirely by `dataset_projects.status == 'released'` rather than a spec-level status.
   - Recommendation: Simplify to ONE status source of truth — `dataset_projects.status` — and have `dataset_specs` carry no independent status field beyond its immutable `created_at`/`parent_spec_id` chain. `get_latest_released_dataset_by_name()` then resolves via "the `Dataset` row whose `dataset_project_id` points at a project with `status='released'`, using `Dataset.created_at DESC` for the documented tiebreak." This avoids two sources of truth needing to stay in sync. Flag as a planner decision — the migration/model code examples above show a `dataset_specs.status` column as a starting point in case the planner decides a spec-level status is genuinely needed (e.g., to distinguish "draft, not yet submitted for validation" from "validated, ready to gate a transition"), but the simpler single-status design should be the default unless a concrete need for spec-level status surfaces during planning.

2. **Exact wording/shape of `klake dataset spec validate`'s CLI subcommand placement — under `project_app` or a separate `dataset_app`?**
   - What we know: ARCHITECTURE.md's CLI section (§4) proposes a `dataset_app` group housing `release`/`diff`/`validate`/`curate-run` subcommands, separate from `project_app`. REQUIREMENTS.md's SPEC-03 literally spells the command as `klake dataset spec validate` (a `dataset` verb, `spec` sub-noun, `validate` action) — a three-level nesting Typer supports via nested sub-Typers (`dataset_app` containing a `spec_app`).
   - What's unclear: Whether Phase 23 should scaffold the full `dataset_app` group now (with only `spec validate` populated, since `release`/`diff`/`curate-run` belong to Phases 27/30/31) or defer `dataset_app`'s creation to whichever phase needs it next, keeping `spec validate` temporarily as a bare `project_app` subcommand or top-level command.
   - Recommendation: Scaffold `dataset_app` now (empty `typer.Typer()` + `app.add_typer(dataset_app, name="dataset")`) with a nested `spec_app` sub-Typer for `dataset spec validate`, since SURFACE-01 explicitly says new CLI groups should exist for later phases to extend — creating the shell now avoids Phase 27+ needing to retrofit a new top-level group into an already-shipped CLI surface.

## Environment Availability

No new external dependency, service, or tool is introduced by this phase — it extends the existing PostgreSQL registry (already required by every phase since v1.0) with two new tables via the existing Alembic migration mechanism. No new Docker Compose service, no new CLI binary, no new SDK.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL | `dataset_projects`/`dataset_specs` tables | ✓ (already required by every existing phase) | 16+ (per CLAUDE.md stack table) | — |
| Alembic | `0012_dataset_project_and_spec.py` migration | ✓ [VERIFIED: uv.lock, alembic 1.18.5] | 1.18.5 | — |
| PyYAML | Spec YAML authoring/parsing | ✓ [VERIFIED: uv.lock, pyyaml 6.0.3] | 6.0.3 | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (per `pyproject.toml [tool.pytest.ini_options]`) |
| Config file | `pyproject.toml:121-129` — `testpaths = ["tests"]`, `xfail_strict = true`, `asyncio_mode = "auto"` |
| Quick run command | `uv run pytest tests/unit/test_project.py -x` (new file, once created) |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROJ-01 | `create_project()` persists all specified fields, `klake project new` creates a `draft`-state row | unit | `pytest tests/unit/test_project.py::test_create_project_draft_state -x` | ❌ Wave 0 (`tests/unit/test_project.py` new) |
| PROJ-02 | Illegal transition raises `IllegalProjectTransitionError` naming from/to/legal-next-states | unit | `pytest tests/unit/test_project.py::test_illegal_transition_rejected -x` | ❌ Wave 0 |
| PROJ-02 | Legal transition succeeds and updates `status` | unit | `pytest tests/unit/test_project.py::test_legal_transition_succeeds -x` | ❌ Wave 0 |
| PROJ-03 | `klake project new/list/show/transition` CLI round-trip | integration | `pytest tests/integration/test_project_cli.py -x` | ❌ Wave 0 |
| PROJ-03 | API `/projects`, `/projects/{id}`, `/projects/{id}/transition` routes | integration | `pytest tests/integration/test_api_project.py -x` | ❌ Wave 0 |
| SPEC-01 | Spec YAML with all fields including nullable `quality_contract_ref`/`policy_ref` parses and validates structurally | unit | `pytest tests/unit/test_project.py::test_spec_all_fields_structural_validate -x` | ❌ Wave 0 |
| SPEC-02 | Editing a spec produces a new version with distinct content hash, parent-version link intact, previous version unmodified/retrievable | unit | `pytest tests/unit/test_project.py::test_spec_version_immutable_chain -x` | ❌ Wave 0 |
| SPEC-02 | Re-saving byte-identical (but re-formatted) YAML does NOT bump the version (canonical-hash stability) | unit | `pytest tests/unit/test_project.py::test_spec_hash_stable_across_yaml_formatting -x` | ❌ Wave 0 |
| SPEC-03 | `klake dataset spec validate` fails with specific reason for nonexistent source reference | unit | `pytest tests/unit/test_project.py::test_spec_validate_unknown_source_fails -x` | ❌ Wave 0 |
| SPEC-03 | `klake dataset spec validate` passes when all references resolve | unit | `pytest tests/unit/test_project.py::test_spec_validate_all_refs_resolve -x` | ❌ Wave 0 |
| — (D-02/Pitfall 2) | `export_finetune_dataset("name")` (no version) resolves to the 'released' spec version's Dataset against a project with two spec versions | integration | `pytest tests/integration/test_export_project_resolution.py::test_latest_released_resolution -x` | ❌ Wave 0 |
| — (D-02) | Legacy (pre-v2.7, no project FK) dataset export behavior is byte-identical to pre-phase behavior | regression | `pytest tests/unit/test_export.py -k legacy -x` | ✓ extend existing `tests/unit/test_export.py` |
| SURFACE-01 | Full existing CLI test suite passes unchanged | regression | `pytest tests/ -k "not test_project"` | ✓ existing suite |
| SURFACE-02 | `docs/openapi.json` regenerated and `test_openapi_export.py` passes after new routes added | regression | `pytest tests/unit/test_openapi_export.py -x` | ✓ existing |
| SURFACE-03 | `TOOLS` count assertion == 14, no duplicate names, full existing MCP test suite passes unchanged | regression + unit | `pytest tests/integration/test_mcp_http.py -x` + import-time assertion | ✓ existing (`tests/integration/test_mcp_http.py`), extend for 3 new tools |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/unit/test_project.py -x` (fast, no service dependencies for pure pipeline-logic tests)
- **Per wave merge:** `uv run pytest tests/unit tests/integration -x`
- **Phase gate:** Full suite green (`uv run pytest`) before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_project.py` — covers PROJ-01/02, SPEC-01/02/03 (pure pipeline-logic tests, no live Postgres needed if the project follows `test_curate.py`'s session-mocking convention — check that file's fixture pattern before writing new tests)
- [ ] `tests/integration/test_project_cli.py` — covers PROJ-03 CLI round-trip
- [ ] `tests/integration/test_api_project.py` — covers PROJ-03 API routes, mirrors `tests/integration/test_api_new_endpoints.py`'s existing shape
- [ ] `tests/integration/test_export_project_resolution.py` — covers the D-02/Success-Criterion-5 resolution rule against all 4 call sites (or fold into `test_dedup_cli_dagster_parity.py`'s existing CLI/Dagster-parity pattern if that file's fixture setup is reusable)
- [ ] No new framework/config install needed — pytest + existing fixtures cover this phase entirely

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | This phase introduces no new authentication surface — `author` on spec versions is a self-reported string field (Pitfall 4), not an authenticated identity; no change to existing auth posture |
| V3 Session Management | No | No new session concept |
| V4 Access Control | No | No new authorization boundary — Dataset Project mutation is unauthenticated in this phase exactly as every other existing mutating CLI/API/pipeline call is today (consistent with the codebase's current single-team, no-RBAC posture per REQUIREMENTS.md's explicit "Enterprise RBAC... out of scope") |
| V5 Input Validation | Yes | `yaml.safe_load` (never `yaml.load`) for spec parsing (T-06-04 precedent); Pydantic field-level validation (`min_length`, `max_length`, `pattern`) for all new `api/schemas.py` models, matching `DomainLoadRequest`'s path-traversal-blocking pattern (`api/schemas.py:872-878`) and `ExportRequest`'s bounded-pattern convention (`api/schemas.py:251-270`) |
| V6 Cryptography | Yes (light touch) | `hashlib.sha256` for spec content hashing — not a secret/credential hash, just a content-addressable integrity hash; no key management involved. Never hand-roll a hash algorithm; stdlib `hashlib` only, matching the existing `_curation_cache_key` precedent |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| YAML deserialization RCE (arbitrary Python object construction via `!!python/object` tags) | Tampering / Elevation of Privilege | `yaml.safe_load` exclusively — never `yaml.load` or `yaml.unsafe_load`. Already the established convention (T-06-04); a new spec-loading code path must not introduce a second, unsafe loader |
| Mass-assignment / over-posting via loosely-typed spec JSON column | Tampering | Field-by-field allow-list validation of the parsed spec against a Pydantic schema BEFORE it is stored as the `dataset_specs.spec` JSON column — never `session.add(DatasetSpec(spec=raw_parsed_dict))` without schema validation first, mirroring `_RAG_CORPUS_FIELDS`' explicit-allow-list precedent (`pipeline/export.py:74-84`) for why implicit/wildcard field acceptance is treated as a real risk in this codebase |
| SQL injection via referential-integrity lookups (source/quality-contract/policy existence checks) | Tampering | ORM `select()` statements only (T-01-03 convention, used throughout `registry/repo.py`) — never raw SQL string interpolation for the new `validate_spec()` reference-existence checks |
| Free-text `author` field impersonation (since it is self-reported, not authenticated) | Spoofing | Not mitigated at the technical layer this phase — document explicitly (Pitfall 4) that `author` is an unverified, self-reported attribution field, consistent with the milestone's stated non-goal of "Enterprise RBAC." A later phase introducing real authentication would need to revisit this field's provenance guarantee |
| Illegal-transition error responses leaking internal state-machine details | Information Disclosure | Low risk — `IllegalProjectTransitionError`'s `legal_next_states` list is intentionally informative (D-04 explicitly wants a "clear, specific error"), and the full transition graph is not a secret (it is fixed, published business logic, not sensitive data) |

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `src/knowledge_lake/registry/models.py` (full file, 655 lines) — `Dataset`/`DatasetExample` exact column definitions, `UNIQUE(name)` constraint
- Direct code inspection: `src/knowledge_lake/registry/repo.py:1288-1520` — `create_dataset`, `get_dataset_by_name`, `get_or_create_dataset`, `update_dataset_export`, `create_dataset_example`, `list_dataset_examples`
- Direct code inspection: `src/knowledge_lake/pipeline/export.py:1-120,540-660` — `TrainEvalContaminationError`, `_make_storage`, `export_finetune_dataset` full body
- Direct code inspection: `src/knowledge_lake/cli/app.py:1200-1300,1555-1636` — `cmd_export`, `domain_app` full registration + `cmd_domain_new`
- Direct code inspection: `src/knowledge_lake/api/app.py:1190-1260` — `export_endpoint` full body, D-02 docstring convention
- Direct code inspection: `src/knowledge_lake/agent/registry.py` (full file, 396 lines) — `ToolDef`, `TOOLS` (all 11 entries), `_export_dispatch`, `registered_tools`
- Direct code inspection: `src/knowledge_lake/agent/server.py` (full file, 145 lines) — `_EXPECTED_ERRORS`, `call_tool`'s exception-handling flow, the special-cased `TrainEvalContaminationError` lazy-import pattern
- Direct code inspection: `src/knowledge_lake/dagster_defs/assets.py:982-1048` — `ExportFinetuneDatasetConfig`, `export_finetune_dataset` asset
- Direct code inspection: `src/knowledge_lake/ids.py` (full file) — `_PREFIX` dict, `new_id()`
- Direct code inspection: `src/knowledge_lake/registry/alembic/versions/0008_dataset_examples.py`, `0011_chunk_dedup_ledger.py` (full files) — migration shape precedent
- Direct code inspection: `src/knowledge_lake/pipeline/curate.py:1-91` — module docstring, `_build_filters`, `_curation_cache_key`
- Direct code inspection: `src/knowledge_lake/pipeline/datasets.py:139-150,254-260,403-410` — `_dataset_gen_cache_key`, `generate_qa_example`/`generate_instruction_example` signatures
- Direct code inspection: `src/knowledge_lake/config/settings.py:376-453,614-703` — `DatasetSettings`/`ExportSettings`/`DomainSettings` shape, `Settings` nested-config convention
- Direct code inspection: `src/knowledge_lake/api/schemas.py:244-282,690-734,864-890` — `ExportRequest`/`ExportResponse`, `GenerateDatasetRequest`/`Response`, `DomainLoadRequest`/`Response` naming conventions
- Direct code inspection: `src/knowledge_lake/domains/loader.py:12,47,75-98` — `yaml.safe_load` exclusive-use convention (T-06-04)
- Direct code inspection: `pyproject.toml:121-136` — pytest/ruff config
- Direct code inspection: `uv.lock` — verified pinned versions (alembic 1.18.5, pydantic 2.13.4, pyyaml 6.0.3)
- `.planning/research/PITFALLS.md` (Pitfall 2, lines 96-153) — the exact identity-break mechanics this phase resolves
- `.planning/research/ARCHITECTURE.md` (build order, table decisions, ID prefixes, CLI/API/MCP surface reuse sections)
- `.planning/phases/23-dataset-project-specification-foundation/23-CONTEXT.md` — D-01 through D-05 locked decisions

### Secondary (MEDIUM confidence)
- None — this phase required no external documentation lookups; all findings are grounded in direct repository inspection.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies, all versions confirmed against `uv.lock`
- Architecture: HIGH — every pattern cited against an exact file:line precedent already in the codebase
- Pitfalls: HIGH — all five pitfalls are either directly observed in the current code (`_EXPECTED_ERRORS` tuple, `UNIQUE(name)` constraint, migration precedent) or a direct restatement of CONTEXT.md/PITFALLS.md's own already-verified findings

**Research date:** 2026-07-21
**Valid until:** 30 days (stable internal codebase, no fast-moving external dependency in scope for this phase)
