"""Tests for pipeline/quality/ pure predicate module (QUAL-01).

Covers every branch of the 7 check_* predicates, run_predicates()'s three
termination paths (including an explicit ordering/determinism test), and
compute_substance_signals()'s empty/non-empty branches. Also asserts the
zero-I/O contract: importing knowledge_lake.pipeline.quality must never pull
sqlalchemy, boto3, or dagster into sys.modules.
"""

from __future__ import annotations

import subprocess
import sys

from knowledge_lake.pipeline.quality import (
    PredicateResult,
    check_alpha_ratio,
    check_domain_allowlist,
    check_link_density,
    check_stopword_ratio,
    check_table_exemption,
    check_terminal_punct_ratio,
    check_token_floor,
    compute_substance_signals,
    run_predicates,
)

# ── Import boundary (QUAL-01 zero-I/O contract) ─────────────────────────────


def test_import_does_not_pull_in_sqlalchemy_boto3_dagster() -> None:
    # Run in a fresh subprocess rather than checking sys.modules in-process:
    # this test suite's own tests/conftest.py has an autouse fixture
    # (_clear_settings_cache) that imports knowledge_lake.registry.db (and
    # therefore sqlalchemy) before EVERY test body runs, including this one
    # — so an in-process sys.modules check would always see sqlalchemy
    # already loaded regardless of what pipeline.quality itself does. A
    # subprocess with no conftest.py involved isolates the actual claim:
    # importing knowledge_lake.pipeline.quality alone must not transitively
    # import sqlalchemy, boto3, or dagster.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import knowledge_lake.pipeline.quality; "
            "mods = {m.split('.')[0] for m in sys.modules}; "
            "forbidden = {'sqlalchemy', 'boto3', 'dagster'} & mods; "
            "assert not forbidden, forbidden",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


# ── check_token_floor ────────────────────────────────────────────────────────


def test_check_token_floor_passes_at_exact_boundary() -> None:
    # "Real content." is exactly 3 tiktoken tokens — 3 is not < 3.
    result = check_token_floor("Real content.", {})
    assert result == PredicateResult(True, "token_floor_ok")


def test_check_token_floor_fails_below_floor() -> None:
    result = check_token_floor("", {})
    assert result.passed is False
    assert result.reason == "below_token_floor:0<3"


def test_check_token_floor_respects_custom_min_tokens() -> None:
    result = check_token_floor("Real content.", {}, min_tokens=10)
    assert result.passed is False
    assert "below_token_floor" in result.reason


# ── check_alpha_ratio ────────────────────────────────────────────────────────


def test_check_alpha_ratio_empty_text() -> None:
    result = check_alpha_ratio("", {})
    assert result == PredicateResult(False, "empty_text")


def test_check_alpha_ratio_all_digits_fails() -> None:
    result = check_alpha_ratio("12345", {})
    assert result.passed is False
    assert "below_alpha_ratio" in result.reason


def test_check_alpha_ratio_prose_passes() -> None:
    result = check_alpha_ratio("Real content.", {})
    assert result == PredicateResult(True, "alpha_ratio_ok")


# ── check_link_density ───────────────────────────────────────────────────────


def test_check_link_density_insufficient_sample_size() -> None:
    result = check_link_density("too few words", {})
    assert result == PredicateResult(True, "insufficient_sample_size")


def test_check_link_density_high_density_fails() -> None:
    text = (
        "[a](http://x.com) [b](http://x.com) [c](http://x.com) "
        "[d](http://x.com) [e](http://x.com) word word word word word"
    )
    result = check_link_density(text, {})
    assert result.passed is False
    assert "above_link_density" in result.reason


def test_check_link_density_no_links_passes() -> None:
    text = "This is a plain prose sentence with exactly ten words total here"
    result = check_link_density(text, {})
    assert result == PredicateResult(True, "link_density_ok")


# ── check_stopword_ratio ─────────────────────────────────────────────────────


def test_check_stopword_ratio_insufficient_sample_size() -> None:
    result = check_stopword_ratio("too few words", {})
    assert result == PredicateResult(True, "insufficient_sample_size")


def test_check_stopword_ratio_nav_line_fails() -> None:
    text = "Home About Us Contact Sitemap Search Toggle Navigation Back Top"
    result = check_stopword_ratio(text, {})
    assert result.passed is False
    assert "below_stopword_ratio" in result.reason


def test_check_stopword_ratio_real_prose_passes() -> None:
    text = (
        "The patient was seen and evaluated for a condition related to "
        "the ongoing treatment of their diagnosis and prescribed medication"
    )
    result = check_stopword_ratio(text, {})
    assert result == PredicateResult(True, "stopword_ratio_ok")


