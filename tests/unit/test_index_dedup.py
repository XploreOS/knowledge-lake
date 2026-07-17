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

import hashlib
import unicodedata
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import knowledge_lake.registry.db as registry_db
from knowledge_lake.pipeline.dedup import (
    KLAKE_DEDUP_NAMESPACE,
    dedup_chunks,
    normalize_for_dedup,
    point_id_for_text,
    text_sha256_for,
)


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
