"""SearXNG-based source discovery plugin (INGEST-07, D-10).

Implements the DiscoveryPlugin protocol using the SearXNG JSON API.
SearXNG is a self-hosted meta-search engine — no API keys needed.

Security (T-02-23):
    - Query is passed as an httpx params value (httpx URL-encodes it).
    - Never string-formatted into the URL (prevents SSRF/injection).
    - searxng_url is treated as trusted internal config only (injected from Settings).

Error handling (Pitfall 3):
    - A 403 response means the SearXNG instance does not have JSON format enabled.
    - Raises RuntimeError with a clear message directing the operator to enable
      formats: [html, json] in infra/searxng/settings.yml.
"""

from __future__ import annotations

import httpx
import structlog

from knowledge_lake.plugins.protocols import DiscoveryResult

log = structlog.get_logger(__name__)

# Timeout for SearXNG requests (internal service — should respond quickly)
_SEARXNG_TIMEOUT_SECONDS = 15.0


class SearXNGDiscovery:
    """SearXNG discovery plugin — searches via JSON API and returns DiscoveryResults.

    Satisfies the DiscoveryPlugin protocol (runtime_checkable).

    Args:
        searxng_url: Base URL of the SearXNG instance (injected from settings, CR-03).
    """

    name: str = "searxng"

    def __init__(self, searxng_url: str = "http://localhost:8888") -> None:
        self.searxng_url = searxng_url

    def search(self, query: str, limit: int) -> list[DiscoveryResult]:
        """Run a discovery query against SearXNG and return candidate results.

        The query is passed as an httpx params value (T-02-23: never string-formatted
        into the URL). SearXNG responds with a JSON payload containing a 'results'
        list, each with 'url' and optionally 'title'.

        Args:
            query: Natural-language search query.
            limit: Maximum number of results to return.

        Returns:
            List of DiscoveryResult items capped at limit.

        Raises:
            RuntimeError: If SearXNG returns 403 (JSON format not enabled).
            httpx.HTTPStatusError: For other non-2xx responses.
        """
        url = f"{self.searxng_url.rstrip('/')}/search"

        # T-02-23: Pass q as a params value — httpx will URL-encode it.
        # MUST NOT string-format the query into the URL.
        params = {"q": query, "format": "json"}

        log.info(
            "searxng_discovery.search",
            searxng_url=self.searxng_url,
            query=query[:80],
            limit=limit,
        )

        with httpx.Client(timeout=_SEARXNG_TIMEOUT_SECONDS) as client:
            response = client.get(url, params=params)

        # Pitfall 3: A 403 means JSON format is not enabled in SearXNG settings.
        if response.status_code == 403:
            raise RuntimeError(
                f"SearXNG returned 403 Forbidden. The JSON format is likely not enabled. "
                f"Ensure 'search: formats: [html, json]' is set in "
                f"infra/searxng/settings.yml (Pitfall 3). "
                f"URL: {url}"
            )

        # Raise for any other non-2xx status
        response.raise_for_status()

        data = response.json()
        raw_results = data.get("results", [])

        # Cap at limit and parse into DiscoveryResult items
        results: list[DiscoveryResult] = []
        for item in raw_results[:limit]:
            result_url = item.get("url", "")
            title = item.get("title", "")
            if result_url:
                results.append(DiscoveryResult(url=result_url, title=title))

        log.info(
            "searxng_discovery.complete",
            query=query[:80],
            total_raw=len(raw_results),
            returned=len(results),
        )
        return results
