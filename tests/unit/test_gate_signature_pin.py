"""Gate signature pinning tests (GATE-01, D-05, D-06).

Pins the SHA256 byte-stability of _signature() so Phase 19 pattern extensions
to BOILERPLATE_PATTERNS in clean.py cannot silently change the gate output and
trigger spurious re-crawls of all registered sources.
"""

from __future__ import annotations

import re

from knowledge_lake.pipeline.clean import BOILERPLATE_PATTERNS
from knowledge_lake.pipeline.crawl import _signature

# ── Module-level constants ────────────────────────────────────────────────────

# Fixture that triggers all 4 gate-pattern categories:
#   - "Page 3 of 10"       → page header (pattern 1)
#   - "Skip to main content" → navigation (pattern 3)
#   - "Copyright 2026 HealthOrg. All rights reserved." → copyright (pattern 4)
# (cookie/privacy pattern 2 not present — fixture exercises the other 3)
_FIXTURE: str = (
    "Page 3 of 10\n\n"
    "# Clinical Guidelines for Hypertension Management\n\n"
    "Evidence-based recommendations for care.\n\n"
    "Skip to main content\n\n"
    "Copyright 2026 HealthOrg. All rights reserved.\n"
)

# Pinned hash — computed from the actual Task 1 implementation on 2026-07-16.
# DO NOT change this value without understanding the consequence: changing this
# pin means every source's stored last_content_hash will no longer match and
# ALL sources will be re-crawled on the next scheduled run.
_EXPECTED_HASH: str = "339b473b8b9a5e14768c138521e98259440f384a3b1379814c342b833807f826"


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_gate_signature_byte_stable() -> None:
    """GATE-01: Gate signature must not change when clean.py patterns change. (D-05)"""
    actual = _signature(_FIXTURE)
    assert actual == _EXPECTED_HASH, (
        f"Gate signature changed: stored={_EXPECTED_HASH!r} actual={actual!r}. "
        "A gate signature change means re-crawl of all sources will be triggered. "
        "Update the pin only if the change is intentional and all source hashes "
        "have been reset."
    )


def test_gate_decoupled_from_clean_patterns() -> None:
    """GATE-01: Adding a new pattern to BOILERPLATE_PATTERNS does not change the gate signature. (D-06)

    Simulates Phase 19 extending clean patterns.
    """
    sig_before = _signature(_FIXTURE)
    original_len = len(BOILERPLATE_PATTERNS)

    try:
        # Simulate a Phase 19 extension: append a new pattern to clean.py's list
        BOILERPLATE_PATTERNS.append(
            re.compile(r"(?i)^subscribe to our newsletter[^\n]*$", re.MULTILINE)
        )
        sig_after = _signature(_FIXTURE)
    finally:
        BOILERPLATE_PATTERNS.pop()
        assert len(BOILERPLATE_PATTERNS) == original_len, (
            f"BOILERPLATE_PATTERNS was not restored: "
            f"expected length {original_len}, got {len(BOILERPLATE_PATTERNS)}"
        )

    assert sig_before == sig_after, (
        "Gate signature changed after extending BOILERPLATE_PATTERNS — "
        "gate is still coupled to clean.py. "
        "_signature() must call _gate_normalize() (frozen patterns), "
        "not remove_boilerplate() (evolving patterns)."
    )
