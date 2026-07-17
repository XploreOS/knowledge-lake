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

from knowledge_lake.pipeline.dedup import (
    KLAKE_DEDUP_NAMESPACE,
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
