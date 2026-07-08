"""Unit tests for pipeline/index.py's extended payload join (D-07, INDEX-01).

Uses the same in-memory-SQLite-backed session harness as tests/unit/test_enrich.py:
knowledge_lake.registry.db.get_engine is monkeypatched to a StaticPool sqlite
engine so index()'s own get_session() calls resolve against the same database
the test seeds via registry_repo. get_vectorstore() is mocked at the
pipeline.index module level (mirrors tests/unit/test_builtin_plugins.py's
mocking style) so no real Qdrant server is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.pipeline.index as index_module
import knowledge_lake.registry.db as registry_db
from knowledge_lake.registry import repo as registry_repo


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    """In-memory SQLite engine, shared connection via StaticPool so multiple
    Session() instances (opened by separate get_session() calls inside index())
    all see the same committed data.
    """
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
    """Route registry.db.get_session() at index()'s call sites to the test engine."""
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)


@pytest.fixture()
def session(engine):
    with Session(engine) as sess:
        yield sess


@pytest.fixture()
def fake_vstore(monkeypatch):
    """Mock get_vectorstore() so index() never touches a real Qdrant server.

    ensure_aliased_collection defaults to (already-existing alias, created=False)
    so the registry-write path is NOT exercised unless a test explicitly wants it.
    """
    vstore = MagicMock()
    vstore.ensure_aliased_collection.return_value = ("klake_chunks_v1", False)
    monkeypatch.setattr(index_module, "get_vectorstore", lambda _s: vstore)
    return vstore


def _one_chunk(chunk_id: str = "chk_001") -> dict:
    return {
        "chunk_id": chunk_id,
        "section_path": "§1",
        "page": 1,
        "text": "hello world",
    }


def _captured_payload(vstore: MagicMock) -> dict:
    """Extract the single upserted VectorPoint's payload from the mocked upsert call."""
    upsert_call = vstore.upsert.call_args
    points = upsert_call.args[1] if upsert_call.args and len(upsert_call.args) > 1 else upsert_call.kwargs["points"]
    return points[0].payload


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestPayloadDomainFromSourceConfig:
    def test_payload_includes_domain_from_source_config(self, session, fake_vstore) -> None:
        source = registry_repo.create_source(
            session, name="Domain Source", source_type="web", config={"domain": "healthcare"}
        )
        raw = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="d_raw", storage_uri="s3://b/raw/d_raw.pdf",
        )
        parsed = registry_repo.create_parsed_artifact(
            session, source_id=source.id, parent_artifact_id=raw.id,
            content_hash="d_parsed", storage_uri="s3://b/silver/d_parsed.json",
        )
        session.commit()

        chunks = [_one_chunk()]
        vectors = [[0.1] * 4]
        index_module.index(chunks, vectors, dim=4, parsed_artifact_id=parsed.id)

        payload = _captured_payload(fake_vstore)
        assert payload["domain"] == "healthcare"
        assert payload["document_type"] is None
        assert payload["quality_score"] is None

    def test_payload_domain_none_when_source_config_empty(self, session, fake_vstore) -> None:
        source = registry_repo.create_source(
            session, name="No Config Source", source_type="web", config=None,
        )
        raw = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="nc_raw", storage_uri="s3://b/raw/nc_raw.pdf",
        )
        parsed = registry_repo.create_parsed_artifact(
            session, source_id=source.id, parent_artifact_id=raw.id,
            content_hash="nc_parsed", storage_uri="s3://b/silver/nc_parsed.json",
        )
        session.commit()

        chunks = [_one_chunk()]
        vectors = [[0.1] * 4]
        # Must not raise even though config is None.
        index_module.index(chunks, vectors, dim=4, parsed_artifact_id=parsed.id)

        payload = _captured_payload(fake_vstore)
        assert payload["domain"] is None


class TestPayloadEnrichmentFields:
    def test_payload_includes_enrichment_fields_when_present(self, session, fake_vstore) -> None:
        source = registry_repo.create_source(session, name="Enrich Source", source_type="web")
        raw = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="e_raw", storage_uri="s3://b/raw/e_raw.pdf",
        )
        parsed = registry_repo.create_parsed_artifact(
            session, source_id=source.id, parent_artifact_id=raw.id,
            content_hash="e_parsed", storage_uri="s3://b/silver/e_parsed.json",
        )
        cleaned = registry_repo.create_cleaned_artifact(
            session, source_id=source.id, parent_artifact_id=parsed.id,
            content_hash="e_cleaned", storage_uri="s3://b/silver/e_cleaned.md",
        )
        registry_repo.create_enriched_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=cleaned.id,
            content_hash="e_enriched",
            metadata={"document_type": "guidance", "keywords": ["hipaa", "security"]},
            quality_score=0.82,
        )
        session.commit()

        chunks = [_one_chunk()]
        vectors = [[0.1] * 4]
        index_module.index(chunks, vectors, dim=4, parsed_artifact_id=parsed.id)

        payload = _captured_payload(fake_vstore)
        assert payload["document_type"] == "guidance"
        assert payload["keywords"] == ["hipaa", "security"]
        assert payload["quality_score"] == 0.82


