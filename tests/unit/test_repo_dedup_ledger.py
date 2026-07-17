"""Unit tests for registry/repo.py's chunk dedup ledger CRUD (DEDUP-01..03).

Uses a plain in-memory SQLite engine + StaticPool (same harness style as
tests/unit/test_index_payload.py), but calls repo.* functions directly
against a Session(engine) -- no get_session()/get_engine() indirection is
involved here, since these functions take an explicit ``session`` argument.
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from knowledge_lake.registry import repo as registry_repo


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    from knowledge_lake.registry.models import Base

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    with Session(engine) as sess:
        yield sess


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


# ── claim_dedup_ledger_entry ─────────────────────────────────────────────────


def test_claim_fresh_pair_creates_new_primary(session):
    created_at = _now()
    row, is_new_primary = registry_repo.claim_dedup_ledger_entry(
        session,
        collection="klake_chunks",
        text_sha256="abc123",
        point_id="pid-1",
        chunk_id="chk_1",
        parsed_artifact_id="art_1",
        source_id="src_1",
        created_at=created_at,
    )
    session.commit()

    assert is_new_primary is True
    assert row.collection == "klake_chunks"
    assert row.text_sha256 == "abc123"
    assert row.point_id == "pid-1"
    assert row.primary_chunk_id == "chk_1"
    assert row.primary_parsed_artifact_id == "art_1"
    assert row.primary_source_id == "src_1"
    assert row.contributor_count == 1
    assert len(row.contributors) == 1
    assert row.contributors[0] == {
        "chunk_id": "chk_1",
        "document": "art_1",
        "source_id": "src_1",
        "created_at": created_at.isoformat(),
    }
    # Primary is always contributors[0] (D-23)
    assert row.contributors[0]["chunk_id"] == row.primary_chunk_id


def test_claim_second_call_same_key_loses_race(session):
    first_created_at = _now()
    row1, won1 = registry_repo.claim_dedup_ledger_entry(
        session,
        collection="klake_chunks",
        text_sha256="duptext",
        point_id="pid-1",
        chunk_id="chk_1",
        parsed_artifact_id="art_1",
        source_id="src_1",
        created_at=first_created_at,
    )
    session.commit()

    second_created_at = _now()
    row2, won2 = registry_repo.claim_dedup_ledger_entry(
        session,
        collection="klake_chunks",
        text_sha256="duptext",
        point_id="pid-2",
        chunk_id="chk_2",
        parsed_artifact_id="art_2",
        source_id="src_2",
        created_at=second_created_at,
    )
    session.commit()

    assert won1 is True
    assert won2 is False
    # The losing call returns the ORIGINAL row, untouched.
    assert row2.id == row1.id
    assert row2.primary_chunk_id == "chk_1"
    assert row2.primary_parsed_artifact_id == "art_1"
    assert row2.point_id == "pid-1"
    assert len(row2.contributors) == 1
    assert row2.contributors[0]["chunk_id"] == "chk_1"


def test_claim_same_text_different_collection_creates_independent_rows(session):
    created_at = _now()
    row1, won1 = registry_repo.claim_dedup_ledger_entry(
        session,
        collection="klake_chunks",
        text_sha256="sharedtext",
        point_id="pid-1",
        chunk_id="chk_1",
        parsed_artifact_id="art_1",
        source_id="src_1",
        created_at=created_at,
    )
    session.commit()

    row2, won2 = registry_repo.claim_dedup_ledger_entry(
        session,
        collection="klake_chunks_other",
        text_sha256="sharedtext",
        point_id="pid-2",
        chunk_id="chk_2",
        parsed_artifact_id="art_2",
        source_id="src_2",
        created_at=created_at,
    )
    session.commit()

    assert won1 is True
    assert won2 is True
    assert row1.id != row2.id
    assert row1.collection == "klake_chunks"
    assert row2.collection == "klake_chunks_other"


def test_claim_never_branches_on_rowcount():
    import inspect

    source = inspect.getsource(registry_repo.claim_dedup_ledger_entry)
    assert ".rowcount" not in source


# ── get_dedup_ledger_entry ────────────────────────────────────────────────────


def test_get_dedup_ledger_entry_returns_none_for_unclaimed(session):
    result = registry_repo.get_dedup_ledger_entry(
        session, collection="klake_chunks", text_sha256="never-claimed"
    )
    assert result is None


def test_get_dedup_ledger_entry_finds_claimed_row(session):
    created_at = _now()
    row, _ = registry_repo.claim_dedup_ledger_entry(
        session,
        collection="klake_chunks",
        text_sha256="findme",
        point_id="pid-1",
        chunk_id="chk_1",
        parsed_artifact_id="art_1",
        source_id="src_1",
        created_at=created_at,
    )
    session.commit()

    by_text = registry_repo.get_dedup_ledger_entry(
        session, collection="klake_chunks", text_sha256="findme"
    )
    assert by_text is not None
    assert by_text.id == row.id

    by_point = registry_repo.get_dedup_ledger_entry(
        session, collection="klake_chunks", point_id="pid-1"
    )
    assert by_point is not None
    assert by_point.id == row.id


def test_get_dedup_ledger_entry_requires_exactly_one_key(session):
    with pytest.raises(ValueError):
        registry_repo.get_dedup_ledger_entry(session, collection="klake_chunks")

    with pytest.raises(ValueError):
        registry_repo.get_dedup_ledger_entry(
            session,
            collection="klake_chunks",
            text_sha256="a",
            point_id="b",
        )


# ── append_dedup_contributor ──────────────────────────────────────────────────


def test_append_dedup_contributor_appends_and_derives_count(session):
    created_at = _now()
    row, _ = registry_repo.claim_dedup_ledger_entry(
        session,
        collection="klake_chunks",
        text_sha256="appendme",
        point_id="pid-1",
        chunk_id="chk_1",
        parsed_artifact_id="art_1",
        source_id="src_1",
        created_at=created_at,
    )
    session.commit()
    assert row.contributor_count == 1

    second_at = _now()
    registry_repo.append_dedup_contributor(
        session,
        row,
        chunk_id="chk_2",
        document="art_2",
        source_id="src_2",
        created_at=second_at,
    )
    session.commit()

    assert row.contributor_count == 2
    assert len(row.contributors) == 2
    assert row.contributors[1] == {
        "chunk_id": "chk_2",
        "document": "art_2",
        "source_id": "src_2",
        "created_at": second_at.isoformat(),
    }


@pytest.mark.parametrize("n_appends", [1, 2, 5])
def test_append_dedup_contributor_count_never_drifts(session, n_appends):
    created_at = _now()
    row, _ = registry_repo.claim_dedup_ledger_entry(
        session,
        collection="klake_chunks",
        text_sha256=f"drift-{n_appends}",
        point_id="pid-1",
        chunk_id="chk_1",
        parsed_artifact_id="art_1",
        source_id="src_1",
        created_at=created_at,
    )
    session.commit()

    for i in range(n_appends):
        registry_repo.append_dedup_contributor(
            session,
            row,
            chunk_id=f"chk_extra_{i}",
            document=f"art_extra_{i}",
            source_id=f"src_extra_{i}",
            created_at=_now(),
        )
    session.commit()

    assert row.contributor_count == len(row.contributors)
    assert row.contributor_count == 1 + n_appends


def test_append_dedup_contributor_is_idempotent_for_repeated_chunk_id(session):
    """Regression (code review WR-01): reprocessing an already-indexed
    document reuses the same content-hash-derived chunk_id (chunk() is
    itself content-hash idempotent). dedup_chunks() correctly routes that
    rerun's chunk to "duplicates" every time, so index() calls
    append_dedup_contributor with the SAME chunk_id on every rerun. Without
    an idempotency guard, this would double-count the same document as two
    distinct contributors of itself, inflating contributor_count and
    corrupting the ledger's per-document lineage guarantee."""
    created_at = _now()
    row, _ = registry_repo.claim_dedup_ledger_entry(
        session,
        collection="klake_chunks",
        text_sha256="reprocessme",
        point_id="pid-1",
        chunk_id="chk_1",
        parsed_artifact_id="art_1",
        source_id="src_1",
        created_at=created_at,
    )
    session.commit()
    assert row.contributor_count == 1

    # First genuine duplicate: a different document contributing the same text.
    registry_repo.append_dedup_contributor(
        session,
        row,
        chunk_id="chk_2",
        document="art_2",
        source_id="src_2",
        created_at=_now(),
    )
    session.commit()
    assert row.contributor_count == 2

    # Reprocessing doc_1: same chunk_id as the existing primary (chk_1) is
    # "re-appended" — must be a no-op, not a third contributor entry.
    registry_repo.append_dedup_contributor(
        session,
        row,
        chunk_id="chk_1",
        document="art_1",
        source_id="src_1",
        created_at=_now(),
    )
    session.commit()

    assert row.contributor_count == 2, (
        "Re-appending an existing chunk_id must be a no-op — contributor_count "
        "must not inflate when the same document/chunk is reprocessed."
    )
    assert len(row.contributors) == 2
    chunk_ids = [c["chunk_id"] for c in row.contributors]
    assert chunk_ids.count("chk_1") == 1, (
        f"chk_1 must appear exactly once in contributors, got {chunk_ids}"
    )

    # Reprocessing the SECOND contributor's chunk (chk_2) must also be a no-op.
    registry_repo.append_dedup_contributor(
        session,
        row,
        chunk_id="chk_2",
        document="art_2",
        source_id="src_2",
        created_at=_now(),
    )
    session.commit()

    assert row.contributor_count == 2
    assert len(row.contributors) == 2


def test_single_contributor_ledger_row_has_length_one(session):
    """DEDUP-03 trivial boundary case: no duplicate ever arrived."""
    created_at = _now()
    row, _ = registry_repo.claim_dedup_ledger_entry(
        session,
        collection="klake_chunks",
        text_sha256="loneonly",
        point_id="pid-1",
        chunk_id="chk_1",
        parsed_artifact_id="art_1",
        source_id="src_1",
        created_at=created_at,
    )
    session.commit()

    assert len(row.contributors) == 1
    assert row.contributor_count == 1
