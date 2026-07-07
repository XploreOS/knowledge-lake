"""Wave 0 test stubs for HealthcareValidator (DOMAIN-03).

All tests are marked xfail until the validator is created in Task 3.
"""

from __future__ import annotations

import pytest

try:
    from knowledge_lake.domains.loader import DomainLoader
    from knowledge_lake.domains.models import ValidationResult
except ImportError:
    DomainLoader = None  # type: ignore[assignment, misc]
    ValidationResult = None  # type: ignore[assignment]

# We also try to load the validator directly for isolated tests
try:
    import importlib.util
    from pathlib import Path

    _VALIDATOR_PATH = Path(__file__).parent.parent.parent / "domains" / "healthcare" / "validators" / "validate.py"
    if _VALIDATOR_PATH.exists():
        _spec = importlib.util.spec_from_file_location("healthcare_validator", str(_VALIDATOR_PATH))
        _mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
        _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
        HealthcareValidator = _mod.HealthcareValidator
        _StandaloneValidationResult = _mod.ValidationResult
    else:
        HealthcareValidator = None  # type: ignore[assignment, misc]
        _StandaloneValidationResult = None  # type: ignore[assignment]
except Exception:
    HealthcareValidator = None  # type: ignore[assignment]
    _StandaloneValidationResult = None  # type: ignore[assignment]


@pytest.mark.xfail(reason="Wave 0 stub — implementation pending")
def test_validate_document_returns_validation_result() -> None:
    """HealthcareValidator().validate_document({'text': 'normal text'}) returns ValidationResult with passed, warnings, errors."""
    assert HealthcareValidator is not None, "HealthcareValidator not yet implemented"
    validator = HealthcareValidator()
    result = validator.validate_document({"text": "normal text without PHI"})
    assert result is not None
    assert hasattr(result, "passed"), "ValidationResult must have 'passed' attribute"
    assert hasattr(result, "warnings"), "ValidationResult must have 'warnings' attribute"
    assert hasattr(result, "errors"), "ValidationResult must have 'errors' attribute"


@pytest.mark.xfail(reason="Wave 0 stub — implementation pending")
def test_validate_document_clinical_code_passes() -> None:
    """Text 'ICD-10 code E11.9' produces passed=True (no unknown coding system)."""
    assert HealthcareValidator is not None
    validator = HealthcareValidator()
    result = validator.validate_document({"text": "ICD-10 code E11.9 diabetes mellitus"})
    assert result.passed is True, f"Expected passed=True for valid ICD-10 code, got passed={result.passed!r}"


@pytest.mark.xfail(reason="Wave 0 stub — implementation pending")
def test_phi_heuristic_triggers_warning() -> None:
    """Text containing PHI triggers warnings containing phi-related item (or passed=False)."""
    assert HealthcareValidator is not None
    validator = HealthcareValidator()
    result = validator.validate_document(
        {"text": "Patient: John Smith DOB: 01/01/1980 SSN 123-45-6789"}
    )
    # PHI heuristic must trigger — either warnings non-empty or passed=False
    phi_triggered = (
        len(result.warnings) > 0
        or result.passed is False
        or any("phi" in w.lower() for w in result.warnings)
    )
    assert phi_triggered, (
        f"PHI heuristic not triggered for text with PHI indicators. "
        f"passed={result.passed!r}, warnings={result.warnings!r}"
    )
    # Also verify that matched text is NOT in warnings (T-06-03: no PHI in logs)
    for warning in result.warnings:
        assert "John Smith" not in warning, "PHI matched text must not appear in warnings"
        assert "123-45-6789" not in warning, "PHI matched text must not appear in warnings"
