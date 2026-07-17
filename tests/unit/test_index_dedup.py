"""Pure-function tests for index-time exact dedup (DEDUP-01/02/03).

This is the SAME file RESEARCH.md's Validation Architecture designates for
every DEDUP-01/02/03 unit test in this phase. Later plans (21-04's
dedup_chunks() router tests, 21-05's index() duplicate-routing tests) APPEND
new classes here — they do not replace this file's existing classes.

Deliberately distinct from tests/unit/test_dedup.py, which covers MinHash
near-duplicate detection (CLEAN-03) via pipeline.clean.compute_minhash — a
wholly separate, corpus-wide near-dup concern unrelated to this phase's
exact, index-time dedup key.
"""

from __future__ import annotations

import datetime
import hashlib
import unicodedata
import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.pipeline.index as index_module
import knowledge_lake.registry.db as registry_db
from knowledge_lake.pipeline.dedup import (
    KLAKE_DEDUP_NAMESPACE,
    dedup_chunks,
    normalize_for_dedup,
    point_id_for_text,
    text_sha256_for,
)
from knowledge_lake.registry import repo as registry_repo


class TestNormalizeForDedup:
    """D-01/D-02/D-03: NFKC normalize, whitespace-run collapse, strip — nothing else."""

    def test_collapses_whitespace_runs_and_strips(self) -> None:
        assert normalize_for_dedup("Hello   World\n\n\t") == "Hello World"

    def test_empty_string_normalizes_to_empty(self) -> None:
        assert normalize_for_dedup("") == ""

    def test_whitespace_only_normalizes_to_empty(self) -> None:
        assert normalize_for_dedup("   \n\t  ") == ""

    def test_no_casefolding(self) -> None:
        """D-02: no casefolding — 'WBC' and 'wbc' must remain distinct."""
        assert normalize_for_dedup("WBC") != normalize_for_dedup("wbc")

    def test_nfkc_equivalence_precomposed_vs_decomposed(self) -> None:
        """D-01: a precomposed accented character and its NFKC-equivalent
        decomposed form normalize to the identical string."""
        precomposed = "café"  # "café" with precomposed é (U+00E9)
        decomposed = "café"  # "café" with combining acute accent (U+0301)
        assert precomposed != decomposed  # sanity: byte-different inputs
        assert normalize_for_dedup(precomposed) == normalize_for_dedup(decomposed)
        assert normalize_for_dedup(precomposed) == unicodedata.normalize(
            "NFKC", precomposed
        )


class TestTextSha256For:
    """D-04: hash is computed over UTF-8 encoded bytes of the NORMALIZED string."""

    def test_matches_direct_recomputation(self) -> None:
        for text in ["Hello   World\n\n\t", "WBC", "wbc", "", "   ", "some clinical note text"]:
            expected = hashlib.sha256(
                normalize_for_dedup(text).encode("utf-8")
            ).hexdigest()
            assert text_sha256_for(text) == expected

    def test_different_normalized_text_yields_different_hash(self) -> None:
        assert text_sha256_for("WBC") != text_sha256_for("wbc")

    def test_nfkc_equivalent_text_yields_same_hash(self) -> None:
        precomposed = "café"
        decomposed = "café"
        assert text_sha256_for(precomposed) == text_sha256_for(decomposed)


class TestPointIdForText:
    """D-05/D-06: deterministic uuid5 point-ID derivation from a frozen namespace."""

    def test_namespace_is_frozen_literal(self) -> None:
        assert KLAKE_DEDUP_NAMESPACE == uuid.UUID("94eca03b-54f1-4438-a007-2f835b9d2c07")

    def test_returns_valid_bare_uuid_string(self) -> None:
        point_id = point_id_for_text("some clinical note text")
        assert isinstance(point_id, str)
        assert len(point_id) == 36
        assert str(uuid.UUID(point_id)) == point_id

    def test_deterministic_across_repeated_calls(self) -> None:
        """DEDUP-02: calling twice on identical text yields the identical point_id
        (simulates two separate process_crawled runs)."""
        text = "Patient presents with elevated WBC count."
        first_call = point_id_for_text(text)
        second_call = point_id_for_text(text)
        assert first_call == second_call

    def test_nfkc_equivalent_text_yields_same_point_id(self) -> None:
        precomposed = "café"
        decomposed = "café"
        assert point_id_for_text(precomposed) == point_id_for_text(decomposed)

    def test_case_different_text_yields_different_point_id(self) -> None:
        assert point_id_for_text("WBC") != point_id_for_text("wbc")

    def test_point_id_equality_tracks_sha256_equality(self) -> None:
        """point_id_for_text(a) == point_id_for_text(b) iff
        text_sha256_for(a) == text_sha256_for(b)."""
        pairs = [
            ("café", "café", True),  # NFKC-equivalent -> same
            ("WBC", "wbc", False),  # casing differs -> different
            ("Hello   World\n\n\t", "Hello World", True),  # whitespace-equivalent
        ]
        for text_a, text_b, expect_equal in pairs:
            hashes_equal = text_sha256_for(text_a) == text_sha256_for(text_b)
            ids_equal = point_id_for_text(text_a) == point_id_for_text(text_b)
            assert hashes_equal is expect_equal
            assert ids_equal == hashes_equal

    def test_uses_uuid5_of_sha256_hex_digest(self) -> None:
        text = "some clinical note text"
        expected = str(uuid.uuid5(KLAKE_DEDUP_NAMESPACE, text_sha256_for(text)))
        assert point_id_for_text(text) == expected