class TestEnsureAliasedCollectionRegistration:
    def test_ensure_aliased_collection_registers_on_first_create(
        self, session, monkeypatch
    ) -> None:
        source = registry_repo.create_source(session, name="Reg Source", source_type="web")
        raw = registry_repo.create_raw_artifact(
            session, source_id=source.id, content_hash="r_raw", storage_uri="s3://b/raw/r_raw.pdf",
        )
        parsed = registry_repo.create_parsed_artifact(
            session, source_id=source.id, parent_artifact_id=raw.id,
            content_hash="r_parsed", storage_uri="s3://b/silver/r_parsed.json",
        )
        session.commit()

        vstore = MagicMock()
        vstore.ensure_aliased_collection.return_value = ("klake_chunks_v1", True)
        monkeypatch.setattr(index_module, "get_vectorstore", lambda _s: vstore)

        register_spy = MagicMock(wraps=registry_repo.register_vector_collection)
        monkeypatch.setattr(registry_repo, "register_vector_collection", register_spy)

        index_module.index([_one_chunk()], [[0.1] * 4], dim=4, parsed_artifact_id=parsed.id)

        register_spy.assert_called_once()
        _, call_kwargs = register_spy.call_args
        assert call_kwargs["physical_collection"] == "klake_chunks_v1"

        # A second call where ensure_aliased_collection reports created=False
        # must NOT call register_vector_collection again.
        vstore.ensure_aliased_collection.return_value = ("klake_chunks", False)
        register_spy.reset_mock()
        index_module.index(
            [_one_chunk("chk_002")], [[0.1] * 4], dim=4, parsed_artifact_id=parsed.id
        )
        register_spy.assert_not_called()


class TestPayloadNewFieldsStub:
    """RED-state stub: asserts that the 7 new source-metadata fields exist in the payload.
    Will fail until get_source() + index.py join extension are implemented (Task 1 GREEN).
    """

    def test_payload_contains_source_name_field(self, session, fake_vstore) -> None:
        source = registry_repo.create_source(
            session,
            name="Stub Source",
            source_type="html",
            config={"domain": "healthcare", "tags": ["test"]},
        )
        raw = registry_repo.create_raw_artifact(
            session,
            source_id=source.id,
            content_hash="stub_raw",
            storage_uri="s3://b/raw/stub_raw.pdf",
        )
        parsed = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash="stub_parsed",
            storage_uri="s3://b/silver/stub_parsed.json",
        )
        session.commit()

        index_module.index([_one_chunk()], [[0.1] * 4], dim=4, parsed_artifact_id=parsed.id)
        payload = _captured_payload(fake_vstore)
        assert "source_name" in payload
        assert "format" in payload
        assert "tags" in payload
        assert "title" in payload
        assert "organization" in payload
        assert "source_url" in payload
        assert "source_id" in payload


