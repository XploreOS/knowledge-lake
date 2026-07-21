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

import structlog
from sqlalchemy.exc import IntegrityError

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session

log = structlog.get_logger(__name__)


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
        purpose, intended_uses, prohibited_uses, owners, created_at, updated_at.

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
            "created_at": project.created_at,
            "updated_at": project.updated_at,
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