# ── TestDedupChunks (Plan 21-04) ──────────────────────────────────────────────
#
# End-to-end router tests against a REAL (SQLite in-memory) ledger, since
# dedup_chunks() calls get_session() internally — mirrors
# tests/unit/test_index_payload.py's engine/_patch_engine harness, not
# tests/unit/test_repo_dedup_ledger.py's direct Session(engine) style.


@pytest.fixture()
def engine():
    """In-memory SQLite engine, shared connection via StaticPool so multiple
    Session() instances (opened by separate get_session() calls inside
    dedup_chunks()) all see the same committed data.
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
    """Route registry.db.get_session() at dedup_chunks()'s call sites to the
    test engine."""
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)


def _chunk(chunk_id: str, text: str) -> dict:
    """Mirrors chunk()'s real per-chunk output shape."""
    return {
        "chunk_id": chunk_id,
        "artifact_id": chunk_id,
        "text": text,
        "section_path": "§1",
        "page": 1,
        "is_table": False,
        "oversized": False,
        "substance_passed": True,
        "rejection_reason": None,
    }


class TestDedupChunks:
    """DEDUP-01/02: dedup_chunks() router — atomic ledger claim, routing,
    annotation, conservation invariant, and cross-call idempotency."""

    def test_empty_input_returns_empty_result_without_opening_session(
        self, monkeypatch
    ) -> None:
        def _raise_if_called():
            raise AssertionError("get_session should not be called for empty input")

        monkeypatch.setattr(registry_db, "get_session", _raise_if_called)

        result = dedup_chunks(
            [], "doc_1", "src_1", collection="klake_chunks"
        )

        assert result == {
            "new": [],
            "duplicates": [],
            "stats": {
                "total": 0,
                "unique": 0,
                "duplicates": 0,
                "collection": "klake_chunks",
                "embed_calls_saved": 0,
            },
        }

    def test_all_distinct_text_routes_to_new_and_annotates_chunks(self) -> None:
        chunks = [
            _chunk("chk_1", "First distinct chunk text."),
            _chunk("chk_2", "Second distinct chunk text."),
            _chunk("chk_3", "Third distinct chunk text."),
        ]

        result = dedup_chunks(
            chunks, "doc_1", "src_1", collection="klake_chunks"
        )

        assert len(result["new"]) == 3
        assert len(result["duplicates"]) == 0
        for chunk in result["new"]:
            assert "text_sha256" in chunk
            assert "point_id" in chunk
        assert result["stats"] == {
            "total": 3,
            "unique": 3,
            "duplicates": 0,
            "collection": "klake_chunks",
            "embed_calls_saved": 0,
        }

    def test_within_batch_duplicate_routes_second_occurrence_to_duplicates(
        self,
    ) -> None:
        chunks = [
            _chunk("chk_1", "Repeated boilerplate text."),
            _chunk("chk_2", "Repeated boilerplate text."),
        ]

        result = dedup_chunks(
            chunks, "doc_1", "src_1", collection="klake_chunks"
        )

        assert len(result["new"]) == 1
        assert len(result["duplicates"]) == 1
        assert result["new"][0]["chunk_id"] == "chk_1"
        assert result["duplicates"][0]["chunk_id"] == "chk_2"
        assert (
            result["new"][0]["point_id"] == result["duplicates"][0]["point_id"]
        )
        assert result["stats"]["embed_calls_saved"] == 1

    def test_cross_call_duplicate_routes_second_document_to_duplicates(
        self,
    ) -> None:
        """Corpus-wide dedup: two SEPARATE dedup_chunks() calls (different
        documents) sharing identical text — the second routes to duplicates."""
        first_result = dedup_chunks(
            [_chunk("chk_1", "Shared boilerplate across documents.")],
            "doc_1",
            "src_1",
            collection="klake_chunks",
        )
        second_result = dedup_chunks(
            [_chunk("chk_2", "Shared boilerplate across documents.")],
            "doc_2",
            "src_2",
            collection="klake_chunks",
        )

        assert len(first_result["new"]) == 1
        assert len(first_result["duplicates"]) == 0
        assert len(second_result["new"]) == 0
        assert len(second_result["duplicates"]) == 1
        assert second_result["duplicates"][0]["chunk_id"] == "chk_2"

    def test_reprocessing_identical_document_is_idempotent(self) -> None:
        """DEDUP-02: re-processing the SAME document (same parsed_artifact_id,
        same chunk text) a second time routes everything to duplicates."""
        chunks = [
            _chunk("chk_1", "Idempotent re-index chunk one."),
            _chunk("chk_2", "Idempotent re-index chunk two."),
        ]

        first_result = dedup_chunks(
            chunks, "doc_1", "src_1", collection="klake_chunks"
        )
        second_result = dedup_chunks(
            chunks, "doc_1", "src_1", collection="klake_chunks"
        )

        assert len(first_result["new"]) == 2
        assert len(first_result["duplicates"]) == 0
        assert len(second_result["new"]) == 0
        assert len(second_result["duplicates"]) == 2

    def test_conservation_invariant_raises_runtime_error_on_violation(self) -> None:
        """_assert_dedup_conservation_invariant raises RuntimeError (never a
        bare assert) when new_count + duplicate_count != total, mirroring
        chunk.py's _assert_chunk_conservation_invariant precedent exactly."""
        from knowledge_lake.pipeline.dedup import (
            _assert_dedup_conservation_invariant,
        )

        with pytest.raises(RuntimeError, match="conservation invariant violated"):
            _assert_dedup_conservation_invariant(
                new_count=1,
                duplicate_count=1,
                total=3,
                parsed_artifact_id="doc_1",
            )

    def test_conservation_invariant_passes_silently_when_balanced(self) -> None:
        from knowledge_lake.pipeline.dedup import (
            _assert_dedup_conservation_invariant,
        )

        # No exception raised.
        _assert_dedup_conservation_invariant(
            new_count=2,
            duplicate_count=1,
            total=3,
            parsed_artifact_id="doc_1",
        )

    def test_dedup_chunks_never_violates_conservation_invariant_in_practice(
        self,
    ) -> None:
        """Regression guard: the real ledger-claim loop, run over a mixed
        batch of distinct/duplicate chunks, never trips the invariant."""
        chunks = [
            _chunk("chk_1", "Alpha text."),
            _chunk("chk_2", "Alpha text."),
            _chunk("chk_3", "Beta text."),
        ]

        result = dedup_chunks(
            chunks, "doc_1", "src_1", collection="klake_chunks"
        )

        assert len(result["new"]) + len(result["duplicates"]) == len(chunks)


