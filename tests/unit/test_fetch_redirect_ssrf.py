"""Tests for _fetch_with_retry redirect-hop SSRF prevention (02-01 Task 1).

Verifies:
    - A 302 redirect to a private/link-local IP raises ValueError before
      the private host is contacted.
    - A normal 200 (no redirect) returns body bytes and content type.
    - Redirect chain cap is enforced.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import httpx
import pytest


class TestFetchRedirectSSRF:
    """Tests that _fetch_with_retry rejects redirects to private IPs."""

    def test_redirect_to_private_ip_rejected(self):
        """A 302 to a private IP must raise ValueError before contacting the private host."""
        from knowledge_lake.pipeline.ingest import _fetch_with_retry

        call_log: list[str] = []

        class MockTransport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                url = str(request.url)
                call_log.append(url)
                if "example.com" in url:
                    # First request -> 302 to a private IP hostname
                    return httpx.Response(
                        status_code=302,
                        headers={"location": "https://internal.evil.com/secret"},
                    )
                # Should NOT reach here
                return httpx.Response(status_code=200, content=b"secret data")

        # Mock getaddrinfo: example.com -> public, internal.evil.com -> private
        def fake_getaddrinfo(host, port, *args, **kwargs):
            if host == "example.com":
                return [(2, 1, 6, "", ("93.184.216.34", 443))]
            elif host == "internal.evil.com":
                return [(2, 1, 6, "", ("169.254.169.254", 443))]
            return [(2, 1, 6, "", ("93.184.216.34", 443))]

        with patch("socket.getaddrinfo", side_effect=fake_getaddrinfo):
            with patch("httpx.Client", return_value=httpx.Client(transport=MockTransport())):
                with pytest.raises(ValueError, match="private|SSRF"):
                    _fetch_with_retry("https://example.com/start")

        # The private host should NOT have been contacted
        assert not any("internal.evil.com" in url for url in call_log), (
            "Private host was contacted — redirect SSRF not prevented"
        )

    def test_redirect_to_rfc1918_rejected(self):
        """A 302 to 10.x.x.x must be rejected."""
        from knowledge_lake.pipeline.ingest import _fetch_with_retry

        def fake_getaddrinfo(host, port, *args, **kwargs):
            if host == "public.example.com":
                return [(2, 1, 6, "", ("93.184.216.34", 443))]
            elif host == "internal.corp":
                return [(2, 1, 6, "", ("10.0.0.5", 443))]
            return [(2, 1, 6, "", ("93.184.216.34", 443))]

        class MockTransport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                if "public.example.com" in str(request.url):
                    return httpx.Response(
                        status_code=301,
                        headers={"location": "https://internal.corp/data"},
                    )
                return httpx.Response(status_code=200, content=b"data")

        with patch("socket.getaddrinfo", side_effect=fake_getaddrinfo):
            with patch("httpx.Client", return_value=httpx.Client(transport=MockTransport())):
                with pytest.raises(ValueError, match="private|SSRF"):
                    _fetch_with_retry("https://public.example.com/resource")

    def test_normal_200_returns_body(self):
        """A normal 200 response (no redirects) returns body bytes and content type."""
        from knowledge_lake.pipeline.ingest import _fetch_with_retry

        expected_body = b"Hello, world! This is a test document."
        expected_ct = "text/html"

        def fake_getaddrinfo(host, port, *args, **kwargs):
            return [(2, 1, 6, "", ("93.184.216.34", 443))]

        class MockTransport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                return httpx.Response(
                    status_code=200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    content=expected_body,
                )

        with patch("socket.getaddrinfo", side_effect=fake_getaddrinfo):
            with patch("httpx.Client", return_value=httpx.Client(transport=MockTransport())):
                body, ct = _fetch_with_retry("https://safe.example.com/page")

        assert body == expected_body
        assert ct == expected_ct

    def test_redirect_chain_cap(self):
        """Exceeding the redirect chain cap raises ValueError."""
        from knowledge_lake.pipeline.ingest import _fetch_with_retry

        redirect_count = [0]

        def fake_getaddrinfo(host, port, *args, **kwargs):
            return [(2, 1, 6, "", ("93.184.216.34", 443))]

        class MockTransport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                redirect_count[0] += 1
                # Always redirect to a new public URL
                return httpx.Response(
                    status_code=302,
                    headers={"location": f"https://safe.example.com/page{redirect_count[0]}"},
                )

        with patch("socket.getaddrinfo", side_effect=fake_getaddrinfo):
            with patch("httpx.Client", return_value=httpx.Client(transport=MockTransport())):
                with pytest.raises(ValueError, match="redirect|too many"):
                    _fetch_with_retry("https://safe.example.com/start")
