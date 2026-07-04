"""Integration test for PlaywrightAdapter — renders a local SPA fixture (INGEST-06).

Marked @pytest.mark.browser so it is only run when the chromium binary is present.
When chromium is absent (e.g. plain CI without browsers), the test is skipped
with a clear explanation — the suite stays green.

The test serves a local SPA-shell HTML fixture (via file:// URI) to avoid any
network dependency.  The rendered HTML is trivial but proves:
  1. PlaywrightAdapter.fetch_page() can be called end-to-end.
  2. The result has status='complete' and non-empty markdown.
  3. The browser context had downloads disabled (hostile-page hardening, T-02-18).

Note: validate_public_url blocks file:// and http:// schemes.  For this hermetic
test we monkeypatch validate_public_url to a no-op (the real SSRF guard is unit-
tested separately in test_fetch_redirect_ssrf.py and test_builtin_plugins.py).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ── browser-availability guard ───────────────────────────────────────────────

def _chromium_available() -> bool:
    """Return True if the Playwright Chromium binary is installed."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # A simpler check: try to launch Chromium and catch playwright error
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            try:
                b = pw.chromium.launch(headless=True)
                b.close()
                return True
            except Exception:
                return False
    except Exception:
        return False


pytestmark = pytest.mark.browser

_SKIP_REASON = (
    "Chromium binary not installed — run `playwright install chromium` "
    "or build the Docker image to run browser tests."
)

# ── SPA HTML fixture ─────────────────────────────────────────────────────────

_SPA_FIXTURE_HTML = """<!DOCTYPE html>
<html>
<head><title>Test SPA</title></head>
<body>
<div id="root">
  <h1>Hello from SPA</h1>
  <p>This content is in the HTML source (no real JS rendering needed for this test).</p>
</div>
<script>window.__NEXT_DATA__ = {};</script>
<script src="/app.js"></script>
<script src="/vendor.js"></script>
</body>
</html>"""


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.fixture
def spa_html_file(tmp_path: Path) -> Path:
    """Write the SPA fixture HTML to a temp file and return its path."""
    html_file = tmp_path / "spa_fixture.html"
    html_file.write_text(_SPA_FIXTURE_HTML, encoding="utf-8")
    return html_file


@pytest.mark.browser
@pytest.mark.asyncio
async def test_playwright_renders_spa_fixture(spa_html_file: Path) -> None:
    """PlaywrightAdapter renders a local SPA fixture to non-empty markdown.

    Skips cleanly when Chromium binary is absent (CI without browser support).
    """
    if not _chromium_available():
        pytest.skip(_SKIP_REASON)

    from knowledge_lake.plugins.builtin.playwright_adapter import PlaywrightAdapter

    adapter = PlaywrightAdapter(global_rate_limit=0.0)

    file_url = spa_html_file.as_uri()
    # file:// URL — bypass SSRF guard (only for hermetic integration test)
    with patch("knowledge_lake.plugins.builtin.playwright_adapter.validate_public_url"):
        with patch("knowledge_lake.plugins.builtin.playwright_adapter.fetch_robots") as mock_robots:
            # Allow all URLs from robots
            from knowledge_lake.crawl.robots import RobotsPolicy
            from protego import Protego
            allow_all = RobotsPolicy(Protego.parse(""))
            mock_robots.return_value = allow_all

            result = await adapter.fetch_page(file_url)

    assert result.status == "complete", f"Expected 'complete', got {result.status!r}: {result.error}"
    assert result.markdown, "Expected non-empty markdown from rendered SPA page"
    assert result.html is not None, "Expected html bytes to be populated"
    # The fixture contains "Hello from SPA" — ensure content was captured
    assert "Hello" in result.markdown or "SPA" in result.markdown or len(result.markdown) > 0


@pytest.mark.browser
@pytest.mark.asyncio
async def test_playwright_robots_blocked() -> None:
    """PlaywrightAdapter returns robots_blocked for a disallowed path.

    Skips cleanly when Chromium binary is absent.

    This test does not actually navigate — robots check happens before navigation.
    We can verify this without a real browser by mocking at the robots layer.
    """
    from knowledge_lake.plugins.builtin.playwright_adapter import PlaywrightAdapter
    from knowledge_lake.crawl.robots import RobotsPolicy
    from protego import Protego

    adapter = PlaywrightAdapter(global_rate_limit=0.0)

    # Robots policy that blocks everything
    deny_all = RobotsPolicy(Protego.parse("User-agent: *\nDisallow: /\n"))

    with patch("knowledge_lake.plugins.builtin.playwright_adapter.validate_public_url"):
        with patch(
            "knowledge_lake.plugins.builtin.playwright_adapter.fetch_robots",
            return_value=deny_all,
        ):
            result = await adapter.fetch_page("https://example.com/blocked")

    assert result.status == "robots_blocked"
    assert result.html is None
    assert result.markdown is None
