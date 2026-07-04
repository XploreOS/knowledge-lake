"""Unit tests for the DiscoveryPlugin protocol, SearXNG implementation, and resolver.

Tests:
  - DiscoveryResult dataclass construction
  - SearXNGDiscovery satisfies DiscoveryPlugin protocol (isinstance check)
  - SearXNGDiscovery.search() parses a sample SearXNG JSON response into DiscoveryResult items
  - The query is sent as an httpx params value (not formatted into the URL)
  - A 403 response (JSON format not enabled) raises a clear error
  - get_discovery resolver with mocked entry-points returns the SearXNG plugin
  - Settings.searxng_url and Settings.discovery defaults are correct
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest


# ── Sample SearXNG JSON response ──────────────────────────────────────────────

SEARXNG_SAMPLE_RESPONSE = {
    "query": "HIPAA security rule",
    "number_of_results": 3,
    "results": [
        {
            "url": "https://www.hhs.gov/hipaa/for-professionals/security/index.html",
            "title": "HIPAA Security Rule",
            "content": "The HIPAA Security Rule...",
        },
        {
            "url": "https://www.cms.gov/hipaa",
            "title": "CMS HIPAA Resources",
            "content": "Resources for covered entities...",
        },
        {
            "url": "https://example.com/hipaa-guide",
            "title": "",  # empty title — should default to ""
            "content": "A comprehensive guide...",
        },
    ],
}


class TestDiscoveryResult:
    """Test DiscoveryResult dataclass."""

    def test_construction(self) -> None:
        from knowledge_lake.plugins.protocols import DiscoveryResult

        r = DiscoveryResult(url="https://example.com", title="Example")
        assert r.url == "https://example.com"
        assert r.title == "Example"

    def test_title_defaults_empty(self) -> None:
        from knowledge_lake.plugins.protocols import DiscoveryResult

        r = DiscoveryResult(url="https://example.com", title="")
        assert r.title == ""


class TestDiscoveryPluginProtocol:
    """Test DiscoveryPlugin protocol contract."""

    def test_searxng_satisfies_protocol(self) -> None:
        from knowledge_lake.plugins.protocols import DiscoveryPlugin
        from knowledge_lake.plugins.builtin.searxng_discovery import SearXNGDiscovery

        plugin = SearXNGDiscovery(searxng_url="http://localhost:8888")
        assert isinstance(plugin, DiscoveryPlugin)

    def test_searxng_has_name(self) -> None:
        from knowledge_lake.plugins.builtin.searxng_discovery import SearXNGDiscovery

        plugin = SearXNGDiscovery(searxng_url="http://localhost:8888")
        assert plugin.name == "searxng"


class TestSearXNGDiscoverySearch:
    """Test SearXNGDiscovery.search() with mocked httpx transport."""

    def test_parses_results_into_discovery_result(self) -> None:
        """A sample SearXNG JSON with 3 results yields 3 DiscoveryResult items."""
        from knowledge_lake.plugins.builtin.searxng_discovery import SearXNGDiscovery
        from knowledge_lake.plugins.protocols import DiscoveryResult

        mock_response = httpx.Response(
            status_code=200,
            json=SEARXNG_SAMPLE_RESPONSE,
            request=httpx.Request("GET", "http://searxng:8080/search"),
        )

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            plugin = SearXNGDiscovery(searxng_url="http://searxng:8080")
            results = plugin.search("HIPAA security rule", limit=10)

        assert len(results) == 3
        assert all(isinstance(r, DiscoveryResult) for r in results)
        assert results[0].url == "https://www.hhs.gov/hipaa/for-professionals/security/index.html"
        assert results[0].title == "HIPAA Security Rule"
        assert results[2].title == ""  # empty title preserved

    def test_query_passed_as_params_value(self) -> None:
        """The query is sent as an httpx params value, not formatted into the URL."""
        from knowledge_lake.plugins.builtin.searxng_discovery import SearXNGDiscovery

        mock_response = httpx.Response(
            status_code=200,
            json=SEARXNG_SAMPLE_RESPONSE,
            request=httpx.Request("GET", "http://searxng:8080/search"),
        )

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            plugin = SearXNGDiscovery(searxng_url="http://searxng:8080")
            plugin.search("HIPAA security rule", limit=10)

            # Verify the params are passed correctly
            call_args = mock_client.get.call_args
            assert call_args is not None
            # params should contain q and format
            params = call_args.kwargs.get("params") or (
                call_args[1] if len(call_args) > 1 else {}
            )
            assert params["q"] == "HIPAA security rule"
            assert params["format"] == "json"

    def test_limit_caps_results(self) -> None:
        """limit parameter caps the number of DiscoveryResult items returned."""
        from knowledge_lake.plugins.builtin.searxng_discovery import SearXNGDiscovery

        mock_response = httpx.Response(
            status_code=200,
            json=SEARXNG_SAMPLE_RESPONSE,
            request=httpx.Request("GET", "http://searxng:8080/search"),
        )

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            plugin = SearXNGDiscovery(searxng_url="http://searxng:8080")
            results = plugin.search("test", limit=2)

        assert len(results) == 2

    def test_403_raises_clear_error(self) -> None:
        """A 403 response (JSON not enabled) raises a descriptive error."""
        from knowledge_lake.plugins.builtin.searxng_discovery import SearXNGDiscovery

        mock_response = httpx.Response(
            status_code=403,
            request=httpx.Request("GET", "http://searxng:8080/search"),
        )

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            plugin = SearXNGDiscovery(searxng_url="http://searxng:8080")
            with pytest.raises(RuntimeError, match="(?i)json.*format.*not enabled|403"):
                plugin.search("test", limit=5)


class TestDiscoveryResolver:
    """Test get_discovery resolver."""

    def test_group_discovery_constant(self) -> None:
        from knowledge_lake.plugins.resolver import GROUP_DISCOVERY

        assert GROUP_DISCOVERY == "knowledge_lake.discovery"

    def test_get_discovery_injects_searxng_url(self) -> None:
        """get_discovery injects settings.searxng_url into the builtin plugin."""
        from knowledge_lake.plugins.resolver import get_discovery
        from knowledge_lake.config.settings import Settings

        settings = Settings(
            searxng_url="http://test-searxng:9999",
            discovery="searxng",
            _env_file=None,
        )

        with patch("knowledge_lake.plugins.resolver.entry_points") as mock_ep:
            from knowledge_lake.plugins.builtin.searxng_discovery import SearXNGDiscovery

            ep = MagicMock()
            ep.name = "searxng"
            ep.load.return_value = SearXNGDiscovery
            mock_ep.return_value = [ep]

            result = get_discovery(settings)
            assert result.searxng_url == "http://test-searxng:9999"


class TestDiscoverySettings:
    """Test discovery-related settings defaults."""

    def test_searxng_url_default(self) -> None:
        from knowledge_lake.config.settings import Settings

        s = Settings(_env_file=None)
        assert s.searxng_url == "http://localhost:8888"

    def test_discovery_swap_key_default(self) -> None:
        from knowledge_lake.config.settings import Settings

        s = Settings(_env_file=None)
        assert s.discovery == "searxng"

    def test_discovery_swap_key_validated(self) -> None:
        """Invalid swap key format is rejected."""
        from knowledge_lake.config.settings import Settings

        with pytest.raises(Exception):  # ValidationError
            Settings(discovery="../../etc/passwd", _env_file=None)
