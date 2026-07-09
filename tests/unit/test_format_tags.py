"""
Tests for _format_tags helper (STORE-02).
"""

from __future__ import annotations

import pytest

from knowledge_lake.storage.s3 import _format_tags


def test_format_tags_produces_urlencode_string():
    """_format_tags encodes a dict to a URL-encoded string (S3 Tagging= format)."""
    result = _format_tags({"domain": "healthcare", "format": "html"})
    assert result == "domain=healthcare&format=html", (
        f"Expected 'domain=healthcare&format=html', got: {result!r}"
    )


def test_tag_value_truncated_at_256_chars():
    """_format_tags truncates tag values to 256 characters before encoding."""
    long_value = "x" * 300
    result = _format_tags({"key": long_value})
    # Extract the value portion from "key=<value>" and check it's 256 chars
    value_portion = result.split("=", 1)[1]
    assert len(value_portion) == 256, (
        f"Expected value portion to be 256 chars, got: {len(value_portion)}"
    )
