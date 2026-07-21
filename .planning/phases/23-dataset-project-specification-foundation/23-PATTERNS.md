# Phase 23: Dataset Project + Specification Foundation - Pattern Map

**Mapped:** 2026-07-21
**Files analyzed:** 10 new/modified files
**Analogs found:** 10 / 10 (all have a direct, cited precedent — this phase's own RESEARCH.md already names exact analogs; this file makes the excerpts concrete for the planner)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `src/knowledge_lake/pipeline/project.py` (new) | service (pipeline module) | CRUD + state-machine transitions | `src/knowledge_lake/pipeline/curate.py` | exact (module shape) + `pipeline/export.py` (exception + settings pattern) |
| `src/knowledge_lake/registry/models.py` (modified — `+DatasetProject`, `+DatasetSpec`, `+FK` on `Dataset`) | model | CRUD | `Dataset`/`DatasetExample` classes (same file, lines 566-601) | exact |
| `src/knowledge_lake/registry/repo.py` (modified — `+create_project`, `+get_project_by_id/name`, `+list_projects`, `+create_spec_version`, `+get_latest_spec_version`, `+get_latest_released_dataset_by_name`) | service (data-access layer) | CRUD | `get_dataset_by_name`/`get_or_create_dataset`/`create_dataset` (same file, lines ~1288-1400) | exact |
| `src/knowledge_lake/registry/alembic/versions/0012_dataset_project_and_spec.py` (new) | migration | batch (schema DDL) | `0008_dataset_examples.py`, `0011_chunk_dedup_ledger.py` | exact |
| `src/knowledge_lake/cli/app.py` (modified — `+project_app`, `+dataset_app`/`spec_app`, `+cmd_project_new/list/show/transition`, `+cmd_dataset_spec_validate`) | controller (CLI) | request-response | `domain_app` + `cmd_domain_new` (same file, lines 1569-1636) | exact |
| `src/knowledge_lake/api/app.py` (modified — `+/projects`, `+/projects/{id}`, `+/projects/{id}/transition`, `+/projects/{id}/specs`, `+/specs/{id}/validate`) | controller (API route) | request-response | `export_endpoint` (same file, lines 1192-1260) | exact |
| `src/knowledge_lake/api/schemas.py` (modified — `+ProjectCreate/Out/TransitionRequest`, `+SpecVersionCreate/Out/ValidateResponse`) | model (Pydantic schema) | request-response | `ExportRequest`/`ExportResponse` (same file, lines 244-282) | exact |
| `src/knowledge_lake/agent/registry.py` (modified — `+3` read `ToolDef`s: `project_list`, `project_show`, `spec_validate`; `TOOLS` assert `11 -> 14`) | controller (MCP tool registry) | request-response | existing read `ToolDef` entries (`search`/`list_sources`/`lineage`/`stats`) + `_lineage_handler` shim (lines ~230-246) | exact |
| `src/knowledge_lake/ids.py` (modified — `+"dataset_project": "dpj"`, `+"dataset_spec": "dsp"`) | utility (config/constants) | — | existing `_PREFIX` dict (lines 32-46) | exact |
| `src/knowledge_lake/pipeline/export.py` (modified — internal `get_dataset_by_name` -> `get_latest_released_dataset_by_name` swap only, D-02) | service | CRUD (read-path identity resolution) | same file's `export_finetune_dataset()` body + `TrainEvalContaminationError` (lines 90-98) | exact (self-analog — this is a targeted internal edit, not a new file) |

## Pattern Assignments

### `src/knowledge_lake/pipeline/project.py` (service, CRUD + state-machine)

**Analog:** `src/knowledge_lake/pipeline/curate.py` (module shape) + `src/knowledge_lake/pipeline/export.py` (exception convention)

**Module docstring + imports pattern** (`pipeline/curate.py:1-46`):
```python
"""Curate stage: cleaned_document artifact -> curated_document artifact (CURATE-01..03).
...
Design decisions this module implements:
  D-01: curated_document always parents off the cleaned_document artifact, ...
"""
from __future__ import annotations

import hashlib

import structlog
from datasketch import MinHashLSH
from sqlalchemy.exc import IntegrityError

from knowledge_lake.config.settings import CurateSettings, Settings, get_settings
from knowledge_lake.pipeline.clean import compute_minhash
from knowledge_lake.pipeline.utils import uri_to_key as _uri_to_key
from knowledge_lake.quality.scorer import compute_composite_quality_score
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.storage.s3 import StorageBackend

log = structlog.get_logger(__name__)
```
**Note:** all pipeline imports are deferred to function scope in the actual DB/settings-touching helpers — `curate.py`'s module-level imports shown above are the *safe, cheap* ones (stdlib, structlog, sqlalchemy exceptions); RESEARCH.md's own `pipeline/project.py` skeleton (RESEARCH.md lines 172-234) already follows this exactly — copy that skeleton verbatim as the starting structure, it is not a re-derivation, it is the analog already written out.

**Exception pattern** (`pipeline/export.py:90-98`):
```python
class TrainEvalContaminationError(RuntimeError):
    """Raised when check_train_eval_contamination() finds undocumented overlap.

    05-AI-SPEC Section 7: "hard block, not an alert — export command fails closed."
    Add the offending cleaned_document artifact IDs to
    ExportSettings.contamination_override_artifact_ids only after explicit operator
    review of the accepted overlap.
    """
```
Use this exact shape for `IllegalProjectTransitionError(RuntimeError)` (D-04) — a plain docstring-only `RuntimeError` subclass, with the from/to/legal-next fields added in `__init__` per RESEARCH.md Pattern 1 (lines 203-220). Do **not** subclass `ValueError` (see Shared Patterns > Error Handling below).

**Core state-machine + settings pattern:** copy RESEARCH.md's Pattern 1 code block verbatim (`_TRANSITIONS` dict, `transition_project()`, `get_session()` context manager, `settings: Settings | None = None` kwarg) — it is already written against this exact analog and does not need re-derivation.

---

### `src/knowledge_lake/registry/models.py` (model, CRUD)

**Analog:** `Dataset` class, same file, lines 566-601

**Core pattern** (lines 566-598):
```python
class Dataset(Base):
    """Curated dataset record — extended in Phase 5 with real columns (DATA-01..03).
    ...
    """

    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("name", name="uq_datasets_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dataset_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ...
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
```
`DatasetProject`/`DatasetSpec` follow this exact `Mapped[...]`/`mapped_column` style with `String(64)` primary keys (prefixed IDs via `new_id()`), `UniqueConstraint` for `dataset_projects.name`, and `DateTime(timezone=True)` timestamp columns with `server_default=func.now()`. The new nullable FK columns on `Dataset` (`dataset_project_id`, `dataset_spec_id`) go directly below the existing `storage_uri` column in this same class.

---

### `src/knowledge_lake/registry/repo.py` (service, CRUD)

**Analog:** `get_dataset_by_name`/`get_or_create_dataset`/`create_dataset` (lines ~1288-1400)

**Core pattern** (lines 1340-1347):
```python
def get_dataset_by_name(session: Session, name: str) -> Dataset | None:
    """Return the Dataset matching ``name``, or None.

    Uses the uq_datasets_name unique index for O(1) lookup.
    No raw SQL — ORM select (T-01-03).
    """
    stmt = select(Dataset).where(Dataset.name == name).limit(1)
    return session.execute(stmt).scalar_one_or_none()
```
`get_project_by_id`, `get_project_by_name`, `list_projects`, `get_latest_spec_version` all follow this `select(...).where(...)` ORM pattern — never raw SQL (V5/T-01-03 convention, cited in RESEARCH.md's Security Domain section).

**`get_latest_released_dataset_by_name()` — the D-02 resolution function.** Copy RESEARCH.md Pattern 5 verbatim (lines 346-369) — it is written directly against this analog:
```python
def get_latest_released_dataset_by_name(session: Session, name: str) -> Dataset | None:
    """D-02 resolution rule for export_finetune_dataset(name) (no version arg). ..."""
    dataset = get_dataset_by_name(session, name)
    if dataset is None or dataset.dataset_project_id is None:
        return dataset  # legacy path, byte-identical to today's behavior
    stmt = (
        select(Dataset)
        .join(DatasetSpec, DatasetSpec.id == Dataset.dataset_spec_id)
        .where(
            Dataset.dataset_project_id == dataset.dataset_project_id,
            DatasetSpec.status == "released",
        )
        .order_by(Dataset.created_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()
```
This function sits **alongside**, never replaces, `get_dataset_by_name()` — do not modify the existing function.

---

### `src/knowledge_lake/registry/alembic/versions/0012_dataset_project_and_spec.py` (migration, batch DDL)

**Analog:** `0008_dataset_examples.py`, `0011_chunk_dedup_ledger.py` (grouped-migration shape — new table(s) + FK columns on an existing table, in one file)

RESEARCH.md already contains the full skeleton for this file (lines 458-532) — copy it verbatim as the starting point: revision header, `upgrade()` creating `dataset_projects` then `dataset_specs` then adding the two nullable FK columns to `datasets`, `downgrade()` dropping in exact reverse order. Key constraint from Pitfall 3/5 (RESEARCH.md lines 424-452): the new `datasets.dataset_project_id`/`dataset_spec_id` columns **must be nullable**, and this must be the same migration file as the two new tables (not split).

---

### `src/knowledge_lake/cli/app.py` (controller, request-response)

**Analog:** `domain_app` sub-Typer group + `cmd_domain_new`, lines 1569-1636

**Registration pattern** (lines 1569-1573):
```python
domain_app = typer.Typer(
    name="domain",
    help="Author and manage domain packs.",
    add_completion=False,
)
app.add_typer(domain_app, name="domain")
```
`project_app` (and `dataset_app` per RESEARCH.md's Open Question 2 recommendation — scaffold now, populate with `spec validate` under a nested `spec_app`) copy this exactly, swapping name/help text.

**Command pattern with error handling** (lines 1583-1600, `cmd_domain_new`):
```python
@domain_app.command(name="new")
def cmd_domain_new(
    name: str = typer.Argument(..., help="Domain pack name — must match " f"{_DOMAIN_NAME_HELP_PATTERN}."),
    root: str = typer.Option("domains", "--root", "-r", help="..."),
    force: bool = typer.Option(False, "--force", "-f", help="..."),
) -> None:
    from knowledge_lake.domains.scaffold import scaffold_domain

    try:
        result = scaffold_domain(name, root=root, force=force)
    except (ValueError, FileExistsError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Created domain pack '{name}' at {result['path']}/")
```
Note the **deferred import inside the command function** (`from knowledge_lake.domains.scaffold import scaffold_domain`) — every new `cmd_project_*`/`cmd_dataset_spec_validate` command must import from `pipeline/project.py` the same way, never at module top.

**Rich-markup escaping gotcha (KL-13)** (lines 1578-1582): if `project new --name` gets a validation-pattern help string, escape literal `[` characters (`.replace("[", "\\[")`) exactly as `_DOMAIN_NAME_HELP_PATTERN` does, or Typer's Rich rendering silently strips the character class from `--help` output.

**Illegal-transition CLI error handling:** RESEARCH.md Pattern 3 (lines 290-306) already shows `cmd_project_transition` catching `IllegalProjectTransitionError` before the generic `ValueError` — copy that ordering (specific exception first, generic fallback second), matching this file's existing `except (ValueError, FileExistsError)` convention of catching the more specific type when one exists.

---

### `src/knowledge_lake/api/app.py` (controller, request-response)

**Analog:** `export_endpoint`, lines 1192-1260

**Core request-response + typed-error pattern** (lines 1192-1246):
```python
@app.post(
    "/exports",
    response_model=ExportResponse,
    tags=["export"],
    summary="Export the corpus or a dataset to the gold zone (EXPORT-01/02/03)",
    status_code=200,
)
def export_endpoint(body: ExportRequest) -> ExportResponse:
    """... D-02 compliance: Calls the same pipeline.export functions as the CLI export command — no behavior re-implemented."""
    from knowledge_lake.pipeline.export import (
        TrainEvalContaminationError,
        export_finetune_dataset,
        export_pretrain_corpus,
        export_rag_corpus,
    )

    if body.kind == "finetune" and not body.dataset_name:
        raise HTTPException(status_code=422, detail="dataset_name is required for kind='finetune'.")

    logger.info("api.export", kind=body.kind, dataset_name=body.dataset_name, domain=body.domain)

    try:
        if body.kind == "rag-corpus":
            result = export_rag_corpus(domain=body.domain)
        ...
    except TrainEvalContaminationError as exc:
        logger.warning("api.export.contamination", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        logger.warning("api.export.error", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info("api.export.complete", kind=body.kind, dataset_id=result.get("dataset_id"), row_count=result.get("row_count"))
    return ExportResponse(...)
```
New `/projects`, `/projects/{id}`, `/projects/{id}/specs`, `/specs/{id}/validate` routes follow this exact shape: deferred import from `pipeline/project.py` inside the route function, `logger.info` call before and after, typed-exception-first `except` ordering, no business logic in the handler (SURFACE-02).

**409 for illegal transitions — first use of 409 in this codebase.** RESEARCH.md Pattern 4 (lines 316-337) gives the exact route body:
```python
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
Flag this in the plan as a **deliberate new status code**, not copied from an existing route (every prior error path in this file uses 422 or 404).

---

### `src/knowledge_lake/api/schemas.py` (model, request-response)

**Analog:** `ExportRequest`/`ExportResponse`, lines 244-282

**Core bounded-field pattern** (lines 244-270):
```python
class ExportRequest(BaseModel):
    """Request body for POST /exports.

    Bounded to the three valid export kinds via Pydantic pattern validation
    (T-05-09: no free-form string ever reaches the gold-zone S3 key construction).
    """

    kind: str = Field(
        ...,
        pattern=r"^(rag-corpus|pretrain|finetune)$",
        description="Export kind: ...",
    )
    dataset_name: str | None = Field(default=None, max_length=255, description="...")
    domain: str | None = Field(default=None, min_length=1, max_length=100, description="...")
```
`ProjectCreate`, `ProjectTransitionRequest` (`to_state` should be `pattern`-bounded to the 11 known state names, mirroring `kind`'s bounded pattern), `SpecVersionCreate` all follow this `Field(..., pattern=..., max_length=..., description=...)` allow-list-first convention — matches the Mass-assignment mitigation RESEARCH.md's Security Domain section calls out explicitly (never accept an unvalidated free-form dict into `dataset_specs.spec`).

---

### `src/knowledge_lake/agent/registry.py` (controller, MCP)

**Analog:** existing read `ToolDef` entries + `_lineage_handler` thin-shim pattern (lines ~230-246, 375-393)

**Thin-shim handler pattern** (lines 230-234):
```python
def _lineage_handler(artifact_id: str) -> dict:
    """Thin shim: maps LineageInput.artifact_id to resolve_ancestry()."""
    nodes = resolve_ancestry(artifact_id)
    return {"artifact_id": artifact_id, "nodes": nodes}
```
`project_list`/`project_show`/`spec_validate` handlers follow this exact one-line-body shim shape — call straight into `pipeline/project.py`, return a dict.

**TOOLS list + assertion** (lines 375-376):
```python
assert len(TOOLS) == 11, f"TOOLS must have exactly 11 entries, got {len(TOOLS)}"
assert len({t.name for t in TOOLS}) == 11, "TOOLS has duplicate tool names"
```
Both numbers become 14. Also update the module docstring's "11 Knowledge Lake MCP tools" line (line 3) and the "Order: 4 read tools first, then 7 write tools" comment (near the `TOOLS` list) to "7 read tools first, then 7 write tools" — RESEARCH.md's Pitfall 1 flags this exact drift risk.

**MCP error boundary — do NOT add IllegalProjectTransitionError handling this phase.** `agent/server.py:33` (`_EXPECTED_ERRORS = (ValueError, LookupError)`) does not catch `RuntimeError` subclasses automatically — `TrainEvalContaminationError` needed its own hand-written `except` clause (`agent/server.py:115-138`, shown in Shared Patterns below). Since Phase 23 ships **read-only** MCP tools only (D-05), none of `project_list`/`project_show`/`spec_validate`'s handlers can raise `IllegalProjectTransitionError` — only `ValueError`/`LookupError` need to propagate naturally (already handled by the existing `_EXPECTED_ERRORS` tuple, no `agent/server.py` change needed this phase).

---

### `src/knowledge_lake/ids.py` (utility, config)

**Analog:** same file's `_PREFIX` dict, lines 32-46

```python
_PREFIX: dict[str, str] = {
    "source": "src",
    ...
    "dataset": "dst",
    "dataset_example": "dex",
    "tree_index": "idx",
}
```
Add exactly two entries: `"dataset_project": "dpj"`, `"dataset_spec": "dsp"` — additive only, no reordering of existing entries.

---

### `src/knowledge_lake/pipeline/export.py` (service — targeted internal edit only)

**Analog:** the file's own `export_finetune_dataset()` body (D-02 target)

Per RESEARCH.md Pattern 5, this is the **only** internal change needed for D-02 — the four call sites (`cli/app.py:1280`, `api/app.py:1242`, `agent/registry.py:130`, `dagster_defs/assets.py:1034`) stay byte-identical:
```python
def export_finetune_dataset(dataset_name: str, *, domain=None, settings=None) -> dict:
    ...
    with get_session() as session:
        dataset = registry_repo.get_latest_released_dataset_by_name(session, dataset_name)  # was get_dataset_by_name
        if dataset is None:
            raise ValueError(f"Dataset not found: {dataset_name!r}")
        ...
```

## Shared Patterns

### Typed domain exceptions over generic `ValueError`
**Source:** `src/knowledge_lake/pipeline/export.py:90-98` (`TrainEvalContaminationError(RuntimeError)`)
**Apply to:** `pipeline/project.py`'s `IllegalProjectTransitionError` (D-04) — a `RuntimeError` subclass, not `ValueError`, so callers must explicitly catch it rather than it silently blending into generic input-validation handling.
```python
class TrainEvalContaminationError(RuntimeError):
    """Raised when check_train_eval_contamination() finds undocumented overlap.
    ...
    """
```

### MCP exception boundary — RuntimeError subclasses need hand-rolled except clauses
**Source:** `src/knowledge_lake/agent/server.py:33` (`_EXPECTED_ERRORS`) + lines 115-138 (special-cased `TrainEvalContaminationError` handling)
```python
_EXPECTED_ERRORS = (ValueError, LookupError)
...
except Exception:
    try:
        from knowledge_lake.pipeline.export import TrainEvalContaminationError
    except ImportError:
        TrainEvalContaminationError = None
    ...
    if TrainEvalContaminationError is not None and isinstance(exc, TrainEvalContaminationError):
        return types.CallToolResult(content=[types.TextContent(type="text", text=str(exc))], isError=True)
    raise
```
**Apply to:** nothing in Phase 23 itself (read-only MCP tools this phase never raise `IllegalProjectTransitionError`) — but add a one-line comment next to `IllegalProjectTransitionError`'s definition in `pipeline/project.py` noting this gap explicitly for whichever future phase adds a mutating `project_transition` MCP tool (RESEARCH.md Pitfall 2).

### CLI sub-Typer group registration
**Source:** `src/knowledge_lake/cli/app.py:1569-1573` (`domain_app`)
**Apply to:** `project_app`, `dataset_app` (with nested `spec_app`)
```python
domain_app = typer.Typer(name="domain", help="Author and manage domain packs.", add_completion=False)
app.add_typer(domain_app, name="domain")
```

### ORM-only data access (no raw SQL)
**Source:** `src/knowledge_lake/registry/repo.py:1340-1347` (`get_dataset_by_name`)
**Apply to:** all new `registry/repo.py` functions (`get_project_by_id/name`, `list_projects`, `create_spec_version`, `get_latest_spec_version`, `get_latest_released_dataset_by_name`, and `validate_spec()`'s referential-integrity lookups against `sources`)
```python
stmt = select(Dataset).where(Dataset.name == name).limit(1)
return session.execute(stmt).scalar_one_or_none()
```

### `yaml.safe_load` exclusive use for spec parsing
**Source:** `src/knowledge_lake/domains/loader.py:12,47,75-98` (not read in full this pass — RESEARCH.md T-06-04 already cites exact line numbers; convention confirmed via CONTEXT.md D-03 and RESEARCH.md's Security Domain section)
**Apply to:** the YAML-authoring path in `pipeline/project.py` / `cli/app.py`'s `klake dataset spec` commands — `yaml.safe_load` only, never `yaml.load`/`yaml.unsafe_load`.

### Canonical-JSON content hash
**Source:** `_curation_cache_key` (`pipeline/curate.py:80-91`, not fully excerpted this pass — RESEARCH.md Pattern 2, lines 236-255, already gives the concrete `_spec_content_hash()` implementation copied from this convention)
**Apply to:** `pipeline/project.py::_spec_content_hash()` — `hashlib.sha256(orjson.dumps(parsed_spec, option=orjson.OPT_SORT_KEYS)).hexdigest()`.

## No Analog Found

None — RESEARCH.md's own file-by-file mapping already establishes a direct precedent for every file in scope; this phase is explicitly described in RESEARCH.md as "applying four already-proven patterns... to a new entity family — there is no genuinely novel technical problem here."

## Metadata

**Analog search scope:** `src/knowledge_lake/{pipeline,registry,cli,api,agent,ids.py}` — directly targeted via CONTEXT.md/RESEARCH.md's own file:line citations rather than a blind Glob/Grep sweep, since RESEARCH.md already performed exhaustive direct-code-inspection analog discovery for this phase (see RESEARCH.md's Sources section, 20 direct-inspection citations).
**Files read this pass:** `pipeline/curate.py` (1-46), `pipeline/export.py` (80-98, 1192-1260 via api/app.py), `cli/app.py` (1555-1636), `api/app.py` (1180-1260), `registry/models.py` (560-601), `registry/repo.py` (1330-1400), `agent/registry.py` (1-40, 230-260, 360-396), `agent/server.py` (1-40, 95-145), `api/schemas.py` (240-282), `ids.py` (25-55)
**Pattern extraction date:** 2026-07-21
</content>
