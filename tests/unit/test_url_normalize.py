"""Property and table tests for normalize_url and validate_public_url (02-01 Task 1).

Tests:
    - normalize_url is idempotent (hypothesis property)
    - normalize_url preserves query parameter order (hypothesis property)
    - normalize_url table tests for expected transformations
    - validate_public_url rejects non-https, private IPs, IMDS, loopback
    - validate_public_url accepts normal public https URLs
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


# ── normalize_url table tests ────────────────────────────────────────────────


class TestNormalizeUrl:
    """Table-driven tests for normalize_url behaviour."""

    def test_lowercases_scheme_and_host(self):
        from knowledge_lake.pipeline.ingest import normalize_url

        result = normalize_url("HTTPS://Example.COM/path")
        assert result == "https://example.com/path"

    def test_strips_fragment(self):
        from knowledge_lake.pipeline.ingest import normalize_url

        result = normalize_url("https://example.com/page#section")
        assert result == "https://example.com/page"

    def test_strips_trailing_slash(self):
        from knowledge_lake.pipeline.ingest import normalize_url

        result = normalize_url("https://example.com/path/")
        assert result == "https://example.com/path"

    def test_keeps_root_slash(self):
        from knowledge_lake.pipeline.ingest import normalize_url

        result = normalize_url("https://example.com/")
        assert result == "https://example.com/"

    def test_preserves_query_order(self):
        from knowledge_lake.pipeline.ingest import normalize_url

        result = normalize_url("https://example.com/a?b=2&a=1")
        assert result == "https://example.com/a?b=2&a=1"

    def test_preserves_explicit_non_default_port(self):
        from knowledge_lake.pipeline.ingest import normalize_url

        result = normalize_url("https://example.com:8443/path")
        assert result == "https://example.com:8443/path"

    def test_full_normalization(self):
        """The exact example from the acceptance criteria."""
        from knowledge_lake.pipeline.ingest import normalize_url

        result = normalize_url("HTTPS://Example.COM/a/?b=2&a=1#frag")
        assert result == "https://example.com/a?b=2&a=1"

    def test_empty_path(self):
        from knowledge_lake.pipeline.ingest import normalize_url

        result = normalize_url("https://example.com")
        # No path = no trailing slash
        assert result == "https://example.com"


# ── normalize_url hypothesis property tests ──────────────────────────────────


# Strategy for valid https URLs with query strings
_url_strategy = st.builds(
    lambda host, path, query: f"https://{host}{path}{query}",
    host=st.from_regex(r"[a-z]{3,10}\.[a-z]{2,4}", fullmatch=True),
    path=st.from_regex(r"(/[a-z0-9]{1,10}){0,4}", fullmatch=True),
    query=st.from_regex(r"(\?[a-z]=[0-9](&[a-z]=[0-9]){0,3})?", fullmatch=True),
)


class TestNormalizeUrlProperties:
    """Hypothesis property tests for normalize_url."""

    @given(url=_url_strategy)
    @settings(max_examples=200)
    def test_idempotent(self, url: str):
        """normalize_url(normalize_url(u)) == normalize_url(u)."""
        from knowledge_lake.pipeline.ingest import normalize_url

        once = normalize_url(url)
        twice = normalize_url(once)
        assert once == twice, f"Not idempotent: {url!r} -> {once!r} -> {twice!r}"

    @given(
        params=st.lists(
            st.tuples(
                st.from_regex(r"[a-z]{1,5}", fullmatch=True),
                st.from_regex(r"[a-z0-9]{1,5}", fullmatch=True),
            ),
            min_size=2,
            max_size=6,
        )
    )
    @settings(max_examples=100)
    def test_query_order_preserved(self, params: list[tuple[str, str]]):
        """Query parameter order must not be changed (D-06)."""
        from knowledge_lake.pipeline.ingest import normalize_url

        query = "&".join(f"{k}={v}" for k, v in params)
        url = f"https://example.com/p?{query}"
        result = normalize_url(url)
        # The query part of the result must match the input query exactly
        assert f"?{query}" in result


# ── validate_public_url tests ────────────────────────────────────────────────


class TestValidatePublicUrl:
    """Table tests for validate_public_url."""

    def test_rejects_http_scheme(self):
        from knowledge_lake.pipeline.ingest import validate_public_url

        with pytest.raises(ValueError, match="https"):
            validate_public_url("http://example.com/page")

    def test_rejects_ftp_scheme(self):
        from knowledge_lake.pipeline.ingest import validate_public_url

        with pytest.raises(ValueError, match="https"):
            validate_public_url("ftp://example.com/file")

    def test_rejects_private_10x(self):
        from knowledge_lake.pipeline.ingest import validate_public_url

        # Mock getaddrinfo to return a 10.x address
        fake_info = [(2, 1, 6, "", ("10.0.0.1", 443))]
        with patch("socket.getaddrinfo", return_value=fake_info):
            with pytest.raises(ValueError, match="private"):
                validate_public_url("https://evil.example.com/page")

    def test_rejects_imds_169_254(self):
        from knowledge_lake.pipeline.ingest import validate_public_url

        fake_info = [(2, 1, 6, "", ("169.254.169.254", 443))]
        with patch("socket.getaddrinfo", return_value=fake_info):
            with pytest.raises(ValueError, match="private"):
                validate_public_url("https://evil.example.com/metadata")

    def test_rejects_loopback(self):
        from knowledge_lake.pipeline.ingest import validate_public_url

        fake_info = [(2, 1, 6, "", ("127.0.0.1", 443))]
        with patch("socket.getaddrinfo", return_value=fake_info):
            with pytest.raises(ValueError, match="private"):
                validate_public_url("https://evil.example.com/loop")

    def test_accepts_public_url(self):
        from knowledge_lake.pipeline.ingest import validate_public_url

        # Mock getaddrinfo to return a public IP
        fake_info = [(2, 1, 6, "", ("93.184.216.34", 443))]
        with patch("socket.getaddrinfo", return_value=fake_info):
            # Should not raise
            result = validate_public_url("https://example.com/page")
            assert result is None