class TestPayloadSourceFields:
    """Verify 7 new source-metadata payload fields (PAYLOAD-01, D-01..D-05)."""

    def test_payload_includes_all_7_new_fields_when_source_has_metadata(
        self, session, fake_vstore
    ) -> None:
        """All 7 new payload fields are populated from a Source row with full config."""
        source = registry_repo.create_source(
            session,
            name="IFM",
            source_type="html",
            url="https://ifm.org",
            config={
                "domain": "healthcare",
                "tags": ["functional-medicine", "ifm"],
                "organization": "IFM",
            },
        )
        raw = registry_repo.create_raw_artifact(
            session,
            source_id=source.id,
            content_hash="ifm_raw",
            storage_uri="s3://b/raw/ifm_raw.html",
        )
        parsed = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash="ifm_parsed",
            storage_uri="s3://b/silver/ifm_parsed.json",
        )
        cleaned = registry_repo.create_cleaned_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed.id,
            content_hash="ifm_cleaned",
            storage_uri="s3://b/silver/ifm_cleaned.md",
        )
        registry_repo.create_enriched_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=cleaned.id,
            content_hash="ifm_enriched",
            metadata={"title": "Functional Medicine Basics", "document_type": "guide"},
        )
        session.commit()

        index_module.index([_one_chunk()], [[0.1] * 4], dim=4, parsed_artifact_id=parsed.id)
        payload = _captured_payload(fake_vstore)

        assert payload["source_id"] == source.id
        assert payload["source_name"] == "IFM"
        assert payload["source_url"] == "https://ifm.org"
        assert payload["format"] == "html"
        assert payload["tags"] == ["functional-medicine", "ifm"]
        assert payload["title"] == "Functional Medicine Basics"
        assert payload["organization"] == "IFM"

    def test_payload_source_fields_degrade_gracefully_when_no_source(
        self, session, fake_vstore
    ) -> None:
        """When a source has config=None, all optional source-metadata fields degrade."""
        source = registry_repo.create_source(
            session,
            name="NoMeta",
            source_type="web",
            config=None,
        )
        raw = registry_repo.create_raw_artifact(
            session,
            source_id=source.id,
            content_hash="nm_raw",
            storage_uri="s3://b/raw/nm_raw.pdf",
        )
        parsed = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash="nm_parsed",
            storage_uri="s3://b/silver/nm_parsed.json",
        )
        session.commit()

        index_module.index([_one_chunk()], [[0.1] * 4], dim=4, parsed_artifact_id=parsed.id)
        payload = _captured_payload(fake_vstore)

        # Source exists but config is None — optional fields degrade gracefully.
        assert payload["source_name"] == "NoMeta"  # name always present
        assert payload["source_url"] is None
        assert payload["format"] == "web"
        assert payload["tags"] == []
        assert payload["title"] is None
        assert payload["organization"] is None

    def test_payload_title_from_enriched_metadata(
        self, session, fake_vstore
    ) -> None:
        """title comes from enriched artifact metadata_ even when source has no org/tags."""
        source = registry_repo.create_source(
            session,
            name="HHS",
            source_type="pdf",
            config={"domain": "healthcare"},
        )
        raw = registry_repo.create_raw_artifact(
            session,
            source_id=source.id,
            content_hash="hhs_raw",
            storage_uri="s3://b/raw/hhs_raw.pdf",
        )
        parsed = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash="hhs_parsed",
            storage_uri="s3://b/silver/hhs_parsed.json",
        )
        cleaned = registry_repo.create_cleaned_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed.id,
            content_hash="hhs_cleaned",
            storage_uri="s3://b/silver/hhs_cleaned.md",
        )
        registry_repo.create_enriched_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=cleaned.id,
            content_hash="hhs_enriched",
            metadata={"title": "HIPAA Security Rule", "document_type": "regulation"},
        )
        session.commit()

        index_module.index([_one_chunk()], [[0.1] * 4], dim=4, parsed_artifact_id=parsed.id)
        payload = _captured_payload(fake_vstore)

        assert payload["title"] == "HIPAA Security Rule"
        assert payload["tags"] == []
        assert payload["organization"] is None

    def test_register_source_persists_tags_into_config(
        self, session, fake_vstore
    ) -> None:
        """register_source() persists tags into Source.config alongside domain (D-05)."""
        from knowledge_lake.pipeline.ingest import register_source

        register_source(
            "https://hl7.org/fhir",
            "HL7 FHIR",
            domain="healthcare",
            tags=["fhir", "hl7"],
        )

        # The _patch_engine autouse fixture routes get_session() to the test engine,
        # so register_source() wrote the source into our in-memory SQLite DB.
        from sqlalchemy import select
        from knowledge_lake.registry.models import Source

        with Session(session.bind) as verify_session:
            stmt = select(Source).where(Source.name == "HL7 FHIR")
            src = verify_session.execute(stmt).scalar_one()

        assert src.config is not None
        assert src.config["tags"] == ["fhir", "hl7"]
        assert src.config["domain"] == "healthcare"


class TestEmptyChunksShortCircuit:
    def test_empty_chunks_returns_empty_list_without_touching_vstore(
        self, session, fake_vstore
    ) -> None:
        assert index_module.index([], [], dim=4, parsed_artifact_id="doc_missing") == []
        fake_vstore.ensure_aliased_collection.assert_not_called()


class TestChunksVectorsLengthMismatch:
    def test_mismatched_lengths_raise_value_error_not_assert(
        self, session, fake_vstore
    ) -> None:
        """Regression for WR-04: a chunks/vectors length mismatch must raise a
        real ValueError (never a bare ``assert``, which is compiled out under
        python -O) so a buggy embedder can't silently truncate indexed chunks.
        """
        chunks = [_one_chunk("chk_001"), _one_chunk("chk_002")]
        vectors = [[0.1] * 4]  # one vector short

        with pytest.raises(ValueError, match="length mismatch"):
            index_module.index(chunks, vectors, dim=4, parsed_artifact_id="doc_missing")

        fake_vstore.ensure_aliased_collection.assert_not_called()
