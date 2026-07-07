"""Healthcare document validator for the healthcare domain pack (DOMAIN-03, D-04).

Self-contained module — only stdlib imports allowed (re, typing, dataclasses).
No knowledge_lake imports permitted: this module is loaded dynamically via
importlib.util.spec_from_file_location without the package context (Pitfall 7).

Security requirements:
  - T-06-03: PHI matched text must NEVER appear in logs or warnings.
    Only log phi_gate_triggered=True. Never log the matched span.
  - PHI detection is a keyword heuristic only (not ML) per PROJECT.md:
    "PHI/PII handling — only in explicitly controlled test environments"

Coding patterns recognized:
  - ICD-10-CM: letter + 2 digits + optional decimal + 1-4 digits (e.g. E11.9, A00.0, Z23)
  - LOINC: 1-5 digits + dash + 1 check digit (e.g. 2160-0, 35200-4)
  - NDC: 4-5 digits + dash + 3-4 digits + dash + 1-2 digits (e.g. 0002-7597-01)
  - HCPCS: letter + 4 digits (e.g. G0008, A0428)
  - RxNorm CUI: "RxCUI" followed by optional colon/space then digits (e.g. RxCUI:1049502)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    """Result from HealthcareValidator.validate_document().

    passed=True when no errors exist (warnings are non-fatal).
    passed=False only when errors list is non-empty.
    """

    passed: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ── Clinical coding system patterns ────────────────────────────────────────────

KNOWN_CODING_PATTERNS: dict[str, "re.Pattern[str]"] = {
    "ICD10": re.compile(r"\b[A-Z]\d{2}(?:\.\d{1,4})?\b"),
    "LOINC": re.compile(r"\b\d{1,5}-\d\b"),
    "NDC": re.compile(r"\b\d{4,5}-\d{3,4}-\d{1,2}\b"),
    "HCPCS": re.compile(r"\b[A-Z]\d{4}\b"),
    "RxNorm": re.compile(r"\bRxCUI:?\s*\d+\b"),
}

# ── PHI heuristic patterns (T-06-03) ─────────────────────────────────────────
# These patterns detect POTENTIAL PHI indicators. Matched text is NEVER logged.
# Only phi_gate_triggered=True is surfaced in warnings.

PHI_PATTERNS: list["re.Pattern[str]"] = [
    # Social Security Number: DDD-DD-DDDD
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    # Date of Birth keyword indicator
    re.compile(r"\bDOB\s*:\s*\d"),
    # Patient name pattern: "Patient: Firstname" or "Patient Name: Firstname"
    re.compile(r"\bPatient\s*(?:Name\s*)?:\s*[A-Z][a-z]+"),
    # NPI number: 10-digit number prefixed by "NPI"
    re.compile(r"\bNPI\s*:\s*\d{10}\b"),
]


class HealthcareValidator:
    """Healthcare-specific document validator.

    Checks documents for:
    1. PHI heuristic gate — detects likely Protected Health Information patterns
       using regex heuristics. Adds a warning if triggered but does NOT log
       matched text (T-06-03 — Information Disclosure mitigation).
    2. Clinical coding system references — validates that detected clinical codes
       match known coding system patterns. This is informational, not a failure.

    Usage:
        validator = HealthcareValidator()
        result = validator.validate_document({"text": "E11.9 diabetes mellitus..."})
        if result.warnings:
            print("Warnings:", result.warnings)
    """

    def validate_document(self, document: dict[str, Any]) -> ValidationResult:
        """Validate a document dict for healthcare-specific concerns.

        Args:
            document: Dict containing at minimum a "text" key with the document content.

        Returns:
            ValidationResult(passed, warnings, errors).
            - passed=True when no errors exist (warnings alone do not cause failure).
            - passed=False when errors list is non-empty.
            - PHI heuristic trigger adds to warnings but does not set passed=False.
        """
        text: str = document.get("text", "") or ""
        warnings: list[str] = []
        errors: list[str] = []

        # ── Step 1: PHI heuristic gate (T-06-03) ──────────────────────────────
        # Check for potential PHI indicator patterns.
        # CRITICAL: Only log that PHI was detected (phi_gate_triggered=True).
        # Never include the matched text span in logs or warnings.
        for phi_pattern in PHI_PATTERNS:
            if phi_pattern.search(text):
                warnings.append("phi_gate_triggered=True")
                break  # One warning is sufficient; avoid duplicate phi warnings

        # ── Step 2: Clinical coding system reference check ────────────────────
        # For each recognized coding system, check if codes are present in the text.
        # This is a validation pass (informational) — not a failure condition.
        # We verify that detected code patterns are from known systems, which is
        # always true by construction (KNOWN_CODING_PATTERNS only recognizes them).
        # No errors are generated here unless future validation rules require it.
        _detected_systems: list[str] = []
        for system_name, pattern in KNOWN_CODING_PATTERNS.items():
            if pattern.search(text):
                _detected_systems.append(system_name)
        # _detected_systems is available for future use (e.g., audit logging)
        # but we do not surface it in the result to avoid exposing document content.

        # ── Result ─────────────────────────────────────────────────────────────
        passed = len(errors) == 0
        return ValidationResult(passed=passed, warnings=warnings, errors=errors)
