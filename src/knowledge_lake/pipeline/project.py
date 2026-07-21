"""Dataset Project lifecycle: create/get/list/transition (PROJ-01, PROJ-02).

A direct structural mirror of pipeline/curate.py — function-shaped (not
class-shaped), deferred imports at function scope where this codebase's
convention calls for them, Settings-driven configuration via a
``settings: Settings | None = None`` kwarg, and get_session() context-manager
usage for every DB interaction.

Design decisions this module implements:
  D-04 (CONTEXT.md): transition_project() enforces the 11-state lifecycle via
        a guarded _TRANSITIONS adjacency map — illegal edges raise
        IllegalProjectTransitionError (a RuntimeError subclass, never a
        ValueError) rather than silently mutating status.
  PROJ-01: create_project()/get_project()/list_projects() store the
        declarative intended_uses/prohibited_uses fields with NO enforcement
        gate in this phase — enforcement arrives via Phase 25's Usage Policy
        Engine. get_latest_released_dataset_by_name() (D-02's fix for
        export_finetune_dataset's identity ambiguity) is implemented in
        Plan 23-04, not here.
"""

from __future__ import annotations

import hashlib

import orjson
import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import IntegrityError

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session

log = structlog.get_logger(__name__)


_SCHEMA_VERSION = "1.0"
"""DatasetSpecFields schema version tag (SPEC-01/02).

Bumped only on a genuinely breaking DatasetSpecFields shape change —
additive fields like the future Phase 25/26 referential tightening (D-01)
do NOT require a bump.
"""


class DatasetSpecFields(BaseModel):
    """Allow-list schema for a Dataset Specification's field set (SPEC-01).

    Mirrors domains/models.py's SourceEntry/DomainManifest exact pattern:
    ``model_config = ConfigDict(extra="forbid")`` — an unrecognized key
    raises a Pydantic ValidationError (mass-assignment mitigation, T-23-07).
    A fresh, self-contained model — pipeline modules never import from
    ``knowledge_lake.api.schemas``.
    """

    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(max_length=4000)
    """Free-text statement of the dataset's purpose (SPEC-01)."""

    dataset_type: str = Field(max_length=64)
    """Kind of dataset this spec produces (SPEC-01)."""

    domain: str = Field(max_length=100)
    """Domain pack name this spec scopes to (SPEC-01)."""

    included_sources: list[str] = []
    """Source IDs (src_<uuidv7>) this spec includes. Existence-checked by
    validate_spec() (SPEC-03)."""

    excluded_sources: list[str] = []
    """Source IDs (src_<uuidv7>) this spec excludes. Existence-checked by
    validate_spec() (SPEC-03)."""

    allowed_license_categories: list[str] = []
    """License categories permitted for sources included in this spec (SPEC-01)."""

    usage_policy_ref: str | None = Field(default=None, max_length=255)
    """D-01: forward reference to a Phase 25 Usage Policy — schema-validated
    (type only) in Phase 23; NOT existence-checked until Phase 25 lands,
    without a spec schema version bump."""

    quality_contract_ref: str | None = Field(default=None, max_length=255)
    """D-01: forward reference to a Phase 26 Quality Contract — schema-
    validated (type only) in Phase 23; NOT existence-checked until Phase 26
    lands, without a spec schema version bump."""

    curation_engine: str | None = Field(default=None, max_length=255)
    """Curation engine identifier this spec requests (SPEC-01)."""

    generation_strategy: dict | None = None
    """Generation strategy configuration (SPEC-01)."""

    validation_requirements: dict | None = None
    """Validation requirements configuration (SPEC-01)."""

    split_strategy: dict | None = None
    """Train/eval/test split strategy configuration (SPEC-01)."""

    decontamination_targets: list[str] = []
    """Decontamination target identifiers (SPEC-01)."""

    export_formats: list[str] = []
    """Export format identifiers (SPEC-01)."""

    release_requirements: dict | None = None
    """Release requirements configuration (SPEC-01)."""

    human_approval_requirements: dict | None = None
    """Human approval requirements configuration (SPEC-01)."""


# ── 11-state lifecycle graph (PROJ-02) ──────────────────────────────────────
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

