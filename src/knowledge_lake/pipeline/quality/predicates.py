"""Pure quality predicate functions for section/chunk substance gating (QUAL-01).

Every predicate is a standalone function of the shape
``f(text: str, metadata: dict) -> PredicateResult(passed, reason)`` with zero
dependencies on I/O, S3, Dagster, or ``knowledge_lake.config.settings`` — this
module is independently importable and testable with no infrastructure.

Design resolution (CONTEXT.md D-11 vs this module): D-11 names six predicates
(``check_token_floor``, ``check_alpha_ratio``, ``check_link_density``,
``check_stopword_ratio``, ``check_table_exemption``, ``check_domain_allowlist``).
This module adds a seventh, ``check_terminal_punct_ratio``, to satisfy D-03's
explicit "low token_count + low terminal_punct_ratio + high link_density"
substance-threshold description — D-11's "Predicates include:" phrasing is
read as non-exhaustive, not a closed set.

Exemption predicates (``check_table_exemption``, ``check_domain_allowlist``)
are unconditional overrides: if either passes, ``run_predicates()`` returns
success immediately regardless of any other predicate's outcome. Callers MUST
place exemption predicates FIRST in the list passed to ``run_predicates()`` so
an exemption match short-circuits before any threshold predicate ever runs
(mirrors 17/18-RESEARCH.md's Pitfall-3-style ordering discipline). Note that
``run_predicates()`` allows exemption predicates to run after a threshold
predicate has already failed and returned — order matters for *which*
predicates get evaluated, not for correctness of any single predicate.

IMPORTANT — allowlist protection is opt-in, not automatic: ``run_predicates()``
never adds ``check_domain_allowlist`` to the predicate list on its own. Every
caller (``classify_sections()`` in Plan 19-04, and Phase 20's chunk substance
gate) is responsible for including it explicitly if allowlist protection is
desired for that call site.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from knowledge_lake.pipeline.quality.constants import (
    STOP_WORDS_SET,
    TERMINAL_PUNCTUATION_SET,
    _LINK_PATTERN,
    token_count,
)

# ── Result type ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PredicateResult:
    """Outcome of a single quality predicate evaluation."""

    passed: bool
    """True if the text passed this predicate's check."""

    reason: str
    """Machine-readable reason code (e.g. "below_token_floor:2<3")."""


# ── Tunable defaults ─────────────────────────────────────────────────────────

DEFAULT_MIN_TOKENS = 3
DEFAULT_MIN_ALPHA_RATIO = 0.5
DEFAULT_MAX_LINK_DENSITY = 0.3
DEFAULT_MIN_STOPWORD_RATIO = 0.05
DEFAULT_MIN_TERMINAL_PUNCT_RATIO = 0.02

# Below this word count, ratio-based checks are statistically unreliable on
# DataTrove's 8-word STOP_WORDS list and must PASS by default rather than fail.
_MIN_SAMPLE_WORDS = 6


# ── Predicates ───────────────────────────────────────────────────────────────


def check_token_floor(
    text: str,
    metadata: dict,
    *,
    min_tokens: int = DEFAULT_MIN_TOKENS,
) -> PredicateResult:
    """Fail if ``text`` has fewer than ``min_tokens`` cl100k_base tokens."""
    count = token_count(text)
    if count < min_tokens:
        return PredicateResult(False, f"below_token_floor:{count}<{min_tokens}")
    return PredicateResult(True, "token_floor_ok")


def check_alpha_ratio(
    text: str,
    metadata: dict,
    *,
    min_ratio: float = DEFAULT_MIN_ALPHA_RATIO,
) -> PredicateResult:
    """Fail if the ratio of alphabetic to non-whitespace characters is too low."""
    non_ws = [c for c in text if not c.isspace()]
    if not non_ws:
        return PredicateResult(False, "empty_text")
    ratio = sum(c.isalpha() for c in non_ws) / len(non_ws)
    if ratio < min_ratio:
        return PredicateResult(False, f"below_alpha_ratio:{ratio:.2f}<{min_ratio}")
    return PredicateResult(True, "alpha_ratio_ok")


def check_link_density(
    text: str,
    metadata: dict,
    *,
    max_density: float = DEFAULT_MAX_LINK_DENSITY,
    min_sample_words: int = _MIN_SAMPLE_WORDS,
) -> PredicateResult:
    """Fail if the ratio of link matches to words exceeds ``max_density``."""
    words = text.split()
    if len(words) < min_sample_words:
        return PredicateResult(True, "insufficient_sample_size")
    density = len(_LINK_PATTERN.findall(text)) / len(words)
    if density > max_density:
        return PredicateResult(False, f"above_link_density:{density:.2f}>{max_density}")
    return PredicateResult(True, "link_density_ok")


def check_stopword_ratio(
    text: str,
    metadata: dict,
    *,
    min_ratio: float = DEFAULT_MIN_STOPWORD_RATIO,
    min_sample_words: int = _MIN_SAMPLE_WORDS,
) -> PredicateResult:
    """Fail if the ratio of stopwords to words is too low (nav/boilerplate signal)."""
    words = text.lower().split()
    if len(words) < min_sample_words:
        return PredicateResult(True, "insufficient_sample_size")
    ratio = sum(1 for w in words if w in STOP_WORDS_SET) / len(words)
    if ratio < min_ratio:
        return PredicateResult(False, f"below_stopword_ratio:{ratio:.2f}<{min_ratio}")
    return PredicateResult(True, "stopword_ratio_ok")


