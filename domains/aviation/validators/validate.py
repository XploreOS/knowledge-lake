"""Document validator for the aviation domain pack.

Self-contained module — only stdlib imports allowed. No knowledge_lake imports:
this module is loaded dynamically via importlib.util without the package context.

The DomainLoader instantiates the class defined here whose name ends with
"Validator" and which exposes a validate_document() method.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── Aviation identifier / terminology patterns ───────────────────────────────

# N-number (US civil aircraft registration): N followed by 1-5 digits and an
# optional 1-2 letter suffix, e.g. N12345, N1AB.
N_NUMBER_PATTERN = re.compile(r"\bN\d{1,5}[A-Z]{0,2}\b")

# Federal regulation citation, e.g. "14 CFR 91.3" or "14 CFR § 91.3".
CFR_CITATION_PATTERN = re.compile(r"\b\d{1,3}\s*CFR\s*§?\s*\d+(?:\.\d+)?\b")

# Any mention of "CFR" at all (used to detect malformed citations below).
CFR_MENTION_PATTERN = re.compile(r"\bCFR\b")

# Common aviation domain terms — mirrors taxonomy.yaml entity_types plus a
# handful of everyday operational vocabulary.
AVIATION_TERMS = (
    "aircraft",
    "airport",
    "airman",
    "pilot",
    "runway",
    "faa",
    "atc",
    "air traffic",
    "maneuver",
    "regulation",
    "navigation",
    "weather",
    "airspace",
    "certificate",
)
AVIATION_TERM_PATTERN = re.compile(
    "|".join(re.escape(term) for term in AVIATION_TERMS), re.IGNORECASE
)


@dataclass
class ValidationResult:
    """Result from AviationValidator.validate_document()."""

    passed: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class AviationValidator:
    """Validator for aviation documents.

    Checks:
    1. Empty document — fatal (errors, passed=False).
    2. No aviation term or identifier (N-number, CFR citation, domain
       vocabulary) detected anywhere in the text — non-fatal (warning).
    3. A bare "CFR" mention that does not match the standard citation shape
       ("14 CFR 91.3" / "14 CFR § 91.3") — likely a malformed regulation
       reference — non-fatal (warning).
    """

    def validate_document(self, document: dict[str, Any]) -> ValidationResult:
        text: str = document.get("text", "") or ""
        warnings: list[str] = []
        errors: list[str] = []

        # ── Check 1: empty document ────────────────────────────────────────
        if not text.strip():
            errors.append("empty document")
            return ValidationResult(passed=False, warnings=warnings, errors=errors)

        # ── Check 2: no aviation term or identifier detected ──────────────
        has_term = bool(AVIATION_TERM_PATTERN.search(text))
        has_n_number = bool(N_NUMBER_PATTERN.search(text))
        has_cfr_citation = bool(CFR_CITATION_PATTERN.search(text))
        if not (has_term or has_n_number or has_cfr_citation):
            warnings.append("no_aviation_terms_detected")

        # ── Check 3: malformed regulation citation ─────────────────────────
        # A bare "CFR" mention without a matching well-formed citation nearby
        # is likely a truncated or malformed regulation reference.
        if CFR_MENTION_PATTERN.search(text) and not has_cfr_citation:
            warnings.append("malformed_regulation_citation")

        return ValidationResult(passed=len(errors) == 0, warnings=warnings, errors=errors)