LIFECYCLE_STATES: frozenset[str] = frozenset(_TRANSITIONS)
"""Public, derived-from-_TRANSITIONS set of all 11 lifecycle state names (WR-05).

The single source of truth for callers outside this module that need to
validate a state name (e.g. api/app.py's transition_project_endpoint) without
hand-maintaining a second enumeration (e.g. a regex) that can silently drift
from _TRANSITIONS if a state is ever added/removed/renamed.
"""


# NOT caught by agent/server.py's `_EXPECTED_ERRORS = (ValueError, LookupError)`
# tuple — if a future MCP mutating tool (e.g. `project_transition`) can raise
# this, `agent/server.py` needs its own hand-rolled `except` clause, mirroring
# the existing `TrainEvalContaminationError` special case (Pitfall 2).
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


class ProjectNotFoundError(ValueError):
    """Raised when a Dataset Project ID does not resolve to any row (PROJ-01).

    A ``ValueError`` subclass (unlike ``IllegalProjectTransitionError``, which
    is deliberately a ``RuntimeError``) so every existing ``except ValueError``
    catcher in this codebase (CLI commands, agent/server.py's
    ``_EXPECTED_ERRORS``) keeps working unchanged (WR-01 review fix). Callers
    that need to distinguish "not found" (404) from "bad input" (422) — e.g.
    ``create_spec_version_endpoint`` — should catch ``ProjectNotFoundError``
    before the broader ``ValueError``.
    """

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        super().__init__(f"Dataset Project not found: {project_id!r}")


def create_project(
    *,
    name: str,
    dataset_type: str,
    description: str | None = None,
    purpose: str | None = None,
    intended_uses: list[str] | None = None,
    prohibited_uses: list[str] | None = None,
    domain: str | None = None,
    owners: list[str] | None = None,
    settings: Settings | None = None,
) -> dict:
    """Create a new Dataset Project in status='draft' (PROJ-01).

    Args:
        name: Human-readable, unique Dataset Project name.
        dataset_type: Kind of dataset this project produces
            ('rag_eval', 'instruction_tuning', 'pretraining', etc.).
        description: Free-text description. None if omitted.
        purpose: Free-text statement of the project's purpose. None if omitted.
        intended_uses: List of free-text intended-use strings. Stored
            declaratively only — no gate in this function or anywhere in
            Phase 23 checks them against actual usage; enforcement arrives
            via Phase 25's Usage Policy Engine.
        prohibited_uses: List of free-text prohibited-use strings. Stored
            declaratively only — no gate in this function or anywhere in
            Phase 23 blocks project creation or any transition based on
            their content; enforcement arrives via Phase 25's Usage Policy
            Engine.
        domain: Domain pack name this project scopes to, e.g. 'healthcare'.
        owners: List of free-text owner names/emails. Informational only.
        settings: Settings override (for testing).

    Returns:
        dict with keys: id, name, dataset_type, status, domain.

    Raises:
        ValueError: If a project with this name already exists
            (uq_dataset_projects_name).
    """
    # Settings-driven convention (Pattern 1) — no sub-config to read yet, kept
    # for parity with the rest of pipeline/*.py and future extension.
    _settings = settings or get_settings()
    with get_session() as session:
        try:
            project = registry_repo.create_project(
                session,
                name=name,
                dataset_type=dataset_type,
                description=description,
                purpose=purpose,
                intended_uses=intended_uses,
                prohibited_uses=prohibited_uses,
                domain=domain,
                owners=owners,
            )
            session.flush()
        except IntegrityError as exc:
            raise ValueError(f"Dataset Project name already exists: {name!r}") from exc
        return {
            "id": project.id,
            "name": project.name,
            "dataset_type": project.dataset_type,
            "status": project.status,
            "domain": project.domain,
        }


def get_project(project_id: str, *, settings: Settings | None = None) -> dict:
    """Fetch a single Dataset Project by ID (PROJ-01).

    Args:
        project_id: Dataset Project ID (``dpj_...``).
        settings: Settings override (for testing).

    Returns:
        Full detail dict: id, name, dataset_type, status, domain, description,
        purpose, intended_uses, prohibited_uses, owners, created_at, updated_at
        (the latter two as ISO-8601 strings, mirroring
        ``_spec_version_to_dict``'s convention, so ``ProjectOut`` can declare
        them as plain ``str`` fields — WR-04 review fix).

    Raises:
        ValueError: If no project exists with this ID.
    """
    with get_session() as session:
        project = registry_repo.get_project_by_id(session, project_id)
        if project is None:
            raise ValueError(f"Dataset Project not found: {project_id!r}")
        return {
            "id": project.id,
            "name": project.name,
            "dataset_type": project.dataset_type,
            "status": project.status,
            "domain": project.domain,
            "description": project.description,
            "purpose": project.purpose,
            "intended_uses": project.intended_uses,
            "prohibited_uses": project.prohibited_uses,
            "owners": project.owners,
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat(),
        }