# ── TestIndexDuplicateRouting (Plan 21-05) ────────────────────────────────────
#
# index()'s duplicate_chunks kwarg — contributor append, capped/primary-first
# mirror, self-heal. Reuses this file's engine/_patch_engine SQLite harness
# (dedup_chunks()'s and index()'s ledger reads/writes must see the same
# committed data) plus tests/unit/test_index_payload.py's fake_vstore
# MagicMock-based get_vectorstore patching convention.


@pytest.fixture()
def dedup_session(engine):
    with Session(engine) as sess:
        yield sess


@pytest.fixture()
def fake_vstore(monkeypatch):
    """Mock get_vectorstore() so index() never touches a real Qdrant server.

    set_payload defaults to True so tests explicitly opt into the
    False/self-heal path by overriding it.
    """
    vstore = MagicMock()
    vstore.ensure_aliased_collection.return_value = ("klake_chunks_v1", False)
    vstore.set_payload.return_value = True
    monkeypatch.setattr(index_module, "get_vectorstore", lambda _s: vstore)
    return vstore


def _seed_document(session) -> tuple[str, str]:
    """Create a minimal source/raw/parsed artifact chain; returns (source_id, parsed_id)."""
    source = registry_repo.create_source(session, name="Dedup Source", source_type="web")
    raw = registry_repo.create_raw_artifact(
        session,
        source_id=source.id,
        content_hash="dup_raw",
        storage_uri="s3://b/raw/dup_raw.pdf",
    )
    parsed = registry_repo.create_parsed_artifact(
        session,
        source_id=source.id,
        parent_artifact_id=raw.id,
        content_hash="dup_parsed",
        storage_uri="s3://b/silver/dup_parsed.json",
    )
    session.commit()
    return source.id, parsed.id


