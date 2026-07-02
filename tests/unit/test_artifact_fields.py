"""
Unit tests verifying the six FOUND-06 lineage fields are non-null on every
artifact type and that the UNIQUE(content_hash, artifact_type) constraint
prevents duplicate nodes.

These tests run against an in-memory SQLite database.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, exc as sa_exc
from sqlalchemy.orm import Session


@pytest.fixture(scope="module")
def engine():
    from knowledge_lake.registry.models import Base

    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    with Session(engine) as sess:
        yield sess
        sess.rollback()


@pytest.fixture()
def source(session):
    from knowledge_lake.registry.repo import create_source
    return create_source(session, name="FOUND-06 Source", source_type="web")


class TestFoundSixFields:
    """Every artifact carries the six FOUND-06 lineage fields."""

    def test_raw_all_six_fields_non_null(self, session, source) -> None:
        from knowledge_lake.registry.repo import create_raw_artifact

        art = create_raw_artifact(
            session,
            source_id=source.id,
            content_hash="f06_raw_hash",
            storage_uri="s3://b/raw/f06_raw_hash.pdf",
        )
        session.flush()

        # (1) source_id
        assert art.source_id is not None and art.source_id == source.id
        # (2) parent_artifact_id — NULL for raw is correct/intentional
        assert art.parent_artifact_id is None
        # (3) content_hash
        assert art.content_hash == "f06_raw_hash"
        # (4) pipeline_version
        assert art.pipeline_version and len(art.pipeline_version) > 0
        # (5) storage_uri
        assert art.storage_uri == "s3://b/raw/f06_raw_hash.pdf"
        # (6) created_at
        assert art.created_at is not None

    def test_parsed_all_six_fields_non_null(self, session, source) -> None:
        from knowledge_lake.registry.repo import (
            create_parsed_artifact,
            create_raw_artifact,
        )

        raw = create_raw_artifact(
            session,
            source_id=source.id,
            content_hash="f06_p_raw",
            storage_uri="s3://b/raw/f06_p_raw.pdf",
        )
        parsed = create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash="f06_parsed_hash",
            storage_uri="s3://b/silver/f06_parsed_hash.json",
        )
        session.flush()

        assert parsed.source_id == source.id
        assert parsed.parent_artifact_id == raw.id   # linked to raw
        assert parsed.content_hash == "f06_parsed_hash"
        assert parsed.pipeline_version
        assert parsed.storage_uri
        assert parsed.created_at is not None

    def test_chunk_all_six_fields_non_null(self, session, source) -> None:
        from knowledge_lake.registry.repo import (
            create_chunk_artifact,
            create_parsed_artifact,
            create_raw_artifact,
        )

        raw = create_raw_artifact(
            session,
            source_id=source.id,
            content_hash="f06_c_raw",
            storage_uri="s3://b/raw/f06_c_raw.pdf",
        )
        parsed = create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash="f06_c_parsed",
            storage_uri="s3://b/silver/f06_c_parsed.json",
        )
        chunk = create_chunk_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed.id,
            content_hash="f06_chunk_hash",
            storage_uri="s3://b/silver/f06_chunk_hash.json",
        )
        session.flush()

        assert chunk.source_id == source.id
        assert chunk.parent_artifact_id == parsed.id  # linked to parsed
        assert chunk.content_hash == "f06_chunk_hash"
        assert chunk.pipeline_version
        assert chunk.storage_uri
        assert chunk.created_at is not None


class TestUniqueConstraint:
    """UNIQUE(content_hash, artifact_type) prevents duplicate nodes."""

    def test_duplicate_hash_and_type_raises(self, session, source) -> None:
        """Inserting two raw artifacts with identical hash+type must fail."""
        from knowledge_lake.registry.repo import create_raw_artifact

        create_raw_artifact(
            session,
            source_id=source.id,
            content_hash="dup_hash",
            storage_uri="s3://b/raw/dup_hash.pdf",
        )
        session.flush()

        with pytest.raises((sa_exc.IntegrityError, Exception)):
            create_raw_artifact(
                session,
                source_id=source.id,
                content_hash="dup_hash",   # same hash + same type = violation
                storage_uri="s3://b/raw/dup_hash.pdf",
            )
            session.flush()

    def test_same_hash_different_type_is_allowed(self, session, source) -> None:
        """Same content_hash for different artifact_types must be allowed."""
        from knowledge_lake.registry.repo import (
            create_chunk_artifact,
            create_parsed_artifact,
            create_raw_artifact,
        )

        raw = create_raw_artifact(
            session,
            source_id=source.id,
            content_hash="cross_type_hash",
            storage_uri="s3://b/raw/cross_type_hash.pdf",
        )
        # parsed with same hash (unlikely but schema-permitted)
        parsed = create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash="cross_type_hash",  # same hash, different type
            storage_uri="s3://b/silver/cross_type_hash.json",
        )
        session.flush()
        # If we get here without IntegrityError, the constraint is correct
        assert raw.id != parsed.id
