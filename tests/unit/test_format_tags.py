"""
RED-state tests for _format_tags helper (STORE-02). Uses ImportError guard
because _format_tags is not yet defined in s3.py.
"""

from __future__ import annotations

import pytest

try:
    from knowledge_lake.storage.s3 import _format_tags
except ImportError:
    _format_tags = None


@pytest.mark.xfail(strict=False, reason="STORE-02: _format_tags not yet defined in s3.py")
def test_format_tags_produces_urlencode_string():
    """_format_tags encodes a dict to a URL-encoded string (S3 Tagging= format)."""
    if _format_tags is None:
        pytest.skip("_format_tags not yet defined in s3.py")
    result = _format_tags({"domain": "healthcare", "format": "html"})
    assert result == "domain=healthcare&format=html", (
        f"Expected 'domain=healthcare&format=html', got: {result!r}"
    )


@pytest.mark.xfail(strict=False, reason="STORE-02: _format_tags not yet defined in s3.py")
def test_tag_value_truncated_at_256_chars():
    """_format_tags truncates tag values to 256 characters before encoding."""
    if _format_tags is None:
        pytest.skip("_format_tags not yet defined in s3.py")
    long_value = "x" * 300
    result = _format_tags({"key": long_value})
    # Extract the value portion from "key=<value>" and check it's 256 chars
    value_portion = result.split("=", 1)[1]
    assert len(value_portion) == 256, (
        f"Expected value portion to be 256 chars, got: {len(value_portion)}"
    )