# ── check_terminal_punct_ratio ───────────────────────────────────────────────


def test_check_terminal_punct_ratio_insufficient_sample_size() -> None:
    result = check_terminal_punct_ratio("too few words", {})
    assert result == PredicateResult(True, "insufficient_sample_size")


def test_check_terminal_punct_ratio_no_punctuation_fails() -> None:
    text = "word word word word word word word word word word word word"
    result = check_terminal_punct_ratio(text, {})
    assert result.passed is False
    assert "below_terminal_punct_ratio" in result.reason


def test_check_terminal_punct_ratio_real_prose_passes() -> None:
    text = (
        "This is a sentence. It has proper terminal punctuation. "
        "Here is another one. And a fourth sentence here too."
    )
    result = check_terminal_punct_ratio(text, {})
    assert result == PredicateResult(True, "terminal_punct_ratio_ok")


# ── check_table_exemption ─────────────────────────────────────────────────────


def test_check_table_exemption_true_when_is_table_set() -> None:
    result = check_table_exemption("anything", {"is_table": True})
    assert result == PredicateResult(True, "table_exempt")


def test_check_table_exemption_false_when_not_table() -> None:
    result = check_table_exemption("anything", {})
    assert result == PredicateResult(False, "not_table")


# ── check_domain_allowlist ────────────────────────────────────────────────────


def test_check_domain_allowlist_none_patterns_falls_through() -> None:
    result = check_domain_allowlist("anything", {}, allowlist_patterns=None)
    assert result == PredicateResult(False, "no_allowlist_match")


def test_check_domain_allowlist_matching_pattern() -> None:
    result = check_domain_allowlist(
        "ICD-10 E11.9", {}, allowlist_patterns=["ICD-10"]
    )
    assert result == PredicateResult(True, "domain_allowlist_match:ICD-10")


def test_check_domain_allowlist_non_matching_pattern() -> None:
    result = check_domain_allowlist(
        "just prose", {}, allowlist_patterns=["ICD-10"]
    )
    assert result == PredicateResult(False, "no_allowlist_match")


# ── compute_substance_signals ─────────────────────────────────────────────────


def test_compute_substance_signals_empty_text() -> None:
    signals = compute_substance_signals("")
    assert signals == {
        "token_count": 0,
        "link_density": 0.0,
        "terminal_punct_ratio": 0.0,
        "stopword_ratio": 0.0,
    }


def test_compute_substance_signals_non_empty_text() -> None:
    signals = compute_substance_signals("The patient has a condition.")
    assert signals["token_count"] > 0
    assert signals["link_density"] == 0.0
    assert signals["terminal_punct_ratio"] > 0.0
    assert signals["stopword_ratio"] > 0.0


# ── run_predicates ────────────────────────────────────────────────────────────


def test_run_predicates_exemption_short_circuits_before_threshold_fails() -> None:
    result = run_predicates(
        "", {"is_table": True}, [check_table_exemption, check_token_floor]
    )
    assert result == PredicateResult(True, "table_exempt")


def test_run_predicates_threshold_fail_short_circuits() -> None:
    result = run_predicates("", {}, [check_token_floor, check_alpha_ratio])
    assert result.passed is False
    assert "below_token_floor" in result.reason


def test_run_predicates_full_pass_fallthrough() -> None:
    result = run_predicates(
        "Real content.", {}, [check_token_floor, check_alpha_ratio]
    )
    assert result == PredicateResult(True, "all_checks_passed")


def test_run_predicates_ordering_determinism_a_first() -> None:
    # Both check_token_floor (A) and check_alpha_ratio (B) fail on "12345"
    # (5 tokens... actually need both to fail: use a short numeric string).
    text = "123"
    result = run_predicates(text, {}, [check_token_floor, check_alpha_ratio])
    # check_token_floor fails first when listed first.
    assert "below_token_floor" in result.reason


def test_run_predicates_ordering_determinism_b_first() -> None:
    text = "123"
    result = run_predicates(text, {}, [check_alpha_ratio, check_token_floor])
    # check_alpha_ratio fails first when listed first (reversed order).
    assert "below_alpha_ratio" in result.reason


def test_run_predicates_exemption_predicate_fails_then_threshold_runs() -> None:
    # check_table_exemption fails (not a table) -> not an early return since
    # exemption failure isn't gated; loop continues to check_token_floor.
    result = run_predicates(
        "", {}, [check_table_exemption, check_token_floor]
    )
    assert result.passed is False
    assert "below_token_floor" in result.reason
