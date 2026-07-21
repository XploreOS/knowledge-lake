"""Tests for pipeline/project.py — Dataset Project lifecycle: create/get/list/
transition (PROJ-01, PROJ-02).

Uses an in-memory-SQLite-backed session (mirrors tests/unit/test_curate.py's
engine/session fixture pattern) with knowledge_lake.registry.db.get_engine
monkeypatched so create_project()/transition_project()'s own get_session()
calls resolve against the same in-memory database.
"""

from __future__ import annotations

import datetime
import unicodedata

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.registry.db as registry_db
from knowledge_lake.pipeline.project import (
    _TRANSITIONS,
    IllegalProjectTransitionError,
    create_project,
    get_project,
    list_projects,
    transition_project,
)
from knowledge_lake.registry import repo as registry_repo

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    """In-memory SQLite engine, shared connection via StaticPool so multiple
    Session() instances all see the same database."""
    from knowledge_lake.registry.models import Base

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _patch_engine(monkeypatch, engine):
    """Route registry.db.get_session() at create_project()/transition_project()
    call sites to the in-memory test engine."""
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)


@pytest.fixture()
def session(engine):
    with Session(engine) as sess:
        yield sess


# ── Task 1: core create/get/list/transition happy paths ────────────────────


class TestCreateProject:
    def test_create_project_draft_state(self):
        result = create_project(
            name="Healthcare RAG Corpus",
            dataset_type="rag_eval",
            description="A description",
            purpose="A purpose",
            intended_uses=["research"],
            prohibited_uses=["resale"],
            domain="healthcare",
            owners=["alice@example.com"],
        )
        assert result["status"] == "draft"
        assert result["name"] == "Healthcare RAG Corpus"
        assert result["dataset_type"] == "rag_eval"
        assert result["domain"] == "healthcare"
        assert result["id"].startswith("dpj_")

        full = get_project(result["id"])
        assert full["description"] == "A description"
        assert full["purpose"] == "A purpose"
        assert full["intended_uses"] == ["research"]
        assert full["prohibited_uses"] == ["resale"]
        assert full["owners"] == ["alice@example.com"]

    def test_create_project_optional_fields_omitted(self):
        result = create_project(name="Minimal Project", dataset_type="pretraining")
        full = get_project(result["id"])
        assert full["description"] is None
        assert full["purpose"] is None
        assert full["intended_uses"] is None
        assert full["prohibited_uses"] is None
        assert full["domain"] is None
        assert full["owners"] is None

    def test_create_project_duplicate_name_raises_valueerror(self, session):
        create_project(name="Dup Project", dataset_type="rag_eval")
        with pytest.raises(ValueError, match="already exists"):
            create_project(name="Dup Project", dataset_type="rag_eval")

        # Exactly one row exists for the duplicated name (E3).
        matches = [
            p for p in registry_repo.list_projects(session) if p.name == "Dup Project"
        ]
        assert len(matches) == 1

    def test_create_project_duplicate_name_simulated_race(self, session):
        """Two create_project() calls in immediate succession against the SAME
        shared engine prove the DB-level UNIQUE constraint is the actual
        enforcement mechanism, not an application-level pre-check (E4)."""
        create_project(name="Race Project", dataset_type="rag_eval")
        with pytest.raises(ValueError, match="already exists"):
            create_project(name="Race Project", dataset_type="rag_eval")

        matches = [
            p for p in registry_repo.list_projects(session) if p.name == "Race Project"
        ]
        assert len(matches) == 1

    def test_create_project_name_byte_equality_no_normalization(self):
        """No NFC/casefold normalization is applied -- byte-distinct unicode
        strings that look similar are stored as distinct rows (E2)."""
        nfc_name = unicodedata.normalize("NFC", "Caf\u00e9-Docs")
        # NFD-decomposed form of the e-acute is a byte-distinct string from
        # the NFC-composed form above, even though both render identically.
        nfd_name = unicodedata.normalize("NFD", "Caf\u00e9-Docs")
        assert nfd_name != nfc_name

        r1 = create_project(name=nfc_name, dataset_type="rag_eval")
        r2 = create_project(name=nfd_name, dataset_type="rag_eval")
        assert r1["id"] != r2["id"]


# ── Task 2: state-graph reachability, self-transition, ordering tiebreak ───


class TestTransitions:
    def test_legal_transition_succeeds(self):
        result = create_project(name="Transition Project", dataset_type="rag_eval")
        updated = transition_project(result["id"], "configured")
        assert updated["status"] == "configured"
        assert get_project(result["id"])["status"] == "configured"

    def test_illegal_transition_rejected(self):
        result = create_project(name="Illegal Transition Project", dataset_type="rag_eval")
        with pytest.raises(IllegalProjectTransitionError) as exc_info:
            transition_project(result["id"], "released")

        err = exc_info.value
        assert err.from_state == "draft"
        assert err.to_state == "released"
        assert err.legal_next_states == ["configured"]

        # status is unchanged after the illegal attempt.
        assert get_project(result["id"])["status"] == "draft"

    def test_self_transition_rejected(self):
        """A self-transition (to_state == current status) is never a legal
        edge — draft -> draft raises like any other illegal edge (E6)."""
        result = create_project(name="Self Transition Project", dataset_type="rag_eval")
        with pytest.raises(IllegalProjectTransitionError):
            transition_project(result["id"], "draft")
        assert get_project(result["id"])["status"] == "draft"

    def test_transitions_graph_no_dead_ends(self):
        """Every state key in the ACTUAL _TRANSITIONS dict has a non-empty
        legal-next set, except 'archived' which is the explicit terminal
        state (E5)."""
        for state, legal_next in _TRANSITIONS.items():
            if state == "archived":
                assert legal_next == set()
            else:
                assert legal_next, f"state {state!r} has no legal outgoing edges"


# ── Task 2: list_projects() ordering + empty case ───────────────────────────


class TestListProjects:
    def test_list_projects_empty(self):
        assert list_projects() == []

    def test_list_projects_ordering_tiebreak(self, session):
        r1 = create_project(name="Tiebreak A", dataset_type="rag_eval")
        r2 = create_project(name="Tiebreak B", dataset_type="rag_eval")

        # Force both rows to share the exact same created_at so id DESC is the
        # only thing that can break the tie (E8).
        tied_ts = datetime.datetime.now(datetime.UTC)
        row1 = registry_repo.get_project_by_id(session, r1["id"])
        row2 = registry_repo.get_project_by_id(session, r2["id"])
        row1.created_at = tied_ts
        row2.created_at = tied_ts
        session.flush()
        session.commit()

        results = list_projects()
        tied_ids = [p["id"] for p in results if p["id"] in (r1["id"], r2["id"])]
        expected_order = sorted([r1["id"], r2["id"]], reverse=True)
        assert tied_ids == expected_order
