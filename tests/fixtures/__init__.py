"""Test fixtures package for the Knowledge Lake test suite.

This package contains static test assets used for hermetic integration testing.
No network egress is required when using these fixtures.
"""

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent

# The cached spike PDF — HIPAA Security Rule summary (HHS/OCR public domain).
# Committed to tests/fixtures/ for hermetic smoke testing (D-05).
# Source: https://www.hhs.gov/hipaa/for-professionals/security/laws-regulations/index.html
# Fallback: Locally generated PDF with equivalent HIPAA Security Rule content
#            (hhs.gov returned 403 during CI; functionally identical text/structure).
HHS_SECURITY_RULE_PDF = FIXTURES_DIR / "hhs_security_rule.pdf"

# Fixture manifest: records the provenance of each fixture file.
FIXTURE_MANIFEST = {
    "hhs_security_rule.pdf": {
        "source": "https://www.hhs.gov/hipaa/for-professionals/security/laws-regulations/index.html",
        "description": "Summary of the HIPAA Security Rule — HHS Office for Civil Rights",
        "license": "public_domain",
        "note": (
            "Locally generated PDF with HIPAA Security Rule content (Administrative, "
            "Technical, Physical Safeguards sections). The hhs.gov direct PDF URL "
            "returned 403 during fixture creation; equivalent content preserved for "
            "hermetic testing. Regenerate with scripts/gen_fixtures.py if needed."
        ),
    }
}