def list_projects(*, settings: Settings | None = None) -> list[dict]:
    """List all Dataset Projects, ordered created_at DESC, id DESC (PROJ-01).

    Args:
        settings: Settings override (for testing).

    Returns:
        List of summary dicts (same shape as create_project()'s return), one
        per row, empty list if none exist.
    """
    with get_session() as session:
        projects = registry_repo.list_projects(session)
        return [
            {
                "id": p.id,
                "name": p.name,
                "dataset_type": p.dataset_type,
                "status": p.status,
                "domain": p.domain,
            }
            for p in projects
        ]


def transition_project(
    project_id: str, to_state: str, *, settings: Settings | None = None
) -> dict:
    """Transition a Dataset Project to a new lifecycle state (PROJ-02).

    Guarded by the module-level _TRANSITIONS adjacency map — an edge not
    present in the current state's legal-next set (including a self-
    transition) raises IllegalProjectTransitionError without mutating
    ``status`` at all.

    Args:
        project_id: Dataset Project ID (``dpj_...``).
        to_state: Target lifecycle state.
        settings: Settings override (for testing).

    Returns:
        dict with keys: id, status (the new status).

    Raises:
        ValueError: If no project exists with this ID.
        IllegalProjectTransitionError: If ``to_state`` is not in the legal
            next-states set for the project's current status.
    """
    _settings = settings or get_settings()
    with get_session() as session:
        project = registry_repo.get_project_by_id(session, project_id)
        if project is None:
            raise ValueError(f"Dataset Project not found: {project_id!r}")
        legal_next = _TRANSITIONS.get(project.status, set())
        if to_state not in legal_next:
            raise IllegalProjectTransitionError(project.status, to_state, legal_next)
        project.status = to_state
        return {"id": project.id, "status": project.status}


# ── Dataset Specification versioning (SPEC-01..03) ──────────────────────────


