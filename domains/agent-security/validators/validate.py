"""Document validator for the agent-security domain pack.

Self-contained module — only stdlib imports allowed. No knowledge_lake imports:
this module is loaded dynamically via importlib.util without the package context.

The DomainLoader instantiates the class defined here whose name ends with
"Validator" and which exposes a validate_document() method.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── Agent-security identifier / terminology patterns ────────────────────────

# Permission-scope string, e.g. "read:documents" or "write:tools".
PERMISSION_SCOPE_PATTERN = re.compile(r"\b\w+:\w+\b")

# Tool-call identifier, e.g. "mcp__filesystem__read".
TOOL_IDENTIFIER_PATTERN = re.compile(r"\bmcp__\w+__\w+\b")

# CVSS vector string, e.g. "AV:N/AC:L/PR:N".
CVSS_VECTOR_PATTERN = re.compile(r"\bAV:[NAL]/AC:[LH]/PR:[NLH]\b")

# Any mention of "CVSS" at all (used to detect malformed vectors below).
CVSS_MENTION_PATTERN = re.compile(r"\bCVSS\b")

# Common agent-security domain terms — mirrors taxonomy.yaml entity_types plus
# a handful of everyday operational/threat vocabulary.
AGENT_SECURITY_TERMS = (
    "agent",
    "tool",
    "permission",
    "scope",
    "prompt injection",
    "mcp",
    "oauth",
    "rbac",
    "abac",
    "tool-poisoning",
    "confused deputy",
    "privilege escalation",
    "data exfiltration",
    "threat",
    "mitigation",
    "cvss",
)
AGENT_SECURITY_TERM_PATTERN = re.compile(
    "|".join(re.escape(term) for term in AGENT_SECURITY_TERMS), re.IGNORECASE
)


@dataclass
class ValidationResult:
    """Result from AgentSecurityValidator.validate_document()."""

    passed: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class AgentSecurityValidator:
    """Validator for agent-security documents.

    Checks:
    1. Empty document — fatal (errors, passed=False).
    2. No agent-security term or identifier (domain vocabulary, permission
       scope, tool identifier, CVSS vector) detected anywhere in the text —
       non-fatal (warning).
    3. A bare "CVSS" mention that does not match the standard vector shape
       ("AV:N/AC:L/PR:N") — likely a malformed CVSS reference — non-fatal
       (warning).
    """

    def validate_document(self, document: dict[str, Any]) -> ValidationResult:
        text: str = document.get("text", "") or ""
        warnings: list[str] = []
        errors: list[str] = []

        # ── Check 1: empty document ────────────────────────────────────────
        if not text.strip():
            errors.append("empty document")
            return ValidationResult(passed=False, warnings=warnings, errors=errors)

        # ── Check 2: no agent-security term or identifier detected ────────
        has_term = bool(AGENT_SECURITY_TERM_PATTERN.search(text))
        has_permission_scope = bool(PERMISSION_SCOPE_PATTERN.search(text))
        has_tool_identifier = bool(TOOL_IDENTIFIER_PATTERN.search(text))
        has_cvss_vector = bool(CVSS_VECTOR_PATTERN.search(text))
        if not (has_term or has_permission_scope or has_tool_identifier or has_cvss_vector):
            warnings.append("no_agent_security_terms_detected")

        # ── Check 3: malformed CVSS vector ─────────────────────────────────
        # A bare "CVSS" mention without a matching well-formed vector string
        # nearby is likely a truncated or malformed CVSS reference.
        if CVSS_MENTION_PATTERN.search(text) and not has_cvss_vector:
            warnings.append("malformed_cvss_vector")

        return ValidationResult(passed=len(errors) == 0, warnings=warnings, errors=errors)