def check_terminal_punct_ratio(
    text: str,
    metadata: dict,
    *,
    min_ratio: float = DEFAULT_MIN_TERMINAL_PUNCT_RATIO,
    min_sample_words: int = _MIN_SAMPLE_WORDS,
) -> PredicateResult:
    """Fail if the ratio of terminal punctuation marks to words is too low."""
    words = text.split()
    if len(words) < min_sample_words:
        return PredicateResult(True, "insufficient_sample_size")
    ratio = sum(1 for c in text if c in TERMINAL_PUNCTUATION_SET) / len(words)
    if ratio < min_ratio:
        return PredicateResult(
            False, f"below_terminal_punct_ratio:{ratio:.2f}<{min_ratio}"
        )
    return PredicateResult(True, "terminal_punct_ratio_ok")


def check_table_exemption(text: str, metadata: dict) -> PredicateResult:
    """Exempt the text if ``metadata["is_table"]`` is truthy.

    EXEMPTION predicate — a ``passed=False`` result is expected/normal for
    non-table sections, not an error.

    KNOWN GAP (RESEARCH.md Pitfall 2, flagged not fixed): no builtin parser
    (docling_parser.py, tika_parser.py, unstructured_parser.py,
    json_xml_parser.py) currently ever sets ``Section.is_table=True``, so this
    predicate is forward-looking infrastructure for real-world Docling-parsed
    documents today, not an effective safety net. Build it exactly as
    specified anyway — it protects any future parser/format that does set the
    flag, and Phase 20 may also consume it — but do not treat it as
    sufficient protection for tabular clinical content; the domain allowlist
    (``check_domain_allowlist``, wired in Plan 19-02/19-04) is the actual
    safety net today. This parser-level gap is out of this phase's scope to
    fix (CLEAN-04/05/06/QUAL-01 make no parser changes).
    """
    if metadata.get("is_table"):
        return PredicateResult(True, "table_exempt")
    return PredicateResult(False, "not_table")


def check_domain_allowlist(
    text: str,
    metadata: dict,
    *,
    allowlist_patterns: list[str] | None = None,
) -> PredicateResult:
    """Exempt the text if it matches any of ``allowlist_patterns``.

    EXEMPTION predicate — a ``passed=False`` result (no allowlist match, or no
    patterns supplied) is expected/normal, not an error.

    Allowlist protection is OPT-IN PER CALLER: ``run_predicates()`` never
    auto-includes this predicate. Callers (``classify_sections()`` in Plan
    19-04, and Phase 20's chunk substance gate) must place it in their own
    predicate list explicitly for allowlist protection to have any effect.
    """
    for pattern in allowlist_patterns or []:
        if re.search(pattern, text):
            return PredicateResult(True, f"domain_allowlist_match:{pattern}")
    return PredicateResult(False, "no_allowlist_match")


# ── Substance signal computation (non-gating) ───────────────────────────────


def compute_substance_signals(text: str) -> dict:
    """Return the raw CLEAN-04 substance annotation signals for ``text``.

    Always returns well-defined values (never raises on empty text) and NEVER
    gates pass/fail — independent of any predicate threshold, intended for
    persistence in clean.py's ``section_annotations`` (Plan 19-04).
    """
    words = text.split()
    word_count = len(words)
    link_count = len(_LINK_PATTERN.findall(text))
    terminal_count = sum(1 for c in text if c in TERMINAL_PUNCTUATION_SET)
    stopword_count = sum(1 for w in text.lower().split() if w in STOP_WORDS_SET)
    return {
        "token_count": token_count(text),
        "link_density": link_count / word_count if word_count else 0.0,
        "terminal_punct_ratio": terminal_count / word_count if word_count else 0.0,
        "stopword_ratio": stopword_count / word_count if word_count else 0.0,
    }


# ── Combinator ───────────────────────────────────────────────────────────────

_EXEMPTION_PREDICATES = {check_table_exemption, check_domain_allowlist}


def run_predicates(
    text: str,
    metadata: dict,
    predicates: list[Callable[..., PredicateResult]],
) -> PredicateResult:
    """Evaluate ``predicates`` in list order, never reordered/sorted.

    For each predicate, in the exact order given:
      - If it is an EXEMPTION predicate (``check_table_exemption`` or
        ``check_domain_allowlist``) and it passed, return
        ``PredicateResult(True, result.reason)`` immediately — an exemption
        match unconditionally overrides any prior or subsequent predicate.
      - If it is not an exemption predicate and it failed, return
        ``PredicateResult(False, result.reason)`` immediately — the first
        failing threshold predicate wins.
      - Otherwise continue to the next predicate.

    If every predicate is evaluated without returning, all thresholds passed
    (or were exempted-but-failed, e.g. "not_table"/"no_allowlist_match" for a
    section that isn't otherwise rejected) — returns
    ``PredicateResult(True, "all_checks_passed")``.

    Ordering discipline (caller responsibility): place exemption predicates
    FIRST in ``predicates`` so an exemption match short-circuits before any
    threshold predicate runs. ``run_predicates`` itself is order-agnostic —
    it evaluates whatever order it's given — but callers must place
    exemptions first for the override semantics to take effect before a
    threshold failure would otherwise return early.
    """
    for predicate in predicates:
        result = predicate(text, metadata)
        if predicate in _EXEMPTION_PREDICATES and result.passed:
            return PredicateResult(True, result.reason)
        if predicate not in _EXEMPTION_PREDICATES and not result.passed:
            return PredicateResult(False, result.reason)
    return PredicateResult(True, "all_checks_passed")