def _spec_content_hash(parsed_spec: dict) -> str:
    """Derive the canonical content hash for a parsed Dataset Specification dict.

    D-03: sha256 over the canonical (sorted-key) JSON serialization of
    ``parsed_spec`` — NOT over raw YAML bytes, so formatting-only re-saves
    (key reordering, whitespace, comments) never produce a spurious new
    version. Mirrors pipeline.curate._curation_cache_key's exact
    hashlib.sha256(...).hexdigest() shape, adapted to hash canonical JSON
    instead of an f-string.
    """
    canonical_bytes = orjson.dumps(parsed_spec, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(canonical_bytes).hexdigest()


def _spec_version_to_dict(spec_row) -> dict:
    """Shared dict-shape builder for create_spec_version()/get_latest_spec()."""
    return {
        "id": spec_row.id,
        "dataset_project_id": spec_row.dataset_project_id,
        "parent_spec_id": spec_row.parent_spec_id,
        "content_hash": spec_row.content_hash,
        "schema_version": spec_row.schema_version,
        "author": spec_row.author,
        "created_at": spec_row.created_at.isoformat(),
    }


def create_spec_version(
    project_id: str, spec: dict, *, author: str, settings: Settings | None = None
) -> dict:
    """Create a new immutable Dataset Specification version (SPEC-01/02).

    The incoming ``spec`` dict is validated against DatasetSpecFields's
    allow-list BEFORE any DB touch (T-23-07 mass-assignment mitigation). D-03:
    the canonical content hash is computed first; if it exactly matches the
    project's current latest spec version's content_hash, NO new DatasetSpec
    row is inserted — the existing (unchanged) version is returned instead
    (re-saving byte-identical-but-reformatted YAML is a merge/no-op, never a
    spurious new version).

    ``author`` is a self-reported free-text string — no authentication system
    backs it in this codebase; do not treat it as a verified identity
    (Pitfall 4).

    Args:
        project_id: Dataset Project ID (``dpj_...``) this spec version belongs to.
        spec: Parsed Dataset Specification dict (SPEC-01 field set).
        author: Self-reported free-text attribution string.
        settings: Settings override (for testing).

    Returns:
        dict with keys: id, dataset_project_id, parent_spec_id, content_hash,
        schema_version, author, created_at.

    Raises:
        ValueError: If ``spec`` fails DatasetSpecFields validation.
        ProjectNotFoundError: If no project exists with ``project_id`` (a
            ``ValueError`` subclass — callers that need to distinguish
            "not found" from "bad input" should catch
            ``ProjectNotFoundError`` first).
    """
    _settings = settings or get_settings()
    try:
        validated = DatasetSpecFields(**spec)
    except ValidationError as exc:
        raise ValueError(f"Invalid Dataset Specification: {exc}") from exc
    validated_dict = validated.model_dump()
    content_hash = _spec_content_hash(validated_dict)

    with get_session() as session:
        project = registry_repo.get_project_by_id(session, project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)

        latest = registry_repo.get_latest_spec_version(session, project_id)
        if latest is not None and latest.content_hash == content_hash:
            # D-03/E11: formatting-only re-save — merge/no-op, return the
            # existing (unchanged) version rather than inserting a new row.
            return _spec_version_to_dict(latest)

        parent_spec_id = latest.id if latest is not None else None
        new_spec = registry_repo.create_spec_version_row(
            session,
            dataset_project_id=project_id,
            spec=validated_dict,
            content_hash=content_hash,
            schema_version=_SCHEMA_VERSION,
            author=author,
            parent_spec_id=parent_spec_id,
        )
        session.flush()
        return _spec_version_to_dict(new_spec)


def get_latest_spec(project_id: str, *, settings: Settings | None = None) -> dict | None:
    """Fetch the most recently created Dataset Specification version for a project.

    Args:
        project_id: Dataset Project ID (``dpj_...``).
        settings: Settings override (for testing).

    Returns:
        dict in the same shape create_spec_version() returns, or None if the
        project exists but has zero spec versions.

    Raises:
        ProjectNotFoundError: If no project exists with this ID (a
            ``ValueError`` subclass, consistent with get_project()/
            transition_project()/create_spec_version() — WR-02 review fix).
    """
    _settings = settings or get_settings()
    with get_session() as session:
        project = registry_repo.get_project_by_id(session, project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        latest = registry_repo.get_latest_spec_version(session, project_id)
        if latest is None:
            return None
        return _spec_version_to_dict(latest)


def validate_spec(spec_id: str, *, settings: Settings | None = None) -> dict:
    """Validate a Dataset Specification version's referential integrity (SPEC-03).

    Only ``included_sources``/``excluded_sources`` are existence-checked
    against the live ``sources`` table this phase. ``quality_contract_ref``/
    ``usage_policy_ref`` are validated structurally only (already enforced by
    DatasetSpecFields's Pydantic type) — Phases 25/26 add referential
    enforcement for those two WITHOUT a spec schema version bump (D-01).

    Args:
        spec_id: Dataset Specification version ID (``dsp_...``).
        settings: Settings override (for testing).

    Returns:
        dict with keys: spec_id, dataset_project_id, valid (bool), errors
        (list[str], one itemized "Source not found: <id>" entry per
        unresolved reference — empty list when valid).

    Raises:
        ValueError: If no spec version exists with this ID.
    """
    _settings = settings or get_settings()
    with get_session() as session:
        spec_row = registry_repo.get_spec_by_id(session, spec_id)
        if spec_row is None:
            raise ValueError(f"Dataset Specification version not found: {spec_id!r}")

        errors: list[str] = []
        spec_dict = spec_row.spec
        referenced_source_ids = spec_dict.get("included_sources", []) + spec_dict.get(
            "excluded_sources", []
        )
        for source_id in referenced_source_ids:
            if registry_repo.get_source(session, source_id) is None:
                errors.append(f"Source not found: {source_id!r}")

        return {
            "spec_id": spec_row.id,
            "dataset_project_id": spec_row.dataset_project_id,
            "valid": len(errors) == 0,
            "errors": errors,
        }