def _dup_chunk(chunk_id: str, text: str) -> dict:
    """Mirrors dedup_chunks()'s annotated duplicate-chunk output shape."""
    return {
        "chunk_id": chunk_id,
        "text": text,
        "section_path": "§1",
        "page": 1,
        "text_sha256": text_sha256_for(text),
        "point_id": point_id_for_text(text),
    }


class TestIndexDuplicateRouting:
    """DEDUP-03: index()'s duplicate_chunks kwarg — contributor append,
    capped/primary-first mirror, self-heal, and backward compatibility."""

    def test_index_without_duplicate_chunks_unaffected(
        self, dedup_session, fake_vstore
    ) -> None:
        """Backward compatibility: calling index() without duplicate_chunks
        at all behaves identically to before this plan — set_payload is
        never called."""
        _source_id, parsed_id = _seed_document(dedup_session)
        chunks = [
            {"chunk_id": "chk_1", "section_path": "§1", "page": 1, "text": "hello world"}
        ]
        vectors = [[0.1] * 4]

        indexed = index_module.index(chunks, vectors, dim=4, parsed_artifact_id=parsed_id)

        assert indexed == ["chk_1"]
        fake_vstore.set_payload.assert_not_called()
        fake_vstore.upsert.assert_called_once()

    def test_set_payload_called_with_only_contributors_and_count(
        self, dedup_session, fake_vstore
    ) -> None:
        """T-21-11: set_payload is called with ONLY {contributors, contributor_count}
        for a single duplicate — never document/text/quality_score/etc."""
        source_id, parsed_id = _seed_document(dedup_session)
        text = "Repeated boilerplate text."

        registry_repo.claim_dedup_ledger_entry(
            dedup_session,
            collection="klake_chunks",
            text_sha256=text_sha256_for(text),
            point_id=point_id_for_text(text),
            chunk_id="chk_primary",
            parsed_artifact_id=parsed_id,
            source_id=source_id,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        dedup_session.commit()

        dup = _dup_chunk("chk_dup", text)

        index_module.index(
            [], [], dim=4, parsed_artifact_id=parsed_id, duplicate_chunks=[dup]
        )

        fake_vstore.set_payload.assert_called_once()
        collection_arg, point_id_arg, payload_arg = fake_vstore.set_payload.call_args.args
        assert collection_arg == "klake_chunks"
        assert point_id_arg == dup["point_id"]
        assert set(payload_arg.keys()) == {"contributors", "contributor_count"}
        assert payload_arg["contributor_count"] == 2
        assert len(payload_arg["contributors"]) == 2

    def test_contributor_cap_boundary_51_contributors_yields_50_length_mirror(
        self, dedup_session, fake_vstore
    ) -> None:
        """A ledger row with exactly contributor_cap+1 (51) contributors
        produces a Qdrant contributors[] of length 50, with
        contributor_count == 51 (DEDUP-01/03 boundary edge case)."""
        source_id, parsed_id = _seed_document(dedup_session)
        text = "Boundary boilerplate text."
        now = datetime.datetime.now(datetime.UTC)

        ledger_row, _ = registry_repo.claim_dedup_ledger_entry(
            dedup_session,
            collection="klake_chunks",
            text_sha256=text_sha256_for(text),
            point_id=point_id_for_text(text),
            chunk_id="chk_primary",
            parsed_artifact_id=parsed_id,
            source_id=source_id,
            created_at=now,
        )
        # Seed 49 more contributors directly (primary + 49 = 50 total before
        # this test's index() call appends the 51st).
        for i in range(49):
            registry_repo.append_dedup_contributor(
                dedup_session,
                ledger_row,
                chunk_id=f"chk_seed_{i}",
                document=parsed_id,
                source_id=source_id,
                created_at=now + datetime.timedelta(seconds=i + 1),
            )
        dedup_session.commit()
        assert ledger_row.contributor_count == 50

        dup = _dup_chunk("chk_51st", text)
        index_module.index(
            [], [], dim=4, parsed_artifact_id=parsed_id, duplicate_chunks=[dup]
        )

        payload_arg = fake_vstore.set_payload.call_args.args[2]
        assert payload_arg["contributor_count"] == 51
        assert len(payload_arg["contributors"]) == 50

    def test_primary_always_first_even_with_later_primary_timestamp(
        self, dedup_session, fake_vstore
    ) -> None:
        """D-21/D-23: a naive full sort by created_at would place the primary
        LAST if its own timestamp is later than another contributor's — the
        capped mirror must still place it first."""
        source_id, parsed_id = _seed_document(dedup_session)
        text = "Tie-break boilerplate text."
        later = datetime.datetime.now(datetime.UTC)
        earlier = later - datetime.timedelta(hours=1)

        ledger_row, _ = registry_repo.claim_dedup_ledger_entry(
            dedup_session,
            collection="klake_chunks",
            text_sha256=text_sha256_for(text),
            point_id=point_id_for_text(text),
            chunk_id="chk_primary",
            parsed_artifact_id=parsed_id,
            source_id=source_id,
            created_at=later,  # primary's own timestamp is the LATEST
        )
        registry_repo.append_dedup_contributor(
            dedup_session,
            ledger_row,
            chunk_id="chk_earlier",
            document=parsed_id,
            source_id=source_id,
            created_at=earlier,  # earlier than the primary
        )
        dedup_session.commit()

        dup = _dup_chunk("chk_dup", text)
        index_module.index(
            [], [], dim=4, parsed_artifact_id=parsed_id, duplicate_chunks=[dup]
        )

        payload_arg = fake_vstore.set_payload.call_args.args[2]
        assert payload_arg["contributors"][0]["chunk_id"] == "chk_primary"

    def test_new_chunk_payload_filterable_fields_unaffected(
        self, dedup_session, fake_vstore
    ) -> None:
        """PAYLOAD-01/02: a 'new' chunk's payload (unaffected by this plan)
        still contains all pre-existing source-metadata/domain/format
        fields, proving _resolve_document_payload_fields is unmodified."""
        source = registry_repo.create_source(
            dedup_session,
            name="Filter Source",
            source_type="html",
            config={"domain": "healthcare", "tags": ["t1"]},
        )
        raw = registry_repo.create_raw_artifact(
            dedup_session,
            source_id=source.id,
            content_hash="filt_raw",
            storage_uri="s3://b/raw/filt_raw.pdf",
        )
        parsed = registry_repo.create_parsed_artifact(
            dedup_session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash="filt_parsed",
            storage_uri="s3://b/silver/filt_parsed.json",
        )
        dedup_session.commit()

        chunks = [{"chunk_id": "chk_1", "section_path": "§1", "page": 1, "text": "hello"}]
        index_module.index(chunks, [[0.1] * 4], dim=4, parsed_artifact_id=parsed.id)

        upsert_call = fake_vstore.upsert.call_args
        points = upsert_call.args[1]
        payload = points[0].payload
        assert payload["domain"] == "healthcare"
        assert payload["source_id"] == source.id
        assert payload["format"] == "html"
        assert payload["tags"] == ["t1"]

    def test_self_heal_on_vanished_point_reembeds_and_repairs_ledger(
        self, dedup_session, fake_vstore, monkeypatch, engine
    ) -> None:
        """T-21-10/D-24: set_payload returning False triggers a fresh
        embed()+upsert() under the SAME point_id, and repairs the ledger
        row's primary_chunk_id/primary_parsed_artifact_id/primary_source_id/
        primary_created_at to reflect the now-current (healed) chunk."""
        source_id, parsed_id = _seed_document(dedup_session)
        text = "Vanished point boilerplate text."

        registry_repo.claim_dedup_ledger_entry(
            dedup_session,
            collection="klake_chunks",
            text_sha256=text_sha256_for(text),
            point_id=point_id_for_text(text),
            chunk_id="chk_primary",
            parsed_artifact_id=parsed_id,
            source_id=source_id,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        dedup_session.commit()

        fake_vstore.set_payload.return_value = False

        fake_embed = MagicMock(return_value=([[0.2, 0.2, 0.2, 0.2]], 4))
        monkeypatch.setattr("knowledge_lake.pipeline.embed.embed", fake_embed)

        dup = _dup_chunk("chk_healed", text)
        index_module.index(
            [], [], dim=4, parsed_artifact_id=parsed_id, duplicate_chunks=[dup]
        )

        # Only the healed-points upsert runs (no "new" chunks in this call).
        fake_vstore.upsert.assert_called_once()
        healed_points = fake_vstore.upsert.call_args.args[1]
        assert len(healed_points) == 1
        assert healed_points[0].id == dup["point_id"]

        # Ledger row is repaired to point at the now-current (healed) chunk.
        with Session(engine) as verify_session:
            refreshed = registry_repo.get_dedup_ledger_entry(
                verify_session,
                collection="klake_chunks",
                text_sha256=text_sha256_for(text),
            )
            assert refreshed.primary_chunk_id == "chk_healed"
            assert refreshed.primary_parsed_artifact_id == parsed_id
            assert refreshed.primary_source_id == source_id
