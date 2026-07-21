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
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.registry.db as registry_db
from knowledge_lake.pipeline.project import (
    _TRANSITIONS,
    DatasetSpecFields,
    IllegalProjectTransitionError,
    _spec_content_hash,
    create_project,
    create_spec_version,
    get_latest_spec,
    get_project,
    list_projects,
    transition_project,
    validate_spec,
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


# ── Plan 23-03 Task 1 leftovers: DatasetSpecFields allow-list schema ───────


class TestSpecFields:
    def test_spec_minimal_fields_validate(self):
        """Only purpose/dataset_type/domain given -- every other field
        defaults per DatasetSpecFields().model_dump() shape (E10)."""
        spec = DatasetSpecFields(purpose="p", dataset_type="rag_eval", domain="healthcare")
        dumped = spec.model_dump()
        assert dumped["purpose"] == "p"
        assert dumped["dataset_type"] == "rag_eval"
        assert dumped["domain"] == "healthcare"
        assert dumped["included_sources"] == []
        assert dumped["excluded_sources"] == []
        assert dumped["allowed_license_categories"] == []
        assert dumped["usage_policy_ref"] is None
        assert dumped["quality_contract_ref"] is None
        assert dumped["curation_engine"] is None
        assert dumped["generation_strategy"] is None
        assert dumped["validation_requirements"] is None
        assert dumped["split_strategy"] is None
        assert dumped["decontamination_targets"] == []
        assert dumped["export_formats"] == []
        assert dumped["release_requirements"] is None
        assert dumped["human_approval_requirements"] is None

    def test_spec_extra_field_rejected(self):
        """An unrecognized key raises ValidationError directly (allow-list),
        and create_spec_version() translates it to ValueError (mass-
        assignment mitigation proof, T-23-07)."""
        with pytest.raises(ValidationError):
            DatasetSpecFields(purpose="p", dataset_type="t", domain="d", bogus_field="x")

    def test_spec_extra_field_rejected_via_create_spec_version(self):
        result = create_project(name="Extra Field Project", dataset_type="rag_eval")
        with pytest.raises(ValueError, match="Invalid Dataset Specification"):
            create_spec_version(
                result["id"],
                {"purpose": "p", "dataset_type": "t", "domain": "d", "bogus_field": "x"},
                author="alice",
            )


# ── Plan 23-03 Task 1 leftovers: content hash + versioning behavior ────────


class TestSpecVersioning:
    def test_spec_content_hash_key_order_independent(self):
        assert _spec_content_hash({"a": 1, "b": 2}) == _spec_content_hash({"b": 2, "a": 1})

    def test_create_spec_version_first_has_no_parent(self):
        """E12: the first-ever spec version for a brand-new project has
        parent_spec_id=None."""
        result = create_project(name="First Spec Project", dataset_type="rag_eval")
        v1 = create_spec_version(
            result["id"],
            {"purpose": "p", "dataset_type": "t", "domain": "d"},
            author="alice",
        )
        assert v1["parent_spec_id"] is None

    def test_get_latest_spec_empty_project_returns_none(self):
        """E12: get_latest_spec() for a project with zero spec versions
        returns None, never raising."""
        result = create_project(name="No Spec Project", dataset_type="rag_eval")
        assert get_latest_spec(result["id"]) is None

    def test_spec_hash_stable_across_yaml_formatting(self, session):
        """E11: two Python dicts representing the SAME spec content but
        constructed with different key insertion order (mirroring what two
        differently-formatted-but-semantically-identical YAML files would
        parse to) result in exactly ONE DatasetSpec row for the project."""
        result = create_project(name="Formatting Stable Project", dataset_type="rag_eval")
        pid = result["id"]

        create_spec_version(
            pid,
            {"purpose": "p", "dataset_type": "t", "domain": "d"},
            author="alice",
        )
        create_spec_version(
            pid,
            {"domain": "d", "purpose": "p", "dataset_type": "t"},
            author="alice",
        )

        rows = [
            row
            for row in session.execute(
                registry_repo.select(registry_repo.DatasetSpec)
            ).scalars()
            if row.dataset_project_id == pid
        ]
        assert len(rows) == 1

    def test_spec_version_immutable_chain(self, session):
        """Two genuinely different spec versions: the second's parent_spec_id
        equals the first's id; re-fetching the FIRST version afterward proves
        it is retrievable unmodified (ROADMAP Success Criterion 3)."""
        result = create_project(name="Immutable Chain Project", dataset_type="rag_eval")
        pid = result["id"]

        v1 = create_spec_version(
            pid, {"purpose": "p1", "dataset_type": "t", "domain": "d"}, author="alice"
        )
        v2 = create_spec_version(
            pid, {"purpose": "p2", "dataset_type": "t", "domain": "d"}, author="bob"
        )
        assert v2["parent_spec_id"] == v1["id"]

        refetched = registry_repo.get_spec_by_id(session, v1["id"])
        assert refetched.content_hash == v1["content_hash"]
        assert refetched.spec == {
            "purpose": "p1",
            "dataset_type": "t",
            "domain": "d",
            "included_sources": [],
            "excluded_sources": [],
            "allowed_license_categories": [],
            "usage_policy_ref": None,
            "quality_contract_ref": None,
            "curation_engine": None,
            "generation_strategy": None,
            "validation_requirements": None,
            "split_strategy": None,
            "decontamination_targets": [],
            "export_formats": [],
            "release_requirements": None,
            "human_approval_requirements": None,
        }

    def test_get_latest_spec_version_ordering_tiebreak(self, session):
        """E13: two versions with an identical created_at -- id DESC breaks
        the tie."""
        result = create_project(name="Spec Tiebreak Project", dataset_type="rag_eval")
        pid = result["id"]

        v1 = create_spec_version(
            pid, {"purpose": "p1", "dataset_type": "t", "domain": "d"}, author="alice"
        )
        v2 = create_spec_version(
            pid, {"purpose": "p2", "dataset_type": "t", "domain": "d"}, author="alice"
        )

        tied_ts = datetime.datetime.now(datetime.UTC)
        row1 = registry_repo.get_spec_by_id(session, v1["id"])
        row2 = registry_repo.get_spec_by_id(session, v2["id"])
        row1.created_at = tied_ts
        row2.created_at = tied_ts
        session.flush()
        session.commit()

        latest = get_latest_spec(pid)
        expected_id = max(v1["id"], v2["id"])
        assert latest["id"] == expected_id


# ── Task 2: validate_spec() referential integrity ───────────────────────────


class TestValidateSpec:
    def test_spec_validate_unknown_source_fails(self):
        result = create_project(name="Validate Unknown Source Project", dataset_type="rag_eval")
        v1 = create_spec_version(
            result["id"],
            {
                "purpose": "p",
                "dataset_type": "t",
                "domain": "d",
                "included_sources": ["src_does_not_exist"],
            },
            author="alice",
        )

        report = validate_spec(v1["id"])
        assert report["valid"] is False
        assert "Source not found: 'src_does_not_exist'" in report["errors"]

    def test_spec_validate_all_refs_resolve(self, session):
        result = create_project(name="Validate All Refs Project", dataset_type="rag_eval")
        source = registry_repo.create_source(
            session, name="A Real Source", source_type="web", url="https://example.com"
        )
        session.flush()
        session.commit()

        v1 = create_spec_version(
            result["id"],
            {
                "purpose": "p",
                "dataset_type": "t",
                "domain": "d",
                "included_sources": [source.id],
            },
            author="alice",
        )

        report = validate_spec(v1["id"])
        assert report["valid"] is True
        assert report["errors"] == []

    def test_spec_validate_empty_source_lists_is_valid(self):
        """An empty included_sources/excluded_sources list (no source
        references at all) is vacuously valid, not an error."""
        result = create_project(name="Validate Empty Refs Project", dataset_type="rag_eval")
        v1 = create_spec_version(
            result["id"],
            {"purpose": "p", "dataset_type": "t", "domain": "d"},
            author="alice",
        )

        report = validate_spec(v1["id"])
        assert report["valid"] is True
        assert report["errors"] == []

    def test_spec_validate_ignores_quality_contract_and_policy_refs(self, session):
        """D-01: quality_contract_ref/usage_policy_ref are validated
        structurally only -- a spec with nonsense refs still validates=True
        as long as its source references resolve."""
        result = create_project(name="Validate D01 Scope Project", dataset_type="rag_eval")
        source = registry_repo.create_source(
            session, name="Another Real Source", source_type="web", url="https://example.org"
        )
        session.flush()
        session.commit()

        v1 = create_spec_version(
            result["id"],
            {
                "purpose": "p",
                "dataset_type": "t",
                "domain": "d",
                "included_sources": [source.id],
                "quality_contract_ref": "qc_totally_made_up",
                "usage_policy_ref": "pol_made_up",
            },
            author="alice",
        )

        report = validate_spec(v1["id"])
        assert report["valid"] is True
        assert report["errors"] == []

    def test_spec_validate_unknown_spec_id_raises(self):
        """validate_spec('dsp_unknown') raises ValueError rather than
        returning a malformed report."""
        with pytest.raises(ValueError, match="not found"):
            validate_spec("dsp_unknown")
